using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// C2_NO_REPLAN / C3_REPLAN 비교 실험을 위한 동적 장애물 시나리오 관리자입니다.
///
/// 처리 순서
/// 1) GO1Agent가 실제 GO1에 보낼 경로를 확정할 때까지 대기
/// 2) 확정된 경로의 앞쪽 후보 지점에 장애물 배치
/// 3) 기존 전송 경로가 실제로 차단되는지 확인
/// 4) 장애물 반영 후에도 현재 위치에서 목표까지 완전한 우회 경로가 존재하는지 확인
/// 5) 유효한 경우에만 GO1Agent.OnRuntimeObstacleUpdated() 호출
/// 6) C2는 차단 이벤트만 기록하고 기존 경로 유지
/// 7) C3는 GO1ReplanController가 PATH_CANCEL 후 새 경로 생성
///
/// 중요:
/// - 이 컴포넌트는 GO1Agent, GO1PathPlanner, GO1ReplanController와 같은
///   Assembly-CSharp 안에 두는 것을 권장합니다.
/// - C2와 C3는 같은 baseRandomSeed, 같은 trial index, 같은 시작/목표 조건을 사용해야 합니다.
/// </summary>
[DefaultExecutionOrder(-200)]
[DisallowMultipleComponent]
public class DynamicObstacleScenarioManager : MonoBehaviour
{
    public enum ExperimentCondition
    {
        C2_NO_REPLAN,
        C3_REPLAN
    }

    public enum SpawnTriggerMode
    {
        /// <summary>실제 GO1의 state_change=true 확인 후 장애물을 생성합니다.</summary>
        AfterRealPathFollowing,

        /// <summary>경로 명령이 전송된 시점부터 생성 조건을 확인합니다.</summary>
        AfterPathCommandSent,

        /// <summary>ContextMenu 또는 SpawnObstacleForCurrentPath()를 호출할 때 생성합니다.</summary>
        Manual
    }

    public enum PlacementMode
    {
        /// <summary>전체 전송 경로의 일정 진행률 지점에 배치합니다.</summary>
        FixedPathProgress,

        /// <summary>현재 로봇 위치에서 경로를 따라 일정 거리 앞에 배치합니다.</summary>
        DistanceAheadFromRobot
    }

    [Serializable]
    public class ScenarioPreset
    {
        [Tooltip("논문 로그에 기록할 시나리오 ID입니다.")]
        public string scenarioId = "S01";

        [Range(0.1f, 0.9f)]
        [Tooltip("FixedPathProgress 모드에서 사용할 경로 진행률입니다.")]
        public float pathProgress = 0.55f;

        [Min(0.5f)]
        [Tooltip("DistanceAheadFromRobot 모드에서 현재 위치로부터 경로를 따라 이동할 거리입니다.")]
        public float distanceAhead = 3.0f;

        [Tooltip("경로 중심으로부터 좌우 오프셋입니다. 0이면 경로 중심에 배치합니다.")]
        public float lateralOffset = 0f;

        [Tooltip("생성할 장애물의 로컬 스케일입니다.")]
        public Vector3 obstacleScale = new Vector3(0.48f, 0.72f, 0.48f);

        [Tooltip("같은 C2/C3 쌍에서 동일하게 유지할 난수 시드입니다.")]
        public int randomSeed = 121;
    }

    [Header("Core References")]
    public GO1Agent agent;
    public GO1PathPlanner pathPlanner;
    public GO1ReplanController replanController;

    [Tooltip("장애물로 사용할 Prefab입니다. Collider가 없으면 BoxCollider를 자동 추가합니다.")]
    public GameObject obstaclePrefab;

    [Tooltip("생성된 장애물을 정리할 부모 Transform입니다. 비워두면 이 오브젝트 아래에 생성합니다.")]
    public Transform obstacleParent;

    [Header("Experiment Condition")]
    public ExperimentCondition condition = ExperimentCondition.C3_REPLAN;
    public SpawnTriggerMode spawnTrigger = SpawnTriggerMode.AfterRealPathFollowing;
    public PlacementMode placementMode = PlacementMode.FixedPathProgress;

    [Tooltip("시작 시 GO1Agent의 condition ID와 재탐색 플래그를 자동 설정합니다.")]
    public bool applyConditionToAgent = true;

    [Tooltip("경로가 새로 전송될 때마다 한 번 자동 실행합니다.")]
    public bool autoRunEachMission = true;

    [Tooltip("장애물 생성 전 추가 대기 시간입니다. 실제 GO1이 출발한 직후 너무 가까이 생성되는 것을 방지합니다.")]
    [Min(0f)]
    public float spawnDelayAfterTrigger = 0.25f;

    [Header("Scenario Sequence")]
    [Tooltip("Inspector에 직접 정의한 시나리오 목록을 사용합니다.")]
    public bool usePresetList = true;

    public List<ScenarioPreset> scenarioPresets = new List<ScenarioPreset>
    {
        new ScenarioPreset()
    };

