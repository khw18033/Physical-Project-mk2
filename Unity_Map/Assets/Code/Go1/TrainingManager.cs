using UnityEngine;
using UnityEngine.AI;
using Unity.MLAgents;
using System.Collections;
using System.Collections.Generic;

public class TrainingManager : MonoBehaviour
{
    [Header("설정")]
    public GameObject go1Prefab;
    public Transform startPoint;
    public int agentCount = 5;
    public float goalMinDistance = 3f;
    public float goalMaxDistance = 6f;
    public float minOpenRadius = 2.0f;

    [Tooltip("목표 위치를 찾을 때 시도할 최대 횟수입니다.")]
    public int randomPointAttempts = 500;

    [Tooltip("목표 지점에도 시작점과 같은 개방 공간 검사를 적용할지 여부입니다. 좁은 복도 평가에서는 해제 권장.")]
    public bool requireOpenAreaForGoal = false;

    [Header("재현성")]
    [Tooltip("논문 실험에서 같은 랜덤 시작점/목표 분포를 재현하려면 체크합니다.")]
    public bool useFixedRandomSeed = true;

    [Tooltip("UnityEngine.Random에 적용할 고정 시드입니다. 비교 조건 간에는 같은 값을 사용합니다.")]
    public int randomSeed = 121;

    [Header("Curriculum")]
    public float successRateThreshold = 0.7f;
    public int evaluationWindow = 20;

    [Header("Evaluation (난이도 고정)")]
    [Tooltip("논문 평가용. 켜면 평가 내내 난이도(목표 거리 범위)가 자동으로 오르내리지 않고 evaluationDifficultyLevel로 고정된다. 그래야 모든 trial이 같은 거리 분포에서 나와 성공률이 일관된다. 학습 시에는 끈다.")]
    public bool evaluationFixedDifficulty = false;

    [Tooltip("평가 시 고정할 난이도 레벨. 0=가까움(~5m), 1=중간(~10m), 2=원거리(무제한). 거리 구간별 성능을 보려면 0,1,2로 각각 돌린다.")]
    public int evaluationDifficultyLevel = 0;

    private int currentDifficultyLevel = 0;
    private Queue<bool> recentResults = new Queue<bool>();
    private float[] maxDistanceByLevel = { 5f, 10f, 999f };

    private GO1Agent[] agents;
    private GameObject[] goalObjects;
    private int[] agentLayers;

    private NavMeshTriangulation triangulation;

    void Start()
    {
        if (useFixedRandomSeed)
        {
            Random.InitState(randomSeed);
            Debug.Log($"[TrainingManager] 고정 랜덤 시드 적용: {randomSeed}");
        }

        triangulation = NavMesh.CalculateTriangulation();
        StartCoroutine(InitAfterNavMesh());
    }

    IEnumerator InitAfterNavMesh()
    {
        yield return null;
        yield return null;

        // 평가 모드면 난이도를 지정 레벨로 고정한 채 시작한다.
        if (evaluationFixedDifficulty)
        {
            currentDifficultyLevel = Mathf.Clamp(
                evaluationDifficultyLevel, 0, maxDistanceByLevel.Length - 1);
            Debug.Log($"[TrainingManager] 평가 모드: 난이도 {currentDifficultyLevel} 고정");
        }

        agents = new GO1Agent[agentCount];
        goalObjects = new GameObject[agentCount];
        agentLayers = new int[agentCount];
        CharacterController[] controllers = new CharacterController[agentCount];

        for (int i = 0; i < agentCount; i++)
        {
            Vector3 randomStart = GetRandomStartPosition();

            GameObject agentObj = Instantiate(go1Prefab, randomStart,
                Quaternion.Euler(0f, Random.Range(0f, 360f), 0f));
            agentObj.name = $"GO1_Agent_{i}";

            int layer = 7 + i;
            agentObj.layer = layer;
            agentLayers[i] = layer;

            foreach (Transform child in agentObj.GetComponentsInChildren<Transform>())
                child.gameObject.layer = layer;

            agents[i] = agentObj.GetComponent<GO1Agent>();
            agents[i].startPoint = startPoint;
            agents[i].trainingManager = this;
            controllers[i] = agentObj.GetComponent<CharacterController>();

            for (int j = 0; j < i; j++)
                Physics.IgnoreLayerCollision(layer, agentLayers[j], true);

            // 시각화용 구체로 목표 생성
            goalObjects[i] = new GameObject($"GoalPoint_{i}");
            GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            sphere.transform.SetParent(goalObjects[i].transform);
            sphere.transform.localPosition = Vector3.zero;
            sphere.transform.localScale = Vector3.one * 0.3f;
            Destroy(sphere.GetComponent<Collider>());
            sphere.GetComponent<Renderer>().material.color = Color.green;

            SetRandomGoal(i);
        }

        for (int i = 0; i < agentCount; i++)
        {
            for (int j = 0; j < agentCount; j++)
            {
                if (i != j && controllers[i] != null && controllers[j] != null)
                {
                    Physics.IgnoreCollision(controllers[i], controllers[j], true);
                    Debug.Log($"[TrainingManager] 충돌 무시: Agent_{i} ↔ Agent_{j}");
                }
            }
        }
    }

