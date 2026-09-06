using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Unity 내부에서 C2/C3 비교 실험을 수행하는 평가 관리자입니다.
///
/// 한 trial의 처리 순서
/// 1) 장애물 없이 시작점 -> 목표점으로 이동하여 기준 경로를 기록
/// 2) 같은 시작점, 같은 목표점으로 가상 GO1을 되돌림
/// 3) 기준 경로를 잠근 상태로 두 번째 주행 시작
/// 4) 기준 경로 진행 중 앞쪽에 장애물 생성
/// 5) C2: 잠긴 기준 경로를 유지
///    C3: 잠금을 해제하고 NavMesh 경로를 다시 계산
/// 6) 성공/실패 결과 저장 후 다음 scenario 진행
///
/// TrainingManager는 목표 생성에만 사용하고, 목표 도달 뒤 새 목표로 넘어가는 기본 흐름은
/// GO1Agent가 이 관리자에 먼저 알리도록 패치하여 차단합니다.
/// </summary>
[DefaultExecutionOrder(-300)]
[DisallowMultipleComponent]
public class C2C3EvaluationManager : MonoBehaviour
{
    public enum EvaluationCondition
    {
        C2_NO_REPLAN,
        C3_REPLAN,

        // 전역 계획 없이 RL 단독 주행 조건. 목표점을 단일 경유점([시작점, 목표점] 직선)으로만
        // 관측에 제공하고, 지역 관측(16방향 레이 + 목표 방향)만으로 주행한다.
        // DRL 내비게이션 계열(Chen, Almazrouei 등)의 기본 조건과 대응된다.
        // 사다리 구성: 계획 없음(C1_RL_ONLY) → 낡은 계획(C2) → 재탐색(C3).
        // 장애물 배치는 C2/C3와 동일하게 NavMesh 기준 경로 위에 놓아 시나리오 대응을 유지한다.
        C1_RL_ONLY_NO_PLAN
    }

    public enum EvaluationPhase
    {
        Idle,
        PreparingBaseline,
        BaselineRun,
        PreparingObstacleRun,
        ObstacleRun,
        TrialCompleted,
        Finished,
        Stopped
    }

    [Header("Core References")]
    public GO1Agent agent;
    public GO1PathPlanner pathPlanner;
    public DynamicObstacleScenarioManager obstacleScenarioManager;
    public TrainingManager trainingManager;

    [Tooltip("TrainingManager가 생성한 Agent_0 같은 런타임 에이전트를 자동으로 찾아 연결합니다.")]
    public bool autoBindRuntimeAgent = true;

    [Header("Evaluation Condition")]
    public EvaluationCondition condition = EvaluationCondition.C2_NO_REPLAN;

    [Tooltip("Play 시작 후 평가를 자동 시작합니다.")]
    public bool autoStart = false;

    [Tooltip("TrainingManager가 agent를 생성할 때까지 자동 시작이 기다리는 최대 시간입니다.")]
    [Min(0.5f)]
    public float autoStartReferenceWait = 5f;

    [Tooltip("세트당 trial 수입니다. 총 trial = trialsPerSet × scenarioSetSeeds.Length")]
    [Min(1)]
    public int trialsPerSet = 30;

    [Tooltip("각 세트에 사용할 랜덤 시드 배열입니다. 세트 수 = 배열 길이.")]
    public int[] scenarioSetSeeds = { 121, 222, 333, 444, 555, 666, 777, 888, 999, 1110 };

    // 하위 호환: 기존 Inspector totalTrials는 trialsPerSet × sets 로 자동 계산됩니다.
    public int totalTrials => trialsPerSet * Mathf.Max(1, scenarioSetSeeds != null ? scenarioSetSeeds.Length : 1);

    [Tooltip("현재 trial index입니다. C2와 C3 모두 0에서 시작하세요.")]
    [Min(0)]
    public int currentTrialIndex = 0;

    private int currentSetIndex = 0;

    [Header("Paired Evaluation (C2+C3 동일 장애물)")]
    [Tooltip("true: 장애물을 한 번 배치하고 C2(경로 잠금)와 C3(재탐색)를 순서대로 실행합니다.\n" +
             "같은 장애물 위치에서 두 조건의 차이를 직접 비교합니다.")]
    public bool pairedMode = true;

    [Tooltip("Paired 모드에 C1(전역 계획 없이 RL 단독)을 첫 단계로 포함해 3중 짝(triple)으로 " +
             "실행합니다. 같은 시작/목표/장애물에서 C1→C2→C3를 연달아 돌리므로 300개 trial 전부가 " +
             "좌표 단위로 정확히 대응됩니다(별도 세션 방식의 좌표 매칭 손실 없음).")]
    public bool pairedIncludeC1RlOnly = false;

    [Tooltip("Paired 모드에서 C2 완료 후 C3 시작 전 에이전트 리셋 대기 시간입니다.")]
    [Min(0f)]
    public float pairedIntraTrialDelay = 0.5f;

    [Tooltip("같은 시나리오의 기준 경로 생성이 실패했을 때 재시도 횟수입니다.")]
    [Range(0, 10)]
    public int maxBaselineRetries = 2;

    [Header("Unity Standalone Mode (실제 Go1 없이)")]
    [Tooltip("기준 주행 없이 NavMesh 계획 경로를 직접 기준 경로로 사용합니다.\n" +
             "실제 Go1 없이 Unity 단독 실험(논문 C2/C3)에 권장합니다.\n" +
             "흐름: 경로 계산 → 장애물 배치 → C2: 원본 경로 잠금 출발 / C3: 재탐색 후 출발")]
    public bool useNavMeshPathDirectly = false;

    [Tooltip("useNavMeshPathDirectly 모드에서 장애물 배치 완료 후 에이전트 출발까지 대기 시간입니다.")]
    [Min(0f)]
    public float placementToRunDelay = 0.3f;

    [Tooltip("useNavMeshPathDirectly 모드에서 장애물 배치 완료를 기다리는 최대 시간입니다.")]
    [Min(1f)]
    public float obstacleFirstPlacementTimeout = 8f;

    [Header("Scenario Generation")]
    [Tooltip("TrainingManager를 이용해 trial마다 새 시작점과 목표점을 생성합니다.")]
    public bool generateScenarioWithTrainingManager = true;

    [Tooltip("시작 yaw를 trial seed로 고정 생성합니다.")]
    public bool useDeterministicStartYaw = true;

    [Tooltip("시작 yaw 생성 기준 seed입니다. C2/C3에서 동일하게 유지하세요.")]
    public int startYawBaseSeed = 121;

    [Tooltip("TrainingManager를 쓰지 않을 때 사용할 시작 위치입니다. 비우면 현재 agent 위치를 사용합니다.")]
    public Transform fallbackStartPoint;

    [Header("Run Timing")]
    [Tooltip("기준 경로 도착 후 시작점으로 되돌리기 전 대기 시간입니다.")]
    [Min(0f)]
    public float resetDelay = 0.25f;

    [Tooltip("두 번째 주행을 시작한 뒤 장애물 생성 조건을 확인하기 전 최소 대기 시간입니다.")]
    [Min(0f)]
    public float minimumRunBeforeObstacle = 0.2f;

    [Tooltip("장애물 위치의 진행률보다 이 값만큼 앞서 장애물을 생성합니다. 예: 장애물 0.55, lead 0.15 -> 로봇 진행률 0.40에서 생성")]
    [Range(0f, 0.4f)]
    public float obstacleSpawnLeadProgress = 0.15f;

    [Tooltip("기준 경로 생성 주행 제한 시간입니다. 초과하면 같은 시나리오를 재시도합니다.")]
    [Min(1f)]
    public float baselineRunTimeout = 60f;

    [Tooltip("두 번째 주행 제한 시간입니다. 초과하면 실패 처리합니다.")]
    [Min(1f)]
    public float obstacleRunTimeout = 60f;

    [Tooltip("주행 시작 후 이 시간이 지난 뒤 agent가 멈춰 있으면 조기 실패로 판단합니다.")]
    [Min(0.1f)]
    public float stoppedAgentDetectionDelay = 1.0f;

    [Tooltip("trial 종료 후 다음 trial 시작까지 대기 시간입니다.")]
    [Min(0f)]
    public float nextTrialDelay = 0.5f;

    [Header("Agent Control")]
    [Tooltip("관리형 평가 중 GO1Agent의 기존 evaluationMode를 끄고 새 목표 자동 순환을 차단합니다.")]
    public bool forceManagedEvaluationMode = true;

    [Tooltip("기준 경로 생성과 장애물 주행 중 Time.timeScale입니다.")]
    [Range(0.1f, 20f)]
    public float evaluationTimeScale = 1f;

    [Tooltip("C3에서 장애물 생성 직후 기준 경로 잠금을 해제하고 NavMesh를 즉시 다시 계산합니다.")]
    public bool replanImmediatelyForC3 = true;

    [Header("Result Logging")]
    public bool writeResultCsv = true;
    public string resultFolderName = "GO1_C2C3_Evaluation";
    public string resultFileName = "c2c3_evaluation_summary.csv";
    public bool debugLogs = true;

    [Header("Paper Statistics")]
    [Tooltip("전체 trial 완료 시 mean±std 통계 요약 CSV를 자동 생성합니다.")]
    public bool writeStatsSummary = true;

    [Tooltip("통계 요약 CSV 파일 이름입니다.")]
    public string statsSummaryFileName = "c2c3_stats_summary.csv";

