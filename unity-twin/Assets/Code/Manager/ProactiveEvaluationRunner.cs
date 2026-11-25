using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 가상 전용 짝지은 비교 실험 러너: 정지 후 재탐색(StopAndReplan) 대 정지 없는 경로 교체(NoStopSwap).
///
/// 한 trial (seed 하나) = 같은 시작점, 목표점, 장애물로 두 조건을 한 번씩 실행 (순서는 seed마다 교대).
/// 한 run 순서:
/// 1) 시작 pose로 순간이동, 목표 설정, 미션 시작 (ML-Agent가 기준 경로 생성)
/// 2) 가상 GO1이 기준 경로 재주행을 시작하면 시각 t0
/// 3) GO1이 장애물 예정 위치에서 spawnDistance 안으로 들어오면 장애물 등장 (360 카메라 인식 대용)
/// 4) 조건별 대응 → 목표 도착, 실패, 시간 초과까지 측정
/// 5) runs.csv 1행 + traj/run_XXXX.csv (10 Hz 궤적)
///
/// 장애물 위치는 ML 경로가 아니라 시작점→목표점 NavMesh 최단 경로에서 seed로 정하므로
/// 두 조건에서 같은 세계 좌표에 놓인다.
///
/// 사용: 빈 GameObject에 붙이고 Play → F9 시작, F10 중지 (또는 autoStart).
/// </summary>
[DisallowMultipleComponent]
public class ProactiveEvaluationRunner : MonoBehaviour
{
    [Header("References (비우면 자동 탐색)")]
    public GO1Agent agent;
    public GO1ProactivePathUpdater updater;

    [Header("Scenarios (startPoints가 있으면 그것, 없으면 자동 생성, 둘 다 없으면 Play 시작 pose와 agent.target 한 쌍)")]
    public Transform[] startPoints;
    public Transform[] goalPoints;
    [Tooltip("NavMesh에서 시작점/목표점 쌍을 이 개수만큼 자동으로 뽑습니다. 0이면 끔.")]
    public int autoScenarioCount = 10;
    [Tooltip("자동 생성 쌍의 NavMesh 경로 길이 범위(m).")]
    public Vector2 autoScenarioPathLength = new Vector2(5f, 9f);
    [Tooltip("자동 생성 점이 벽/가구 경계에서 떨어져야 하는 최소 거리(m).")]
    public float autoScenarioEdgeMargin = 0.35f;
    public int scenarioSeed = 777;

    [Header("Virtual robot")]
    [Tooltip("켜면 가상 GO1이 실제 로봇의 C++ 경로 추종기와 같은 식/값으로 움직입니다 (최대 0.22 m/s, 11.5도 이상 틀리면 제자리 회전).")]
    public bool realFollowerModel = true;
    [Tooltip("재주행 속도(m/s). 0이면 agent 기본값(moveSpeed × virtualPlanSpeedMultiplier).")]
    public float replaySpeed = 0.4f;
    [Tooltip("재주행 중간 웨이포인트 허용 오차(m). 0이면 agent 기본값(0.75).")]
    public float replayWaypointTolerance = 0.05f;

    [Header("Trials")]
    [Min(1)] public int trials = 30;
    public int baseSeed = 5000;
    public bool autoStart = false;
    public KeyCode startKey = KeyCode.F9;
    public KeyCode stopKey = KeyCode.F10;
    [Tooltip("시뮬레이션 배속. 1 = 실시간.")]
    public float timeScale = 1f;

    public enum EvalCondition
    {
        A_RobotStop,          // 온보드 탐지 + 정지 후 재탐색 (기존 방식)
        B_OnboardReplan,      // 온보드 탐지 + 주행 중 전역 재계획 (Nav2 방식의 온보드 전용 내비게이션)
        C_InfraNoStop,        // 인프라(360 카메라)가 장애물 등장 즉시 탐지 + 정지 없는 경로 교체 (제안)
        D_OnboardDStarLite,   // 온보드 탐지 + 격자 D* Lite 증분 재계획
        E_OnboardDWA,         // 온보드 탐지 + DWA 반응형 로컬 플래너 (전역 재계획 없음)
        O_KnownAtStart        // 기준선: 출발할 때부터 장애물을 알고 있음
    }

    public enum PlacementMode { AlongPath, AfterCorner }

    [Header("Conditions")]
    [Tooltip("한 trial에서 실행할 조건. 순서는 trial마다 한 칸씩 돌립니다.")]
    public EvalCondition[] conditions =
        { EvalCondition.A_RobotStop, EvalCondition.B_OnboardReplan, EvalCondition.C_InfraNoStop };

    [Header("Onboard sensing (A, B, D, E)")]
    [Tooltip("로봇 정면 카메라의 좌우 시야 반각(도). 이 안에 있고 가려지지 않아야 탐지합니다.")]
    public float robotHalfFovDeg = 60f;
    [Tooltip("켜면 로봇과 장애물 사이에 벽/가구가 있으면 탐지하지 못합니다.")]
    public bool robotNeedsLineOfSight = true;
    public float robotEyeHeight = 0.3f;

    [Header("Infrastructure sensing (C) - 기록용")]
    public Vector3 infraAnchor = new Vector3(3.235f, 0f, 6.585f);
    public float infraRange = 4f;

    [Header("Multiple obstacles")]
    [Tooltip("한 run에 등장하는 장애물 수. 2 이상이면 경로를 따라 차례로 놓이고, 로봇이 가까이 갈 때마다 하나씩 나타납니다.")]
    [Min(1)] public int obstacleCount = 1;
    [Tooltip("켜면 나타나는 장애물을 상자 대신 사람 모형으로 보여 준다 (크기·충돌은 그대로).")]
    public bool obstacleAsPerson = false;
    [Tooltip("장애물이 여러 개일 때 놓는 경로 비율 범위 (이 범위를 개수만큼 나눠 구간마다 하나).")]
    public Vector2 multiFractionRange = new Vector2(0.2f, 0.85f);
    [Tooltip("장애물끼리 최소 거리(m).")]
    public float multiMinSpacing = 1.6f;
    [Tooltip("장애물이 여러 개일 때 앞 장애물이 나타난 뒤 다음 것이 나타나기까지 최소 시간(초). 가면서 하나씩 나타나게 합니다.")]
    public float multiMinAppearGapSec = 2.5f;
    [Tooltip("장애물 가로/세로 크기 범위(m). x < y 이면 장애물마다 크기를 따로 뽑습니다. 아니면 obstacleSize 고정.")]
    public Vector2 obstacleSizeRange = Vector2.zero;
    [Tooltip("켜면 장애물을 인프라(360 카메라) 탐지 범위 안에만 놓습니다.")]
    public bool requireInfraCoverage = false;

    [Header("Placement")]
    public PlacementMode placementMode = PlacementMode.AlongPath;
    [Tooltip("AfterCorner: 이 각도(도) 이상 꺾이는 경로 모퉁이 뒤에 장애물을 둡니다.")]
    public float cornerMinTurnDeg = 25f;
    [Tooltip("AfterCorner: 모퉁이에서 경로를 따라 이만큼(m) 지난 곳.")]
    public Vector2 cornerOffsetRange = new Vector2(0.4f, 1.0f);

