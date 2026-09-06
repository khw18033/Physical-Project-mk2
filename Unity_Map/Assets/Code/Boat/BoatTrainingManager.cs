using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// BoatColregAgent 전용 학습 관리자.
///
/// 핵심 설계:
///   - 선박마다 시작→목표 이상 경로 위에 장애물 N개를 배치 (회피 훈련)
///   - 장애물은 각 선박의 전용 물리 레이어에 할당
///   - 레이어 간 충돌 무시 → 다른 선박/장애물은 물리적 간섭 없음
///   - 타선 탐지(COLREG)는 태그 기반 OverlapSphere라 레이어 영향 없음
///   - 커리큘럼: 성공률이 임계값을 넘으면 장애물 수 자동 증가
/// </summary>
public class BoatTrainingManager : MonoBehaviour
{
    // ── 선박 설정 ──────────────────────────────────────────────────────
    [Header("Boat")]
    [Tooltip("BoatColregAgent가 부착된 선박 프리팹")]
    public GameObject boatPrefab;

    [Tooltip("동시 학습 선박 수 — waterAreaRadius와 minBoatSpacing에 따라 최대값이 제한됨")]
    public int boatCount = 8;

    // ── 수역 설정 ──────────────────────────────────────────────────────
    [Header("Water Area")]
    [Tooltip("스폰 영역 중심 (없으면 원점 사용)")]
    public Transform waterCenter;

    [Tooltip("스폰 영역 반경 (m)")]
    public float waterAreaRadius = 100f;

    [Tooltip("선박 간 최소 초기 간격 (m)")]
    public float minBoatSpacing = 25f;

    [Tooltip("목표 지점 최소 거리 (m)")]
    public float goalMinDistance = 35f;

    [Tooltip("목표 지점 최대 거리 (m)")]
    public float goalMaxDistance = 80f;

    // ── 경로 장애물 설정 ────────────────────────────────────────────────
    [Header("Path Obstacles")]
    [Tooltip("장애물로 쓸 프리팹 (Collider 필수)")]
    public GameObject obstaclePrefab;

    [Tooltip("커리큘럼 레벨별 경로 위 장애물 수. 인덱스 0 = 가장 쉬움")]
    public int[] obstaclesPerLevel = { 1, 2, 3, 5 };

    [Tooltip("장애물을 경로 법선 방향으로 ±얼마나 랜덤 배치할지 (m). " +
             "값이 작을수록 장애물이 경로에 더 정확히 위치함")]
    [Range(0f, 10f)]
    public float obstaclePathOffset = 2.5f;

    [Tooltip("시작점에서 이 비율 이후부터 장애물 배치 (0~1). 너무 가깝지 않게")]
    [Range(0.05f, 0.5f)]
    public float obstacleStartFraction = 0.30f;

    [Tooltip("목표 앞 이 비율까지만 장애물 배치 (0~1). 목표 직전에는 비워둠")]
    [Range(0.5f, 0.95f)]
    public float obstacleEndFraction = 0.85f;

    // ── 레이어 설정 ────────────────────────────────────────────────────
    [Header("Layer Isolation")]
    [Tooltip("선박별 레이어 시작 번호. boatCount만큼 연속 레이어가 필요 (예: 8~11).")]
    public int layerBase = 8;

    // ── 커리큘럼 ───────────────────────────────────────────────────────
    [Header("Curriculum")]
    [Tooltip("이 성공률을 넘으면 난이도(장애물 수) 상향")]
    [Range(0.3f, 1f)]
    public float successRateThreshold = 0.7f;

    [Tooltip("성공률 산정에 사용할 최근 에피소드 수")]
    public int evaluationWindow = 20;

    // ── 재현성 ─────────────────────────────────────────────────────────
    [Header("Reproducibility")]
    public bool useFixedSeed = true;
    public int randomSeed = 42;

    // ── 내부 상태 ──────────────────────────────────────────────────────
    private BoatColregAgent[] boats;
    private GameObject[]       goalMarkers;
    private List<GameObject>[] pathObstacles;  // [boatIndex] 장애물 목록

