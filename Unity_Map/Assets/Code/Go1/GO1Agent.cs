using UnityEngine;
using Unity.MLAgents;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;
using Unity.MLAgents.Demonstrations;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Globalization;

[RequireComponent(typeof(GO1PathPlanner))]
[RequireComponent(typeof(GO1ReplanController))]
public class GO1Agent : Agent
{
    public Transform target;
    private Go1WASDLegacyDrive wasdDrive;
    private CharacterController cc;

    public Transform startPoint;
    public GO1LocalPathUdpSender pathSender;
    public GO1AutoNavigator navigator;
    public TrainingManager trainingManager;

    [Header("Mission Key Settings")]
    [Tooltip("자율주행 경로 생성을 시작하는 키. 이동 중에는 다시 눌러도 정지하지 않고 무시합니다.")]
    public KeyCode startMissionKey = KeyCode.M;

    [Tooltip("자율주행/재탐색/실제 GO1 경로 추종을 즉시 정지하는 키.")]
    public KeyCode stopMissionKey = KeyCode.N;

    [Header("Virtual Agent Movement")]
    public float moveSpeed = 0.4f;
    public float rotateSpeedDeg = 110f;

    [Header("Virtual Planning Speed")]
    [Tooltip("M키로 가상 GO1이 경로 생성할 때만 적용되는 이동 속도 배율. 현실 GO1 속도에는 영향 없음.")]
    public float virtualPlanSpeedMultiplier = 3.0f;

    [Tooltip("M키로 가상 GO1이 경로 생성할 때만 적용되는 회전 속도 배율. 현실 GO1 속도에는 영향 없음.")]
    public float virtualPlanRotateMultiplier = 3.0f;


    // 파생 Agent가 도착 거리만 변경할 수 있도록 만든 확장 지점.
    // 기존 GO1Agent는 0.3m, BoatAgent는 Inspector 값 사용.
    protected virtual float GoalArrivalDistance => 0.3f;

    // 파생 Agent가 생성 경로를 C++로 보내지 않고 Unity에서 직접 재생할 수 있도록 만든 확장 지점.
    // 기존 GO1Agent는 false이므로 기존 동작이 전혀 바뀌지 않는다.
    protected virtual bool UseLocalGeneratedPathReplay => false;
    protected virtual bool LocalReplayUseRawRecordedPath => false;
    protected virtual float LocalReplayMoveSpeed => moveSpeed * virtualPlanSpeedMultiplier;
    protected virtual float LocalReplayRotateSpeedDeg => rotateSpeedDeg;
    protected virtual float LocalReplayWaypointTolerance => 0.75f;
    protected virtual float LocalReplayTimeoutSeconds => 180f;

    // BoatAgent가 로컬 재주행 중 부표를 만났을 때
    // 직접 NavMesh 코너를 따라가는 대신 ML-Agent 정책으로 새 경로를 다시 생성하기 위한 확장 지점.
    protected virtual bool EnableLocalReplayMlAgentReplan => false;

    // 0 이하면 한 미션 안에서 재탐색 횟수 제한 없음.
    protected virtual int LocalReplayMlAgentReplanLimit => 0;

    // NavMeshObstacle carving 반영을 기다리는 기본 시간.
    protected virtual float LocalReplayMlAgentReplanDelay => 0.6f;

    // carving 후 완전한 NavMesh 경로가 생길 때까지 기다리는 최대 시간.
    protected virtual float LocalReplayMlAgentReplanReadyTimeout => 5f;

    private bool localPathReplayActive = false;
    private Coroutine localPathReplayCoroutine = null;
    private readonly List<Vector3> localReplayPath = new List<Vector3>();

    private bool localReplayMlAgentReplanPending = false;
    private bool localReplayMlAgentPathGenerationActive = false;
    private Coroutine localReplayMlAgentReplanCoroutine = null;
    private int localReplayMlAgentReplanCount = 0;

    [Header("Wall Clearance Reward")]
    // 이 구역은 벽과의 거리, 복도 중앙 정렬, 레이 캐스트 범위를 조정하는 보상 파라미터들이다.
    // 값이 커질수록 벽에서 멀어지고 중앙을 더 선호하지만, 지나치면 좁은 통로에서 정체가 생길 수 있다.
    [Tooltip("옆 벽이 이 거리(m)보다 가까워지면 근접 패널티. 좁은 복도에서 벽에 비비는 것을 막는다.")]
    public float wallClearanceThreshold = 0.4f;

    [Tooltip("옆 벽 근접 패널티 가중치. 클수록 벽에서 더 멀리 떨어지려 한다.")]
    public float wallClearancePenaltyWeight = 0.03f;

    [Tooltip("옆 벽 간격을 측정하는 최대 레이 거리(m). 이 거리 안에 양쪽 다 벽이 있으면 복도로 간주.")]
    public float wallClearanceRayDistance = 1.5f;

    [Tooltip("양쪽 모두 벽이 있을 때(복도) 가운데로 정렬하면 주는 보상 가중치.")]
    public float corridorCenteringWeight = 0.01f;

    [Tooltip("벽 간격 레이가 무시할 레이어(다른 에이전트 레이어 7~12은 자동 제외).")]
    public LayerMask wallClearanceMask = ~0;

    [Header("Sensor Gizmo Debug")]
    [Tooltip("Scene 뷰에서 16방향 SphereCast 센서를 보이게 그립니다.")]
    public bool drawSensorGizmos = true;

    [Tooltip("센서 Gizmo의 최대 길이(m). 실제 SphereCast 거리와 같게 두는 것이 좋습니다.")]
    public float sensorGizmoLength = 3f;

    [Tooltip("센서 Gizmo를 그릴 때 사용하는 구체 반경. 실제 캐스트 반경과 맞추면 해석이 쉽습니다.")]
    public float sensorGizmoRadius = 0.08f;

    [Tooltip("Scene 뷰에서 NavMesh 경로와 현재 타깃 웨이포인트(코너)를 표시합니다. 코너를 미리 자르는지 눈으로 확인할 때 사용.")]
    public bool drawWaypointGizmos = true;

    [Header("Evaluation Mode")]
    [Tooltip("Inference Only(프리팹 onnx로 mlagents 없이 Play)로 평가할 때 켠다. 켜면 mlagents 연결이 없어도 학습과 동일한 평가 루프(목표 리셋, 도달 기록, 이동)가 돌아 깨끗한 csv가 쌓인다. 실제 GO1 가상경로(M키) 워크플로를 쓸 땐 끈다.")]
    public bool evaluationMode = false;

    [Tooltip("ONNX 평가에서 자동으로 종료할 완료 trial 수. 0 이하면 횟수 제한 없이 계속 평가합니다.")]
    [Min(0)]
    public int maxEvaluationTrials = 30;

    [Tooltip("최대 평가 횟수에 도달하면 Unity Editor의 Play Mode를 자동으로 종료합니다. 빌드에서는 Application.Quit을 호출합니다. 해제하면 마지막 상태에서 평가만 멈춥니다.")]
    public bool stopPlayModeWhenEvaluationComplete = true;

    [Tooltip("코너 자르기 거리. 다음 코너에 이 거리(m)보다 가까워지면 그 다음 코너로 타깃을 넘긴다. 작게 할수록 코너에 더 바짝 붙어 돈다. (코드의 GetNextWaypoint 0.5f와 같은 의미, Gizmo 표시에 사용)")]
    public float waypointSwitchDistance = 0.5f;

    private int completedEvaluationTrialCount = 0;
    private bool evaluationLimitReached = false;
    private bool evaluationStopRequested = false;

    private float previousPathDist;
    private float previousWaypointDist;

    private DemonstrationRecorder recorder;
    private bool isDemoMode = false;
    private TrainingEpisodeLogger trainingEpisodeLogger;
    private RealGo1CaseStudyLogger caseStudyLogger;

    private int stuckCount = 0;
    private float wallHitCount = 0;
    private bool isArrived = false;
    private bool canMove = false;

    [Header("Managed C2/C3 Decision Requests")]
    [Tooltip("C2/C3 관리형 평가 중 DecisionRequester가 없거나 비활성화된 경우 수동으로 결정을 요청하는 주기입니다.")]
    [Min(1)]
    public int managedEvaluationDecisionPeriod = 5;

    private DecisionRequester managedDecisionRequester;
    private bool managedEvaluationRunActive = false;
    private int managedEvaluationDecisionCounter = 0;

    // C++ path follower가 실제 GO1을 waypoint 경로로 이동 중인지 표시
    // M키를 다시 눌렀을 때 Unity 가상 미션뿐 아니라 현실 GO1 경로도 취소하기 위해 사용
    private bool realGo1PathActive = false;

    // C++에 path JSON을 보낸 뒤, PATH_DONE/STOP/CANCEL 전까지 해당 경로 명령을 소유 중인지 표시한다.
    // realGo1PathActive는 state_change=true일 때만 true가 되고, 이 값은 미션 중복 시작 방지용이다.
    private bool realGo1PathCommandSent = false;

    private bool episodeFailed = false;
    private bool episodeEnding = false;
    private Vector3 lastStartPos;
    private Quaternion lastStartRot;
    private int retryCount = 0;
    public int maxRetryCount = 20;

    private UnityTeleopAndMirror utm;
    private UnityEngine.AI.NavMeshAgent navAgent;
    private UnityEngine.AI.NavMeshPath navPath;

    [Header("Path Planning Component")]
    [Tooltip("NavMesh 경로 생성과 유효성 검사를 담당합니다. 비워두면 같은 GameObject에서 찾고, 없으면 실행 시 자동 추가합니다.")]
    public GO1PathPlanner pathPlanner;

    [Header("Replanning Component")]
    [Tooltip("동적 장애물 차단 판정, PATH_CANCEL, 재탐색 및 재전송 흐름을 담당합니다. 비워두면 같은 GameObject에서 자동 연결합니다.")]
    public GO1ReplanController replanController;

    [Header("C2/C3 Managed Evaluation")]
    [Tooltip("Unity C2/C3 쌍대평가 흐름을 관리합니다. 비워두면 Scene에서 자동 탐색합니다.")]
    public C2C3EvaluationManager c2c3EvaluationManager;

    private const float RuntimeWaypointSwitchDistance = 0.05f;

    [Header("Path Recording")]
    private List<Vector3> recordedPath = new List<Vector3>();
    public float pathRecordInterval = 0.05f;
    private float lastRecordTime = 0f;
    private Vector3 lastRecordedPos = Vector3.zero;
    public float minMoveThreshold = 0.03f;

    [Header("Recorded Path Transfer")]
    [Tooltip("체크하면 recordedPath 원본을 거의 그대로 C++에 전송. 체크 해제 시 아래 설정으로 점 개수를 줄여 전송.")]
    public bool sendRecordedPathAsIs = false;

    [Tooltip("Douglas-Peucker 경로 단순화 허용 오차. 값이 클수록 점이 많이 줄어듦.")]
    public float simplifyTolerance = 0.15f;

    [Tooltip("C++로 보낼 waypoint 사이 최소 거리.")]
    public float minSendPointSpacing = 0.15f;

    [Tooltip("C++로 보낼 waypoint 최대 개수.")]
    public int maxSendPointCount = 50;

    [Tooltip("이 각도 이상 꺾이는 지점은 코너로 판단해서 유지.")]
    public float cornerKeepAngleDeg = 12f;

    [Header("Blocked Detection")]
    [Tooltip("M 시작 전에 NavMesh 경로가 목표까지 완전한지 검사.")]
    public bool enableNavMeshPreCheck = true;

    [Tooltip("M 시작 전에 NavMesh 경로 위 실제 장애물 Collider를 CapsuleCast로 검사.")]
    public bool enablePhysicalPathCheck = false;

    [Tooltip("실제 장애물 검사에 사용할 레이어. 분홍 장애물/벽 Layer를 넣으면 됨.")]
    public LayerMask obstacleLayerMask;

    public float pathCheckRadius = 0.25f;
    public float pathCheckHeight = 0.5f;

    [Tooltip("가상 이동 중 앞으로 가라고 했는데 실제 이동이 거의 없으면 막힘으로 판단.")]
    public bool enableStuckDetection = true;

    public float blockedMoveThreshold = 0.01f;
    public int blockedFrameLimit = 80;
    private int blockedFrameCount = 0;

    private float previousTurn = 0f;
    private float previousMove = 0f;
    private int previousCornerCount = -1;

    private int pathFailCount = 0;
    private const int maxPathFailCount = 30;

    private float _keepAliveInterval = 0.05f;
    private float _lastKeepAliveTime = 0f;

    // M을 누른 순간의 시작 위치/회전.
    // 다음 M을 누르면 현재 실제 GO1 state를 따라간 가상 GO1의 pose가 새 시작 기준이 된다.
    private Vector3 missionStartPosition;
    private Quaternion missionStartRotation;

    [Header("Actual GO1 Point Trace")]
    [Tooltip("C++ state로 실제 GO1이 움직이는 경로를 초록색 점들로 표시")]
    public bool showActualGo1PointTrace = true;

    [Tooltip("실제 GO1 경로 점들을 선으로도 연결")]
    public bool connectActualGo1Points = true;

    [Tooltip("새 경로 시작 시 이전 실제 GO1 점 표시를 삭제")]
    public bool clearActualTraceOnNewRun = true;

    [Tooltip("실제 GO1 경로 점 색상")]
    public Color actualGo1PointColor = Color.green;

    [Tooltip("실제 GO1 경로 선 색상")]
    public Color actualGo1LineColor = Color.green;

    [Tooltip("실제 GO1 경로 점 크기")]
    public float actualGo1PointRadius = 0.08f;

    [Tooltip("실제 GO1 경로 선 두께")]
    public float actualGo1LineWidth = 0.06f;

    [Tooltip("실제 GO1 경로를 몇 초마다 기록할지")]
    public float actualTraceRecordInterval = 0.05f;

    [Tooltip("이 거리 이상 움직였을 때만 실제 GO1 경로 점 추가")]
    public float actualTraceMinMoveThreshold = 0.03f;

    [Tooltip("실제 GO1 경로 표시 높이 오프셋")]
    public float actualTraceYOffset = 0.15f;

    [Tooltip("실제 GO1 점 이름에 번호를 붙임")]
    public bool nameActualTracePoints = true;

    private bool actualTraceRecording = false;
    private float lastActualTraceRecordTime = 0f;
    private Vector3 lastActualTraceRecordedPos = Vector3.zero;
    private readonly List<Vector3> actualTracePoints = new List<Vector3>();
    private readonly List<GameObject> actualTracePointObjects = new List<GameObject>();
    private GameObject actualTraceRoot;
    private LineRenderer actualTraceLine;

    [Header("Runtime Obstacle Replanning")]
    [Tooltip("실제 GO1이 경로를 따라 이동하는 동안 새 JSON 장애물이 현재 경로를 막으면 정지 후 재탐색한다.")]
    public bool enableRuntimeReplanning = true;

    [Tooltip("장애물을 만났을 때 경로 재설정을 켜고 끄는 스위치. false면 장애물이 경로를 막아도 재탐색하지 않는다.")]
    public bool enableObstacleTriggeredReplan = true;

    [Tooltip("한 번의 M키 미션 동안 장애물에 의한 경로 재설정을 몇 번까지 허용할지 설정한다. 기본값 1이면 딱 한 번만 재탐색한다.")]
    public int maxObstacleReplanCountPerMission = 1;

    [Tooltip("재탐색 가능 횟수를 넘겼을 때 경고 로그를 출력한다.")]
    public bool printReplanLimitLog = true;

    [Tooltip("재탐색이 너무 자주 반복되지 않도록 막는 최소 간격(초)")]
    public float replanCooldown = 1.5f;

    [Tooltip("장애물 bounds에 추가로 더하는 경로 차단 판정 여유 반경")]
    public float pathBlockCheckRadius = 0.25f;

    [Tooltip("장애물 bounds 크기에 추가로 더하는 여유값")]
    public float obstacleBoundsMargin = 0.05f;

    [Tooltip("PATH_CANCEL/정지 명령 후 실제 state가 Unity에 반영될 때까지 대기하는 시간")]
    public float replanStopWaitTime = 0.3f;

    [Tooltip("NavMeshObstacle carving이 반영될 때까지 대기하는 시간")]
    public float navMeshCarvingWaitTime = 0.35f;

    [Tooltip("재탐색 관련 로그 출력")]
    public bool debugRuntimeReplan = true;

    [Tooltip("재탐색으로 새 경로를 전송한 뒤, 이 시간 동안 추가 재탐색을 막고 JSON 장애물 처리를 일시 중지한다.")]
    public float postReplanLockSeconds = 5.0f;

    [Header("Safe Path Cancel / Resend")]
    [Tooltip("재탐색 전 PATH_CANCEL과 정지 명령을 여러 번 보내 C++ path follower의 기존 경로를 확실히 지운다.")]
    public bool useSafeCancelBeforeReplan = true;

    [Tooltip("재탐색 전 PATH_CANCEL 반복 전송 횟수")]
    public int cancelRepeatCount = 3;

    [Tooltip("PATH_CANCEL 반복 전송 간격")]
    public float cancelRepeatInterval = 0.10f;

    [Tooltip("마지막 PATH_CANCEL 이후 새 경로 탐색을 시작하기 전 대기 시간")]
    public float cancelToReplanWaitTime = 0.45f;

    [Tooltip("PATH_CANCEL 전송 후 C++이 mode=98 CANCEL_ACK를 보낼 때까지 기다린다.")]
    public bool waitForCancelAckBeforeReplan = true;

    [Tooltip("C++ CANCEL_ACK(mode=98)를 기다리는 최대 시간. timeout이어도 기존 시간 대기 방식으로 계속 진행한다.")]
    public float cancelAckTimeout = 3.0f;

    [Tooltip("재탐색 직전에 Unity 가상 GO1 pose를 C++ state가 반영된 실제 GO1 pose로 다시 맞춘다.")]
    public bool syncPoseToSdkBeforeReplan = true;

    [Tooltip("재탐색 pose 동기화 로그 출력")]
    public bool debugReplanPoseSync = true;

    [Header("Manual Mission Start Sync")]
    [Tooltip("M키로 새 경로를 시작하기 직전에 C++ state 기준 pose로 가상 GO1을 한 번 더 동기화한다.")]
    public bool syncPoseToSdkBeforeManualMission = true;

    [Tooltip("Z키 yaw 보정 등 외부 보정이 들어왔을 때 GO1Agent missionStartRotation도 같은 yaw 기준으로 갱신한다.")]
    public bool allowExternalYawSync = true;

    [Tooltip("M키 시작 직전 pose 동기화 로그 출력")]
    public bool debugManualStartPoseSync = true;

    [Tooltip("estop=1 정지 후 재탐색 전에 estop=0 해제 명령을 보낼지 여부")]
    public bool releaseEstopBeforeReplan = true;

    [Tooltip("estop=0 해제 명령 후 재탐색 전 대기 시간")]
    public float estopReleaseWaitTime = 0.20f;

    [Tooltip("새 path를 너무 빠르게 연속 전송하지 않도록 막는 최소 간격")]
    public float minPathSendInterval = 0.50f;

    [Header("Runtime Replan Generated Path Retry")]
    [Tooltip("재탐색으로 새로 만든 경로가 장애물을 통과하거나 너무 짧으면, C++로 보내지 않고 다시 경로를 생성합니다.")]
    public bool retryRuntimeReplanWhenGeneratedPathInvalid = true;

    [Tooltip("재탐색 경로가 이상할 때 추가로 다시 경로를 생성하는 최대 횟수. 3이면 최초 재탐색 실패 후 최대 3번 더 시도합니다.")]
    public int maxRuntimeReplanGenerateRetryCount = 3;

    [Tooltip("재탐색 경로 재생성 사이 대기 시간. NavMeshObstacle carving 반영 시간을 주기 위한 값입니다.")]
    public float runtimeReplanRetryDelay = 0.35f;

    [Tooltip("C++로 보내기 직전 최종 경로가 장애물 Collider를 통과하는지 검사합니다.")]
    public bool validateGeneratedPathBeforeSend = true;

    [Tooltip("단순화된 경로가 막혀 있으면 recordedPath 원본 경로로 한 번 더 검사하고, 가능하면 원본 경로를 보냅니다.")]
    public bool fallbackToRawRecordedPathWhenGeneratedPathBlocked = true;

    [Tooltip("최종 경로 검사에서 Trigger Collider도 장애물로 취급합니다.")]
    public bool includeTriggerCollidersInGeneratedPathValidation = true;

    [Tooltip("재탐색 경로 재생성 관련 로그 출력")]
    public bool debugRuntimeReplanRetry = true;

    [Header("Fire Landmark Correction Replan")]
    [Tooltip("소화기 landmark 보정을 GO1Agent 재탐색 흐름과 연결합니다.")]
    public bool enableFireLandmarkCorrectionReplan = true;

    [Tooltip("현실 GO1이 path follower로 이동 중 소화기가 near로 처음 보이면 PATH_CANCEL 후 보정하고 재탐색합니다.")]
    public bool cancelAndReplanOnFireLandmarkWhileRealPath = true;

    [Tooltip("한 번의 M키 미션 중 이동 중 소화기 보정 재탐색 허용 횟수. 기본 1회.")]
    public int maxFireCorrectionReplanDuringPathPerMission = 1;

    [Tooltip("경로 완료 후 near 소화기가 보였을 때 적용할 소화기 보정 허용 횟수. 기본 1회.")]
    public int maxFireCorrectionAfterPathDonePerMission = 1;

    [Tooltip("소화기 보정/재탐색 최소 간격. 같은 소화기를 계속 보며 반복 재탐색하는 것을 막습니다.")]
    public float fireCorrectionReplanCooldown = 10.0f;

    [Tooltip("이 거리보다 작은 소화기 보정량은 무시합니다.")]
    public float fireCorrectionMinDeltaM = 0.15f;

    [Tooltip("소화기 보정 재탐색 로그 출력")]
    public bool debugFireCorrectionReplan = true;

    [Header("Fire Landmark Correction Axis")]
    [Tooltip("소화기 기준 보정 적용 시 X축 보정 방향을 반전합니다.")]
    public bool invertFireCorrectionX = false;

