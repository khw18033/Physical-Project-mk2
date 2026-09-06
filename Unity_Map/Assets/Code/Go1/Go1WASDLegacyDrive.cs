using UnityEngine;

[RequireComponent(typeof(Animation))]
[RequireComponent(typeof(CharacterController))]
[DisallowMultipleComponent]

/*
===============================================================================
Go1WASDLegacyDrive.cs
-------------------------------------------------------------------------------
GO1 디지털 트윈(유니티 모델)의 이동/회전 적용 + 애니메이션 구동 통합 드라이버

[핵심 목적]
이 스크립트는 "GO1 디지털 트윈 Transform"을 다양한 입력 소스(State/Cmd/Marker/Local)로
구동하고, 동시에 적절한 애니메이션 클립(Idle/Turn/좌우/전후)을 재생한다.

특히, 현실-가상 동기화를 위해 "마커(ArUco 등) 기반 월드 포즈"를 최우선으로 적용하는
Marker Override 모드(= TOP Priority)를 지원한다.

-------------------------------------------------------------------------------
[입력 소스 우선순위 (중요)]

Update()에서 매 프레임 다음 순서로 제어 소스를 선택한다.

1) Marker Override (최우선)
   - useMarkerOverride=true
   - markerTimeoutSec 이내에 새 마커 데이터 수신 시 active
   - ApplyMarkerPoseWorld()

2) External State (현실/SDK 상태 미러링)
   - useExternalState=true && hasState=true
   - ApplyExternalPoseWorld()

3) External Cmd (SDK 텔레옵 명령 미러링)
   - useExternalCmd=true && hasCmd=true
   - ApplyExternalCmdBody()

4) Local Legacy Control (키보드 WASD/QE 폴백)
   - 위 소스들이 없을 때만 동작
   - LegacyLocalControl()

※ Marker 데이터가 일정 시간 끊기면(markerTimeoutSec 초) 자동으로 State/Cmd로 복귀한다.

-------------------------------------------------------------------------------
[마커 기반 동기화(ANTI-JITTER 포함)]

- SetMarkerWorldPose(worldPos, yawDegOptional)
  외부(예: ArUcoUDPReceiver)에서 받은 월드 좌표를 저장하고, markerLastTime을 갱신한다.

- ApplyMarkerPoseWorld()
  1) markerWorldOffset 적용
  2) markerStabilize=true면 지터 방지 필터 적용
     - markerDeadzone 이하 변화는 무시
     - markerMaxSpeed로 프레임당 이동량 제한
     - markerFollow로 추종 강도(EMA 유사) 제어
  3) markerLockY=true면 markerFixedY로 Y 고정
  4) markerAffectsYaw=true면 yaw까지 적용(기본 false: 위치만)

-------------------------------------------------------------------------------
[State 기반 월드 포즈 적용]

- SetExternalState(x, y, yawRad, vx, vy, wz, estop, mode)
  SDK/현실로부터 받은 월드 좌표(x,y)와 yaw를 저장한다.

- ApplyExternalPoseWorld()
  - posScale, invertY, invertYaw, yawOffsetDeg 등을 적용하여 Unity 좌표로 매핑
  - smoothing 옵션으로 위치/회전 Lerp(Slerp) 적용 가능

-------------------------------------------------------------------------------
[Cmd 기반 바디 이동(텔레옵 미러)]

- SetExternalCmd(vx, vy, wz, estop)
  속도 기반으로 Transform을 이동/회전
  (월드 포즈가 아닌 "명령 따라가기" 성격)

-------------------------------------------------------------------------------
[애니메이션 구동 방식(AnimDriveMode)]

1) FromStateVel
   - sVx/sVy/sWz(상태 속도)로 클립 결정

2) FromCmdVel
   - cVx/cVy/cWz(명령 속도)로 클립 결정

3) FromTransformDelta (기본 추천)
   - 실제 Transform 변화량(Δpos, Δyaw)으로 속도/회전속도 추정 후 클립 결정
   - 외부 입력이 무엇이든(마커/상태/명령) 애니메이션이 “실제 움직임”을 따라감

-------------------------------------------------------------------------------
[중요 주의사항]

- CharacterController가 켜져 있으면 transform.position 직접 변경 시 충돌 가능
  → 마커 적용 시에는 CC를 잠시 disable 후 position/rotation 반영하는 로직 포함

- estop 또는 mode==1(stand) 상태면 Idle 유지(움직임 차단)

-------------------------------------------------------------------------------
사용 예)
- ArUcoUDPReceiver → go1Driver.SetMarkerWorldPose(targetPos)
- SDK State 수신기   → go1Driver.SetExternalState(x, y, yaw, vx, vy, wz, estop, mode)

===============================================================================
*/