    [Tooltip("프리셋을 사용하지 않을 때 S01~S30을 생성하는 기준 시드입니다.")]
    public int baseRandomSeed = 121;

    [Tooltip("프리셋을 사용하지 않을 때 생성할 전체 시나리오 수입니다.")]
    [Min(1)]
    public int generatedScenarioCount = 30;

    [Range(0.15f, 0.8f)]
    public float generatedMinPathProgress = 0.35f;

    [Range(0.2f, 0.9f)]
    public float generatedMaxPathProgress = 0.70f;

    [Tooltip("현재 실행할 시나리오 인덱스입니다. C2와 C3 시작 시 모두 0으로 맞춥니다.")]
    [Min(0)]
    public int currentScenarioIndex = 0;

    [Tooltip("미션 종료 후 다음 시나리오 인덱스로 자동 증가합니다.")]
    public bool advanceScenarioAfterMission = true;

    [Header("Obstacle Placement")]
    [Tooltip("장애물 Prefab의 local Z축을 경로 진행 방향과 맞춥니다.")]
    public bool alignObstacleWithPath = true;

    [Tooltip("NavMesh 표면에서 장애물 중심을 띄울 높이입니다.")]
    public float obstacleGroundOffset = 0f;

    [Tooltip("생성 장애물에 적용할 Unity Layer입니다. -1이면 Prefab의 Layer를 유지합니다.")]
    [Range(-1, 31)]
    public int generatedObstacleLayer = -1;

    [Tooltip("Collider가 없을 때 자동으로 BoxCollider를 추가합니다.")]
    public bool addBoxColliderIfMissing = true;

    [Tooltip("NavMeshObstacle이 없을 때 자동 추가하고 carving을 활성화합니다.")]
    public bool configureNavMeshObstacle = true;

    [Tooltip("동적 생성 장애물의 NavMesh carving 설정입니다.")]
    public bool carveOnlyStationary = true;

    [Tooltip("후보 위치를 NavMesh 위로 보정하는 최대 거리입니다.")]
    [Min(0.1f)]
    public float navMeshSampleRadius = 1.0f;

    [Tooltip("장애물이 현재 로봇과 최소한 이 거리 이상 떨어져야 합니다.")]
    [Min(0f)]
    public float minDistanceFromRobot = 1.5f;

    [Tooltip("장애물이 목표와 최소한 이 거리 이상 떨어져야 합니다.")]
    [Min(0f)]
    public float minDistanceFromTarget = 1.0f;

    [Header("Validity Check")]
    [Tooltip("NavMeshObstacle carving 반영을 기다리는 시간입니다.")]
    [Min(0f)]
    public float carvingApplyWait = 0.35f;

    [Tooltip("잘못된 후보를 제거한 뒤 NavMesh 복구를 기다리는 시간입니다.")]
    [Min(0f)]
    public float carvingRemovalWait = 0.20f;

    [Tooltip("기준 위치 주변에서 시도할 최대 후보 수입니다.")]
    [Range(1, 20)]
    public int maxPlacementAttempts = 9;

    [Tooltip("후보가 실패할 때 경로 진행률 또는 전방 거리를 바꿀 간격입니다.")]
    [Min(0.05f)]
    public float candidateStep = 0.07f;

    [Tooltip("새 NavMesh 경로와 장애물 경계 사이에 확보할 최소 여유 거리입니다.")]
    [Min(0f)]
    public float alternatePathClearance = 0.15f;

    [Tooltip("우회 경로가 기존 경로보다 지나치게 길면 후보를 거부합니다. 0이면 제한하지 않습니다.")]
    [Min(0f)]
    public float maxAlternatePathLengthRatio = 2.5f;

    [Header("Mission Cleanup")]
    [Tooltip("실제 경로가 종료되면 생성 장애물을 제거합니다.")]
    public bool cleanupObstacleWhenMissionEnds = true;

    [Tooltip("새 미션이 시작되기 전 이전 장애물을 자동 제거합니다.")]
    public bool cleanupBeforeNewMission = true;

    [Header("Debug")]
    public bool debugLogs = true;
    public bool drawPlacementGizmos = true;

    public event Action<bool, GameObject, string> ObstaclePlacementFinished;

    private GameObject spawnedObstacle;
    private Coroutine spawnRoutine;
    private bool spawnedThisMission;

    // C2C3EvaluationManager가 실제 GO1 전송 경로 대신 기준 경로를 직접 넘길 때 사용합니다.
    private List<Vector3> pendingEvaluationPath;
    private bool pendingNotifyAgentRuntimeObstacle = true;
    private bool previousPathCommandSent;
    private bool previousMissionBusy;
    private bool missionObserved;
    private int activeScenarioIndex = -1;

    private Vector3 lastCandidatePosition;
    private Vector3 lastCandidateDirection = Vector3.forward;
    private bool lastCandidateValid;

    public GameObject SpawnedObstacle => spawnedObstacle;
    public bool HasSpawnedThisMission => spawnedThisMission;
    public bool IsBusy => spawnRoutine != null;