    [Tooltip("소화기 기준 보정 적용 시 Z축 보정 방향을 반전합니다. 보정된 가상 GO1 위치가 Z축 방향으로 대칭이면 켜세요.")]
    public bool invertFireCorrectionZ = true;

    [Header("Real GO1 Motion State Gate")]
    [Tooltip("5009번 포트의 state_change JSON을 처리하는 Go1ObstacleJsonReceiver. 비워두면 자동 탐색합니다.")]
    public Go1ObstacleJsonReceiver obstacleReceiver;

    [Tooltip("경로 전송 직후 realGo1PathActive를 바로 true로 하지 않고, state_change=true가 들어올 때까지 대기합니다.")]
    public bool waitForStateChangeTrueBeforeRealPathActive = true;

    [Tooltip("이 값이 true면 경로 전송 이후 새로 들어온 state_change=true만 시작 신호로 인정합니다. 이전 미션의 stale true를 막기 위해 true 권장.")]
    public bool requireFreshStateChangeAfterPathSend = true;

    [Tooltip("state_change=true를 기다리는 최대 시간. 0 이하면 무한 대기합니다.")]
    public float realGo1StartWaitTimeoutSec = 5.0f;

    [Tooltip("대기 시간이 초과되었을 때도 강제로 실제 경로 추종 상태로 전환할지 여부. state_change 기준만 쓰려면 false 유지.")]
    public bool activateRealPathOnStateWaitTimeout = false;

    [Tooltip("state_change=true 대기 시간이 초과되면, 방금 C++로 보냈던 동일 경로를 다시 전송합니다.")]
    public bool resendPathOnStateChangeTimeout = true;

    [Tooltip("한 번 생성한 경로에 대해 state_change timeout 후 재전송할 최대 횟수. 1이면 한 번만 다시 보냅니다.")]
    public int maxStateChangeTimeoutPathResendCount = 1;

    [Tooltip("timeout 후 같은 경로를 다시 보내기 전 추가 대기 시간. C++ 수신/UDP 처리 꼬임을 줄이기 위한 값입니다.")]
    public float stateChangeTimeoutPathResendDelay = 0.25f;

    [Tooltip("real GO1 시작 대기/state_change 관련 로그 출력")]
    public bool debugRealGo1StartWait = true;

    [Tooltip("realGo1PathActive 상태를 5009번 state_change=false와 동기화합니다. false가 들어오면 실제 이동 중이 아닌 것으로 표시합니다.")]
    public bool syncRealPathActiveFalseFromStateChange = true;

    [Tooltip("state_change=false가 한 번 들어왔다고 바로 가상 GO1 추종을 끄지 않고, 지정 시간 동안 false가 유지될 때만 끕니다. true/false가 섞여 들어오는 환경에서는 true 권장.")]
    public bool requireContinuousFalseBeforeDisablingRealPath = true;

    [Tooltip("state_change=false가 이 시간 이상 연속 유지되어야 driveByState를 끕니다. 너무 짧으면 true 직후 false 패킷 때문에 가상 GO1이 멈출 수 있습니다.")]
    public float realGo1FalseStateHoldSec = 0.8f;

    [Header("Fire Correction Before Path Planning")]
    [Tooltip("M키로 경로를 만들기 직전에 5009 큐에 쌓인 JSON을 먼저 처리해서 소화기 landmark 보정을 먼저 적용합니다.")]
    public bool processQueuedJsonBeforeManualMission = true;

    [Tooltip("가상 GO1이 목표에 도달해서 C++로 path를 보내기 직전에 큐에 쌓인 JSON을 먼저 처리합니다. 소화기 보정이 적용되면 기존 경로는 버리고 다시 경로를 만듭니다.")]
    public bool processQueuedJsonBeforePathSend = true;

    [Tooltip("경로 생성/전송 직전에 한 번에 처리할 5009 JSON 최대 개수입니다.")]
    public int maxPreMissionJsonPackets = 50;

    [Tooltip("C++로 path를 보내기 직전 소화기 보정이 적용되면 기존 recordedPath를 버리고 보정된 위치에서 다시 경로를 생성합니다.")]
    public bool restartVirtualPathIfFireCorrectedBeforeSend = true;

    [Tooltip("소화기 보정을 경로 생성 전에 적용하는 흐름의 로그를 출력합니다.")]
    public bool debugFireCorrectionBeforePathPlanning = true;

    private int fireCorrectionVersion = 0;
    private bool suppressManualStartSdkSyncOnce = false;

    private bool waitingRealGo1Start = false;
    private Coroutine realGo1StartWaitCoroutine = null;
    private float realGo1StartWaitBeginTime = -999f;
    private int realGo1StartPathResendCount = 0;
    private float firstFalseStateWhileRealPathActiveTime = -999f;

    // 장애물 기반 재탐색 상태는 GO1ReplanController가 소유합니다.
    // 소화기 landmark 보정 재탐색은 기존 기능 호환을 위해 GO1Agent에 유지합니다.
    private Coroutine fireReplanCoroutine = null;
    private readonly List<Vector3> currentSentPath = new List<Vector3>();
    private float lastPathSendTime = -999f;

    private bool fireCorrectionInProgress = false;
    private bool fireLandmarkReplanning = false;
    private int fireCorrectionDuringPathCountThisMission = 0;
    private int fireCorrectionAfterPathDoneCountThisMission = 0;
    private float lastFireCorrectionReplanTime = -999f;

    private bool IsReplanningActive
    {
        get
        {
            return fireLandmarkReplanning ||
                   (replanController != null && replanController.IsBusy);
        }
    }

    public bool IsMoving()
    {
        // 실제로 움직이는 상태만 true로 둔다.
        // 경로 전송 후 state_change=true를 기다리는 구간은 waitingRealGo1Start로 별도 관리한다.
        return (canMove && !isArrived) ||
               localPathReplayActive ||
               realGo1PathActive ||
               IsReplanningActive;
    }

    public bool IsMissionBusy()
    {
        return (canMove && !isArrived) ||
               localPathReplayActive ||
               localReplayMlAgentReplanPending ||
               realGo1PathCommandSent ||
               waitingRealGo1Start ||
               realGo1PathActive ||
               IsReplanningActive;
    }

    /// <summary>
    /// 생성된 경로를 Unity에서 다시 따라가는 단계인지 반환합니다.
    /// 부표는 이 단계에서만 경로 위에 배치합니다.
    /// </summary>
    public bool IsLocalGeneratedPathReplayActive()
    {
        return localPathReplayActive;
    }

    /// <summary>
    /// 현재 재주행 경로 복사본입니다.
    /// BoatBuoyMlReplanController가 부표 위치를 계산할 때 사용합니다.
    /// </summary>
    public Vector3[] GetLocalReplayPathSnapshot()
    {
        return localReplayPath.ToArray();
    }

    public int GetLocalReplayMlAgentReplanCount()
    {
        return localReplayMlAgentReplanCount;
    }

    public bool IsLocalReplayMlAgentReplanPending()
    {
        return localReplayMlAgentReplanPending;
    }

    /// <summary>
    /// 현재 로컬 경로 재주행을 멈추고,
    /// 현 위치를 새 시작점으로 삼아 ONNX/ML-Agent 정책으로 목표까지 경로를 다시 생성합니다.
    /// 새 경로 생성이 완료되면 해당 시작점으로 복귀하여 새 경로를 다시 재주행합니다.
    /// </summary>
    public bool RequestMlAgentReplanFromLocalReplay(
        string reason,
        float carvingWaitSeconds = -1f
    )
    {
        if (!UseLocalGeneratedPathReplay ||
            !EnableLocalReplayMlAgentReplan)
        {
            Debug.LogWarning(
                $"[{gameObject.name}] ML-Agent 로컬 재탐색이 비활성화되어 있습니다."
            );
            return false;
        }

        if (!localPathReplayActive || target == null)
        {
            Debug.LogWarning(
                $"[{gameObject.name}] 경로 재주행 중이 아니므로 ML-Agent 재탐색을 시작할 수 없습니다."
            );
            return false;
        }

        if (localReplayMlAgentReplanPending)
        {
            Debug.LogWarning(
                $"[{gameObject.name}] 이미 ML-Agent 재탐색 준비 중입니다."
            );
            return false;
        }

        int limit = LocalReplayMlAgentReplanLimit;
        if (limit > 0 &&
            localReplayMlAgentReplanCount >= limit)
        {
            Debug.LogWarning(
                $"[{gameObject.name}] ML-Agent 재탐색 횟수 제한 도달 | " +
                $"count={localReplayMlAgentReplanCount}, limit={limit}"
            );
            return false;
        }

        if (localPathReplayCoroutine != null)
        {
            StopCoroutine(localPathReplayCoroutine);
            localPathReplayCoroutine = null;
        }

        localPathReplayActive = false;
        localReplayPath.Clear();

        canMove = false;
        isArrived = false;
        blockedFrameCount = 0;
        previousTurn = 0f;
        previousMove = 0f;

        localReplayMlAgentReplanPending = true;
        localReplayMlAgentPathGenerationActive = true;
        localReplayMlAgentReplanCount++;

        ReplanBeginExperiment(null);
        WriteExperimentEvent(
            "boat_ml_replan_request",
            string.IsNullOrWhiteSpace(reason)
                ? "buoy_obstacle"
                : reason,
            transform.position
        );

        float waitSeconds = carvingWaitSeconds >= 0f
            ? carvingWaitSeconds
            : LocalReplayMlAgentReplanDelay;

        if (localReplayMlAgentReplanCoroutine != null)
            StopCoroutine(localReplayMlAgentReplanCoroutine);

        localReplayMlAgentReplanCoroutine = StartCoroutine(
            RestartMlAgentPlanningAfterBuoy(
                string.IsNullOrWhiteSpace(reason)
                    ? "buoy_obstacle"
                    : reason,
                Mathf.Max(0f, waitSeconds)
            )
        );

        Debug.Log(
            $"[{gameObject.name}] 부표 감지 → 기존 재주행 정지, ML-Agent 재탐색 준비 | " +
            $"count={localReplayMlAgentReplanCount}, wait={waitSeconds:F2}s"
        );

        return true;
    }

    // M키를 눌러 가상 GO1이 목표 지점까지 빠르게 이동하면서
    // 경로를 생성하는 중인지 외부 스크립트에서 확인하기 위한 함수.
    // 이 구간에서는 현실 GO1은 정지해 있어도 카메라 JSON이 계속 들어올 수 있으므로,
    // Go1ObstacleJsonReceiver가 JSON 장애물 생성을 잠시 무시할 때 사용한다.
    public bool IsVirtualPathPlanning()
    {
        return !Academy.Instance.IsCommunicatorOn && canMove && !isArrived;
    }

    // 경로 전송 후 C++ path follower가 실제 GO1을 waypoint 경로로 이동 중인지 확인한다.
    public bool IsRealPathFollowing()
    {
        return realGo1PathActive;
    }

    public bool IsWaitingRealGo1Start()
    {
        return waitingRealGo1Start;
    }

    public bool HasRealGo1PathCommandSent()
    {
        return realGo1PathCommandSent;
    }

    // 런타임 재탐색으로 새 경로를 보낸 직후 JSON을 잠시 막아야 하는지 확인한다.
    public bool IsPostReplanJsonBlocked()
    {
        return replanController != null && replanController.IsPostReplanJsonBlocked();
    }

    public float GetPostReplanJsonBlockRemaining()
    {
        return replanController != null
            ? replanController.GetPostReplanJsonBlockRemaining()
            : 0f;
    }



    // JSON 장애물 생성을 무시해야 하는 상태인지 확인한다.
    // true인 경우:
    // 1) M키로 가상 GO1이 경로를 생성하는 중
    // 2) 경로 전송 후 실제 GO1이 waypoint를 따라 이동하는 중
    public bool ShouldIgnoreObstacleJson()
    {
        return IsMoving();
    }

    [Header("KCI Experiment Logging")]
    [Tooltip("학습/가상 경로/실제 GO1 주행 결과를 CSV로 저장합니다.")]
    public bool enableExperimentLogging = true;

    [Tooltip("CSV의 method 열에 기록할 실험 방법 이름입니다.")]
    public string experimentMethodName = "MLAgents_Replan";

    [Tooltip("프로젝트 루트(Assets의 상위 폴더) 아래에 생성할 결과 폴더 이름입니다. 예: D:/My project/GO1_KCI_Experiment")]
    public string experimentFolderName = "GO1_KCI_Experiment";

    [Tooltip("실제 GO1/경로 추종 샘플을 저장하는 주기(초)입니다.")]
    public float experimentSampleInterval = 0.05f;

    [Tooltip("실험 시작/종료 시 Console에 저장 경로를 출력합니다.")]
    public bool debugExperimentLogging = true;

    [Tooltip("같은 Collider와 계속 접촉할 때 충돌을 중복 집계하지 않는 최소 간격(초)입니다.")]
    public float experimentCollisionCooldown = 0.5f;

    [Header("Paper Experiment Identification")]
    [Tooltip("실행할 때마다 세션 ID 폴더를 만들어 이전 실험 데이터와 분리합니다.")]
    public bool createSessionSubfolder = true;

    [Tooltip("비교 실험 조건입니다. 예: C1_BASELINE, C2_NO_REPLAN, C3_REPLAN")]
    public string experimentConditionId = "C3_REPLAN";

    [Tooltip("장애물 및 출발/목표 배치를 구분하는 시나리오 ID입니다. 예: S01, S02")]
    public string experimentScenarioId = "S01";

    [Tooltip("실험에 사용한 Unity 맵 또는 Scene 구분 이름입니다.")]
    public string experimentMapId = "TestMap_A";

    [Tooltip("평가에 사용한 ONNX 정책 구분 이름입니다.")]
    public string experimentPolicyId = "GO1_Baseline";

    [Tooltip("사용한 ML-Agents 버전을 직접 기록합니다.")]
    public string experimentMlAgentsVersion = "unknown";

    [Tooltip("사용한 학습 YAML 파일 이름입니다.")]
    public string experimentYamlName = "go1.yaml";

    [Tooltip("TrainingManager가 없는 실제 로봇 실험에서 사용할 난수 시드 기록값입니다.")]
    public int experimentFallbackRandomSeed = 121;

