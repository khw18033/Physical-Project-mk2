using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Generic;
using UnityEngine;

public class UnityTeleopAndMirror : MonoBehaviour
{
    [Header("Singleton Options")]
    public bool dontDestroyOnLoad = true;
    public bool destroyDuplicates = true;

    private GO1Agent go1Agent;
    private volatile bool _pathDoneNotify = false;
    // mode=98: C++이 PATH_CANCEL 처리 완료 후 보내는 ACK
    private volatile bool _pathCancelAckNotify = false;
    private volatile bool _pathCancelAckLogPending = false;
    private ulong _lastPathCancelAckSeq = 0;
    private double _lastPathCancelAckX = 0.0;
    private double _lastPathCancelAckZ = 0.0;
    private double _lastPathCancelAckYaw = 0.0;

    private static UnityTeleopAndMirror _instance;
    public static UnityTeleopAndMirror Instance => _instance;

    [Header("SDK PC (receiver) - Unity -> SDK (cmd)")]
    public string sdkPcIp = "192.168.50.81";
    public int sdkPcPort = 15100;

    [Header("SDK PC -> Unity (state)")]
    public int stateListenPort = 15101;

    [Header("SDK State Movement Monitor")]
    [Tooltip("경로 전송 후 현실 GO1이 실제로 움직이기 시작했는지 판정할 때 사용하는 위치 변화 임계값")]
    public float realMoveStartDistanceThreshold = 0.03f;

    [Tooltip("경로 전송 후 현실 GO1이 실제로 움직이기 시작했는지 판정할 때 사용하는 선속도/각속도 임계값")]
    public float realMoveStartSpeedThreshold = 0.03f;

    [Header("SDK PC -> Unity (cmd mirror)")]
    public bool driveBySdkCmd = false;
    public int sdkCmdListenPort = 15102;

    [Header("Speed limits")]
    public float maxVx = 0.4f;
    public float maxVy = 0.4f;
    public float maxWz = 2.0f;

    [Header("Unity -> SDK Forward Command Tuning")]
    [Tooltip("Unity에서 SDK로 보내는 vx 직진/후진 명령 배율입니다. 1.2면 기존보다 20% 더 빠르게 전진/후진합니다.")]
    public float unityToSdkVxScale = 1.0f;

    // 이전 버전 호환용. 실제 체크박스는 GO1CoordinateMapper의
    // Command Invert Forward에서만 관리합니다.
    [SerializeField, HideInInspector]
    private bool invertUnityToSdkVx = false;

    [Tooltip("작은 vx 입력도 최소 이 값 이상으로 보내고 싶을 때 사용합니다. 0이면 사용하지 않습니다.")]
    public float minUnityToSdkVxAbs = 0.0f;

    [Tooltip("이 값보다 작은 vx 입력은 0으로 처리합니다.")]
    public float unityToSdkVxDeadzone = 0.001f;

    [Tooltip("튜닝 후 SDK로 보낼 vx 절댓값 상한입니다. 배율로 더 크게 보내려면 maxVx보다 크게 설정하세요.")]
    public float maxUnityToSdkVxAbs = 0.6f;

    [Header("Unity -> SDK Yaw Command Tuning")]
    [Tooltip("Unity에서 SDK로 보내는 wz 회전 명령 배율입니다. 1.2면 기존보다 20% 더 회전합니다.")]
    public float unityToSdkWzScale = 1.0f;

    // 이전 버전 호환용. 실제 체크박스는 GO1CoordinateMapper의
    // Command Invert Yaw에서만 관리합니다.
    [SerializeField, HideInInspector]
    private bool invertUnityToSdkWz = false;

    [SerializeField, HideInInspector]
    private bool legacyCommandFlagsMigrated = false;

    [Tooltip("작은 wz 입력도 최소 이 값 이상으로 보내고 싶을 때 사용합니다. 0이면 사용하지 않습니다.")]
    public float minUnityToSdkWzAbs = 0.0f;

    [Tooltip("이 값보다 작은 wz 입력은 0으로 처리합니다.")]
    public float unityToSdkWzDeadzone = 0.001f;

    [Header("Drive by EXTERNAL WORLD POSE")]
    public bool driveByState = true;

    [Header("State Follow Rebase")]
    [Tooltip("state_change=true로 driveByState를 다시 켤 때, 현재 가상 GO1 위치를 기준으로 SDK state 원점을 재보정해서 순간이동을 막습니다.")]
    public bool enableStateFollowRebase = true;

    [Tooltip("state follow rebase 적용 로그 출력")]
    public bool logStateFollowRebase = true;

    [Header("Virtual Mode (V키 토글)")]
    public KeyCode virtualModeToggleKey = KeyCode.V;

    [Header("Target Driver")]
    public Go1WASDLegacyDrive driver;

    [Header("Coordinate Mapper - 좌표계 변환 단일 관리") ]
    [Tooltip("Unity/SDK/path 좌표계 변환은 이 컴포넌트 한 곳에서만 관리합니다.")]
    public GO1CoordinateMapper coordinateMapper;

    [Header("SDK Origin Reset")]
    [Tooltip("누르면 현재 수신 중인 현실 Go1 위치를 새 원점으로 잡습니다. KeyCode.None이면 키 입력으로 원점 재설정을 하지 않습니다.")]
    public KeyCode resetOriginKey = KeyCode.None;

    [Header("Runtime Calibration Debug")]
    public bool showCalibrationGui = true;
    public bool logCalibrationValues = false;

    [Header("Yaw Align Key (Z키 보정)")]
    [Tooltip("이 키를 누르면 현재 SDK yaw 기준으로 가상 GO1의 Y 회전이 targetVirtualYawDeg가 되도록 yawOffsetDeg를 자동 보정한다.")]
    public KeyCode yawAlignKey = KeyCode.Z;

    [Tooltip("Z키 보정 후 가상 GO1이 바라보게 할 Unity Yaw 각도")]
    public float targetVirtualYawDeg = 90f;

    [Tooltip("Z키를 누를 때 C++ SDK yaw와 Unity yaw를 비교해서 Unity 쪽 yaw 기준을 SDK 기준에 맞춘다.")]
    public bool compareSdkYawAndUnityYawOnZ = true;

    [Tooltip("Z키를 누르는 순간 가상 GO1 회전을 targetVirtualYawDeg로 즉시 맞춘다.")]
    public bool snapVirtualYawOnAlignKey = true;

    [Tooltip("Z키 보정 시 GO1Agent 루트 회전도 같은 yaw로 맞춘다. 경로 생성 시작 yaw 오차를 줄이기 위한 옵션")]
    public bool syncAgentRootYawOnAlignKey = true;


    [Tooltip("Z키 보정값을 C++/SDK 쪽에 UDP 메시지로 알려준다.")]
    public bool notifySdkYawOffset = true;

    [Tooltip("시작 시 현재 yawOffsetDeg를 C++/SDK에 한 번 보낸다.")]
    public bool sendYawOffsetOnStart = true;

    [Tooltip("yaw 보정 메시지를 주기적으로 재전송한다.")]
    public bool repeatYawOffsetNotify = false;

    [Tooltip("yaw 보정 메시지 재전송 주기")]
    public float yawOffsetNotifyHz = 1.0f;

    [Tooltip("C++에서 받을 yaw 보정 메시지 prefix")]
    public string yawOffsetNotifyPrefix = "YAW_CALIB";

    [Header("Smoothing")]
    [Tooltip("C++ state가 늦게 반영되는 문제를 막기 위해 기본값은 false. true로 켜도 forceImmediateStateApply가 true이면 즉시 반영됩니다.")]
    public bool smoothing = false;
    public float posLerp = 15f;
    public float rotLerp = 20f;

    [Header("Low Latency State Sync")]
    [Tooltip("C++에서 들어온 위치/회전을 보간하지 않고 매 FixedUpdate마다 즉시 적용합니다. z/r 보정 확인 시 true 권장.")]
    public bool forceImmediateStateApply = true;

    [Tooltip("UDP 수신 버퍼에 쌓인 오래된 state 패킷을 버리고 가장 마지막 패킷만 사용합니다.")]
    public bool dropOldStatePackets = true;

    [Tooltip("state UDP 수신 버퍼 크기. 너무 크면 오래된 패킷이 밀려서 늦게 반영될 수 있으므로 작게 유지합니다.")]
    public int stateReceiveBufferSize = 8192;

    [Header("Teleop")]
    public bool enableTeleop = true;
    public bool allowTeleopEvenWhenDriveByState = true;

    [Header("Unified Manual Teleop (VR/WASD -> Real + Virtual)")]
    [Tooltip("키보드 W/A/S/D/Q/E 입력도 SendTeleopCmd() 경로를 통해 현실/가상 Go1에 동일하게 적용합니다. VR 조작 중에는 중복 명령 방지를 위해 false 권장.")]
    public bool enableKeyboardTeleop = false;

    [Tooltip("VR 또는 WASD로 현실 Go1에 보내는 최종 vx/vy/wz 명령을 가상 Go1에도 동시에 적용합니다.")]
    public bool mirrorManualCommandToVirtual = true;

    [Tooltip("수동 명령이 활성화된 동안 SDK state가 가상 Go1 Transform을 덮어쓰지 않도록 합니다.")]
    public bool suspendStateFollowWhileManualCommand = true;