public class Go1WASDLegacyDrive : MonoBehaviour
{
    [Header("Coordinate Mapper")]
    [Tooltip("방향 반전과 축 교환 체크박스는 이 컴포넌트에서만 관리합니다.")]
    public GO1CoordinateMapper coordinateMapper;

    [Header("Legacy clip names (Element 9~13)")]
    public string clipIdle     = "0Idle";
    public string clipTurnIdle = "1Idle";
    public string clipLeft     = "1LXN";
    public string clipRight    = "1LXP";
    public string clipBack     = "1LYN";
    public string clipForward  = "1LYP";

    [Header("Gravity")]
    public float gravity = 9.81f;

    [Header("Marker Override (TOP Priority)")]
    [Tooltip("true면 마커가 들어오는 동안(State/Cmd/Local보다) 항상 마커가 1순위로 transform을 잡습니다.")]
    public bool useMarkerOverride = true;

    [Tooltip("이 시간 동안 새 마커가 안 오면 마커 우선권 해제 -> State/Cmd로 자동 복귀")]
    public float markerTimeoutSec = 0.35f;

    [Tooltip("마커로 yaw까지 적용할지 (기본 false: 위치만)")]
    public bool markerAffectsYaw = false;

    [Tooltip("마커 적용 시 Y를 고정할지(바닥 고정용)")]
    public bool markerLockY = true;

    [Tooltip("markerLockY=true일 때 사용할 Y값")]
    public float markerFixedY = 0.0f;

    [Tooltip("마커 적용 시 추가 오프셋(월드 좌표)")]
    public Vector3 markerWorldOffset = Vector3.zero;

    [Header("Marker Stability Filter (ANTI JITTER)")]
    [Tooltip("마커 위치가 너무 자주 흔들릴 때 안정화 필터 사용(추천: true)")]
    public bool markerStabilize = true;

    [Tooltip("이 이하 변화는 무시 (m). 추천: 0.02~0.05")]
    public float markerDeadzone = 0.02f;

    [Tooltip("초당 이동 최대 속도 (m/s). 추천: 0.5~2.0")]
    public float markerMaxSpeed = 1.0f;

    [Tooltip("필터 추종 강도(0~1). 0.2~0.4 추천. 낮을수록 더 안정적/느림")]
    [Range(0f, 1f)] public float markerFollow = 0.2f;

    private bool markerFilterInited = false;
    private Vector3 markerFilteredPos;

    [Header("State-driven options (WORLD pose)")]
    public bool useExternalState = true;     
    public float posScale = 1.0f;
    public float yawOffsetDeg = 0f;

    // 이전 버전 호환용. State 반전은 GO1CoordinateMapper에서만 관리합니다.
    [SerializeField, HideInInspector] private bool invertY = false;
    [SerializeField, HideInInspector] private bool invertYaw = false;

    [Header("Smoothing (STATE pose)")]
    public bool smoothing = true;
    public float posLerp = 15f;
    public float rotLerp = 20f;

    [Header("Cmd-driven options (SDK teleop mirror)")]
    public bool useExternalCmd = false;    
    public float cmdToAnimDeadzone = 0.02f;  

    public enum AnimDriveMode
    {
        FromStateVel,       
        FromCmdVel,      
        FromTransformDelta   
    }

    [Header("Animation Drive Mode")]
    public AnimDriveMode animMode = AnimDriveMode.FromTransformDelta;

    [Header("Transform-delta thresholds (AnimMode=FromTransformDelta)")]
    [Tooltip("이 값 이하의 속도면 정지로 판단 (m/s).")]
    public float moveSpeedEps = 0.02f;

    [Tooltip("이 값 이상이면 '회전 중'으로 판단 (deg/s).")]
    public float yawSpeedEpsDeg = 20f;