    [Header("D* Lite (D)")]
    public float dstarCell = 0.02f;
    [Tooltip("격자에서 장애물 표면부터 막는 거리(m). 0 이하면 NavMesh와 같은 여유.")]
    public float dstarMargin = -1f;
    [Tooltip("실제 장애물이 놓이는 시점: GO1이 장애물 위치에서 이 거리(m) 안에 들어올 때. 인프라 탐지 조건은 이때 트윈에 반영됩니다.")]
    public Vector2 appearDistanceRange = new Vector2(3.0f, 5.0f);
    [Tooltip("탐지 조건을 만족한 뒤 트윈에 반영되기까지의 지연(초). 모든 조건에 똑같이 적용.")]
    public float detectLatencySec = 0f;
    [Tooltip("트윈 장애물 위치 오차의 표준편차(m, x와 z 각각). 0이면 실제 위치 그대로. 접촉과 간격은 항상 실제 위치로 잽니다.")]
    public float twinNoiseSigma = 0f;
    [Tooltip("결과 폴더 이름 뒤에 붙는 표시.")]
    public string sessionLabel = "";

    [Header("Obstacle (seed로 결정)")]
    [Tooltip("시작→목표 NavMesh 경로 길이에 대한 장애물 위치 비율 범위.")]
    public Vector2 pathFractionRange = new Vector2(0.35f, 0.65f);
    [Tooltip("경로 수직 방향 오프셋 범위(m).")]
    public Vector2 lateralOffsetRange = new Vector2(-0.10f, 0.10f);
    [Tooltip("로봇 탐지 조건: GO1이 장애물 위치에서 이 거리(m) 안에 들어오면 트윈에 반영.")]
    public Vector2 spawnDistanceRange = new Vector2(1.2f, 2.0f);
    public Vector3 obstacleSize = new Vector3(0.5f, 0.6f, 0.5f);
    [Tooltip("NavMesh에서 파낼 영역을 장애물보다 넓히는(+)/줄이는(-) 값(m). 실제 360 수신기의 navMeshPadding과 같은 뜻.")]
    public float navMeshPadding = 0f;
    [Tooltip("NavMesh agent radius(m). 파낸 영역은 장애물 표면에서 이 값 + navMeshPadding 만큼 떨어집니다.")]
    public float navAgentRadius = 0.25f;
    [Tooltip("장애물 위치를 고를 때 우회 폭에 더 요구하는 여유(m).")]
    public float placementExtraMargin = 0.05f;

    private struct Placement
    {
        public float frac, lateral, sideLeft, sideRight; public bool ok; public int tries;
        public float[] fracs, laterals;
    }
    private readonly List<GameObject> spawnedAll = new List<GameObject>();
    private readonly List<GameObject> ghosts = new List<GameObject>();
    private readonly Dictionary<int, Placement> placementCache = new Dictionary<int, Placement>();
    public string obstacleTag = "Obstacle";
    public string obstacleLayer = "Obstacle";

    [Header("Limits")]
    public float rolloutTimeout = 120f;
    [Tooltip("재주행 시작 후 시간 초과 = 이 값 × (NavMesh 경로 길이 / 0.1 m/s) 와 runTimeoutMin 중 큰 값.")]
    public float runTimeoutMin = 180f;
    public float idleFailSeconds = 3f;

    [Header("Measurement")]
    [Tooltip("이 속도(m/s) 미만이면 정지로 봅니다.")]
    public float stopSpeedThreshold = 0.03f;
    [Tooltip("정지가 이 시간(s) 이상 이어지면 정지 1회로 셉니다.")]
    public float stopEventMinSeconds = 0.5f;
    [Tooltip("몸체 중심과 장애물 표면 거리가 이 값(m) 미만이면 접촉으로 봅니다. 가상 가정값(provisional).")]
    public float contactRadius = 0.25f;
    public float trajectorySampleHz = 10f;

    [Header("Output")]
    public string outputFolderName = "GO1_Proactive_Evaluation";

    [Header("Status")]
    [SerializeField] private bool running;
    [SerializeField] private int currentTrial;
    [SerializeField] private string currentCondition;

    private string sessionDir;
    private string runsCsv;
    private int runIndex;
    private Coroutine mainRoutine;
    private GameObject spawnedObstacle;
    private Vector3 defaultStartPos;
    private Quaternion defaultStartRot;
    private Vector3 defaultGoalPos;

    public bool IsRunning => running;
    public int RunsDone => runIndex;
    public string SessionDir => sessionDir;
    public string CurrentCondition => currentCondition;
    public int CurrentTrial => currentTrial;

    private bool completedFlag;
    private bool completedSuccess;
    private string completedReason;
    private float completedFinalError;

    private void Start()
    {
        ResolveRefs();
        if (agent != null)
        {
            defaultStartPos = agent.transform.position;
            defaultStartRot = agent.transform.rotation;
            if (agent.target != null) defaultGoalPos = agent.target.position;
        }
        if (autoStart)
            StartEvaluation();
    }

    private void Update()
    {
        if (Input.GetKeyDown(startKey) && !running) StartEvaluation();
        if (Input.GetKeyDown(stopKey) && running) StopEvaluation();
    }

    private void OnDestroy()
    {
        if (agent != null) agent.LocalReplayCompleted -= OnReplayCompleted;
    }

    private void ResolveRefs()
    {
        if (agent == null) agent = FindFirstObjectByType<GO1Agent>();
        if (agent != null && updater == null)
        {
            updater = agent.GetComponent<GO1ProactivePathUpdater>();
            if (updater == null) updater = agent.gameObject.AddComponent<GO1ProactivePathUpdater>();
        }
    }

    public void StartEvaluation()
    {
        ResolveRefs();
        if (agent == null || agent.target == null)
        {
            Debug.LogError("[ProactiveEval] GO1Agent 또는 target이 없습니다.");
            return;
        }

        agent.virtualOnlyMode = true;
        agent.enableRuntimeReplanning = true;
        agent.enableObstacleTriggeredReplan = true;
        agent.LocalReplayCompleted -= OnReplayCompleted;
        agent.LocalReplayCompleted += OnReplayCompleted;
        agent.ProactiveRealFollower = realFollowerModel;
        agent.ProactiveReplaySpeedOverride = replaySpeed;
        agent.ProactiveReplayToleranceOverride = replayWaypointTolerance;
        BuildScenarios();
        placementCache.Clear();

        string stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture);
        if (!string.IsNullOrEmpty(sessionLabel)) stamp += "_" + sessionLabel;
        sessionDir = Path.Combine(Directory.GetParent(Application.dataPath).FullName, outputFolderName, stamp);
        Directory.CreateDirectory(Path.Combine(sessionDir, "traj"));
        runsCsv = Path.Combine(sessionDir, "runs.csv");
        File.WriteAllText(runsCsv, RunRow.Header + "\n", new UTF8Encoding(false));
        WriteMeta(stamp);