    private const float SpawnRadiusFraction = 0.5f; // 경계 반경의 50% 이내에만 스폰

    private int          currentDifficultyLevel;
    private Queue<bool>  recentResults = new Queue<bool>();

    // ═══════════════════════════════════════════════════════════════════
    // 초기화
    // ═══════════════════════════════════════════════════════════════════

    private void Start()
    {
        if (useFixedSeed)
            Random.InitState(randomSeed);

        StartCoroutine(InitBoats());
    }

    private IEnumerator InitBoats()
    {
        yield return null; // 씬 로드 한 프레임 대기

        if (boatPrefab == null)
        {
            Debug.LogError("[BoatTrainingManager] boatPrefab이 설정되지 않았습니다.");
            yield break;
        }

        boats         = new BoatColregAgent[boatCount];
        goalMarkers   = new GameObject[boatCount];
        pathObstacles = new List<GameObject>[boatCount];
        for (int i = 0; i < boatCount; i++)
            pathObstacles[i] = new List<GameObject>();

        // 선박 간 충돌 무시 (서로의 몸체/장애물 통과)
        for (int a = 0; a < boatCount; a++)
            for (int b = a + 1; b < boatCount; b++)
                Physics.IgnoreLayerCollision(layerBase + a, layerBase + b, true);

        // 물 표면·바닥 메쉬(Default 레이어 0)와 각 선박 레이어 간 물리 충돌 무시
        // 배의 BoxCollider가 수면 아래 Plane과 겹쳐 예상치 못한 힘이 발생하는 것을 방지
        for (int i = 0; i < boatCount; i++)
            Physics.IgnoreLayerCollision(layerBase + i, 0, true);

        // 선박 스폰
        List<Vector3> occupied = new List<Vector3>();
        for (int i = 0; i < boatCount; i++)
        {
            Vector3 spawnPos = RandomWaterPosition(occupied, minBoatSpacing);
            occupied.Add(spawnPos);

            GameObject obj = Instantiate(
                boatPrefab,
                spawnPos,
                Quaternion.Euler(0f, Random.Range(0f, 360f), 0f)
            );
            obj.name = $"BoatColreg_{i}";

            // 선박과 그 자식 전체에 전용 레이어 적용
            SetLayerRecursive(obj, layerBase + i);

            boats[i] = obj.GetComponent<BoatColregAgent>();
            if (boats[i] == null)
            {
                Debug.LogError($"[BoatTrainingManager] {obj.name}에 BoatColregAgent가 없습니다.");
                continue;
            }

            boats[i].trainingManager  = this;
            boats[i].boundaryCenter   = waterCenter != null ? waterCenter.position : Vector3.zero;
            boats[i].boundaryRadius   = waterAreaRadius;
            goalMarkers[i]            = CreateGoalMarker(i);

            // 초기 목표 & 장애물 배치 — 스폰 위치를 직접 전달
            AssignGoalAndObstacles(i, spawnPos);
        }

        Debug.Log($"[BoatTrainingManager] {boatCount}척 초기화 완료 | " +
                  $"난이도={currentDifficultyLevel} | 장애물={GetObstacleCount()}개");
    }

    // ═══════════════════════════════════════════════════════════════════
    // BoatColregAgent → BoatTrainingManager 콜백
    // ═══════════════════════════════════════════════════════════════════