    [Tooltip("조이스틱/키를 놓은 뒤 이 시간 동안 0 명령을 유지한 후 SDK state 동기화로 복귀합니다.")]
    public float manualCommandReleaseDelay = 0.12f;

    [Tooltip("이 값보다 작은 vx/vy/wz는 가상 수동 명령 활성 판정에서 0으로 간주합니다.")]
    public float manualCommandActivityDeadzone = 0.001f;

    [Header("SDK Connection Routing (이중 구동 방지)")]
    [Tooltip("SDK가 연결되어 있으면 텔레옵 명령을 SDK로만 보내고, 가상 Go1은 SDK state가 움직이게 합니다. " +
             "연결이 없으면 유니티가 명령으로 가상 Go1을 직접 움직입니다.")]
    public bool driveVirtualBySdkWhenConnected = true;

    [Tooltip("최근 이 시간(초) 안에 SDK state 패킷을 받았으면 'SDK 연결됨'으로 판단합니다.")]
    public float sdkConnectedStateTimeoutSec = 0.5f;

    [Header("FIX Unity Start Pose")]
    public bool fixUnityStartPose = true;
    public Vector3 unityFixedStartPos = new Vector3(2f, 0f, 1.2f);
    public bool lockYToFixedStart = true;

    [Header("Marker Priority")]
    public bool pauseStateApplyWhileMarkerActive = true;
    public bool allowTeleopWhileMarkerActive = true;

    [Header("Virtual Feedback to C++ (포트 15103)")]
    [Tooltip("가상 테스트 시 활성화. 실제 로봇 사용 시 비활성화 권장.")]
    public bool sendVirtualFeedback = true;
    public int virtualFeedbackPort = 15103;

    // =============================================
    // Waypoint 시각화 (C++에서 포트 15104로 수신)
    // =============================================
    [Header("Waypoint Visualizer (포트 15104)")]
    public bool showWaypoints = true;
    public int waypointListenPort = 15104;
    public Color waypointColor = Color.red;
    public Color lineColor = Color.yellow;
    public float markerSize = 0.3f;
    public float markerHeight = 0.5f;

    [Header("Path Finish Yaw Compare")]
    [Tooltip("C++ mode=99 경로 완료 신호를 받았을 때 C++ yaw와 Unity 가상 GO1 yaw를 비교해서 로그로 출력합니다.")]
    public bool compareYawOnPathDone = true;

    [Tooltip("완료 시 yaw 차이가 이 값보다 크면 Warning 로그를 출력합니다. 단위: deg")]
    public float pathDoneYawWarnThresholdDeg = 3.0f;

    [Tooltip("완료 시 위치 차이도 같이 비교해서 로그로 출력합니다.")]
    public bool comparePositionOnPathDone = true;

    [Tooltip("완료 시 위치 차이가 이 값보다 크면 Warning 로그를 출력합니다. 단위: meter")]
    public float pathDonePositionWarnThresholdM = 0.20f;

    [Header("DEBUG")]
    public bool debug = true;
    public float debugPrintHz = 5f;

    private float _dbgNext;

    private float _virtualManualCommandActiveUntil = -999f;
    private bool _keyboardTeleopWasActive = false;

    // 수동 VR/WASD 명령이 끝나는 순간을 감지해
    // SDK state follow 기준점을 현재 가상 위치로 재보정한다.
    private bool _wasVirtualManualCommandActive = false;

    private UdpClient txUdp;
    private IPEndPoint txEp;
    private UdpClient rxStateUdp;
    private Thread rxStateThread;
    private UdpClient rxCmdUdp;
    private Thread rxCmdThread;
    private volatile bool running;
    private bool _stopped = false;
    private readonly object _stopLock = new object();

    // 가상 피드백 UDP
    private UdpClient feedbackUdp;
    private IPEndPoint feedbackEp;

    // Waypoint 수신 UDP
    private UdpClient rxWaypointUdp;
    private Thread rxWaypointThread;
    private volatile string _pendingWaypointMsg = null;
    private readonly object _waypointLock = new object();

    // Waypoint 시각화 오브젝트
    private List<GameObject> _waypointMarkers = new List<GameObject>();
    private LineRenderer _waypointLine;

    [NonSerialized] public ulong sSeq;
    [NonSerialized] public double sTms;
    [NonSerialized] public double sX, sZ, sYaw;
    [NonSerialized] public double sVx, sVy, sWz;
    [NonSerialized] public int sEstop, sMode;
    private volatile bool hasState = false;
    private volatile float lastStateReceiveUnityTime = -999f;
    private volatile bool _stateUpdatedFromThread = false;

    [NonSerialized] public float cVx, cVy, cWz;
    [NonSerialized] public int cEstop;
    private volatile bool hasCmd = false;

    private readonly object _stateLock = new object();
    private bool _originInited = false;
    private double _originX = 0.0;
    private double _originZ = 0.0;

    // SDK 위치 변화량을 몸체축 기준으로 변환해 누적하기 위한 상태입니다.
    // 기존 코드에서는 GO1CoordinateMapper의 useBodyAxisStateDeltaMapping /
    // invertBodyAxisStateLateral 값이 실제 위치 적용 경로에서 호출되지 않았습니다.
    private bool _bodyAxisStateInited = false;
    private double _bodyAxisPrevSdkX = 0.0;
    private double _bodyAxisPrevSdkZ = 0.0;
    private Vector3 _bodyAxisUnityPos = Vector3.zero;

    [Serializable]
    private class PoseJson
    { public float x, z, yaw_deg, conf; public double ts; }

    [Serializable]
    private class CmdJson
    { public float vx, vy, wz; public int estop; }



    private GO1CoordinateMapper Mapper
    {
        get
        {
            if (coordinateMapper == null)
                coordinateMapper = GetComponent<GO1CoordinateMapper>();
            if (coordinateMapper == null && driver != null)
                coordinateMapper = driver.GetComponent<GO1CoordinateMapper>();
            if (coordinateMapper == null)
                coordinateMapper = FindFirstObjectByType<GO1CoordinateMapper>();
            if (coordinateMapper == null)
                coordinateMapper = gameObject.AddComponent<GO1CoordinateMapper>();
            return coordinateMapper;
        }
    }

    private float ApplyUnityToSdkVxTuning(float vx)
    {
        if (Mathf.Abs(vx) < unityToSdkVxDeadzone)
            return 0f;

        vx = Mapper.MapCommandVx(vx);

        vx *= unityToSdkVxScale;

        if (minUnityToSdkVxAbs > 0f && Mathf.Abs(vx) < minUnityToSdkVxAbs)
            vx = Mathf.Sign(vx) * minUnityToSdkVxAbs;

        float limit = Mathf.Max(0.0f, maxUnityToSdkVxAbs);
        if (limit <= 0.0001f)
            limit = Mathf.Max(0.0001f, maxVx);

        return Mathf.Clamp(vx, -limit, limit);
    }

    private float ApplyUnityToSdkVyTuning(float vy)
    {
        vy = Mapper.MapCommandVy(vy);
        return Mathf.Clamp(vy, -maxVy, maxVy);
    }

    private float ApplyUnityToSdkWzTuning(float wz)
    {
        if (Mathf.Abs(wz) < unityToSdkWzDeadzone)
            return 0f;

        wz = Mapper.MapCommandWz(wz);

        wz *= unityToSdkWzScale;

        if (minUnityToSdkWzAbs > 0f && Mathf.Abs(wz) < minUnityToSdkWzAbs)
            wz = Mathf.Sign(wz) * minUnityToSdkWzAbs;

        return Mathf.Clamp(wz, -maxWz, maxWz);
    }

    public void SendTeleopCmd(float vx, float vy, float wz, int estop)
    {
        if (!enableTeleop)
            return;

        // 현실 Go1에 실제 전송되는 최종 명령을 먼저 만든다.
        // 방향 반전 체크박스는 GO1CoordinateMapper 한 곳에서만 적용된다.
        vx = ApplyUnityToSdkVxTuning(vx);
        vy = ApplyUnityToSdkVyTuning(vy);
        wz = ApplyUnityToSdkWzTuning(wz);
        estop = (estop != 0) ? 1 : 0;

        // 같은 최종 명령을 가상 Go1에도 전달한다.
        MirrorFinalTeleopCommandToVirtual(vx, vy, wz, estop);

        // 현실 연결이 없어도 위의 가상 테스트는 동작하도록 UDP 확인은 뒤에서 한다.
        if (txUdp == null || txEp == null)
            return;

        string msg = $"{vx:F3} {vy:F3} {wz:F3} {estop}";
        byte[] data = Encoding.ASCII.GetBytes(msg);

        try
        {
            txUdp.Send(data, data.Length, txEp);
        }
        catch (ObjectDisposedException) { }
        catch (SocketException)
        {
            if (debug)
                Debug.LogWarning("[UTM] TX SocketException");
        }
        catch (Exception e)
        {
            if (debug)
                Debug.LogWarning($"[UTM] TX error: {e.Message}");
        }
    }