    public float GetCurrentScenarioPathProgress()
    {
        ScenarioPreset scenario = GetScenario(currentScenarioIndex);
        return scenario != null ? scenario.pathProgress : 0.55f;
    }

    public string GetCurrentScenarioId()
    {
        ScenarioPreset scenario = GetScenario(currentScenarioIndex);
        return scenario != null ? scenario.scenarioId : "S" + (currentScenarioIndex + 1).ToString("D2");
    }

    public int GetCurrentScenarioSeed()
    {
        ScenarioPreset scenario = GetScenario(currentScenarioIndex);
        return scenario != null ? scenario.randomSeed : baseRandomSeed + currentScenarioIndex;
    }

    private void Awake()
    {
        ResolveReferences();
        ApplyConditionSettings();
    }

    private void Start()
    {
        ResolveReferences();
        ApplyConditionSettings();
    }

    private void OnDisable()
    {
        StopSpawnRoutine();
    }

    private void OnDestroy()
    {
        DestroySpawnedObstacleImmediateSafe();
    }

    private void Update()
    {
        ResolveReferences();

        if (agent == null)
            return;

        bool pathCommandSent = agent.HasRealGo1PathCommandSent();
        bool missionBusy = agent.IsMissionBusy();

        // 새로운 실제 경로 명령의 상승 에지를 새 미션 시작으로 간주합니다.
        if (pathCommandSent && !previousPathCommandSent)
        {
            missionObserved = true;
            spawnedThisMission = false;

            if (cleanupBeforeNewMission)
                DestroySpawnedObstacle();

            if (autoRunEachMission && spawnTrigger != SpawnTriggerMode.Manual)
                TryStartAutomaticSpawn();
        }

        // 경로 명령은 이미 있었지만 real path 활성화를 기다리는 모드입니다.
        if (autoRunEachMission &&
            spawnTrigger == SpawnTriggerMode.AfterRealPathFollowing &&
            pathCommandSent &&
            agent.IsRealPathFollowing() &&
            !spawnedThisMission &&
            spawnRoutine == null)
        {
            TryStartAutomaticSpawn();
        }

        // 관측한 미션이 종료된 경우 정리하고 다음 시나리오로 이동합니다.
        if (missionObserved && previousMissionBusy && !missionBusy)
        {
            HandleMissionEnded();
        }

        previousPathCommandSent = pathCommandSent;
        previousMissionBusy = missionBusy;
    }

    private void ResolveReferences()
    {
        if (agent == null)
            agent = GetComponent<GO1Agent>();

        if (agent == null)
            agent = FindFirstObjectByType<GO1Agent>();

        if (pathPlanner == null && agent != null)
            pathPlanner = agent.GetComponent<GO1PathPlanner>();

        if (replanController == null && agent != null)
            replanController = agent.GetComponent<GO1ReplanController>();

        if (obstacleParent == null)
            obstacleParent = transform;
    }

    private void ApplyConditionSettings()
    {
        if (!applyConditionToAgent || agent == null)
            return;

        agent.enableRuntimeReplanning = true;
        agent.enableObstacleTriggeredReplan = condition == ExperimentCondition.C3_REPLAN;
        agent.experimentConditionId = condition.ToString();
        agent.experimentMethodName = "MLAgents_NavMesh_ClosedLoop";

        ScenarioPreset scenario = GetScenario(currentScenarioIndex);
        if (scenario != null)
        {
            agent.experimentScenarioId = scenario.scenarioId;
            agent.experimentFallbackRandomSeed = scenario.randomSeed;
        }
    }

    private void TryStartAutomaticSpawn()
    {
        if (spawnedThisMission || spawnRoutine != null)
            return;

        if (!IsSpawnTriggerSatisfied())
            return;

        spawnRoutine = StartCoroutine(SpawnForCurrentPathRoutine());
    }

    private bool IsSpawnTriggerSatisfied()
    {
        if (agent == null)
            return false;

        switch (spawnTrigger)
        {
            case SpawnTriggerMode.AfterRealPathFollowing:
                return agent.IsRealPathFollowing();

            case SpawnTriggerMode.AfterPathCommandSent:
                return agent.HasRealGo1PathCommandSent();

            case SpawnTriggerMode.Manual:
                return true;

            default:
                return false;
        }
    }

    /// <summary>
    /// 현재 전송 경로를 기준으로 장애물 생성을 수동 요청합니다.
    /// </summary>
    [ContextMenu("Spawn Obstacle For Current Path")]
    public void SpawnObstacleForCurrentPath()
    {
        ResolveReferences();
        ApplyConditionSettings();

        if (spawnRoutine != null)
        {
            if (debugLogs)
                Debug.LogWarning("[DynamicObstacleScenarioManager] 이미 장애물 배치 작업이 실행 중입니다.", this);
            return;
        }

        spawnRoutine = StartCoroutine(SpawnForCurrentPathRoutine());
    }

