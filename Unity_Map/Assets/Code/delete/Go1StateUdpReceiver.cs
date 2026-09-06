using System;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

/*
===============================================================================
Go1StateUdpReceiver.cs
-------------------------------------------------------------------------------
GO1 상태(State) UDP 패킷을 수신하여 Unity의 target Transform(로봇 루트)을
월드 좌표(x,z) + yaw 회전으로 동기화하는 수신기

[개요]
외부(PC/SDK 브릿지)가 주기적으로 송신하는 GO1 상태 문자열을 UDP로 받아,
Unity 씬에서 로봇(디지털 트윈)의 위치/방향을 실시간 업데이트한다.

- 입력: UDP 텍스트 패킷(STATE)
- 출력: target.position / target.rotation 갱신
- 옵션: 좌표계 변환(swap/invert/scale/offset), yaw 오프셋, 스무딩

-------------------------------------------------------------------------------
[수신 포맷(기본 텍스트 STATE)]

공백 구분, 최소 10개 토큰:
  seq t_ms x z yaw vx vy wz estop mode

예)
  "1234 170000.12 1.234 0.567 -0.321 0.10 0.00 0.02 0 0"

- seq   : 패킷 시퀀스 번호(ulong)
- t_ms  : 타임스탬프(ms 또는 송신측 기준 시간 값)
- x, z  : 월드 좌표(보통 meters)
- yaw   : yaw 라디안(rad) (송신측 구현에 따라 deg일 수도 있으니 주의)
- vx,vy,wz : 속도/각속도(참고용, 본 스크립트는 포즈 적용에 주로 사용)
- estop : 비상정지 플래그(0/1)
- mode  : 로봇 상태 모드(예: stand/stop 등)

※ TryParseState는 InvariantCulture로 파싱하여
   소수점 '.' 환경에서도 안전하게 동작하도록 한다.

-------------------------------------------------------------------------------
[동작 흐름]

Start()
  1) target이 비어 있으면 자기 transform을 target으로 사용
  2) listenPort(기본 15101)에 UDP 바인드
  3) 백그라운드 스레드(RxLoop) 시작

RxLoop()
  - UDP Receive → 문자열 파싱(TryParseState)
  - 최신 상태를 공유 변수(_x,_z,_yawRad 등)에 저장
  - 메인 스레드에서 적용할 수 있도록 _hasNew 플래그 세팅

Update()
  - _hasNew가 true인 경우 최신 x/z/yaw를 읽어 Transform에 반영
  - 좌표 변환(swapXZ / invertX / invertZ / positionScale / positionOffset) 적용
  - yaw 변환(invertYaw / yawOffsetDeg) 적용
  - useSmooth에 따라 즉시 적용 또는 exp 기반 Lerp/Slerp로 스무딩 적용

OnDestroy()
  - 스레드 종료 플래그 내림 + UDP 소켓 닫기 + 스레드 Join

-------------------------------------------------------------------------------
[좌표계/매핑 옵션]

- swapXZ: 송신측 좌표계가 Unity와 축 정의가 다를 때 사용
- invertX/invertZ: 좌표 방향(부호)이 반대일 때 사용
- positionScale: 단위 스케일 조정(기본 1m=1유니티)
- positionOffset: Unity 씬 기준 오프셋(시작 위치 맞추기)

Yaw:
- invertYaw: 회전 방향이 반대일 때 사용
- yawOffsetDeg: 기준 각도 보정(예: Unity 기준을 90도 돌려 맞출 때)

-------------------------------------------------------------------------------
[스무딩]

- useSmooth=true:
  - 위치: exp 형태(1 - exp(-k*dt))를 이용한 Lerp
  - 회전: exp 형태를 이용한 Slerp
  → 네트워크 지터/패킷 간격 변화로 인한 떨림을 완화

-------------------------------------------------------------------------------
[주의사항]

- UDP 스레드에서 Unity API(Transform 등)를 직접 호출하면 안 됨
  (본 스크립트는 메인 스레드 Update에서만 적용하도록 설계됨)
- listenPort 중복 바인딩 시 수신 불가(동일 포트 2개 프로세스 금지)
- yaw가 rad/deg인지 송신측과 반드시 일치해야 함
  (현재 구현은 rad로 가정하고 Rad2Deg 변환 적용)

-------------------------------------------------------------------------------
[확장 가능]

- JSON 포맷 지원(예: {"x":..,"z":..,"yaw_deg":..})
- estop/mode에 따라 포즈 적용 차단(정지 상태 유지)
- 패킷 타임아웃 시 target 업데이트 중지/복귀 로직
- origin 보정(첫 상태를 기준으로 Unity 시작 위치 고정) 통합

===============================================================================
*/

public class Go1StateUdpReceiver : MonoBehaviour
{
    [Header("UDP Listen (STATE)")]
    public int listenPort = 15101;

    [Header("Target to move (Unity Go1 root Transform)")]
    public Transform target;

    [Header("Coordinate mapping")]
    public bool swapXZ = false;          // 필요하면 x<->z 스왑
    public bool invertX = false;         // 필요하면 x 부호 반전
    public bool invertZ = false;         // 필요하면 z 부호 반전
    public float positionScale = 1.0f;   // 미터 스케일 조정(보통 1)