    private void MirrorFinalTeleopCommandToVirtual(float vx, float vy, float wz, int estop)
    {
        if (!mirrorManualCommandToVirtual || driver == null)
            return;

        // SDK 연결 시: 명령은 이미 SDK로 전송되었고, 가상 Go1은 SDK state가 움직인다.
        // 따라서 여기서 로컬로 가상 Go1을 직접 구동하지 않는다(이중 구동 방지).
        if (driveVirtualBySdkWhenConnected && IsSdkConnected())
            return;

        float activityDz = Mathf.Max(0f, manualCommandActivityDeadzone);
        bool active =
            Mathf.Abs(vx) > activityDz ||
            Mathf.Abs(vy) > activityDz ||
            Mathf.Abs(wz) > activityDz ||
            estop != 0;

        if (active)
        {
            _virtualManualCommandActiveUntil =
                Time.time + Mathf.Max(0f, manualCommandReleaseDelay);
        }

        // 현실 Go1에 전송하는 최종 명령을
        // GO1CoordinateMapper에서 가상 모델의 90도 축에 맞게 변환한다.
        Vector3 virtualCmd = Mapper.FinalSdkCommandToVirtual(vx, vy, wz);

        driver.SetExternalCmd(
            virtualCmd.x,
            virtualCmd.y,
            virtualCmd.z,
            estop
        );
    }

    private bool IsVirtualManualCommandActive()
    {
        // SDK가 연결되어 있으면 가상 Go1은 SDK state가 움직이므로,
        // 로컬 명령 미러링(가상 직접 구동)과 state-follow 억제를 모두 끈다.
        if (driveVirtualBySdkWhenConnected && IsSdkConnected())
            return false;

        return mirrorManualCommandToVirtual &&
               Time.time <= _virtualManualCommandActiveUntil;
    }

    private void MigrateLegacyCommandFlags()
    {
        if (legacyCommandFlagsMigrated)
            return;

        // 이전 UTM 체크박스의 최종 효과를 중앙 Mapper 설정으로 옮깁니다.
        if (invertUnityToSdkVx)
            Mapper.commandInvertForward = !Mapper.commandInvertForward;

        if (invertUnityToSdkWz)
            Mapper.commandInvertYaw = !Mapper.commandInvertYaw;

        invertUnityToSdkVx = false;
        invertUnityToSdkWz = false;
        legacyCommandFlagsMigrated = true;
    }

    private void Awake()
    {
        if (_instance != null && _instance != this)
        { if (destroyDuplicates) { Destroy(gameObject); return; } }
        _instance = this;
        if (dontDestroyOnLoad) DontDestroyOnLoad(gameObject);
    }

    void Start()
    {
        go1Agent = FindFirstObjectByType<GO1Agent>();

        if (driver == null)
            driver = UnityEngine.Object.FindFirstObjectByType<Go1WASDLegacyDrive>();

        _ = Mapper;
        MigrateLegacyCommandFlags();
        ApplyDriverConfig(false, false);

        try
        {
            txUdp = new UdpClient();
            txUdp.Client.SendBufferSize = 1 << 20;
            txEp = new IPEndPoint(IPAddress.Parse(sdkPcIp), sdkPcPort);
        }
        catch (Exception e)
        { Debug.LogError($"[UTM] TX init failed: {e.Message}"); txUdp = null; txEp = null; }

        try
        {
            rxStateUdp = new UdpClient(stateListenPort);
            // 너무 큰 ReceiveBufferSize는 오래된 state 패킷이 계속 쌓여
            // C++ 동작이 Unity에 몇 초 늦게 반영되는 원인이 될 수 있다.
            rxStateUdp.Client.ReceiveBufferSize = Mathf.Max(1024, stateReceiveBufferSize);
        }
        catch (SocketException se)
        { Debug.LogError($"[UTM] State bind fail: {se.Message}"); rxStateUdp = null; }
        catch (Exception e)
        { Debug.LogError($"[UTM] State init fail: {e.Message}"); rxStateUdp = null; }

        if (driveBySdkCmd)
        {
            try
            {
                rxCmdUdp = new UdpClient(sdkCmdListenPort);
                rxCmdUdp.Client.ReceiveBufferSize = 1 << 20;
            }
            catch (Exception e)
            { Debug.LogError($"[UTM] Cmd init fail: {e.Message}"); rxCmdUdp = null; }
        }

        // 가상 피드백 UDP 초기화
        if (sendVirtualFeedback)
        {
            try
            {
                feedbackUdp = new UdpClient();
                feedbackEp = new IPEndPoint(IPAddress.Parse(sdkPcIp), virtualFeedbackPort);
                Debug.Log($"[UTM] Virtual feedback → {sdkPcIp}:{virtualFeedbackPort}");
            }
            catch (Exception e)
            {
                Debug.LogError($"[UTM] Feedback UDP init failed: {e.Message}");
                feedbackUdp = null; feedbackEp = null;
            }
        }

        // Waypoint 수신 UDP 초기화
        if (showWaypoints)
        {
            try
            {
                rxWaypointUdp = new UdpClient(waypointListenPort);
                rxWaypointThread = new Thread(WaypointRecvLoop)
                    { IsBackground = true, Name = "UTM_WaypointRecv" };
                rxWaypointThread.Start();
                Debug.Log($"[UTM] Waypoint 수신 포트: {waypointListenPort}");
            }
            catch (Exception e)
            { Debug.LogError($"[UTM] Waypoint UDP init failed: {e.Message}"); rxWaypointUdp = null; }

            // LineRenderer 초기화
            _waypointLine = gameObject.AddComponent<LineRenderer>();
            _waypointLine.startWidth = 0.08f;
            _waypointLine.endWidth = 0.08f;
            _waypointLine.material = new Material(Shader.Find("Sprites/Default"));
            _waypointLine.startColor = lineColor;
            _waypointLine.endColor = lineColor;
            _waypointLine.positionCount = 0;
            _waypointLine.useWorldSpace = true;
        }

        Time.fixedDeltaTime = 0.02f;
        running = true;

        if (sendYawOffsetOnStart)
            SendYawCalibrationToCpp();

        if (rxStateUdp != null)
        {
            rxStateThread = new Thread(StateRecvLoop)
                { IsBackground = true, Name = "UTM_StateRecv" };
            rxStateThread.Start();
        }

        if (rxCmdUdp != null)
        {
            rxCmdThread = new Thread(CmdRecvLoop)
                { IsBackground = true, Name = "UTM_CmdRecv" };
            rxCmdThread.Start();
        }
    }

    void OnDestroy()
    { StopThreadsAndClose(); if (_instance == this) _instance = null; }

    void OnDisable() { StopThreadsAndClose(); }

    private void StopThreadsAndClose()
    {
        lock (_stopLock)
        {
            if (_stopped) return;
            _stopped = true; running = false;
            try { rxStateUdp?.Close(); } catch { }
            try { rxCmdUdp?.Close(); } catch { }
            try { rxWaypointUdp?.Close(); } catch { }
            try { txUdp?.Close(); } catch { }
            try { feedbackUdp?.Close(); } catch { }
            try { if (rxStateThread?.IsAlive == true) rxStateThread.Join(300); } catch { }
            try { if (rxCmdThread?.IsAlive == true) rxCmdThread.Join(300); } catch { }
            try { if (rxWaypointThread?.IsAlive == true) rxWaypointThread.Join(300); } catch { }
            rxStateThread = null; rxCmdThread = null; rxWaypointThread = null;
            rxStateUdp = null; rxCmdUdp = null; rxWaypointUdp = null;
            txUdp = null; txEp = null;
            feedbackUdp = null; feedbackEp = null;
        }
    }

    private bool _cppUnityMode = false;
    private float _nextYawOffsetNotifyTime = 0f;

    void Update()
    {
        if (Input.GetKeyDown(virtualModeToggleKey))
        {
            _cppUnityMode = !_cppUnityMode;
            SendModeToggleToCpp(_cppUnityMode);
            Debug.Log($"[UTM] C++ 모드: {(_cppUnityMode ? "T=1 Unity cmd" : "T=0 C++ WASD")}");
        }

        if (Input.GetKeyDown(yawAlignKey))
        {
            AlignVirtualYawToTargetAndNotify();
        }

        if (resetOriginKey != KeyCode.None && Input.GetKeyDown(resetOriginKey))
        {
            ResetStateOriginToCurrentState();
        }

        if (repeatYawOffsetNotify && Time.time >= _nextYawOffsetNotifyTime)
        {
            _nextYawOffsetNotifyTime = Time.time + (1f / Mathf.Max(0.1f, yawOffsetNotifyHz));
            SendYawCalibrationToCpp();
        }

        // Waypoint 메시지 처리 (메인 스레드에서)
        if (showWaypoints)
        {
            string msg;
            lock (_waypointLock) { msg = _pendingWaypointMsg; _pendingWaypointMsg = null; }
            if (msg != null) UpdateWaypointVisualization(msg);
        }
    }

