using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// C1(NavMesh-only) 조건 평가 관리자입니다.
///
/// GO1Agent(강화학습 정책)의 이동/조향은 쓰지 않고,
/// 순수 UnityEngine.AI.NavMeshAgent + NavMesh의 자동 재경로(autoRepath) +
/// NavMeshObstacle carving만으로 동적 장애물 상황에 얼마나 잘 대응하는지 측정합니다.
///
/// 장애물 배치는 C2C3EvaluationManager와 완전히 동일한 DynamicObstacleScenarioManager
/// 인스턴스를 그대로 재사용합니다(별도의 C1 전용 배치 로직을 복제하지 않음).
/// 재배치(retry) 시 후보 위치가 경로를 완전히 막아 재시도가 발생하는 경우에도
/// C1/C2/C3가 항상 같은 코드 경로를 타므로 조건 간 장애물 위치가 갈릴 수 없습니다.
/// 같은 baseRandomSeed/trialsPerSet/scenarioSetSeeds를 맞추면 C1/C2/C3 3조건을
/// 같은 시나리오 분포에서 비교할 수 있습니다.
///
/// 한 trial의 처리 순서 (C2C3EvaluationManager의 useNavMeshPathDirectly 흐름과 동일한 순서)
/// 1) 시작점/목표점 생성 (TrainingManager)
/// 2) 장애물 없는 기준 NavMesh 경로 계산
/// 3) NavMeshAgent를 시작점으로 워프 (로봇이 출발점에 있는 상태를 만든다)
/// 4) 로봇이 아직 출발점에 있는 채로 장애물을 미리 배치 — DynamicObstacleScenarioManager의
///    minDistanceFromRobot 검증이 "출발점 기준"으로 통과해야 C2/C3와 같은 확률로 성공한다.
///    (주행 중 로봇이 이미 지나간 지점 근처에 배치를 시도하면 항상 too_close_to_robot으로 실패한다)
/// 5) 장애물 배치 후 우회 경로가 실제로 존재하는지 확인 — 없으면 다음 시나리오로 재시도
/// 6) SetDestination으로 실제 주행 타이밍 측정 시작
/// 7) 이후의 회피/재탐색은 전적으로 NavMeshAgent.autoRepath + NavMeshObstacle carving에 맡김
///    (이 관리자는 개입하지 않음 — "NavMesh만으로 얼마나 잘 파악하는지"를 그대로 관찰)
/// 8) 성공/충돌/정체/타임아웃을 기록하고 다음 trial로 진행
/// </summary>
[DefaultExecutionOrder(-300)]
[DisallowMultipleComponent]
public class C1EvaluationManager : MonoBehaviour
{
    public enum EvaluationPhase
    {
        Idle,
        PreparingTrial,
        Running,
        TrialCompleted,
        Finished,
        Stopped
    }

    [Header("Core References")]
    [Tooltip("C1 주행을 담당하는 순수 NavMeshAgent입니다. GO1Agent가 없어도 됩니다.")]
    public NavMeshAgent agent;

    public TrainingManager trainingManager;

    [Tooltip("C2/C3와 동일한 DynamicObstacleScenarioManager 인스턴스를 그대로 연결하세요. " +
             "장애물 재배치(retry) 로직을 조건마다 따로 구현하면 배치 위치가 갈릴 수 있어 " +
             "반드시 같은 컴포넌트를 공유해야 합니다.")]
    public DynamicObstacleScenarioManager obstacleScenarioManager;

    [Tooltip(
        "agent와 같은 GameObject에 GO1Agent(RL)가 함께 있는 경우(예: 기존 XRI lab 씬의 go1 리그를 그대로 재사용할 때) " +
        "설정하세요. GO1AutoNavigator가 P키 수동 주행에 쓰는 것과 동일한 " +
        "OnNavigatorStarted()/OnNavigatorArrived() 훅으로 CharacterController와 RL 이동을 평가 세션 동안 " +
        "완전히 비활성화합니다. 비워두면 자동으로 agent.GetComponent<GO1Agent>()를 찾고, 그래도 없으면 무시합니다."
    )]
    public GO1Agent coexistingAgent;
    private bool coexistingAgentControlTaken;

    [Header("Trials")]
    [Tooltip("세트당 trial 수입니다. 총 trial = trialsPerSet × scenarioSetSeeds.Length")]
    [Min(1)]
    public int trialsPerSet = 30;

    [Tooltip("각 세트에 사용할 랜덤 시드 배열입니다. C2/C3와 동일하게 맞추면 같은 시나리오 분포를 씁니다.")]
    public int[] scenarioSetSeeds = { 121, 222, 333, 444, 555, 666, 777, 888, 999, 1110 };

    public int totalTrials => trialsPerSet * Mathf.Max(1, scenarioSetSeeds != null ? scenarioSetSeeds.Length : 1);

    [Min(0)]
    public int currentTrialIndex = 0;
    private int currentSetIndex = 0;
    private int totalScenarioSkips = 0;

    [Header("Start/Goal Generation")]
    public bool useDeterministicStartYaw = true;
    public int startYawBaseSeed = 121;

    [Tooltip("시작/목표 위치 생성이 실패했을 때 재시도할 최대 횟수입니다.")]
    [Range(0, 10)]
    public int maxPositionRetries = 5;

    [Header("Obstacle Placement")]
    [Tooltip("C2C3EvaluationManager.useNavMeshPathDirectly와 반드시 같은 값으로 맞추세요. " +
             "true: 로봇이 출발점에 있을 때 미리 장애물을 배치(사전 배치) — \"재탐색 자체의 효과\"를 " +
             "측정할 때 씀. false: 로봇이 실제 주행 중 일정 진행률에 도달한 시점에 그 자리에서 " +
             "장애물을 생성(실시간 배치) — carving이 끝나기 전에 이미 그 경로에 진입해 있는 상황을 " +
             "만들어 \"국소 실행 전략(규칙 기반 vs RL)의 반응 속도 차이\"를 측정할 때 씀.")]
    public bool useNavMeshPathDirectly = false;

    [Tooltip("[사전 배치 모드] 로봇이 출발점에 있는 상태에서 장애물을 미리 배치합니다(주행 시작 전). " +
             "C2/C3의 PlaceObstacleThenRunRoutine과 동일한 순서를 따라야 " +
             "minDistanceFromRobot 검증이 같은 기준으로 통과합니다.")]
    [Min(0.5f)]
    public float obstacleFirstPlacementTimeout = 8f;

    [Tooltip("[사전 배치 모드] 현재 시나리오에서 유효한 장애물 위치를 찾지 못했을 때(너무 가까움/경로 완전 차단) " +
             "다음 시나리오로 넘어가며 재시도할 최대 횟수입니다.")]
    [Range(0, 20)]
    public int maxObstacleRetries = 8;

    [Header("Obstacle Trigger (실시간 배치 모드 전용)")]
    [Tooltip("주행 시작 후 장애물 생성 조건을 확인하기 전 최소 대기 시간입니다.")]
    [Min(0f)]
    public float minimumRunBeforeObstacle = 0.2f;

    [Tooltip("장애물 시나리오 진행률보다 이 값만큼 앞서 장애물을 생성합니다. 작을수록 로봇과 " +
             "가까운 곳에서 갑자기 나타나 반응 시간이 촉박해집니다.")]
    [Range(0f, 0.4f)]
    public float obstacleSpawnLeadProgress = 0.15f;

    [Header("Run Timing")]
    [Tooltip("도착 판정 거리입니다.")]
    [Min(0.01f)]
    public float arriveDistanceThreshold = 0.2f;

