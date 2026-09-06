using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Concurrent;
using UnityEngine;

/*
===============================================================================
Go1TwinUDP.cs
-------------------------------------------------------------------------------
GO1 디지털 트윈용 상태(JSON) UDP 수신기 (SDK PC -> Unity)
- UdpClient.ReceiveAsync() 기반 비동기 수신(Task)
- 백그라운드에서 JSON 파싱
- Unity 메인 스레드에서만 필드 갱신(ConcurrentQueue<Action> 사용)
- OnEnable/OnDisable 생명주기에 맞춰 안전하게 시작/종료

[개요]
외부(예: SDK PC)가 주기적으로 송신하는 GO1 상태를 JSON 형태로 수신하여
Unity 내부 필드(vx, vy, wz, q[])에 저장한다.

이 스크립트는 "상태를 받아 저장"하는 역할만 하며,
받은 값으로 Transform/애니메이션을 적용하는 것은
다른 드라이버(예: Go1WASDLegacyDrive, Go1StateAnimationDriver)가 담당할 수 있다.

-------------------------------------------------------------------------------
[수신 데이터(JSON) 포맷]

Go1StateMsg:
{
  "rpy": [roll, pitch, yaw],   // 옵션
  "q":   [ ... 12개 관절 값 ... ],
  "vx":  0.1,
  "vy":  0.0,
  "wz":  0.02,
  "estop": 0
}

- vx, vy, wz : 속도/각속도 (트윈 애니메이션/디버그 등에 사용)
- q[12]      : 관절/모터 값 (모델 관절 구동에 사용 가능)
- rpy        : 자세 각도 (옵션, 현재 코드는 저장만 가능)
- estop      : 비상정지 (현재 코드는 저장만 가능)

-------------------------------------------------------------------------------
[왜 메인 스레드 작업 큐가 필요한가?]

Unity는 대부분의 API(Transform, GameObject, Component 등)를
메인 스레드에서만 안전하게 호출할 수 있다.

이 스크립트는 UDP 수신/파싱을 백그라운드(Task)에서 처리하고,
"Unity 필드 갱신"은 _mainThreadJobs 큐에 Action으로 넣어
Update()에서 메인 스레드로 실행한다.

-------------------------------------------------------------------------------
[동작 흐름]

OnEnable()
  → StartReceiver(): UDP 바인드 + CancellationTokenSource 생성 + RxLoop Task 시작

RxLoop(ct)
  1) await ReceiveAsync()로 패킷 수신
  2) UTF8 문자열로 변환
  3) (옵션) logEveryN마다 패킷 요약 로그 출력
  4) JsonUtility.FromJson<Go1StateMsg>()로 파싱
  5) _mainThreadJobs.Enqueue(Action):
       - vx/vy/wz 갱신
       - q[] 복사
       - hasNew=true 설정

Update()
  → 큐에 쌓인 Action을 모두 실행 (메인 스레드 안전 처리)

OnDisable()/OnDestroy()/OnApplicationQuit()
  → StopReceiver(): ct.Cancel + udp.Close + 정리

-------------------------------------------------------------------------------
[Debug 옵션]

- logPacket:
  - true면 수신 패킷 로그 활성화
- logEveryN:
  - N번째 패킷마다 한 번씩 로그 (너무 많이 찍히는 것 방지)

-------------------------------------------------------------------------------
[주의사항]

- listenPort(기본 15101)가 다른 수신기(UTM/Go1StateUdpReceiver 등)와 겹치면
  UDP 바인드 실패 또는 한쪽만 수신되는 문제가 발생할 수 있다.
  → 동일 포트는 “한 프로세스/한 UdpClient”만 바인드 가능

- JsonUtility는 구조가 단순한 JSON에 적합하며
  필드명이 정확히 일치해야 파싱된다.

-------------------------------------------------------------------------------
[확장 가능]

- estop 수신 시 hasNew와 별개로 “정지 상태” 플래그 제공
- rpy를 저장하여 root 회전까지 동기화
- 패킷 타임아웃 감지(일정 시간 미수신 시 hasNew=false 처리)
- 메시지 버전/검증(conf, seq, timestamp) 추가

===============================================================================
*/

public class Go1TwinUDP : MonoBehaviour
{
    [Header("Listen (SDK PC -> Unity state)")]
    public int listenPort = 15101;

