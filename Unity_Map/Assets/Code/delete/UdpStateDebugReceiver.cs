using System;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Concurrent;
using UnityEngine;

/*
===============================================================================
UdpStateDebugReceiver.cs
-------------------------------------------------------------------------------
UDP 상태 패킷 "원문 문자열"을 그대로 수신해서 콘솔에 출력하는 디버그 리시버

목적:
- SDK PC -> Unity 로 들어오는 STATE(또는 JSON) 패킷이 "실제로 들어오는지"
- 패킷 포맷이 어떤지(공백 구분 텍스트인지, JSON인지)
- 특정 포트가 충돌 중인지(바인딩 실패) 빠르게 확인

-------------------------------------------------------------------------------
[동작 방식]

1) OnEnable()에서 StartRx() 호출
   - UdpClient(listenPort)로 바인딩 (기본 15101)
   - ReceiveBufferSize를 크게(1MB) 설정
   - Task.Run으로 비동기 수신 루프 시작

2) Loop() (백그라운드 Task)
   - udp.ReceiveAsync()로 패킷 수신
   - 바이트 -> UTF8 문자열 변환
   - 너무 길면 maxChars로 잘라서 큐에 저장(ConcurrentQueue)

3) Update() (Unity 메인 스레드)
   - 큐에 쌓인 메시지를 모두 Dequeue
   - latest에 마지막 문자열 저장
   - enableLog=true면 Debug.Log로 출력

4) OnDisable()에서 StopRx() 호출
   - CancellationTokenSource Cancel
   - UdpClient Close 및 Dispose 정리

-------------------------------------------------------------------------------
[필드 설명]

- listenPort : 수신할 UDP 포트 (기본 15101)
- maxChars   : 로그 출력 시 문자열 최대 길이 (너무 긴 JSON/텍스트 방지)
- enableLog  : true면 콘솔에 출력, false면 latest만 갱신

- latest     : 마지막으로 수신된 문자열(Inspector에서 확인 가능)

-------------------------------------------------------------------------------
[주의사항]

- 같은 PC/프로세스에서 동일 포트(예: 15101)를 이미 다른 스크립트가 바인딩 중이면
  StartRx()에서 예외가 나고 수신이 되지 않음 (포트 충돌/중복 인스턴스 주의)

- 이 스크립트는 "파싱/동기화 적용"을 하지 않는다.
  즉, 로봇 트윈을 움직이기 위한 값 변환은 다른 스크립트(UTM/StateReceiver 등)에서 수행.

- VR/빌드 환경에서도 로그가 너무 많이 찍히면 성능 저하가 생길 수 있으니
  enableLog를 끄거나, 출력 빈도를 제한하는 방식으로 확장 가능.

-------------------------------------------------------------------------------
[추천 사용 시나리오]

- “유니티 트윈이 안 움직인다” 디버깅 시
  1) enableLog 켜고
  2) 실제로 패킷이 들어오는지 확인
  3) 들어온다면 포맷 확인 → 파서/매핑/축 반전 문제로 범위 좁히기

===============================================================================
*/

public class UdpStateDebugReceiver : MonoBehaviour
{
    public int listenPort = 15101;
    public int maxChars = 2000;
    public bool enableLog = true;

    private UdpClient _udp;
    private CancellationTokenSource _cts;
    private Task _task;

    private readonly ConcurrentQueue<string> _msgs = new ConcurrentQueue<string>();
    public string latest;

    void OnEnable()
    {
        StartRx();
    }

    void OnDisable()
    {
        StopRx();
    }

    void Update()
    {
        while (_msgs.TryDequeue(out var s))
        {
            latest = s;
            if (enableLog) Debug.Log($"[UdpStateDebugReceiver] {s}");
        }
    }

    private void StartRx()
    {
        StopRx();

        try
        {
            _udp = new UdpClient(listenPort);
            _udp.Client.ReceiveBufferSize = 1 << 20;

            _cts = new CancellationTokenSource();
            _task = Task.Run(() => Loop(_cts.Token), _cts.Token);

            Debug.Log($"[UdpStateDebugReceiver] Listening :{listenPort}");
        }
        catch (Exception e)
        {
            Debug.LogError($"[UdpStateDebugReceiver] start fail: {e.Message}");
            StopRx();
        }
    }

    private void StopRx()
    {
        try { _cts?.Cancel(); } catch { }
        try { _udp?.Close(); } catch { }
        _udp = null;
        try { _cts?.Dispose(); } catch { }
        _cts = null;
        _task = null;
    }

    private async Task Loop(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (_udp == null) break;
                var r = await _udp.ReceiveAsync().ConfigureAwait(false);
                string s = Encoding.UTF8.GetString(r.Buffer);
                if (s.Length > maxChars) s = s.Substring(0, maxChars) + "...";
                _msgs.Enqueue(s);
            }
            catch (ObjectDisposedException) { break; }
            catch (SocketException)
            {
                if (ct.IsCancellationRequested) break;
                await Task.Delay(50, ct).ConfigureAwait(false);
            }
            catch (Exception)
            {
                if (ct.IsCancellationRequested) break;
                await Task.Delay(50, ct).ConfigureAwait(false);
            }
        }
    }
}