    private void AlignVirtualYawToTargetAndNotify()
    {
        bool has;
        double sdkYawRad;

        lock (_stateLock)
        {
            has = hasState;
            sdkYawRad = sYaw;
        }

        if (!has)
        {
            Debug.LogWarning("[UTM] Z yaw align 실패: 아직 SDK state yaw를 수신하지 못했습니다.");
            return;
        }

        float sdkYawDeg = (float)(sdkYawRad * Mathf.Rad2Deg);
        float signedSdkYawDeg = Mapper.invertSdkYawForUnity ? -sdkYawDeg : sdkYawDeg;
        float beforeDriverYaw = driver != null ? driver.transform.eulerAngles.y : 0f;
        float beforeAgentYaw = go1Agent != null ? go1Agent.transform.eulerAngles.y : 0f;

        Mapper.AlignSdkYawToUnityTarget(sdkYawRad, targetVirtualYawDeg);
        float alignedUnityYawDeg = ConvertSdkYawRadToUnityYawDeg(sdkYawRad);

        if (snapVirtualYawOnAlignKey && driver != null)
        {
            Vector3 euler = driver.transform.eulerAngles;
            driver.transform.rotation = Quaternion.Euler(euler.x, alignedUnityYawDeg, euler.z);
        }

        if (syncAgentRootYawOnAlignKey && go1Agent != null)
        {
            go1Agent.ApplyExternalYawSync(alignedUnityYawDeg, "Z-key sdk yaw align");
        }

        SendYawCalibrationToCpp();

        Debug.Log(
            "[UTM] Z키 yaw 정렬 완료 | " +
            $"sdkYaw={sdkYawDeg:F2}deg, signedSdkYaw={signedSdkYawDeg:F2}deg, " +
            $"targetUnityYaw={targetVirtualYawDeg:F2}deg, alignedUnityYaw={alignedUnityYawDeg:F2}deg, " +
            $"driverYawBefore={beforeDriverYaw:F2}deg, agentYawBefore={beforeAgentYaw:F2}deg, " +
            $"yawOffsetDeg={Mapper.sdkYawOffsetDeg:F2}deg, fineOffset={Mapper.unityYawFineOffsetDeg:F2}deg, legacy180={Mapper.applyLegacyExtra180Yaw}"
        );
    }

    private float ConvertSdkYawRadToUnityYawDeg(double sdkYawRad)
    {
        return Mapper.SdkYawRadToUnityYawDeg(sdkYawRad);
    }

    private float ConvertUnityYawDegToSdkYawRad(float unityYawDeg)
    {
        return Mapper.UnityYawDegToSdkYawRad(unityYawDeg);
    }

    private float NormalizeYawDeg(float yawDeg)
    {
        return GO1CoordinateMapper.NormalizeDeg(yawDeg);
    }

    private float NormalizeYawRad(float yawRad)
    {
        while (yawRad > Mathf.PI) yawRad -= 2f * Mathf.PI;
        while (yawRad < -Mathf.PI) yawRad += 2f * Mathf.PI;
        return yawRad;
    }

    private Vector2 ConvertSdkRelativeXZToUnityDelta(float relX, float relZ)
    {
        return Mapper.SdkRelativeXZToUnityDelta(relX, relZ);
    }

    private void InitBodyAxisStatePosition(
        double sdkX,
        double sdkZ,
        Vector3 unityPosition)
    {
        _bodyAxisPrevSdkX = sdkX;
        _bodyAxisPrevSdkZ = sdkZ;
        _bodyAxisUnityPos = unityPosition;
        _bodyAxisStateInited = true;
    }

    private Vector3 UpdateBodyAxisStatePosition(
        double sdkX,
        double sdkZ,
        double sdkYawRad,
        float unityY)
    {
        if (!_bodyAxisStateInited)
        {
            Vector3 startPos = driver != null
                ? driver.transform.position
                : unityFixedStartPos;

            startPos.y = unityY;
            InitBodyAxisStatePosition(sdkX, sdkZ, startPos);
            return _bodyAxisUnityPos;
        }

        float sdkDeltaX = (float)(sdkX - _bodyAxisPrevSdkX);
        float sdkDeltaZ = (float)(sdkZ - _bodyAxisPrevSdkZ);

        Vector2 unityDelta =
            Mapper.SdkStateWorldDeltaToUnityBodyDelta(
                sdkDeltaX,
                sdkDeltaZ,
                sdkYawRad
            );

        _bodyAxisUnityPos.x += unityDelta.x;
        _bodyAxisUnityPos.z += unityDelta.y;
        _bodyAxisUnityPos.y = unityY;

        _bodyAxisPrevSdkX = sdkX;
        _bodyAxisPrevSdkZ = sdkZ;

        return _bodyAxisUnityPos;
    }

    public void ResetStateOriginToCurrentState()
    {
        bool has;
        double x;
        double z;

        lock (_stateLock)
        {
            has = hasState;
            x = sX;
            z = sZ;
        }

        if (!has)
        {
            Debug.LogWarning("[UTM] 원점 재설정 실패: 아직 SDK state를 수신하지 못했습니다.");
            return;
        }

        _originInited = true;
        _originX = x;
        _originZ = z;

        Vector3 resetUnityPos = driver != null
            ? driver.transform.position
            : unityFixedStartPos;

        if (driver != null && fixUnityStartPose)
        {
            float y = lockYToFixedStart ? unityFixedStartPos.y : driver.transform.position.y;
            resetUnityPos = new Vector3(unityFixedStartPos.x, y, unityFixedStartPos.z);
            driver.transform.position = resetUnityPos;
        }

        InitBodyAxisStatePosition(x, z, resetUnityPos);

        Debug.Log(
            $"[UTM] 현재 SDK state를 새 원점으로 설정: " +
            $"origin=({_originX:F3},{_originZ:F3}), " +
            $"bodyAxisBase=({resetUnityPos.x:F3},{resetUnityPos.z:F3})"
        );
    }

    // state_change=true가 들어와서 driveByState를 다시 켜기 직전에 호출한다.
    // 현재 SDK state를 그대로 적용하면 가상 GO1이 SDK 절대 위치로 순간이동할 수 있으므로,
    // 현재 가상 GO1 위치가 "지금 받은 SDK state 위치"가 되도록 unityFixedStartPos를 재계산한다.
    public bool RebaseStateFollowToCurrentVirtualPose(Vector3 currentVirtualPose, Quaternion currentVirtualRotation, string reason = "state-follow-start")
    {
        if (!enableStateFollowRebase)
            return false;

        bool has;
        double x;
        double z;
        double yaw;

        lock (_stateLock)
        {
            has = hasState;
            x = sX;
            z = sZ;
            yaw = sYaw;
        }

        if (!has)
        {
            if (logStateFollowRebase || debug)
                Debug.LogWarning("[UTM] state follow rebase 실패: 아직 SDK state가 없습니다. reason=" + reason);

            return false;
        }

        if (!_originInited)
        {
            _originInited = true;
            _originX = x;
            _originZ = z;
        }

        if (Mapper.useBodyAxisStateDeltaMapping)
        {
            float bodyY = lockYToFixedStart
                ? unityFixedStartPos.y
                : currentVirtualPose.y;

            Vector3 rebasedPos = new Vector3(
                currentVirtualPose.x,
                bodyY,
                currentVirtualPose.z
            );

            // 다음 SDK 위치 변화량부터 현재 가상 위치에 이어 붙입니다.
            InitBodyAxisStatePosition(x, z, rebasedPos);
            unityFixedStartPos = rebasedPos;

            if (driver != null)
                driver.transform.SetPositionAndRotation(
                    rebasedPos,
                    currentVirtualRotation
                );

            if (logStateFollowRebase || debug)
            {
                Debug.Log(
                    "[UTM] body-axis state follow rebase 적용 | " +
                    "reason=" + reason +
                    ", sdkRaw=(" + x.ToString("F3") + "," + z.ToString("F3") + ")" +
                    ", virtualPos=(" + rebasedPos.x.ToString("F3") + "," + rebasedPos.z.ToString("F3") + ")" +
                    ", invertLateral=" + Mapper.invertBodyAxisStateLateral
                );
            }

            return true;
        }

        float relX = (float)(x - _originX);
        float relZ = (float)(z - _originZ);
        Vector2 mappedDelta = ConvertSdkRelativeXZToUnityDelta(relX, relZ);

        // FixedUpdate의 state 적용식과 반드시 같은 부호를 사용해야 한다.
        // desiredPos = (unityFixedStartPos.x + mappedDelta.x,
        //               unityFixedStartPos.z + mappedDelta.y)
        // 이 desiredPos가 현재 가상 GO1 위치가 되도록 역산한다.
        float y = lockYToFixedStart ? unityFixedStartPos.y : currentVirtualPose.y;
        unityFixedStartPos = new Vector3(
            currentVirtualPose.x - mappedDelta.x,
            y,
            currentVirtualPose.z - mappedDelta.y
        );

        if (driver != null)
        {
            Vector3 p = currentVirtualPose;
            if (lockYToFixedStart)
                p.y = unityFixedStartPos.y;

            driver.transform.SetPositionAndRotation(p, currentVirtualRotation);
        }

        float sdkUnityYawDeg = ConvertSdkYawRadToUnityYawDeg(yaw);

        if (logStateFollowRebase || debug)
        {
            Debug.Log(
                "[UTM] state follow rebase 적용 | " +
                "reason=" + reason +
                ", sdkRaw=(" + x.ToString("F3") + "," + z.ToString("F3") + ")" +
                ", rel=(" + relX.ToString("F3") + "," + relZ.ToString("F3") + ")" +
                ", mappedDelta=(" + mappedDelta.x.ToString("F3") + "," + mappedDelta.y.ToString("F3") + ")" +
                ", virtualPos=(" + currentVirtualPose.x.ToString("F3") + "," + currentVirtualPose.z.ToString("F3") + ")" +
                ", newFixedStart=(" + unityFixedStartPos.x.ToString("F3") + "," + unityFixedStartPos.z.ToString("F3") + ")" +
                ", sdkUnityYaw=" + sdkUnityYawDeg.ToString("F1") + "deg"
            );
        }

        return true;
    }