    [Tooltip("속도/회전속도 EMA 스무딩(0~1). 1에 가까울수록 즉각 반응.")]
    [Range(0f, 1f)] public float deltaSmooth = 0.35f;

    [Tooltip("제자리 회전만 있을 때 TurnIdle을 우선 재생.")]
    public bool preferTurnIdleWhenNoMove = true;

    [Header("Debug (optional)")]
    public bool debug = false;
    public float debugHz = 5f;

    private Animation anim;
    private CharacterController cc;
    private float verticalVel;

    private bool hasState = false;
    private double sX, sY, sYaw;    
    private double sVx, sVy, sWz;   
    private int sEstop, sMode;

    private bool hasCmd = false;
    private float cVx, cVy, cWz;
    private int cEstop;

    private bool hasMarker = false;
    private float markerLastTime = -999f;
    private Vector3 markerWorldPos;
    private float markerYawDeg = 0f;

    private Vector3 _prevPos;
    private float _prevYaw;
    private bool _deltaInited;
    private float _smMove;
    private float _smYawSpd;
    private string _curClip = "";
    private float _nextDbg;

    // 이전 버전 호환용. 로컬 WASD 방향 체크박스는 GO1CoordinateMapper에서만 관리합니다.
    [SerializeField, HideInInspector] private bool SWAP_XZ = true;
    [SerializeField, HideInInspector] private bool INVERT_FORWARD = true;
    [SerializeField, HideInInspector] private bool INVERT_STRAFE = false;
    [SerializeField, HideInInspector] private bool legacyLocalFlagsMigrated = false;

    [Header("Legacy local control (fallback only)")]
    [Tooltip("UnityTeleopAndMirror 없이 이 드라이버 단독으로 WASD 이동할 때만 켭니다.")]
    public bool enableLegacyLocalControl = false;

    public float moveSpeed = 0.40f;
    public float strafeSpeed = 0.40f;
    public float rotateSpeedDeg = 110f;

    private GO1CoordinateMapper Mapper
    {
        get
        {
            if (coordinateMapper == null)
                coordinateMapper = GetComponent<GO1CoordinateMapper>();
            if (coordinateMapper == null)
                coordinateMapper = FindFirstObjectByType<GO1CoordinateMapper>();
            if (coordinateMapper == null)
                coordinateMapper = gameObject.AddComponent<GO1CoordinateMapper>();
            return coordinateMapper;
        }
    }

    private void MigrateLegacyMappingFlags()
    {
        if (legacyLocalFlagsMigrated)
            return;

        Mapper.legacyLocalSwapXZ = SWAP_XZ;
        Mapper.legacyLocalInvertForward = INVERT_FORWARD;
        Mapper.legacyLocalInvertStrafe = INVERT_STRAFE;

        // invertY/invertYaw는 UnityTeleopAndMirror가 이미 Mapper 값으로 덮어쓰던
        // 중복 체크박스였으므로 새 중앙 설정에는 추가 적용하지 않습니다.
        invertY = false;
        invertYaw = false;
        legacyLocalFlagsMigrated = true;
    }

    void Awake()
    {
        _ = Mapper;
        MigrateLegacyMappingFlags();

        anim = GetComponent<Animation>();
        cc = GetComponent<CharacterController>();

        if (!string.IsNullOrEmpty(clipIdle) && anim.GetClip(clipIdle) != null)
            anim.clip = anim.GetClip(clipIdle);

        ForceLoop(clipIdle);
        ForceLoop(clipTurnIdle);
        ForceLoop(clipLeft);
        ForceLoop(clipRight);
        ForceLoop(clipBack);
        ForceLoop(clipForward);

        InitDeltaAnim();
    }

    void OnEnable()
    {
        InitDeltaAnim();
        PlayIfValid(clipIdle);
    }

    private void InitDeltaAnim()
    {
        _prevPos = transform.position;
        _prevYaw = transform.eulerAngles.y;
        _deltaInited = true;
        _smMove = 0f;
        _smYawSpd = 0f;
        _curClip = "";
        _nextDbg = 0f;
    }