    /// <summary>에피소드 시작마다 호출. 배를 중심 영역에 재배치하고 목표·장애물을 새로 설정한다.</summary>
    public void OnBoatEpisodeBegin(BoatColregAgent boat)
    {
        int idx = IndexOf(boat);
        if (idx < 0) return;

        // 배 위치/방향 재배치 (경계 이탈 후 같은 자리에서 재시작 방지)
        Vector3 center = waterCenter != null ? waterCenter.position : Vector3.zero;
        Vector2 rnd    = Random.insideUnitCircle * (waterAreaRadius * SpawnRadiusFraction);
        Vector3 newPos = new Vector3(center.x + rnd.x, center.y, center.z + rnd.y);
        Quaternion newRot = Quaternion.Euler(0f, Random.Range(0f, 360f), 0f);

        // transform 대신 Rigidbody API 사용 (물리 엔진이 이전 속도를 유지하는 문제 방지)
        Rigidbody boatRb = boats[idx].GetComponent<Rigidbody>();
        if (boatRb != null)
        {
            boatRb.position = newPos;
            boatRb.rotation = newRot;
        }
        else
        {
            boats[idx].transform.position = newPos;
            boats[idx].transform.rotation = newRot;
        }

        // transform.position이 아닌 newPos를 직접 전달 — rb.position 설정 직후
        // transform 동기화 타이밍에 무관하게 올바른 위치 기준으로 목표를 생성
        AssignGoalAndObstacles(idx, newPos);
    }

    /// <summary>목표 도달 시 호출. 성공 기록 후 커리큘럼 갱신.</summary>
    public void OnBoatReachedGoal(BoatColregAgent boat)
    {
        RecordResult(true);
        TryDifficultyUp();
        int idx = IndexOf(boat);
        Debug.Log($"[BoatTrainingManager] Boat_{idx} 목표 도달 | " +
                  $"성공률={GetSuccessRate():P0} 난이도={currentDifficultyLevel}");
    }

    /// <summary>충돌 또는 타임아웃 시 호출. 실패 기록 후 커리큘럼 조정.</summary>
    public void OnBoatFailed(BoatColregAgent boat)
    {
        RecordResult(false);
        TryDifficultyDown();
        int idx = IndexOf(boat);
        Debug.Log($"[BoatTrainingManager] Boat_{idx} 실패 | 성공률={GetSuccessRate():P0}");
    }

    // ═══════════════════════════════════════════════════════════════════
    // 목표 & 장애물 배치
    // ═══════════════════════════════════════════════════════════════════

    private void AssignGoalAndObstacles(int idx, Vector3 boatPos)
    {
        if (boats[idx] == null) return;

        Vector3 goalPos = RandomGoalPosition(boatPos);

        goalMarkers[idx].transform.position = goalPos;
        boats[idx].SetGoal(goalMarkers[idx].transform);

        ClearObstacles(idx);
        PlacePathObstacles(idx, boatPos, goalPos);
    }

    /// <summary>
    /// 선박 i의 이상 경로(직선) 위에 N개의 장애물을 배치한다.
    ///
    /// 배치 규칙:
    ///   - 경로를 obstaclesPerLevel 수만큼 균등 분할 후 각 구간 중점에 배치
    ///   - 각 장애물에 법선 방향 랜덤 오프셋을 주어 회피 필요성 부여
    ///   - 오프셋이 너무 크면 장애물이 경로를 완전히 벗어나므로 obstaclePathOffset 조절 권장
    ///   - 선박 전용 레이어 할당 → 타 선박은 이 장애물에 물리 반응 없음
    /// </summary>
    private void PlacePathObstacles(int idx, Vector3 start, Vector3 goal)
    {
        int count = GetObstacleCount();
        if (count <= 0 || obstaclePrefab == null) return;

        Vector3 pathVec  = goal - start;
        pathVec.y        = 0f;
        float pathLen    = pathVec.magnitude;
        if (pathLen < 1f) return;

        Vector3 fwd  = pathVec / pathLen;
        Vector3 perp = Vector3.Cross(fwd, Vector3.up).normalized; // 법선 (수평)

        int layer = layerBase + idx;

        for (int i = 0; i < count; i++)
        {
            // 균등 분할 비율 + 소량 랜덤 흔들기 (장애물이 똑같이 줄 서지 않도록)
            float tBase = Mathf.Lerp(obstacleStartFraction, obstacleEndFraction,
                                     (i + 0.5f) / count);
            float t = Mathf.Clamp(tBase + Random.Range(-0.04f, 0.04f),
                                  obstacleStartFraction, obstacleEndFraction);

            // 법선 오프셋: 오른쪽/왼쪽 교차 배치 → 배가 지그재그로 피해야 함
            float side = (i % 2 == 0 ? 1f : -1f)
                         * Random.Range(obstaclePathOffset * 0.3f, obstaclePathOffset);

            Vector3 pos = start + fwd * (t * pathLen) + perp * side;
            pos.y       = start.y; // 수면 높이 유지

            GameObject obs = Instantiate(obstaclePrefab, pos,
                                         Quaternion.Euler(0f, Random.Range(0f, 360f), 0f));
            obs.name = $"PathObs_Boat{idx}_{i}";

            // 전용 레이어 → 다른 선박은 이 장애물을 물리적으로 무시
            SetLayerRecursive(obs, layer);
            
            // 장애물의 Rigidbody도 isKinematic으로 설정 (물리 시뮬레이션 비활성화)
            Rigidbody obsRb = obs.GetComponent<Rigidbody>();
            if (obsRb != null)
                obsRb.isKinematic = true;

            pathObstacles[idx].Add(obs);
        }

        Debug.Log($"[BoatTrainingManager] Boat_{idx} 장애물 {count}개 배치 완료");
    }