    public bool SetRandomGoal(int agentIndex)
    {
        if (agents == null || goalObjects == null ||
            agentIndex < 0 || agentIndex >= agents.Length ||
            agents[agentIndex] == null || goalObjects[agentIndex] == null)
            return false;

        float maxDist = maxDistanceByLevel[
            Mathf.Min(currentDifficultyLevel, maxDistanceByLevel.Length - 1)];

        Vector3 agentPos = agents[agentIndex].transform.position;
        Vector3 randomPoint;

        if (!TryGetNavMeshRandomPoint(agentPos, maxDist, out randomPoint))
        {
            Debug.LogError(
                $"[TrainingManager] Agent_{agentIndex} 유효 목표 생성 실패 | " +
                $"요구 거리={goalMinDistance:F2}~{Mathf.Min(goalMaxDistance, maxDist):F2}m");
            return false;
        }

        goalObjects[agentIndex].transform.position = randomPoint;
        agents[agentIndex].SetGoal(goalObjects[agentIndex].transform);

        float finalDistance = Vector3.Distance(
            new Vector3(agentPos.x, 0f, agentPos.z),
            new Vector3(randomPoint.x, 0f, randomPoint.z));

        Debug.Log($"[TrainingManager] Agent_{agentIndex} 목표 설정: {randomPoint} " +
                  $"거리={finalDistance:F2}m (난이도={currentDifficultyLevel})");
        return true;
    }

    public bool ResetGoalForAgent(GO1Agent agent)
    {
        if (agent == null)
            return false;

        // agents 배열에 등록된 에이전트인 경우 기존 경로로 처리
        if (agents != null)
        {
            for (int i = 0; i < agents.Length; i++)
            {
                if (agents[i] == agent)
                    return SetRandomGoal(i);
            }
        }

        // agentCount=0 또는 씬에 직접 배치된 에이전트: agent.target을 직접 이동
        if (agent.target == null)
        {
            Debug.LogError("[TrainingManager] ResetGoalForAgent: agent.target이 null입니다. " +
                           "GO1Agent Inspector에서 target(GoalPoint)을 연결하세요.", agent);
            return false;
        }

        Vector3 agentPos = agent.transform.position;
        float maxDist = maxDistanceByLevel[
            Mathf.Clamp(currentDifficultyLevel, 0, maxDistanceByLevel.Length - 1)];

        if (triangulation.vertices == null || triangulation.vertices.Length == 0)
            triangulation = NavMesh.CalculateTriangulation();

        Vector3 randomPoint;
        if (!TryGetNavMeshRandomPoint(agentPos, maxDist, out randomPoint))
        {
            Debug.LogError("[TrainingManager] ResetGoalForAgent: 유효 목표 생성 실패. " +
                           "NavMesh가 씬에 베이크되어 있는지 확인하세요.", agent);
            return false;
        }

        agent.target.position = randomPoint;
        agent.SetGoal(agent.target);

        float dist = Vector3.Distance(
            new Vector3(agentPos.x, 0f, agentPos.z),
            new Vector3(randomPoint.x, 0f, randomPoint.z));
        Debug.Log($"[TrainingManager] 직접 배치 에이전트 목표 설정: {randomPoint} 거리={dist:F2}m", agent);
        return true;
    }