    [Header("Debug")]
    public bool logPacket = false;
    public int logEveryN = 60;

    public volatile bool hasNew;
    public float vx, vy, wz;
    public float[] q = new float[12];

    private UdpClient _udp;
    private CancellationTokenSource _cts;
    private Task _rxTask;

    private readonly ConcurrentQueue<Action> _mainThreadJobs = new ConcurrentQueue<Action>();
    private int _rxCount;

    [Serializable]
    public class Go1StateMsg
    {
        public float[] rpy;
        public float[] q;
        public float vx;
        public float vy;
        public float wz;
        public int estop;
    }

    void OnEnable()
    {
        StartReceiver();
    }

    void OnDisable()
    {
        StopReceiver();
    }

    void OnDestroy()
    {
        StopReceiver();
    }

    void OnApplicationQuit()
    {
        StopReceiver();
    }

    void Update()
    {
        while (_mainThreadJobs.TryDequeue(out var job))
        {
            try { job?.Invoke(); }
            catch (Exception e) { Debug.LogWarning($"[Go1TwinUDP] main job error: {e.Message}"); }
        }
    }

    private void StartReceiver()
    {
        StopReceiver();

        try
        {
            _udp = new UdpClient(listenPort);
            _udp.Client.ReceiveBufferSize = 1 << 20; // 1MB
            _udp.Client.SendBufferSize = 1 << 20;

            _cts = new CancellationTokenSource();
            _rxTask = Task.Run(() => RxLoop(_cts.Token), _cts.Token);

            Debug.Log($"[Go1TwinUDP] Listening UDP :{listenPort}");
        }
        catch (Exception e)
        {
            Debug.LogError($"[Go1TwinUDP] StartReceiver failed: {e}");
            StopReceiver();
        }
    }

    private void StopReceiver()
    {
        try
        {
            if (_cts != null && !_cts.IsCancellationRequested)
                _cts.Cancel();
        }
        catch { }

        try
        {
            _udp?.Close();
        }
        catch { }

        _udp = null;

        try
        {
            _cts?.Dispose();
        }
        catch { }

        _cts = null;
        _rxTask = null;
    }

    private async Task RxLoop(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (_udp == null) break;

                UdpReceiveResult result = await _udp.ReceiveAsync().ConfigureAwait(false);
                byte[] data = result.Buffer;
                if (data == null || data.Length == 0) continue;

                string json = Encoding.UTF8.GetString(data);

                _rxCount++;
                if (logPacket && (_rxCount % Mathf.Max(1, logEveryN) == 0))
                    Debug.Log($"[Go1TwinUDP] RX#{_rxCount} {data.Length}B from {result.RemoteEndPoint} : {Trim(json, 200)}");

                // 파싱은 백그라운드에서 해도 되지만, 필드 갱신은 메인스레드에서만
                Go1StateMsg msg = null;
                try { msg = JsonUtility.FromJson<Go1StateMsg>(json); }
                catch (Exception pe)
                {
                    if (logPacket) Debug.LogWarning($"[Go1TwinUDP] JSON parse error: {pe.Message}");
                    continue;
                }

                if (msg == null) continue;

                _mainThreadJobs.Enqueue(() =>
                {
                    // 여기서만 Unity 필드 갱신
                    vx = msg.vx;
                    vy = msg.vy;
                    wz = msg.wz;

                    if (msg.q != null)
                    {
                        int n = Mathf.Min(q.Length, msg.q.Length);
                        for (int i = 0; i < n; i++) q[i] = msg.q[i];
                    }

                    hasNew = true;
                });
            }
            catch (ObjectDisposedException)
            {
                // 정상 종료 시 흔함
                break;
            }
            catch (SocketException)
            {
                // 소켓 닫힘/포트 충돌 등
                if (ct.IsCancellationRequested) break;
                await Task.Delay(50, ct).ConfigureAwait(false);
            }
            catch (Exception e)
            {
                if (ct.IsCancellationRequested) break;
                Debug.LogWarning($"[Go1TwinUDP] RxLoop error: {e.Message}");
                await Task.Delay(50, ct).ConfigureAwait(false);
            }
        }
    }

    private static string Trim(string s, int max)
    {
        if (string.IsNullOrEmpty(s)) return s;
        return s.Length <= max ? s : s.Substring(0, max) + "...";
    }
}