    private void ClearObstacles(int idx)
    {
        foreach (var obs in pathObstacles[idx])
            if (obs != null) Destroy(obs);
        pathObstacles[idx].Clear();
    }

    // ═══════════════════════════════════════════════════════════════════
    // 위치 생성
    // ═══════════════════════════════════════════════════════════════════

    /// <summary>이미 사용된 위치들과 minSpacing 이상 떨어진 수면 위 위치를 반환한다.</summary>
    private Vector3 RandomWaterPosition(List<Vector3> occupied, float minSpacing)
    {
        Vector3 center = waterCenter != null ? waterCenter.position : Vector3.zero;

        float spawnRadius = waterAreaRadius * SpawnRadiusFraction;
        for (int attempt = 0; attempt < 300; attempt++)
        {
            Vector2 rnd = Random.insideUnitCircle * spawnRadius;
            Vector3 candidate = new Vector3(center.x + rnd.x, center.y, center.z + rnd.y);

            bool tooClose = false;
            foreach (Vector3 used in occupied)
            {
                if (Vector3.Distance(candidate, used) < minSpacing)
                {
                    tooClose = true;
                    break;
                }
            }
            if (!tooClose) return candidate;
        }

        Debug.LogWarning("[BoatTrainingManager] 충분한 간격의 스폰 위치를 찾지 못해 기본값 반환");
        Vector2 fallback = Random.insideUnitCircle * spawnRadius * 0.5f;
        return new Vector3(
            (waterCenter != null ? waterCenter.position.x : 0f) + fallback.x,
            waterCenter != null ? waterCenter.position.y : 0f,
            (waterCenter != null ? waterCenter.position.z : 0f) + fallback.y
        );
    }

    /// <summary>선박 위치에서 goalMinDistance ~ goalMaxDistance 범위의 목표 위치를 반환한다.</summary>
    private Vector3 RandomGoalPosition(Vector3 boatPos)
    {
        Vector3 center = waterCenter != null ? waterCenter.position : Vector3.zero;

        for (int attempt = 0; attempt < 300; attempt++)
        {
            Vector2 rnd = Random.insideUnitCircle * waterAreaRadius;
            Vector3 candidate = new Vector3(center.x + rnd.x, boatPos.y, center.z + rnd.y);

            float dist = new Vector2(candidate.x - boatPos.x,
                                     candidate.z - boatPos.z).magnitude;
            if (dist >= goalMinDistance && dist <= goalMaxDistance)
                return candidate;
        }

        // 방향 고정 폴백: 선수 정면으로 goalMinDistance
        Vector3 dir = boatPos + Vector3.forward * goalMinDistance;
        return new Vector3(dir.x, boatPos.y, dir.z);
    }

    // ═══════════════════════════════════════════════════════════════════
    // 커리큘럼
    // ═══════════════════════════════════════════════════════════════════