    /// <summary>
    /// ResetGoalForAgent의 trial 재현성 버전입니다. GetRandomStartPositionForTrial과 같은 이유로,
    /// C2C3EvaluationManager가 별도 세션에서 돌아도 같은 trial 번호가 같은 목표를 뽑도록
    /// 호출 직전에 trial 전용 시드로 다시 초기화합니다.
    /// </summary>
    public bool ResetGoalForAgentForTrial(GO1Agent agent, int trialIndex, int retryAttempt)
    {
        Random.InitState(unchecked(randomSeed + trialIndex * 97 + retryAttempt + 1));
        return ResetGoalForAgent(agent);
    }

    public void OnAgentReachedGoal(GO1Agent agent)
    {
        RecordResult(true);
        CheckDifficultyUpdate();

        for (int i = 0; i < agentCount; i++)
        {
            if (agents[i] == agent)
            {
                // 다음 목표는 GO1Agent.OnEpisodeBegin에서 새 시작 위치가 정해진 뒤 생성한다.
                Debug.Log($"[TrainingManager] Agent_{i} 성공! " +
                          $"성공률={GetSuccessRate():F2} 난이도={currentDifficultyLevel}");
                return;
            }
        }
    }

    public void OnAgentFailed(GO1Agent agent)
    {
        RecordResult(false);

        if (!evaluationFixedDifficulty &&
            recentResults.Count >= evaluationWindow &&
            GetSuccessRate() < 0.3f && currentDifficultyLevel > 0)
        {
            currentDifficultyLevel--;
            recentResults.Clear();
            Debug.Log($"[TrainingManager] 성공률 낮음 → 난이도 하향: {currentDifficultyLevel}");
        }

        for (int i = 0; i < agentCount; i++)
        {
            if (agents[i] == agent)
            {
                Debug.Log($"[TrainingManager] Agent_{i} 실패! 성공률={GetSuccessRate():F2}");
                return;
            }
        }
    }

    private void RecordResult(bool success)
    {
        recentResults.Enqueue(success);
        if (recentResults.Count > evaluationWindow)
            recentResults.Dequeue();
    }

    private float GetSuccessRate()
    {
        if (recentResults.Count == 0) return 0f;

        int successCount = 0;
        foreach (bool r in recentResults)
            if (r) successCount++;

        return (float)successCount / recentResults.Count;
    }

    private void CheckDifficultyUpdate()
    {
        if (evaluationFixedDifficulty) return;  // 평가 중 난이도 고정
        if (recentResults.Count < evaluationWindow) return;

        float successRate = GetSuccessRate();

        if (successRate >= successRateThreshold &&
            currentDifficultyLevel < maxDistanceByLevel.Length - 1)
        {
            currentDifficultyLevel++;
            recentResults.Clear();
            Debug.Log($"[TrainingManager] 난이도 상향! 레벨={currentDifficultyLevel} " +
                      $"(성공률={successRate:F2})");
        }
    }

    public int GetCurrentDifficultyLevel()
    {
        return currentDifficultyLevel;
    }

    public float GetCurrentSuccessRate()
    {
        return GetSuccessRate();
    }

    public bool IsEvaluationDifficultyFixed()
    {
        return evaluationFixedDifficulty;
    }

    public int GetRandomSeed()
    {
        return useFixedRandomSeed ? randomSeed : -1;
    }

    /// <summary>
    /// GO1Agent 없이 임의 위치를 기준으로 목표 지점을 생성합니다.
    /// C1(NavMesh-only) 평가처럼 RL 에이전트를 쓰지 않는 조건에서
    /// C2/C3와 동일한 목표 거리 분포(현재 난이도 기준)를 재현하기 위해 사용합니다.
    /// </summary>
    public bool TryGetRandomGoalPosition(Vector3 fromPosition, out Vector3 goalPosition)
    {
        goalPosition = fromPosition;

        if (triangulation.vertices == null || triangulation.vertices.Length == 0)
            triangulation = NavMesh.CalculateTriangulation();

        float maxDist = maxDistanceByLevel[
            Mathf.Clamp(currentDifficultyLevel, 0, maxDistanceByLevel.Length - 1)];

        return TryGetNavMeshRandomPoint(fromPosition, maxDist, out goalPosition);
    }