    [Header("Completion")]
    [Tooltip("전체 trial 완료 시 Unity Editor Play Mode를 종료합니다.")]
    public bool stopPlayModeWhenFinished = false;

    public EvaluationPhase Phase => phase;
    public bool IsRunning => evaluationRunning && phase != EvaluationPhase.Finished && phase != EvaluationPhase.Stopped;
    public bool IsObstacleRun => phase == EvaluationPhase.ObstacleRun;
    public IReadOnlyList<Vector3> BaselinePath => baselinePath;

    // ─── 논문 Table 1용 per-trial 누적 데이터 ───
    private struct TrialMetrics
    {
        public bool   success;
        public string reason;
        public float  duration;
        public float  distance;
        public float  finalError;
        public bool   replanApplied;
        public float  replanDelay;
        public int    collisionCount;
        public int    obstacleCollisionCount;
        public int    stuckCount;
        public int    replanCount;
        public float  travelDistance;
        public float  accumulatedReplanTime;
        public float  placementLatency;
    }
    private readonly List<TrialMetrics> trialMetricsList = new List<TrialMetrics>();

    private EvaluationPhase phase = EvaluationPhase.Idle;
    private bool evaluationRunning;
    private int baselineRetryCount;

    private Vector3 savedStartPosition;
    private Quaternion savedStartRotation;
    private Vector3 savedGoalPosition;
    private readonly List<Vector3> baselinePath = new List<Vector3>();

    private bool obstacleSpawnRequested;
    private bool obstaclePlaced;
    private bool obstaclePlacementFailed;
    private bool replanApplied;
    private int totalScenarioSkips;
    private float baselineRunStartTime;
    private float obstacleRunStartTime;
    private float obstaclePlacedTime = -1f;
    private float replanAppliedTime = -1f;

    // 장애물 배치 호출→성공 콜백까지의 실제(벽시계) 시간. NavMeshObstacle carving 적용 대기가
    // Time.timeScale과 무관한 실제 시간 기준이라, 이 지연도 같은 기준으로 재야 의미가 있다.
    // "재탐색 계산 자체"가 아니라 "가상환경에 장애물이 실제로 반영되기까지"의 비용을 측정한다.
    private float spawnCallRealtime = -1f;
    private float lastPlacementLatency = -1f;
    private float obstacleRunDistance;
    private Vector3 previousAgentPosition;
    private string lastPlacementMessage = string.Empty;

    // ── Paired mode ──────────────────────────────────────────────────────────
    private enum PairedPhase { None, WaitingForC1, WaitingForC2, WaitingForC3 }
    private PairedPhase pairedRunPhase = PairedPhase.None;
    private bool pairedRunCompleted;

    private struct RunSnapshot
    {
        public bool   success;
        public string reason;
        public float  duration;
        public float  distance;
        public float  finalError;
        public bool   replanApplied;
        public float  replanDelay;
        public int    collisions;
        public int    obstacleCollisions;
        public int    stuckCount;
        public int    replanCount;
        public float  placementLatency;
    }
    private RunSnapshot pairC1;
    private RunSnapshot pairC2;
    private RunSnapshot pairC3;
    private readonly List<TrialMetrics> c2TrialMetricsList = new List<TrialMetrics>();
    private readonly List<TrialMetrics> c1TrialMetricsList = new List<TrialMetrics>();
    // ─────────────────────────────────────────────────────────────────────────

    private Coroutine transitionRoutine;
    private string csvPath;
    private bool originalAgentEvaluationMode;
    private int originalMaxEvaluationTrials;
    private bool originalStopPlayModeWhenComplete;
    private bool agentSettingsCaptured;

    private void Awake()
    {
        ResolveReferences();
        ConfigureForManagedEvaluation();
    }

    private void Start()
    {
        ResolveReferences();
        ConfigureForManagedEvaluation();

        if (autoStart)
            StartCoroutine(AutoStartWhenReadyRoutine());
    }

    private IEnumerator AutoStartWhenReadyRoutine()
    {
        float startTime = Time.realtimeSinceStartup;

        while (Time.realtimeSinceStartup - startTime < autoStartReferenceWait)
        {
            ResolveReferences();
            SubscribeObstacleEvents();

            if (ValidateReferences(out _))
            {
                StartEvaluation();
                yield break;
            }

            yield return null;
        }

        ResolveReferences();
        if (!ValidateReferences(out string error))
            Debug.LogError("[C2C3EvaluationManager] 자동 시작 실패: " + error, this);
    }

    private void OnEnable()
    {
        ResolveReferences();
        SubscribeObstacleEvents();
    }

    private void OnDisable()
    {
        UnsubscribeObstacleEvents();
    }

    private void Update()
    {
        if (!IsRunning || agent == null)
            return;

        if (phase == EvaluationPhase.BaselineRun)
        {
            float baselineElapsed = Time.time - baselineRunStartTime;

            if (baselineElapsed >= stoppedAgentDetectionDelay && !agent.IsMoving())
            {
                HandleBaselineFailure("baseline_agent_stopped");
                return;
            }

            if (baselineElapsed >= baselineRunTimeout)
            {
                HandleBaselineFailure("baseline_run_timeout");
                return;
            }

            return;
        }

        if (phase != EvaluationPhase.ObstacleRun)
            return;

        Vector3 currentPosition = agent.transform.position;
        obstacleRunDistance += HorizontalDistance(previousAgentPosition, currentPosition);
        previousAgentPosition = currentPosition;

        float elapsed = Time.time - obstacleRunStartTime;

        if (elapsed >= stoppedAgentDetectionDelay && !agent.IsMoving())
        {
            CompleteCurrentTrial(false, "obstacle_agent_stopped");
            return;
        }

        if (!obstacleSpawnRequested && elapsed >= minimumRunBeforeObstacle)
        {
            float obstacleProgress = obstacleScenarioManager != null
                ? obstacleScenarioManager.GetCurrentScenarioPathProgress()
                : 0.55f;

            float triggerProgress = Mathf.Clamp01(obstacleProgress - obstacleSpawnLeadProgress);
            float currentProgress = CalculatePathProgressXZ(baselinePath, currentPosition);

            if (currentProgress >= triggerProgress)
                RequestObstacleSpawn();
        }

        if (elapsed >= obstacleRunTimeout)
            CompleteCurrentTrial(false, "obstacle_run_timeout");
    }

    private void ResolveReferences()
    {
        if (trainingManager == null)
            trainingManager = FindFirstObjectByType<TrainingManager>();

        if (obstacleScenarioManager == null)
            obstacleScenarioManager = FindFirstObjectByType<DynamicObstacleScenarioManager>();

        // TrainingManager가 씬 시작 시 Agent_0 같은 런타임 인스턴스를 생성하는 경우,
        // Inspector에 연결된 원본 go1 오브젝트보다 생성된 에이전트를 우선 사용합니다.
        if (autoBindRuntimeAgent && (!evaluationRunning || agent == null || !agent.gameObject.activeInHierarchy))
        {
            GO1Agent runtimeAgent = FindBestRuntimeAgent();
            if (runtimeAgent != null)
                agent = runtimeAgent;
        }

        if (agent == null)
            agent = FindFirstObjectByType<GO1Agent>();

        BindAgentDependencies();
    }

    private GO1Agent FindBestRuntimeAgent()
    {
        GO1Agent[] agents = FindObjectsByType<GO1Agent>(
            FindObjectsInactive.Exclude,
            FindObjectsSortMode.None
        );

        GO1Agent best = null;
        int bestScore = int.MinValue;

        foreach (GO1Agent candidate in agents)
        {
            if (candidate == null || !candidate.gameObject.activeInHierarchy)
                continue;

            int score = 0;

            // TrainingManager가 생성하는 기본 이름을 우선합니다.
            if (candidate.gameObject.name.StartsWith("Agent_", StringComparison.OrdinalIgnoreCase))
                score += 1000;

            // 이미 목표가 할당된 에이전트는 실제 평가 인스턴스일 가능성이 높습니다.
            if (candidate.target != null)
                score += 500;

            if (candidate.enabled)
                score += 100;

            if (trainingManager != null && candidate.trainingManager == trainingManager)
                score += 50;

            if (candidate == agent)
                score += 10;

            if (score > bestScore)
            {
                bestScore = score;
                best = candidate;
            }
        }

        return best;
    }

    private void BindAgentDependencies()
    {
        if (agent == null)
            return;

        GO1PathPlanner runtimePathPlanner = agent.GetComponent<GO1PathPlanner>();
        if (runtimePathPlanner == null)
        {
            runtimePathPlanner = agent.gameObject.AddComponent<GO1PathPlanner>();
            Debug.LogWarning(
                "[C2C3EvaluationManager] 런타임 GO1Agent에 GO1PathPlanner가 없어 자동 추가했습니다: " +
                agent.gameObject.name,
                agent
            );
        }

        pathPlanner = runtimePathPlanner;

        GO1ReplanController runtimeReplanController = agent.GetComponent<GO1ReplanController>();
        if (runtimeReplanController == null)
        {
            runtimeReplanController = agent.gameObject.AddComponent<GO1ReplanController>();
            Debug.LogWarning(
                "[C2C3EvaluationManager] 런타임 GO1Agent에 GO1ReplanController가 없어 자동 추가했습니다: " +
                agent.gameObject.name,
                agent
            );
        }

        runtimeReplanController.EnsureReferences(agent, pathPlanner);
        agent.c2c3EvaluationManager = this;

        if (agent.trainingManager == null && trainingManager != null)
            agent.trainingManager = trainingManager;

        if (trainingManager == null && agent.trainingManager != null)
            trainingManager = agent.trainingManager;

        if (obstacleScenarioManager != null)
        {
            obstacleScenarioManager.agent = agent;
            obstacleScenarioManager.pathPlanner = pathPlanner;
            obstacleScenarioManager.replanController = runtimeReplanController;
        }
    }