    [Tooltip("trial 전체 제한 시간입니다. 초과하면 실패 처리합니다.")]
    [Min(1f)]
    public float runTimeout = 60f;

    [Tooltip("이동 거리가 (기준 경로 길이 × 이 배수)를 넘으면 목표 도달 없이도 " +
             "\"과도한 배회\"로 간주해 조기 종료합니다. NavMeshAgent가 두 경로 사이에서 " +
             "계속 왔다갔다하며 진행하지 못하는 드문 경우, 60초를 다 채우지 않고 빨리 다음 trial로 넘어가기 위함입니다.")]
    [Min(2f)]
    public float excessiveWanderingMultiplier = 6f;

    [Tooltip("이 시간 이상 연속으로 멈춰 있으면 정체 이벤트로 기록합니다 (재탐색 대기 등 짧은 정지는 제외).")]
    [Min(0.1f)]
    public float stuckEventThreshold = 0.6f;

    [Tooltip("이 시간 이상 연속으로 멈춰 있으면 trial을 실패로 종료합니다.")]
    [Min(0.5f)]
    public float stoppedAgentFailTimeout = 6f;

    [Tooltip("정체로 간주할 최대 속도입니다.")]
    [Min(0f)]
    public float stuckVelocityThreshold = 0.03f;

    [Tooltip("trial 종료 후 다음 trial 시작까지 대기 시간입니다.")]
    [Min(0f)]
    public float nextTrialDelay = 0.5f;

    [Header("Rotation Control")]
    [Tooltip("go1 메시의 정면 축이 Unity 기본 forward(+Z)와 어긋나 있어(GO1AutoNavigator의 " +
             "visualYawOffset과 동일 원인), NavMeshAgent.updateRotation을 그대로 쓰면 로봇이 " +
             "이동 방향과 무관하게 옆으로 미끄러지듯 보인다. 켜두면 GO1AutoNavigator와 동일하게 " +
             "직접 회전을 계산해 이 문제를 보정한다.")]
    public bool controlRotationManually = true;
    public float rotationSpeed = 8f;
    public float visualYawOffset = 90f;

    [Header("Collision Detection (거리 기반)")]
    [Tooltip("로봇과 장애물 경계 사이 거리가 (장애물 반경 + 이 값) 이하이면 충돌로 간주합니다.")]
    [Min(0f)]
    public float collisionProximityMargin = 0.05f;

    [Tooltip("같은 장애물에 대해 충돌을 다시 셀 때까지의 최소 간격입니다.")]
    [Min(0.05f)]
    public float collisionCooldown = 0.5f;

    [Header("Result Logging")]
    public bool writeResultCsv = true;
    public string resultFolderName = "GO1_C1_fullmap";
    public bool createSessionSubfolder = true;

    [Tooltip("비워두면 시작 시각 기준으로 자동 생성합니다.")]
    public string experimentSessionId = "";

    public string experimentMapId = "fullmap";
    public string experimentPolicyId = "NavMeshOnly";
    public string experimentMethodName = "Unity_C1_NavMeshOnly_Evaluation";
    public string experimentConditionId = "C1_NAVMESH_ONLY";

    public bool debugLogs = true;

    [Header("Playback")]
    [Tooltip("Time.timeScale 배율입니다. 에디터에서 눈으로 빠르게 확인할 때만 1보다 크게 쓰세요. " +
             "실제 300 trial 데이터 수집(논문용) 시에는 반드시 1로 되돌려야 합니다 — " +
             "duration_sec/replan_time_sec 등 시간 지표가 1배속으로 측정된 C2/C3 데이터와 어긋납니다.")]
    [Min(0.1f)]
    public float simulationSpeedMultiplier = 5f;

    [Header("Completion")]
    [Tooltip("Play 시작 후 평가를 자동 시작합니다.")]
    public bool autoStart = false;

    [Tooltip("전체 trial 완료 시 Unity Editor Play Mode를 종료합니다.")]
    public bool stopPlayModeWhenFinished = false;

    public EvaluationPhase Phase => phase;
    public bool IsRunning => evaluationRunning && phase != EvaluationPhase.Finished && phase != EvaluationPhase.Stopped;

    // ─── per-trial 상태 ───────────────────────────────────────────────────
    private EvaluationPhase phase = EvaluationPhase.Idle;
    private bool evaluationRunning;

    private Vector3 savedStartPosition;
    private Quaternion savedStartRotation;
    private Vector3 savedGoalPosition;
    private readonly List<Vector3> baselinePath = new List<Vector3>();
    private float baselinePathLength;

    private bool obstacleSpawnRequested;
    private bool obstaclePlaced;
    private bool obstaclePlacementFailed;
    private string lastPlacementMessage = string.Empty;
    private float obstaclePlacedTime = -1f;
    private float prepStartTime;
    private float runStartTime;
    private float travelDistance;
    private Vector3 previousPosition;

    private bool pathSignatureInitialized;
    private int lastPathCornerCount = -1;
    private Vector3 lastPathCornerSum;
    private int pendingPathCornerCount = -1;
    private Vector3 pendingPathCornerSum;
    private int rerouteCountThisTrial;
    private float firstRerouteAfterObstacleTime = -1f;

    private int collisionCountThisTrial;
    private int obstacleCollisionCountThisTrial;
    private float lastCollisionTime = -999f;

    private int stuckCountThisTrial;
    private float timeSinceMovement;
    private bool currentlyStuck;

    private float initialPlanStartTime;
    private float initialPlanDoneTime = -1f;

    private Coroutine transitionRoutine;

    // ─── CSV ──────────────────────────────────────────────────────────────
    private string experimentDirectory;
    private string missionSummaryCsvPath;
    private string scenarioConfigCsvPath;
    private string obstacleEventCsvPath;
    private string experimentConfigCsvPath;
    private bool staticConfigWritten;

    private void Awake()
    {
        ResolveReferences();
    }

    private void Start()
    {
        ResolveReferences();

        if (autoStart)
            StartEvaluation();
    }

    private void OnEnable()
    {
        ResolveReferences();
        SubscribeObstacleEvents();
    }

    private void OnDisable()
    {
        UnsubscribeObstacleEvents();
        StopTransitionRoutine();
        ReturnControlToCoexistingAgent();
    }

    private void ResolveReferences()
    {
        if (trainingManager == null)
            trainingManager = FindFirstObjectByType<TrainingManager>();

        if (obstacleScenarioManager == null)
            obstacleScenarioManager = FindFirstObjectByType<DynamicObstacleScenarioManager>();

        if (agent == null)
            agent = FindFirstObjectByType<NavMeshAgent>();

        if (coexistingAgent == null && agent != null)
            coexistingAgent = agent.GetComponent<GO1Agent>();
    }

    /// <summary>
    /// agent와 같은 리그에 GO1Agent(RL)가 함께 있으면, GO1AutoNavigator의 수동 주행과 동일한 방식으로
    /// CharacterController/RL 이동을 평가 세션 동안 비활성화합니다. 그래야 NavMeshAgent가 단독으로
    /// Transform을 제어하며 "NavMesh만으로" 장애물에 대응하는지 순수하게 관찰할 수 있습니다.
    /// </summary>
    private void TakeControlFromCoexistingAgent()
    {
        // GO1PathPlanner(같은 리그에 있으면)가 Awake()에서 navAgent.updatePosition/updateRotation을
        // false로 고정해 둔다 — GO1Agent가 CharacterController로 직접 움직이고 NavMeshAgent는
        // 경로 계산 참조용으로만 쓰기 때문이다. C1은 NavMeshAgent 자체가 Transform을 움직여야 하므로
        // 여기서 다시 true로 되돌려야 실제로 로봇이 이동한다.
        if (agent != null)
        {
            agent.updatePosition = true;
            agent.updateRotation = true;
        }

        if (coexistingAgent == null || coexistingAgentControlTaken)
            return;

        // enableDemoRecording=false: C1은 자동 반복 평가라 ML-Agents 데모 녹화가 필요 없고,
        // 켜둔 채 오래 방치하면 .demo 파일 재임포트 문제(무한 임포트 루프)가 생길 수 있다.
        coexistingAgent.OnExternalControlStarted(false);
        coexistingAgentControlTaken = true;

        if (debugLogs)
            Debug.Log("[C1EvaluationManager] GO1Agent 제어권 이관(OnExternalControlStarted) | agent=" + coexistingAgent.name, this);
    }