    /// <summary>
    /// C1/C2/C3처럼 여러 개의 독립된 세션(별도의 EvaluationManager)에서 "같은 trial 번호는
    /// 같은 시작/목표 시나리오"가 되도록 재현성이 필요할 때 씁니다. UnityEngine.Random은
    /// 전역 스트림이라 이전에 몇 번 호출됐는지(세션마다 재시도 횟수가 달라 회차별로 달라짐)에
    /// 따라 결과가 갈리는데, 이 오버로드는 호출 직전에 trial 전용 시드로 다시 초기화해
    /// 세션 히스토리와 무관하게 항상 같은 값을 뽑도록 만든다.
    /// </summary>
    public Vector3 GetRandomStartPositionForTrial(int trialIndex, int retryAttempt = 0)
    {
        Random.InitState(unchecked(randomSeed + trialIndex * 97 + retryAttempt));
        return GetRandomStartPosition();
    }

    /// <summary>GetRandomStartPositionForTrial과 짝을 이루는 목표 지점 버전입니다.</summary>
    public bool TryGetRandomGoalPositionForTrial(int trialIndex, int retryAttempt, Vector3 fromPosition, out Vector3 goalPosition)
    {
        Random.InitState(unchecked(randomSeed + trialIndex * 97 + retryAttempt + 1));
        return TryGetRandomGoalPosition(fromPosition, out goalPosition);
    }

    public float GetCurrentDifficultyMaxDistance()
    {
        int index = Mathf.Clamp(currentDifficultyLevel, 0, maxDistanceByLevel.Length - 1);
        return Mathf.Min(goalMaxDistance, maxDistanceByLevel[index]);
    }

    public Vector3 GetRandomStartPosition()
    {
        if (triangulation.vertices == null || triangulation.vertices.Length == 0)
        {
            triangulation = NavMesh.CalculateTriangulation();
            if (triangulation.vertices == null || triangulation.vertices.Length == 0)
                return startPoint != null ? startPoint.position : Vector3.zero;
        }

        if (startPoint == null)
        {
            Debug.LogError("[TrainingManager] startPoint가 연결되지 않았습니다. Inspector에서 Start Point를 설정하세요.", this);
            return Vector3.zero;
        }

        for (int attempt = 0; attempt < 100; attempt++)
        {
            Vector3 candidate = GetRandomNavMeshPoint();

            NavMeshHit hit;
            if (!NavMesh.SamplePosition(candidate, out hit, 1f, NavMesh.AllAreas))
                continue;

            if (IsOpenArea(hit.position, minOpenRadius))
                return hit.position;
        }

        Debug.LogWarning("[TrainingManager] 랜덤 시작 위치 실패, 기본 시작점 반환");
        return startPoint.position;
    }

    private bool TryGetNavMeshRandomPoint(
        Vector3 origin,
        float maxDist,
        out Vector3 result)
    {
        result = origin;

        float clampedMax = Mathf.Min(goalMaxDistance, maxDist);
        float clampedMin = Mathf.Min(goalMinDistance, clampedMax);
        int attempts = Mathf.Max(1, randomPointAttempts);
        NavMeshPath validationPath = new NavMeshPath();

        for (int attempt = 0; attempt < attempts; attempt++)
        {
            Vector3 candidate = GetRandomNavMeshPoint();

            NavMeshHit hit;
            if (!NavMesh.SamplePosition(candidate, out hit, 1f, NavMesh.AllAreas))
                continue;

            // candidate가 아니라 SamplePosition 이후의 실제 최종 좌표로 거리를 검증해야 한다.
            Vector3 sampled = hit.position;
            float dist = Vector3.Distance(
                new Vector3(origin.x, 0f, origin.z),
                new Vector3(sampled.x, 0f, sampled.z));

            if (dist < clampedMin || dist > clampedMax)
                continue;

            if (requireOpenAreaForGoal && !IsOpenArea(sampled, minOpenRadius))
                continue;

            if (!NavMesh.CalculatePath(origin, sampled, NavMesh.AllAreas, validationPath) ||
                validationPath.status != NavMeshPathStatus.PathComplete)
                continue;

            result = sampled;
            return true;
        }

        // 랜덤 표본이 실패하면 NavMesh 꼭짓점을 전수 검사해 가능한 지점을 한 번 더 찾는다.
        if (triangulation.vertices != null)
        {
            for (int i = 0; i < triangulation.vertices.Length; i++)
            {
                Vector3 sampled = triangulation.vertices[i];
                float dist = Vector3.Distance(
                    new Vector3(origin.x, 0f, origin.z),
                    new Vector3(sampled.x, 0f, sampled.z));

                if (dist < clampedMin || dist > clampedMax)
                    continue;

                if (requireOpenAreaForGoal && !IsOpenArea(sampled, minOpenRadius))
                    continue;

                if (!NavMesh.CalculatePath(origin, sampled, NavMesh.AllAreas, validationPath) ||
                    validationPath.status != NavMeshPathStatus.PathComplete)
                    continue;

                result = sampled;
                return true;
            }
        }

        return false;
    }