    // 외부 랜드마크(예: 소화기) 기반 보정용.
    // "시작점으로 되돌려서" 보정하는 것이 아니라,
    // 현재 SDK state로 Unity에 표시 중인 현재 GO1 위치가 delta만큼 이동하도록 기준점(unityFixedStartPos)을 보정한다.
    public void ApplyExternalUnityPositionCorrection(Vector3 worldDelta, string reason = "landmark", bool applyImmediately = true)
    {
        if (lockYToFixedStart)
            worldDelta.y = 0f;

        if (worldDelta.sqrMagnitude < 0.000001f)
            return;

        Vector3 currentBefore = driver != null ? driver.transform.position : GetCurrentSdkUnityMappedPosition();
        Vector3 currentAfter = currentBefore + worldDelta;

        // 현재 표시 위치 = unityFixedStartPos + SDK mappedDelta 구조이므로,
        // 기준점에 같은 delta를 더하면 현재 위치와 이후 모든 SDK 표시 위치가 같은 delta만큼 보정된다.
        unityFixedStartPos += worldDelta;

        if (_bodyAxisStateInited)
            _bodyAxisUnityPos += worldDelta;

        if (applyImmediately)
        {
            if (driver != null)
            {
                if (driveByState && HasSdkState())
                    driver.transform.position = GetCurrentSdkUnityMappedPosition();
                else
                    driver.transform.position = currentAfter;
            }

            if (go1Agent != null && (driver == null || go1Agent.transform != driver.transform))
                go1Agent.transform.position += worldDelta;
        }

        if (debug)
        {
            Debug.Log(
                "[UTM] 현재 위치 기준 외부 랜드마크 보정 | " +
                $"reason={reason}, delta=({worldDelta.x:F3},{worldDelta.y:F3},{worldDelta.z:F3}), " +
                $"currentBefore={currentBefore}, currentAfter={currentAfter}, newFixedStart={unityFixedStartPos}"
            );
        }
    }

    private void SendYawCalibrationToCpp()
    {
        if (!notifySdkYawOffset) return;
        if (txUdp == null || txEp == null) return;

        int invertYawInt = Mapper.invertSdkYawForUnity ? 1 : 0;
        int legacy180Int = Mapper.applyLegacyExtra180Yaw ? 1 : 0;
        float totalYawOffsetDeg = Mapper.GetTotalYawOffsetForSdkNotifyDeg();

        string msg = $"{yawOffsetNotifyPrefix} {totalYawOffsetDeg:F3} 1 {invertYawInt} {legacy180Int}";
        byte[] data = Encoding.ASCII.GetBytes(msg);

        try
        {
            txUdp.Send(data, data.Length, txEp);
            if (debug)
                Debug.Log("[UTM] Yaw calibration 전송: " + msg);
        }
        catch (ObjectDisposedException) { }
        catch (Exception e)
        {
            if (debug) Debug.LogWarning($"[UTM] Yaw calibration 전송 실패: {e.Message}");
        }
    }

    public bool HasSdkState()
    {
        lock (_stateLock)
        {
            return hasState;
        }
    }

    // 최근에 SDK state 패킷을 받고 있으면 SDK가 연결되어 가상 Go1을 구동할 수 있다고 본다.
    // 이 값이 "가상 Go1을 SDK가 움직일지 / 유니티가 움직일지"를 가르는 기준이다.
    // (UDP는 비연결형이라 소켓 존재만으로는 SDK 동작 여부를 알 수 없으므로 state 신선도로 판정)
    public bool IsSdkConnected()
    {
        return lastStateReceiveUnityTime > 0f &&
               (Time.time - lastStateReceiveUnityTime) <= Mathf.Max(0f, sdkConnectedStateTimeoutSec);
    }

    public float GetLastStateReceiveUnityTime()
    {
        return lastStateReceiveUnityTime;
    }

    public void ClearPathCancelAck()
    {
        _pathCancelAckNotify = false;
        _pathCancelAckLogPending = false;
    }

    public bool ConsumePathCancelAck()
    {
        if (_pathCancelAckNotify)
        {
            _pathCancelAckNotify = false;
            return true;
        }

        return false;
    }

    public void GetLastPathCancelAckRawState(out double x, out double z, out double yaw, out ulong seq)
    {
        lock (_stateLock)
        {
            x = _lastPathCancelAckX;
            z = _lastPathCancelAckZ;
            yaw = _lastPathCancelAckYaw;
            seq = _lastPathCancelAckSeq;
        }
    }

    // mode=98 ACK가 들어온 바로 그 순간의 C++ raw pose를
    // 현재 Unity 표시 좌표계로 변환해서 반환한다.
    // 재탐색 시작점은 driver.transform의 현재값이 아니라 이 ACK pose를 우선 사용해야
    // 2번째 경로 시작 yaw/position이 C++에서 실제로 끊긴 위치와 어긋나지 않는다.
    public bool GetLastPathCancelAckUnityPose(out Vector3 pos, out Quaternion rot, out ulong seq)
    {
        double x;
        double z;
        double yaw;
        bool hasAck;

        lock (_stateLock)
        {
            hasAck = _lastPathCancelAckSeq != 0;
            x = _lastPathCancelAckX;
            z = _lastPathCancelAckZ;
            yaw = _lastPathCancelAckYaw;
            seq = _lastPathCancelAckSeq;
        }

        if (!hasAck)
        {
            pos = driver != null ? driver.transform.position : unityFixedStartPos;
            rot = driver != null ? driver.transform.rotation : Quaternion.identity;
            seq = 0;
            return false;
        }

        float relX;
        float relZ;
        lock (_stateLock)
        {
            relX = (float)(x - _originX);
            relZ = (float)(z - _originZ);
        }

        Vector2 mappedDelta = ConvertSdkRelativeXZToUnityDelta(relX, relZ);

        float y = unityFixedStartPos.y;
        if (!lockYToFixedStart && driver != null)
            y = driver.transform.position.y;

        pos = new Vector3(
            unityFixedStartPos.x + mappedDelta.x,
            y,
            unityFixedStartPos.z + mappedDelta.y
        );

        float yawDeg = ConvertSdkYawRadToUnityYawDeg(yaw);
        rot = Quaternion.Euler(0f, yawDeg, 0f);
        return true;
    }

    public bool TryGetCurrentSdkUnityYawDeg(out float yawDeg)
    {
        bool has;
        double yaw;

        lock (_stateLock)
        {
            has = hasState;
            yaw = sYaw;
        }

        if (!has)
        {
            yawDeg = driver != null ? driver.transform.eulerAngles.y : 0f;
            return false;
        }

        yawDeg = ConvertSdkYawRadToUnityYawDeg(yaw);
        return true;
    }

    public Quaternion GetCurrentSdkUnityMappedRotation()
    {
        float yawDeg;
        if (TryGetCurrentSdkUnityYawDeg(out yawDeg))
            return Quaternion.Euler(0f, yawDeg, 0f);

        if (driver != null)
            return driver.transform.rotation;

        return Quaternion.identity;
    }

    public Vector3 GetCurrentSdkUnityMappedPosition()
    {
        bool has;
        double x;
        double z;

        lock (_stateLock)
        {
            has = hasState;
            x = sX;
            z = sZ;
        }

        if (!has)
        {
            if (driver != null)
                return driver.transform.position;

            return unityFixedStartPos;
        }

        if (Mapper.useBodyAxisStateDeltaMapping &&
            _bodyAxisStateInited)
        {
            Vector3 p = _bodyAxisUnityPos;
            if (lockYToFixedStart)
                p.y = unityFixedStartPos.y;
            else if (driver != null)
                p.y = driver.transform.position.y;

            return p;
        }

        float relX;
        float relZ;
        lock (_stateLock)
        {
            relX = (float)(x - _originX);
            relZ = (float)(z - _originZ);
        }

        Vector2 mappedDelta = ConvertSdkRelativeXZToUnityDelta(relX, relZ);

        float y = unityFixedStartPos.y;
        if (!lockYToFixedStart && driver != null)
            y = driver.transform.position.y;

        return new Vector3(
            unityFixedStartPos.x + mappedDelta.x,
            y,
            unityFixedStartPos.z + mappedDelta.y
        );
    }

    public void GetCurrentSdkRawState(out double x, out double z, out double vx, out double vy, out double wz, out int mode)
    {
        lock (_stateLock)
        {
            x = sX;
            z = sZ;
            vx = sVx;
            vy = sVy;
            wz = sWz;
            mode = sMode;
        }
    }

    public bool HasRealGo1StartedMoving(double startX, double startZ)
    {
        double x;
        double z;
        double vx;
        double vy;
        double wz;
        int mode;

        GetCurrentSdkRawState(out x, out z, out vx, out vy, out wz, out mode);

        double dx = x - startX;
        double dz = z - startZ;
        double moved = Math.Sqrt(dx * dx + dz * dz);
        double linearSpeed = Math.Sqrt(vx * vx + vy * vy);

        return moved >= realMoveStartDistanceThreshold ||
               linearSpeed >= realMoveStartSpeedThreshold ||
               Math.Abs(wz) >= realMoveStartSpeedThreshold;
    }