    public void SetExternalState(double x, double y, double yawRad,
                                 double vx = 0, double vy = 0, double wz = 0,
                                 int estop = 0, int mode = 0)
    {
        sX = x; sY = y; sYaw = yawRad;
        sVx = vx; sVy = vy; sWz = wz;
        sEstop = estop; sMode = mode;
        hasState = true;
    }

    public void SetExternalCmd(float vx, float vy, float wz, int estop = 0)
    {
        cVx = vx; cVy = vy; cWz = wz; cEstop = estop;
        hasCmd = true;
    }

    // SetExternalCmd() 바로 아래에 추가
    public void ResetState()
    {
        hasState = false;
        hasCmd = false;
        hasMarker = false;
        markerFilterInited = false;
        Debug.Log("[Go1WASDLegacyDrive] State 리셋 → WASD 모드");
    }

    public void SetMarkerWorldPose(Vector3 worldPos, float yawDegOptional = 0f)
    {
        markerWorldPos = worldPos;
        markerYawDeg = yawDegOptional;
        hasMarker = true;
        markerLastTime = Time.time;

        if (!markerFilterInited)
        {
            markerFilteredPos = worldPos + markerWorldOffset;
            markerFilterInited = true;
        }
    }

    void Update()
    {
        bool markerActive = useMarkerOverride && hasMarker && (Time.time - markerLastTime <= markerTimeoutSec);

        if (markerActive)
        {
            ApplyMarkerPoseWorld();
            ApplyGravityOnly();
        }
        else if (useExternalState && hasState)
        {
            ApplyExternalPoseWorld();
            ApplyGravityOnly();
        }
        else if (useExternalCmd && hasCmd)
        {
            ApplyExternalCmdBody();
            ApplyGravityOnly();
        }
        else if (enableLegacyLocalControl)
        {
            LegacyLocalControl();
        }
        else
        {
            ApplyGravityOnly();
        }

        DriveAnimationUnified();
    }

    private void ApplyMarkerPoseWorld()
    {
        Vector3 rawPos = markerWorldPos + markerWorldOffset;

        Vector3 desiredPos = rawPos;

        if (markerStabilize)
        {
            if (!markerFilterInited)
            {
                markerFilteredPos = rawPos;
                markerFilterInited = true;
            }

            float dist = Vector3.Distance(markerFilteredPos, rawPos);

            if (dist < markerDeadzone)
            {
                desiredPos = markerFilteredPos;
            }
            else
            {
                float dt = Mathf.Max(1e-4f, Time.deltaTime);
                float maxStep = markerMaxSpeed * dt;

                Vector3 stepped = Vector3.MoveTowards(markerFilteredPos, rawPos, maxStep);

                markerFilteredPos = Vector3.Lerp(markerFilteredPos, stepped, markerFollow);
                desiredPos = markerFilteredPos;
            }
        }

        if (markerLockY) desiredPos.y = markerFixedY;
        else desiredPos.y = transform.position.y;

        Quaternion desiredRot = transform.rotation;
        if (markerAffectsYaw)
            desiredRot = Quaternion.Euler(0f, markerYawDeg, 0f);

        if (!smoothing)
        {
            bool hadCC = (cc != null && cc.enabled);
            if (hadCC) cc.enabled = false;

            transform.position = desiredPos;
            if (markerAffectsYaw) transform.rotation = desiredRot;

            if (hadCC) cc.enabled = true;
            return;
        }

        float dt2 = Time.deltaTime;
        float aPos = 1f - Mathf.Exp(-posLerp * dt2);

        bool hadCC2 = (cc != null && cc.enabled);
        if (hadCC2) cc.enabled = false;

        transform.position = Vector3.Lerp(transform.position, desiredPos, aPos);

        if (markerAffectsYaw)
        {
            float aRot = 1f - Mathf.Exp(-rotLerp * dt2);
            transform.rotation = Quaternion.Slerp(transform.rotation, desiredRot, aRot);
        }

        if (hadCC2) cc.enabled = true;

        if (debug && Time.time >= _nextDbg)
        {
            _nextDbg = Time.time + 1f / Mathf.Max(0.1f, debugHz);
            Debug.Log($"[Go1MarkerTOP] raw={rawPos} filt={markerFilteredPos} desired={desiredPos} age={(Time.time - markerLastTime):F2}s dist={Vector3.Distance(markerFilteredPos, rawPos):F3}");
        }
    }
    private void ApplyExternalPoseWorld()
    {
        Vector2 mappedPos = Mapper.SdkRelativeXZToUnityDelta((float)sX, (float)sY);

        Vector3 desiredPos = new Vector3(
            mappedPos.x,
            transform.position.y,
            mappedPos.y
        );

        double yawRad = Mathf.Abs((float)sYaw) > 6.5f
            ? sYaw * Mathf.Deg2Rad
            : sYaw;

        float yawDeg = Mapper.SdkYawRadToUnityYawDeg(yawRad);
        Quaternion desiredRot = Quaternion.Euler(0f, yawDeg, 0f);

        if (!smoothing)
        {
            transform.position = desiredPos;
            transform.rotation = desiredRot;
            return;
        }

        float dt = Time.deltaTime;
        float aPos = 1f - Mathf.Exp(-posLerp * dt);
        float aRot = 1f - Mathf.Exp(-rotLerp * dt);

        transform.position = Vector3.Lerp(transform.position, desiredPos, aPos);
        transform.rotation = Quaternion.Slerp(transform.rotation, desiredRot, aRot);
    }