    private void ConfigureForManagedEvaluation()
    {
        if (agent == null)
            return;

        if (forceManagedEvaluationMode)
        {
            if (!agentSettingsCaptured)
            {
                originalAgentEvaluationMode = agent.evaluationMode;
                originalMaxEvaluationTrials = agent.maxEvaluationTrials;
                originalStopPlayModeWhenComplete = agent.stopPlayModeWhenEvaluationComplete;
                agentSettingsCaptured = true;
            }

            // OnEpisodeBegin의 자동 목표 순환을 사용하지 않고 이 관리자가 직접 흐름을 제어합니다.
            agent.evaluationMode = false;
            agent.maxEvaluationTrials = 0;
            agent.stopPlayModeWhenEvaluationComplete = false;
        }

        ApplyConditionToAgentAndScenarioManager();
    }

    private void ApplyConditionToAgentAndScenarioManager(bool resetScenario = true)
    {
        if (agent != null)
        {
            agent.enableRuntimeReplanning = true;
            agent.enableObstacleTriggeredReplan = condition == EvaluationCondition.C3_REPLAN;
            agent.experimentConditionId = condition.ToString();
            agent.experimentMethodName = "Unity_C2C3_Paired_Evaluation";
        }

        if (obstacleScenarioManager != null)
        {
            obstacleScenarioManager.condition = condition == EvaluationCondition.C3_REPLAN
                ? DynamicObstacleScenarioManager.ExperimentCondition.C3_REPLAN
                : DynamicObstacleScenarioManager.ExperimentCondition.C2_NO_REPLAN;

            obstacleScenarioManager.autoRunEachMission = false;
            obstacleScenarioManager.spawnTrigger = DynamicObstacleScenarioManager.SpawnTriggerMode.Manual;
            obstacleScenarioManager.advanceScenarioAfterMission = false;
            obstacleScenarioManager.currentScenarioIndex = currentTrialIndex;

            if (resetScenario)
                obstacleScenarioManager.ResetCurrentScenario();
        }
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

    [ContextMenu("Start C2/C3 Evaluation")]
    public void StartEvaluation()
    {
        ResolveReferences();
        ConfigureForManagedEvaluation();
        SubscribeObstacleEvents();

        if (!ValidateReferences(out string error))
        {
            Debug.LogError("[C2C3EvaluationManager] " + error, this);
            return;
        }

        StopTransitionRoutine();
        evaluationRunning = true;
        phase = EvaluationPhase.PreparingBaseline;
        currentTrialIndex = 0;
        currentSetIndex = 0;
        baselineRetryCount = 0;
        totalScenarioSkips = 0;
        trialMetricsList.Clear();
        c2TrialMetricsList.Clear();
        c1TrialMetricsList.Clear();
        pairedRunPhase = PairedPhase.None;
        pairedRunCompleted = false;
        Time.timeScale = evaluationTimeScale;
        ApplyCurrentSetSeed();

        InitializeCsv();
        ApplyConditionToAgentAndScenarioManager();
        transitionRoutine = StartCoroutine(BeginNewTrialRoutine());
    }

    [ContextMenu("Stop C2/C3 Evaluation")]
    public void StopEvaluation()
    {
        evaluationRunning = false;
        phase = EvaluationPhase.Stopped;
        StopTransitionRoutine();

        if (agent != null)
            agent.StopManagedEvaluationRun(true);

        if (obstacleScenarioManager != null)
            obstacleScenarioManager.ResetCurrentScenario();

        RestoreAgentSettings();

        if (debugLogs)
            Debug.Log("[C2C3EvaluationManager] 평가를 정지했습니다.", this);
    }

    [ContextMenu("Restart From Trial 0")]
    public void RestartFromFirstTrial()
    {
        StopEvaluation();
        currentTrialIndex = 0;
        StartEvaluation();
    }

    private IEnumerator BeginNewTrialRoutine()
    {
        phase = EvaluationPhase.PreparingBaseline;
        obstacleSpawnRequested = false;
        obstaclePlaced = false;
        replanApplied = false;
        obstaclePlacedTime = -1f;
        replanAppliedTime = -1f;
        spawnCallRealtime = -1f;
        lastPlacementLatency = -1f;
        obstacleRunDistance = 0f;
        lastPlacementMessage = string.Empty;
        baselinePath.Clear();

        if (obstacleScenarioManager != null)
        {
            obstacleScenarioManager.currentScenarioIndex = currentTrialIndex;
            obstacleScenarioManager.ResetCurrentScenario();
        }

        yield return null;

        if (!PrepareScenarioStartAndGoal(0, out string error))
        {
            WriteResultRow(false, "scenario_prepare_failed:" + error, 0f, 0f);
            AdvanceAfterTrial();
            transitionRoutine = null;
            yield break;
        }

        baselineRetryCount = 0;

        if (useNavMeshPathDirectly)
        {
            yield return StartCoroutine(PlaceObstacleThenRunRoutine());
        }
        else
        {
            BeginBaselineRun();
        }
        transitionRoutine = null;
    }

    private bool PrepareScenarioStartAndGoal(int retryAttempt, out string error)
    {
        error = string.Empty;

        Vector3 startPosition;
        if (generateScenarioWithTrainingManager && trainingManager != null)
        {
            // trial 전용 시드로 재시드하는 오버로드를 쓴다 — C1/C2/C3가 각각 별도 세션으로
            // 돌아도 같은 trial 번호는 항상 같은 시작/목표를 뽑아야 짝비교가 성립한다.
            startPosition = trainingManager.GetRandomStartPositionForTrial(currentTrialIndex, retryAttempt);
        }
        else if (fallbackStartPoint != null)
        {
            startPosition = fallbackStartPoint.position;
        }
        else if (agent.startPoint != null)
        {
            startPosition = agent.startPoint.position;
        }
        else
        {
            startPosition = agent.transform.position;
        }

        Quaternion startRotation = agent.transform.rotation;
        if (useDeterministicStartYaw)
        {
            System.Random random = new System.Random(startYawBaseSeed + currentTrialIndex);
            float yaw = (float)(random.NextDouble() * 360.0);
            startRotation = Quaternion.Euler(0f, yaw, 0f);
        }

        agent.SetManagedEvaluationPose(startPosition, startRotation);

        if (generateScenarioWithTrainingManager && trainingManager != null)
        {
            bool assigned = trainingManager.ResetGoalForAgentForTrial(agent, currentTrialIndex, retryAttempt);
            if (!assigned)
            {
                error = "TrainingManager.ResetGoalForAgent returned false";
                return false;
            }
        }

        if (agent.target == null)
        {
            error = "GO1Agent target is null";
            return false;
        }

        savedStartPosition = agent.transform.position;
        savedStartRotation = agent.transform.rotation;
        savedGoalPosition = agent.target.position;

        if (pathPlanner == null || !pathPlanner.HasCompletePath(savedStartPosition, savedGoalPosition))
        {
            error = "start-to-goal PathComplete check failed";
            return false;
        }

        if (agent != null)
        {
            string scenarioId = obstacleScenarioManager != null
                ? obstacleScenarioManager.GetCurrentScenarioId()
                : "S" + (currentTrialIndex + 1).ToString("D2");
            agent.experimentScenarioId = scenarioId;
        }

        return true;
    }

    private void BeginBaselineRun()
    {
        phase = EvaluationPhase.BaselineRun;
        baselineRunStartTime = Time.time;
        pathPlanner.ClearLockedPath();
        agent.BeginManagedEvaluationRun(
            savedStartPosition,
            savedStartRotation,
            savedGoalPosition,
            null,
            false,
            false
        );

        if (debugLogs)
        {
            Debug.Log(
                "[C2C3EvaluationManager] 기준 경로 생성 시작 | condition=" + condition +
                ", trial=" + (currentTrialIndex + 1) + "/" + totalTrials +
                ", start=" + savedStartPosition +
                ", goal=" + savedGoalPosition,
                this
            );
        }
    }

    /// <summary>
    /// GO1Agent가 목표 거리 안에 들어왔을 때 가장 먼저 호출합니다.
    /// true를 반환하면 GO1Agent의 기본 목표 갱신/EndEpisode 흐름을 실행하지 않습니다.
    /// </summary>
    public bool HandleAgentGoalReached(GO1Agent source)
    {
        if (!IsRunning || source != agent)
            return false;

        if (phase == EvaluationPhase.BaselineRun)
        {
            List<Vector3> snapshot = source.GetRecordedPathSnapshot(true);
            baselinePath.Clear();
            baselinePath.AddRange(snapshot);

            if (baselinePath.Count < 2)
            {
                HandleBaselineFailure("baseline_path_too_short");
                return true;
            }

            if (debugLogs)
            {
                Debug.Log(
                    "[C2C3EvaluationManager] 기준 경로 저장 완료 | points=" + baselinePath.Count +
                    ", length=" + CalculatePolylineLengthXZ(baselinePath).ToString("F2") + "m",
                    this
                );
            }

            source.StopManagedEvaluationRun(false);
            StopTransitionRoutine();
            transitionRoutine = StartCoroutine(BeginObstacleRunRoutine());
            return true;
        }

        if (phase == EvaluationPhase.ObstacleRun)
        {
            CompleteCurrentTrial(true, "goal_reached");
            return true;
        }

        return true;
    }

    /// <summary>
    /// GO1Agent의 SafeEndEpisode 직전에 호출됩니다.
    /// 관리형 평가 중이면 EndEpisode를 막고 이 관리자가 실패/완료를 처리합니다.
    /// </summary>
    public bool HandleAgentEpisodeEndRequest(GO1Agent source, bool success, string reason)
    {
        if (!IsRunning || source != agent)
            return false;

        if (phase == EvaluationPhase.BaselineRun)
        {
            HandleBaselineFailure(string.IsNullOrEmpty(reason) ? "baseline_failed" : reason);
            return true;
        }

        if (phase == EvaluationPhase.ObstacleRun)
        {
            CompleteCurrentTrial(success, string.IsNullOrEmpty(reason) ? "obstacle_run_failed" : reason);
            return true;
        }

        return true;
    }

    private void HandleBaselineFailure(string reason)
    {
        if (phase != EvaluationPhase.BaselineRun)
            return;

        phase = EvaluationPhase.PreparingBaseline;
        agent.StopManagedEvaluationRun(true);
        baselineRetryCount++;

        if (baselineRetryCount <= maxBaselineRetries)
        {
            if (debugLogs)
            {
                Debug.LogWarning(
                    "[C2C3EvaluationManager] 기준 경로 생성 실패, 같은 시나리오 재시도 | " +
                    "retry=" + baselineRetryCount + "/" + maxBaselineRetries +
                    ", reason=" + reason,
                    this
                );
            }

            StopTransitionRoutine();
            transitionRoutine = StartCoroutine(RestartBaselineAfterDelay());
            return;
        }

        WriteResultRow(false, "baseline_failed:" + reason, 0f, 0f);
        AdvanceAfterTrial();
    }

    private IEnumerator RestartBaselineAfterDelay()
    {
        if (resetDelay > 0f)
            yield return new WaitForSeconds(resetDelay);

        BeginBaselineRun();
        transitionRoutine = null;
    }

    private IEnumerator BeginObstacleRunRoutine()
    {
        if (!useNavMeshPathDirectly)
        {
            // 기존 흐름: 기준 주행 후 장애물 포함 재주행
            phase = EvaluationPhase.PreparingObstacleRun;

            if (obstacleScenarioManager != null)
                obstacleScenarioManager.ResetCurrentScenario();

            if (resetDelay > 0f)
                yield return new WaitForSeconds(resetDelay);

            obstacleSpawnRequested = false;
            obstaclePlaced = false;
            replanApplied = false;
            obstaclePlacedTime = -1f;
            replanAppliedTime = -1f;
            spawnCallRealtime = -1f;
            lastPlacementLatency = -1f;
            obstacleRunDistance = 0f;

            // C2/C3 모두 두 번째 주행 시작 시에는 기준 경로를 잠급니다.
            // C3만 장애물이 실제로 배치된 직후 잠금을 해제하여 재탐색합니다.
            // C1(RL 단독)은 전역 계획을 제공하지 않으므로 [시작점, 목표점] 직선만 잠급니다.
            agent.BeginManagedEvaluationRun(
                savedStartPosition,
                savedStartRotation,
                savedGoalPosition,
                condition == EvaluationCondition.C1_RL_ONLY_NO_PLAN
                    ? new List<Vector3> { savedStartPosition, savedGoalPosition }
                    : baselinePath,
                true,
                true
            );
        }
        else
        {
            // useNavMeshPathDirectly 흐름: 장애물 이미 배치됨
            obstacleRunDistance = 0f;

            if (condition == EvaluationCondition.C2_NO_REPLAN)
            {
                // C2: 원본 NavMesh 경로를 잠근 상태로 출발 → 장애물에 막혀 실패
                agent.BeginManagedEvaluationRun(
                    savedStartPosition,
                    savedStartRotation,
                    savedGoalPosition,
                    baselinePath,
                    true,
                    true
                );
            }
            else if (condition == EvaluationCondition.C1_RL_ONLY_NO_PLAN)
            {
                // C1(RL 단독): 전역 계획을 아예 제공하지 않는다. 잠긴 경로를
                // [시작점, 목표점] 직선 하나로 고정하면 에이전트의 경로 관측(corner)이
                // 항상 "목표 방향"만 가리키므로, 목표점을 단일 경유점으로 준 것과 같다.
                // 회피는 전적으로 16방향 레이 지역 관측에 맡겨진다.
                // 장애물은 위에서 C2/C3와 동일한 NavMesh 기준 경로에 이미 배치되어
                // 시나리오(시작/목표/장애물) 대응이 유지된다.
                agent.BeginManagedEvaluationRun(
                    savedStartPosition,
                    savedStartRotation,
                    savedGoalPosition,
                    new List<Vector3> { savedStartPosition, savedGoalPosition },
                    true,
                    true
                );
            }
            else
            {
                // C3: 잠금 없이 출발 후 pathPlanner에 재탐색 경로를 설정
                agent.BeginManagedEvaluationRun(
                    savedStartPosition,
                    savedStartRotation,
                    savedGoalPosition,
                    null,
                    false,
                    true
                );

                // BeginManagedEvaluationRun이 ClearLockedPath()를 호출한 뒤 재탐색합니다.
                bool replanned = pathPlanner.CalculatePath(savedStartPosition, savedGoalPosition);

                if (!replanned || pathPlanner.IsCurrentPathInvalidOrPartial)
                {
                    if (debugLogs)
                        Debug.LogWarning($"[C2C3EvaluationManager] C3 재탐색 실패 | trial={currentTrialIndex + 1}", this);
                    CompleteCurrentTrial(false, "c3_replan_failed_after_obstacle");
                    transitionRoutine = null;
                    yield break;
                }

                replanApplied = true;
                replanAppliedTime = Time.time;

                // GO1PathPlanner를 직접 조작하는 재탐색이라 GO1Agent 자신의 재탐색 집계
                // (experimentReplanCount)는 이 호출 없이는 절대 올라가지 않는다 — replan_count가
                // 항상 0으로 기록되던 버그의 원인.
                if (agent != null)
                    agent.ReplanBeginExperiment(obstacleScenarioManager != null ? obstacleScenarioManager.SpawnedObstacle : null);

                if (debugLogs)
                    Debug.Log($"[C2C3EvaluationManager] C3 재탐색 완료 → 시작점부터 우회 경로로 출발 | trial={currentTrialIndex + 1}", this);
            }
        }

        obstacleRunStartTime = Time.time;
        previousAgentPosition = agent.transform.position;
        phase = EvaluationPhase.ObstacleRun;

        if (debugLogs)
        {
            Debug.Log(
                "[C2C3EvaluationManager] 장애물 평가 주행 시작 | condition=" + condition +
                ", scenario=" + (obstacleScenarioManager != null ? obstacleScenarioManager.GetCurrentScenarioId() : "unknown") +
                ", lockedPathPoints=" + baselinePath.Count,
                this
            );
        }

        transitionRoutine = null;
    }

    /// <summary>
    /// useNavMeshPathDirectly 모드 전용 코루틴입니다.
    /// NavMesh 경로 계산 → 장애물 배치 → BeginObstacleRunRoutine 순으로 진행합니다.
    /// </summary>
    private IEnumerator PlaceObstacleThenRunRoutine()
    {
        phase = EvaluationPhase.PreparingObstacleRun;

        if (obstacleScenarioManager == null)
        {
            Debug.LogWarning("[C2C3EvaluationManager] obstacleScenarioManager가 null입니다.", this);
            WriteResultRow(false, "obstacle_manager_null", 0f, 0f);
            AdvanceAfterTrial();
            yield break;
        }

        // 외부 루프: 시작/목표 위치를 새로 잡는 재시도
        // 내부 루프: 현재 위치에서 유효한 장애물 시나리오를 찾는 재시도
        const int maxPositionRetries = 5;
        const int maxObstacleRetries = 8;
        int areaMask = pathPlanner != null ? pathPlanner.areaMask : NavMesh.AllAreas;
        bool validSetupFound = false;

        for (int posRetry = 0; posRetry <= maxPositionRetries; posRetry++)
        {
            // 첫 번째 시도를 제외하고 시작/목표 위치 재설정
            if (posRetry > 0)
            {
                yield return null;
                if (!PrepareScenarioStartAndGoal(posRetry, out string sgError))
                {
                    if (debugLogs)
                        Debug.LogWarning(
                            $"[C2C3EvaluationManager] 새 시작/목표 위치 설정 실패 " +
                            $"| posRetry={posRetry} error={sgError}",
                            this
                        );
                    continue;
                }
            }

            // 현재 위치에서 NavMesh 경로 계산
            NavMeshPath navPath = new NavMeshPath();
            bool pathOk = NavMesh.CalculatePath(savedStartPosition, savedGoalPosition, areaMask, navPath);
            if (!pathOk || navPath.status != NavMeshPathStatus.PathComplete || navPath.corners.Length < 2)
            {
                if (debugLogs)
                    Debug.LogWarning(
                        $"[C2C3EvaluationManager] NavMesh 경로 계산 실패 → 위치 재시도 " +
                        $"| posRetry={posRetry} status={navPath.status}",
                        this
                    );
                continue;
            }

            baselinePath.Clear();
            baselinePath.AddRange(navPath.corners);

            // 내부 루프: 현재 경로에서 유효한 장애물 위치 탐색
            bool obstacleFound = false;
            for (int obsRetry = 0; obsRetry <= maxObstacleRetries; obsRetry++)
            {
                obstacleSpawnRequested = true;
                obstaclePlaced = false;
                obstaclePlacementFailed = false;

                int scenarioIdx = currentTrialIndex + totalScenarioSkips;
                obstacleScenarioManager.currentScenarioIndex = scenarioIdx;
                obstacleScenarioManager.ResetCurrentScenario();
                spawnCallRealtime = Time.realtimeSinceStartup;
                obstacleScenarioManager.SpawnObstacleForEvaluationPath(baselinePath, false);

                // 배치 완료 대기 — 성공/실패 콜백 즉시 탈출.
                // carving 대기(carvingApplyWait 등)는 실제 시간 기준(WaitForSecondsRealtime)인데
                // 이 타임아웃을 Time.time(배속 영향받음)으로 재면 고배속에서 carving이 끝나기도
                // 전에 타임아웃이 먼저 나버린다. 같은 실제 시간 기준으로 맞춘다.
                float waitStart = Time.realtimeSinceStartup;
                while (!obstaclePlaced && !obstaclePlacementFailed
                       && Time.realtimeSinceStartup - waitStart < obstacleFirstPlacementTimeout)
                    yield return null;

                if (!obstaclePlaced)
                {
                    obstacleScenarioManager.ResetCurrentScenario();
                    totalScenarioSkips++;
                    if (debugLogs)
                        Debug.LogWarning(
                            $"[C2C3EvaluationManager] 장애물 배치 실패 " +
                            $"| reason={lastPlacementMessage} obsRetry={obsRetry} posRetry={posRetry}",
                            this
                        );
                    continue;
                }

                // NavMeshObstacle 카빙 적용 대기
                yield return null;
                yield return null;

                // 배치 후 우회 경로 존재 확인
                NavMeshPath postPath = new NavMeshPath();
                bool postOk = NavMesh.CalculatePath(savedStartPosition, savedGoalPosition, areaMask, postPath);
                if (!postOk || postPath.status != NavMeshPathStatus.PathComplete || postPath.corners.Length < 2)
                {
                    obstacleScenarioManager.ResetCurrentScenario();
                    totalScenarioSkips++;
                    if (debugLogs)
                        Debug.LogWarning(
                            $"[C2C3EvaluationManager] 장애물이 우회 경로까지 차단 " +
                            $"| obsRetry={obsRetry} posRetry={posRetry}",
                            this
                        );
                    continue;
                }

                obstacleFound = true;
                if (debugLogs)
                    Debug.Log(
                        $"[C2C3EvaluationManager] 유효한 시나리오 확보 " +
                        $"| scenario={scenarioIdx} posRetry={posRetry} obsRetry={obsRetry} " +
                        $"| trial={currentTrialIndex + 1}/{totalTrials}",
                        this
                    );
                break;
            }

            if (obstacleFound)
            {
                validSetupFound = true;
                break;
            }

            // 내부 루프 전부 실패 → 시작/목표 위치를 새로 잡아 재시도
            if (debugLogs)
                Debug.LogWarning(
                    $"[C2C3EvaluationManager] 현재 경로에서 유효한 장애물 위치 없음 → 위치 재설정 " +
                    $"| posRetry={posRetry}/{maxPositionRetries}",
                    this
                );
        }

        if (!validSetupFound)
        {
            if (debugLogs)
                Debug.LogWarning(
                    $"[C2C3EvaluationManager] 모든 위치/장애물 재시도 소진 → trial 스킵 " +
                    $"| trial={currentTrialIndex + 1}",
                    this
                );
            if (!pairedMode)
                WriteResultRow(false, "no_valid_scenario_found", 0f, 0f);
            AdvanceAfterTrial();
            yield break;
        }

        // 5. 에이전트 출발
        if (pairedMode)
        {
            yield return StartCoroutine(RunPairedConditionsRoutine());
        }
        else
        {
            if (placementToRunDelay > 0f)
                yield return new WaitForSeconds(placementToRunDelay);
            yield return StartCoroutine(BeginObstacleRunRoutine());
        }
    }

    private void RequestObstacleSpawn()
    {
        if (obstacleSpawnRequested || obstacleScenarioManager == null)
            return;

        obstacleSpawnRequested = true;
        spawnCallRealtime = Time.realtimeSinceStartup;
        obstacleScenarioManager.SpawnObstacleForEvaluationPath(baselinePath, false);

        if (debugLogs)
        {
            Debug.Log(
                "[C2C3EvaluationManager] 주행 중 장애물 생성 요청 | " +
                "robotProgress=" + CalculatePathProgressXZ(baselinePath, agent.transform.position).ToString("F3") +
                ", obstacleProgress=" + obstacleScenarioManager.GetCurrentScenarioPathProgress().ToString("F3"),
                this
            );
        }
    }

    private void OnObstaclePlacementFinished(bool success, GameObject obstacle, string message)
    {
        // useNavMeshPathDirectly 모드: PlaceObstacleThenRunRoutine이 폴링하는 플래그를 여기서 설정합니다.
        if (useNavMeshPathDirectly && phase == EvaluationPhase.PreparingObstacleRun)
        {
            lastPlacementMessage = message ?? string.Empty;
            if (success)
            {
                obstaclePlaced = true;
                obstaclePlacedTime = Time.time;
                lastPlacementLatency = spawnCallRealtime >= 0f
                    ? Time.realtimeSinceStartup - spawnCallRealtime
                    : -1f;
            }
            else
            {
                obstaclePlacementFailed = true;
            }
            return;
        }

        if (!IsRunning || phase != EvaluationPhase.ObstacleRun)
            return;

        lastPlacementMessage = message ?? string.Empty;

        if (!success)
        {
            CompleteCurrentTrial(false, "obstacle_placement_failed:" + lastPlacementMessage);
            return;
        }

        obstaclePlaced = true;
        obstaclePlacedTime = Time.time;
        lastPlacementLatency = spawnCallRealtime >= 0f
            ? Time.realtimeSinceStartup - spawnCallRealtime
            : -1f;

        if (condition == EvaluationCondition.C3_REPLAN && replanImmediatelyForC3)
        {
            pathPlanner.ClearLockedPath();
            bool calculated = pathPlanner.CalculatePath(agent.transform.position, savedGoalPosition);

            if (!calculated || pathPlanner.IsCurrentPathInvalidOrPartial)
            {
                CompleteCurrentTrial(false, "c3_replan_failed_after_obstacle");
                return;
            }

            replanApplied = true;
            replanAppliedTime = Time.time;

            // GO1PathPlanner를 직접 조작하는 재탐색이라 GO1Agent 자신의 재탐색 집계
            // (experimentReplanCount)는 이 호출 없이는 절대 올라가지 않는다.
            if (agent != null)
                agent.ReplanBeginExperiment(obstacle);

            if (debugLogs)
            {
                Debug.Log(
                    "[C2C3EvaluationManager] C3 재탐색 적용 | obstacle=" +
                    (obstacle != null ? obstacle.name : "null") +
                    ", delay=" + (replanAppliedTime - obstaclePlacedTime).ToString("F3") + "s",
                    this
                );
            }
        }
        else if (debugLogs)
        {
            Debug.Log(
                condition == EvaluationCondition.C1_RL_ONLY_NO_PLAN
                    ? "[C2C3EvaluationManager] C1(RL 단독) 경로 유지 | 직선 목표 경로 잠금 유지, 전역 계획/재탐색 없음"
                    : "[C2C3EvaluationManager] C2 경로 유지 | 기준 경로 잠금 유지, 전역 재탐색 없음",
                this
            );
        }
    }

    private void CompleteCurrentTrial(bool success, string reason)
    {
        if (!IsRunning || phase == EvaluationPhase.TrialCompleted)
            return;

        phase = EvaluationPhase.TrialCompleted;

        float duration = obstacleRunStartTime > 0f
            ? Mathf.Max(0f, Time.time - obstacleRunStartTime)
            : 0f;
        float finalError = agent != null && agent.target != null
            ? HorizontalDistance(agent.transform.position, agent.target.position)
            : -1f;

        // trial 완료 직전에 지표를 스냅샷 — FinishManagedEvaluationTrial이 내부 카운터를 초기화하기 전
        int snapshotCollisions         = agent != null ? agent.GetActiveTrialCollisionCount()         : 0;
        int snapshotObstacleCollisions = agent != null ? agent.GetActiveTrialObstacleCollisionCount() : 0;
        int snapshotStuck              = agent != null ? agent.GetActiveTrialStuckCount()             : 0;
        int snapshotReplanCount        = agent != null ? agent.GetActiveTrialReplanCount()            : 0;
        float snapshotTravelDist       = agent != null ? agent.GetActiveTrialTravelDistance()         : 0f;
        float snapshotReplanTime       = agent != null ? agent.GetActiveTrialAccumulatedReplanTime()  : 0f;

        float replanDelay = obstaclePlacedTime >= 0f && replanAppliedTime >= 0f
            ? replanAppliedTime - obstaclePlacedTime
            : -1f;

        // ── Paired mode: 결과를 스냅샷에 저장하고 coroutine에 신호만 보냄 ──
        if (pairedMode && pairedRunPhase != PairedPhase.None)
        {
            RunSnapshot snap = new RunSnapshot
            {
                success            = success,
                reason             = reason,
                duration           = duration,
                distance           = obstacleRunDistance,
                finalError         = finalError,
                replanApplied      = replanApplied,
                replanDelay        = replanApplied && replanAppliedTime >= 0f && obstacleRunStartTime >= 0f
                                     ? replanAppliedTime - obstacleRunStartTime : -1f,
                collisions         = snapshotCollisions,
                obstacleCollisions = snapshotObstacleCollisions,
                stuckCount         = snapshotStuck,
                replanCount        = snapshotReplanCount,
                placementLatency   = lastPlacementLatency
            };

            if      (pairedRunPhase == PairedPhase.WaitingForC1) pairC1 = snap;
            else if (pairedRunPhase == PairedPhase.WaitingForC2) pairC2 = snap;
            else                                                  pairC3 = snap;

            if (agent != null)
            {
                agent.FinishManagedEvaluationTrial(success, reason);
                agent.StopManagedEvaluationRun(true);
            }

            pairedRunCompleted = true;

            if (debugLogs)
                Debug.Log(
                    $"[C2C3EvaluationManager] paired 단계 완료 | {pairedRunPhase} " +
                    $"success={success} reason={reason} duration={duration:F2}s finalError={finalError:F2}m",
                    this
                );
            return;
        }
        // ──────────────────────────────────────────────────────────────────────

        trialMetricsList.Add(new TrialMetrics
        {
            success                = success,
            reason                 = reason,
            duration               = duration,
            distance               = obstacleRunDistance,
            finalError             = finalError,
            replanApplied          = replanApplied,
            replanDelay            = replanDelay,
            collisionCount         = snapshotCollisions,
            obstacleCollisionCount = snapshotObstacleCollisions,
            stuckCount             = snapshotStuck,
            replanCount            = snapshotReplanCount,
            travelDistance         = snapshotTravelDist,
            accumulatedReplanTime  = snapshotReplanTime,
            placementLatency       = lastPlacementLatency
        });

        if (agent != null)
        {
            agent.FinishManagedEvaluationTrial(success, reason);
            agent.StopManagedEvaluationRun(true);
        }

        WriteResultRow(success, reason, duration, finalError,
            snapshotCollisions, snapshotObstacleCollisions, snapshotStuck, snapshotReplanCount);

        if (debugLogs)
        {
            Debug.Log(
                "[C2C3EvaluationManager] trial 완료 | condition=" + condition +
                ", trial=" + (currentTrialIndex + 1) + "/" + totalTrials +
                ", success=" + success +
                ", reason=" + reason +
                ", duration=" + duration.ToString("F2") + "s" +
                ", finalError=" + finalError.ToString("F2") + "m",
                this
            );
        }

        AdvanceAfterTrial();
    }

    private void AdvanceAfterTrial()
    {
        StopTransitionRoutine();

        if (obstacleScenarioManager != null)
            obstacleScenarioManager.ResetCurrentScenario();

        currentTrialIndex++;

        // 세트 내 trial이 끝났으면 다음 세트로 전환
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

            totalScenarioSkips = 0;
            ApplyCurrentSetSeed();

            if (debugLogs)
                Debug.Log(
                    $"[C2C3EvaluationManager] 세트 전환 | set={currentSetIndex + 1}/{totalSets} " +
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

        ApplyConditionToAgentAndScenarioManager();
        transitionRoutine = StartCoroutine(BeginNewTrialRoutine());
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Paired mode coroutine
    // ═══════════════════════════════════════════════════════════════════════

    private IEnumerator RunPairedConditionsRoutine()
    {
        if (placementToRunDelay > 0f)
            yield return new WaitForSeconds(placementToRunDelay);

        // ── 0. C1: 전역 계획 없이 RL 단독 (옵션, 같은 장애물) ─────────────
        // C2/C3보다 먼저 돌려도 장애물/시작/목표가 같으므로 순서는 결과에 영향 없다.
        if (pairedIncludeC1RlOnly)
        {
            condition = EvaluationCondition.C1_RL_ONLY_NO_PLAN;
            ApplyConditionToAgentAndScenarioManager(resetScenario: false); // 장애물 유지
            pairedRunPhase     = PairedPhase.WaitingForC1;
            pairedRunCompleted = false;
            obstacleRunDistance = 0f;
            replanApplied      = false;
            replanAppliedTime  = -1f;
            phase = EvaluationPhase.PreparingObstacleRun;

            yield return StartCoroutine(BeginObstacleRunRoutine());

            float c1Timeout = Time.time + obstacleRunTimeout + 5f;
            while (!pairedRunCompleted && Time.time < c1Timeout)
                yield return null;

            if (!pairedRunCompleted)
                ForceCompletePairedRun(false, "timeout");

            if (debugLogs)
                Debug.Log(
                    $"[C2C3EvaluationManager] C1(RL 단독) 완료 | trial={currentTrialIndex + 1} " +
                    $"success={pairC1.success} reason={pairC1.reason} duration={pairC1.duration:F2}s",
                    this
                );

            if (pairedIntraTrialDelay > 0f)
                yield return new WaitForSeconds(pairedIntraTrialDelay);
        }

        // ── 1. C2: 원본 경로 잠금 실행 ────────────────────────────────────
        condition = EvaluationCondition.C2_NO_REPLAN;
        ApplyConditionToAgentAndScenarioManager(resetScenario: false); // 장애물 유지
        pairedRunPhase    = PairedPhase.WaitingForC2;
        pairedRunCompleted = false;
        obstacleRunDistance = 0f;
        replanApplied     = false;
        replanAppliedTime = -1f;
        phase = EvaluationPhase.PreparingObstacleRun;

        yield return StartCoroutine(BeginObstacleRunRoutine());

        float c2Timeout = Time.time + obstacleRunTimeout + 5f;
        while (!pairedRunCompleted && Time.time < c2Timeout)
            yield return null;

        if (!pairedRunCompleted)
            ForceCompletePairedRun(false, "timeout");

        if (debugLogs)
            Debug.Log(
                $"[C2C3EvaluationManager] C2 완료 | trial={currentTrialIndex + 1} " +
                $"success={pairC2.success} reason={pairC2.reason} duration={pairC2.duration:F2}s",
                this
            );

        // ── 2. 전환 대기 (같은 장애물 유지) ───────────────────────────────
        if (pairedIntraTrialDelay > 0f)
            yield return new WaitForSeconds(pairedIntraTrialDelay);

        // ── 3. C3: 재탐색 실행 (장애물 그대로) ────────────────────────────
        condition = EvaluationCondition.C3_REPLAN;
        ApplyConditionToAgentAndScenarioManager(resetScenario: false); // 장애물 유지
        pairedRunPhase     = PairedPhase.WaitingForC3;
        pairedRunCompleted = false;
        obstacleRunDistance = 0f;
        replanApplied      = false;
        replanAppliedTime  = -1f;
        obstaclePlacedTime = Time.time; // C3 재탐색 지연을 런 시작 기준으로 측정
        phase = EvaluationPhase.PreparingObstacleRun;

        yield return StartCoroutine(BeginObstacleRunRoutine());

        float c3Timeout = Time.time + obstacleRunTimeout + 5f;
        while (!pairedRunCompleted && Time.time < c3Timeout)
            yield return null;

        if (!pairedRunCompleted)
            ForceCompletePairedRun(false, "timeout");

        if (debugLogs)
            Debug.Log(
                $"[C2C3EvaluationManager] C3 완료 | trial={currentTrialIndex + 1} " +
                $"success={pairC3.success} reason={pairC3.reason} duration={pairC3.duration:F2}s " +
                $"replanDelay={pairC3.replanDelay:F3}s",
                this
            );

        // ── 4. 결과 기록 ──────────────────────────────────────────────────
        pairedRunPhase = PairedPhase.None;
        trialMetricsList.Add(SnapshotToTrialMetrics(pairC3));
        c2TrialMetricsList.Add(SnapshotToTrialMetrics(pairC2));
        if (pairedIncludeC1RlOnly)
            c1TrialMetricsList.Add(SnapshotToTrialMetrics(pairC1));
        WritePairedResultRow();
        AdvanceAfterTrial();
    }

    private void ForceCompletePairedRun(bool success, string reason)
    {
        if (phase == EvaluationPhase.TrialCompleted) return;

        float duration   = obstacleRunStartTime > 0f ? Time.time - obstacleRunStartTime : 0f;
        float finalError = agent != null && agent.target != null
                           ? HorizontalDistance(agent.transform.position, agent.target.position) : -1f;

        RunSnapshot snap = new RunSnapshot
        {
            success            = success,
            reason             = reason,
            duration           = duration,
            distance           = obstacleRunDistance,
            finalError         = finalError,
            replanApplied      = replanApplied,
            replanDelay        = -1f,
            collisions         = agent != null ? agent.GetActiveTrialCollisionCount()         : 0,
            obstacleCollisions = agent != null ? agent.GetActiveTrialObstacleCollisionCount() : 0,
            stuckCount         = agent != null ? agent.GetActiveTrialStuckCount()             : 0,
            replanCount        = agent != null ? agent.GetActiveTrialReplanCount()            : 0,
            placementLatency   = lastPlacementLatency
        };

        if      (pairedRunPhase == PairedPhase.WaitingForC1) pairC1 = snap;
        else if (pairedRunPhase == PairedPhase.WaitingForC2) pairC2 = snap;
        else                                                  pairC3 = snap;

        if (agent != null)
        {
            agent.FinishManagedEvaluationTrial(success, reason);
            agent.StopManagedEvaluationRun(true);
        }

        phase = EvaluationPhase.TrialCompleted;
        pairedRunCompleted = true;
    }

    private TrialMetrics SnapshotToTrialMetrics(RunSnapshot s) => new TrialMetrics
    {
        success                = s.success,
        reason                 = s.reason,
        duration               = s.duration,
        distance               = s.distance,
        finalError             = s.finalError,
        replanApplied          = s.replanApplied,
        replanDelay            = s.replanDelay,
        collisionCount         = s.collisions,
        obstacleCollisionCount = s.obstacleCollisions,
        stuckCount             = s.stuckCount,
        replanCount            = s.replanCount,
        travelDistance         = s.distance,
        accumulatedReplanTime  = 0f,
        placementLatency       = s.placementLatency
    };

    private void WritePairedResultRow()
    {
        if (!writeResultCsv) return;
        InitializeCsv();

        GameObject obstacle = obstacleScenarioManager != null
            ? obstacleScenarioManager.SpawnedObstacle : null;
        Vector3 obstaclePosition = obstacle != null ? obstacle.transform.position : Vector3.zero;

        string scenarioId = obstacleScenarioManager != null
            ? obstacleScenarioManager.GetCurrentScenarioId()
            : "S" + (currentTrialIndex + 1).ToString("D2");

        string[] values =
        {
            Csv(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff", CultureInfo.InvariantCulture)),
            (currentSetIndex + 1).ToString(CultureInfo.InvariantCulture),
            GetCurrentSetSeed().ToString(CultureInfo.InvariantCulture),
            currentTrialIndex.ToString(CultureInfo.InvariantCulture),
            Csv(scenarioId),
            F(savedStartPosition.x), F(savedStartPosition.z),
            F(savedGoalPosition.x),  F(savedGoalPosition.z),
            baselinePath.Count.ToString(CultureInfo.InvariantCulture),
            F(CalculatePolylineLengthXZ(baselinePath)),
            obstacle != null ? F(obstaclePosition.x) : string.Empty,
            obstacle != null ? F(obstaclePosition.z) : string.Empty,
            // ── C1 (RL 단독, pairedIncludeC1RlOnly=false면 빈 값) ──
            pairedIncludeC1RlOnly ? (pairC1.success ? "1" : "0") : string.Empty,
            pairedIncludeC1RlOnly ? Csv(pairC1.reason) : "\"\"",
            pairedIncludeC1RlOnly ? F(pairC1.duration) : string.Empty,
            pairedIncludeC1RlOnly ? F(pairC1.distance) : string.Empty,
            pairedIncludeC1RlOnly ? F(pairC1.finalError) : string.Empty,
            pairedIncludeC1RlOnly ? pairC1.collisions.ToString(CultureInfo.InvariantCulture) : string.Empty,
            pairedIncludeC1RlOnly ? pairC1.obstacleCollisions.ToString(CultureInfo.InvariantCulture) : string.Empty,
            pairedIncludeC1RlOnly ? pairC1.stuckCount.ToString(CultureInfo.InvariantCulture) : string.Empty,
            // ── C2 ──
            pairC2.success ? "1" : "0",
            Csv(pairC2.reason),
            F(pairC2.duration),
            F(pairC2.distance),
            F(pairC2.finalError),
            pairC2.collisions.ToString(CultureInfo.InvariantCulture),
            pairC2.obstacleCollisions.ToString(CultureInfo.InvariantCulture),
            pairC2.stuckCount.ToString(CultureInfo.InvariantCulture),
            pairC2.replanCount.ToString(CultureInfo.InvariantCulture),
            F(pairC2.placementLatency),
            // ── C3 ──
            pairC3.success ? "1" : "0",
            Csv(pairC3.reason),
            F(pairC3.duration),
            F(pairC3.distance),
            F(pairC3.finalError),
            pairC3.replanApplied ? "1" : "0",
            F(pairC3.replanDelay),
            pairC3.collisions.ToString(CultureInfo.InvariantCulture),
            pairC3.obstacleCollisions.ToString(CultureInfo.InvariantCulture),
            pairC3.stuckCount.ToString(CultureInfo.InvariantCulture),
            pairC3.replanCount.ToString(CultureInfo.InvariantCulture),
            F(pairC3.placementLatency)
        };

        try
        {
            File.AppendAllText(csvPath, string.Join(",", values) + "\n",
                new UTF8Encoding(false));
        }
        catch (Exception e)
        {
            Debug.LogError("[C2C3EvaluationManager] paired CSV 쓰기 오류: " + e.Message, this);
        }

        if (debugLogs)
            Debug.Log(
                $"[C2C3EvaluationManager] paired row 기록 | trial={currentTrialIndex + 1} " +
                $"C2={pairC2.success}({pairC2.reason}) C3={pairC3.success}({pairC3.reason})",
                this
            );
    }

    // ═══════════════════════════════════════════════════════════════════════

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
            Debug.Log(
                $"[C2C3EvaluationManager] 시드 적용 | set={currentSetIndex + 1} seed={seed}",
                this
            );
    }

    private void FinishEvaluation()
    {
        evaluationRunning = false;
        phase = EvaluationPhase.Finished;

        if (agent != null)
            agent.StopManagedEvaluationRun(true);

        if (obstacleScenarioManager != null)
            obstacleScenarioManager.ResetCurrentScenario();

        RestoreAgentSettings();

        if (writeStatsSummary && trialMetricsList.Count > 0)
        {
            WriteStatsSummary();
            if (pairedMode && c2TrialMetricsList.Count > 0)
                WriteStatsSummaryForList(c2TrialMetricsList,
                    "c2_" + statsSummaryFileName,
                    EvaluationCondition.C2_NO_REPLAN);
            if (pairedMode && c1TrialMetricsList.Count > 0)
                WriteStatsSummaryForList(c1TrialMetricsList,
                    "c1_" + statsSummaryFileName,
                    EvaluationCondition.C1_RL_ONLY_NO_PLAN);
        }

        Debug.Log(
            "[C2C3EvaluationManager] 전체 평가 완료 | condition=" + condition +
            ", trials=" + totalTrials +
            ", csv=" + csvPath,
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

    // ─── 논문 Table 1: 30회 반복 평가 통계 요약 ───────────────────────────────
    [ContextMenu("Write Stats Summary Now")]
    public void WriteStatsSummary()
    {
        if (trialMetricsList.Count == 0)
        {
            Debug.LogWarning("[C2C3EvaluationManager] 통계 집계할 trial 데이터가 없습니다.", this);
            return;
        }
        WriteStatsSummaryForList(trialMetricsList, statsSummaryFileName,
            pairedMode ? EvaluationCondition.C3_REPLAN : condition);
    }

    private void WriteStatsSummaryForList(
        List<TrialMetrics> metrics, string fileName, EvaluationCondition cond)
    {
        InitializeCsv();
        if (string.IsNullOrEmpty(csvFolder))
        {
            string projectRoot = Directory.GetParent(Application.dataPath).FullName;
            csvFolder = Path.Combine(projectRoot, resultFolderName);
            Directory.CreateDirectory(csvFolder);
        }

        string statsPath = Path.Combine(csvFolder, fileName);

        int n = metrics.Count;
        int successCount = 0;
        var durations          = new List<float>(n);
        var distances          = new List<float>(n);
        var finalErrors        = new List<float>(n);
        var collisions         = new List<float>(n);
        var obstacleCollisions = new List<float>(n);
        var stuckCounts        = new List<float>(n);
        var replanCounts       = new List<float>(n);
        var replanDelays       = new List<float>(n);
        var travelDistances    = new List<float>(n);
        var replanTimes        = new List<float>(n);
        var placementLatencies = new List<float>(n);

        foreach (TrialMetrics t in metrics)
        {
            if (t.success) successCount++;
            durations.Add(t.duration);
            distances.Add(t.distance);
            finalErrors.Add(t.finalError >= 0f ? t.finalError : 0f);
            collisions.Add(t.collisionCount);
            obstacleCollisions.Add(t.obstacleCollisionCount);
            stuckCounts.Add(t.stuckCount);
            replanCounts.Add(t.replanCount);
            if (t.replanDelay >= 0f) replanDelays.Add(t.replanDelay);
            travelDistances.Add(t.travelDistance);
            replanTimes.Add(t.accumulatedReplanTime);
            if (t.placementLatency >= 0f) placementLatencies.Add(t.placementLatency);
        }

        float successRate = (float)successCount / n;

        var sb = new StringBuilder();
        sb.AppendLine("condition,n,metric,mean,std,min,median,max,success_rate");

        void AppendMetricRow(string metric, List<float> values)
        {
            if (values.Count == 0) return;
            float mean = ComputeMean(values);
            float std  = ComputeStd(values, mean);
            float min  = ComputeMin(values);
            float med  = ComputeMedian(values);
            float max  = ComputeMax(values);
            sb.AppendLine(string.Join(",", new[]
            {
                Csv(cond.ToString()),
                n.ToString(CultureInfo.InvariantCulture),
                Csv(metric),
                FS(mean), FS(std), FS(min), FS(med), FS(max),
                FS(successRate)
            }));
        }

        AppendMetricRow("success_rate_per_trial",       BuildBinaryList(metrics));
        AppendMetricRow("obstacle_run_duration_sec",    durations);
        AppendMetricRow("obstacle_run_distance_m",      distances);
        AppendMetricRow("travel_distance_m",            travelDistances);
        AppendMetricRow("final_goal_error_m",           finalErrors);
        AppendMetricRow("collision_count",              collisions);
        AppendMetricRow("obstacle_collision_count",     obstacleCollisions);
        AppendMetricRow("stuck_count",                  stuckCounts);
        AppendMetricRow("replan_count",                 replanCounts);
        AppendMetricRow("replan_accumulated_time_sec",  replanTimes);
        if (replanDelays.Count > 0)
            AppendMetricRow("replan_response_delay_sec", replanDelays);
        if (placementLatencies.Count > 0)
            AppendMetricRow("obstacle_placement_latency_sec", placementLatencies);

        File.WriteAllText(statsPath, sb.ToString(), new UTF8Encoding(true));

        Debug.Log(
            $"[C2C3EvaluationManager] 통계 요약 저장 | condition={cond} n={n} " +
            $"successRate={successRate:F3} path={statsPath}",
            this
        );
    }

    private List<float> BuildBinaryList(List<TrialMetrics> metrics)
    {
        var list = new List<float>(metrics.Count);
        foreach (var t in metrics)
            list.Add(t.success ? 1f : 0f);
        return list;
    }

    private float ComputeMean(List<float> v)
    {
        if (v.Count == 0) return 0f;
        double sum = 0;
        foreach (float x in v) sum += x;
        return (float)(sum / v.Count);
    }

    private float ComputeStd(List<float> v, float mean)
    {
        if (v.Count < 2) return 0f;
        double sq = 0;
        foreach (float x in v) sq += (x - mean) * (x - mean);
        return (float)Math.Sqrt(sq / (v.Count - 1));
    }

    private float ComputeMin(List<float> v)
    {
        float m = float.MaxValue;
        foreach (float x in v) if (x < m) m = x;
        return m;
    }

    private float ComputeMax(List<float> v)
    {
        float m = float.MinValue;
        foreach (float x in v) if (x > m) m = x;
        return m;
    }

    private float ComputeMedian(List<float> v)
    {
        if (v.Count == 0) return 0f;
        var sorted = new List<float>(v);
        sorted.Sort();
        int mid = sorted.Count / 2;
        return sorted.Count % 2 == 0
            ? (sorted[mid - 1] + sorted[mid]) * 0.5f
            : sorted[mid];
    }

    private string FS(float value)
    {
        return value.ToString("F6", CultureInfo.InvariantCulture);
    }

    private bool ValidateReferences(out string error)
    {
        if (agent == null)
        {
            error = "GO1Agent 참조가 없습니다.";
            return false;
        }

        if (pathPlanner == null)
        {
            error = "GO1PathPlanner 참조가 없습니다.";
            return false;
        }

        if (obstacleScenarioManager == null)
        {
            error = "DynamicObstacleScenarioManager 참조가 없습니다.";
            return false;
        }

        if (generateScenarioWithTrainingManager && trainingManager == null)
        {
            error = "TrainingManager를 이용하도록 설정했지만 참조가 없습니다.";
            return false;
        }

        // TrainingManager를 사용하는 경우 target은 trial 준비 단계의
        // ResetGoalForAgent(agent)에서 할당되므로 여기서 미리 실패시키지 않습니다.
        if (!generateScenarioWithTrainingManager && agent.target == null)
        {
            error = "TrainingManager를 사용하지 않으며 GO1Agent target도 없습니다.";
            return false;
        }

        error = string.Empty;
        return true;
    }

    private string csvFolder;

    private void InitializeCsv()
    {
        if (!writeResultCsv)
            return;

        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        csvFolder = Path.Combine(projectRoot, resultFolderName);
        Directory.CreateDirectory(csvFolder);
        csvPath = Path.Combine(csvFolder, resultFileName);

        if (!File.Exists(csvPath))
        {
            string header = pairedMode
                ? "timestamp,set_id,set_seed,trial_index,scenario_id," +
                  "start_x,start_z,goal_x,goal_z,baseline_path_points,baseline_path_length," +
                  "obstacle_x,obstacle_z," +
                  "c1_success,c1_reason,c1_duration,c1_distance,c1_final_error," +
                  "c1_collisions,c1_obstacle_collisions,c1_stuck," +
                  "c2_success,c2_reason,c2_duration,c2_distance,c2_final_error," +
                  "c2_collisions,c2_obstacle_collisions,c2_stuck,c2_replan_count,c2_placement_latency_sec," +
                  "c3_success,c3_reason,c3_duration,c3_distance,c3_final_error," +
                  "c3_replan_applied,c3_replan_delay," +
                  "c3_collisions,c3_obstacle_collisions,c3_stuck,c3_replan_count,c3_placement_latency_sec\n"
                : "timestamp,condition,set_id,set_seed,trial_index,scenario_id,success,reason," +
                  "start_x,start_z,goal_x,goal_z,baseline_path_points,baseline_path_length," +
                  "obstacle_spawned,obstacle_x,obstacle_z,obstacle_run_duration," +
                  "obstacle_run_distance,final_goal_error,replan_applied,replan_delay," +
                  "collision_count,obstacle_collision_count,stuck_count,replan_count," +
                  "placement_latency_sec,placement_message\n";
            File.WriteAllText(csvPath, header, new UTF8Encoding(true));
        }
    }

    private void WriteResultRow(
        bool success, string reason, float duration, float finalError,
        int collisions = 0, int obstacleCollisions = 0, int stuckEvents = 0, int replanCount = 0)
    {
        if (!writeResultCsv)
            return;

        InitializeCsv();

        GameObject obstacle = obstacleScenarioManager != null
            ? obstacleScenarioManager.SpawnedObstacle
            : null;
        Vector3 obstaclePosition = obstacle != null ? obstacle.transform.position : Vector3.zero;
        float replanDelay = obstaclePlacedTime >= 0f && replanAppliedTime >= 0f
            ? replanAppliedTime - obstaclePlacedTime
            : -1f;

        string scenarioId = obstacleScenarioManager != null
            ? obstacleScenarioManager.GetCurrentScenarioId()
            : "S" + (currentTrialIndex + 1).ToString("D2");

        string[] values =
        {
            Csv(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff", CultureInfo.InvariantCulture)),
            Csv(condition.ToString()),
            (currentSetIndex + 1).ToString(CultureInfo.InvariantCulture),
            GetCurrentSetSeed().ToString(CultureInfo.InvariantCulture),
            currentTrialIndex.ToString(CultureInfo.InvariantCulture),
            Csv(scenarioId),
            success ? "1" : "0",
            Csv(reason),
            F(savedStartPosition.x),
            F(savedStartPosition.z),
            F(savedGoalPosition.x),
            F(savedGoalPosition.z),
            baselinePath.Count.ToString(CultureInfo.InvariantCulture),
            F(CalculatePolylineLengthXZ(baselinePath)),
            obstaclePlaced ? "1" : "0",
            obstacle != null ? F(obstaclePosition.x) : string.Empty,
            obstacle != null ? F(obstaclePosition.z) : string.Empty,
            F(duration),
            F(obstacleRunDistance),
            F(finalError),
            replanApplied ? "1" : "0",
            F(replanDelay),
            collisions.ToString(CultureInfo.InvariantCulture),
            obstacleCollisions.ToString(CultureInfo.InvariantCulture),
            stuckEvents.ToString(CultureInfo.InvariantCulture),
            replanCount.ToString(CultureInfo.InvariantCulture),
            F(lastPlacementLatency),
            Csv(lastPlacementMessage)
        };

        File.AppendAllText(csvPath, string.Join(",", values) + "\n", new UTF8Encoding(true));
    }

    private void RestoreAgentSettings()
    {
        if (!forceManagedEvaluationMode || agent == null)
            return;

        agent.evaluationMode = originalAgentEvaluationMode;
        agent.maxEvaluationTrials = originalMaxEvaluationTrials;
        agent.stopPlayModeWhenEvaluationComplete = originalStopPlayModeWhenComplete;
    }

    private void StopTransitionRoutine()
    {
        if (transitionRoutine == null)
            return;

        StopCoroutine(transitionRoutine);
        transitionRoutine = null;
    }

    private float CalculatePathProgressXZ(IReadOnlyList<Vector3> path, Vector3 position)
    {
        if (path == null || path.Count < 2)
            return 0f;

        float totalLength = CalculatePolylineLengthXZ(path);
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

    private float CalculatePolylineLengthXZ(IReadOnlyList<Vector3> path)
    {
        if (path == null || path.Count < 2)
            return 0f;

        float length = 0f;
        for (int i = 0; i < path.Count - 1; i++)
            length += HorizontalDistance(path[i], path[i + 1]);

        return length;
    }

    private float HorizontalDistance(Vector3 a, Vector3 b)
    {
        a.y = 0f;
        b.y = 0f;
        return Vector3.Distance(a, b);
    }

    private string F(float value)
    {
        return value.ToString("0.######", CultureInfo.InvariantCulture);
    }

    private string Csv(string value)
    {
        if (value == null)
            return string.Empty;

        string escaped = value.Replace("\"", "\"\"");
        return "\"" + escaped + "\"";
    }
}