    private void LogPathDoneYawComparison()
    {
        if (!compareYawOnPathDone && !comparePositionOnPathDone)
            return;

        ulong seq;
        double rawX;
        double rawZ;
        double rawYawRad;
        double rawVx;
        double rawVy;
        double rawWz;
        int rawEstop;
        int rawMode;

        lock (_stateLock)
        {
            seq = sSeq;
            rawX = sX;
            rawZ = sZ;
            rawYawRad = sYaw;
            rawVx = sVx;
            rawVy = sVy;
            rawWz = sWz;
            rawEstop = sEstop;
            rawMode = sMode;
        }

        float cppRawYawDeg = NormalizeYawDeg((float)(rawYawRad * Mathf.Rad2Deg));
        float cppUnityYawDeg = ConvertSdkYawRadToUnityYawDeg(rawYawRad);

        float driverYawDeg = driver != null
            ? NormalizeYawDeg(driver.transform.eulerAngles.y)
            : 0f;

        float agentYawDeg = go1Agent != null
            ? NormalizeYawDeg(go1Agent.transform.eulerAngles.y)
            : driverYawDeg;

        float driverDiffDeg = driver != null
            ? Mathf.DeltaAngle(cppUnityYawDeg, driverYawDeg)
            : 0f;

        float agentDiffDeg = go1Agent != null
            ? Mathf.DeltaAngle(cppUnityYawDeg, agentYawDeg)
            : 0f;

        string posCompare = "";
        float posDiffM = 0f;

        if (comparePositionOnPathDone && driver != null)
        {
            Vector3 sdkMappedPos = GetCurrentSdkUnityMappedPosition();
            Vector3 driverPos = driver.transform.position;
            Vector2 sdkXZ = new Vector2(sdkMappedPos.x, sdkMappedPos.z);
            Vector2 driverXZ = new Vector2(driverPos.x, driverPos.z);
            posDiffM = Vector2.Distance(sdkXZ, driverXZ);

            posCompare =
                $"\n[UTM] 완료 위치 비교 | " +
                $"C++ rawPos=({rawX:F3},{rawZ:F3}), " +
                $"sdkMappedUnityPos=({sdkMappedPos.x:F3},{sdkMappedPos.z:F3}), " +
                $"driverPos=({driverPos.x:F3},{driverPos.z:F3}), " +
                $"diff={posDiffM:F3}m";
        }

        string msg =
            "[UTM] 자율주행 완료 yaw 비교 | " +
            $"seq={seq}, mode={rawMode}, " +
            $"C++ rawYaw={cppRawYawDeg:F2}deg, " +
            $"C++→UnityYaw={cppUnityYawDeg:F2}deg, " +
            $"driverYaw={driverYawDeg:F2}deg, " +
            $"agentYaw={agentYawDeg:F2}deg, " +
            $"driverDiff={driverDiffDeg:F2}deg, " +
            $"agentDiff={agentDiffDeg:F2}deg, " +
            $"rawVel=({rawVx:F3},{rawVy:F3},{rawWz:F3}), estop={rawEstop}" +
            posCompare;

        Debug.Log(msg);

        bool yawWarn = Mathf.Abs(driverDiffDeg) > pathDoneYawWarnThresholdDeg ||
                       Mathf.Abs(agentDiffDeg) > pathDoneYawWarnThresholdDeg;
        bool posWarn = comparePositionOnPathDone && posDiffM > pathDonePositionWarnThresholdM;

        if (yawWarn || posWarn)
        {
            Debug.LogWarning(
                "[UTM] 완료 pose 차이 경고 | " +
                $"yawThreshold={pathDoneYawWarnThresholdDeg:F1}deg, " +
                $"posThreshold={pathDonePositionWarnThresholdM:F2}m. " +
                "이 값이 크면 다음 M 시작 전에 Z키 yaw 정렬 또는 원점/좌표 보정을 다시 확인하세요."
            );
        }
    }

    private void SendModeToggleToCpp(bool unityMode)
    {
        if (txUdp == null || txEp == null) return;
        string msg = unityMode ? "MODE 1" : "MODE 0";
        byte[] data = Encoding.ASCII.GetBytes(msg);
        try { txUdp.Send(data, data.Length, txEp); }
        catch (Exception e)
        { if (debug) Debug.LogWarning($"[UTM] MODE 전송 실패: {e.Message}"); }
    }

    void FixedUpdate()
    {
        // SDK 연결 판정(IsSdkConnected)이 텔레옵 중에도 정확하도록,
        // state 적용(state-follow) 여부와 무관하게 수신 시각을 먼저 갱신한다.
        if (_stateUpdatedFromThread)
        {
            lastStateReceiveUnityTime = Time.time;
            _stateUpdatedFromThread = false;
        }

        bool markerActive = false;
        bool virtualManualActive = IsVirtualManualCommandActive();

        ApplyDriverConfig(markerActive, virtualManualActive);

        // C++ PATH_CANCEL 처리 완료 ACK 로그 처리 (mode=98)
        if (_pathCancelAckLogPending)
        {
            _pathCancelAckLogPending = false;
            Debug.Log("[UTM] C++ PATH_CANCEL ACK 수신! (mode=98)");
        }

        bool agentMoving = go1Agent != null && go1Agent.IsMoving();

        // 키보드도 VR과 동일한 SendTeleopCmd() 경로를 사용한다.
        // 키 입력이 없을 때 0 명령을 계속 보내면 VR 명령을 덮어쓸 수 있으므로,
        // 키가 활성화된 동안과 키를 놓는 순간 한 번만 전송한다.
        if (enableKeyboardTeleop && enableTeleop && !agentMoving)
        {
            bool keyboardActive =
                Input.GetKey(KeyCode.W) ||
                Input.GetKey(KeyCode.A) ||
                Input.GetKey(KeyCode.S) ||
                Input.GetKey(KeyCode.D) ||
                Input.GetKey(KeyCode.Q) ||
                Input.GetKey(KeyCode.E) ||
                Input.GetKey(KeyCode.Space) ||
                Input.GetKey(KeyCode.X);

            if (keyboardActive || _keyboardTeleopWasActive)
            {
                float vx = 0f;
                float vy = 0f;
                float wz = 0f;

                if (Input.GetKey(KeyCode.W)) vx += maxVx;
                if (Input.GetKey(KeyCode.S)) vx -= maxVx;
                if (Input.GetKey(KeyCode.A)) vy -= maxVy;
                if (Input.GetKey(KeyCode.D)) vy += maxVy;
                if (Input.GetKey(KeyCode.Q)) wz += maxWz;
                if (Input.GetKey(KeyCode.E)) wz -= maxWz;

                int estop =
                    (Input.GetKey(KeyCode.Space) ||
                     Input.GetKey(KeyCode.X)) ? 1 : 0;

                SendTeleopCmd(vx, vy, wz, estop);
            }

            _keyboardTeleopWasActive = keyboardActive;
        }
        else
        {
            _keyboardTeleopWasActive = false;
        }

        virtualManualActive = IsVirtualManualCommandActive();

        // 수동 VR/WASD 이동이 끝나는 프레임에 SDK state follow를 그대로 재개하면,
        // 기존 unityFixedStartPos 기준으로 위치가 계산되어 가상 Go1이 다른 곳으로 순간이동할 수 있다.
        // 현재 가상 위치가 현재 SDK state 위치가 되도록 기준점을 먼저 재보정한다.
        bool manualCommandJustEnded =
            _wasVirtualManualCommandActive &&
            !virtualManualActive;

        if (manualCommandJustEnded &&
            driveByState &&
            driver != null &&
            enableStateFollowRebase &&
            HasSdkState())
        {
            RebaseStateFollowToCurrentVirtualPose(
                driver.transform.position,
                driver.transform.rotation,
                "manual-teleop-release"
            );
        }

        _wasVirtualManualCommandActive = virtualManualActive;

        ApplyDriverConfig(markerActive, virtualManualActive);

        // C++ state → Unity Go1 transform 동기화
        // 수동 VR/WASD 명령으로 가상을 움직이는 동안에는 state가 같은 Transform을 덮어쓰지 않는다.
        if (driveByState &&
            driver != null &&
            !(suspendStateFollowWhileManualCommand && virtualManualActive))
        {
            if (!markerActive)
            {
                bool has; double x, z, yaw;
                lock (_stateLock) { has = hasState; x = sX; z = sZ; yaw = sYaw; }

                if (has)
                {
                    if (fixUnityStartPose && !_originInited)
                    {
                        _originInited = true;
                        _originX = x; _originZ = z;
                        driver.transform.position = new Vector3(
                            unityFixedStartPos.x,
                            lockYToFixedStart ? unityFixedStartPos.y
                                              : driver.transform.position.y,
                            unityFixedStartPos.z);

                        InitBodyAxisStatePosition(
                            x,
                            z,
                            driver.transform.position
                        );

                        if (debug)
                            Debug.Log($"[UTM] FixedStart: origin=({_originX:F3},{_originZ:F3})");
                    }

                    float y = lockYToFixedStart
                        ? unityFixedStartPos.y
                        : driver.transform.position.y;

                    Vector3 desiredPos;

                    if (Mapper.useBodyAxisStateDeltaMapping)
                    {
                        // 핵심 수정:
                        // SDK 연속 위치 변화량을 SDK yaw 기준 전진/좌우로 분해하고,
                        // Unity yaw 기준으로 다시 조립한 값을 누적합니다.
                        // 이 경로에서 invertBodyAxisStateLateral가 실제로 적용됩니다.
                        desiredPos = UpdateBodyAxisStatePosition(
                            x,
                            z,
                            yaw,
                            y
                        );
                    }
                    else
                    {
                        float relX = (float)(x - _originX);
                        float relZ = (float)(z - _originZ);
                        Vector2 mappedDelta =
                            ConvertSdkRelativeXZToUnityDelta(relX, relZ);

                        desiredPos = new Vector3(
                            unityFixedStartPos.x + mappedDelta.x,
                            y,
                            unityFixedStartPos.z + mappedDelta.y
                        );
                    }

                    float yawDeg = ConvertSdkYawRadToUnityYawDeg(yaw);
                    Quaternion desiredRot = Quaternion.Euler(0f, yawDeg, 0f);

                    if (_stateUpdatedFromThread)
                    {
                        lastStateReceiveUnityTime = Time.time;
                        _stateUpdatedFromThread = false;
                    }

                    if (!smoothing || forceImmediateStateApply)
                    {
                        driver.transform.position = desiredPos;
                        driver.transform.rotation = desiredRot;
                    }
                    else
                    {
                        float dt = Time.fixedDeltaTime;
                        float aPos = 1f - Mathf.Exp(-posLerp * dt);
                        float aRot = 1f - Mathf.Exp(-rotLerp * dt);
                        driver.transform.position = Vector3.Lerp(
                            driver.transform.position, desiredPos, aPos);
                        driver.transform.rotation = Quaternion.Slerp(
                            driver.transform.rotation, desiredRot, aRot);
                    }
                }
            }
        }

        if (!driveByState && driveBySdkCmd && hasCmd && driver != null)
        {
            if (!markerActive)
                driver.SetExternalCmd(cVx, cVy, cWz, cEstop);
        }

        // 경로 완료 신호 처리 (mode=99)
        // state 적용 이후에 비교해야 driver.transform yaw와 C++ yaw가 같은 프레임 기준이 된다.
        if (_pathDoneNotify)
        {
            _pathDoneNotify = false;
            Debug.Log("[UTM] C++ 경로 완료! (mode=99)");
            LogPathDoneYawComparison();
            go1Agent?.OnPathCompleted();

            // 경로 완료 시 waypoint 마커 제거
            ClearWaypointMarkers();
        }

        // 가상 Go1 피드백 전송
        if (sendVirtualFeedback)
            SendVirtualFeedbackToCpp();

        if (debug && Time.time >= _dbgNext)
        {
            _dbgNext = Time.time + (1f / Mathf.Max(0.1f, debugPrintHz));
            string stateStr;
            lock (_stateLock)
            {
                stateStr = hasState
                    ? $"x={sX:F3} z={sZ:F3} yaw={sYaw:F3} mode={sMode}"
                    : "(none)";
            }
            Debug.Log($"[UTM] cppUnityMode={_cppUnityMode} driveByState={driveByState} " +
                      $"agentMoving={agentMoving} | {stateStr}");

            if (logCalibrationValues)
            {
                Debug.Log(
                    $"[UTM-CALIB] statePosScale={Mapper.statePosScale:F3}, xScale={Mapper.stateXScale:F3}, zScale={Mapper.stateZScale:F3}, " +
                    $"xOffset={Mapper.stateXOffset:F3}, zOffset={Mapper.stateZOffset:F3}, yawOffset={Mapper.sdkYawOffsetDeg:F2}, fineYaw={Mapper.unityYawFineOffsetDeg:F2}, " +
                    $"swapXZ={Mapper.stateSwapXZ}, invertX={Mapper.stateInvertX}, stateInvertZ={Mapper.stateInvertZ}, legacyInvertZ={Mapper.stateInvertZ}"
                );
            }
        }
    }

