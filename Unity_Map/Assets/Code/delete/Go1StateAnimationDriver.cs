using UnityEngine;
[DisallowMultipleComponent]

/*
===============================================================================
Go1StateAnimationDriver.cs
-------------------------------------------------------------------------------
루트 Transform의 이동/회전(Delta)을 기반으로 GO1 애니메이션 클립을 자동 선택하여
재생하는 “Transform-Delta 기반 애니메이션 드라이버”

[개요]
이 스크립트는 로봇(또는 캐릭터)의 root Transform이
월드에서 얼마나 움직였는지(속도)와 얼마나 회전했는지(yaw 회전속도)를 측정한 뒤,
그 결과로 다음과 같은 상태를 판정한다:

- 정지(Idle)
- 제자리 회전(TurnIdle)
- 전진/후진/좌/우 이동(Forward/Back/Left/Right)

즉, 네트워크 state/cmd 값을 직접 읽지 않고도
“Transform이 움직이는 것만으로” 애니메이션이 자연스럽게 따라오게 만든다.

-------------------------------------------------------------------------------
[사용 시나리오]

- UnityTeleopAndMirror / Go1WASDLegacyDrive 등이 root.position/rotation을 갱신
  → 본 스크립트는 그 결과만 보고 애니메이션을 자동 재생
- 마커(ArUco)로 포즈가 덮어써져도 Transform이 변하면 애니메이션이 반영됨
- 외부 상태 입력이 다양한 프로젝트에서 애니메이션 로직을 독립적으로 유지 가능

-------------------------------------------------------------------------------
[핵심 동작 원리]

Update()
  1) 이전 프레임 root 위치/각도 저장값(_prevPos, _prevYaw)과 비교
  2) 이동 속도(speed) 계산:
       speed = |root.position - prevPos| / dt
  3) yaw 회전 속도(yawSpd) 계산:
       dyaw = DeltaAngle(prevYaw, yawNow)
       yawSpd = |dyaw| / dt    (deg/s)
  4) EMA(지수 이동 평균) 형태로 스무딩:
       _smMove   = Lerp(_smMove, speed, smooth)
       _smYawSpd = Lerp(_smYawSpd, yawSpd, smooth)
  5) 임계값으로 moving/turning 판정:
       moving  = _smMove   >= moveSpeedEps
       turning = _smYawSpd >= yawSpeedEpsDeg
  6) 이동 방향 판정:
       dpLocal = root.InverseTransformDirection(dpWorld)
       dpLocal.z가 크면 전/후, dpLocal.x가 크면 좌/우로 간주
  7) 해당 클립을 CrossFade로 전환 재생

-------------------------------------------------------------------------------
[파라미터 설명]

- moveSpeedEps:
  - 이 값 이하 속도면 “정지”로 판단
  - 너무 작으면 지터로 계속 움직임으로 판정될 수 있음

- yawSpeedEpsDeg:
  - 이 값 이상 yaw 회전 속도면 “회전 중”으로 판단

- smooth (0~1):
  - 속도/회전속도 스무딩 계수
  - 낮을수록 더 안정적(느리게 반응), 높을수록 즉각 반응

- preferTurnIdleWhenNoMove:
  - 이동은 없지만 회전만 있는 경우 TurnIdle을 우선 재생

-------------------------------------------------------------------------------
[클립 이름 주의]

- clip 이름은 Animation 컴포넌트에 등록된 clip 이름과 정확히 일치해야 한다.
- 누락된 클립이면 재생하지 않고 경고 출력(debug=true일 때)

-------------------------------------------------------------------------------
[주의사항]

- 이 스크립트는 “Transform 변화”에만 의존한다.
  즉, 애니메이션을 위해서는 root가 실제로 움직이거나 회전해야 한다.
- root가 부모에 의해 움직이고, 자식만 움직이는 구조라면 root 지정이 중요
- Update 기반이므로 FixedUpdate로 포즈가 변해도 정상 동작하지만,
  dt가 매우 작거나 0에 가까우면 계산을 생략한다.

-------------------------------------------------------------------------------
[확장 가능]

- 대각선 이동(Forward+Left 등) 클립 추가
- 회전 방향(좌/우) 판정 후 별도 TurnLeft/TurnRight 클립 지원
- 이동 속도에 따른 애니메이션 속도(anim[clip].speed) 자동 조절
- 네트워크 state 기반 모드와 transform-delta 기반 모드 혼합 지원

===============================================================================
*/