        runIndex = 0;
        running = true;
        Time.timeScale = Mathf.Max(0.1f, timeScale);
        mainRoutine = StartCoroutine(MainLoop());
        Debug.Log("[ProactiveEval] 시작 | trials=" + trials + ", out=" + sessionDir);
    }

    public void StopEvaluation()
    {
        running = false;
        if (mainRoutine != null) StopCoroutine(mainRoutine);
        mainRoutine = null;
        CleanupObstacle();
        if (agent != null) agent.ProactiveAbortForTrial();
        RestoreAgent();
        Time.timeScale = 1f;
        Debug.Log("[ProactiveEval] 중지 | runs=" + runIndex);
    }

    private void RestoreAgent()
    {
        if (agent == null) return;
        agent.ProactiveRealFollower = false;
        agent.ProactiveReplaySpeedOverride = -1f;
        agent.ProactiveReplayToleranceOverride = -1f;
        if (dwa != null) dwa.End();
        if (updater != null) { updater.customPlanner = null; updater.enabled = true; }
    }

    private readonly List<Vector3> scenStarts = new List<Vector3>();
    private readonly List<Vector3> scenGoals = new List<Vector3>();

    private void BuildScenarios()
    {
        scenStarts.Clear(); scenGoals.Clear();
        int given = (startPoints != null && goalPoints != null) ? Mathf.Min(startPoints.Length, goalPoints.Length) : 0;
        for (int i = 0; i < given; i++) { scenStarts.Add(startPoints[i].position); scenGoals.Add(goalPoints[i].position); }
        if (given == 0 && autoScenarioCount > 0) AutoScenarios();
        if (scenStarts.Count == 0) { scenStarts.Add(defaultStartPos); scenGoals.Add(defaultGoalPos); }
    }

    // NavMesh 삼각형에서 넓이 비례로 점을 뽑아, 경계에서 충분히 떨어지고 경로 길이가 범위 안인 쌍만 남긴다.
    private void AutoScenarios()
    {
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        int nTri = tri.indices.Length / 3;
        if (nTri == 0) return;
        var cum = new float[nTri];
        float total = 0f;
        for (int i = 0; i < nTri; i++)
        {
            Vector3 a = tri.vertices[tri.indices[3 * i]], b = tri.vertices[tri.indices[3 * i + 1]], c = tri.vertices[tri.indices[3 * i + 2]];
            total += Vector3.Cross(b - a, c - a).magnitude * 0.5f;
            cum[i] = total;
        }
        var rng = new System.Random(scenarioSeed);
        Func<Vector3> sample = () =>
        {
            float r = (float)rng.NextDouble() * total;
            int i = Array.BinarySearch(cum, r); if (i < 0) i = ~i; i = Mathf.Min(i, nTri - 1);
            Vector3 a = tri.vertices[tri.indices[3 * i]], b = tri.vertices[tri.indices[3 * i + 1]], c = tri.vertices[tri.indices[3 * i + 2]];
            float u = (float)rng.NextDouble(), v = (float)rng.NextDouble();
            if (u + v > 1f) { u = 1f - u; v = 1f - v; }
            return a + (b - a) * u + (c - a) * v;
        };
        Func<Vector3, bool> clear = p =>
            NavMesh.FindClosestEdge(p, out NavMeshHit h, NavMesh.AllAreas) && h.distance >= autoScenarioEdgeMargin;

        var path = new NavMeshPath();
        for (int attempt = 0; attempt < 20000 && scenStarts.Count < autoScenarioCount; attempt++)
        {
            Vector3 s = sample(), g = sample();
            if (!clear(s) || !clear(g)) continue;
            if (!NavMesh.CalculatePath(s, g, NavMesh.AllAreas, path) || path.status != NavMeshPathStatus.PathComplete) continue;
            float len = PathLength(path.corners);
            if (len < autoScenarioPathLength.x || len > autoScenarioPathLength.y) continue;
            scenStarts.Add(s); scenGoals.Add(g);
        }
        Debug.Log("[ProactiveEval] 자동 시나리오 " + scenStarts.Count + "/" + autoScenarioCount + "쌍");
    }

    private IEnumerator MainLoop()
    {
        for (currentTrial = 0; currentTrial < trials && running; currentTrial++)
        {
            int seed = baseSeed + currentTrial;
            int n = conditions.Length;
            for (int k = 0; k < n; k++)
            {
                if (!running) yield break;
                yield return RunOnce(currentTrial, seed, conditions[(k + currentTrial) % n]);
                yield return new WaitForSeconds(0.5f);
            }
        }

        running = false;
        RestoreAgent();
        Time.timeScale = 1f;
        Debug.Log("[ProactiveEval] 완료 | runs=" + runIndex + ", out=" + sessionDir);
    }

    private IEnumerator RunOnce(int trial, int seed, EvalCondition cond)
    {
        var mode = cond == EvalCondition.A_RobotStop
            ? GO1ProactivePathUpdater.ResponseMode.StopAndReplan
            : GO1ProactivePathUpdater.ResponseMode.NoStopSwap;
        bool infraDetect = cond == EvalCondition.C_InfraNoStop || cond == EvalCondition.O_KnownAtStart;
        bool knownAtStart = cond == EvalCondition.O_KnownAtStart;
        bool useDStar = cond == EvalCondition.D_OnboardDStarLite;
        bool useDwa = cond == EvalCondition.E_OnboardDWA;
        currentCondition = cond.ToString();
        var row = new RunRow { run = runIndex, trial = trial, seed = seed, condition = cond.ToString() };
        runIndex++;

        // ---- 시나리오 (seed로 결정, 조건과 무관) ----
        var rng = new System.Random(seed);
        int scen = rng.Next(scenStarts.Count);
        // 고정 시나리오를 준 경우에는 trial 순서대로 하나씩 쓴다 (모든 시나리오를 빠짐없이 돌리기 위해). rng 는 위에서 한 번 뽑은 상태를 유지한다.
        if (startPoints != null && startPoints.Length > 0 && goalPoints != null && goalPoints.Length > 0) scen = trial % scenStarts.Count;
        Vector3 start = scenStarts[scen];
        Vector3 goal = scenGoals[scen];
        float frac = 0f, lateral = 0f;
        float spawnDist = Lerp(spawnDistanceRange, rng.NextDouble());
        float appearDist = Mathf.Max(spawnDist, Lerp(appearDistanceRange, rng.NextDouble()));
        float appearBase = appearDist;   // 조건과 무관한 값 (배치 판정에 씀)
        if (knownAtStart) appearDist = 1e6f;
        Vector2 unitNoise = new Vector2(Gaussian(rng), Gaussian(rng));   // 조건과 무관하게 seed로 고정
        float detectDist = infraDetect ? appearDist : spawnDist;
        row.scenario = scen; row.start = start; row.goal = goal;
        row.spawnDist = spawnDist;
        row.appearDist = appearDist; row.detectDist = detectDist;
        row.noiseSigma = twinNoiseSigma;
        row.noiseDx = unitNoise.x * twinNoiseSigma; row.noiseDz = unitNoise.y * twinNoiseSigma;

        // 장애물이 여러 개면 2번째부터의 거리/오차를 이어서 뽑는다 (1개일 때 난수 순서는 그대로)
        int nObs = Mathf.Max(1, obstacleCount);
        var appearDists = new float[nObs]; var detectDists = new float[nObs]; var noises = new Vector2[nObs];
        appearDists[0] = appearDist; detectDists[0] = detectDist; noises[0] = unitNoise * twinNoiseSigma;
        for (int k = 1; k < nObs; k++)
        {
            float sd = Lerp(spawnDistanceRange, rng.NextDouble());
            rng.NextDouble();   // (예전 난수 자리 유지)
            // 모든 장애물이 같은 거리에서 나타난다: 간격을 두고 놓였으므로 가는 순서대로 하나씩 나타난다
            appearDists[k] = knownAtStart ? 1e6f : Mathf.Max(sd, appearBase);
            noises[k] = new Vector2(Gaussian(rng), Gaussian(rng)) * twinNoiseSigma;
            detectDists[k] = infraDetect ? appearDists[k] : sd;
        }
        row.obstacleCount = nObs;
        var sizes = new Vector3[nObs];
        for (int k = 0; k < nObs; k++)
            sizes[k] = obstacleSizeRange.y > obstacleSizeRange.x
                ? new Vector3(Lerp(obstacleSizeRange, rng.NextDouble()), obstacleSize.y, Lerp(obstacleSizeRange, rng.NextDouble()))
                : obstacleSize;

        CleanupObstacle();
        agent.ProactiveAbortForTrial();
        yield return null;

        NavMeshPath nav = new NavMeshPath();
        if (!NavMesh.CalculatePath(start, goal, NavMesh.AllAreas, nav) || nav.status != NavMeshPathStatus.PathComplete)
        {
            row.endReason = "infra_no_navmesh_path";
            WriteRow(row);
            yield break;
        }
        row.navLen = PathLength(nav.corners);

        // 장애물 위치: 경로를 막되, 실제 로봇이 옆으로 지나갈 폭이 남는 곳만 쓴다 (seed로 다시 뽑음).
        // 한쪽 옆의 NavMesh 여유가 (장애물 반대각 + 파내는 여유)보다 커야 우회로가 생긴다.
        // 판정은 식이 아니라 실제로 놓아 보고 한다: 장애물을 놓은 뒤에도 시작→목표 NavMesh 경로가 이어져야 한다.
        // 같은 seed의 다른 조건은 처음 정한 위치를 그대로 쓴다.
        Vector3 obsPos = Vector3.zero;
        var fracs = new float[nObs]; var laterals = new float[nObs]; var obsAll = new Vector3[nObs];
        bool placed = false;
        if (placementCache.TryGetValue(seed, out Placement cached))
        {
            frac = cached.frac; lateral = cached.lateral; placed = cached.ok;
            row.placeTries = cached.tries; row.sideLeft = cached.sideLeft; row.sideRight = cached.sideRight;
            fracs = cached.fracs; laterals = cached.laterals;
        }
        else
        {
            var probe = new NavMeshPath();
            for (int tries = 1; tries <= (nObs > 1 ? 150 : 40) && !placed; tries++)
            {
                row.placeTries = tries;
                for (int k = 0; k < nObs; k++)
                {
                    if (nObs == 1)
                    {
                        fracs[0] = placementMode == PlacementMode.AfterCorner
                            ? CornerFraction(nav.corners, row.navLen, rng)
                            : Lerp(pathFractionRange, rng.NextDouble());
                    }
                    else
                    {
                        float lo = Mathf.Lerp(multiFractionRange.x, multiFractionRange.y, (float)k / nObs);
                        float hi = Mathf.Lerp(multiFractionRange.x, multiFractionRange.y, (float)(k + 1) / nObs);
                        fracs[k] = Mathf.Lerp(lo, hi, (float)rng.NextDouble());
                    }
                    laterals[k] = Lerp(lateralOffsetRange, rng.NextDouble());
                }
                frac = fracs[0]; lateral = laterals[0];
                if (frac < 0f) break;   // 쓸 모퉁이가 없는 경로

                bool tooClose = false;
                for (int k = 0; k < nObs; k++)
                {
                    obsAll[k] = PointAlong(nav.corners, row.navLen * fracs[k], laterals[k]);
                    if (k > 0 && PlanarDistance(obsAll[k], obsAll[k - 1]) < multiMinSpacing) tooClose = true;
                    if (requireInfraCoverage && PlanarDistance(obsAll[k], infraAnchor) > infraRange - 0.2f) tooClose = true;
                    // 여러 개일 때: 첫 장애물도 출발하고 나서 나타나도록 출발점에서 충분히 떨어뜨린다
                    if (nObs > 1 && k == 0 && PlanarDistance(obsAll[0], start) < appearBase + 0.3f) tooClose = true;
                }
                if (tooClose) continue;

                Vector3 side = SideNormalAlong(nav.corners, row.navLen * frac);
                row.sideLeft = SideFree(obsAll[0], side);
                row.sideRight = SideFree(obsAll[0], -side);

                // 전부 놓은 상태에서도 시작→목표가 이어져야 한다
                for (int k = 0; k < nObs; k++) SpawnObstacle(obsAll[k], sizes[k]);
                yield return new WaitForSeconds(0.2f);   // carving 반영 대기
                placed = NavMesh.CalculatePath(start, goal, NavMesh.AllAreas, probe) &&
                         probe.status == NavMeshPathStatus.PathComplete;
                CleanupObstacle();
                yield return new WaitForSeconds(0.2f);   // 파낸 자리 복구 대기
            }
            placementCache[seed] = new Placement
            {
                frac = frac, lateral = lateral, ok = placed, tries = row.placeTries,
                sideLeft = row.sideLeft, sideRight = row.sideRight,
                fracs = (float[])fracs.Clone(), laterals = (float[])laterals.Clone()
            };
        }
        var twinAll = new Vector3[nObs];
        var obsText = new StringBuilder();
        for (int k = 0; k < nObs; k++)
        {
            obsAll[k] = PointAlong(nav.corners, row.navLen * Mathf.Max(0f, fracs[k]), laterals[k]);
            twinAll[k] = obsAll[k] + new Vector3(noises[k].x, 0f, noises[k].y);   // 트윈이 믿는 위치
            if (k > 0) obsText.Append('|');
            obsText.Append(F(obsAll[k].x)).Append(':').Append(F(obsAll[k].z));
        }
        obsPos = obsAll[0];
        row.obsAll = obsText.ToString();
        row.obsFrac = frac; row.obsLateral = lateral;
        row.obs = obsPos;
        if (!placed)
        {
            row.endReason = frac < 0f ? "infra_no_corner" : "infra_no_passable_placement";
            WriteRow(row);
            yield break;
        }
        row.infraInRange = PlanarDistance(obsPos, infraAnchor) <= infraRange;
        row.latency = detectLatencySec;
        row.placement = placementMode.ToString();

        // ---- 시작 ----
        Vector3 firstDir = nav.corners[1] - nav.corners[0]; firstDir.y = 0f;
        Quaternion startRot = firstDir.sqrMagnitude > 1e-6f
            ? Quaternion.LookRotation(firstDir.normalized) * Quaternion.Euler(0f, 90f, 0f)   // GO1 전진축 = -right
            : defaultStartRot;
        agent.ProactiveTeleportForTrial(start, startRot);
        agent.target.position = goal;
        updater.responseMode = mode;
        updater.ResetCounters();
        updater.ResetPlanStats();
        updater.customPlanner = null;
        updater.enabled = !useDwa;   // DWA 조건은 전역 재계획을 하지 않는다
        completedFlag = false;
        yield return null;

        agent.StartNewMission();

        // ---- 기준 경로 생성 대기 ----
        float rolloutStart = Time.time;
        while (!agent.ProactiveIsLocalReplayActive)
        {
            if (completedFlag || Time.time - rolloutStart > rolloutTimeout)
            {
                row.endReason = completedFlag ? "rollout_" + completedReason : "rollout_timeout";
                WriteRow(row);
                agent.ProactiveAbortForTrial();
                yield break;
            }
            yield return null;
        }
        row.rolloutTime = Time.time - rolloutStart;
        Diag("replay-start", agent.transform.position, goal);
        row.baselineLen = PathLength(agent.ProactiveLocalReplayPath);
        if (recorder != null) recorder.BeginRun("run_" + row.run.ToString("D4") + "_" + cond, start, goal);
        if (useDStar)
        {
            if (dstar == null) { dstar = new DStarLiteGridPlanner(); dstar.Build(dstarCell); }
            dstar.BeginRun(agent.transform.position, goal);
            row.plannerInitMs = (float)dstar.InitMs;
            updater.customPlanner = (a, b) =>
            {
                var p = dstar.Plan(a, b);
                if (debugNavMesh || visualMarkers || p == null)
                    Debug.Log("[ProactiveEval][dstar] " + dstar.LastStatus +
                              (p != null ? " first=" + p[0].ToString("F2") + " last=" + p[p.Count - 1].ToString("F2") +
                                           " len=" + PathLength(p).ToString("F2") + " target=" + b.ToString("F2") : ""));
                return p;
            };
            if (debugNavMesh) Debug.Log("[ProactiveEval][dstar] init " + dstar.InitMs.ToString("F1") + " ms, grid " +
                                        dstar.Width + "x" + dstar.Height + ", free " + dstar.FreeCells);
        }
        if (useDwa)
        {
            if (dwa == null) dwa = agent.gameObject.AddComponent<GO1DwaLocalController>();
            dwa.maxSpeed = realFollowerModel ? agent.PfMaxVx : (replaySpeed > 0f ? replaySpeed : dwa.maxSpeed);
            if (realFollowerModel) dwa.maxYawRateDeg = agent.PfMaxWz * Mathf.Rad2Deg;
            dwa.Begin(agent);
        }

        // ---- 측정 ----
        var traj = new StringBuilder("t,x,z,replay_active,stop_replan,speed,obstacle_present\n");
        float t0 = Time.time;
        float timeout = Mathf.Max(runTimeoutMin, row.navLen / 0.1f);
        float spawnTime = -1f, lastSample = -999f, stoppedRun = 0f, idleTime = 0f;
        float appearTime = -1f;
        var appearTimes = new float[nObs]; var detectReady = new float[nObs]; var spawnTimes = new float[nObs];
        for (int k = 0; k < nObs; k++) { appearTimes[k] = -1f; detectReady[k] = -1f; spawnTimes[k] = -1f; }
        var detectText = new StringBuilder(); var appearText = new StringBuilder(); var spawnText = new StringBuilder();
        bool inStopEvent = false, wasReplay = false;
        Vector3 lastPos = agent.transform.position;
        row.minClearance = float.MaxValue;
        row.minClearanceObs = float.MaxValue;
        int obstacleMask = LayerMask.GetMask(obstacleLayer);

        while (true)
        {
            yield return null;
            float dt = Time.deltaTime;
            float t = Time.time - t0;
            bool replay = agent.ProactiveIsLocalReplayActive;
            bool stopReplan = agent.ProactiveIsStopReplanInProgress;
            Vector3 pos = agent.transform.position;

            float step = 0f;
            if (replay && wasReplay)   // 재탐색 후 재주행 시작점으로 돌아온 첫 프레임은 제외
            {
                Vector3 d = pos - lastPos; d.y = 0f;
                step = d.magnitude;
                row.travel += step;
            }
            if (replay) lastPos = pos;
            wasReplay = replay;
            float speed = dt > 0f ? step / dt : 0f;

            bool stopped = !replay || speed < stopSpeedThreshold;
            if (stopped)
            {
                row.stoppedTotal += dt;
                if (spawnTime >= 0f) row.stoppedAfterSpawn += dt;
                if (appearTime >= 0f)
                {
                    row.stoppedAfterAppear += dt;
                    // 정지의 종류: 재탐색을 기다리며 선 것(wait)과 방향을 맞추느라 제자리에서 돈 것(turn)
                    if (replay) row.stoppedTurn += dt; else row.stoppedWait += dt;
                }
                stoppedRun += dt;
                if (!inStopEvent && stoppedRun >= stopEventMinSeconds && appearTime >= 0f)
                {
                    inStopEvent = true;
                    row.stopEvents++;
                }
            }
            else
            {
                stoppedRun = 0f;
                inStopEvent = false;
            }

            // 실제 장애물 등장 (모든 조건에서 같은 시점)
            for (int k = 0; k < nObs; k++)
            {
                float distK = PlanarDistance(pos, obsAll[k]);
                bool turn = k == 0 || knownAtStart ||
                            (appearTimes[k - 1] >= 0f && Time.time - appearTimes[k - 1] >= multiMinAppearGapSec);
                if (appearTimes[k] < 0f && replay && turn && distK <= appearDists[k])
                {
                    appearTimes[k] = Time.time;
                    appearText.Append(appearText.Length > 0 ? "|" : "").Append(F(t));
                    if (visualMarkers)
                    {
                        // 보기용: 충돌체도 태그도 없어서 계획과 탐지에 영향을 주지 않는다
                        GameObject ghost = GameObject.CreatePrimitive(PrimitiveType.Cube);
                        ghost.name = "EvalTruthGhost";
                        Destroy(ghost.GetComponent<Collider>());
                        ghost.transform.position = new Vector3(obsAll[k].x, obsAll[k].y + sizes[k].y * 0.45f, obsAll[k].z);
                        ghost.transform.localScale = sizes[k] * 0.9f;
                        ghost.GetComponent<Renderer>().material = ProactiveRunRecorder.Flat(new Color(1f, 0.1f, 0.1f, 0.45f));
                        ghosts.Add(ghost);
                    }
                    if (appearTime < 0f)
                    {
                        appearTime = Time.time;
                        row.appearT = t;
                        row.truthBlocked = PathHitsBox(RemainingCopy(), obsAll[k], agent.pathCheckRadius, sizes[k]);
                    }
                }
                // 탐지 조건 만족 → 지연 뒤 트윈에 반영 (인프라: 등장 즉시, 로봇: 가까이 가서 보일 때)
                if (appearTimes[k] >= 0f && detectReady[k] < 0f && replay && distK <= detectDists[k] &&
                    (infraDetect || RobotSees(pos, obsAll[k])))
                {
                    detectReady[k] = Time.time + Mathf.Max(0f, detectLatencySec);
                    if (row.detectActualDist < 0f) row.detectActualDist = distK;
                    if (detectText.Length > 0) detectText.Append('|');
                    detectText.Append(F(distK));
                }
                if (spawnTimes[k] < 0f && detectReady[k] >= 0f && Time.time >= detectReady[k])
                {
                    Diag("before-spawn", pos, goal);
                    SpawnObstacle(twinAll[k], sizes[k]);
                    spawnText.Append(spawnText.Length > 0 ? "|" : "").Append(F(t));
                    Physics.SyncTransforms();   // 새 콜라이더가 아래 막힘 검사에 바로 잡히도록
                    if (useDStar)
                        dstar.AddObstacle(twinAll[k], sizes[k],
                                          dstarMargin > 0f ? dstarMargin : navAgentRadius + navMeshPadding);
                    spawnTimes[k] = Time.time;
                    row.detectedCount++;
                    if (spawnTime < 0f)
                    {
                        spawnTime = Time.time;
                        row.spawnT = t;
                        row.baselineBlocked = agent.ProactiveIsWorldPathBlocked(RemainingCopy(), "eval-baseline-blocked");
                    }
                }
            }
            if (spawnTime >= 0f && row.detourChecked == false && Time.time - spawnTime > 0.2f)
            {
                NavMeshPath dp = new NavMeshPath();
                row.detourExists = NavMesh.CalculatePath(pos, goal, NavMesh.AllAreas, dp) && dp.status == NavMeshPathStatus.PathComplete;
                row.detourChecked = true;
                Diag("after-spawn", pos, goal);
            }

            // 간격 / 접촉 (재주행 중에만: 재탐색 중 ML 롤아웃 이동은 실제 이동이 아님)
            if (replay && obstacleMask != 0)
            {
                float c = MinClearance(pos, obstacleMask);
                if (c < row.minClearance) row.minClearance = c;
                if (c < contactRadius) row.contactTime += dt;
            }
            // 실제 장애물(트윈 위치가 아니라 참값)과의 간격 / 접촉
            if (replay && appearTime >= 0f)
            {
                float ce = float.MaxValue;
                for (int k = 0; k < nObs; k++)
                    if (appearTimes[k] >= 0f) ce = Mathf.Min(ce, BoxDistance(pos, obsAll[k], sizes[k]));
                if (ce < row.minClearanceObs) row.minClearanceObs = ce;
                if (ce < contactRadius) row.contactTimeObs += dt;
            }

            if (Time.time - lastSample >= 1f / Mathf.Max(1f, trajectorySampleHz))
            {
                lastSample = Time.time;
                traj.Append(F(t)).Append(',').Append(F(pos.x)).Append(',').Append(F(pos.z)).Append(',')
                    .Append(replay ? 1 : 0).Append(',').Append(stopReplan ? 1 : 0).Append(',')
                    .Append(F(speed)).Append(',').Append(spawnTime >= 0f ? 1 : 0).Append('\n');
            }

            // 종료 판정
            if (completedFlag)
            {
                row.success = completedSuccess;
                row.endReason = completedReason;
                row.finalError = completedFinalError;
                break;
            }
            if (t > timeout)
            {
                row.endReason = "run_timeout";
                row.finalError = PlanarDistance(pos, goal);
                break;
            }
            bool planning = agent.IsVirtualPathPlanning();
            idleTime = (!replay && !stopReplan && !planning) ? idleTime + dt : 0f;
            if (idleTime > idleFailSeconds)
            {
                row.endReason = "idle_or_replan_failed";
                row.finalError = PlanarDistance(pos, goal);
                break;
            }
        }

        row.tTotal = Time.time - t0;
        row.tAfterSpawn = spawnTime >= 0f ? Time.time - spawnTime : -1f;
        row.tAfterAppear = appearTime >= 0f ? Time.time - appearTime : -1f;
        if (row.minClearance == float.MaxValue) row.minClearance = -1f;
        if (row.minClearanceObs == float.MaxValue) row.minClearanceObs = -1f;
        row.blockedDetections = updater.BlockedDetections;
        row.detectDelay = (spawnTime >= 0f && updater.FirstBlockedTime >= 0f) ? updater.FirstBlockedTime - spawnTime : -1f;
        row.switches = updater.SwitchCountThisMission;
        row.stopReplans = updater.StopReplanRequests;
        row.fallbacks = updater.FallbackStopReplans;
        row.planCalls = updater.PlanCalls;
        row.planMsMean = updater.PlanCalls > 0 ? (float)(updater.TotalPlanMs / updater.PlanCalls) : -1f;
        if (useDwa && dwa != null) { row.dwaStuckTicks = dwa.StuckTicks; dwa.End(); }
        updater.customPlanner = null;
        updater.enabled = true;
        row.spawned = spawnTime >= 0f;

        if (recorder != null) recorder.EndRun();
        foreach (GameObject gh in ghosts) if (gh != null) Destroy(gh);
        ghosts.Clear();
        row.detectDists = detectText.ToString();
        row.appearTs = appearText.ToString(); row.spawnTs = spawnText.ToString();
        File.WriteAllText(Path.Combine(sessionDir, "traj", "run_" + row.run.ToString("D4") + ".csv"), traj.ToString(), new UTF8Encoding(false));
        WriteRow(row);

        agent.ProactiveAbortForTrial();
        CleanupObstacle();
        Debug.Log("[ProactiveEval] run " + row.run + " | trial=" + trial + " " + row.condition +
                  " | success=" + row.success + " (" + row.endReason + ")" +
                  ", t=" + row.tTotal.ToString("F1") + "s, stopped_after_spawn=" + row.stoppedAfterSpawn.ToString("F1") + "s" +
                  ", switches=" + row.switches + ", stop_replans=" + row.stopReplans);
    }

    private void OnReplayCompleted(GO1Agent a, bool success, string reason, float finalError)
    {
        completedFlag = true;
        completedSuccess = success;
        completedReason = reason;
        completedFinalError = finalError;
    }

    private List<Vector3> RemainingCopy()
    {
        var path = agent.ProactiveLocalReplayPath;
        var outList = new List<Vector3> { agent.transform.position };
        if (path == null || path.Count < 2) return outList;
        Vector3 p = agent.transform.position;
        int best = 0; float bd = float.MaxValue;
        for (int i = 0; i < path.Count - 1; i++)
        {
            float d = SegDist(p, path[i], path[i + 1]);
            if (d < bd) { bd = d; best = i; }
        }
        for (int i = best + 1; i < path.Count; i++) outList.Add(path[i]);
        return outList;
    }

    private void SpawnObstacle(Vector3 pos, Vector3? sizeOpt = null)
    {
        Vector3 size = sizeOpt ?? obstacleSize;
        spawnedObstacle = GameObject.CreatePrimitive(PrimitiveType.Cube);
        spawnedAll.Add(spawnedObstacle);
        spawnedObstacle.name = "EvalObstacle";
        spawnedObstacle.transform.position = new Vector3(pos.x, pos.y + size.y * 0.5f, pos.z);
        spawnedObstacle.transform.localScale = size;
        try { spawnedObstacle.tag = obstacleTag; } catch { Debug.LogWarning("[ProactiveEval] Tag '" + obstacleTag + "' 없음"); }
        int layer = LayerMask.NameToLayer(obstacleLayer);
        if (layer >= 0) spawnedObstacle.layer = layer;
        if (visualMarkers)
            spawnedObstacle.GetComponent<Renderer>().material = ProactiveRunRecorder.Flat(new Color(1f, 0.85f, 0.1f));
        var nmo = spawnedObstacle.AddComponent<NavMeshObstacle>();
        nmo.shape = NavMeshObstacleShape.Box;
        nmo.size = new Vector3(   // Anchor360ObstacleReceiver.ApplyNavSize와 같은 식
            Mathf.Max(0.1f, 1f + 2f * navMeshPadding / Mathf.Max(size.x, 0.01f)), 1f,
            Mathf.Max(0.1f, 1f + 2f * navMeshPadding / Mathf.Max(size.z, 0.01f)));
        nmo.carving = true;
        nmo.carveOnlyStationary = false;
        // 장애물을 사람으로 보여 준다 (충돌·NavMesh 는 상자 그대로)
        if (obstacleAsPerson) PersonVisual.Sync(spawnedObstacle, "person", pos.y, new Color(1f, 0.55f, 0.1f));
    }

    // 경로 위 s 지점에서 경로에 수직인 단위 벡터
    private static Vector3 SideNormalAlong(Vector3[] c, float s)
    {
        for (int i = 0; i < c.Length - 1; i++)
        {
            float len = PlanarDistance(c[i], c[i + 1]);
            if (s <= len || i == c.Length - 2)
            {
                Vector3 dir = c[i + 1] - c[i]; dir.y = 0f;
                return dir.sqrMagnitude > 1e-6f ? Vector3.Cross(Vector3.up, dir.normalized) : Vector3.right;
            }
            s -= len;
        }
        return Vector3.right;
    }

    // p에서 dir 방향으로 NavMesh 경계까지의 거리 (p가 NavMesh 밖이면 0)
    private static float SideFree(Vector3 p, Vector3 dir)
    {
        if (!NavMesh.SamplePosition(p, out NavMeshHit on, 0.1f, NavMesh.AllAreas)) return 0f;
        Vector3 from = on.position;
        return NavMesh.Raycast(from, from + dir * 3f, out NavMeshHit hit, NavMesh.AllAreas)
            ? PlanarDistance(from, hit.position) : 3f;
    }

    private void CleanupObstacle()
    {
        foreach (GameObject o in spawnedAll) if (o != null) Destroy(o);
        spawnedAll.Clear();
        spawnedObstacle = null;
    }

    [Header("Debug")]
    public bool debugNavMesh = false;

    [Header("Recording (선택)")]
    [Tooltip("있으면 run마다 위에서 본 화면을 프레임으로 저장합니다.")]
    public ProactiveRunRecorder recorder;
    [Tooltip("켜면 실제 장애물(트윈이 아직 모르는 것)을 빨간 상자로, 트윈에 반영된 장애물을 노란 상자로 보여 줍니다.")]
    public bool visualMarkers = false;


    private void Diag(string tag, Vector3 pos, Vector3 goal)
    {
        if (!debugNavMesh) return;
        var p = new NavMeshPath();
        bool ok = NavMesh.CalculatePath(pos, goal, NavMesh.AllAreas, p);
        float dPos = NavMesh.SamplePosition(pos, out NavMeshHit h1, 5f, NavMesh.AllAreas) ? Vector3.Distance(h1.position, pos) : -1f;
        float dGoal = NavMesh.SamplePosition(goal, out NavMeshHit h2, 5f, NavMesh.AllAreas) ? Vector3.Distance(h2.position, goal) : -1f;
        int carve = 0, all = 0;
        foreach (var o in FindObjectsByType<NavMeshObstacle>(FindObjectsSortMode.None)) { all++; if (o.carving) carve++; }
        float area = 0f;
        var tri = NavMesh.CalculateTriangulation();
        for (int i = 0; i < tri.indices.Length; i += 3)
            area += Vector3.Cross(tri.vertices[tri.indices[i + 1]] - tri.vertices[tri.indices[i]],
                                  tri.vertices[tri.indices[i + 2]] - tri.vertices[tri.indices[i]]).magnitude * 0.5f;
        Debug.Log("[ProactiveEval][diag] " + tag + " | calc=" + ok + " status=" + p.status + " corners=" + p.corners.Length +
                  " | pos=" + pos.ToString("F2") + " offMesh=" + dPos.ToString("F2") +
                  " | goal=" + goal.ToString("F2") + " offMesh=" + dGoal.ToString("F2") +
                  " | obstacles=" + all + " carving=" + carve + " navArea=" + area.ToString("F1"));
    }

    private DStarLiteGridPlanner dstar;
    private GO1DwaLocalController dwa;

    // 로봇 정면 카메라로 장애물이 보이는가: 시야각 안 + (선택) 벽/가구에 가리지 않음
    private bool RobotSees(Vector3 pos, Vector3 obs)
    {
        Vector3 fwd = -agent.transform.right; fwd.y = 0f;
        Vector3 to = obs - pos; to.y = 0f;
        if (to.sqrMagnitude < 1e-6f) return true;
        if (Vector3.Angle(fwd, to) > robotHalfFovDeg) return false;
        if (!robotNeedsLineOfSight) return true;
        Vector3 eye = pos + Vector3.up * robotEyeHeight;
        Vector3 tgt = new Vector3(obs.x, eye.y, obs.z);
        foreach (RaycastHit h in Physics.RaycastAll(eye, (tgt - eye).normalized, Vector3.Distance(eye, tgt),
                                                    agent.ProactiveObstacleLayerMask, QueryTriggerInteraction.Ignore))
        {
            if (h.collider.transform.IsChildOf(agent.transform)) continue;
            return false;
        }
        return true;
    }

    // 경로에서 충분히 꺾이는 모퉁이를 하나 골라, 그 뒤 cornerOffsetRange 만큼 지난 지점의 경로 비율. 없으면 -1.
    private float CornerFraction(Vector3[] c, float navLen, System.Random rng)
    {
        var cand = new List<float>();
        float acc = 0f;
        for (int i = 1; i < c.Length - 1; i++)
        {
            acc += PlanarDistance(c[i - 1], c[i]);
            Vector3 a = c[i] - c[i - 1], b = c[i + 1] - c[i]; a.y = 0f; b.y = 0f;
            if (Vector3.Angle(a, b) >= cornerMinTurnDeg && acc >= 1.0f && acc + cornerOffsetRange.x <= navLen - 0.8f)
                cand.Add(acc);
        }
        double u1 = rng.NextDouble(), u2 = rng.NextDouble();   // 후보가 없어도 같은 수만큼 뽑는다
        if (cand.Count == 0) return -1f;
        float s = cand[Mathf.Min(cand.Count - 1, (int)(u1 * cand.Count))] + Lerp(cornerOffsetRange, u2);
        return Mathf.Min(s, navLen - 0.8f) / navLen;
    }

    // 실제 장애물 상자(축 정렬, obstacleSize)까지의 평면 거리
    private float BoxDistance(Vector3 p, Vector3 center, Vector3? sizeOpt = null)
    {
        Vector3 size = sizeOpt ?? obstacleSize;
        float dx = Mathf.Max(Mathf.Abs(p.x - center.x) - size.x * 0.5f, 0f);
        float dz = Mathf.Max(Mathf.Abs(p.z - center.z) - size.z * 0.5f, 0f);
        return Mathf.Sqrt(dx * dx + dz * dz);
    }

    // 경로가 실제 장애물 상자에서 radius 안으로 지나가는지 (0.05 m 간격 샘플)
    private bool PathHitsBox(List<Vector3> path, Vector3 center, float radius, Vector3? sizeOpt = null)
    {
        for (int i = 0; i < path.Count - 1; i++)
        {
            int steps = Mathf.Max(1, Mathf.CeilToInt(PlanarDistance(path[i], path[i + 1]) / 0.05f));
            for (int s = 0; s <= steps; s++)
                if (BoxDistance(Vector3.Lerp(path[i], path[i + 1], (float)s / steps), center, sizeOpt) < radius)
                    return true;
        }
        return false;
    }

    private static float Gaussian(System.Random rng)
    {
        double u1 = 1.0 - rng.NextDouble(), u2 = rng.NextDouble();
        return (float)(Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2));
    }

    private float MinClearance(Vector3 pos, int mask)
    {
        float best = float.MaxValue;
        Vector3 c = pos + Vector3.up * 0.3f;
        foreach (var col in Physics.OverlapSphere(c, 3f, mask, QueryTriggerInteraction.Ignore))
        {
            Vector3 cp = col.ClosestPoint(c);
            float d = PlanarDistance(cp, c);
            if (d < best) best = d;
        }
        return best;
    }

    private void WriteRow(RunRow r)
    {
        File.AppendAllText(runsCsv, r.ToCsv() + "\n", new UTF8Encoding(false));
    }

    private void WriteMeta(string stamp)
    {
        var sb = new StringBuilder();
        sb.AppendLine("session=" + stamp);
        sb.AppendLine("unity=" + Application.unityVersion);
        sb.AppendLine("scene=" + UnityEngine.SceneManagement.SceneManager.GetActiveScene().name);
        sb.AppendLine("trials=" + trials + " baseSeed=" + baseSeed + " timeScale=" + timeScale);
        sb.AppendLine("detectLatencySec=" + detectLatencySec + " obstacleCount=" + obstacleCount +
                      " multiFractionRange=" + multiFractionRange + " multiMinSpacing=" + multiMinSpacing +
                      " multiMinAppearGapSec=" + multiMinAppearGapSec +
                      " obstacleSizeRange=" + obstacleSizeRange + " requireInfraCoverage=" + requireInfraCoverage);
        sb.AppendLine("conditions=" + string.Join("|", Array.ConvertAll(conditions, c => c.ToString())) +
                      " appearDistanceRange=" + appearDistanceRange + " detectLatencySec=" + detectLatencySec +
                      " twinNoiseSigma=" + twinNoiseSigma + " label=" + sessionLabel);
        sb.AppendLine("pathFractionRange=" + pathFractionRange + " lateralOffsetRange=" + lateralOffsetRange +
                      " spawnDistanceRange=" + spawnDistanceRange + " obstacleSize=" + obstacleSize);
        sb.AppendLine("stopSpeedThreshold=" + stopSpeedThreshold + " stopEventMinSeconds=" + stopEventMinSeconds +
                      " contactRadius=" + contactRadius + " (provisional)");
        sb.AppendLine("updater.checkInterval=" + updater.checkInterval + " confirmBlockedChecks=" + updater.confirmBlockedChecks +
                      " samePathTolerance=" + updater.samePathTolerance + " minSwitchInterval=" + updater.minSwitchInterval +
                      " fallbackAfterFailedChecks=" + updater.fallbackAfterFailedChecks);
        sb.AppendLine("agent=" + agent.name + " pathCheckRadius=" + agent.pathCheckRadius + " pathCheckHeight=" + agent.pathCheckHeight +
                      " moveSpeed=" + agent.moveSpeed);
        sb.AppendLine("placementMode=" + placementMode + " robotHalfFovDeg=" + robotHalfFovDeg +
                      " robotNeedsLineOfSight=" + robotNeedsLineOfSight + " infraAnchor=" + infraAnchor + " infraRange=" + infraRange +
                      " dstarCell=" + dstarCell);
        sb.AppendLine("navMeshPadding=" + navMeshPadding + " placement=carve-tested (start->goal path must stay complete)");
        sb.AppendLine("realFollowerModel=" + realFollowerModel + " (maxVx=" + agent.PfMaxVx + " minVx=" + agent.PfMinVx +
                      " maxWz=" + agent.PfMaxWz + " turnOnly=" + agent.PfTurnOnly + " lookahead=" + agent.PfLookahead +
                      " reach=" + agent.PfReach + ")");
        sb.AppendLine("replaySpeed=" + replaySpeed + " replayWaypointTolerance=" + replayWaypointTolerance +
                      " scenarioSeed=" + scenarioSeed + " autoScenarioPathLength=" + autoScenarioPathLength);
        for (int i = 0; i < scenStarts.Count; i++)
            sb.AppendLine("scenario" + i + " start=" + scenStarts[i].ToString("F2") + " goal=" + scenGoals[i].ToString("F2"));
        File.WriteAllText(Path.Combine(sessionDir, "meta.txt"), sb.ToString(), new UTF8Encoding(false));
    }

    // ---- helpers ----
    private static float Lerp(Vector2 r, double u) => Mathf.Lerp(r.x, r.y, (float)u);

    private static float PlanarDistance(Vector3 a, Vector3 b)
    {
        a.y = 0f; b.y = 0f;
        return Vector3.Distance(a, b);
    }

    private static float PathLength(IReadOnlyList<Vector3> p)
    {
        if (p == null) return 0f;
        float L = 0f;
        for (int i = 1; i < p.Count; i++) L += PlanarDistance(p[i - 1], p[i]);
        return L;
    }

    private static Vector3 PointAlong(Vector3[] c, float s, float lateral)
    {
        for (int i = 0; i < c.Length - 1; i++)
        {
            float len = PlanarDistance(c[i], c[i + 1]);
            if (s <= len || i == c.Length - 2)
            {
                Vector3 dir = c[i + 1] - c[i]; dir.y = 0f;
                Vector3 n = dir.sqrMagnitude > 1e-6f ? Vector3.Cross(Vector3.up, dir.normalized) : Vector3.zero;
                return Vector3.Lerp(c[i], c[i + 1], len > 1e-4f ? Mathf.Clamp01(s / len) : 0f) + n * lateral;
            }
            s -= len;
        }
        return c[c.Length - 1];
    }

    private static float SegDist(Vector3 p, Vector3 a, Vector3 b)
    {
        Vector2 P = new Vector2(p.x, p.z), A = new Vector2(a.x, a.z), AB = new Vector2(b.x, b.z) - A;
        if (AB.sqrMagnitude < 1e-6f) return Vector2.Distance(P, A);
        float t = Mathf.Clamp01(Vector2.Dot(P - A, AB) / AB.sqrMagnitude);
        return Vector2.Distance(P, A + AB * t);
    }

    private static string F(float v) => v.ToString("0.###", CultureInfo.InvariantCulture);

    private class RunRow
    {
        public int run, trial, seed, scenario;
        public string condition;
        public Vector3 start, goal, obs;
        public float obsFrac, obsLateral, spawnDist, navLen, baselineLen, rolloutTime;
        public bool spawned, baselineBlocked, detourExists, detourChecked, success;
        public string endReason = "";
        public float finalError = -1f, tTotal, spawnT = -1f, tAfterSpawn = -1f, stoppedTotal, stoppedAfterSpawn;
        public int stopEvents, blockedDetections, switches, stopReplans, fallbacks;
        public float travel, minClearance = -1f, contactTime, detectDelay = -1f, minClearanceObs = -1f, contactTimeObs;
        public float appearDist, detectDist, appearT = -1f, tAfterAppear = -1f, stoppedAfterAppear, noiseSigma, noiseDx, noiseDz;
        public bool truthBlocked;
        public int placeTries;
        public float sideLeft, sideRight;
        public float detectActualDist = -1f, planMsMean = -1f, plannerInitMs = -1f;
        public int planCalls, dwaStuckTicks;
        public bool infraInRange;
        public float latency;
        public float stoppedWait, stoppedTurn;
        public int obstacleCount = 1, detectedCount;
        public string obsAll = "", detectDists = "", appearTs = "", spawnTs = "";
        public string placement = "";

        public const string Header =
            "run,trial,seed,condition,scenario,start_x,start_z,goal_x,goal_z,obs_x,obs_z,obs_frac,obs_lateral,spawn_dist," +
            "nav_len,baseline_len,rollout_time,spawned,baseline_blocked,detour_exists,success,end_reason,final_error," +
            "t_total,spawn_t,t_after_spawn,stopped_total,stopped_after_spawn,stop_events,travel,min_clearance,contact_time," +
            "min_clearance_obs,contact_time_obs," +
            "blocked_detections,detect_delay,switches,stop_replans,fallbacks," +
            "appear_dist,detect_dist,appear_t,t_after_appear,stopped_after_appear,truth_blocked,noise_sigma,noise_dx,noise_dz," +
            "place_tries,side_left,side_right," +
            "detect_actual_dist,plan_calls,plan_ms_mean,planner_init_ms,dwa_stuck_ticks,infra_in_range,placement,detect_latency," +
            "obstacle_count,detected_count,obs_all,detect_dists,appear_ts,spawn_ts,stopped_wait,stopped_turn";

        public string ToCsv()
        {
            string B(bool b) => b ? "1" : "0";
            return string.Join(",", new[]
            {
                run.ToString(), trial.ToString(), seed.ToString(), condition, scenario.ToString(),
                F(start.x), F(start.z), F(goal.x), F(goal.z), F(obs.x), F(obs.z), F(obsFrac), F(obsLateral), F(spawnDist),
                F(navLen), F(baselineLen), F(rolloutTime), B(spawned), B(baselineBlocked), B(detourExists), B(success),
                endReason, F(finalError), F(tTotal), F(spawnT), F(tAfterSpawn), F(stoppedTotal), F(stoppedAfterSpawn),
                stopEvents.ToString(), F(travel), F(minClearance), F(contactTime), F(minClearanceObs), F(contactTimeObs),
                blockedDetections.ToString(), F(detectDelay), switches.ToString(), stopReplans.ToString(), fallbacks.ToString(),
                F(appearDist), F(detectDist), F(appearT), F(tAfterAppear), F(stoppedAfterAppear), B(truthBlocked),
                F(noiseSigma), F(noiseDx), F(noiseDz),
                placeTries.ToString(), F(sideLeft), F(sideRight),
                F(detectActualDist), planCalls.ToString(), F(planMsMean), F(plannerInitMs), dwaStuckTicks.ToString(),
                B(infraInRange), placement, F(latency),
                obstacleCount.ToString(), detectedCount.ToString(), obsAll, detectDists, appearTs, spawnTs,
                F(stoppedWait), F(stoppedTurn)
            });
        }
    }
}
