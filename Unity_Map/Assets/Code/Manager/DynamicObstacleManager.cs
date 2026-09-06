using UnityEngine;
using UnityEngine.AI;
using Unity.MLAgents;
using System.Collections;
using System.Collections.Generic;

public class DynamicObstacleManager : MonoBehaviour
{
    [Header("설정")]
    public GameObject obstaclePrefab;
    public int maxObstacles = 5;
    public float spawnInterval = 30f;
    public float minDistFromAgent = 2f;
    public float minDistFromGoal = 2f;

    [Header("장애물 유지/제거 설정")]
    public float removeAfterSeconds = 120f;

    private Dictionary<GameObject, float> lastHitRealtime = new Dictionary<GameObject, float>();
    private List<GameObject> activeObstacles = new List<GameObject>();
    private GO1Agent[] agents;

    void Start()
    {
        agents = FindObjectsByType<GO1Agent>(FindObjectsSortMode.None);
        StartCoroutine(SpawnObstaclesRoutine());
        StartCoroutine(CheckObstaclesRoutine());
    }

    IEnumerator SpawnObstaclesRoutine()
    {
        yield return new WaitForSecondsRealtime(3f);
        SpawnNewObstacles();

        while (true)
        {
            yield return new WaitForSecondsRealtime(spawnInterval);
            SpawnNewObstacles();
        }
    }

    IEnumerator CheckObstaclesRoutine()
    {
        while (true)
        {
            yield return new WaitForSecondsRealtime(10f);
            RemoveInactiveObstacles();
        }
    }

    bool IsAnyAgentRunningMission()
    {
        agents = FindObjectsByType<GO1Agent>(FindObjectsSortMode.None);

        foreach (var agent in agents)
        {
            if (agent == null) continue;

            // GO1Agent.IsMoving()은 M키로 가상 경로를 생성 중이거나,
            // C++ 실제 GO1이 waypoint 경로를 따라가는 중이면 true를 반환한다.
            if (agent.IsMoving())
                return true;
        }

        return false;
    }

    void SpawnNewObstacles()
    {
        if (IsAnyAgentRunningMission())
        {
            Debug.Log("[DynamicObstacleManager] M키 자율주행 동작 중이므로 장애물 생성을 건너뜁니다.");
            return;
        }

        if (Academy.Instance.IsCommunicatorOn)
            agents = FindObjectsByType<GO1Agent>(FindObjectsSortMode.None);

        activeObstacles.RemoveAll(obs => obs == null);

        int toSpawn = maxObstacles - activeObstacles.Count;
        if (toSpawn <= 0)
        {
            Debug.Log("[DynamicObstacleManager] 최대 장애물 수 도달");
            return;
        }

        int placed = 0;
        int attempts = 0;

        while (placed < toSpawn && attempts < 100)
        {
            attempts++;
            Vector3 pos = GetRandomNavMeshPoint();

            if (pos == Vector3.zero) continue;
            if (IsTooCloseToAgents(pos)) continue;
            if (IsTooCloseToGoals(pos)) continue;
            if (IsTooCloseToExistingObstacles(pos)) continue;

            GameObject obs = Instantiate(
                obstaclePrefab,
                pos,
                Quaternion.Euler(0, Random.Range(0f, 360f), 0));

            ObstacleHitDetector detector = obs.AddComponent<ObstacleHitDetector>();
            detector.manager = this;

            activeObstacles.Add(obs);
            lastHitRealtime[obs] = Time.realtimeSinceStartup;

            placed++;
        }

        Debug.Log($"[DynamicObstacleManager] 장애물 {placed}개 추가 " +
                  $"(총 {activeObstacles.Count}개)");
    }

    void RemoveInactiveObstacles()
    {
        List<GameObject> toRemove = new List<GameObject>();

        foreach (var obs in activeObstacles)
        {
            if (obs == null) continue;

            float hitRealtime = lastHitRealtime.ContainsKey(obs)
                ? lastHitRealtime[obs] : -1f;

            bool longTimeNoHit = hitRealtime >= 0f &&
                (Time.realtimeSinceStartup - hitRealtime) > removeAfterSeconds;

            if (longTimeNoHit)
            {
                Debug.Log($"[DynamicObstacleManager] 장애물 제거 ({removeAfterSeconds}초 경과)");
                toRemove.Add(obs);
            }
        }

        foreach (var obs in toRemove)
        {
            activeObstacles.Remove(obs);
            lastHitRealtime.Remove(obs);
            Destroy(obs);
        }

        if (toRemove.Count > 0)
            SpawnNewObstacles();
    }

    public void OnObstacleHit(GameObject obstacle)
    {
        if (lastHitRealtime.ContainsKey(obstacle))
        {
            lastHitRealtime[obstacle] = Time.realtimeSinceStartup;
            Debug.Log($"[DynamicObstacleManager] 장애물 충돌! 타이머 리셋");
        }
    }

    bool IsTooCloseToAgents(Vector3 pos)
    {
        foreach (var agent in agents)
        {
            if (agent == null) continue;
            if (Vector3.Distance(pos, agent.transform.position) < minDistFromAgent)
                return true;
        }
        return false;
    }

    bool IsTooCloseToGoals(Vector3 pos)
    {
        foreach (var agent in agents)
        {
            if (agent == null) continue;
            if (agent.target == null) continue;
            if (Vector3.Distance(pos, agent.target.position) < minDistFromGoal)
                return true;
        }
        return false;
    }

    bool IsTooCloseToExistingObstacles(Vector3 pos)
    {
        foreach (var obs in activeObstacles)
        {
            if (obs == null) continue;
            if (Vector3.Distance(pos, obs.transform.position) < 1.5f)
                return true;
        }
        return false;
    }

    Vector3 GetRandomNavMeshPoint()
    {
        NavMeshTriangulation tri = NavMesh.CalculateTriangulation();
        if (tri.vertices.Length == 0) return Vector3.zero;

        for (int attempt = 0; attempt < 30; attempt++)
        {
            int triIdx = Random.Range(0, tri.indices.Length / 3) * 3;
            Vector3 v0 = tri.vertices[tri.indices[triIdx]];
            Vector3 v1 = tri.vertices[tri.indices[triIdx + 1]];
            Vector3 v2 = tri.vertices[tri.indices[triIdx + 2]];

            float r1 = Mathf.Sqrt(Random.value);
            float r2 = Random.value;
            Vector3 candidate = (1 - r1) * v0 + r1 * (1 - r2) * v1 + r1 * r2 * v2;

            NavMeshHit hit;
            if (NavMesh.SamplePosition(candidate, out hit, 1f, NavMesh.AllAreas))
                return hit.position;
        }

        return Vector3.zero;
    }

    public void ForceUpdate()
    {
        if (IsAnyAgentRunningMission())
        {
            Debug.Log("[DynamicObstacleManager] M키 자율주행 동작 중이므로 ForceUpdate 장애물 생성을 건너뜁니다.");
            return;
        }

        SpawnNewObstacles();
    }

    public void ClearAll()
    {
        foreach (var obs in activeObstacles)
        {
            if (obs != null)
                Destroy(obs);
        }
        activeObstacles.Clear();
        lastHitRealtime.Clear();
    }

    void OnDestroy()
    {
        ClearAll();
    }
}