public class Go1StateAnimationDriver : MonoBehaviour
{
    [Header("Refs")]
    public Animation anim;                 
    public Transform root;            

    [Header("Clip Names (match your Animation list)")]
    public string clipIdle     = "0Idle";
    public string clipTurnIdle = "1Idle";
    public string clipLeft     = "1LXN";
    public string clipRight    = "1LXP";
    public string clipBack     = "1LYN";
    public string clipForward  = "1LYP";

    [Header("Detection Thresholds")]
    [Tooltip("이 값 이하의 속도면 정지로 판단 (m/s).")]
    public float moveSpeedEps = 0.02f;

    [Tooltip("이 값 이상이면 '회전 중'으로 판단 (deg/s).")]
    public float yawSpeedEpsDeg = 20f;

    [Header("Smoothing")]
    [Tooltip("속도/회전속도 EMA 스무딩(0~1). 1에 가까울수록 즉각 반응.")]
    [Range(0f, 1f)] public float smooth = 0.35f;

    [Header("Priority")]
    [Tooltip("제자리 회전만 있을 때 TurnIdle을 우선 재생.")]
    public bool preferTurnIdleWhenNoMove = true;

    [Header("Debug")]
    public bool debug = false;
    public float debugHz = 5f;

    private Vector3 _prevPos;
    private float _prevYaw;
    private bool _inited;

    private float _smMove;   
    private float _smYawSpd; 

    private string _curClip = "";
    private float _nextDbg;

    void Reset()
    {
        root = transform;
        anim = GetComponent<Animation>();
    }

    void Awake()
    {
        if (root == null) root = transform;
        if (anim == null) anim = GetComponent<Animation>();
    }

    void OnEnable()
    {
        InitPrev();
        PlayIfExists(clipIdle);
    }

    void InitPrev()
    {
        _prevPos = root.position;
        _prevYaw = root.eulerAngles.y;
        _inited = true;
        _smMove = 0f;
        _smYawSpd = 0f;
    }

    void Update()
    {
        if (anim == null || root == null) return;

        if (!_inited) InitPrev();

        float dt = Time.deltaTime;
        if (dt <= 1e-5f) return;

        Vector3 dpWorld = (root.position - _prevPos);
        float speed = dpWorld.magnitude / dt;

        float yawNow = root.eulerAngles.y;
        float dyaw = Mathf.DeltaAngle(_prevYaw, yawNow);    
        float yawSpd = Mathf.Abs(dyaw) / dt;                  

        _prevPos = root.position;
        _prevYaw = yawNow;

        _smMove = Mathf.Lerp(_smMove, speed, smooth);
        _smYawSpd = Mathf.Lerp(_smYawSpd, yawSpd, smooth);

        bool moving = _smMove >= moveSpeedEps;
        bool turning = _smYawSpd >= yawSpeedEpsDeg;

        Vector3 dpLocal = root.InverseTransformDirection(dpWorld);
        string want = clipIdle;

        if (moving)
        {
            if (Mathf.Abs(dpLocal.z) >= Mathf.Abs(dpLocal.x))
                want = (dpLocal.z >= 0f) ? clipForward : clipBack;
            else
                want = (dpLocal.x >= 0f) ? clipRight : clipLeft;
        }
        else
        {
            if (preferTurnIdleWhenNoMove && turning)
                want = clipTurnIdle;
            else
                want = clipIdle;
        }

        PlayIfExists(want);

        if (debug && Time.time >= _nextDbg)
        {
            _nextDbg = Time.time + 1f / Mathf.Max(0.1f, debugHz);
            Debug.Log($"[Go1Anim] speed={_smMove:F3} yawSpd={_smYawSpd:F1} moving={moving} turning={turning} dpLocal={dpLocal} clip={_curClip}");
        }
    }

    private void PlayIfExists(string clip)
    {
        if (string.IsNullOrEmpty(clip)) return;
        if (_curClip == clip) return;

        if (anim.GetClip(clip) == null)
        {
            if (debug) Debug.LogWarning($"[Go1Anim] Missing clip: {clip}");
            return;
        }

        anim.CrossFade(clip, 0.08f);
        _curClip = clip;
    }
}