    // =============================================
    // Waypoint 수신 루프 (백그라운드 스레드)
    // C++에서 "WAYPOINTS count x0 z0 x1 z1 ..." 형식으로 수신
    // =============================================
    private void WaypointRecvLoop()
    {
        IPEndPoint any = new IPEndPoint(IPAddress.Any, 0);
        while (running)
        {
            try
            {
                var udp = rxWaypointUdp;
                if (udp == null) break;
                byte[] data = udp.Receive(ref any);
                if (data == null || data.Length == 0) continue;
                string s = Encoding.ASCII.GetString(data).Trim();
                if (string.IsNullOrEmpty(s)) continue;
                lock (_waypointLock) { _pendingWaypointMsg = s; }
            }
            catch (ObjectDisposedException) { break; }
            catch (SocketException)
            { if (!running) break; Thread.Sleep(5); }
            catch (Exception e)
            { if (debug) Debug.LogWarning($"[UTM] WaypointRecvLoop: {e.Message}"); Thread.Sleep(5); }
        }
    }

    // =============================================
    // Waypoint 시각화 업데이트 (메인 스레드)
    // C++ world 좌표 → Unity 좌표 변환 후 마커/라인 표시
    // =============================================
    private void UpdateWaypointVisualization(string msg)
    {
        // "WAYPOINTS count x0 z0 x1 z1 ..."
        string[] parts = msg.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 2 || parts[0] != "WAYPOINTS") return;

        if (!int.TryParse(parts[1], out int count)) return;
        if (parts.Length < 2 + count * 2) return;

        // 기존 마커 제거
        ClearWaypointMarkers();

        Vector3[] positions = new Vector3[count];
        float baseY = driver != null ? driver.transform.position.y + markerHeight : markerHeight;

        for (int i = 0; i < count; i++)
        {
            if (!float.TryParse(parts[2 + i * 2], out float wx)) continue;
            if (!float.TryParse(parts[2 + i * 2 + 1], out float wz)) continue;

            // C++ world 좌표 → Unity 좌표
            // C++ world는 로봇 시작 위치(0,0) 기준
            // Unity 시작 위치(unityFixedStartPos) 기준으로 변환
            Vector2 mappedWp = Mapper.applyMappingToWaypoints
                ? ConvertSdkRelativeXZToUnityDelta(wx, wz)
                : new Vector2(wx, wz);

            Vector3 unityPos = new Vector3(
                unityFixedStartPos.x + mappedWp.x,
                baseY,
                unityFixedStartPos.z + mappedWp.y
            );
            positions[i] = unityPos;

            // 마커(구) 생성
            GameObject marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            marker.name = $"WP_{i}";
            marker.transform.position = unityPos;
            marker.transform.localScale = Vector3.one * markerSize;

            // 콜라이더 제거 (물리 간섭 방지)
            var col = marker.GetComponent<Collider>();
            if (col) Destroy(col);

            // 색상 설정
            var rend = marker.GetComponent<Renderer>();
            if (rend)
            {
                rend.material = new Material(Shader.Find("Standard"));
                rend.material.color = waypointColor;
            }

            // 번호 표시용 이름
            marker.transform.SetParent(transform);
            _waypointMarkers.Add(marker);
        }

        // LineRenderer로 경로 선 표시
        if (_waypointLine != null)
        {
            _waypointLine.positionCount = count;
            _waypointLine.SetPositions(positions);
            _waypointLine.startColor = lineColor;
            _waypointLine.endColor = lineColor;
        }