    private static readonly string experimentSessionId =
        System.DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture);

    private string experimentDirectory;
    private string experimentSummaryCsvPath;
    private string experimentTrackingCsvPath;
    private string experimentEventCsvPath;
    private string experimentConfigCsvPath;
    private string inspectorConfigCsvPath;
    private string scenarioConfigCsvPath;
    private string obstacleEventCsvPath;
    private bool experimentStaticConfigurationWritten = false;
    private bool experimentTrialStartWritten = false;
    private string experimentTrialMode = "unknown";
    private bool experimentTrialActive = false;
    private int experimentTrialId = 0;
    private float experimentTrialStartTime = 0f;
    private System.DateTime experimentTrialStartDateTime;
    private float experimentPlanningStartTime = 0f;
    private float experimentFirstPathSendTime = -1f;
    private float experimentLastSampleTime = -999f;
    private float experimentTravelDistance = 0f;
    private Vector3 experimentPreviousPosition;
    private Vector3 experimentStartPosition;
    private Quaternion experimentStartRotation;
    private Vector3 experimentTargetPosition;
    private int experimentCollisionCount = 0;
    private int experimentObstacleCollisionCount = 0;
    private readonly Dictionary<int, float> experimentLastCollisionTimeByCollider =
        new Dictionary<int, float>();
    private int experimentStuckEventCount = 0;
    private int experimentReplanCount = 0;
    private float experimentAccumulatedReplanTime = 0f;
    private float experimentCurrentReplanStartTime = -1f;
    private int experimentRawWaypointCount = 0;
    private int experimentSentWaypointCount = 0;
    private float experimentSentPathLength = 0f;
    private string experimentLastFailureReason = "";

    public override void Initialize()
    {
        completedEvaluationTrialCount = 0;
        evaluationLimitReached = false;
        evaluationStopRequested = false;

        InitializeExperimentLogging();
        wasdDrive = GetComponent<Go1WASDLegacyDrive>();
        cc = GetComponent<CharacterController>();
        recorder = GetComponent<DemonstrationRecorder>();
        managedDecisionRequester = GetComponent<DecisionRequester>();
        trainingEpisodeLogger = GetComponent<TrainingEpisodeLogger>();
        caseStudyLogger       = GetComponent<RealGo1CaseStudyLogger>();

        if (trainingManager == null)
            trainingManager = FindFirstObjectByType<TrainingManager>();

        utm = FindFirstObjectByType<UnityTeleopAndMirror>();

        EnsurePathPlanner();
        EnsureReplanController();

        if (c2c3EvaluationManager == null)
            c2c3EvaluationManager = FindFirstObjectByType<C2C3EvaluationManager>();

        Time.timeScale = 1f;

        if (Academy.Instance.IsCommunicatorOn && wasdDrive != null)
            wasdDrive.enabled = false;
    }

    private void EnsurePathPlanner()
    {
        if (pathPlanner == null)
            pathPlanner = GetComponent<GO1PathPlanner>();

        if (pathPlanner == null)
            pathPlanner = gameObject.AddComponent<GO1PathPlanner>();

        pathPlanner.EnsureInitialized();
    }

    private void EnsureReplanController()
    {
        if (replanController == null)
            replanController = GetComponent<GO1ReplanController>();

        if (replanController == null)
            replanController = gameObject.AddComponent<GO1ReplanController>();

        replanController.EnsureReferences(this, pathPlanner);
    }

    private Vector3[] CurrentPathCorners
    {
        get
        {
            return pathPlanner != null
                ? pathPlanner.CurrentCorners
                : System.Array.Empty<Vector3>();
        }
    }

    private void CalculateCurrentPath(Vector3 from, Vector3 to)
    {
        EnsurePathPlanner();
        pathPlanner.CalculatePath(from, to);
    }

    private float GetNavMeshPathDistance(Vector3 from, Vector3 to)
    {
        EnsurePathPlanner();
        return pathPlanner.GetPathDistance(from, to);
    }

    private Vector3 GetNextWaypointDirection()
    {
        if (target == null)
            return Vector3.forward;

        CalculateCurrentPath(transform.position, target.position);

        if (pathPlanner == null || pathPlanner.IsCurrentPathInvalidOrPartial)
        {
            pathFailCount++;

            if (pathFailCount > maxPathFailCount)
            {
                pathFailCount = 0;

                if (Academy.Instance.IsCommunicatorOn)
                {
                    episodeFailed = true;
                    SafeEndEpisode();
                }
            }

            return -transform.right;
        }

        pathFailCount = 0;

        Vector3[] corners = CurrentPathCorners;
        if (corners.Length < 2)
            return (target.position - transform.position).normalized;

        Vector3 nextWaypoint = pathPlanner.GetNextWaypoint(
            transform.position,
            target.position,
            RuntimeWaypointSwitchDistance
        );

        Vector3 direction = nextWaypoint - transform.position;
        direction.y = 0f;

        return direction.sqrMagnitude > 0.000001f
            ? direction.normalized
            : (target.position - transform.position).normalized;
    }

    private Vector3 GetNextWaypoint()
    {
        if (target == null)
            return transform.position;

        if (pathPlanner == null)
            return target.position;

        return pathPlanner.GetNextWaypoint(
            transform.position,
            target.position,
            RuntimeWaypointSwitchDistance
        );
    }

    // 진행 방향 기준 양옆으로 레이를 쏴 벽과의 간격을 재고,
    // (1) 한쪽 벽에 너무 붙으면 근접 패널티, (2) 양쪽에 벽이 있으면 가운데 정렬 보상을 준다.
    // 다른 에이전트(레이어 7~12)는 벽으로 오인하지 않도록 마스크에서 제외한다.
    private void AddWallClearanceReward()
    {
        Vector3 fwd = -transform.right;
        fwd.y = 0f;
        if (fwd.sqrMagnitude < 1e-6f)
            return;
        fwd.Normalize();

        Vector3 leftDir = Vector3.Cross(Vector3.up, fwd).normalized;
        Vector3 rightDir = -leftDir;

        Vector3 origin = transform.position + Vector3.up * 0.5f;

        // 에이전트 레이어(7~12) 제외
        int mask = wallClearanceMask.value;
        for (int l = 7; l <= 12; l++)
            mask &= ~(1 << l);

        float leftDist = CastSideClearance(origin, leftDir, mask);
        float rightDist = CastSideClearance(origin, rightDir, mask);

        // [폭 독립 보상] 절대 거리 기준 근접 패널티는 제거했다.
        // 좁은 복도일수록 가혹해져 진입을 막던 주범이었고, 폭이 제각각인 맵에선 단일 임계값이 성립하지 않는다.
        // 벽에 '닿는' 것 자체는 OnControllerColliderHit의 충돌 패널티가 폭과 무관하게 처리한다.

        // 양쪽 모두 벽이 가까우면(복도) 좌우 간격 차이에 비례한 정렬 패널티 → 가운데 유도.
        // |좌-우| 는 복도 폭과 무관하므로 폭이 달라도 동일하게 작동한다.
        bool leftWall = leftDist < wallClearanceRayDistance;
        bool rightWall = rightDist < wallClearanceRayDistance;
        if (leftWall && rightWall)
        {
            float imbalance = Mathf.Abs(leftDist - rightDist) / wallClearanceRayDistance;
            AddReward(-imbalance * corridorCenteringWeight);
        }
    }

    private float CastSideClearance(Vector3 origin, Vector3 dir, int mask)
    {
        RaycastHit hit;
        if (Physics.Raycast(origin, dir, out hit, wallClearanceRayDistance, mask, QueryTriggerInteraction.Ignore))
            return hit.distance;
        return wallClearanceRayDistance;
    }

    private void EnableWASD()
    {
        if (utm != null)
        {
            utm.driveByState = true;
            utm.enableTeleop = true;
        }

        if (cc != null)
            cc.enabled = true;

        if (wasdDrive != null)
        {
            wasdDrive.ResetState();
            wasdDrive.enabled = true;
            wasdDrive.useMarkerOverride = false;
            wasdDrive.useExternalState = false;
            wasdDrive.useExternalCmd = false;
        }

        if (navigator != null)
            navigator.EnableExternalControllers();

        Debug.Log("[GO1Agent] WASD/state 동기화 모드 복귀");
    }

    private int ProcessPendingJsonForFireCorrectionGate(string reason)
    {
        if (obstacleReceiver == null)
            obstacleReceiver = FindFirstObjectByType<Go1ObstacleJsonReceiver>();

        if (obstacleReceiver == null)
            return 0;

        int queuedBefore = obstacleReceiver.GetQueuedJsonCount();
        int processed = obstacleReceiver.ProcessQueuedJsonForPathPlanningGate(maxPreMissionJsonPackets);

        if (debugFireCorrectionBeforePathPlanning && (processed > 0 || queuedBefore > 0))
        {
            Debug.Log(
                "[GO1Agent] 경로 생성 전 5009 JSON 선처리 | " +
                "reason=" + reason +
                ", queuedBefore=" + queuedBefore +
                ", processed=" + processed +
                ", fireCorrectionVersion=" + fireCorrectionVersion
            );
        }

        return processed;
    }

    private bool TryRestartVirtualPathIfFireCorrectedBeforeSendingPath(string reason)
    {
        if (!processQueuedJsonBeforePathSend || !restartVirtualPathIfFireCorrectedBeforeSend)
            return false;

        int correctionVersionBefore = fireCorrectionVersion;

        // 지금은 가상 GO1이 목표에 도달한 직후라 canMove=true일 수 있다.
        // 이 상태로 소화기 보정을 요청하면 기존 로직이 "가상 경로 생성 중"으로 보고 보정을 거절할 수 있으므로,
        // 잠깐 정지 상태로 바꿔 큐의 소화기 보정을 먼저 적용시킨다.
        bool oldCanMove = canMove;
        bool oldIsArrived = isArrived;
        canMove = false;
        isArrived = false;

        int processed = ProcessPendingJsonForFireCorrectionGate(reason);

        bool fireCorrected = fireCorrectionVersion != correctionVersionBefore;

        if (!fireCorrected)
        {
            canMove = oldCanMove;
            isArrived = oldIsArrived;
            return false;
        }

        canMove = false;
        isArrived = false;
        blockedFrameCount = 0;
        recordedPath.Clear();
        lastRecordTime = 0f;
        lastRecordedPos = transform.position;
        previousTurn = 0f;
        previousMove = 0f;
        pathFailCount = 0;

        if (debugFireCorrectionBeforePathPlanning)
        {
            Debug.Log(
                "[GO1Agent] C++ path 전송 직전 소화기 보정이 적용됨 → 기존 경로 폐기 후 보정된 pose에서 재경로 생성 | " +
                "reason=" + reason +
                ", processedJson=" + processed +
                ", newPos=" + transform.position +
                ", yaw=" + transform.eulerAngles.y.ToString("F1")
            );
        }

        StartMission();
        return true;
    }

    private void StartMission()
    {
        if (target == null)
        {
            canMove = false;
            return;
        }

        if (!experimentTrialActive)
            BeginExperimentTrial(Academy.Instance.IsCommunicatorOn ? "training" : "manual");

        if (experimentFirstPathSendTime < 0f)
            experimentPlanningStartTime = Time.time;

        // M키 수동 시작이면, 경로 생성 직전에 C++ state 기준 pose/yaw를 한 번 더 반영한다.
        // 이렇게 해야 Unity가 만든 시작 yaw와 C++ path follower가 쓰는 yaw 기준이 어긋나지 않는다.
        bool skipSdkPoseSyncThisStart = suppressManualStartSdkSyncOnce;
        suppressManualStartSdkSyncOnce = false;

        bool isRuntimeReplanPathGeneration =
            replanController != null && replanController.IsRuntimePathWaitingForSend;

        if (!isRuntimeReplanPathGeneration && syncPoseToSdkBeforeManualMission && !skipSdkPoseSyncThisStart)
        {
            SyncVirtualPoseToCurrentSdkState("manual-start-before-mission", false, debugManualStartPoseSync);
        }
        else if (skipSdkPoseSyncThisStart && debugFireCorrectionBeforePathPlanning)
        {
            Debug.Log("[GO1Agent] 소화기 보정 직후 경로 생성이므로 C++ state pose 동기화를 1회 건너뜁니다. 보정된 Unity pose 기준으로 경로를 생성합니다.");
        }

        // M을 누른 현재 pose를 새 시작 기준으로 사용한다.
        // 1번째 도착 후 실제 GO1이 130도 방향이면, driveByState로 반영된 그 130도 pose가 여기 저장된다.
        missionStartPosition = transform.position;
        missionStartRotation = transform.rotation;

        isArrived = false;
        canMove = true;
        blockedFrameCount = 0;

        // 사용자가 시작한 새 미션에서만 장애물 재탐색 횟수와 잠금 상태를 초기화합니다.
        // GO1ReplanController가 새 경로 생성을 요청한 경우에는 기존 재탐색 횟수를 유지합니다.
        if (!isRuntimeReplanPathGeneration)
        {
            if (replanController != null)
                replanController.ResetForManualMission();

            // 새 M키 미션마다 소화기 landmark 보정 기회도 초기화한다.
            fireCorrectionInProgress = false;
            fireLandmarkReplanning = false;
            fireCorrectionDuringPathCountThisMission = 0;
            fireCorrectionAfterPathDoneCountThisMission = 0;
            lastFireCorrectionReplanTime = -999f;
        }

        recordedPath.Clear();
        lastRecordTime = 0f;
        lastRecordedPos = missionStartPosition;
        recordedPath.Add(missionStartPosition);

        stuckCount = 0;
        wallHitCount = 0;
        previousTurn = 0f;
        previousMove = 0f;
        pathFailCount = 0;
        _lastKeepAliveTime = 0f;

        if (utm != null)
        {
            // 경로 생성 중에는 C++ state 적용을 잠시 끄고,
            // 가상 GO1만 ML-Agent 정책대로 빠르게 움직인다.
            utm.driveByState = false;
            utm.enableTeleop = true;
        }

        if (navigator != null)
            navigator.DisableExternalControllers();

        if (wasdDrive != null)
            wasdDrive.enabled = false;

        if (cc != null)
            cc.enabled = true;

        previousPathDist = GetNavMeshPathDistance(transform.position, target.position);
        CalculateCurrentPath(transform.position, target.position);

        Vector3 nextWp = GetNextWaypoint();
        previousWaypointDist = Vector3.Distance(
            new Vector3(transform.position.x, 0f, transform.position.z),
            new Vector3(nextWp.x, 0f, nextWp.z)
        );

        MarkExperimentTrialStarted();

        // 케이스 스터디 로거: 미션 시작
        caseStudyLogger?.LogMissionStart();

        Debug.Log(
            $"[GO1Agent] 미션 시작 | startPos={missionStartPosition}, " +
            $"startRot={missionStartRotation.eulerAngles}, target={target.position}, " +
            $"virtualSpeed x{virtualPlanSpeedMultiplier}"
        );
    }

    private void StopMission()
    {
        StopLocalGeneratedPathReplay(false, "user_stop");

        if (fireReplanCoroutine != null)
        {
            StopCoroutine(fireReplanCoroutine);
            fireReplanCoroutine = null;
        }

        fireLandmarkReplanning = false;

        if (replanController != null)
            replanController.ResetAll("StopMission");

        currentSentPath.Clear();
        fireCorrectionInProgress = false;
        fireCorrectionDuringPathCountThisMission = 0;
        fireCorrectionAfterPathDoneCountThisMission = 0;
        lastFireCorrectionReplanTime = -999f;

        canMove = false;
        isArrived = false;
        ClearRealGo1PathCommandState("StopMission");
        blockedFrameCount = 0;

        // Unity 가상 경로 생성 중이든, C++ 실제 GO1 경로 추종 중이든
        // N키를 누르면 C++ path follower까지 반드시 취소한다.
        if (pathSender != null)
            pathSender.SendPathCancel();

        // PATH_CANCEL이 누락되거나 C++ 처리까지 시간이 걸리는 경우를 대비해
        // 즉시 0속도/estop 명령도 같이 보낸다.
        if (utm != null)
        {
            utm.SendTeleopCmd(0f, 0f, 0f, 1);
            utm.driveByState = true;
        }

        StopActualGo1PointTrace(false);
        EnableWASD();

        FinishExperimentTrial(false, "user_stop");

        Debug.Log("[GO1Agent] 미션 정지 + C++ PATH_CANCEL 전송");
    }

    void Update()
    {
        UpdateRealGo1PathActiveFromStateChange();

        if (Input.GetKeyDown(stopMissionKey))
        {
            if (Academy.Instance.IsCommunicatorOn)
                return;

            if (IsMissionBusy())
            {
                StopMission();
            }
            else
            {
                Debug.Log("[GO1Agent] 정지 키 입력: 현재 진행 중인 미션이 없습니다.");
            }
        }

        if (Input.GetKeyDown(startMissionKey))
        {
            if (Academy.Instance.IsCommunicatorOn)
                return;

            if (IsMissionBusy())
            {
                Debug.Log("[GO1Agent] 시작 키 입력 무시: 이미 자율주행/재탐색/실제 GO1 시작 대기가 진행 중입니다. 정지는 N키를 사용하세요.");
                return;
            }

            isArrived = false;

            if (target == null)
            {
                Debug.LogWarning("[GO1Agent] GoalPoint가 없습니다.");
                return;
            }

            if (processQueuedJsonBeforeManualMission)
            {
                ProcessPendingJsonForFireCorrectionGate("manual-start-before-path-planning");
            }

            if (enableNavMeshPreCheck && IsPathBlockedByNavMesh(transform.position, target.position))
            {
                Debug.LogWarning("[GO1Agent] NavMesh 기준 목표까지 완전한 경로가 없습니다.");
                return;
            }

            if (enablePhysicalPathCheck && IsPathPhysicallyBlocked(transform.position, target.position))
            {
                Debug.LogWarning("[GO1Agent] 실제 Collider 기준 경로가 막혀 있습니다.");
                return;
            }

            ResetLocalReplayMlAgentReplanForNewMission();
            StartMission();
        }

        // M으로 가상 경로 생성 중일 때 C++ 쪽 teleop timeout 방지용 keep-alive.
        // 실제 이동 명령이 아니라 0 명령만 보낸다.
        if (canMove && !isArrived && !Academy.Instance.IsCommunicatorOn)
        {
            if (Time.time - _lastKeepAliveTime > _keepAliveInterval)
            {
                _lastKeepAliveTime = Time.time;
                utm?.SendTeleopCmd(0f, 0f, 0f, 0);
            }
        }

        UpdateActualGo1PointTrace();
        UpdateExperimentTracking();
    }

    private void FixedUpdate()
    {
        // C2/C3 관리형 평가는 OnEpisodeBegin의 일반 평가 루프를 사용하지 않는다.
        // 따라서 프리팹에 DecisionRequester가 없거나 비활성화되어 있으면
        // Agent가 행동 결정을 받지 못해 canMove=true여도 정지할 수 있다.
        if (Academy.Instance.IsCommunicatorOn ||
            !managedEvaluationRunActive ||
            !canMove ||
            isArrived ||
            target == null)
        {
            return;
        }

        if (managedDecisionRequester == null)
            managedDecisionRequester = GetComponent<DecisionRequester>();

        // 정상적으로 켜진 DecisionRequester가 있으면 기존 주기를 그대로 사용한다.
        if (managedDecisionRequester != null && managedDecisionRequester.enabled)
            return;

        managedEvaluationDecisionCounter++;
        int period = Mathf.Max(1, managedEvaluationDecisionPeriod);

        if (managedEvaluationDecisionCounter >= period)
        {
            managedEvaluationDecisionCounter = 0;
            RequestDecision();
        }
        else
        {
            // 새 결정 사이의 프레임에는 마지막 행동을 계속 적용한다.
            RequestAction();
        }
    }

    public void OnNavigatorStarted()
    {
        OnExternalControlStarted(true);
    }

    public void OnNavigatorArrived()
    {
        OnExternalControlEnded();
    }

    /// <summary>
    /// GO1AutoNavigator/외부 평가 관리자 등이 이 GO1Agent와 같은 리그(CharacterController)를
    /// 공유하며 NavMeshAgent 등으로 직접 이동을 제어할 때, RL 이동을 완전히 비활성화합니다.
    /// enableDemoRecording=false로 호출하면 ML-Agents DemonstrationRecorder는 건드리지 않습니다
    /// (예: C1EvaluationManager처럼 자동 반복 평가 중에는 데모 녹화가 필요 없고,
    /// 녹화 상태로 오래 방치하면 데모 파일 재임포트 문제가 생길 수 있음).
    /// </summary>
    public void OnExternalControlStarted(bool enableDemoRecording)
    {
        isDemoMode = true;
        Time.timeScale = 1f;

        if (wasdDrive != null)
            wasdDrive.enabled = false;

        if (cc != null)
            cc.enabled = false;

        if (enableDemoRecording && recorder != null)
        {
            recorder.Record = true;
            Debug.Log($"[{gameObject.name}] 데모 시작");
        }
    }

    public void OnExternalControlEnded()
    {
        isDemoMode = false;

        if (cc != null)
            cc.enabled = true;

        if (wasdDrive != null)
            wasdDrive.enabled = true;

        if (recorder != null && recorder.Record)
        {
            recorder.Record = false;
            Debug.Log($"[{gameObject.name}] 데모 완료");
        }

        if (Academy.Instance.IsCommunicatorOn && wasdDrive != null)
            wasdDrive.enabled = false;
    }

    public override void OnEpisodeBegin()
    {
        episodeEnding = false;

        if (isDemoMode)
            return;

        if (!Academy.Instance.IsCommunicatorOn && !evaluationMode)
            return;

        // 최대 평가 횟수에 도달한 뒤에는 새 trial을 시작하지 않는다.
        if (evaluationMode && !Academy.Instance.IsCommunicatorOn && evaluationLimitReached)
        {
            canMove = false;
            isArrived = true;
            return;
        }

        if (!experimentTrialActive)
            BeginExperimentTrial(Academy.Instance.IsCommunicatorOn ? "training" : "evaluation");

        isArrived = false;
        canMove = false;
        blockedFrameCount = 0;

        recordedPath.Clear();
        lastRecordTime = 0f;

        previousTurn = 0f;
        previousMove = 0f;
        previousCornerCount = -1;
        pathFailCount = 0;

        Time.timeScale = 20f;

        if (wasdDrive != null)
            wasdDrive.enabled = false;

        if (cc != null)
            cc.enabled = false;

        if (episodeFailed && retryCount < maxRetryCount)
        {
            retryCount++;
            transform.position = lastStartPos;
            transform.rotation = lastStartRot;
            episodeFailed = false;

            Debug.Log($"[{gameObject.name}] 재시도 {retryCount}/{maxRetryCount}");
        }
        else
        {
            retryCount = 0;
            episodeFailed = false;

            Vector3 startPos = trainingManager != null
                ? trainingManager.GetRandomStartPosition()
                : (startPoint != null ? startPoint.position : transform.position);

            transform.position = startPos;
            transform.rotation = Quaternion.Euler(0f, Random.Range(0f, 360f), 0f);

            lastStartPos = transform.position;
            lastStartRot = transform.rotation;

            if (trainingManager != null)
            {
                bool goalAssigned = trainingManager.ResetGoalForAgent(this);
                if (!goalAssigned)
                    Debug.LogError($"[{gameObject.name}] 새 시작 위치 기준 목표 생성 실패");
            }

            Debug.Log($"[{gameObject.name}] 새 위치 pos={transform.position}");
        }

        if (cc != null)
            cc.enabled = true;

        lastRecordedPos = transform.position;

        if (pathPlanner != null)
            pathPlanner.Warp(transform.position);

        if (target != null)
        {
            previousPathDist = GetNavMeshPathDistance(transform.position, target.position);
            CalculateCurrentPath(transform.position, target.position);

            Vector3 nextWp = GetNextWaypoint();
            previousWaypointDist = Vector3.Distance(
                new Vector3(transform.position.x, 0f, transform.position.z),
                new Vector3(nextWp.x, 0f, nextWp.z)
            );
        }

        stuckCount = 0;
        wallHitCount = 0;

        MarkExperimentTrialStarted();
    }

    public override void CollectObservations(VectorSensor sensor)
    {
        if (target == null || isArrived)
        {
            for (int i = 0; i < 35; i++)
                sensor.AddObservation(0f);

            return;
        }

        sensor.AddObservation(-transform.right);
        sensor.AddObservation(previousTurn);
        sensor.AddObservation(previousMove);

        CalculateCurrentPath(transform.position, target.position);

        for (int i = 1; i <= 3; i++)
        {
            if (i < CurrentPathCorners.Length)
            {
                Vector3 corner = CurrentPathCorners[i] - transform.position;
                sensor.AddObservation(corner.normalized);
                sensor.AddObservation(corner.magnitude / 20f);
            }
            else
            {
                Vector3 toTarget = target.position - transform.position;
                sensor.AddObservation(toTarget.normalized);
                sensor.AddObservation(toTarget.magnitude / 20f);
            }
        }

        Vector3 nextDir = GetNextWaypointDirection();
        sensor.AddObservation(Vector3.Dot(-transform.right, nextDir));
        sensor.AddObservation(Vector3.Cross(-transform.right, nextDir).y);

        // 16방향 SphereCast: 에이전트 반경만 한 구체를 쏴 '내 몸이 그 방향으로 얼마나 지나갈 수 있나'를 관측.
        // 단일 Raycast(8방향 45도)보다 촘촘(22.5도)해서 좁은 입구가 레이 사이 빈틈에 빠지지 않고,
        // 구체 반경 덕분에 '못 끼는 틈'과 '통과 가능한 구멍'을 폭과 무관하게 구분한다.
        float castRadius = (cc != null) ? cc.radius : 0.2f;

        int obsMask = ~0;
        for (int l = 7; l <= 12; l++)
            obsMask &= ~(1 << l);   // 다른 에이전트 레이어(7~12) 제외

        Vector3 castOrigin = transform.position + Vector3.up * 0.5f;

        for (int i = 0; i < 16; i++)
        {
            Vector3 dir = Quaternion.Euler(0f, i * 22.5f, 0f) * (-transform.right);
            dir.y = 0f;
            if (dir.sqrMagnitude > 1e-6f) dir.Normalize();

            RaycastHit hit;
            float dist = Physics.SphereCast(
                castOrigin, castRadius, dir, out hit, sensorGizmoLength, obsMask, QueryTriggerInteraction.Ignore
            ) ? Mathf.Clamp01(hit.distance / sensorGizmoLength) : 1f;

            sensor.AddObservation(dist);
        }

        // Observation Space Size: 35  (이전 27에서 레이 8 -> 16으로 증가)
        // 프리팹의 Behavior Parameters > Vector Observation > Space Size 도 35로 바꿔야 함.
    }

    private void OnDrawGizmosSelected()
    {
        if (!drawSensorGizmos)
            return;

        float castRadius = sensorGizmoRadius > 0f ? sensorGizmoRadius : 0.08f;
        Vector3 castOrigin = transform.position + Vector3.up * 0.5f;
        int obsMask = ~0;
        for (int l = 7; l <= 12; l++)
            obsMask &= ~(1 << l);

        Gizmos.color = Color.yellow;
        Gizmos.DrawWireSphere(castOrigin, castRadius);

        for (int i = 0; i < 16; i++)
        {
            Vector3 dir = Quaternion.Euler(0f, i * 22.5f, 0f) * (-transform.right);
            dir.y = 0f;
            if (dir.sqrMagnitude > 1e-6f)
                dir.Normalize();

            RaycastHit hit;
            bool hasHit = Physics.SphereCast(
                castOrigin,
                castRadius,
                dir,
                out hit,
                sensorGizmoLength,
                obsMask,
                QueryTriggerInteraction.Ignore
            );

            Vector3 endPoint = hasHit ? hit.point : castOrigin + dir * sensorGizmoLength;
            Gizmos.color = hasHit ? Color.red : Color.cyan;
            Gizmos.DrawLine(castOrigin, endPoint);
            Gizmos.DrawWireSphere(endPoint, 0.03f);
        }

        DrawWaypointGizmos();
    }

    // NavMesh 경로와 '지금 에이전트가 향하는 타깃 웨이포인트'를 Scene 뷰에 그린다.
    // - 흰 선: NavMesh 경로 전체
    // - 하늘색 점: 경로의 각 코너
    // - 노란 큰 점 + 노란 선: 지금 향하는 타깃 코너 (코너 자르기 로직 반영)
    // - 주황 와이어 구: corners[1] 기준 '자르기 발동 반경'(waypointSwitchDistance).
    //   에이전트가 이 구 안에 들어오면 노란 타깃이 다음 코너로 점프 → 그 순간이 코너 자르기다.
    // 학습/관측/보상에는 전혀 영향 없는 에디터 표시 전용 코드.
    private void DrawWaypointGizmos()
    {
        if (!drawWaypointGizmos)
            return;

        if (!Application.isPlaying)
            return;

        if (pathPlanner == null || CurrentPathCorners.Length < 2)
            return;

        Vector3 up = Vector3.up * 0.12f;

        // 경로 선 (흰색)
        Gizmos.color = Color.white;
        for (int i = 0; i < CurrentPathCorners.Length - 1; i++)
            Gizmos.DrawLine(CurrentPathCorners[i] + up, CurrentPathCorners[i + 1] + up);

        // 각 코너 (하늘색 점)
        Gizmos.color = Color.cyan;
        for (int i = 1; i < CurrentPathCorners.Length; i++)
            Gizmos.DrawSphere(CurrentPathCorners[i] + up, 0.07f);

        // corners[1] 기준 자르기 발동 반경 (주황 와이어 구)
        Gizmos.color = new Color(1f, 0.5f, 0f, 1f);
        Gizmos.DrawWireSphere(CurrentPathCorners[1] + up, waypointSwitchDistance);

        // 지금 향하는 타깃 웨이포인트 (코너 자르기 로직을 그대로 반영)
        Vector3 nw = CurrentPathCorners[1];
        if (CurrentPathCorners.Length > 2 &&
            Vector3.Distance(transform.position, nw) < waypointSwitchDistance)
            nw = CurrentPathCorners[2];

        Gizmos.color = Color.yellow;
        Gizmos.DrawSphere(nw + Vector3.up * 0.18f, 0.14f);
        Gizmos.DrawLine(transform.position + Vector3.up * 0.18f, nw + Vector3.up * 0.18f);
    }

    void OnControllerColliderHit(ControllerColliderHit hit)
    {
        if (isDemoMode || target == null || isArrived || hit == null || hit.collider == null)
            return;

        // 다른 학습 에이전트는 충돌 통계에서 제외한다.
        if (hit.gameObject.layer >= 7 && hit.gameObject.layer <= 12)
            return;

        // CharacterController.Move는 바닥과 접촉할 때도 매 step 콜백을 발생시킨다.
        // 위쪽을 향하는 접촉면은 바닥으로 보고 충돌 통계와 패널티에서 제외한다.
        if (hit.normal.y > 0.5f)
            return;

        AddReward(-0.02f);

        int colliderId = hit.collider.GetInstanceID();
        float lastTime;
        bool newCollisionEvent =
            !experimentLastCollisionTimeByCollider.TryGetValue(colliderId, out lastTime) ||
            Time.time - lastTime >= Mathf.Max(0.01f, experimentCollisionCooldown);

        if (newCollisionEvent)
        {
            experimentLastCollisionTimeByCollider[colliderId] = Time.time;
            experimentCollisionCount++;
            WriteExperimentEvent("collision", hit.gameObject.name, transform.position);
        }

        if (hit.gameObject.CompareTag("Obstacle"))
        {
            wallHitCount++;

            if (newCollisionEvent)
                experimentObstacleCollisionCount++;

            AddReward(-0.05f);

            if (wallHitCount > 50)
            {
                episodeFailed = true;
                AddReward(-1.0f);
                SafeEndEpisode();
            }
        }
    }

    public override void OnActionReceived(ActionBuffers actions)
    {
        if (evaluationLimitReached)
            return;

        if (isDemoMode || isArrived || target == null)
            return;

        if (!Academy.Instance.IsCommunicatorOn && !canMove && !evaluationMode)
            return;

        float moveForward = actions.ContinuousActions[0];
        float turn = actions.ContinuousActions[1];

        Vector3 posBefore = transform.position;

        // 회전 입력 평활화. 학습은 1배속, 가상 경로 생성은 virtualPlanRotateMultiplier배속으로
        // 움직이므로 '거리당 회전 응답'을 맞추기 위해 가상 모드에서는 필터를 더 빠르게 반응시킨다.
        // 이 보정이 없으면 빠른 가상 주행에서 코너를 지나친 뒤 되돌아오며 루프가 생긴다.
        float baseTurnLerp = 0.6f;
        float turnLerp = baseTurnLerp;
        if (!Academy.Instance.IsCommunicatorOn && canMove && !isArrived)
            turnLerp = Mathf.Clamp01(baseTurnLerp * virtualPlanRotateMultiplier);
        float smoothedTurn = Mathf.Lerp(previousTurn, turn, turnLerp);

        float currentMoveSpeed = moveSpeed;
        float currentRotateSpeedDeg = rotateSpeedDeg;

        // M키 가상 경로 생성 중에만 빠르게 이동한다.
        // 학습 중이나 C++ 실제 경로 추종 중에는 적용되지 않는다.
        if (!Academy.Instance.IsCommunicatorOn && canMove && !isArrived)
        {
            currentMoveSpeed *= virtualPlanSpeedMultiplier;
            currentRotateSpeedDeg *= virtualPlanRotateMultiplier;
        }

        transform.Rotate(0f, smoothedTurn * currentRotateSpeedDeg * Time.deltaTime, 0f);

        float lockedY = transform.position.y;

        Vector3 move =
            -transform.right *
            moveForward *
            currentMoveSpeed *
            Time.deltaTime;

        move.y = 0f;

        if (cc != null)
        {
            cc.Move(move);
        }
        else
        {
            transform.position += move;
        }

        // 이동 코드나 다른 컴포넌트가 Y를 변경해도 기존 높이로 복구
        Vector3 lockedPosition = transform.position;
        lockedPosition.y = lockedY;
        transform.position = lockedPosition;

        if (navAgent != null && navAgent.isOnNavMesh)
        {
            navAgent.nextPosition = transform.position;
        }

        // M키 가상 경로 생성 중 경로 기록
        if (!Academy.Instance.IsCommunicatorOn && canMove && !isArrived)
        {
            if (Time.time - lastRecordTime > pathRecordInterval)
            {
                float moved = Vector3.Distance(transform.position, lastRecordedPos);

                if (moved > minMoveThreshold)
                {
                    recordedPath.Add(transform.position);
                    lastRecordedPos = transform.position;
                }

                lastRecordTime = Time.time;
            }
        }

        // ===== 보상 체계 =====
        // 설계 의도:
        // 1) 매 프레임은 약하게 패널티를 주고
        // 2) 목표 방향 정렬과 경로 단축은 분명하게 보상하며
        // 3) 충돌/막힘/벽 긁기는 강하게 억제한다.
        // 이렇게 해야 빠르지만 위험한 정책보다, 조금 느려도 안정적인 정책이 남는다.
        AddReward(-0.001f);

        // 회전 자체가 아니라 회전 변화량만 벌한다.
        // 코너를 돌기 위한 지속 회전은 허용하고, 좌우 진동만 줄인다.
        AddReward(-Mathf.Abs(smoothedTurn - previousTurn) * 0.003f);

        Vector3 nextDir = GetNextWaypointDirection();
        float nextFacing = Vector3.Dot(-transform.right, nextDir);

        // 웨이포인트를 향해 꺾는 동작이 순이득이 되도록 정렬 보상을 준다.
        // 회전 페널티보다 작아지면, 에이전트가 방향 전환을 기피할 수 있다.
        AddReward(nextFacing * 0.01f);

        // 거의 정면 정렬이면 작은 보너스를 더 줘서 마지막 각도 맞추기를 돕는다.
        if (nextFacing > 0.95f)
            AddReward(0.002f);

        // 반대 방향을 보고 있으면 명확히 감점해서 되돌아가는 행동을 막는다.
        if (nextFacing < 0f)
            AddReward(-0.005f);

        // 목표까지의 전체 경로가 줄어들면 보상한다.
        // 벽 앞에서 빙빙 돌기보다, 실제로 경로를 줄이는 행동을 선호하게 만든다.
        float pathDist = GetNavMeshPathDistance(transform.position, target.position);
        float approachReward = Mathf.Clamp((previousPathDist - pathDist) * 1.5f, -0.05f, 0.05f);
        AddReward(approachReward);
        previousPathDist = pathDist;

        // 바로 다음 웨이포인트에 가까워질수록 보상한다.
        // 코너를 지나치면 별도 보너스가 한번 더 들어가므로, 코너 통과 행동이 살아난다.
        Vector3 nextWp = GetNextWaypoint();
        float waypointDist = Vector3.Distance(
            new Vector3(transform.position.x, 0f, transform.position.z),
            new Vector3(nextWp.x, 0f, nextWp.z)
        );

        float waypointReward = Mathf.Clamp(previousWaypointDist - waypointDist, -0.05f, 0.05f);
        AddReward(waypointReward);
        previousWaypointDist = waypointDist;

        // 웨이포인트를 실제로 지나친 순간에만 1회 보너스를 준다.
        // 매 프레임 보상하면 코너 근처에서 제자리 회전으로 보상을 파밍할 수 있다.
        int currentCornerCount = CurrentPathCorners.Length;
        if (previousCornerCount < 0)
            previousCornerCount = currentCornerCount;
        if (currentCornerCount < previousCornerCount && currentCornerCount >= 2)
            AddReward(0.3f);
        previousCornerCount = currentCornerCount;

        // 벽과의 간격을 유지해 좁은 복도에서 긁히는 행동을 줄인다.
        AddWallClearanceReward();

        float actualMoved = Vector3.Distance(transform.position, posBefore);
        AccumulateExperimentDistance(posBefore, transform.position);

        // 앞으로 가라고 했는데 실제로 못 움직이면 막힘으로 본다.
        if (moveForward > 0.1f && actualMoved < 0.001f)
        {
            stuckCount++;
            AddReward(-0.01f);

            if (stuckCount > 100)
            {
                experimentStuckEventCount++;
                experimentLastFailureReason = "training_stuck";
                episodeFailed = true;
                SafeEndEpisode();
                return;
            }
        }
        else
        {
            stuckCount = 0;
        }

        // 일반 M 테스트 중 막힘 감지
        if (enableStuckDetection &&
            !Academy.Instance.IsCommunicatorOn &&
            canMove &&
            !isArrived)
        {
            if (Mathf.Abs(moveForward) > 0.1f && actualMoved < blockedMoveThreshold)
            {
                blockedFrameCount++;

                if (blockedFrameCount >= blockedFrameLimit)
                {
                    Debug.LogWarning("[GO1Agent] 이동 중 막힘 감지: 경로 생성 중단");
                    experimentStuckEventCount++;
                    experimentLastFailureReason = "virtual_path_blocked";
                    WriteExperimentEvent("stuck", experimentLastFailureReason, transform.position);

                    canMove = false;
                    isArrived = false;
                    blockedFrameCount = 0;

                    ReturnVirtualToMissionStartPose();
                    EnableWASD();
                    return;
                }
            }
            else
            {
                blockedFrameCount = 0;
            }
        }

        previousTurn = smoothedTurn;
        previousMove = moveForward;

        float directDist = Vector3.Distance(transform.position, target.position);

        if (directDist < GoalArrivalDistance)
        {
            // C2/C3 관리형 평가에서는 TrainingManager의 새 목표 생성과 EndEpisode를 실행하기 전에
            // 평가 관리자에게 기준 경로 저장/동일 시작점 재주행/결과 처리를 위임합니다.
            if (c2c3EvaluationManager != null &&
                c2c3EvaluationManager.IsRunning &&
                c2c3EvaluationManager.HandleAgentGoalReached(this))
            {
                return;
            }

            if (Academy.Instance.IsCommunicatorOn || evaluationMode)
            {
                AddReward(10.0f);
                episodeFailed = false;
                retryCount = 0;

                // 기록을 먼저 한다. OnAgentReachedGoal()이 새 목표를 할당하므로,
                // 그 전에 FinishExperimentTrial을 호출해야 '도달한 목표' 기준으로 오차가 찍힌다.
                FinishExperimentTrial(true, evaluationMode && !Academy.Instance.IsCommunicatorOn ? "eval_goal" : "training_goal");

                if (trainingManager != null)
                    trainingManager.OnAgentReachedGoal(this);

                SafeEndEpisode();
            }
            else
            {
                // C++로 보내기 직전에 큐에 남아 있던 소화기 JSON을 먼저 처리한다.
                // 여기서 보정이 적용되면 지금까지 만든 recordedPath는 보정 전 좌표계 기준이므로 폐기하고 다시 경로를 만든다.
                if (TryRestartVirtualPathIfFireCorrectedBeforeSendingPath("before-send-path"))
                    return;

                // 마지막 점이 target과 충분히 다르면 target도 추가
                if (recordedPath.Count > 0)
                {
                    float lastDist = Vector3.Distance(recordedPath[recordedPath.Count - 1], target.position);

                    if (lastDist > 0.1f)
                        recordedPath.Add(target.position);
                    else
                        recordedPath[recordedPath.Count - 1] = target.position;
                }
                else
                {
                    recordedPath.Add(target.position);
                }

                // BoatAgent처럼 로컬 경로 검증 모드를 사용하는 파생 Agent는
                // C++/UDP로 경로를 보내지 않고, 방금 생성한 경로를 시작점부터 직접 다시 따라간다.
                if (UseLocalGeneratedPathReplay)
                {
                    bool replayStarted = StartLocalGeneratedPathReplay();

                    if (!replayStarted)
                    {
                        canMove = false;
                        isArrived = false;
                        EnableWASD();

                        Debug.LogWarning(
                            $"[{gameObject.name}] 생성 경로 로컬 재생을 시작하지 못했습니다."
                        );
                    }

                    return;
                }

                bool pathSendStarted = SendPathToRobot();

                // 케이스 스터디 로거: 경로 전송
                if (pathSendStarted)
                    caseStudyLogger?.LogPathSentToRobot(recordedPath.Count, 0f);

                // 가상 GO1을 이번 M 시작 위치로 되돌린다.
                // path가 실제로 전송된 경우에는 state_change=true가 오기 전까지
                // C++ state를 가상 GO1에 반영하지 않는다.
                ReturnVirtualToMissionStartPose(!pathSendStarted);

                // 케이스 스터디 로거: 가상 경로 생성 완료
                caseStudyLogger?.LogVirtualPathDone(recordedPath.Count);

                isArrived = true;
                canMove = false;

                if (pathSendStarted)
                {
                    HoldVirtualGo1UntilRealMotion("path sent, waiting state_change=true");
                    StartRealGo1PathFollowing();
                    Debug.Log($"[{gameObject.name}] 목표 도달. 경로 전송 완료. 5009 state_change=true 대기 시작.");
                }
                else
                {
                    EnableWASD();
                    Debug.LogWarning($"[{gameObject.name}] 목표 도달했지만 생성 경로가 유효하지 않아 전송하지 않았습니다. 재탐색 재시도 조건이면 다시 경로를 생성합니다.");
                }
            }

            return;
        }

        if (StepCount >= MaxStep - 1)
        {
            if (Academy.Instance.IsCommunicatorOn || evaluationMode)
            {
                episodeFailed = true;

                if (trainingManager != null)
                    trainingManager.OnAgentFailed(this);

                SafeEndEpisode();
            }
        }
    }


    private bool StartLocalGeneratedPathReplay()
    {
        if (localPathReplayActive)
        {
            Debug.LogWarning($"[{gameObject.name}] 이미 생성 경로를 재생 중입니다.");
            return false;
        }

        if (recordedPath == null || recordedPath.Count < 2)
        {
            Debug.LogWarning(
                $"[{gameObject.name}] 로컬 재생 실패: 기록 경로 점이 2개 미만입니다. " +
                $"recorded={recordedPath?.Count ?? 0}"
            );
            return false;
        }

        List<Vector3> pathToReplay =
            BuildPathToSendFromRecordedPath(LocalReplayUseRawRecordedPath);

        if (pathToReplay == null || pathToReplay.Count < 2)
        {
            Debug.LogWarning(
                $"[{gameObject.name}] 로컬 재생 실패: 재생할 경로 점이 2개 미만입니다."
            );
            return false;
        }

        // 재생 시작점과 최종 목표점을 명시적으로 보장한다.
        if (Vector3.Distance(pathToReplay[0], missionStartPosition) > 0.05f)
            pathToReplay.Insert(0, missionStartPosition);
        else
            pathToReplay[0] = missionStartPosition;

        if (target != null)
        {
            if (Vector3.Distance(pathToReplay[pathToReplay.Count - 1], target.position) > 0.05f)
                pathToReplay.Add(target.position);
            else
                pathToReplay[pathToReplay.Count - 1] = target.position;
        }

        localReplayPath.Clear();
        localReplayPath.AddRange(pathToReplay);

        RecordExperimentPathPrepared(recordedPath, localReplayPath);
        recordedPath.Clear();

        canMove = false;
        isArrived = true;
        blockedFrameCount = 0;
        localPathReplayActive = true;
        localReplayMlAgentReplanPending = false;

        if (localReplayMlAgentPathGenerationActive)
        {
            localReplayMlAgentPathGenerationActive = false;
            ReplanCompleteExperiment("ml_agent_new_path_ready");
        }

        if (localPathReplayCoroutine != null)
            StopCoroutine(localPathReplayCoroutine);

        localPathReplayCoroutine =
            StartCoroutine(ReplayGeneratedPathLocally());

        Debug.Log(
            $"[{gameObject.name}] 생성 경로 로컬 재생 시작 | " +
            $"points={localReplayPath.Count}, " +
            $"speed={LocalReplayMoveSpeed:F2}, " +
            $"turnSpeed={LocalReplayRotateSpeedDeg:F1}, " +
            $"tolerance={LocalReplayWaypointTolerance:F2}"
        );

        return true;
    }

    private IEnumerator ReplayGeneratedPathLocally()
    {
        SetPoseForLocalReplay(missionStartPosition, missionStartRotation);

        // 텔레포트 결과가 NavMesh/Physics에 반영될 시간을 한 프레임 준다.
        yield return null;

        float replayStartTime = Time.time;
        int waypointIndex = 1;
        float lockedReplayY = missionStartPosition.y;

        while (waypointIndex < localReplayPath.Count)
        {
            if (!localPathReplayActive)
                yield break;

            if (Time.time - replayStartTime > LocalReplayTimeoutSeconds)
            {
                CompleteLocalReplay(
                    false,
                    "timeout",
                    GetPlanarDistance(transform.position, target != null ? target.position : transform.position)
                );
                yield break;
            }

            Vector3 waypoint = localReplayPath[waypointIndex];
            waypoint.y = lockedReplayY;

            Vector3 toWaypoint = waypoint - transform.position;
            toWaypoint.y = 0f;

            float waypointDistance = toWaypoint.magnitude;

            if (waypointDistance <= LocalReplayWaypointTolerance)
            {
                waypointIndex++;
                continue;
            }

            if (toWaypoint.sqrMagnitude > 0.000001f)
            {
                Vector3 desiredDirection = toWaypoint.normalized;

                // 기존 GO1Agent의 전진축은 -transform.right이므로,
                // -X축이 다음 waypoint를 향하도록 목표 Yaw를 만든다.
                Quaternion desiredRotation =
                    Quaternion.LookRotation(desiredDirection, Vector3.up) *
                    Quaternion.Euler(0f, 90f, 0f);

                transform.rotation = Quaternion.RotateTowards(
                    transform.rotation,
                    desiredRotation,
                    LocalReplayRotateSpeedDeg * Time.deltaTime
                );

                float headingError = Vector3.Angle(
                    -transform.right,
                    desiredDirection
                );

                // 방향이 크게 어긋난 상태에서는 먼저 회전하고,
                // 경로 방향과 가까워질수록 정상 속도로 전진한다.
                float moveFactor = Mathf.InverseLerp(90f, 10f, headingError);
                float moveDistance =
                    LocalReplayMoveSpeed *
                    moveFactor *
                    Time.deltaTime;

                Vector3 newPosition =
                    transform.position +
                    (-transform.right * moveDistance);

                newPosition.y = lockedReplayY;
                transform.position = newPosition;

                if (navAgent != null && navAgent.isOnNavMesh)
                    navAgent.nextPosition = transform.position;
            }

            yield return null;
        }

        float finalError = target != null
            ? GetPlanarDistance(transform.position, target.position)
            : float.MaxValue;

        bool success = target != null &&
                       finalError <= GoalArrivalDistance;

        CompleteLocalReplay(
            success,
            success ? "local_replay_goal" : "local_replay_final_error",
            finalError
        );
    }

    private void SetPoseForLocalReplay(Vector3 position, Quaternion rotation)
    {
        bool restoreCharacterController =
            cc != null && cc.enabled;

        if (restoreCharacterController)
            cc.enabled = false;

        Vector3 replayPosition = position;
        replayPosition.y = position.y;

        Quaternion replayRotation = Quaternion.Euler(
            0f,
            rotation.eulerAngles.y,
            0f
        );

        transform.SetPositionAndRotation(
            replayPosition,
            replayRotation
        );

        if (navAgent != null && navAgent.isOnNavMesh)
            navAgent.nextPosition = replayPosition;

        if (restoreCharacterController)
            cc.enabled = true;
    }

    private void CompleteLocalReplay(
        bool success,
        string reason,
        float finalError
    )
    {
        localPathReplayActive = false;
        localPathReplayCoroutine = null;
        localReplayMlAgentReplanPending = false;
        canMove = false;
        isArrived = success;

        if (success)
        {
            FinishExperimentTrial(true, reason);

            Debug.Log(
                $"[{gameObject.name}] 생성 경로 재주행 성공 | " +
                $"finalError={finalError:F2}m, " +
                $"arrivalDistance={GoalArrivalDistance:F2}m"
            );
        }
        else
        {
            FinishExperimentTrial(false, reason);

            Debug.LogWarning(
                $"[{gameObject.name}] 생성 경로 재주행 실패 | " +
                $"reason={reason}, finalError={finalError:F2}m, " +
                $"arrivalDistance={GoalArrivalDistance:F2}m"
            );
        }

        EnableWASD();
    }

    private void StopLocalGeneratedPathReplay(
        bool finishAsFailure,
        string reason
    )
    {
        if (localPathReplayCoroutine != null)
        {
            StopCoroutine(localPathReplayCoroutine);
            localPathReplayCoroutine = null;
        }

        if (localReplayMlAgentReplanCoroutine != null)
        {
            StopCoroutine(localReplayMlAgentReplanCoroutine);
            localReplayMlAgentReplanCoroutine = null;
        }

        bool wasActive =
            localPathReplayActive ||
            localReplayMlAgentReplanPending;

        localPathReplayActive = false;
        localReplayMlAgentReplanPending = false;
        localReplayMlAgentPathGenerationActive = false;
        localReplayPath.Clear();

        if (wasActive && finishAsFailure)
            FinishExperimentTrial(false, reason);
    }

    private void ResetLocalReplayMlAgentReplanForNewMission()
    {
        if (localReplayMlAgentReplanCoroutine != null)
        {
            StopCoroutine(localReplayMlAgentReplanCoroutine);
            localReplayMlAgentReplanCoroutine = null;
        }

        localReplayMlAgentReplanPending = false;
        localReplayMlAgentPathGenerationActive = false;
        localReplayMlAgentReplanCount = 0;
    }

    private IEnumerator RestartMlAgentPlanningAfterBuoy(
        string reason,
        float carvingWaitSeconds
    )
    {
        if (carvingWaitSeconds > 0f)
            yield return new WaitForSeconds(carvingWaitSeconds);

        float deadline =
            Time.time +
            Mathf.Max(
                0.5f,
                LocalReplayMlAgentReplanReadyTimeout
            );

        // NavMeshObstacle carving이 아직 반영되지 않았으면
        // 완전한 우회 경로가 생길 때까지 짧게 재검사합니다.
        while (
            enableNavMeshPreCheck &&
            IsPathBlockedByNavMesh(
                transform.position,
                target.position
            )
        )
        {
            if (!localReplayMlAgentReplanPending)
                yield break;

            if (Time.time >= deadline)
            {
                localReplayMlAgentReplanPending = false;
                localReplayMlAgentPathGenerationActive = false;
                localReplayMlAgentReplanCoroutine = null;
                ReplanCompleteExperiment("ml_agent_replan_navmesh_not_ready");

                float finalError =
                    target != null
                        ? GetPlanarDistance(
                            transform.position,
                            target.position
                        )
                        : float.MaxValue;

                CompleteLocalReplay(
                    false,
                    "ml_replan_navmesh_not_ready",
                    finalError
                );

                yield break;
            }

            yield return new WaitForSeconds(0.1f);
        }

        if (!localReplayMlAgentReplanPending)
            yield break;

        // 함선 현재 위치/회전을 그대로 새 missionStartPose로 사용합니다.
        // BoatAgent는 실제 GO1 SDK pose 동기화가 필요 없으므로 이번 시작에서 건너뜁니다.
        suppressManualStartSdkSyncOnce = true;

        localReplayMlAgentReplanPending = false;
        localReplayMlAgentReplanCoroutine = null;

        Debug.Log(
            $"[{gameObject.name}] ML-Agent 재탐색 시작 | " +
            $"reason={reason}, start={transform.position}, target={target.position}"
        );

        // 여기서부터는 기존 M키 경로 생성과 완전히 같은 ONNX/ML-Agent 흐름입니다.
        StartMission();
    }

    private static float GetPlanarDistance(Vector3 a, Vector3 b)
    {
        float dx = a.x - b.x;
        float dz = a.z - b.z;
        return Mathf.Sqrt(dx * dx + dz * dz);
    }

    public void OnPathCompleted()
    {
        Debug.Log("[GO1Agent] C++ 실제 GO1 경로 완료 수신");

        canMove = false;
        isArrived = true;
        ClearRealGo1PathCommandState("OnPathCompleted");
        fireLandmarkReplanning = false;
        currentSentPath.Clear();

        if (replanController != null)
            replanController.ResetAll("OnPathCompleted");

        StopActualGo1PointTrace(true);
        FinishExperimentTrial(true, "real_path_completed");

        // 현재 transform은 driveByState에 의해 실제 GO1 최종 pose를 따라가고 있어야 한다.
        // 다음 M을 누르면 이 pose가 새 missionStartPosition/Rotation이 된다.
        EnableWASD();
    }

    private Vector3 FixFireCorrectionAxis(Vector3 correctionDelta)
    {
        Vector3 fixedDelta = correctionDelta;
        fixedDelta.y = 0f;

        if (invertFireCorrectionX)
            fixedDelta.x = -fixedDelta.x;

        if (invertFireCorrectionZ)
            fixedDelta.z = -fixedDelta.z;

        return fixedDelta;
    }

    // Receiver가 감지 장애물 지도 전체를 같은 delta로 이동시킬 수 있도록,
    // GO1Agent에서 실제 적용한 축 보정 결과를 외부에 알려주는 함수입니다.
    public Vector3 GetFireLandmarkCorrectionDeltaAfterAxis(Vector3 correctionDelta)
    {
        return FixFireCorrectionAxis(correctionDelta);
    }

    public bool RequestFireLandmarkCorrectionReplan(
        Vector3 correctionDelta,
        string landmarkName,
        bool isNear,
        UnityTeleopAndMirror correctionUtm = null)
    {
        Vector3 ignoredAppliedDelta;
        return RequestFireLandmarkCorrectionReplan(
            correctionDelta,
            landmarkName,
            isNear,
            out ignoredAppliedDelta,
            correctionUtm
        );
    }

    public bool RequestFireLandmarkCorrectionReplan(
        Vector3 correctionDelta,
        string landmarkName,
        bool isNear,
        out Vector3 appliedCorrectionDelta,
        UnityTeleopAndMirror correctionUtm = null)
    {
        appliedCorrectionDelta = Vector3.zero;

        if (!enableFireLandmarkCorrectionReplan)
            return false;

        // 소화기 위치 보정은 near로 들어온 경우에만 사용한다.
        // middle/far 소화기는 표시만 하고 위치 보정/재탐색에는 쓰지 않는다.
        if (!isNear)
        {
            if (debugFireCorrectionReplan)
                Debug.Log("[GO1Agent] 소화기 landmark 보정 무시: near가 아님 | landmark=" + landmarkName);
            return false;
        }

        Vector3 rawCorrectionDelta = correctionDelta;
        correctionDelta = FixFireCorrectionAxis(correctionDelta);
        appliedCorrectionDelta = correctionDelta;

        if (debugFireCorrectionReplan &&
            (invertFireCorrectionX || invertFireCorrectionZ))
        {
            Debug.Log(
                "[GO1Agent] 소화기 landmark 보정 축 변환 | " +
                "raw=(" + rawCorrectionDelta.x.ToString("F3") + "," + rawCorrectionDelta.z.ToString("F3") + "), " +
                "fixed=(" + correctionDelta.x.ToString("F3") + "," + correctionDelta.z.ToString("F3") + "), " +
                "invertX=" + invertFireCorrectionX + ", invertZ=" + invertFireCorrectionZ
            );
        }

        float correctionDistance = correctionDelta.magnitude;

        if (correctionDistance < Mathf.Max(0f, fireCorrectionMinDeltaM))
        {
            if (debugFireCorrectionReplan)
            {
                Debug.Log(
                    "[GO1Agent] 소화기 landmark 보정 무시: 보정량이 작음 | " +
                    "delta=" + correctionDistance.ToString("F3") + "m, min=" + fireCorrectionMinDeltaM.ToString("F3")
                );
            }
            return false;
        }

        if (fireCorrectionInProgress || IsReplanningActive)
        {
            if (debugFireCorrectionReplan)
                Debug.Log("[GO1Agent] 소화기 landmark 보정 무시: 이미 보정/재탐색 중");
            return false;
        }

        if (Time.time - lastFireCorrectionReplanTime < Mathf.Max(0f, fireCorrectionReplanCooldown))
        {
            if (debugFireCorrectionReplan)
            {
                Debug.Log(
                    "[GO1Agent] 소화기 landmark 보정 무시: 쿨타임 중 | remaining=" +
                    (fireCorrectionReplanCooldown - (Time.time - lastFireCorrectionReplanTime)).ToString("F1") + "s"
                );
            }
            return false;
        }

        // 1) 현실 GO1이 실제 waypoint 경로를 따라가는 중이면:
        //    near 소화기를 처음 봤을 때만 PATH_CANCEL -> 정지 -> 보정 -> 재탐색을 수행한다.
        if (realGo1PathActive)
        {
            if (!cancelAndReplanOnFireLandmarkWhileRealPath)
                return false;

            int maxDuringPath = Mathf.Max(0, maxFireCorrectionReplanDuringPathPerMission);
            if (fireCorrectionDuringPathCountThisMission >= maxDuringPath)
            {
                if (debugFireCorrectionReplan)
                {
                    Debug.LogWarning(
                        "[GO1Agent] 소화기 landmark 이동 중 보정 제한 도달 | " +
                        "count=" + fireCorrectionDuringPathCountThisMission + "/" + maxDuringPath
                    );
                }
                return false;
            }

            fireCorrectionDuringPathCountThisMission++;
            lastFireCorrectionReplanTime = Time.time;
            fireCorrectionInProgress = true;

            if (fireReplanCoroutine != null)
                StopCoroutine(fireReplanCoroutine);

            fireReplanCoroutine = StartCoroutine(
                FireLandmarkCancelCorrectAndReplanRoutine(correctionDelta, landmarkName, correctionUtm)
            );
            return true;
        }

        // 2) 경로 완료 후 또는 정지 상태에서 near 소화기가 보이면:
        //    미션당 1번만 보정한다. 이때는 PATH_CANCEL/재탐색 없이 기준점만 보정한다.
        //    다음 M키를 누르면 보정된 위치 기준에서 새 경로가 만들어진다.
        if (!IsMoving())
        {
            int maxAfterDone = Mathf.Max(0, maxFireCorrectionAfterPathDonePerMission);
            if (fireCorrectionAfterPathDoneCountThisMission >= maxAfterDone)
            {
                if (debugFireCorrectionReplan)
                {
                    Debug.LogWarning(
                        "[GO1Agent] 소화기 landmark 경로 완료 후 보정 제한 도달 | " +
                        "count=" + fireCorrectionAfterPathDoneCountThisMission + "/" + maxAfterDone
                    );
                }
                return false;
            }

            bool applied = ApplyFireLandmarkCorrectionDelta(correctionDelta, landmarkName, correctionUtm, "after-path-done");
            if (applied)
            {
                fireCorrectionAfterPathDoneCountThisMission++;
                lastFireCorrectionReplanTime = Time.time;
            }
            return applied;
        }

        if (debugFireCorrectionReplan)
            Debug.Log("[GO1Agent] 소화기 landmark 보정 무시: 가상 경로 생성 중이거나 적용 불가 상태");

        return false;
    }

    private IEnumerator FireLandmarkCancelCorrectAndReplanRoutine(
        Vector3 correctionDelta,
        string landmarkName,
        UnityTeleopAndMirror correctionUtm)
    {
        fireLandmarkReplanning = true;

        if (debugFireCorrectionReplan)
        {
            Debug.Log(
                "[GO1Agent] 소화기 landmark 감지 → PATH_CANCEL + 정지 + 보정 + 재탐색 시작 | " +
                "landmark=" + landmarkName + ", correction=(" +
                correctionDelta.x.ToString("F3") + "," + correctionDelta.z.ToString("F3") + ")"
            );
        }

        ClearRealGo1PathCommandState("FireLandmarkCancelCorrectAndReplan");
        canMove = false;
        isArrived = false;
        blockedFrameCount = 0;
        currentSentPath.Clear();

        StopActualGo1PointTrace(false);
        EnableWASD();

        if (useSafeCancelBeforeReplan)
        {
            yield return StartCoroutine(SendCancelAndStopBurst());
        }
        else
        {
            if (pathSender != null)
                pathSender.SendPathCancel();

            if (utm != null)
            {
                utm.enableTeleop = true;
                utm.SendTeleopCmd(0f, 0f, 0f, 1);
                utm.driveByState = true;
            }

            if (replanStopWaitTime > 0f)
                yield return new WaitForSeconds(replanStopWaitTime);

            if (releaseEstopBeforeReplan && utm != null)
                utm.SendTeleopCmd(0f, 0f, 0f, 0);
        }

        if (navMeshCarvingWaitTime > 0f)
            yield return new WaitForSeconds(navMeshCarvingWaitTime);

        bool corrected = ApplyFireLandmarkCorrectionDelta(
            correctionDelta,
            landmarkName,
            correctionUtm,
            "during-path-cancel-replan"
        );

        if (!corrected)
        {
            Debug.LogWarning("[GO1Agent] 소화기 landmark 보정 적용 실패. 재탐색을 중단합니다.");
            fireLandmarkReplanning = false;
            fireCorrectionInProgress = false;
            fireReplanCoroutine = null;
            EnableWASD();
            yield break;
        }

        if (target == null)
        {
            Debug.LogWarning("[GO1Agent] 소화기 landmark 재탐색 실패: target이 없습니다.");
            fireLandmarkReplanning = false;
            fireCorrectionInProgress = false;
            fireReplanCoroutine = null;
            EnableWASD();
            yield break;
        }

        if (enableNavMeshPreCheck && IsPathBlockedByNavMesh(transform.position, target.position))
        {
            Debug.LogWarning("[GO1Agent] 소화기 landmark 재탐색 실패: 목표까지 완전한 NavMesh 경로가 없습니다.");
            fireLandmarkReplanning = false;
            fireCorrectionInProgress = false;
            fireReplanCoroutine = null;
            EnableWASD();
            yield break;
        }

        if (enablePhysicalPathCheck && IsPathPhysicallyBlocked(transform.position, target.position))
        {
            Debug.LogWarning("[GO1Agent] 소화기 landmark 재탐색 실패: Collider 기준 경로가 막혀 있습니다.");
            fireLandmarkReplanning = false;
            fireCorrectionInProgress = false;
            fireReplanCoroutine = null;
            EnableWASD();
            yield break;
        }

        EnsureReplanController();
        replanController.MarkRuntimePathWaitingForSend();
        StartMission();

        fireLandmarkReplanning = false;
        fireCorrectionInProgress = false;
        fireReplanCoroutine = null;
    }

    private bool ApplyFireLandmarkCorrectionDelta(
        Vector3 correctionDelta,
        string landmarkName,
        UnityTeleopAndMirror correctionUtm,
        string phase)
    {
        correctionDelta.y = 0f;

        if (correctionDelta.sqrMagnitude < 0.000001f)
            return false;

        UnityTeleopAndMirror targetUtm = correctionUtm != null ? correctionUtm : utm;
        if (targetUtm == null)
            targetUtm = FindFirstObjectByType<UnityTeleopAndMirror>();

        if (targetUtm != null)
        {
            targetUtm.ApplyExternalUnityPositionCorrection(
                correctionDelta,
                "fire-landmark " + phase + " " + landmarkName,
                true
            );
        }
        else
        {
            transform.position += correctionDelta;
        }

        missionStartPosition = transform.position;
        missionStartRotation = transform.rotation;
        lastRecordedPos = missionStartPosition;

        if (pathPlanner != null)
            pathPlanner.Warp(missionStartPosition);

        fireCorrectionVersion++;

        // 소화기 보정 직후 다음 경로 생성에서 C++ state pose를 다시 강제 동기화하면
        // 방금 보정한 Unity 기준 위치가 이전 SDK pose로 되돌아갈 수 있으므로 1회 건너뛴다.
        if (phase != "during-path-cancel-replan")
            suppressManualStartSdkSyncOnce = true;

        if (debugFireCorrectionReplan)
        {
            Debug.Log(
                "[GO1Agent] 소화기 landmark 보정 적용 | " +
                "phase=" + phase + ", landmark=" + landmarkName + ", delta=(" +
                correctionDelta.x.ToString("F3") + "," + correctionDelta.z.ToString("F3") + "), " +
                "newPos=" + transform.position
            );
        }

        return true;
    }

    public void OnRuntimeObstacleUpdated(GameObject obstacle)
    {
        // 케이스 스터디 로거: 장애물 Unity 반영
        caseStudyLogger?.LogObstacleInUnity(obstacle);

        EnsureReplanController();
        replanController.OnRuntimeObstacleUpdated(obstacle);
    }





    private void SyncVirtualPoseToCurrentSdkState(string reason, bool preferCancelAckPose = true, bool printLog = true)
    {
        if (reason.StartsWith("runtime-replan") && !syncPoseToSdkBeforeReplan)
            return;

        if (utm == null || !utm.HasSdkState())
        {
            if (printLog)
                Debug.LogWarning("[GO1Agent] pose 동기화 실패: 아직 C++ state가 없습니다. reason=" + reason);

            return;
        }

        Vector3 realPos;
        Quaternion realRot;
        bool usedCancelAckPose = false;
        ulong ackSeq = 0;

        // 재탐색 직전에는 "현재 Unity Transform"보다
        // C++이 PATH_CANCEL을 처리한 순간(mode=98 ACK)의 pose를 우선 사용한다.
        // 수동 M 시작에서는 최신 C++ state를 사용해서 Z키 보정 이후 yaw 기준을 맞춘다.
        if (preferCancelAckPose && utm.GetLastPathCancelAckUnityPose(out realPos, out realRot, out ackSeq))
        {
            usedCancelAckPose = true;
        }
        else
        {
            realPos = utm.GetCurrentSdkUnityMappedPosition();
            realRot = utm.GetCurrentSdkUnityMappedRotation();
        }

        bool ccWasEnabled = cc != null && cc.enabled;
        if (cc != null)
            cc.enabled = false;

        transform.SetPositionAndRotation(realPos, realRot);

        if (wasdDrive != null && wasdDrive.transform != transform)
            wasdDrive.transform.SetPositionAndRotation(realPos, realRot);

        if (pathPlanner != null)
            pathPlanner.Warp(realPos);

        if (cc != null)
            cc.enabled = ccWasEnabled;

        missionStartPosition = realPos;
        missionStartRotation = realRot;
        lastRecordedPos = realPos;
        previousPathDist = target != null ? GetNavMeshPathDistance(transform.position, target.position) : previousPathDist;

        if (printLog)
        {
            Debug.Log(
                "[GO1Agent] C++ state 기준 pose/yaw 동기화 | " +
                "reason=" + reason +
                ", source=" + (usedCancelAckPose ? ("cancelACK seq=" + ackSeq) : "currentState") +
                ", pos=" + realPos +
                ", yaw=" + realRot.eulerAngles.y.ToString("F1") + "deg"
            );
        }
    }

    public void ApplyExternalYawSync(float unityYawDeg, string reason)
    {
        if (!allowExternalYawSync)
            return;

        bool ccWasEnabled = cc != null && cc.enabled;
        if (cc != null)
            cc.enabled = false;

        Vector3 euler = transform.eulerAngles;
        Quaternion rot = Quaternion.Euler(euler.x, unityYawDeg, euler.z);
        transform.rotation = rot;

        if (wasdDrive != null && wasdDrive.transform != transform)
        {
            Vector3 driveEuler = wasdDrive.transform.eulerAngles;
            wasdDrive.transform.rotation = Quaternion.Euler(driveEuler.x, unityYawDeg, driveEuler.z);
        }

        if (pathPlanner != null)
            pathPlanner.Warp(transform.position);

        if (cc != null)
            cc.enabled = ccWasEnabled;

        missionStartRotation = transform.rotation;

        if (debugManualStartPoseSync || debugReplanPoseSync)
        {
            Debug.Log(
                "[GO1Agent] 외부 yaw 동기화 적용 | " +
                "reason=" + reason +
                ", yaw=" + unityYawDeg.ToString("F2") + "deg"
            );
        }
    }

    private IEnumerator SendCancelAndStopBurst()
    {
        int count = Mathf.Max(1, cancelRepeatCount);

        if (utm != null)
        {
            utm.enableTeleop = true;
            utm.driveByState = true;
            utm.ClearPathCancelAck();
        }

        for (int i = 0; i < count; i++)
        {
            if (pathSender != null)
                pathSender.SendPathCancel();

            if (utm != null)
                utm.SendTeleopCmd(0f, 0f, 0f, 1);

            if (debugRuntimeReplan)
                Debug.Log("[GO1Agent] PATH_CANCEL/STOP 전송 " + (i + 1) + "/" + count);

            if (cancelRepeatInterval > 0f)
                yield return new WaitForSeconds(cancelRepeatInterval);
        }

        if (waitForCancelAckBeforeReplan && utm != null)
        {
            bool gotAck = false;
            float ackStart = Time.time;
            float timeout = Mathf.Max(0.1f, cancelAckTimeout);

            while (Time.time - ackStart < timeout)
            {
                if (utm.ConsumePathCancelAck())
                {
                    gotAck = true;

                    if (debugRuntimeReplan)
                    {
                        double ackX, ackZ, ackYaw;
                        ulong ackSeq;
                        utm.GetLastPathCancelAckRawState(out ackX, out ackZ, out ackYaw, out ackSeq);

                        Debug.Log(
                            "[GO1Agent] C++ PATH_CANCEL ACK 확인 완료 | " +
                            "seq=" + ackSeq +
                            ", rawPos=(" + ackX.ToString("F3") + "," + ackZ.ToString("F3") + ")" +
                            ", rawYaw=" + (ackYaw * Mathf.Rad2Deg).ToString("F1") + "deg"
                        );
                    }

                    break;
                }

                yield return null;
            }

            if (!gotAck)
            {
                Debug.LogWarning(
                    "[GO1Agent] C++ PATH_CANCEL ACK 대기 timeout. " +
                    "기존 시간 대기 방식으로 재탐색을 계속 진행합니다."
                );
            }
        }

        float waitTime = Mathf.Max(replanStopWaitTime, cancelToReplanWaitTime);
        if (waitTime > 0f)
            yield return new WaitForSeconds(waitTime);

        if (releaseEstopBeforeReplan && utm != null)
        {
            utm.SendTeleopCmd(0f, 0f, 0f, 0);

            if (debugRuntimeReplan)
                Debug.Log("[GO1Agent] estop 해제 명령 전송 후 재탐색 대기");

            if (estopReleaseWaitTime > 0f)
                yield return new WaitForSeconds(estopReleaseWaitTime);
        }
    }

    private int GetClosestPathSegmentIndex(Vector3 position)
    {
        if (currentSentPath == null || currentSentPath.Count < 2)
            return 0;

        int bestIndex = 0;
        float bestDistance = float.MaxValue;

        for (int i = 0; i < currentSentPath.Count - 1; i++)
        {
            float dist = DistancePointToSegmentXZ(position, currentSentPath[i], currentSentPath[i + 1]);

            if (dist < bestDistance)
            {
                bestDistance = dist;
                bestIndex = i;
            }
        }

        return bestIndex;
    }

    private Bounds GetObstacleBounds(GameObject obj)
    {
        Renderer renderer = obj.GetComponent<Renderer>();

        if (renderer == null)
            renderer = obj.GetComponentInChildren<Renderer>();

        if (renderer != null)
            return renderer.bounds;

        Collider collider = obj.GetComponent<Collider>();

        if (collider == null)
            collider = obj.GetComponentInChildren<Collider>();

        if (collider != null)
            return collider.bounds;

        return new Bounds(obj.transform.position, Vector3.one * 0.3f);
    }

    private float DistancePointToSegmentXZ(Vector3 p, Vector3 a, Vector3 b)
    {
        Vector2 p2 = new Vector2(p.x, p.z);
        Vector2 a2 = new Vector2(a.x, a.z);
        Vector2 b2 = new Vector2(b.x, b.z);

        Vector2 ab = b2 - a2;

        if (ab.sqrMagnitude < 0.0001f)
            return Vector2.Distance(p2, a2);

        float t = Vector2.Dot(p2 - a2, ab) / ab.sqrMagnitude;
        t = Mathf.Clamp01(t);

        Vector2 closest = a2 + ab * t;
        return Vector2.Distance(p2, closest);
    }

    private bool SendPathToRobot()
    {
        if (pathSender == null)
        {
            Debug.LogWarning("[GO1Agent] pathSender 없음");
            return false;
        }

        if (recordedPath.Count < 2)
        {
            Debug.LogWarning("[GO1Agent] 경로가 너무 짧음");
            TryScheduleRuntimeReplanGenerateRetry("recorded path too short");
            return false;
        }

        List<Vector3> pathToSend = BuildPathToSendFromRecordedPath(false);

        if (pathToSend.Count < 2)
        {
            Debug.LogWarning("[GO1Agent] 전송할 경로가 너무 짧음");
            TryScheduleRuntimeReplanGenerateRetry("send path too short");
            return false;
        }

        if (validateGeneratedPathBeforeSend && IsWorldPathPhysicallyBlocked(pathToSend, "generated-send-path"))
        {
            bool recoveredByRawPath = false;

            if (fallbackToRawRecordedPathWhenGeneratedPathBlocked && !sendRecordedPathAsIs)
            {
                List<Vector3> rawPath = BuildPathToSendFromRecordedPath(true);

                if (rawPath.Count >= 2 && !IsWorldPathPhysicallyBlocked(rawPath, "raw-recorded-path"))
                {
                    pathToSend = rawPath;
                    recoveredByRawPath = true;

                    if (debugRuntimeReplanRetry)
                    {
                        Debug.LogWarning(
                            "[GO1Agent] 단순화된 경로가 장애물을 통과하여 recordedPath 원본 경로로 대체합니다. " +
                            "send=" + pathToSend.Count
                        );
                    }
                }
            }

            if (!recoveredByRawPath)
            {
                Debug.LogWarning("[GO1Agent] 생성된 최종 경로가 장애물을 통과합니다. C++로 보내지 않고 재탐색을 시도합니다.");
                TryScheduleRuntimeReplanGenerateRetry("generated path blocked");
                return false;
            }
        }

        currentSentPath.Clear();
        currentSentPath.AddRange(pathToSend);
        realGo1StartPathResendCount = 0;

        RecordExperimentPathPrepared(recordedPath, pathToSend);

        Debug.Log(
            $"[GO1Agent] 경로 전송 | recorded={recordedPath.Count}, send={pathToSend.Count}, " +
            $"startPos={missionStartPosition}, startRot={missionStartRotation.eulerAngles}"
        );

        // UDP cancel/new path가 너무 붙어서 가면 C++에서 cancel이 새 path를 지워버리는 상황이 생길 수 있다.
        // 최소 전송 간격을 보장해서 경로 전송 꼬임을 줄인다.
        float sinceLastPathSend = Time.time - lastPathSendTime;
        if (sinceLastPathSend < minPathSendInterval)
        {
            if (debugRuntimeReplan)
            {
                Debug.Log(
                    "[GO1Agent] path 전송 간격 보호 | wait=" +
                    (minPathSendInterval - sinceLastPathSend).ToString("F2") + "s"
                );
            }

            // SendPathToRobot은 코루틴이 아니므로 여기서는 즉시 지연 실행 코루틴으로 넘긴다.
            StartCoroutine(DelayedSendPathToRobot(pathToSend, true));
            recordedPath.Clear();
            return true;
        }

        // 이번 M 시작 pose를 JSON local frame 기준으로 사용.
        pathSender.CaptureStartPose(pathToSend[0], missionStartRotation);
        pathSender.SendPathFromCorners(pathToSend.ToArray());
        lastPathSendTime = Time.time;
        MarkExperimentPathSent("immediate");

        if (replanController != null)
        {
            bool wasWaitingForSend = replanController.IsRuntimePathWaitingForSend;
            replanController.NotifyPathSent();
            // 재탐색 경로인 경우 케이스 스터디 로거 기록
            if (wasWaitingForSend)
                caseStudyLogger?.LogReplanPathSent(pathToSend.Count, 0f);
        }

        recordedPath.Clear();
        return true;
    }

    private List<Vector3> BuildPathToSendFromRecordedPath(bool forceRaw)
    {
        if (forceRaw || sendRecordedPathAsIs)
            return new List<Vector3>(recordedPath);

        List<Vector3> simplified = SimplifyPath(recordedPath, simplifyTolerance);
        return ReducePathKeepCorners(
            simplified,
            minSendPointSpacing,
            cornerKeepAngleDeg,
            maxSendPointCount
        );
    }

    private bool IsWorldPathPhysicallyBlocked(List<Vector3> worldPath, string context)
    {
        if (worldPath == null || worldPath.Count < 2)
            return true;

        QueryTriggerInteraction triggerMode = includeTriggerCollidersInGeneratedPathValidation
            ? QueryTriggerInteraction.Collide
            : QueryTriggerInteraction.Ignore;

        for (int i = 0; i < worldPath.Count - 1; i++)
        {
            Vector3 a = worldPath[i];
            Vector3 b = worldPath[i + 1];

            Vector3 dir = b - a;
            dir.y = 0f;

            float dist = dir.magnitude;
            if (dist < 0.01f)
                continue;

            dir.Normalize();

            Vector3 p1 = a + Vector3.up * 0.2f;
            Vector3 p2 = a + Vector3.up * pathCheckHeight;

            bool hit = Physics.CapsuleCast(
                p1,
                p2,
                pathCheckRadius,
                dir,
                out RaycastHit hitInfo,
                dist,
                obstacleLayerMask,
                triggerMode
            );

            Debug.DrawLine(
                a + Vector3.up * 0.08f,
                b + Vector3.up * 0.08f,
                hit ? Color.red : Color.cyan,
                1.5f
            );

            if (hit)
            {
                if (debugRuntimeReplanRetry)
                {
                    Debug.LogWarning(
                        "[GO1Agent] 최종 경로 장애물 통과 감지 | " +
                        "context=" + context +
                        ", obstacle=" + hitInfo.collider.name +
                        ", segment=" + i +
                        ", hitDist=" + hitInfo.distance.ToString("F2")
                    );
                }

                return true;
            }
        }

        return false;
    }

    private bool TryScheduleRuntimeReplanGenerateRetry(string reason)
    {
        EnsureReplanController();
        return replanController.TryScheduleGeneratedPathRetry(reason);
    }



    private IEnumerator DelayedSendPathToRobot(List<Vector3> pathToSend, bool startWaitAfterSend = false)
    {
        float wait = Mathf.Max(0f, minPathSendInterval - (Time.time - lastPathSendTime));
        if (wait > 0f)
            yield return new WaitForSeconds(wait);

        if (pathSender == null || pathToSend == null || pathToSend.Count < 2)
            yield break;

        currentSentPath.Clear();
        currentSentPath.AddRange(pathToSend);

        pathSender.CaptureStartPose(pathToSend[0], missionStartRotation);
        pathSender.SendPathFromCorners(pathToSend.ToArray());
        lastPathSendTime = Time.time;
        MarkExperimentPathSent("delayed");

        if (replanController != null)
        {
            bool wasWaitingForSend = replanController.IsRuntimePathWaitingForSend;
            replanController.NotifyPathSent();
            if (wasWaitingForSend)
                caseStudyLogger?.LogReplanPathSent(pathToSend.Count, 0f);
        }

        if (startWaitAfterSend)
        {
            HoldVirtualGo1UntilRealMotion("delayed path sent, waiting state_change=true");
            StartRealGo1PathFollowing();
        }

        if (debugRuntimeReplan)
            Debug.Log("[GO1Agent] 지연 path 전송 완료 | send=" + pathToSend.Count);
    }

    private void StartRealGo1PathFollowing()
    {
        realGo1PathCommandSent = true;
        realGo1PathActive = false;

        if (realGo1StartWaitCoroutine != null)
        {
            StopCoroutine(realGo1StartWaitCoroutine);
            realGo1StartWaitCoroutine = null;
        }

        if (!waitForStateChangeTrueBeforeRealPathActive)
        {
            ActivateRealGo1PathFollowing("state_change wait disabled");
            return;
        }

        if (obstacleReceiver == null)
            obstacleReceiver = FindFirstObjectByType<Go1ObstacleJsonReceiver>();

        waitingRealGo1Start = true;
        realGo1StartWaitBeginTime = Time.time;
        realGo1StartWaitCoroutine = StartCoroutine(WaitForRealGo1StateChangeTrueRoutine());

        if (debugRealGo1StartWait)
        {
            Debug.Log(
                "[GO1Agent] path 전송 완료 → 5009 state_change=true 대기 시작 | " +
                "receiver=" + (obstacleReceiver != null ? obstacleReceiver.name : "null") +
                ", timeout=" + realGo1StartWaitTimeoutSec.ToString("F1") + "s"
            );
        }
    }

    private IEnumerator WaitForRealGo1StateChangeTrueRoutine()
    {
        while (true)
        {
            string summary;
            if (CanActivateRealPathByStateChange(out summary))
            {
                ActivateRealGo1PathFollowing("state_change=true | " + summary);
                yield break;
            }

            if (realGo1StartWaitTimeoutSec > 0f &&
                Time.time - realGo1StartWaitBeginTime >= realGo1StartWaitTimeoutSec)
            {
                string resendBlockReason;
                if (CanResendCurrentPathOnStateTimeout(out resendBlockReason))
                {
                    yield return StartCoroutine(ResendCurrentPathAfterStateTimeoutRoutine(summary));
                    continue;
                }

                waitingRealGo1Start = false;
                realGo1StartWaitCoroutine = null;

                if (activateRealPathOnStateWaitTimeout)
                {
                    ActivateRealGo1PathFollowing("state_change wait timeout fallback | " + summary + ", resend=" + resendBlockReason);
                }
                else
                {
                    realGo1PathActive = false;

                    if (debugRealGo1StartWait)
                    {
                        Debug.LogWarning(
                            "[GO1Agent] state_change=true 대기 timeout → 실제 GO1이 움직이지 않는 것으로 판단 | " +
                            summary + ", resend=" + resendBlockReason
                        );
                    }
                }

                yield break;
            }

            yield return null;
        }
    }

    private bool CanResendCurrentPathOnStateTimeout(out string reason)
    {
        if (!resendPathOnStateChangeTimeout)
        {
            reason = "timeout resend disabled";
            return false;
        }

        int maxResend = Mathf.Max(0, maxStateChangeTimeoutPathResendCount);
        if (realGo1StartPathResendCount >= maxResend)
        {
            reason = "timeout resend limit reached " + realGo1StartPathResendCount + "/" + maxResend;
            return false;
        }

        if (pathSender == null)
        {
            reason = "pathSender null";
            return false;
        }

        if (currentSentPath == null || currentSentPath.Count < 2)
        {
            reason = "currentSentPath invalid";
            return false;
        }

        reason = "resend available " + realGo1StartPathResendCount + "/" + maxResend;
        return true;
    }

    private IEnumerator ResendCurrentPathAfterStateTimeoutRoutine(string timeoutSummary)
    {
        realGo1StartPathResendCount++;
        int resendIndex = realGo1StartPathResendCount;
        int maxResend = Mathf.Max(0, maxStateChangeTimeoutPathResendCount);

        if (debugRealGo1StartWait)
        {
            Debug.LogWarning(
                "[GO1Agent] state_change=true 대기 timeout → 동일 경로 재전송 예약 | " +
                "resend=" + resendIndex + "/" + maxResend +
                ", pathPoints=" + (currentSentPath != null ? currentSentPath.Count : 0) +
                ", lastState=" + timeoutSummary
            );
        }

        float extraDelay = Mathf.Max(0f, stateChangeTimeoutPathResendDelay);
        if (extraDelay > 0f)
            yield return new WaitForSeconds(extraDelay);

        float intervalWait = Mathf.Max(0f, minPathSendInterval - (Time.time - lastPathSendTime));
        if (intervalWait > 0f)
            yield return new WaitForSeconds(intervalWait);

        // 재전송 대기 중 state_change=true가 늦게 들어왔으면 굳이 다시 보내지 않고 바로 활성화한다.
        string lateSummary;
        if (CanActivateRealPathByStateChange(out lateSummary))
        {
            ActivateRealGo1PathFollowing("late state_change=true before resend | " + lateSummary);
            yield break;
        }

        // 대기 중 N키/재탐색/완료 등으로 상태가 초기화되었으면 재전송하지 않는다.
        if (!realGo1PathCommandSent || !waitingRealGo1Start)
        {
            if (debugRealGo1StartWait)
            {
                Debug.LogWarning(
                    "[GO1Agent] 동일 경로 재전송 취소: 대기 중 경로 상태가 해제됨 | " +
                    "commandSent=" + realGo1PathCommandSent +
                    ", waiting=" + waitingRealGo1Start
                );
            }
            yield break;
        }

        if (pathSender == null || currentSentPath == null || currentSentPath.Count < 2)
        {
            if (debugRealGo1StartWait)
                Debug.LogWarning("[GO1Agent] 동일 경로 재전송 실패: pathSender 또는 currentSentPath가 유효하지 않습니다.");
            yield break;
        }

        pathSender.CaptureStartPose(currentSentPath[0], missionStartRotation);
        pathSender.SendPathFromCorners(currentSentPath.ToArray());
        lastPathSendTime = Time.time;

        // 재전송한 시점 이후에 들어오는 state_change=true만 fresh state로 인정하도록 타이머를 다시 시작한다.
        realGo1StartWaitBeginTime = Time.time;
        waitingRealGo1Start = true;
        realGo1PathActive = false;

        if (debugRealGo1StartWait)
        {
            Debug.Log(
                "[GO1Agent] 동일 경로 재전송 완료 → state_change=true 재대기 시작 | " +
                "resend=" + resendIndex + "/" + maxResend +
                ", timeout=" + realGo1StartWaitTimeoutSec.ToString("F1") + "s" +
                ", pathPoints=" + currentSentPath.Count
            );
        }
    }

    private bool CanActivateRealPathByStateChange(out string summary)
    {
        if (obstacleReceiver == null)
            obstacleReceiver = FindFirstObjectByType<Go1ObstacleJsonReceiver>();

        if (obstacleReceiver == null)
        {
            summary = "motion receiver not found";
            return false;
        }

        summary = obstacleReceiver.GetLastGo1MotionStateSummary();

        if (!obstacleReceiver.ShouldMoveVirtualGo1AfterPathSent())
            return false;

        if (requireFreshStateChangeAfterPathSend)
        {
            float age = obstacleReceiver.GetLastGo1MotionStateAgeSec();
            float elapsedAfterPathSent = Mathf.Max(0f, Time.time - realGo1StartWaitBeginTime);

            // age가 경로 전송 후 경과 시간보다 작거나 같으면, 경로 전송 이후에 들어온 상태값으로 볼 수 있다.
            if (age > elapsedAfterPathSent + 0.05f)
            {
                summary += ", ignored stale state before path send";
                return false;
            }
        }

        return true;
    }

    private void ActivateRealGo1PathFollowing(string reason)
    {
        waitingRealGo1Start = false;
        realGo1PathActive = true;
        realGo1StartWaitCoroutine = null;
        firstFalseStateWhileRealPathActiveTime = -999f;

        // 케이스 스터디 로거: 실제 Go1 주행 시작 확인
        caseStudyLogger?.LogRealGo1Started();

        if (utm != null)
        {
            utm.enableTeleop = true;

            // 핵심:
            // state_change=true가 들어온 순간 driveByState를 바로 켜면,
            // UTM이 가지고 있던 SDK 절대 위치로 가상 GO1이 순간이동할 수 있다.
            // 따라서 현재 가상 GO1 위치를 "지금 SDK state의 표시 위치"로 다시 기준 잡은 뒤에
            // driveByState를 켠다.
            utm.RebaseStateFollowToCurrentVirtualPose(
                transform.position,
                transform.rotation,
                "GO1Agent ActivateRealGo1PathFollowing | " + reason
            );

            utm.driveByState = true;
        }

        StartActualGo1PointTrace();

        if (debugRealGo1StartWait || debugRuntimeReplan)
        {
            Debug.Log(
                "[GO1Agent] 실제 GO1 이동 확인 → state follow rebase 후 realGo1PathActive=true | " +
                "reason=" + reason
            );
        }
    }

    private void UpdateRealGo1PathActiveFromStateChange()
    {
        if (!syncRealPathActiveFalseFromStateChange)
            return;

        if (!waitForStateChangeTrueBeforeRealPathActive)
            return;

        if (!realGo1PathCommandSent || !realGo1PathActive)
        {
            firstFalseStateWhileRealPathActiveTime = -999f;
            return;
        }

        if (obstacleReceiver == null)
            obstacleReceiver = FindFirstObjectByType<Go1ObstacleJsonReceiver>();

        if (obstacleReceiver == null || !obstacleReceiver.HasRecentGo1MotionState())
            return;

        // true가 들어오면 false 누적 시간을 초기화한다.
        // 5009 포트에 true/false 패킷이 섞여 들어오는 경우, false 한 번에 driveByState를 꺼버리면
        // 현실 GO1이 막 움직이기 시작해도 가상 GO1이 바로 멈춰 보일 수 있다.
        if (obstacleReceiver.IsRealGo1MovingByStateChange())
        {
            firstFalseStateWhileRealPathActiveTime = -999f;
            return;
        }

        if (requireContinuousFalseBeforeDisablingRealPath)
        {
            if (firstFalseStateWhileRealPathActiveTime < 0f)
            {
                firstFalseStateWhileRealPathActiveTime = Time.time;

                if (debugRealGo1StartWait)
                {
                    Debug.Log(
                        "[GO1Agent] state_change=false 감지. 즉시 정지하지 않고 연속 false 유지 여부 확인 시작 | " +
                        obstacleReceiver.GetLastGo1MotionStateSummary()
                    );
                }

                return;
            }

            float hold = Mathf.Max(0.05f, realGo1FalseStateHoldSec);
            if (Time.time - firstFalseStateWhileRealPathActiveTime < hold)
                return;
        }

        realGo1PathActive = false;
        firstFalseStateWhileRealPathActiveTime = -999f;

        if (utm != null)
        {
            utm.enableTeleop = true;
            utm.driveByState = false;
        }

        StopActualGo1PointTrace(false);

        if (debugRealGo1StartWait)
        {
            Debug.Log(
                "[GO1Agent] state_change=false 지속 확인 → 실제 GO1 이동 중 아님으로 판단, driveByState=false | " +
                obstacleReceiver.GetLastGo1MotionStateSummary()
            );
        }
    }

    private void ClearRealGo1PathCommandState(string reason)
    {
        realGo1PathCommandSent = false;
        realGo1PathActive = false;
        firstFalseStateWhileRealPathActiveTime = -999f;
        waitingRealGo1Start = false;
        realGo1StartPathResendCount = 0;

        if (realGo1StartWaitCoroutine != null)
        {
            StopCoroutine(realGo1StartWaitCoroutine);
            realGo1StartWaitCoroutine = null;
        }

        if (debugRealGo1StartWait)
        {
            Debug.Log("[GO1Agent] 실제 GO1 경로 상태 초기화 | reason=" + reason);
        }
    }

    private void HoldVirtualGo1UntilRealMotion(string reason)
    {
        if (utm != null)
        {
            utm.enableTeleop = true;
            utm.driveByState = false;
        }

        if (debugRealGo1StartWait)
        {
            Debug.Log("[GO1Agent] state_change=true 대기 중 → 가상 GO1 state 반영 중지 | reason=" + reason);
        }
    }

    private void ReturnVirtualToMissionStartPose(bool enableStateFollowAfterReturn = true)
    {
        bool ccWasEnabled = cc != null && cc.enabled;

        if (cc != null)
            cc.enabled = false;

        transform.SetPositionAndRotation(missionStartPosition, missionStartRotation);

        if (pathPlanner != null)
            pathPlanner.Warp(missionStartPosition);

        if (cc != null)
            cc.enabled = ccWasEnabled;

        lastRecordedPos = missionStartPosition;

        if (utm != null)
        {
            utm.driveByState = enableStateFollowAfterReturn;
            utm.enableTeleop = true;
        }

        Debug.Log(
            $"[GO1Agent] 가상 GO1 시작 pose 복귀 | " +
            $"pos={missionStartPosition}, rot={missionStartRotation.eulerAngles}, " +
            $"driveByState={enableStateFollowAfterReturn}"
        );
    }

    /// <summary>
    /// C2/C3 기준 경로 생성이 끝난 시점의 recordedPath 복사본을 반환합니다.
    /// </summary>
    public List<Vector3> GetRecordedPathSnapshot(bool includeTarget)
    {
        List<Vector3> snapshot = new List<Vector3>(recordedPath);

        if (snapshot.Count == 0)
            snapshot.Add(transform.position);

        if (includeTarget && target != null)
        {
            if (snapshot.Count == 0 || Vector3.Distance(snapshot[snapshot.Count - 1], target.position) > 0.05f)
                snapshot.Add(target.position);
            else
                snapshot[snapshot.Count - 1] = target.position;
        }

        return snapshot;
    }

    /// <summary>
    /// CharacterController와 NavMeshAgent 상태를 안전하게 유지하면서 평가 시작 pose를 설정합니다.
    /// </summary>
    public void SetManagedEvaluationPose(Vector3 position, Quaternion rotation)
    {
        if (cc == null)
            cc = GetComponent<CharacterController>();

        bool ccWasEnabled = cc != null && cc.enabled;
        if (cc != null)
            cc.enabled = false;

        transform.SetPositionAndRotation(position, rotation);

        EnsurePathPlanner();
        pathPlanner.Warp(position);
        pathPlanner.SyncAgentPosition(position);

        if (cc != null)
            cc.enabled = ccWasEnabled;

        lastRecordedPos = position;
    }

    /// <summary>
    /// TrainingManager의 episode 순환을 사용하지 않고 C2/C3 평가용 가상 주행을 시작합니다.
    /// lockToProvidedPath=true이면 C2 기준 경로를 고정하고, C3는 장애물 생성 뒤 EvaluationManager가 잠금을 해제합니다.
    /// </summary>
    public void BeginManagedEvaluationRun(
        Vector3 startPosition,
        Quaternion startRotation,
        Vector3 goalPosition,
        IReadOnlyList<Vector3> providedPath,
        bool lockToProvidedPath,
        bool logAsExperimentTrial)
    {
        EnsurePathPlanner();
        EnsureReplanController();

        if (target == null)
        {
            Debug.LogError("[GO1Agent] 관리형 평가 시작 실패: target이 없습니다.", this);
            return;
        }

        if (experimentTrialActive && logAsExperimentTrial)
            FinishExperimentTrial(false, "managed_trial_restarted");

        ClearRealGo1PathCommandState("managed evaluation run start");
        currentSentPath.Clear();

        if (replanController != null)
            replanController.ResetAll("managed evaluation run start");

        SetManagedEvaluationPose(startPosition, startRotation);
        target.position = goalPosition;

        missionStartPosition = startPosition;
        missionStartRotation = startRotation;
        lastStartPos = startPosition;
        lastStartRot = startRotation;

        if (lockToProvidedPath)
        {
            if (!pathPlanner.SetLockedPath(providedPath))
            {
                Debug.LogError("[GO1Agent] 관리형 평가 시작 실패: 기준 경로 잠금에 실패했습니다.", this);
                canMove = false;
                isArrived = true;
                return;
            }
        }
        else
        {
            pathPlanner.ClearLockedPath();
        }

        episodeEnding = false;
        episodeFailed = false;
        isArrived = false;
        canMove = true;
        blockedFrameCount = 0;
        stuckCount = 0;
        wallHitCount = 0;
        previousTurn = 0f;
        previousMove = 0f;
        previousCornerCount = -1;
        pathFailCount = 0;
        retryCount = 0;

        recordedPath.Clear();
        recordedPath.Add(startPosition);
        lastRecordTime = 0f;
        lastRecordedPos = startPosition;

        if (utm != null)
        {
            utm.driveByState = false;
            utm.enableTeleop = true;
        }

        if (navigator != null)
            navigator.DisableExternalControllers();

        if (wasdDrive != null)
            wasdDrive.enabled = false;

        if (cc != null)
            cc.enabled = true;

        previousPathDist = GetNavMeshPathDistance(transform.position, target.position);
        CalculateCurrentPath(transform.position, target.position);

        Vector3 nextWp = GetNextWaypoint();
        previousWaypointDist = Vector3.Distance(
            new Vector3(transform.position.x, 0f, transform.position.z),
            new Vector3(nextWp.x, 0f, nextWp.z)
        );

        if (logAsExperimentTrial)
        {
            if (!experimentTrialActive)
                BeginExperimentTrial("c2c3_obstacle_evaluation");

            MarkExperimentTrialStarted();
        }

        managedEvaluationRunActive = true;
        managedEvaluationDecisionCounter = 0;

        // 관리형 주행 시작 즉시 첫 추론을 요청한다.
        // DecisionRequester가 있더라도 첫 결정이 늦어지는 현상을 방지한다.
        RequestDecision();

        Debug.Log(
            "[GO1Agent] C2/C3 관리형 주행 시작 | " +
            "lockedPath=" + pathPlanner.IsPathLocked +
            ", decisionRequester=" + (managedDecisionRequester != null ? managedDecisionRequester.enabled.ToString() : "missing") +
            ", decisionPeriod=" + managedEvaluationDecisionPeriod +
            ", start=" + startPosition +
            ", goal=" + goalPosition,
            this
        );
    }

    /// <summary>
    /// 관리형 평가 주행만 정지합니다. EndEpisode나 TrainingManager 목표 변경은 호출하지 않습니다.
    /// </summary>
    public void StopManagedEvaluationRun(bool clearLockedPath)
    {
        managedEvaluationRunActive = false;
        managedEvaluationDecisionCounter = 0;
        canMove = false;
        isArrived = true;
        blockedFrameCount = 0;
        stuckCount = 0;
        previousTurn = 0f;
        previousMove = 0f;

        if (clearLockedPath && pathPlanner != null)
            pathPlanner.ClearLockedPath();

        if (utm != null)
        {
            utm.driveByState = false;
            utm.enableTeleop = true;
        }
    }

    public void FinishManagedEvaluationTrial(bool success, string reason)
    {
        episodeFailed = !success;
        experimentLastFailureReason = success ? string.Empty : reason;

        if (experimentTrialActive)
            FinishExperimentTrial(success, reason);
    }

    private void SafeEndEpisode()
    {
        if (episodeEnding)
            return;

        string reason = string.IsNullOrEmpty(experimentLastFailureReason)
            ? (episodeFailed ? "episode_failed" : "episode_end")
            : experimentLastFailureReason;

        // C2/C3 관리형 평가에서는 EndEpisode를 실행하면 TrainingManager가 새 목표를 만들기 때문에
        // 평가 관리자에게 종료 요청을 넘기고 기존 episode 순환을 차단합니다.
        if (c2c3EvaluationManager != null &&
            c2c3EvaluationManager.IsRunning &&
            c2c3EvaluationManager.HandleAgentEpisodeEndRequest(this, !episodeFailed, reason))
        {
            episodeEnding = false;
            return;
        }

        if (experimentTrialActive)
            FinishExperimentTrial(!episodeFailed, reason);

        episodeEnding = true;

        // 훈련 에피소드 로거에 결과 전달 (학습 보상 곡선 CSV 기록)
        trainingEpisodeLogger?.OnEpisodeEnded(!episodeFailed);

        // ONNX 평가에서는 episode 종료를 1개 trial 완료로 계산한다.
        // 제한에 도달한 경우 EndEpisode()를 다시 호출하지 않아 31번째 trial 생성을 막는다.
        if (RegisterCompletedEvaluationTrial())
            return;

        EndEpisode();
    }

    private bool RegisterCompletedEvaluationTrial()
    {
        if (!evaluationMode || Academy.Instance.IsCommunicatorOn)
            return false;

        completedEvaluationTrialCount++;

        if (maxEvaluationTrials <= 0 || completedEvaluationTrialCount < maxEvaluationTrials)
            return false;

        evaluationLimitReached = true;
        canMove = false;
        isArrived = true;

        Debug.Log(
            "[GO1Agent] ONNX 평가 완료 | completed=" +
            completedEvaluationTrialCount + "/" + maxEvaluationTrials +
            ", CSV 저장 완료" +
            (stopPlayModeWhenEvaluationComplete ? ", Play Mode 종료 요청" : ", 평가 정지")
        );

        if (stopPlayModeWhenEvaluationComplete)
            RequestStopAfterEvaluationComplete();

        return true;
    }

    private void RequestStopAfterEvaluationComplete()
    {
        if (evaluationStopRequested)
            return;

        evaluationStopRequested = true;

#if UNITY_EDITOR
        // 현재 콜백과 CSV 쓰기가 모두 끝난 뒤 안전하게 Play Mode를 종료한다.
        UnityEditor.EditorApplication.delayCall += () =>
        {
            if (UnityEditor.EditorApplication.isPlaying)
                UnityEditor.EditorApplication.isPlaying = false;
        };
#else
        Application.Quit();
#endif
    }

    private bool IsPathBlockedByNavMesh(Vector3 from, Vector3 to)
    {
        EnsurePathPlanner();
        return pathPlanner.IsPathBlockedByNavMesh(from, to);
    }

    private bool IsPathPhysicallyBlocked(Vector3 from, Vector3 to)
    {
        EnsurePathPlanner();
        return pathPlanner.IsPathPhysicallyBlocked(
            from,
            to,
            obstacleLayerMask,
            pathCheckRadius,
            pathCheckHeight,
            true
        );
    }

    private List<Vector3> SimplifyPath(List<Vector3> path, float tolerance)
    {
        if (path == null)
            return new List<Vector3>();

        if (path.Count <= 2)
            return new List<Vector3>(path);

        List<Vector3> result = new List<Vector3>();
        result.Add(path[0]);

        SimplifySection(path, 0, path.Count - 1, tolerance, result);

        result.Add(path[path.Count - 1]);

        return result;
    }

    private void SimplifySection(List<Vector3> path, int start, int end, float tolerance, List<Vector3> result)
    {
        if (end <= start + 1)
            return;

        float maxDist = 0f;
        int maxIdx = start;

        Vector3 startPt = path[start];
        Vector3 endPt = path[end];

        for (int i = start + 1; i < end; i++)
        {
            float dist = PointToLineDistance(path[i], startPt, endPt);

            if (dist > maxDist)
            {
                maxDist = dist;
                maxIdx = i;
            }
        }

        if (maxDist > tolerance)
        {
            SimplifySection(path, start, maxIdx, tolerance, result);
            result.Add(path[maxIdx]);
            SimplifySection(path, maxIdx, end, tolerance, result);
        }
    }

    private float PointToLineDistance(Vector3 point, Vector3 lineStart, Vector3 lineEnd)
    {
        Vector3 line = endMinusStart(lineStart, lineEnd);

        Vector3 pointFlat = point;
        pointFlat.y = 0f;

        Vector3 lineStartFlat = lineStart;
        lineStartFlat.y = 0f;

        if (line.sqrMagnitude < 0.0001f)
            return Vector3.Distance(pointFlat, lineStartFlat);

        float t = Mathf.Clamp01(Vector3.Dot(pointFlat - lineStartFlat, line) / line.sqrMagnitude);
        Vector3 projection = lineStartFlat + line * t;

        return Vector3.Distance(pointFlat, projection);
    }

    private Vector3 endMinusStart(Vector3 start, Vector3 end)
    {
        Vector3 line = end - start;
        line.y = 0f;
        return line;
    }

    private List<Vector3> ReducePathKeepCorners(
        List<Vector3> path,
        float minSpacing,
        float cornerAngleDegValue,
        int maxPoints)
    {
        List<Vector3> result = new List<Vector3>();

        if (path == null || path.Count == 0)
            return result;

        if (path.Count <= 2)
            return new List<Vector3>(path);

        result.Add(path[0]);
        Vector3 lastKept = path[0];

        for (int i = 1; i < path.Count - 1; i++)
        {
            Vector3 prev = path[i - 1];
            Vector3 curr = path[i];
            Vector3 next = path[i + 1];

            Vector3 a = curr - prev;
            Vector3 b = next - curr;

            a.y = 0f;
            b.y = 0f;

            float moved = Vector3.Distance(
                new Vector3(curr.x, 0f, curr.z),
                new Vector3(lastKept.x, 0f, lastKept.z)
            );

            bool farEnough = moved >= minSpacing;

            bool isCorner = false;
            if (a.sqrMagnitude > 0.0001f && b.sqrMagnitude > 0.0001f)
            {
                float angle = Vector3.Angle(a.normalized, b.normalized);
                isCorner = angle >= cornerAngleDegValue;
            }

            if (farEnough || isCorner)
            {
                result.Add(curr);
                lastKept = curr;
            }
        }

        result.Add(path[path.Count - 1]);

        if (maxPoints <= 2 || result.Count <= maxPoints)
            return result;

        List<Vector3> limited = new List<Vector3>();
        limited.Add(result[0]);

        float step = (float)(result.Count - 2) / Mathf.Max(1, maxPoints - 2);

        for (int i = 1; i < maxPoints - 1; i++)
        {
            int idx = Mathf.RoundToInt(i * step);
            idx = Mathf.Clamp(idx, 1, result.Count - 2);
            limited.Add(result[idx]);
        }

        limited.Add(result[result.Count - 1]);

        return limited;
    }

    // =========================================================
    // Actual GO1 Point Trace
    // C++ state를 받아 driveByState=true로 움직이는 현재 transform을 샘플링한다.
    // 각 샘플 지점에 초록색 Sphere를 생성하므로 실제 GO1이 점-by-점으로 간 경로를 볼 수 있다.
    // =========================================================
    private void StartActualGo1PointTrace()
    {
        if (!showActualGo1PointTrace)
            return;

        actualTraceRecording = true;
        lastActualTraceRecordTime = Time.time;

        if (clearActualTraceOnNewRun)
            ClearActualGo1PointTrace();

        EnsureActualTraceRoot();

        actualTracePoints.Clear();

        Vector3 start = transform.position;
        AddActualTracePoint(start, true);

        Debug.Log($"[GO1Agent] 실제 GO1 점 경로 표시 시작: start={start}");
    }

    private void StopActualGo1PointTrace(bool keepObjects)
    {
        if (!actualTraceRecording)
            return;

        actualTraceRecording = false;

        if (showActualGo1PointTrace)
        {
            Vector3 end = transform.position;

            if (actualTracePoints.Count == 0 ||
                Vector3.Distance(end, actualTracePoints[actualTracePoints.Count - 1]) > 0.01f)
            {
                AddActualTracePoint(end, true);
            }
        }

        Debug.Log($"[GO1Agent] 실제 GO1 점 경로 표시 종료: points={actualTracePoints.Count}");

        if (!keepObjects)
            ClearActualGo1PointTrace();
    }

    private void UpdateActualGo1PointTrace()
    {
        if (!actualTraceRecording || !showActualGo1PointTrace)
            return;

        if (Time.time - lastActualTraceRecordTime < actualTraceRecordInterval)
            return;

        lastActualTraceRecordTime = Time.time;

        Vector3 current = transform.position;

        if (actualTracePoints.Count > 0 &&
            Vector3.Distance(current, lastActualTraceRecordedPos) < actualTraceMinMoveThreshold)
        {
            return;
        }

        AddActualTracePoint(current, false);
    }

    private void AddActualTracePoint(Vector3 worldPos, bool force)
    {
        if (!force && actualTracePoints.Count > 0)
        {
            if (Vector3.Distance(worldPos, actualTracePoints[actualTracePoints.Count - 1]) < actualTraceMinMoveThreshold)
                return;
        }

        EnsureActualTraceRoot();

        actualTracePoints.Add(worldPos);
        lastActualTraceRecordedPos = worldPos;

        GameObject pointObj = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        int idx = actualTracePoints.Count - 1;
        pointObj.name = nameActualTracePoints ? $"Actual_GO1_Point_{idx}" : "Actual_GO1_Point";
        pointObj.transform.SetParent(actualTraceRoot.transform, true);
        pointObj.transform.position = worldPos + Vector3.up * actualTraceYOffset;
        pointObj.transform.localScale = Vector3.one * actualGo1PointRadius * 2f;

        Collider col = pointObj.GetComponent<Collider>();
        if (col != null)
            Destroy(col);

        Renderer renderer = pointObj.GetComponent<Renderer>();
        if (renderer != null)
            renderer.material = CreateActualTraceMaterial(actualGo1PointColor);

        actualTracePointObjects.Add(pointObj);

        RefreshActualTraceLine();
    }

    private void EnsureActualTraceRoot()
    {
        if (actualTraceRoot != null)
            return;

        actualTraceRoot = new GameObject("Actual_GO1_Point_By_Point_Path_Green");
    }

    private void RefreshActualTraceLine()
    {
        if (!connectActualGo1Points)
            return;

        EnsureActualTraceRoot();

        if (actualTraceLine == null)
        {
            GameObject lineObj = new GameObject("Actual_GO1_Point_Path_Line_Green");
            lineObj.transform.SetParent(actualTraceRoot.transform, true);

            actualTraceLine = lineObj.AddComponent<LineRenderer>();
            actualTraceLine.useWorldSpace = true;
            actualTraceLine.numCapVertices = 4;
            actualTraceLine.numCornerVertices = 4;
            actualTraceLine.material = CreateActualTraceMaterial(actualGo1LineColor);
        }

        actualTraceLine.startWidth = actualGo1LineWidth;
        actualTraceLine.endWidth = actualGo1LineWidth;
        actualTraceLine.startColor = actualGo1LineColor;
        actualTraceLine.endColor = actualGo1LineColor;

        actualTraceLine.positionCount = actualTracePoints.Count;

        for (int i = 0; i < actualTracePoints.Count; i++)
        {
            actualTraceLine.SetPosition(i, actualTracePoints[i] + Vector3.up * actualTraceYOffset);
        }
    }

    private Material CreateActualTraceMaterial(Color color)
    {
        Shader shader = Shader.Find("Sprites/Default");

        if (shader == null)
            shader = Shader.Find("Standard");

        Material mat = new Material(shader);
        mat.color = color;
        return mat;
    }

    [ContextMenu("Clear Actual GO1 Point Trace")]
    public void ClearActualGo1PointTrace()
    {
        actualTracePoints.Clear();
        actualTracePointObjects.Clear();
        actualTraceLine = null;

        if (actualTraceRoot != null)
        {
            Destroy(actualTraceRoot);
            actualTraceRoot = null;
        }
    }

    private void InitializeExperimentLogging()
    {
        if (!enableExperimentLogging)
            return;

        // 결과 CSV를 프로젝트 폴더 안(Assets의 상위 = 프로젝트 루트)에 생성한다.
        // Editor에서 Application.dataPath는 <ProjectRoot>/Assets 이므로 그 부모가 프로젝트 루트다.
        // Assets 바깥이라 Unity가 .meta를 만들거나 재임포트하지 않는다.
        // 주의: 빌드(Standalone)에서는 dataPath가 <Game>_Data를 가리키므로 위치가 달라진다. 연구용 Editor 실행 기준.
        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        string baseDirectory = Path.Combine(projectRoot, experimentFolderName);
        experimentDirectory = createSessionSubfolder
            ? Path.Combine(baseDirectory, experimentSessionId)
            : baseDirectory;

        Directory.CreateDirectory(experimentDirectory);

        experimentSummaryCsvPath = Path.Combine(experimentDirectory, "mission_summary.csv");
        experimentTrackingCsvPath = Path.Combine(experimentDirectory, "path_tracking.csv");
        experimentEventCsvPath = Path.Combine(experimentDirectory, "events.csv");
        experimentConfigCsvPath = Path.Combine(experimentDirectory, "experiment_config.csv");
        inspectorConfigCsvPath = Path.Combine(experimentDirectory, "inspector_config.csv");
        scenarioConfigCsvPath = Path.Combine(experimentDirectory, "scenario_config.csv");
        obstacleEventCsvPath = Path.Combine(experimentDirectory, "obstacle_events.csv");

        EnsureExperimentCsvHeader(
            experimentSummaryCsvPath,
            "session_id,agent_name,trial_id,condition_id,scenario_id,map_id,policy_id,method,mode,difficulty_level,random_seed,start_time_iso,end_time_iso,success,end_reason,duration_sec,planning_time_sec,travel_distance_m,shortest_path_m,path_efficiency,collision_count,obstacle_collision_count,stuck_count,replan_count,replan_time_sec,raw_waypoints,sent_waypoints,sent_path_length_m,final_target_error_m,reached_by_error,cumulative_reward,steps,start_x,start_z,start_yaw,target_x,target_z,end_x,end_z,end_yaw"
        );
        EnsureExperimentCsvHeader(
            experimentTrackingCsvPath,
            "session_id,agent_name,trial_id,condition_id,scenario_id,time_sec,state,virtual_x,virtual_z,virtual_yaw,real_x,real_z,real_yaw,path_cross_track_error_m,target_distance_m"
        );
        EnsureExperimentCsvHeader(
            experimentEventCsvPath,
            "session_id,agent_name,trial_id,condition_id,scenario_id,time_sec,event_type,detail,x,z"
        );
        EnsureExperimentCsvHeader(
            experimentConfigCsvPath,
            "session_id,agent_name,condition_id,scenario_id,map_id,policy_id,method,random_seed,unity_version,mlagents_version,yaml_name,evaluation_mode,communicator_on,created_at_iso"
        );
        EnsureExperimentCsvHeader(
            inspectorConfigCsvPath,
            "session_id,agent_name,condition_id,move_speed,rotate_speed_deg,virtual_plan_speed_multiplier,virtual_plan_rotate_multiplier,wall_clearance_threshold,wall_clearance_penalty_weight,wall_clearance_ray_distance,corridor_centering_weight,waypoint_switch_distance,blocked_move_threshold,blocked_frame_limit,path_check_radius,path_check_height,path_block_check_radius,obstacle_bounds_margin,runtime_replanning_enabled,obstacle_triggered_replan_enabled,max_obstacle_replan_count,replan_cooldown_sec,post_replan_lock_sec,replan_stop_wait_sec,navmesh_carving_wait_sec,simplify_tolerance,min_send_point_spacing,max_send_point_count,corner_keep_angle_deg,sample_interval_sec"
        );
        EnsureExperimentCsvHeader(
            scenarioConfigCsvPath,
            "session_id,agent_name,trial_id,mode,condition_id,scenario_id,map_id,policy_id,difficulty_level,evaluation_fixed_difficulty,agent_count,goal_min_distance,goal_max_distance,min_open_radius,start_x,start_z,start_yaw,target_x,target_z,target_straight_distance_m,random_seed,created_at_iso"
        );
        EnsureExperimentCsvHeader(
            obstacleEventCsvPath,
            "session_id,agent_name,trial_id,condition_id,scenario_id,time_sec,obstacle_name,center_x,center_z,size_x,size_z,distance_to_path_m,block_threshold_m,closest_segment,path_blocked,replan_requested,replan_skip_reason,replan_count"
        );

        if (debugExperimentLogging)
            Debug.Log("[GO1Agent] KCI 실험 CSV 저장 폴더: " + experimentDirectory);
    }

    private void EnsureExperimentCsvHeader(string path, string header)
    {
        if (!File.Exists(path) || new FileInfo(path).Length == 0)
            File.WriteAllText(path, header + "\n", new UTF8Encoding(true));
    }

    private void EnsureExperimentStaticConfigurationWritten()
    {
        if (!enableExperimentLogging || experimentStaticConfigurationWritten)
            return;

        if (string.IsNullOrEmpty(experimentDirectory))
            InitializeExperimentLogging();

        if (string.IsNullOrEmpty(experimentDirectory))
            return;

        WriteExperimentConfiguration();
        WriteInspectorConfiguration();
        experimentStaticConfigurationWritten = true;
    }

    private int GetExperimentRandomSeed()
    {
        return trainingManager != null
            ? trainingManager.GetRandomSeed()
            : experimentFallbackRandomSeed;
    }

    private int GetExperimentDifficultyLevel()
    {
        return trainingManager != null
            ? trainingManager.GetCurrentDifficultyLevel()
            : -1;
    }

    private void WriteExperimentConfiguration()
    {
        if (!enableExperimentLogging || string.IsNullOrEmpty(experimentConfigCsvPath))
            return;

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(gameObject.name),
            Csv(experimentConditionId),
            Csv(experimentScenarioId),
            Csv(experimentMapId),
            Csv(experimentPolicyId),
            Csv(experimentMethodName),
            GetExperimentRandomSeed().ToString(CultureInfo.InvariantCulture),
            Csv(Application.unityVersion),
            Csv(experimentMlAgentsVersion),
            Csv(experimentYamlName),
            evaluationMode ? "1" : "0",
            Academy.Instance.IsCommunicatorOn ? "1" : "0",
            Csv(System.DateTime.Now.ToString("o", CultureInfo.InvariantCulture))
        });

        AppendExperimentLine(experimentConfigCsvPath, row);
    }

    private void WriteInspectorConfiguration()
    {
        if (!enableExperimentLogging || string.IsNullOrEmpty(inspectorConfigCsvPath))
            return;

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(gameObject.name),
            Csv(experimentConditionId),
            F(moveSpeed),
            F(rotateSpeedDeg),
            F(virtualPlanSpeedMultiplier),
            F(virtualPlanRotateMultiplier),
            F(wallClearanceThreshold),
            F(wallClearancePenaltyWeight),
            F(wallClearanceRayDistance),
            F(corridorCenteringWeight),
            F(waypointSwitchDistance),
            F(blockedMoveThreshold),
            blockedFrameLimit.ToString(CultureInfo.InvariantCulture),
            F(pathCheckRadius),
            F(pathCheckHeight),
            F(pathBlockCheckRadius),
            F(obstacleBoundsMargin),
            enableRuntimeReplanning ? "1" : "0",
            enableObstacleTriggeredReplan ? "1" : "0",
            maxObstacleReplanCountPerMission.ToString(CultureInfo.InvariantCulture),
            F(replanCooldown),
            F(postReplanLockSeconds),
            F(replanStopWaitTime),
            F(navMeshCarvingWaitTime),
            F(simplifyTolerance),
            F(minSendPointSpacing),
            maxSendPointCount.ToString(CultureInfo.InvariantCulture),
            F(cornerKeepAngleDeg),
            F(experimentSampleInterval)
        });

        AppendExperimentLine(inspectorConfigCsvPath, row);
    }

    private void BeginExperimentTrial(string mode)
    {
        if (!enableExperimentLogging || experimentTrialActive)
            return;

        if (string.IsNullOrEmpty(experimentDirectory))
            InitializeExperimentLogging();

        experimentTrialId++;
        experimentTrialMode = string.IsNullOrEmpty(mode) ? "unknown" : mode;
        experimentTrialStartWritten = false;
        experimentTrialActive = true;
        experimentTrialStartTime = Time.time;
        experimentTrialStartDateTime = System.DateTime.Now;
        experimentPlanningStartTime = Time.time;
        experimentFirstPathSendTime = -1f;
        experimentLastSampleTime = -999f;
        experimentTravelDistance = 0f;
        experimentCollisionCount = 0;
        experimentObstacleCollisionCount = 0;
        experimentLastCollisionTimeByCollider.Clear();
        experimentStuckEventCount = 0;
        experimentReplanCount = 0;
        experimentAccumulatedReplanTime = 0f;
        experimentCurrentReplanStartTime = -1f;
        experimentRawWaypointCount = 0;
        experimentSentWaypointCount = 0;
        experimentSentPathLength = 0f;
        experimentLastFailureReason = "";

        RefreshExperimentTrialPose();
    }

    private void MarkExperimentTrialStarted()
    {
        if (!enableExperimentLogging || !experimentTrialActive || experimentTrialStartWritten)
            return;

        RefreshExperimentTrialPose();
        EnsureExperimentStaticConfigurationWritten();
        WriteScenarioConfiguration();
        WriteExperimentEvent("trial_begin", experimentTrialMode, transform.position);
        experimentTrialStartWritten = true;
    }

    private void WriteScenarioConfiguration()
    {
        if (!enableExperimentLogging || !experimentTrialActive ||
            string.IsNullOrEmpty(scenarioConfigCsvPath))
            return;

        int difficultyLevel = GetExperimentDifficultyLevel();
        bool evaluationFixed = trainingManager != null && trainingManager.IsEvaluationDifficultyFixed();
        int managerAgentCount = trainingManager != null ? trainingManager.agentCount : 1;
        float managerGoalMin = trainingManager != null ? trainingManager.goalMinDistance : -1f;
        float managerGoalMax = trainingManager != null ? trainingManager.goalMaxDistance : -1f;
        float managerOpenRadius = trainingManager != null ? trainingManager.minOpenRadius : -1f;
        float targetDistance = Vector3.Distance(
            new Vector3(experimentStartPosition.x, 0f, experimentStartPosition.z),
            new Vector3(experimentTargetPosition.x, 0f, experimentTargetPosition.z));

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(gameObject.name),
            experimentTrialId.ToString(CultureInfo.InvariantCulture),
            Csv(experimentTrialMode),
            Csv(experimentConditionId),
            Csv(experimentScenarioId),
            Csv(experimentMapId),
            Csv(experimentPolicyId),
            difficultyLevel.ToString(CultureInfo.InvariantCulture),
            evaluationFixed ? "1" : "0",
            managerAgentCount.ToString(CultureInfo.InvariantCulture),
            F(managerGoalMin),
            F(managerGoalMax),
            F(managerOpenRadius),
            F(experimentStartPosition.x),
            F(experimentStartPosition.z),
            F(experimentStartRotation.eulerAngles.y),
            F(experimentTargetPosition.x),
            F(experimentTargetPosition.z),
            F(targetDistance),
            GetExperimentRandomSeed().ToString(CultureInfo.InvariantCulture),
            Csv(System.DateTime.Now.ToString("o", CultureInfo.InvariantCulture))
        });

        AppendExperimentLine(scenarioConfigCsvPath, row);
    }

    private void WriteObstacleEvent(
        GameObject obstacle,
        float distanceToPath,
        float blockThreshold,
        int closestSegment,
        bool pathBlocked,
        bool replanRequested,
        string replanSkipReason)
    {
        if (!enableExperimentLogging || !experimentTrialActive || obstacle == null ||
            string.IsNullOrEmpty(obstacleEventCsvPath))
            return;

        Bounds bounds = GetObstacleBounds(obstacle);
        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(gameObject.name),
            experimentTrialId.ToString(CultureInfo.InvariantCulture),
            Csv(experimentConditionId),
            Csv(experimentScenarioId),
            F(Time.time - experimentTrialStartTime),
            Csv(obstacle.name),
            F(bounds.center.x),
            F(bounds.center.z),
            F(bounds.size.x),
            F(bounds.size.z),
            F(distanceToPath),
            F(blockThreshold),
            closestSegment.ToString(CultureInfo.InvariantCulture),
            pathBlocked ? "1" : "0",
            replanRequested ? "1" : "0",
            Csv(replanSkipReason),
            (experimentReplanCount + (replanRequested ? 1 : 0)).ToString(
                CultureInfo.InvariantCulture)
        });

        AppendExperimentLine(obstacleEventCsvPath, row);
    }

    private void RefreshExperimentTrialPose()
    {
        if (!experimentTrialActive)
            return;

        experimentStartPosition = transform.position;
        experimentStartRotation = transform.rotation;
        experimentPreviousPosition = transform.position;
        experimentTargetPosition = target != null ? target.position : transform.position;
    }

    private void AccumulateExperimentDistance(Vector3 from, Vector3 to)
    {
        if (!enableExperimentLogging || !experimentTrialActive)
            return;

        Vector3 a = new Vector3(from.x, 0f, from.z);
        Vector3 b = new Vector3(to.x, 0f, to.z);
        float d = Vector3.Distance(a, b);
        // 0.4 m/s, 50 Hz 환경에서는 한 step 이동량이 약 0.008 m이므로
        // 기존 0.01 m 기준은 정상 이동까지 모두 버린다.
        if (d > 0.0001f && d < 10f)
            experimentTravelDistance += d;

        experimentPreviousPosition = to;
    }

    private void RecordExperimentPathPrepared(List<Vector3> rawPath, List<Vector3> sendPath)
    {
        if (!experimentTrialActive)
            return;

        experimentRawWaypointCount = rawPath != null ? rawPath.Count : 0;
        experimentSentWaypointCount = sendPath != null ? sendPath.Count : 0;
        experimentSentPathLength = CalculateExperimentPathLength(sendPath);

        WriteExperimentEvent(
            "path_prepared",
            "raw=" + experimentRawWaypointCount + ";send=" + experimentSentWaypointCount +
            ";length=" + F(experimentSentPathLength),
            transform.position
        );
    }

    private void MarkExperimentPathSent(string detail)
    {
        if (!experimentTrialActive)
            return;

        MarkExperimentTrialStarted();

        if (experimentFirstPathSendTime < 0f)
            experimentFirstPathSendTime = Time.time;

        WriteExperimentEvent("path_sent", detail, transform.position);
    }

    private void CompleteExperimentReplan(string detail)
    {
        if (!experimentTrialActive || experimentCurrentReplanStartTime < 0f)
            return;

        float elapsed = Mathf.Max(0f, Time.time - experimentCurrentReplanStartTime);
        experimentAccumulatedReplanTime += elapsed;
        experimentCurrentReplanStartTime = -1f;
        WriteExperimentEvent("replan_ready", detail + ";duration=" + F(elapsed), transform.position);
    }

    private void UpdateExperimentTracking()
    {
        if (!enableExperimentLogging || !experimentTrialActive)
            return;

        MarkExperimentTrialStarted();
        AccumulateExperimentDistance(experimentPreviousPosition, transform.position);

        if (Time.time - experimentLastSampleTime < Mathf.Max(0.01f, experimentSampleInterval))
            return;

        experimentLastSampleTime = Time.time;

        Vector3 virtualPos = transform.position;
        float virtualYaw = transform.eulerAngles.y;
        Vector3 realPos = virtualPos;
        float realYaw = virtualYaw;

        if (utm != null && utm.HasSdkState())
        {
            realPos = utm.GetCurrentSdkUnityMappedPosition();
            realYaw = utm.GetCurrentSdkUnityMappedRotation().eulerAngles.y;
        }

        string state = GetExperimentStateName();
        float crossTrack = GetExperimentDistanceToSentPathXZ(realPos);
        float targetDistance = target != null
            ? Vector3.Distance(new Vector3(realPos.x, 0f, realPos.z), new Vector3(target.position.x, 0f, target.position.z))
            : 0f;

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(gameObject.name),
            experimentTrialId.ToString(CultureInfo.InvariantCulture),
            Csv(experimentConditionId),
            Csv(experimentScenarioId),
            F(Time.time - experimentTrialStartTime),
            Csv(state),
            F(virtualPos.x), F(virtualPos.z), F(virtualYaw),
            F(realPos.x), F(realPos.z), F(realYaw),
            F(crossTrack), F(targetDistance)
        });

        AppendExperimentLine(experimentTrackingCsvPath, row);
    }

    private string GetExperimentStateName()
    {
        if (IsReplanningActive) return "replanning";
        if (waitingRealGo1Start) return "waiting_real_start";
        if (realGo1PathActive) return "real_path_following";
        if (canMove && !isArrived) return Academy.Instance.IsCommunicatorOn ? "training" : "virtual_planning";
        if (isArrived) return "arrived";
        return "idle";
    }

    private float GetExperimentDistanceToSentPathXZ(Vector3 position)
    {
        if (currentSentPath == null || currentSentPath.Count < 2)
            return -1f;

        float minDist = float.MaxValue;
        for (int i = 0; i < currentSentPath.Count - 1; i++)
            minDist = Mathf.Min(minDist, DistancePointToSegmentXZ(position, currentSentPath[i], currentSentPath[i + 1]));

        return minDist == float.MaxValue ? -1f : minDist;
    }

    private float CalculateExperimentPathLength(List<Vector3> path)
    {
        if (path == null || path.Count < 2)
            return 0f;

        float length = 0f;
        for (int i = 1; i < path.Count; i++)
        {
            Vector3 a = new Vector3(path[i - 1].x, 0f, path[i - 1].z);
            Vector3 b = new Vector3(path[i].x, 0f, path[i].z);
            length += Vector3.Distance(a, b);
        }
        return length;
    }

    private void FinishExperimentTrial(bool success, string reason)
    {
        if (!enableExperimentLogging || !experimentTrialActive)
            return;

        MarkExperimentTrialStarted();
        CompleteExperimentReplan("trial_end");

        Vector3 endPos = transform.position;
        float endYaw = transform.eulerAngles.y;
        float duration = Mathf.Max(0f, Time.time - experimentTrialStartTime);
        float planningTime = experimentFirstPathSendTime >= 0f
            ? Mathf.Max(0f, experimentFirstPathSendTime - experimentPlanningStartTime)
            : 0f;
        float shortest = GetNavMeshPathDistance(experimentStartPosition, experimentTargetPosition);
        float finalError = Vector3.Distance(
            new Vector3(endPos.x, 0f, endPos.z),
            new Vector3(experimentTargetPosition.x, 0f, experimentTargetPosition.z));

        // 에이전트는 목표 중심에 정확히 닿기 전에 도착 허용 반경 안에서 성공한다.
        // 따라서 목표 중심까지의 전체 최단거리에서 실제 종료 시 남은 거리를 제외한
        // 유효 최단거리와 실제 이동거리를 비교한다. 수치 오차로 1을 넘지 않도록 제한한다.
        float effectiveShortest = Mathf.Max(0f, shortest - finalError);
        float efficiency = experimentTravelDistance > 0.0001f
            ? Mathf.Clamp01(effectiveShortest / experimentTravelDistance)
            : 0f;

        bool reachedByError = finalError < GoalArrivalDistance;

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(gameObject.name),
            experimentTrialId.ToString(CultureInfo.InvariantCulture),
            Csv(experimentConditionId),
            Csv(experimentScenarioId),
            Csv(experimentMapId),
            Csv(experimentPolicyId),
            Csv(experimentMethodName),
            Csv(experimentTrialMode),
            GetExperimentDifficultyLevel().ToString(CultureInfo.InvariantCulture),
            GetExperimentRandomSeed().ToString(CultureInfo.InvariantCulture),
            Csv(experimentTrialStartDateTime.ToString("o", CultureInfo.InvariantCulture)),
            Csv(System.DateTime.Now.ToString("o", CultureInfo.InvariantCulture)),
            success ? "1" : "0",
            Csv(reason),
            F(duration), F(planningTime), F(experimentTravelDistance), F(shortest), F(efficiency),
            experimentCollisionCount.ToString(CultureInfo.InvariantCulture),
            experimentObstacleCollisionCount.ToString(CultureInfo.InvariantCulture),
            experimentStuckEventCount.ToString(CultureInfo.InvariantCulture),
            experimentReplanCount.ToString(CultureInfo.InvariantCulture), F(experimentAccumulatedReplanTime),
            experimentRawWaypointCount.ToString(CultureInfo.InvariantCulture),
            experimentSentWaypointCount.ToString(CultureInfo.InvariantCulture), F(experimentSentPathLength),
            F(finalError), reachedByError ? "1" : "0", F(GetCumulativeReward()),
            StepCount.ToString(CultureInfo.InvariantCulture),
            F(experimentStartPosition.x), F(experimentStartPosition.z), F(experimentStartRotation.eulerAngles.y),
            F(experimentTargetPosition.x), F(experimentTargetPosition.z),
            F(endPos.x), F(endPos.z), F(endYaw)
        });

        AppendExperimentLine(experimentSummaryCsvPath, row);
        WriteExperimentEvent("trial_end", (success ? "success;" : "failure;") + reason, endPos);

        if (debugExperimentLogging)
        {
            Debug.Log(
                "[GO1Agent] 실험 저장 완료 | session=" + experimentSessionId +
                ", agent=" + gameObject.name +
                ", trial=" + experimentTrialId +
                ", success=" + success + ", reason=" + reason +
                ", distance=" + experimentTravelDistance.ToString("F2") + "m"
            );
        }

        experimentTrialActive = false;
        experimentTrialStartWritten = false;
    }

    private void WriteExperimentEvent(string eventType, string detail, Vector3 position)
    {
        if (!enableExperimentLogging || !experimentTrialActive || string.IsNullOrEmpty(experimentEventCsvPath))
            return;

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(gameObject.name),
            experimentTrialId.ToString(CultureInfo.InvariantCulture),
            Csv(experimentConditionId),
            Csv(experimentScenarioId),
            F(Time.time - experimentTrialStartTime),
            Csv(eventType), Csv(detail),
            F(position.x), F(position.z)
        });
        AppendExperimentLine(experimentEventCsvPath, row);
    }

    private void AppendExperimentLine(string path, string line)
    {
        if (string.IsNullOrEmpty(path))
            return;

        try
        {
            File.AppendAllText(path, line + "\n", new UTF8Encoding(false));
        }
        catch (System.Exception e)
        {
            Debug.LogError("[GO1Agent] 실험 CSV 저장 실패: " + e.Message);
        }
    }

    private string Csv(string value)
    {
        if (value == null) return "\"\"";
        return "\"" + value.Replace("\"", "\"\"") + "\"";
    }

    private string F(float value)
    {
        return value.ToString("F6", CultureInfo.InvariantCulture);
    }

    // ---------------------------------------------------------------------
    // GO1ReplanController bridge API
    // 장애물 기반 재탐색의 순서 제어는 컨트롤러가 담당하고,
    // GO1Agent의 기존 private 상태는 아래 좁은 인터페이스를 통해서만 변경합니다.
    // ---------------------------------------------------------------------
    internal UnityTeleopAndMirror ReplanTeleop => utm;
    internal IReadOnlyList<Vector3> ReplanCurrentSentPath => currentSentPath;

    internal void ReplanPrepareForRuntimeStop()
    {
        ClearRealGo1PathCommandState("GO1ReplanController");
        canMove = false;
        isArrived = false;
        blockedFrameCount = 0;
        currentSentPath.Clear();
        StopActualGo1PointTrace(false);
        EnableWASD();
    }

    internal IEnumerator ReplanExecuteCancelAndStopBurst()
    {
        yield return SendCancelAndStopBurst();
    }

    internal void ReplanSyncVirtualPoseToSdk(string reason, bool preferCancelAckPose, bool printLog)
    {
        SyncVirtualPoseToCurrentSdkState(reason, preferCancelAckPose, printLog);
    }

    internal bool ReplanValidatePathToCurrentTarget(out string failureReason)
    {
        if (target == null)
        {
            failureReason = "target_missing";
            return false;
        }

        if (enableNavMeshPreCheck && IsPathBlockedByNavMesh(transform.position, target.position))
        {
            failureReason = "navmesh_path_incomplete";
            return false;
        }

        if (enablePhysicalPathCheck && IsPathPhysicallyBlocked(transform.position, target.position))
        {
            failureReason = "physical_path_blocked";
            return false;
        }

        failureReason = "";
        return true;
    }

    internal void ReplanStartVirtualPathGeneration()
    {
        StartMission();
    }

    internal void ReplanPrepareGeneratedPathRetry()
    {
        canMove = false;
        isArrived = false;
        ClearRealGo1PathCommandState("RuntimeReplanGenerateRetry");
        ReturnVirtualToMissionStartPose();
        recordedPath.Clear();
    }

    internal void ReplanAbortAndEnableManualControl()
    {
        canMove = false;
        isArrived = false;
        EnableWASD();
    }

    internal void ReplanWriteObstacleEvent(
        GameObject obstacle,
        float distanceToPath,
        float blockThreshold,
        int closestSegment,
        bool pathBlocked,
        bool replanRequested,
        string replanSkipReason)
    {
        WriteObstacleEvent(
            obstacle,
            distanceToPath,
            blockThreshold,
            closestSegment,
            pathBlocked,
            replanRequested,
            replanSkipReason
        );
    }

    internal void ReplanBeginExperiment(GameObject obstacle)
    {
        experimentReplanCount++;
        experimentCurrentReplanStartTime = Time.time;

        // 케이스 스터디 로거: 재탐색 시작
        caseStudyLogger?.LogReplanTriggered(
            obstacle != null ? obstacle.name : "policy_request"
        );

        WriteExperimentEvent(
            "replan_start",
            obstacle != null ? obstacle.name : "policy_request",
            transform.position
        );
    }

    internal void ReplanCompleteExperiment(string detail)
    {
        CompleteExperimentReplan(detail);
    }

    public void StartNewMission()
    {
        StartMission();
    }

    public void StopCurrentMissionFromPolicy()
    {
        if (IsMissionBusy())
        {
            StopMission();
        }
    }

    public bool RequestObstacleTriggeredReplanFromPolicy(Transform blockingObstacle = null)
    {
        EnsureReplanController();
        return replanController.RequestObstacleTriggeredReplanFromPolicy(blockingObstacle);
    }

    public void ResumeAutoDrivingFromPolicy()
    {
        if (!IsMoving() && target != null && !IsReplanningActive)
        {
            StartMission();
        }
    }

    public void SetNewGoalAndStart(Transform newGoal)
    {
        target = newGoal;
        StartMission();
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        ActionSegment<float> act = actionsOut.ContinuousActions;
        act[0] = 0f;
        act[1] = 0f;
    }

    public void SetGoal(Transform newGoal)
    {
        target = newGoal;

        if (target != null)
        {
            previousPathDist = GetNavMeshPathDistance(transform.position, target.position);

            CalculateCurrentPath(transform.position, target.position);

            previousCornerCount = CurrentPathCorners.Length;

            Vector3 nextWp = GetNextWaypoint();
            previousWaypointDist = Vector3.Distance(
                new Vector3(transform.position.x, 0f, transform.position.z),
                new Vector3(nextWp.x, 0f, nextWp.z)
            );
        }
    }

    // ─── 논문 실험 데이터 추출용 Public Getter (C2C3EvaluationManager에서 trial 완료 직전 호출) ───
    public int GetActiveTrialCollisionCount()         => experimentCollisionCount;
    public int GetActiveTrialObstacleCollisionCount() => experimentObstacleCollisionCount;
    public int GetActiveTrialStuckCount()             => experimentStuckEventCount;
    public int GetActiveTrialReplanCount()            => experimentReplanCount;
    public float GetActiveTrialTravelDistance()       => experimentTravelDistance;
    public float GetActiveTrialAccumulatedReplanTime() => experimentAccumulatedReplanTime;
}