    /// <summary>
    /// Unity C2/C3 평가에서 기준 경로를 직접 지정하여 장애물을 생성합니다.
    /// notifyAgentRuntimeObstacle=false이면 실제 GO1용 PATH_CANCEL 재탐색 콜백은 호출하지 않습니다.
    /// </summary>
    public void SpawnObstacleForEvaluationPath(IReadOnlyList<Vector3> evaluationPath, bool notifyAgentRuntimeObstacle)
    {
        ResolveReferences();
        ApplyConditionSettings();

        if (evaluationPath == null || evaluationPath.Count < 2)
        {
            ObstaclePlacementFinished?.Invoke(false, null, "evaluation_path_too_short");
            return;
        }

        pendingEvaluationPath = new List<Vector3>(evaluationPath);
        pendingNotifyAgentRuntimeObstacle = notifyAgentRuntimeObstacle;
        SpawnObstacleForCurrentPath();
    }

    private IEnumerator SpawnForCurrentPathRoutine()
    {
        if (spawnDelayAfterTrigger > 0f)
            yield return new WaitForSeconds(spawnDelayAfterTrigger);

        ResolveReferences();
        ApplyConditionSettings();

        if (!ValidateCoreReferences(out string referenceError))
        {
            Debug.LogError("[DynamicObstacleScenarioManager] " + referenceError, this);
            pendingEvaluationPath = null;
            pendingNotifyAgentRuntimeObstacle = true;
            ObstaclePlacementFinished?.Invoke(false, null, "reference_error:" + referenceError);
            spawnRoutine = null;
            yield break;
        }

        IReadOnlyList<Vector3> sourcePath = pendingEvaluationPath != null && pendingEvaluationPath.Count >= 2
            ? pendingEvaluationPath
            : agent.ReplanCurrentSentPath;
        bool notifyAgentRuntimeObstacle = pendingEvaluationPath != null
            ? pendingNotifyAgentRuntimeObstacle
            : true;

        if (sourcePath == null || sourcePath.Count < 2)
        {
            const string noPathReason = "source_path_missing";
            Debug.LogWarning(
                "[DynamicObstacleScenarioManager] 현재 전송 경로 또는 평가 기준 경로가 없어 장애물을 생성하지 못했습니다.",
                this
            );
            pendingEvaluationPath = null;
            pendingNotifyAgentRuntimeObstacle = true;
            ObstaclePlacementFinished?.Invoke(false, null, noPathReason);
            spawnRoutine = null;
            yield break;
        }

        // 재탐색이 시작되면 currentSentPath가 비워질 수 있으므로 복사본을 사용합니다.
        List<Vector3> originalPath = new List<Vector3>(sourcePath);
        pendingEvaluationPath = null;
        pendingNotifyAgentRuntimeObstacle = true;
        ScenarioPreset scenario = GetScenario(currentScenarioIndex);
        activeScenarioIndex = currentScenarioIndex;

        if (scenario == null)
        {
            Debug.LogError("[DynamicObstacleScenarioManager] 사용할 시나리오를 만들지 못했습니다.", this);
            ObstaclePlacementFinished?.Invoke(false, null, "scenario_missing");
            spawnRoutine = null;
            yield break;
        }

        agent.experimentScenarioId = scenario.scenarioId;
        agent.experimentFallbackRandomSeed = scenario.randomSeed;

        if (cleanupBeforeNewMission)
            DestroySpawnedObstacle();

        float originalPathLength = CalculatePolylineLength(originalPath);
        bool success = false;
        string lastFailure = "unknown";

        for (int attempt = 0; attempt < Mathf.Max(1, maxPlacementAttempts); attempt++)
        {
            if (!TryGetCandidate(
                    originalPath,
                    scenario,
                    attempt,
                    out Vector3 candidatePosition,
                    out Vector3 pathDirection,
                    out string candidateFailure))
            {
                lastFailure = candidateFailure;
                continue;
            }

            lastCandidatePosition = candidatePosition;
            lastCandidateDirection = pathDirection;
            lastCandidateValid = false;

            spawnedObstacle = CreateObstacle(
                candidatePosition,
                pathDirection,
                scenario,
                attempt
            );

            if (spawnedObstacle == null)
            {
                lastFailure = "obstacle_instantiation_failed";
                continue;
            }

            // NavMeshObstacle carving은 Unity 내부 비동기 작업(실제 프레임 기준)으로 처리된다.
            // Time.timeScale이 올라가면(빠른 평가 배속) WaitForSeconds는 실제 대기 시간이
            // 그만큼 줄어들어 carving이 끝나기 전에 검증을 시도할 수 있으므로, 실제 시간
            // 기준(WaitForSecondsRealtime)으로 대기해 배속과 무관하게 안정적으로 처리되게 한다.
            if (carvingApplyWait > 0f)
                yield return new WaitForSecondsRealtime(carvingApplyWait);
            else
                yield return null;

            bool valid = ValidatePlacedObstacle(
                spawnedObstacle,
                originalPath,
                originalPathLength,
                out string validationFailure,
                out float alternatePathLength
            );

            if (valid)
            {
                success = true;
                lastCandidateValid = true;
                spawnedThisMission = true;

                if (debugLogs)
                {
                    Debug.Log(
                        "[DynamicObstacleScenarioManager] 유효한 장애물 배치 완료 | " +
                        "condition=" + condition +
                        ", scenario=" + scenario.scenarioId +
                        ", attempt=" + (attempt + 1) +
                        ", position=" + candidatePosition +
                        ", altPathLength=" + alternatePathLength.ToString("F2") + "m",
                        this
                    );
                }

                // 실제 GO1 폐루프 실험에서는 agent 알림을 통해 PATH_CANCEL/재탐색을 실행합니다.
                // Unity C2/C3 정량평가에서는 EvaluationManager가 경로 잠금/해제를 직접 제어하므로
                // notifyAgentRuntimeObstacle=false로 호출합니다.
                if (notifyAgentRuntimeObstacle)
                    agent.OnRuntimeObstacleUpdated(spawnedObstacle);

                ObstaclePlacementFinished?.Invoke(true, spawnedObstacle, "valid_obstacle_placed");
                break;
            }

            lastFailure = validationFailure;

            if (debugLogs)
            {
                Debug.LogWarning(
                    "[DynamicObstacleScenarioManager] 장애물 후보 거부 | " +
                    "scenario=" + scenario.scenarioId +
                    ", attempt=" + (attempt + 1) +
                    ", reason=" + validationFailure +
                    ", position=" + candidatePosition,
                    this
                );
            }

            DestroySpawnedObstacle();

            // 위와 동일한 이유로 실제 시간 기준으로 대기한다.
            if (carvingRemovalWait > 0f)
                yield return new WaitForSecondsRealtime(carvingRemovalWait);
            else
                yield return null;
        }

        if (!success)
        {
            Debug.LogWarning(
                "[DynamicObstacleScenarioManager] 유효한 장애물 위치를 찾지 못했습니다 → 다음 시나리오로 전환. " +
                "scenario=" + scenario.scenarioId +
                ", lastReason=" + lastFailure,
                this
            );

            DestroySpawnedObstacle();
            ObstaclePlacementFinished?.Invoke(false, null, lastFailure);
        }

        spawnRoutine = null;
    }