    private int GetObstacleCount()
    {
        int level = Mathf.Clamp(currentDifficultyLevel, 0, obstaclesPerLevel.Length - 1);
        return obstaclesPerLevel[level];
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
        int ok = 0;
        foreach (bool r in recentResults) if (r) ok++;
        return (float)ok / recentResults.Count;
    }

    private void TryDifficultyUp()
    {
        if (recentResults.Count < evaluationWindow) return;
        if (GetSuccessRate() < successRateThreshold) return;
        if (currentDifficultyLevel >= obstaclesPerLevel.Length - 1) return;

        currentDifficultyLevel++;
        recentResults.Clear();
        Debug.Log($"[BoatTrainingManager] 난이도 상향 → 레벨 {currentDifficultyLevel} " +
                  $"({GetObstacleCount()}개 장애물)");
    }

    private void TryDifficultyDown()
    {
        if (recentResults.Count < evaluationWindow) return;
        if (GetSuccessRate() >= 0.3f) return;
        if (currentDifficultyLevel <= 0) return;

        currentDifficultyLevel--;
        recentResults.Clear();
        Debug.Log($"[BoatTrainingManager] 성공률 저조 → 난이도 하향: 레벨 {currentDifficultyLevel}");
    }

    // ═══════════════════════════════════════════════════════════════════
    // 유틸리티
    // ═══════════════════════════════════════════════════════════════════

    private int IndexOf(BoatColregAgent boat)
    {
        for (int i = 0; i < boats.Length; i++)
            if (boats[i] == boat) return i;
        return -1;
    }

    private static void SetLayerRecursive(GameObject obj, int layer)
    {
        obj.layer = layer;
        foreach (Transform t in obj.GetComponentsInChildren<Transform>(true))
            t.gameObject.layer = layer;
    }

    private static GameObject CreateGoalMarker(int idx)
    {
        GameObject root = new GameObject($"BoatGoal_{idx}");

        GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        sphere.transform.SetParent(root.transform);
        sphere.transform.localPosition = Vector3.zero;
        sphere.transform.localScale    = Vector3.one * 0.6f;
        Object.Destroy(sphere.GetComponent<Collider>());
        sphere.GetComponent<Renderer>().material.color = Color.green;

        return root;
    }

    // ── 공개 상태 조회 ──────────────────────────────────────────────────
    public int   GetCurrentDifficultyLevel() => currentDifficultyLevel;
    public float GetCurrentSuccessRate()     => GetSuccessRate();
    public int   GetObstacleCountInfo()      => GetObstacleCount();

    /// <summary>COLREGS 판정을 위해 자선을 제외한 가장 가까운 타선을 반환한다.</summary>
    public BoatColregAgent GetNearestOtherBoat(BoatColregAgent self)
    {
        if (boats == null) return null;
        BoatColregAgent nearest = null;
        float           minDist = float.MaxValue;
        foreach (var b in boats)
        {
            if (b == null || b == self) continue;
            float d = Vector3.Distance(self.transform.position, b.transform.position);
            if (d < minDist) { minDist = d; nearest = b; }
        }
        return nearest;
    }

    // ── 에디터 시각화 (Gizmos) ──────────────────────────────────────────
    private void OnDrawGizmosSelected()
    {
        Vector3 center = waterCenter != null ? waterCenter.position : Vector3.zero;

        // 수역 범위
        Gizmos.color = new Color(0f, 0.5f, 1f, 0.25f);
        Gizmos.DrawWireSphere(center, waterAreaRadius);

        // 목표 최소/최대 거리 (첫 선박 기준 예시)
        if (boats != null && boats.Length > 0 && boats[0] != null)
        {
            Gizmos.color = new Color(1f, 1f, 0f, 0.2f);
            Gizmos.DrawWireSphere(boats[0].transform.position, goalMinDistance);
            Gizmos.color = new Color(0f, 1f, 0f, 0.15f);
            Gizmos.DrawWireSphere(boats[0].transform.position, goalMaxDistance);
        }
    }
}