    [Header("Offsets (meters)")]
    public Vector3 positionOffset = Vector3.zero;

    [Header("Yaw mapping")]
    public bool invertYaw = false;       // 필요하면 yaw 부호 반전
    public float yawOffsetDeg = 0.0f;    // 필요하면 추가 오프셋(예: 90)

    [Header("Smoothing")]
    public bool useSmooth = true;
    [Range(0.0f, 30.0f)] public float posLerpSpeed = 12.0f;
    [Range(0.0f, 30.0f)] public float rotLerpSpeed = 12.0f;

    [Header("Debug")]
    public bool logPackets = false;

    private UdpClient _udp;
    private Thread _rxThread;
    private volatile bool _running;

    private readonly object _lock = new object();
    private bool _hasNew = false;
    private double _x, _z, _yawRad;
    private ulong _seq;
    private double _tms;
    private float _vx, _vy, _wz;
    private int _estop, _mode;

    void Start()
    {
        if (target == null) target = this.transform;

        _udp = new UdpClient(listenPort);
        _udp.Client.ReceiveTimeout = 1000;

        _running = true;
        _rxThread = new Thread(RxLoop);
        _rxThread.IsBackground = true;
        _rxThread.Start();

        Debug.Log($"[Go1StateUdpReceiver] Listening UDP {listenPort} (STATE)");
    }

    void OnDestroy()
    {
        _running = false;
        try { _udp?.Close(); } catch { }
        try { _rxThread?.Join(200); } catch { }
    }

    private void RxLoop()
    {
        var ep = new IPEndPoint(IPAddress.Any, 0);

        while (_running)
        {
            try
            {
                byte[] data = _udp.Receive(ref ep);
                string msg = Encoding.ASCII.GetString(data).Trim();
                if (string.IsNullOrEmpty(msg)) continue;

                if (!TryParseState(msg,
                    out ulong seq, out double tms,
                    out double x, out double z, out double yaw,
                    out float vx, out float vy, out float wz,
                    out int estop, out int mode))
                {
                    continue;
                }

                lock (_lock)
                {
                    _seq = seq; _tms = tms;
                    _x = x; _z = z; _yawRad = yaw;
                    _vx = vx; _vy = vy; _wz = wz;
                    _estop = estop; _mode = mode;
                    _hasNew = true;
                }

                if (logPackets)
                    Debug.Log($"[STATE] seq={seq} x={x:F3} z={z:F3} yaw(rad)={yaw:F3} mode={mode} estop={estop}");
            }
            catch (SocketException)
            {
            }
            catch (Exception)
            {
            }
        }
    }

    void Update()
    {
        if (target == null) return;

        bool has;
        double x, z, yaw;
        lock (_lock)
        {
            has = _hasNew;
            x = _x; z = _z; yaw = _yawRad;
            _hasNew = false;
        }
        if (!has) return;

        float fx = (float)x * positionScale;
        float fz = (float)z * positionScale;

        if (swapXZ)
        {
            float tmp = fx; fx = fz; fz = tmp;
        }
        if (invertX) fx = -fx;
        if (invertZ) fz = -fz;

        Vector3 desiredPos = new Vector3(fx, 0f, fz) + positionOffset;

        double yawUsed = invertYaw ? -yaw : yaw;
        float yawDeg = (float)(yawUsed * Mathf.Rad2Deg) + yawOffsetDeg;
        Quaternion desiredRot = Quaternion.Euler(0f, yawDeg, 0f);

        if (!useSmooth)
        {
            target.position = desiredPos;
            target.rotation = desiredRot;
        }
        else
        {
            float dt = Time.deltaTime;
            target.position = Vector3.Lerp(target.position, desiredPos, 1f - Mathf.Exp(-posLerpSpeed * dt));
            target.rotation = Quaternion.Slerp(target.rotation, desiredRot, 1f - Mathf.Exp(-rotLerpSpeed * dt));
        }
    }

    private static bool TryParseState(
        string msg,
        out ulong seq, out double tms,
        out double x, out double z, out double yaw,
        out float vx, out float vy, out float wz,
        out int estop, out int mode)
    {
        seq = 0; tms = 0;
        x = 0; z = 0; yaw = 0;
        vx = 0; vy = 0; wz = 0;
        estop = 0; mode = 0;

        string[] p = msg.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
        if (p.Length < 10) return false;

        var ci = CultureInfo.InvariantCulture;

        try
        {
            seq = ulong.Parse(p[0], ci);
            tms = double.Parse(p[1], ci);
            x = double.Parse(p[2], ci);
            z = double.Parse(p[3], ci);
            yaw = double.Parse(p[4], ci);
            vx = float.Parse(p[5], ci);
            vy = float.Parse(p[6], ci);
            wz = float.Parse(p[7], ci);
            estop = int.Parse(p[8], ci);
            mode = int.Parse(p[9], ci);
            return true;
        }
        catch
        {
            return false;
        }
    }
}