    private bool ValidateCoreReferences(out string error)
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

        if (replanController == null)
        {
            error = "GO1ReplanController 참조가 없습니다.";
            return false;
        }

        if (obstaclePrefab == null)
        {
            error = "Obstacle Prefab이 지정되지 않았습니다.";
            return false;
        }

        if (agent.target == null)
        {
            error = "GO1Agent의 target이 지정되지 않았습니다.";
            return false;
        }

        error = string.Empty;
        return true;
    }

    private ScenarioPreset GetScenario(int index)
    {
        if (usePresetList && scenarioPresets != null && scenarioPresets.Count > 0)
        {
            int wrappedIndex = PositiveModulo(index, scenarioPresets.Count);
            ScenarioPreset preset = scenarioPresets[wrappedIndex];

            if (preset != null)
                return preset;
        }

        int count = Mathf.Max(1, generatedScenarioCount);
        int generatedIndex = PositiveModulo(index, count);
        System.Random random = new System.Random(baseRandomSeed + generatedIndex);

        float minProgress = Mathf.Min(generatedMinPathProgress, generatedMaxPathProgress);
        float maxProgress = Mathf.Max(generatedMinPathProgress, generatedMaxPathProgress);
        float progress = Mathf.Lerp(minProgress, maxProgress, (float)random.NextDouble());

        return new ScenarioPreset
        {
            scenarioId = "S" + (generatedIndex + 1).ToString("D2"),
            pathProgress = progress,
            distanceAhead = 2.5f + (float)random.NextDouble() * 1.5f,
            lateralOffset = 0f,
            obstacleScale = new Vector3(0.48f, 0.72f, 0.48f),
            randomSeed = baseRandomSeed + generatedIndex
        };
    }

    private bool TryGetCandidate(
        IReadOnlyList<Vector3> path,
        ScenarioPreset scenario,
        int attempt,
        out Vector3 candidatePosition,
        out Vector3 pathDirection,
        out string failureReason)
    {
        candidatePosition = Vector3.zero;
        pathDirection = Vector3.forward;
        failureReason = string.Empty;

        if (path == null || path.Count < 2)
        {
            failureReason = "path_too_short";
            return false;
        }

        float signedOffset = GetAlternatingAttemptOffset(attempt);
        bool foundPoint;

        if (placementMode == PlacementMode.FixedPathProgress)
        {
            float progress = Mathf.Clamp01(
                scenario.pathProgress + signedOffset * candidateStep
            );

            progress = Mathf.Clamp(progress, 0.08f, 0.92f);
            foundPoint = TryGetPointAtProgress(
                path,
                progress,
                out candidatePosition,
                out pathDirection
            );
        }
        else
        {
            float distance = Mathf.Max(
                0.5f,
                scenario.distanceAhead + signedOffset * candidateStep * 5f
            );

            foundPoint = TryGetPointAheadFromRobot(
                path,
                agent.transform.position,
                distance,
                out candidatePosition,
                out pathDirection
            );
        }

        if (!foundPoint)
        {
            failureReason = "candidate_point_not_found";
            return false;
        }

        pathDirection.y = 0f;
        if (pathDirection.sqrMagnitude < 0.0001f)
            pathDirection = Vector3.forward;
        else
            pathDirection.Normalize();

        Vector3 lateral = Vector3.Cross(Vector3.up, pathDirection).normalized;
        candidatePosition += lateral * scenario.lateralOffset;

        NavMeshHit navHit;
        if (!NavMesh.SamplePosition(
                candidatePosition,
                out navHit,
                Mathf.Max(0.1f, navMeshSampleRadius),
                pathPlanner.areaMask))
        {
            failureReason = "candidate_not_on_navmesh";
            return false;
        }

        candidatePosition = navHit.position + Vector3.up * obstacleGroundOffset;

        float robotDistance = HorizontalDistance(candidatePosition, agent.transform.position);
        if (robotDistance < minDistanceFromRobot)
        {
            failureReason = "too_close_to_robot";
            return false;
        }

        float targetDistance = HorizontalDistance(candidatePosition, agent.target.position);
        if (targetDistance < minDistanceFromTarget)
        {
            failureReason = "too_close_to_target";
            return false;
        }

        return true;
    }

    private GameObject CreateObstacle(
        Vector3 position,
        Vector3 pathDirection,
        ScenarioPreset scenario,
        int attempt)
    {
        Quaternion rotation = Quaternion.identity;

        if (alignObstacleWithPath && pathDirection.sqrMagnitude > 0.0001f)
            rotation = Quaternion.LookRotation(pathDirection.normalized, Vector3.up);

        GameObject obstacle = Instantiate(
            obstaclePrefab,
            position,
            rotation,
            obstacleParent != null ? obstacleParent : transform
        );

        if (obstacle == null)
            return null;

        obstacle.name =
            "EXP_" + condition + "_" + scenario.scenarioId + "_A" + (attempt + 1);
        obstacle.transform.localScale = scenario.obstacleScale;

        if (generatedObstacleLayer >= 0)
            SetLayerRecursively(obstacle, generatedObstacleLayer);

        Collider collider = obstacle.GetComponentInChildren<Collider>();
        if (collider == null && addBoxColliderIfMissing)
        {
            BoxCollider box = obstacle.AddComponent<BoxCollider>();
            box.center = Vector3.zero;
            box.size = Vector3.one;
            box.isTrigger = false;
            collider = box;
        }

        if (collider != null)
            collider.isTrigger = false;

        if (configureNavMeshObstacle)
        {
            NavMeshObstacle navObstacle = obstacle.GetComponent<NavMeshObstacle>();
            if (navObstacle == null)
                navObstacle = obstacle.AddComponent<NavMeshObstacle>();

            navObstacle.shape = NavMeshObstacleShape.Box;

            Bounds worldBounds = GetObstacleBounds(obstacle);
            Vector3 lossyScale = obstacle.transform.lossyScale;
            Vector3 safeScale = new Vector3(
                Mathf.Max(0.0001f, Mathf.Abs(lossyScale.x)),
                Mathf.Max(0.0001f, Mathf.Abs(lossyScale.y)),
                Mathf.Max(0.0001f, Mathf.Abs(lossyScale.z))
            );

            navObstacle.center = obstacle.transform.InverseTransformPoint(worldBounds.center);
            navObstacle.size = new Vector3(
                worldBounds.size.x / safeScale.x,
                worldBounds.size.y / safeScale.y,
                worldBounds.size.z / safeScale.z
            );
            navObstacle.carving = true;
            navObstacle.carveOnlyStationary = carveOnlyStationary;
        }

        return obstacle;
    }

    private bool ValidatePlacedObstacle(
        GameObject obstacle,
        IReadOnlyList<Vector3> originalPath,
        float originalPathLength,
        out string failureReason,
        out float alternatePathLength)
    {
        failureReason = string.Empty;
        alternatePathLength = 0f;

        if (obstacle == null)
        {
            failureReason = "obstacle_missing";
            return false;
        }

        Bounds bounds = GetObstacleBounds(obstacle);
        float obstacleRadius = Mathf.Max(bounds.extents.x, bounds.extents.z);
        float blockThreshold = obstacleRadius + Mathf.Max(0f, agent.pathBlockCheckRadius);

        float distanceToOriginalPath = DistancePointToPolylineXZ(
            bounds.center,
            originalPath
        );

        if (distanceToOriginalPath > blockThreshold)
        {
            failureReason = "does_not_block_original_path";
            return false;
        }

        NavMeshPath alternatePath = new NavMeshPath();
        bool calculated = NavMesh.CalculatePath(
            agent.transform.position,
            agent.target.position,
            pathPlanner.areaMask,
            alternatePath
        );

        if (!calculated ||
            alternatePath.status != NavMeshPathStatus.PathComplete ||
            alternatePath.corners == null ||
            alternatePath.corners.Length < 2)
        {
            failureReason = "all_routes_blocked_or_path_incomplete";
            return false;
        }

        alternatePathLength = CalculatePolylineLength(alternatePath.corners);

        if (maxAlternatePathLengthRatio > 0f && originalPathLength > 0.01f)
        {
            float ratio = alternatePathLength / originalPathLength;
            if (ratio > maxAlternatePathLengthRatio)
            {
                failureReason = "alternate_path_too_long_ratio_" + ratio.ToString("F2");
                return false;
            }
        }

        float distanceToAlternatePath = DistancePointToPolylineXZ(
            bounds.center,
            alternatePath.corners
        );

        float requiredClearance = obstacleRadius + alternatePathClearance;
        if (distanceToAlternatePath <= requiredClearance)
        {
            failureReason = "alternate_path_still_intersects_obstacle";
            return false;
        }

        return true;
    }

    private void HandleMissionEnded()
    {
        missionObserved = false;
        spawnedThisMission = false;
        activeScenarioIndex = -1;

        StopSpawnRoutine();

        if (cleanupObstacleWhenMissionEnds)
            DestroySpawnedObstacle();

        if (advanceScenarioAfterMission)
        {
            currentScenarioIndex++;
            ApplyConditionSettings();
        }

        if (debugLogs)
        {
            Debug.Log(
                "[DynamicObstacleScenarioManager] 미션 종료 처리 | nextScenarioIndex=" +
                currentScenarioIndex,
                this
            );
        }
    }

    [ContextMenu("Reset Current Scenario")]
    public void ResetCurrentScenario()
    {
        StopSpawnRoutine();
        DestroySpawnedObstacle();
        spawnedThisMission = false;
        missionObserved = false;
        activeScenarioIndex = -1;
        pendingEvaluationPath = null;
        pendingNotifyAgentRuntimeObstacle = true;
        ApplyConditionSettings();
    }

    [ContextMenu("Advance To Next Scenario")]
    public void AdvanceToNextScenario()
    {
        ResetCurrentScenario();
        currentScenarioIndex++;
        ApplyConditionSettings();
    }

    [ContextMenu("Return To First Scenario")]
    public void ReturnToFirstScenario()
    {
        ResetCurrentScenario();
        currentScenarioIndex = 0;
        ApplyConditionSettings();
    }

    [ContextMenu("Destroy Spawned Obstacle")]
    public void DestroySpawnedObstacle()
    {
        if (spawnedObstacle == null)
            return;

        GameObject target = spawnedObstacle;
        spawnedObstacle = null;

        if (Application.isPlaying)
            Destroy(target);
        else
            DestroyImmediate(target);
    }

    private void DestroySpawnedObstacleImmediateSafe()
    {
        if (spawnedObstacle == null)
            return;

        GameObject target = spawnedObstacle;
        spawnedObstacle = null;

        if (Application.isPlaying)
            Destroy(target);
        else
            DestroyImmediate(target);
    }

    private void StopSpawnRoutine()
    {
        if (spawnRoutine == null)
            return;

        StopCoroutine(spawnRoutine);
        spawnRoutine = null;
    }

    private bool TryGetPointAtProgress(
        IReadOnlyList<Vector3> path,
        float progress,
        out Vector3 point,
        out Vector3 direction)
    {
        point = Vector3.zero;
        direction = Vector3.forward;

        float totalLength = CalculatePolylineLength(path);
        if (totalLength < 0.01f)
            return false;

        return TryGetPointAtDistance(
            path,
            Mathf.Clamp01(progress) * totalLength,
            out point,
            out direction
        );
    }

    private bool TryGetPointAheadFromRobot(
        IReadOnlyList<Vector3> path,
        Vector3 robotPosition,
        float distanceAhead,
        out Vector3 point,
        out Vector3 direction)
    {
        point = Vector3.zero;
        direction = Vector3.forward;

        if (path == null || path.Count < 2)
            return false;

        int closestSegment = 0;
        float closestDistance = float.MaxValue;
        float distanceBeforeClosest = 0f;
        float accumulated = 0f;
        float projectionOnClosest = 0f;

        for (int i = 0; i < path.Count - 1; i++)
        {
            Vector3 a = Flatten(path[i]);
            Vector3 b = Flatten(path[i + 1]);
            Vector3 p = Flatten(robotPosition);
            Vector3 ab = b - a;
            float segmentLength = ab.magnitude;

            if (segmentLength < 0.001f)
                continue;

            float t = Mathf.Clamp01(Vector3.Dot(p - a, ab) / ab.sqrMagnitude);
            Vector3 projected = a + ab * t;
            float distance = Vector3.Distance(p, projected);

            if (distance < closestDistance)
            {
                closestDistance = distance;
                closestSegment = i;
                distanceBeforeClosest = accumulated;
                projectionOnClosest = t * segmentLength;
            }

            accumulated += segmentLength;
        }

        float distanceFromPathStart = distanceBeforeClosest + projectionOnClosest;
        float targetDistance = distanceFromPathStart + Mathf.Max(0f, distanceAhead);

        return TryGetPointAtDistance(path, targetDistance, out point, out direction);
    }

    private bool TryGetPointAtDistance(
        IReadOnlyList<Vector3> path,
        float targetDistance,
        out Vector3 point,
        out Vector3 direction)
    {
        point = Vector3.zero;
        direction = Vector3.forward;

        if (path == null || path.Count < 2)
            return false;

        float remaining = Mathf.Max(0f, targetDistance);

        for (int i = 0; i < path.Count - 1; i++)
        {
            Vector3 a = path[i];
            Vector3 b = path[i + 1];
            Vector3 segment = b - a;
            segment.y = 0f;
            float length = segment.magnitude;

            if (length < 0.001f)
                continue;

            if (remaining <= length)
            {
                float t = remaining / length;
                point = Vector3.Lerp(a, b, t);
                direction = segment.normalized;
                return true;
            }

            remaining -= length;
        }

        Vector3 finalSegment = path[path.Count - 1] - path[path.Count - 2];
        finalSegment.y = 0f;

        point = path[path.Count - 1];
        direction = finalSegment.sqrMagnitude > 0.0001f
            ? finalSegment.normalized
            : Vector3.forward;

        return true;
    }

    public static float CalculatePolylineLength(IReadOnlyList<Vector3> path)
    {
        if (path == null || path.Count < 2)
            return 0f;

        float length = 0f;
        for (int i = 0; i < path.Count - 1; i++)
            length += HorizontalDistance(path[i], path[i + 1]);

        return length;
    }

    public static float CalculatePolylineLength(Vector3[] path)
    {
        if (path == null || path.Length < 2)
            return 0f;

        float length = 0f;
        for (int i = 0; i < path.Length - 1; i++)
            length += HorizontalDistance(path[i], path[i + 1]);

        return length;
    }

    private float DistancePointToPolylineXZ(
        Vector3 point,
        IReadOnlyList<Vector3> path)
    {
        if (path == null || path.Count < 2)
            return float.MaxValue;

        float minimum = float.MaxValue;
        for (int i = 0; i < path.Count - 1; i++)
        {
            minimum = Mathf.Min(
                minimum,
                DistancePointToSegmentXZ(point, path[i], path[i + 1])
            );
        }

        return minimum;
    }

    private float DistancePointToPolylineXZ(
        Vector3 point,
        Vector3[] path)
    {
        if (path == null || path.Length < 2)
            return float.MaxValue;

        float minimum = float.MaxValue;
        for (int i = 0; i < path.Length - 1; i++)
        {
            minimum = Mathf.Min(
                minimum,
                DistancePointToSegmentXZ(point, path[i], path[i + 1])
            );
        }

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

    public static Bounds GetObstacleBounds(GameObject obstacle)
    {
        if (obstacle == null)
            return new Bounds(Vector3.zero, Vector3.zero);

        Collider[] colliders = obstacle.GetComponentsInChildren<Collider>();
        if (colliders != null && colliders.Length > 0)
        {
            Bounds combined = colliders[0].bounds;
            for (int i = 1; i < colliders.Length; i++)
                combined.Encapsulate(colliders[i].bounds);
            return combined;
        }

        Renderer[] renderers = obstacle.GetComponentsInChildren<Renderer>();
        if (renderers != null && renderers.Length > 0)
        {
            Bounds combined = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
                combined.Encapsulate(renderers[i].bounds);
            return combined;
        }

        return new Bounds(obstacle.transform.position, obstacle.transform.lossyScale);
    }

    private static float HorizontalDistance(Vector3 a, Vector3 b)
    {
        a.y = 0f;
        b.y = 0f;
        return Vector3.Distance(a, b);
    }

    private Vector3 Flatten(Vector3 value)
    {
        value.y = 0f;
        return value;
    }

    private float GetAlternatingAttemptOffset(int attempt)
    {
        if (attempt <= 0)
            return 0f;

        int magnitude = (attempt + 1) / 2;
        return attempt % 2 == 1 ? magnitude : -magnitude;
    }

    private int PositiveModulo(int value, int divisor)
    {
        if (divisor <= 0)
            return 0;

        int result = value % divisor;
        return result < 0 ? result + divisor : result;
    }

    private void SetLayerRecursively(GameObject root, int layer)
    {
        if (root == null)
            return;

        root.layer = layer;
        foreach (Transform child in root.transform)
            SetLayerRecursively(child.gameObject, layer);
    }

    private void OnDrawGizmosSelected()
    {
        if (!drawPlacementGizmos)
            return;

        Gizmos.color = lastCandidateValid ? Color.green : Color.yellow;
        Gizmos.DrawWireSphere(lastCandidatePosition, 0.25f);
        Gizmos.DrawLine(
            lastCandidatePosition,
            lastCandidatePosition + lastCandidateDirection.normalized
        );

        if (spawnedObstacle != null)
        {
            Gizmos.color = Color.red;
            Bounds bounds = GetObstacleBounds(spawnedObstacle);
            Gizmos.DrawWireCube(bounds.center, bounds.size);
        }
    }
}