    private void ApplyExternalCmdBody()
    {
        if (cEstop != 0) return;

        float yawDeg = cWz * Mathf.Rad2Deg * Time.deltaTime;
        transform.Rotate(0f, yawDeg, 0f, Space.World);

        Vector3 forward = transform.forward;
        Vector3 left = -transform.right;

        Vector3 v = forward * cVx + left * cVy;
        Vector3 move = v * Time.deltaTime;

        if (cc != null) cc.Move(move);
        else transform.position += move;
    }

    private void DriveAnimationUnified()
    {
        bool estopped = (useExternalState && hasState && (sEstop != 0 || sMode == 1)) ||
                        (useExternalCmd && hasCmd && (cEstop != 0));
        if (estopped)
        {
            PlayIfValid(clipIdle);
            return;
        }

        switch (animMode)
        {
            case AnimDriveMode.FromStateVel:
                DriveAnimFromStateVel();
                break;

            case AnimDriveMode.FromCmdVel:
                DriveAnimFromCmdVel();
                break;

            case AnimDriveMode.FromTransformDelta:
            default:
                DriveAnimFromTransformDelta();
                break;
        }
    }

    private void DriveAnimFromStateVel()
    {
        float vx = (float)sVx;
        float vy = (float)sVy;
        float wz = (float)sWz;

        bool hasYaw = Mathf.Abs(wz) > 0.05f;
        bool hasMove = Mathf.Abs(vx) > cmdToAnimDeadzone || Mathf.Abs(vy) > cmdToAnimDeadzone;

        if (!hasMove)
        {
            PlayIfValid(hasYaw ? clipTurnIdle : clipIdle);
            return;
        }

        if (Mathf.Abs(vx) >= Mathf.Abs(vy))
            PlayIfValid(vx >= 0f ? clipForward : clipBack);
        else
            PlayIfValid(vy >= 0f ? clipLeft : clipRight);
    }

    private void DriveAnimFromCmdVel()
    {
        bool hasYaw = Mathf.Abs(cWz) > 0.05f;
        bool hasMove = Mathf.Abs(cVx) > cmdToAnimDeadzone || Mathf.Abs(cVy) > cmdToAnimDeadzone;

        if (!hasMove)
        {
            PlayIfValid(hasYaw ? clipTurnIdle : clipIdle);
            return;
        }

        if (Mathf.Abs(cVx) >= Mathf.Abs(cVy))
            PlayIfValid(cVx >= 0f ? clipForward : clipBack);
        else
            PlayIfValid(cVy >= 0f ? clipLeft : clipRight);
    }