    private void ReturnControlToCoexistingAgent()
    {
        if (coexistingAgent == null || !coexistingAgentControlTaken)
            return;

        coexistingAgent.OnExternalControlEnded();
        coexistingAgentControlTaken = false;

        // GO1PathPlanner가 기대하는 수동 동기화 모드로 되돌려서 GO1Agent에게 리그를 온전히 반환한다.
        if (agent != null)
        {
            agent.updatePosition = false;
            agent.updateRotation = false;
        }

        if (debugLogs)
            Debug.Log("[C1EvaluationManager] GO1Agent 제어권 반환(OnExternalControlEnded) | agent=" + coexistingAgent.name, this);
    }

    private void SubscribeObstacleEvents()
    {
        if (obstacleScenarioManager == null)
            return;

        obstacleScenarioManager.ObstaclePlacementFinished -= OnObstaclePlacementFinished;
        obstacleScenarioManager.ObstaclePlacementFinished += OnObstaclePlacementFinished;
    }

    private void UnsubscribeObstacleEvents()
    {
        if (obstacleScenarioManager != null)
            obstacleScenarioManager.ObstaclePlacementFinished -= OnObstaclePlacementFinished;
    }

    private bool ValidateReferences(out string error)
    {
        if (agent == null) { error = "NavMeshAgent 참조가 없습니다."; return false; }
        if (trainingManager == null) { error = "TrainingManager 참조가 없습니다."; return false; }
        if (obstacleScenarioManager == null) { error = "DynamicObstacleScenarioManager 참조가 없습니다."; return false; }
        if (obstacleScenarioManager.obstaclePrefab == null) { error = "Obstacle Prefab이 지정되지 않았습니다."; return false; }
        error = string.Empty;
        return true;
    }

    [ContextMenu("Start C1 Evaluation")]
    public void StartEvaluation()
    {
        ResolveReferences();
        SubscribeObstacleEvents();

        if (!ValidateReferences(out string error))
        {
            Debug.LogError("[C1EvaluationManager] " + error, this);
            return;
        }

        if (string.IsNullOrEmpty(experimentSessionId))
            experimentSessionId = DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture);

        InitializeCsv();
        TakeControlFromCoexistingAgent();
        Time.timeScale = Mathf.Max(0.1f, simulationSpeedMultiplier);

        StopTransitionRoutine();
        evaluationRunning = true;
        currentTrialIndex = 0;
        currentSetIndex = 0;
        totalScenarioSkips = 0;
        ApplyCurrentSetSeed();