        Debug.Log($"[UTM] Waypoint 시각화: {count}개");
    }

    private void ClearWaypointMarkers()
    {
        foreach (var m in _waypointMarkers)
            if (m != null) Destroy(m);
        _waypointMarkers.Clear();

        if (_waypointLine != null)
            _waypointLine.positionCount = 0;
    }

    private void SendVirtualFeedbackToCpp()
    {
        if (feedbackUdp == null || feedbackEp == null || driver == null) return;

        Vector3 pos = driver.transform.position;
        float unityYawDeg = driver.transform.eulerAngles.y;
        float cppYaw = ConvertUnityYawDegToSdkYawRad(unityYawDeg);

        string msg = $"{pos.x:F4} {pos.z:F4} {cppYaw:F4}";
        byte[] data = Encoding.ASCII.GetBytes(msg);

        try { feedbackUdp.Send(data, data.Length, feedbackEp); }
        catch (ObjectDisposedException) { }
        catch (Exception e)
        { if (debug) Debug.LogWarning($"[UTM] Feedback send error: {e.Message}"); }
    }

    private void ApplyDriverConfig(bool markerActive, bool virtualManualActive)
    {
        if (driver == null)
            return;

        // SDK state 위치는 UnityTeleopAndMirror가 직접 적용한다.
        driver.useExternalState = false;

        bool sdkCmdMirrorActive =
            !driveByState &&
            driveBySdkCmd &&
            hasCmd;

        driver.useExternalCmd =
            virtualManualActive ||
            sdkCmdMirrorActive;

        // UTM이 붙어 있을 때 드라이버 내부의 별도 WASD 폴백은 사용하지 않는다.
        driver.enableLegacyLocalControl = false;

        driver.coordinateMapper = Mapper;
        driver.posScale = Mapper.statePosScale;
        driver.yawOffsetDeg = Mapper.sdkYawOffsetDeg;
        driver.smoothing = smoothing;
        driver.posLerp = posLerp;
        driver.rotLerp = rotLerp;
    }

    private void StateRecvLoop()
    {
        IPEndPoint any = new IPEndPoint(IPAddress.Any, 0);

        while (running)
        {
            try
            {
                var udp = rxStateUdp;
                if (udp == null) break;

                byte[] data = udp.Receive(ref any);
                if (data == null || data.Length == 0) continue;

                // 핵심 수정:
                // C++이 빠른 주기로 state를 보내면 UDP receive buffer에 오래된 패킷이 쌓일 수 있다.
                // Unity는 과거 state를 순서대로 따라가면 z/r 보정과 실제 동작이 한참 늦게 보인다.
                // 따라서 현재 버퍼에 남아 있는 패킷을 모두 비우고, 가장 마지막 state만 파싱한다.
                if (dropOldStatePackets)
                {
                    while (udp.Available > 0)
                    {
                        byte[] latest = udp.Receive(ref any);
                        if (latest != null && latest.Length > 0)
                            data = latest;
                    }
                }

                string s = Encoding.UTF8.GetString(data).Trim();
                if (string.IsNullOrEmpty(s)) continue;

                ParseStatePacket(s);
            }
            catch (ObjectDisposedException) { break; }
            catch (SocketException)
            {
                if (!running) break;
                Thread.Sleep(1);
            }
            catch (Exception e)
            {
                if (debug) Debug.LogWarning($"[UTM] StateRecvLoop: {e.Message}");
                Thread.Sleep(1);
            }
        }
    }

    private void ParseStatePacket(string s)
    {
        if (string.IsNullOrEmpty(s))
            return;

        if (s[0] == '{')
        {
            TryParseJsonPose(s);
            return;
        }

        string[] t = s.Split(
            new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);

        if (t.Length < 10) return;

        if (!ulong.TryParse(t[0], out ulong seq)) return;
        if (!double.TryParse(t[1], out double tms)) return;
        if (!double.TryParse(t[2], out double x)) return;
        if (!double.TryParse(t[3], out double z)) return;
        if (!double.TryParse(t[4], out double yaw)) return;

        double vx = 0, vy = 0, wz = 0;
        double.TryParse(t[5], out vx);
        double.TryParse(t[6], out vy);
        double.TryParse(t[7], out wz);

        int estop = 0, mode = 0;
        int.TryParse(t[8], out estop);
        int.TryParse(t[9], out mode);

        lock (_stateLock)
        {
            sSeq = seq;
            sTms = tms;
            sX = x;
            sZ = z;
            sYaw = yaw;
            sVx = vx;
            sVy = vy;
            sWz = wz;
            sEstop = estop;
            sMode = mode;
            hasState = true;
            _stateUpdatedFromThread = true;
        }

        if (mode == 99)
            _pathDoneNotify = true;

        if (mode == 98)
        {
            lock (_stateLock)
            {
                _lastPathCancelAckSeq = seq;
                _lastPathCancelAckX = x;
                _lastPathCancelAckZ = z;
                _lastPathCancelAckYaw = yaw;
            }

            _pathCancelAckNotify = true;
            _pathCancelAckLogPending = true;
        }
    }

    private void CmdRecvLoop()
    {
        IPEndPoint any = new IPEndPoint(IPAddress.Any, 0);
        while (running)
        {
            try
            {
                var udp = rxCmdUdp;
                if (udp == null) break;
                byte[] data = udp.Receive(ref any);
                if (data == null || data.Length == 0) continue;
                string s = Encoding.UTF8.GetString(data).Trim();
                if (string.IsNullOrEmpty(s)) continue;

                if (s[0] == '{')
                {
                    var c = JsonUtility.FromJson<CmdJson>(s);
                    cVx = c.vx; cVy = c.vy; cWz = c.wz; cEstop = c.estop;
                    hasCmd = true; continue;
                }

                string[] t = s.Split(
                    new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                if (t.Length < 4) continue;
                float.TryParse(t[0], out cVx);
                float.TryParse(t[1], out cVy);
                float.TryParse(t[2], out cWz);
                int.TryParse(t[3], out cEstop);
                hasCmd = true;
            }
            catch (ObjectDisposedException) { break; }
            catch (SocketException)
            { if (!running) break; Thread.Sleep(5); }
            catch (Exception e)
            { if (debug) Debug.LogWarning($"[UTM] CmdRecvLoop: {e.Message}"); Thread.Sleep(5); }
        }
    }

    private void TryParseJsonPose(string json)
    {
        try
        {
            var p = JsonUtility.FromJson<PoseJson>(json);
            if (p == null) return;
            float yawDeg = p.yaw_deg;
            if (Mapper.invertSdkYawForUnity) yawDeg = -yawDeg;
            yawDeg += Mapper.sdkYawOffsetDeg;
            if (Mapper.applyLegacyExtra180Yaw) yawDeg += 180f;
            lock (_stateLock)
            {
                sSeq = 0; sTms = p.ts * 1000.0;
                sX = p.x; sZ = p.z;
                sYaw = NormalizeYawDeg(yawDeg) * Mathf.Deg2Rad;
                sVx = 0; sVy = 0; sWz = 0;
                sEstop = 0; sMode = 0;
                hasState = true;
                _stateUpdatedFromThread = true;
            }
        }
        catch (Exception e)
        { if (debug) Debug.LogWarning($"[UTM] JSON pose parse: {e.Message}"); }
    }

    private void OnValidate()
    {
        if (coordinateMapper != null)
            coordinateMapper.ValidateValues();
        debugPrintHz = Mathf.Max(0.1f, debugPrintHz);
        yawOffsetNotifyHz = Mathf.Max(0.1f, yawOffsetNotifyHz);
        stateReceiveBufferSize = Mathf.Max(1024, stateReceiveBufferSize);
        unityToSdkVxScale = Mathf.Max(0.0f, unityToSdkVxScale);
        minUnityToSdkVxAbs = Mathf.Max(0.0f, minUnityToSdkVxAbs);
        unityToSdkVxDeadzone = Mathf.Max(0.0f, unityToSdkVxDeadzone);
        maxUnityToSdkVxAbs = Mathf.Max(0.0f, maxUnityToSdkVxAbs);
        unityToSdkWzScale = Mathf.Max(0.0f, unityToSdkWzScale);
        minUnityToSdkWzAbs = Mathf.Max(0.0f, minUnityToSdkWzAbs);
        unityToSdkWzDeadzone = Mathf.Max(0.0f, unityToSdkWzDeadzone);
        manualCommandReleaseDelay = Mathf.Max(0.0f, manualCommandReleaseDelay);
        manualCommandActivityDeadzone = Mathf.Max(0.0f, manualCommandActivityDeadzone);
    }

    void OnGUI()
    {
        bool agentMoving = go1Agent != null && go1Agent.IsMoving();
        GUILayout.Label($"[UTM] C++모드={(_cppUnityMode ? "T=1 Unity" : "T=0 WASD")} ({virtualModeToggleKey}키 토글) driveByState={driveByState}");
        GUILayout.Label($"[UTM] agentMoving={agentMoving} enableTeleop={enableTeleop} virtualFeedback={sendVirtualFeedback}");
        GUILayout.Label($"[UTM] waypoints={_waypointMarkers.Count}개 표시중");
        lock (_stateLock)
        {
            GUILayout.Label($"[STATE] has={hasState} x={sX:F3} z={sZ:F3} " +
                            $"yaw={sYaw:F3} mode={sMode}");
        }
        if (driver != null)
        {
            GUILayout.Label($"[DRIVER] pos={driver.transform.position} yaw={driver.transform.eulerAngles.y:F1}deg");
        }
        GUILayout.Label($"[YAW] alignKey={yawAlignKey} target={targetVirtualYawDeg:F1} offset={Mapper.sdkYawOffsetDeg:F1} fine={Mapper.unityYawFineOffsetDeg:F1} legacy180={Mapper.applyLegacyExtra180Yaw}");
        GUILayout.Label($"[CMD MAP] invertVx={Mapper.commandInvertForward} invertVy={Mapper.commandInvertLateral} invertWz={Mapper.commandInvertYaw}");
        GUILayout.Label($"[MANUAL MIRROR] virtual={mirrorManualCommandToVirtual} active={IsVirtualManualCommandActive()} keyboard={enableKeyboardTeleop} rotate90={Mapper.rotateVirtualCommandForModel90Deg} scales=({Mapper.virtualCommandVxScale:F2},{Mapper.virtualCommandVyScale:F2},{Mapper.virtualCommandWzScale:F2})");
        GUILayout.Label($"[FORWARD CMD] vxScale={unityToSdkVxScale:F2} minAbs={minUnityToSdkVxAbs:F2} deadzone={unityToSdkVxDeadzone:F3} maxAbs={maxUnityToSdkVxAbs:F2}");
        GUILayout.Label($"[YAW CMD] wzScale={unityToSdkWzScale:F2} minAbs={minUnityToSdkWzAbs:F2} deadzone={unityToSdkWzDeadzone:F3}");
        GUILayout.Label($"[FIX] originInited={_originInited} origin=({_originX:F3},{_originZ:F3}) resetKey={resetOriginKey}");

        if (showCalibrationGui)
        {
            GUILayout.Label($"[CALIB] use={true} statePosScale={Mapper.statePosScale:F3} xScale={Mapper.stateXScale:F3} zScale={Mapper.stateZScale:F3}");
            GUILayout.Label($"[CALIB] xOffset={Mapper.stateXOffset:F3}m zOffset={Mapper.stateZOffset:F3}m swapXZ={Mapper.stateSwapXZ} invertX={Mapper.stateInvertX} stateInvertZ={Mapper.stateInvertZ}");
            GUILayout.Label($"[BODY AXIS] use={Mapper.useBodyAxisStateDeltaMapping} invertLateral={Mapper.invertBodyAxisStateLateral} initialized={_bodyAxisStateInited}");
        }
    }
}