    private void DriveAnimFromTransformDelta()
    {
        if (!_deltaInited) InitDeltaAnim();

        float dt = Time.deltaTime;
        if (dt <= 1e-5f) return;

        Vector3 dpWorld = (transform.position - _prevPos);
        float speed = dpWorld.magnitude / dt;

        float yawNow = transform.eulerAngles.y;
        float dyaw = Mathf.DeltaAngle(_prevYaw, yawNow);
        float yawSpd = Mathf.Abs(dyaw) / dt;

        _prevPos = transform.position;
        _prevYaw = yawNow;

        _smMove = Mathf.Lerp(_smMove, speed, deltaSmooth);
        _smYawSpd = Mathf.Lerp(_smYawSpd, yawSpd, deltaSmooth);

        bool moving = _smMove >= moveSpeedEps;
        bool turning = _smYawSpd >= yawSpeedEpsDeg;

        Vector3 dpLocal = transform.InverseTransformDirection(dpWorld);

        string want = clipIdle;

        if (moving)
        {
            if (Mathf.Abs(dpLocal.x) >= Mathf.Abs(dpLocal.z))
                want = (dpLocal.x >= 0f) ? clipForward : clipBack;
            else
                want = (dpLocal.z >= 0f) ? clipRight : clipLeft;
        }
        else
        {
            if (preferTurnIdleWhenNoMove && turning) want = clipTurnIdle;
            else want = clipIdle;
        }

        PlayIfValid(want);

        if (debug && Time.time >= _nextDbg)
        {
            _nextDbg = Time.time + 1f / Mathf.Max(0.1f, debugHz);
            Debug.Log($"[Go1Unified] smSpeed={_smMove:F3} smYawSpd={_smYawSpd:F1} moving={moving} turning={turning} dpLocal={dpLocal} clip={_curClip}");
        }
    }

    private void ApplyGravityOnly()
    {
        if (cc == null) return;

        if (cc.isGrounded) verticalVel = -0.5f;
        else verticalVel -= gravity * Time.deltaTime;

        Vector3 move = new Vector3(0f, verticalVel, 0f);
        cc.Move(move * Time.deltaTime);
    }

    private void LegacyLocalControl()
    {
        float yawInput = 0f;
        if (Input.GetKey(KeyCode.Q)) yawInput -= 1f;
        if (Input.GetKey(KeyCode.E)) yawInput += 1f;

        bool hasYaw = Mathf.Abs(yawInput) > 0.01f;
        if (hasYaw)
            transform.Rotate(0f, yawInput * rotateSpeedDeg * Time.deltaTime, 0f);

        float fwd = 0f;
        float str = 0f;

        if (Input.GetKey(KeyCode.W)) fwd += 1f;
        if (Input.GetKey(KeyCode.S)) fwd -= 1f;
        if (Input.GetKey(KeyCode.A)) str += 1f;
        if (Input.GetKey(KeyCode.D)) str -= 1f;

        if (Mapper.legacyLocalInvertForward) fwd = -fwd;
        if (Mapper.legacyLocalInvertStrafe) str = -str;

        bool hasMove = Mathf.Abs(fwd) > 0.01f || Mathf.Abs(str) > 0.01f;

        string targetClip;
        if (!hasMove) targetClip = hasYaw ? clipTurnIdle : clipIdle;
        else
        {
            if (Mathf.Abs(fwd) >= Mathf.Abs(str))
                targetClip = (fwd >= 0f) ? clipForward : clipBack;
            else
                targetClip = (str >= 0f) ? clipRight : clipLeft;
        }
        PlayIfValid(targetClip);

        Vector3 axisForward = transform.forward;
        Vector3 axisRight   = transform.right;

        Vector3 moveHorizontal;
        if (!Mapper.legacyLocalSwapXZ)
            moveHorizontal = axisForward * (fwd * moveSpeed) + axisRight * (str * strafeSpeed);
        else
            moveHorizontal = axisRight * (fwd * moveSpeed) + axisForward * (str * strafeSpeed);

        if (cc.isGrounded) verticalVel = -0.5f;
        else verticalVel -= gravity * Time.deltaTime;

        Vector3 move = moveHorizontal;
        move.y = verticalVel;
        cc.Move(move * Time.deltaTime);
    }

    private void PlayIfValid(string clipName)
    {
        if (string.IsNullOrEmpty(clipName)) return;
        var c = anim.GetClip(clipName);
        if (c == null) return;

        if (_curClip == clipName) return;

        anim.CrossFade(clipName, 0.12f);
        _curClip = clipName;
    }

    private void ForceLoop(string clipName)
    {
        if (string.IsNullOrEmpty(clipName)) return;
        var c = anim.GetClip(clipName);
        if (c == null) return;
        c.wrapMode = WrapMode.Loop;
    }
}