    private Vector3 GetRandomNavMeshPoint()
    {
        // NavMesh 변경(NavMeshObstacle carving 등) 후 triangulation이 stale할 수 있으므로
        // indices가 vertices 범위를 초과하면 재계산한다.
        if (triangulation.indices == null || triangulation.indices.Length < 3 ||
            triangulation.vertices == null || triangulation.vertices.Length == 0)
        {
            triangulation = NavMesh.CalculateTriangulation();
        }

        if (triangulation.indices == null || triangulation.indices.Length < 3 ||
            triangulation.vertices == null || triangulation.vertices.Length == 0)
        {
            return startPoint != null ? startPoint.position : Vector3.zero;
        }

        int maxTri = triangulation.indices.Length / 3;
        int vLen   = triangulation.vertices.Length;

        // 유효한 삼각형을 최대 10번 시도 후 fallback
        for (int attempt = 0; attempt < 10; attempt++)
        {
            int triIdx = Random.Range(0, maxTri) * 3;
            int i0 = triangulation.indices[triIdx];
            int i1 = triangulation.indices[triIdx + 1];
            int i2 = triangulation.indices[triIdx + 2];

            if (i0 >= vLen || i1 >= vLen || i2 >= vLen)
            {
                // stale triangulation — 재계산 후 재시도
                triangulation = NavMesh.CalculateTriangulation();
                maxTri = triangulation.indices != null ? triangulation.indices.Length / 3 : 0;
                vLen   = triangulation.vertices != null ? triangulation.vertices.Length : 0;
                if (maxTri == 0 || vLen == 0)
                    return startPoint != null ? startPoint.position : Vector3.zero;
                continue;
            }

            Vector3 v0 = triangulation.vertices[i0];
            Vector3 v1 = triangulation.vertices[i1];
            Vector3 v2 = triangulation.vertices[i2];

            float r1 = Mathf.Sqrt(Random.value);
            float r2 = Random.value;
            return (1 - r1) * v0 + r1 * (1 - r2) * v1 + r1 * r2 * v2;
        }

        return startPoint != null ? startPoint.position : Vector3.zero;
    }

    bool IsOpenArea(Vector3 point, float minRadius)
    {
        // 16방향으로 늘림 (45도 → 22.5도 간격)
        int checkCount = 16;

        // NavMesh 기반 체크
        for (int i = 0; i < checkCount; i++)
        {
            float angle = i * (360f / checkCount) * Mathf.Deg2Rad;
            Vector3 dir = new Vector3(Mathf.Cos(angle), 0f, Mathf.Sin(angle));
            Vector3 checkPoint = point + dir * minRadius;

            NavMeshHit hit;
            if (!NavMesh.SamplePosition(checkPoint, out hit, 0.5f, NavMesh.AllAreas))
                return false;
        }

        // Raycast 기반 벽 거리 체크
        for (int i = 0; i < checkCount; i++)
        {
            float angle = i * (360f / checkCount) * Mathf.Deg2Rad;
            Vector3 dir = new Vector3(Mathf.Cos(angle), 0f, Mathf.Sin(angle));

            RaycastHit rayHit;
            if (Physics.Raycast(point + Vector3.up * 0.5f, dir,
                out rayHit, minRadius + 0.5f))
                return false;
        }

        return true;
    }
}