        transitionRoutine = StartCoroutine(BeginNewTrialRoutine());
    }

    [ContextMenu("Stop C1 Evaluation")]
    public void StopEvaluation()
    {
        evaluationRunning = false;
        phase = EvaluationPhase.Stopped;
        StopTransitionRoutine();

        if (agent != null && agent.isOnNavMesh)
            agent.ResetPath();

        if (obstacleScenarioManager != null)
            obstacleScenarioManager.DestroySpawnedObstacle();

        ReturnControlToCoexistingAgent();
        Time.timeScale = 1f;

        if (debugLogs)
            Debug.Log("[C1EvaluationManager] 평가를 정지했습니다.", this);
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Trial flow
    // ═══════════════════════════════════════════════════════════════════════

    private IEnumerator BeginNewTrialRoutine()
    {
        phase = EvaluationPhase.PreparingTrial;
        ResetTrialState();
        prepStartTime = Time.time;

        bool prepared = false;
        string lastError = "unknown";

        for (int posRetry = 0; posRetry <= maxPositionRetries; posRetry++)
        {
            if (!PrepareScenarioStartAndGoal(posRetry, out lastError))
            {
                yield return null;
                continue;
            }

            if (!TryCalculateBaselinePath(out lastError))
            {
                yield return null;
                continue;
            }

            // C2/C3의 PlaceObstacleThenRunRoutine과 동일하게, 장애물 배치 검증
            // (minDistanceFromRobot 등)이 "로봇이 출발점에 있는" 기준으로 이뤄지도록
            // 실제 타이밍 측정을 시작하기 전에 먼저 출발점으로 워프한다.
            yield return WarpAgentToStartRoutine();

            if (coexistingAgent != null && coexistingAgent.target != null)
            {
                coexistingAgent.target.position = savedGoalPosition;
                coexistingAgent.SetGoal(coexistingAgent.target);
            }

            // GO1Agent.SetGoal()이 GO1PathPlanner.EnsureInitialized()를 거치며
            // navAgent.updatePosition/updateRotation을 다시 false로 되돌릴 수 있다.
            agent.updatePosition = true;
            agent.updateRotation = true;

            bool obstacleFound;

            if (!useNavMeshPathDirectly)
            {
                // 실시간 배치 모드: 장애물은 여기서 만들지 않는다. Update()에서 로봇이
                // 실제 주행 중 진행률 기준을 넘는 순간 그 자리에서 생성된다. 시나리오 인덱스만
                // 미리 고정해 GetCurrentScenarioPathProgress()/GetCurrentScenarioId()가 이후
                // 같은 값을 보게 한다(C2C3EvaluationManager의 기본 흐름과 동일).
                if (obstacleScenarioManager != null)
                {
                    obstacleScenarioManager.currentScenarioIndex = currentTrialIndex + totalScenarioSkips;
                    obstacleScenarioManager.ResetCurrentScenario();
                }

                obstacleFound = true;
            }
            else if (obstacleScenarioManager == null)
            {
                obstacleFound = false;
                lastError = "obstacle_manager_null";
            }
            else
            {
                obstacleFound = false;

                for (int obsRetry = 0; obsRetry <= maxObstacleRetries; obsRetry++)
                {
                    obstaclePlaced = false;
                    obstaclePlacementFailed = false;
                    lastPlacementMessage = string.Empty;

                    int scenarioIdx = currentTrialIndex + totalScenarioSkips;
                    obstacleScenarioManager.currentScenarioIndex = scenarioIdx;
                    obstacleScenarioManager.ResetCurrentScenario();
                    obstacleScenarioManager.SpawnObstacleForEvaluationPath(baselinePath, false);

                    // carving 대기(carvingApplyWait 등)는 실제 시간 기준(WaitForSecondsRealtime)이라
                    // 이 타임아웃도 같은 기준(Time.realtimeSinceStartup)으로 맞춰야 고배속에서
                    // carving이 끝나기 전에 타임아웃이 먼저 나는 문제가 없다.
                    float waitStart = Time.realtimeSinceStartup;
                    while (!obstaclePlaced && !obstaclePlacementFailed &&
                           Time.realtimeSinceStartup - waitStart < obstacleFirstPlacementTimeout)
                        yield return null;

                    if (!obstaclePlaced)
                    {
                        obstacleScenarioManager.ResetCurrentScenario();
                        totalScenarioSkips++;

                        if (debugLogs)
                            Debug.LogWarning(
                                "[C1EvaluationManager] 장애물 배치 실패 → 다음 시나리오로 재시도 | reason=" +
                                lastPlacementMessage + ", obsRetry=" + obsRetry + ", posRetry=" + posRetry,
                                this
                            );

                        // 파괴(Destroy)는 프레임 끝에 처리되고 NavMeshObstacle carving 해제도
                        // 시간이 걸린다. 같은 프레임에 바로 재시도하면 carving 잔여물이 쌓일 수
                        // 있으므로 최소 한 프레임 여유를 준다.
                        yield return null;
                        continue;
                    }

                    // NavMeshObstacle carving 적용 대기 후 우회 경로 존재 확인
                    yield return null;
                    yield return null;

                    NavMeshPath postPath = new NavMeshPath();
                    bool postOk = NavMesh.CalculatePath(savedStartPosition, savedGoalPosition, NavMesh.AllAreas, postPath);
                    if (!postOk || postPath.status != NavMeshPathStatus.PathComplete || postPath.corners.Length < 2)
                    {
                        obstacleScenarioManager.ResetCurrentScenario();
                        totalScenarioSkips++;

                        if (debugLogs)
                            Debug.LogWarning(
                                "[C1EvaluationManager] 장애물이 우회 경로까지 차단 → 다음 시나리오로 재시도 | obsRetry=" +
                                obsRetry + ", posRetry=" + posRetry,
                                this
                            );

                        yield return null;
                        continue;
                    }

                    obstacleFound = true;
                    break;
                }
            }

            if (obstacleFound)
            {
                prepared = true;
                break;
            }

            lastError = "obstacle_setup_failed:" + lastPlacementMessage;
        }

        if (!prepared)
        {
            if (debugLogs)
                Debug.LogWarning("[C1EvaluationManager] 시나리오 준비 실패 → trial 건너뜀 | reason=" + lastError, this);

            WriteMissionSummaryRow(false, "scenario_prepare_failed:" + lastError, 0f, 0f, 0, 0, 0, 0);
            AdvanceAfterTrial();
            transitionRoutine = null;
            yield break;
        }

        BeginRun();
        transitionRoutine = null;
    }

    private IEnumerator WarpAgentToStartRoutine()
    {
        // 직전 trial이 오래(예: run_timeout) 계속되면 NavMeshAgent의 내부 비동기 경로 쿼리
        // 상태가 꼬인 채로 남을 수 있다(관찰된 증상: 이후 모든 trial이 같은 지점에 갇힘).
        // 컴포넌트를 껐다 켜서 내부 상태를 완전히 초기화한 뒤 다음 trial을 시작한다.
        agent.enabled = false;
        yield return null;
        agent.enabled = true;
        yield return null;

        NavMeshHit hit;
        if (NavMesh.SamplePosition(savedStartPosition, out hit, 5.0f, NavMesh.AllAreas))
            agent.Warp(hit.position);
        else
            agent.Warp(savedStartPosition);

        agent.transform.rotation = savedStartRotation;
        agent.autoRepath = true;
        agent.isStopped = false;
        agent.ResetPath();
    }

    private bool PrepareScenarioStartAndGoal(int retryAttempt, out string error)
    {
        error = string.Empty;

        // trial 전용 시드로 재시드하는 오버로드를 쓴다 — 그래야 C1/C2/C3가 각각 별도
        // 세션으로 돌아도 같은 trial 번호는 항상 같은 시작/목표를 뽑는다(짝비교 가능).
        Vector3 startPosition = trainingManager.GetRandomStartPositionForTrial(currentTrialIndex, retryAttempt);

        if (!trainingManager.TryGetRandomGoalPositionForTrial(currentTrialIndex, retryAttempt, startPosition, out Vector3 goalPosition))
        {
            error = "goal_generation_failed";
            return false;
        }

        Quaternion startRotation = Quaternion.identity;
        if (useDeterministicStartYaw)
        {
            System.Random random = new System.Random(startYawBaseSeed + currentTrialIndex);
            float yaw = (float)(random.NextDouble() * 360.0);
            startRotation = Quaternion.Euler(0f, yaw, 0f);
        }

        savedStartPosition = startPosition;
        savedStartRotation = startRotation;
        savedGoalPosition = goalPosition;
        return true;
    }

    private bool TryCalculateBaselinePath(out string error)
    {
        error = string.Empty;

        NavMeshPath navPath = new NavMeshPath();
        bool ok = NavMesh.CalculatePath(savedStartPosition, savedGoalPosition, NavMesh.AllAreas, navPath);

        if (!ok || navPath.status != NavMeshPathStatus.PathComplete || navPath.corners.Length < 2)
        {
            error = "baseline_path_incomplete";
            return false;
        }

        baselinePath.Clear();
        baselinePath.AddRange(navPath.corners);
        baselinePathLength = DynamicObstacleScenarioManager.CalculatePolylineLength(baselinePath);
        return true;
    }

    private void BeginRun()
    {
        phase = EvaluationPhase.Running;

        // 장애물은 이미 준비 단계(BeginNewTrialRoutine)에서 로봇이 출발점에 있는 상태로
        // 배치를 마쳤다(C2/C3의 useNavMeshPathDirectly 흐름과 동일). 여기서는 실제 주행
        // 타이밍만 시작하면 된다. GO1PathPlanner.EnsureInitialized()가 그 사이 다시
        // updatePosition/updateRotation을 false로 되돌렸을 수 있어 재확인한다.
        // updateRotation은 항상 true로 켜지 않는다 — go1 메시 정면 축이 Unity 기본 forward와
        // 어긋나 있어(visualYawOffset), NavMeshAgent의 기본 회전을 그대로 쓰면 이동 방향과
        // 무관하게 옆으로 미끄러지듯 보인다. controlRotationManually=true면 직접 보정한다.
        agent.updatePosition = true;
        agent.updateRotation = !controlRotationManually;

        runStartTime = Time.time;
        initialPlanStartTime = Time.time;
        initialPlanDoneTime = -1f;
        previousPosition = agent.transform.position;

        agent.SetDestination(savedGoalPosition);

        if (debugLogs)
        {
            Debug.Log(
                "[C1EvaluationManager] 주행 시작 | trial=" + (currentTrialIndex + 1) + "/" + totalTrials +
                ", start=" + savedStartPosition + ", goal=" + savedGoalPosition +
                ", baselineLength=" + baselinePathLength.ToString("F2") + "m",
                this
            );
        }
    }

    private void ResetTrialState()
    {
        obstacleSpawnRequested = false;
        obstaclePlaced = false;
        obstaclePlacementFailed = false;
        lastPlacementMessage = string.Empty;
        obstaclePlacedTime = -1f;
        travelDistance = 0f;
        baselinePath.Clear();
        baselinePathLength = 0f;

        pathSignatureInitialized = false;
        lastPathCornerCount = -1;
        lastPathCornerSum = Vector3.zero;
        pendingPathCornerCount = -1;
        pendingPathCornerSum = Vector3.zero;
        rerouteCountThisTrial = 0;
        firstRerouteAfterObstacleTime = -1f;

        collisionCountThisTrial = 0;
        obstacleCollisionCountThisTrial = 0;
        lastCollisionTime = -999f;

        stuckCountThisTrial = 0;
        timeSinceMovement = 0f;
        currentlyStuck = false;
    }

    private void ReassertAgentDriveFlags()
    {
        // GO1PathPlanner.EnsureInitialized()가 ML-Agents 결정 주기 등에서 여전히
        // navAgent.updatePosition/updateRotation을 되돌릴 수 있다. C1은 NavMeshAgent가
        // 직접 Transform 위치를 움직여야 하므로 updatePosition은 항상 true로 재확인한다.
        // updateRotation은 항상 true로 켜지 않는다 — go1 메시 정면 축이 어긋나 있어(visualYawOffset)
        // NavMeshAgent 기본 회전을 쓰면 옆으로 미끄러지듯 보이므로, controlRotationManually가
        // 켜져 있으면 false로 유지하고 UpdateRotationToMovementDirection()에서 직접 보정한다.
        if (!agent.updatePosition)
            agent.updatePosition = true;

        bool desiredUpdateRotation = !controlRotationManually;
        if (agent.updateRotation != desiredUpdateRotation)
            agent.updateRotation = desiredUpdateRotation;
    }

    private void UpdateRotationToMovementDirection()
    {
        Vector3 dir = agent.desiredVelocity;
        if (dir.sqrMagnitude < 0.0001f) dir = agent.velocity;
        dir.y = 0f;
        if (dir.sqrMagnitude < 0.0001f) return;

        Quaternion targetRot = Quaternion.LookRotation(dir.normalized);
        targetRot *= Quaternion.Euler(0f, visualYawOffset, 0f);

        agent.transform.rotation = Quaternion.Slerp(
            agent.transform.rotation, targetRot, Time.deltaTime * rotationSpeed
        );
    }

    private void LateUpdate()
    {
        if (IsRunning && phase == EvaluationPhase.Running && agent != null)
            ReassertAgentDriveFlags();
    }

    private void Update()
    {
        if (!IsRunning || phase != EvaluationPhase.Running || agent == null)
            return;

        ReassertAgentDriveFlags();

        if (controlRotationManually)
            UpdateRotationToMovementDirection();

        if (!agent.isOnNavMesh)
        {
            CompleteTrial(false, "off_navmesh");
            return;
        }

        Vector3 currentPosition = agent.transform.position;
        travelDistance += HorizontalDistance(previousPosition, currentPosition);
        previousPosition = currentPosition;

        float elapsed = Time.time - runStartTime;

        if (initialPlanDoneTime < 0f && !agent.pathPending)
            initialPlanDoneTime = Time.time;

        UpdatePathSignatureAndDetectReroute();
        UpdateStuckTracking(elapsed);
        UpdateCollisionTracking(currentPosition);

        if (!useNavMeshPathDirectly)
        {
            if (!obstacleSpawnRequested && elapsed >= minimumRunBeforeObstacle)
                TryRequestObstacleSpawn(currentPosition);

            if (obstaclePlacementFailed)
            {
                CompleteTrial(false, "obstacle_placement_failed:" + lastPlacementMessage);
                return;
            }
        }

        float distanceToGoal = HorizontalDistance(currentPosition, savedGoalPosition);
        if (!agent.pathPending && distanceToGoal <= arriveDistanceThreshold)
        {
            CompleteTrial(true, "goal_reached");
            return;
        }

        if (!agent.pathPending && agent.remainingDistance <= Mathf.Max(agent.stoppingDistance, arriveDistanceThreshold) &&
            agent.velocity.sqrMagnitude < 0.0001f && distanceToGoal <= arriveDistanceThreshold * 2f)
        {
            CompleteTrial(true, "goal_reached_stopped");
            return;
        }

        if (timeSinceMovement >= stoppedAgentFailTimeout)
        {
            LogStoppedDiagnostics(currentPosition, distanceToGoal);
            CompleteTrial(false, "agent_stopped");
            return;
        }

        if (baselinePathLength > 0.001f && travelDistance > baselinePathLength * excessiveWanderingMultiplier)
        {
            LogStoppedDiagnostics(currentPosition, distanceToGoal);
            CompleteTrial(false, "excessive_wandering");
            return;
        }

        if (elapsed >= runTimeout)
        {
            CompleteTrial(false, "run_timeout");
            return;
        }
    }

    private void TryRequestObstacleSpawn(Vector3 currentPosition)
    {
        if (obstacleScenarioManager == null || obstacleScenarioManager.IsBusy)
            return;

        float scenarioProgress = obstacleScenarioManager.GetCurrentScenarioPathProgress();
        float triggerProgress = Mathf.Clamp01(scenarioProgress - obstacleSpawnLeadProgress);
        float currentProgress = CalculatePathProgressXZ(baselinePath, currentPosition);

        if (currentProgress < triggerProgress)
            return;

        obstacleSpawnRequested = true;
        // notifyAgentRuntimeObstacle=false: 이 평가 매니저(NavMeshAgent.autoRepath)가 직접
        // 관찰만 하고 GO1Agent 쪽에는 알리지 않는다(C2/C3 정량평가와 동일한 방식).
        obstacleScenarioManager.SpawnObstacleForEvaluationPath(baselinePath, false);

        if (debugLogs)
        {
            Debug.Log(
                "[C1EvaluationManager] 주행 중 장애물 생성 요청 | robotProgress=" +
                currentProgress.ToString("F3") + ", triggerProgress=" + triggerProgress.ToString("F3"),
                this
            );
        }
    }

    private void OnObstaclePlacementFinished(bool success, GameObject obstacle, string message)
    {
        if (phase != EvaluationPhase.PreparingTrial && phase != EvaluationPhase.Running)
            return;

        lastPlacementMessage = message ?? string.Empty;

        if (!success)
        {
            obstaclePlacementFailed = true;
            return;
        }

        obstaclePlaced = true;
        obstaclePlacedTime = Time.time;

        WriteObstacleEventRow(obstacle);

        if (debugLogs)
        {
            Debug.Log(
                "[C1EvaluationManager] 장애물 배치 완료 → 이후 회피는 NavMeshAgent 자동 재경로에 위임 | " +
                "obstacle=" + (obstacle != null ? obstacle.name : "null"),
                this
            );
        }
    }

    private void UpdatePathSignatureAndDetectReroute()
    {
        if (agent.pathPending)
            return;

        Vector3[] corners = agent.path != null ? agent.path.corners : null;
        int cornerLength = corners != null ? corners.Length : 0;

        // corners[0]은 "지금 여기 있다"는 에이전트의 현재 위치이며 이동할 때마다 매 프레임
        // 바뀐다. 이걸 시그니처에 포함하면 정상 주행 중에도 매 프레임 "경로가 바뀜"으로
        // 오검출된다. 남은 waypoint(corners[1..])만 비교해야 실제 재탐색과 단순 진행을 구분한다.
        int remainingWaypointCount = Mathf.Max(0, cornerLength - 1);
        Vector3 sum = Vector3.zero;
        for (int i = 1; i < cornerLength; i++)
            sum += corners[i];

        if (!pathSignatureInitialized)
        {
            lastPathCornerCount = remainingWaypointCount;
            lastPathCornerSum = sum;
            pendingPathCornerCount = remainingWaypointCount;
            pendingPathCornerSum = sum;
            pathSignatureInitialized = true;
            return;
        }

        // NavMesh 경로는 코너 근처에서 인접 프레임끼리 코너 개수가 잠깐 흔들릴 수 있다(예: 2↔3).
        // 이런 단발성 흔들림을 진짜 재탐색으로 세지 않도록, 새 시그니처가 최소 두 프레임
        // 연속으로 유지될 때만 "확정된 변화"로 인정한다(디바운스).
        bool matchesPending = remainingWaypointCount == pendingPathCornerCount &&
                              Vector3.Distance(sum, pendingPathCornerSum) <= 0.05f;

        if (!matchesPending)
        {
            pendingPathCornerCount = remainingWaypointCount;
            pendingPathCornerSum = sum;
            return;
        }

        // waypoint 수가 줄어드는 것은 코너를 정상적으로 지나쳤다는 뜻이지 재탐색이 아니다.
        // waypoint 수가 늘거나, 개수는 같은데 위치 자체가 바뀐 경우만 실제 재탐색으로 본다.
        bool countIncreased = remainingWaypointCount > lastPathCornerCount;
        bool samePositionChanged = remainingWaypointCount == lastPathCornerCount &&
                                    Vector3.Distance(sum, lastPathCornerSum) > 0.05f;
        bool changed = countIncreased || samePositionChanged;

        lastPathCornerCount = remainingWaypointCount;
        lastPathCornerSum = sum;

        if (changed && obstaclePlaced)
        {
            rerouteCountThisTrial++;

            if (firstRerouteAfterObstacleTime < 0f)
                firstRerouteAfterObstacleTime = Time.time;

            if (debugLogs)
            {
                Debug.Log(
                    "[C1EvaluationManager] NavMeshAgent 자동 재경로 감지 | count=" + rerouteCountThisTrial +
                    ", detectionLatency=" + (Time.time - obstaclePlacedTime).ToString("F3") + "s",
                    this
                );
            }
        }
    }

    private void UpdateStuckTracking(float elapsed)
    {
        bool moving = agent.velocity.magnitude >= stuckVelocityThreshold || agent.pathPending;

        if (moving)
        {
            timeSinceMovement = 0f;
            currentlyStuck = false;
            return;
        }

        timeSinceMovement += Time.deltaTime;

        if (!currentlyStuck && timeSinceMovement >= stuckEventThreshold)
        {
            currentlyStuck = true;
            stuckCountThisTrial++;
        }
    }

    private void UpdateCollisionTracking(Vector3 currentPosition)
    {
        GameObject obstacle = obstacleScenarioManager != null ? obstacleScenarioManager.SpawnedObstacle : null;
        if (obstacle == null)
            return;

        if (Time.time - lastCollisionTime < collisionCooldown)
            return;

        Bounds bounds = DynamicObstacleScenarioManager.GetObstacleBounds(obstacle);
        float obstacleRadius = Mathf.Max(bounds.extents.x, bounds.extents.z);
        float distance = HorizontalDistance(currentPosition, bounds.center);

        if (distance <= obstacleRadius + collisionProximityMargin)
        {
            lastCollisionTime = Time.time;
            collisionCountThisTrial++;
            obstacleCollisionCountThisTrial++;

            if (debugLogs)
                Debug.LogWarning("[C1EvaluationManager] 장애물 근접(충돌) 감지 | distance=" + distance.ToString("F2"), this);
        }
    }

    /// <summary>
    /// "agent_stopped"로 trial이 실패할 때 원인 추적용 진단 정보를 남깁니다.
    /// pathStatus가 Partial/Invalid면 NavMesh 연결성 문제, 장애물이 매우 가까우면 carving 회피 실패,
    /// remainingDistance가 크고 velocity도 0이면 로컬 어보이던스에 걸려 멈춘 경우일 가능성이 높습니다.
    /// </summary>
    private void LogStoppedDiagnostics(Vector3 currentPosition, float distanceToGoal)
    {
        GameObject obstacle = obstacleScenarioManager != null ? obstacleScenarioManager.SpawnedObstacle : null;
        string obstacleInfo = "none";

        if (obstacle != null)
        {
            Bounds bounds = DynamicObstacleScenarioManager.GetObstacleBounds(obstacle);
            float distanceToObstacle = HorizontalDistance(currentPosition, bounds.center);
            obstacleInfo = obstacle.name + " dist=" + distanceToObstacle.ToString("F2") + "m";
        }

        Debug.LogWarning(
            "[C1EvaluationManager] agent_stopped 진단 | trial=" + (currentTrialIndex + 1) +
            ", pathStatus=" + agent.pathStatus +
            ", hasPath=" + agent.hasPath +
            ", pathPending=" + agent.pathPending +
            ", isOnNavMesh=" + agent.isOnNavMesh +
            ", remainingDistance=" + agent.remainingDistance.ToString("F2") +
            ", velocity=" + agent.velocity.magnitude.ToString("F3") +
            ", distanceToGoal=" + distanceToGoal.ToString("F2") +
            ", obstaclePlaced=" + obstaclePlaced +
            ", obstacle=" + obstacleInfo +
            ", pos=" + currentPosition + ", goal=" + savedGoalPosition,
            this
        );
    }

    private void CompleteTrial(bool success, string reason)
    {
        if (phase != EvaluationPhase.Running)
            return;

        phase = EvaluationPhase.TrialCompleted;

        float duration = Mathf.Max(0f, Time.time - runStartTime);
        Vector3 endPos = agent.transform.position;
        float finalError = HorizontalDistance(endPos, savedGoalPosition);
        float planningTime = initialPlanDoneTime >= 0f
            ? Mathf.Max(0f, initialPlanDoneTime - initialPlanStartTime)
            : 0f;
        float replanTime = firstRerouteAfterObstacleTime >= 0f && obstaclePlacedTime >= 0f
            ? Mathf.Max(0f, firstRerouteAfterObstacleTime - obstaclePlacedTime)
            : 0f;

        if (agent.isOnNavMesh)
            agent.ResetPath();

        WriteMissionSummaryRow(
            success, reason, duration, finalError,
            collisionCountThisTrial, obstacleCollisionCountThisTrial,
            stuckCountThisTrial, rerouteCountThisTrial,
            planningTime, replanTime, endPos
        );

        obstacleScenarioManager?.DestroySpawnedObstacle();

        if (debugLogs)
        {
            Debug.Log(
                "[C1EvaluationManager] trial 완료 | trial=" + (currentTrialIndex + 1) + "/" + totalTrials +
                ", success=" + success + ", reason=" + reason +
                ", duration=" + duration.ToString("F2") + "s" +
                ", finalError=" + finalError.ToString("F2") + "m" +
                ", collisions=" + collisionCountThisTrial +
                ", reroutes=" + rerouteCountThisTrial,
                this
            );
        }

        AdvanceAfterTrial();
    }

    private void AdvanceAfterTrial()
    {
        StopTransitionRoutine();
        obstacleScenarioManager?.DestroySpawnedObstacle();

        currentTrialIndex++;

        int setSize = Mathf.Max(1, trialsPerSet);
        int trialInSet = currentTrialIndex % setSize;

        if (trialInSet == 0 && currentTrialIndex > 0)
        {
            currentSetIndex++;
            int totalSets = scenarioSetSeeds != null ? scenarioSetSeeds.Length : 1;

            if (currentSetIndex >= totalSets)
            {
                FinishEvaluation();
                return;
            }

            ApplyCurrentSetSeed();

            if (debugLogs)
                Debug.Log(
                    $"[C1EvaluationManager] 세트 전환 | set={currentSetIndex + 1}/{totalSets} " +
                    $"seed={GetCurrentSetSeed()} trial={currentTrialIndex + 1}",
                    this
                );
        }

        transitionRoutine = StartCoroutine(BeginNextTrialAfterDelay());
    }

    private IEnumerator BeginNextTrialAfterDelay()
    {
        if (nextTrialDelay > 0f)
            yield return new WaitForSeconds(nextTrialDelay);

        transitionRoutine = StartCoroutine(BeginNewTrialRoutine());
    }

    private void FinishEvaluation()
    {
        evaluationRunning = false;
        phase = EvaluationPhase.Finished;

        if (agent != null && agent.isOnNavMesh)
            agent.ResetPath();

        obstacleScenarioManager?.DestroySpawnedObstacle();
        ReturnControlToCoexistingAgent();
        Time.timeScale = 1f;

        Debug.Log(
            "[C1EvaluationManager] 전체 평가 완료 | trials=" + totalTrials +
            ", folder=" + experimentDirectory,
            this
        );

        if (stopPlayModeWhenFinished)
        {
#if UNITY_EDITOR
            UnityEditor.EditorApplication.isPlaying = false;
#else
            Application.Quit();
#endif
        }
    }

    private int GetCurrentSetSeed()
    {
        if (scenarioSetSeeds == null || scenarioSetSeeds.Length == 0)
            return 121;
        return scenarioSetSeeds[Mathf.Clamp(currentSetIndex, 0, scenarioSetSeeds.Length - 1)];
    }

    private void ApplyCurrentSetSeed()
    {
        int seed = GetCurrentSetSeed();

        if (obstacleScenarioManager != null)
            obstacleScenarioManager.baseRandomSeed = seed;

        if (trainingManager != null)
        {
            trainingManager.randomSeed = seed;
            trainingManager.useFixedRandomSeed = true;
        }

        if (debugLogs)
            Debug.Log($"[C1EvaluationManager] 시드 적용 | set={currentSetIndex + 1} seed={seed}", this);
    }

    private void StopTransitionRoutine()
    {
        if (transitionRoutine != null)
        {
            StopCoroutine(transitionRoutine);
            transitionRoutine = null;
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Logging (GO1Agent의 CSV 스키마와 동일한 헤더를 사용 — C1/C2/C3 비교 분석 호환)
    // ═══════════════════════════════════════════════════════════════════════

    private void InitializeCsv()
    {
        if (!writeResultCsv)
            return;

        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        string baseDirectory = Path.Combine(projectRoot, resultFolderName);
        experimentDirectory = createSessionSubfolder
            ? Path.Combine(baseDirectory, experimentSessionId)
            : baseDirectory;

        Directory.CreateDirectory(experimentDirectory);

        missionSummaryCsvPath = Path.Combine(experimentDirectory, "mission_summary.csv");
        scenarioConfigCsvPath = Path.Combine(experimentDirectory, "scenario_config.csv");
        obstacleEventCsvPath = Path.Combine(experimentDirectory, "obstacle_events.csv");
        experimentConfigCsvPath = Path.Combine(experimentDirectory, "experiment_config.csv");

        EnsureCsvHeader(
            missionSummaryCsvPath,
            "session_id,agent_name,trial_id,condition_id,scenario_id,map_id,policy_id,method,mode,difficulty_level,random_seed,start_time_iso,end_time_iso,success,end_reason,duration_sec,planning_time_sec,travel_distance_m,shortest_path_m,path_efficiency,collision_count,obstacle_collision_count,stuck_count,replan_count,replan_time_sec,raw_waypoints,sent_waypoints,sent_path_length_m,final_target_error_m,reached_by_error,cumulative_reward,steps,start_x,start_z,start_yaw,target_x,target_z,end_x,end_z,end_yaw"
        );
        EnsureCsvHeader(
            scenarioConfigCsvPath,
            "session_id,agent_name,trial_id,mode,condition_id,scenario_id,map_id,policy_id,difficulty_level,evaluation_fixed_difficulty,agent_count,goal_min_distance,goal_max_distance,min_open_radius,start_x,start_z,start_yaw,target_x,target_z,target_straight_distance_m,random_seed,created_at_iso"
        );
        EnsureCsvHeader(
            obstacleEventCsvPath,
            "session_id,agent_name,trial_id,condition_id,scenario_id,time_sec,obstacle_name,center_x,center_z,size_x,size_z,distance_to_path_m,block_threshold_m,closest_segment,path_blocked,replan_requested,replan_skip_reason,replan_count"
        );
        EnsureCsvHeader(
            experimentConfigCsvPath,
            "session_id,agent_name,condition_id,scenario_id,map_id,policy_id,method,random_seed,unity_version,mlagents_version,yaml_name,evaluation_mode,communicator_on,created_at_iso"
        );

        if (debugLogs)
            Debug.Log("[C1EvaluationManager] 실험 CSV 저장 폴더: " + experimentDirectory, this);
    }

    private void EnsureCsvHeader(string path, string header)
    {
        if (!File.Exists(path) || new FileInfo(path).Length == 0)
            File.WriteAllText(path, header + "\n", new UTF8Encoding(true));
    }

    private void EnsureStaticConfigWritten()
    {
        if (staticConfigWritten || !writeResultCsv || string.IsNullOrEmpty(experimentConfigCsvPath))
            return;

        string scenarioId = obstacleScenarioManager != null
            ? obstacleScenarioManager.GetCurrentScenarioId()
            : "S" + (currentTrialIndex + 1).ToString("D2");

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(agent != null ? agent.gameObject.name : "C1Agent"),
            Csv(experimentConditionId),
            Csv(scenarioId),
            Csv(experimentMapId),
            Csv(experimentPolicyId),
            Csv(experimentMethodName),
            GetCurrentSetSeed().ToString(CultureInfo.InvariantCulture),
            Csv(Application.unityVersion),
            Csv("n/a"),
            Csv("n/a"),
            "1",
            "0",
            Csv(DateTime.Now.ToString("o", CultureInfo.InvariantCulture))
        });

        AppendLine(experimentConfigCsvPath, row);
        staticConfigWritten = true;
    }

    private void WriteScenarioConfigRow()
    {
        if (!writeResultCsv || string.IsNullOrEmpty(scenarioConfigCsvPath))
            return;

        string scenarioId = obstacleScenarioManager != null
            ? obstacleScenarioManager.GetCurrentScenarioId()
            : "S" + (currentTrialIndex + 1).ToString("D2");

        int difficultyLevel = trainingManager != null ? trainingManager.GetCurrentDifficultyLevel() : -1;
        bool evaluationFixed = trainingManager != null && trainingManager.IsEvaluationDifficultyFixed();
        int agentCount = trainingManager != null ? trainingManager.agentCount : 1;
        float goalMin = trainingManager != null ? trainingManager.goalMinDistance : -1f;
        float goalMax = trainingManager != null ? trainingManager.goalMaxDistance : -1f;
        float openRadius = trainingManager != null ? trainingManager.minOpenRadius : -1f;
        float targetDistance = HorizontalDistance(savedStartPosition, savedGoalPosition);

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(agent != null ? agent.gameObject.name : "C1Agent"),
            currentTrialIndex.ToString(CultureInfo.InvariantCulture),
            Csv("evaluation"),
            Csv(experimentConditionId),
            Csv(scenarioId),
            Csv(experimentMapId),
            Csv(experimentPolicyId),
            difficultyLevel.ToString(CultureInfo.InvariantCulture),
            evaluationFixed ? "1" : "0",
            agentCount.ToString(CultureInfo.InvariantCulture),
            F(goalMin),
            F(goalMax),
            F(openRadius),
            F(savedStartPosition.x),
            F(savedStartPosition.z),
            F(savedStartRotation.eulerAngles.y),
            F(savedGoalPosition.x),
            F(savedGoalPosition.z),
            F(targetDistance),
            GetCurrentSetSeed().ToString(CultureInfo.InvariantCulture),
            Csv(DateTime.Now.ToString("o", CultureInfo.InvariantCulture))
        });

        AppendLine(scenarioConfigCsvPath, row);
    }

    private void WriteObstacleEventRow(GameObject obstacle)
    {
        if (!writeResultCsv || obstacle == null || string.IsNullOrEmpty(obstacleEventCsvPath))
            return;

        string scenarioId = obstacleScenarioManager != null
            ? obstacleScenarioManager.GetCurrentScenarioId()
            : "S" + (currentTrialIndex + 1).ToString("D2");

        Bounds bounds = DynamicObstacleScenarioManager.GetObstacleBounds(obstacle);
        float obstacleRadius = Mathf.Max(bounds.extents.x, bounds.extents.z);
        float blockThreshold = obstacleRadius + (coexistingAgent != null ? coexistingAgent.pathBlockCheckRadius : 0.25f);
        float distanceToPath = DistancePointToPolylineXZ(bounds.center, baselinePath);

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(agent != null ? agent.gameObject.name : "C1Agent"),
            currentTrialIndex.ToString(CultureInfo.InvariantCulture),
            Csv(experimentConditionId),
            Csv(scenarioId),
            F(Time.time - prepStartTime),
            Csv(obstacle.name),
            F(bounds.center.x),
            F(bounds.center.z),
            F(bounds.size.x),
            F(bounds.size.z),
            F(distanceToPath),
            F(blockThreshold),
            "-1",
            "1",
            "1",
            Csv(""),
            "0"
        });

        AppendLine(obstacleEventCsvPath, row);
    }

    private void WriteMissionSummaryRow(
        bool success,
        string reason,
        float duration,
        float finalError,
        int collisionCount = 0,
        int obstacleCollisionCount = 0,
        int stuckCount = 0,
        int replanCount = 0,
        float planningTime = 0f,
        float replanTime = 0f,
        Vector3? endPositionOverride = null)
    {
        if (!writeResultCsv)
            return;

        EnsureStaticConfigWritten();
        WriteScenarioConfigRow();

        Vector3 endPos = endPositionOverride ?? (agent != null ? agent.transform.position : savedStartPosition);

        NavMeshPath finalPath = new NavMeshPath();
        float shortest = 0f;
        if (NavMesh.CalculatePath(savedStartPosition, savedGoalPosition, NavMesh.AllAreas, finalPath) &&
            finalPath.status == NavMeshPathStatus.PathComplete)
        {
            shortest = DynamicObstacleScenarioManager.CalculatePolylineLength(finalPath.corners);
        }

        float effectiveShortest = Mathf.Max(0f, shortest - finalError);
        float efficiency = travelDistance > 0.0001f
            ? Mathf.Clamp01(effectiveShortest / travelDistance)
            : 0f;

        bool reachedByError = finalError < arriveDistanceThreshold;
        string scenarioId = obstacleScenarioManager != null
            ? obstacleScenarioManager.GetCurrentScenarioId()
            : "S" + (currentTrialIndex + 1).ToString("D2");
        int difficultyLevel = trainingManager != null ? trainingManager.GetCurrentDifficultyLevel() : -1;

        string row = string.Join(",", new string[]
        {
            Csv(experimentSessionId),
            Csv(agent != null ? agent.gameObject.name : "C1Agent"),
            currentTrialIndex.ToString(CultureInfo.InvariantCulture),
            Csv(experimentConditionId),
            Csv(scenarioId),
            Csv(experimentMapId),
            Csv(experimentPolicyId),
            Csv(experimentMethodName),
            Csv("evaluation"),
            difficultyLevel.ToString(CultureInfo.InvariantCulture),
            GetCurrentSetSeed().ToString(CultureInfo.InvariantCulture),
            Csv(DateTime.Now.AddSeconds(-duration).ToString("o", CultureInfo.InvariantCulture)),
            Csv(DateTime.Now.ToString("o", CultureInfo.InvariantCulture)),
            success ? "1" : "0",
            Csv(reason),
            F(duration),
            F(planningTime),
            F(travelDistance),
            F(shortest),
            F(efficiency),
            collisionCount.ToString(CultureInfo.InvariantCulture),
            obstacleCollisionCount.ToString(CultureInfo.InvariantCulture),
            stuckCount.ToString(CultureInfo.InvariantCulture),
            replanCount.ToString(CultureInfo.InvariantCulture),
            F(replanTime),
            baselinePath.Count.ToString(CultureInfo.InvariantCulture),
            lastPathCornerCount.ToString(CultureInfo.InvariantCulture),
            F(shortest),
            F(finalError),
            reachedByError ? "1" : "0",
            F(0f),
            "0",
            F(savedStartPosition.x), F(savedStartPosition.z), F(savedStartRotation.eulerAngles.y),
            F(savedGoalPosition.x), F(savedGoalPosition.z),
            F(endPos.x), F(endPos.z), F(agent != null ? agent.transform.eulerAngles.y : 0f)
        });

        AppendLine(missionSummaryCsvPath, row);
    }

    private void AppendLine(string path, string line)
    {
        if (string.IsNullOrEmpty(path))
            return;

        try
        {
            File.AppendAllText(path, line + "\n", new UTF8Encoding(false));
        }
        catch (Exception e)
        {
            Debug.LogError("[C1EvaluationManager] CSV 저장 실패: " + e.Message, this);
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

    // ═══════════════════════════════════════════════════════════════════════
    // Geometry helpers
    // ═══════════════════════════════════════════════════════════════════════

    private float CalculatePathProgressXZ(IReadOnlyList<Vector3> path, Vector3 position)
    {
        if (path == null || path.Count < 2)
            return 0f;

        float totalLength = DynamicObstacleScenarioManager.CalculatePolylineLength(path);
        if (totalLength < 0.001f)
            return 0f;

        Vector2 p = new Vector2(position.x, position.z);
        float accumulated = 0f;
        float bestDistance = float.MaxValue;
        float bestProgressDistance = 0f;

        for (int i = 0; i < path.Count - 1; i++)
        {
            Vector2 a = new Vector2(path[i].x, path[i].z);
            Vector2 b = new Vector2(path[i + 1].x, path[i + 1].z);
            Vector2 ab = b - a;
            float segmentLength = ab.magnitude;

            if (segmentLength < 0.0001f)
                continue;

            float t = Mathf.Clamp01(Vector2.Dot(p - a, ab) / ab.sqrMagnitude);
            Vector2 projected = a + ab * t;
            float distance = Vector2.Distance(p, projected);

            if (distance < bestDistance)
            {
                bestDistance = distance;
                bestProgressDistance = accumulated + t * segmentLength;
            }

            accumulated += segmentLength;
        }

        return Mathf.Clamp01(bestProgressDistance / totalLength);
    }

    private float DistancePointToPolylineXZ(Vector3 point, IReadOnlyList<Vector3> path)
    {
        if (path == null || path.Count < 2)
            return float.MaxValue;

        float minimum = float.MaxValue;
        for (int i = 0; i < path.Count - 1; i++)
            minimum = Mathf.Min(minimum, DistancePointToSegmentXZ(point, path[i], path[i + 1]));

        return minimum;
    }

    private float DistancePointToSegmentXZ(Vector3 point, Vector3 start, Vector3 end)
    {
        Vector2 p = new Vector2(point.x, point.z);
        Vector2 a = new Vector2(start.x, start.z);
        Vector2 b = new Vector2(end.x, end.z);
        Vector2 ab = b - a;

        if (ab.sqrMagnitude < 0.0001f)
            return Vector2.Distance(p, a);

        float t = Mathf.Clamp01(Vector2.Dot(p - a, ab) / ab.sqrMagnitude);
        Vector2 closest = a + ab * t;
        return Vector2.Distance(p, closest);
    }

    private float HorizontalDistance(Vector3 a, Vector3 b)
    {
        a.y = 0f;
        b.y = 0f;
        return Vector3.Distance(a, b);
    }
}
