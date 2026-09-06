using UnityEngine;
using UnityEngine.AI;
using System.Collections.Generic;

/// <summary>
/// BoatAgent의 로컬 경로 재주행 중 B키로 현재 경로 앞쪽에 부표를 생성합니다.
/// 부표가 생성되면 기존 재주행을 중단하고,
/// 현재 함선 위치에서 GoalPoint까지 ML-Agent 정책으로 새 경로를 다시 생성합니다.
///
/// 재탐색된 경로의 로컬 재주행이 시작되면 B키를 다시 눌러
/// 같은 미션에서 여러 번 재탐색할 수 있습니다.
/// </summary>
public class BoatBuoyReplanController : MonoBehaviour
{
    [Header("References")]
    [Tooltip("같은 Boat 오브젝트의 BoatAgent를 연결합니다.")]
    public BoatAgent boatAgent;

    [Tooltip("경로 위에 생성할 부표 프리팹입니다.")]
    public GameObject buoyPrefab;

    [Tooltip("생성된 부표를 정리할 부모 Transform입니다. 비워도 됩니다.")]
    public Transform buoyParent;

    [Header("Input")]
    [Tooltip("로컬 경로 재주행 중 부표를 생성하고 ML-Agent 재탐색을 시작합니다.")]
    public KeyCode spawnBuoyKey = KeyCode.B;

    [Tooltip("현재까지 생성한 모든 런타임 부표를 제거합니다.")]
    public KeyCode clearBuoysKey = KeyCode.C;

    [Header("Multiple Buoys")]
    [Tooltip("한 미션에서 생성할 수 있는 부표 개수입니다. 0이면 제한 없이 여러 번 생성할 수 있습니다.")]
    [Min(0)]
    public int maxRuntimeBuoys = 0;

    [Tooltip("B키 연속 입력으로 부표가 중복 생성되는 것을 막는 최소 간격입니다.")]
    [Min(0f)]
    public float minimumSpawnInterval = 0.5f;

    [Tooltip("새 부표를 만들 때 이전 부표를 유지합니다. 여러 번 재탐색하려면 체크합니다.")]
    public bool keepPreviousBuoys = true;

    [Header("Spawn Position")]
    [Tooltip("함선 현재 위치에서 재주행 경로를 따라 이 거리 앞에 부표를 생성합니다.")]
    [Min(1f)]
    public float spawnLookAheadDistance = 12f;

    [Tooltip("경로 위치에 더할 Y축 오프셋입니다.")]
    public float buoyYOffset = 0f;

    [Tooltip("남은 경로가 Look Ahead 거리보다 짧을 때 목표 바로 앞에 부표를 생성하지 않도록 하는 최소 목표 여유 거리입니다.")]
    [Min(0f)]
    public float minimumDistanceFromGoal = 5f;

    [Header("Obstacle Configuration")]
    [Tooltip("부표에 Collider가 없으면 BoxCollider를 자동으로 추가합니다.")]
    public bool addColliderIfMissing = true;

    [Tooltip("부표에 NavMeshObstacle이 없으면 자동으로 추가하고 Carving을 활성화합니다.")]
    public bool autoConfigureNavMeshObstacle = true;

    [Tooltip("NavMesh에서 차단할 부표 영역의 XZ 크기입니다.")]
    public Vector2 carvingSizeXZ = new Vector2(6f, 6f);

    [Tooltip("NavMeshObstacle 높이입니다.")]
    [Min(0.1f)]
    public float carvingHeight = 2f;

    [Tooltip("부표 생성 후 NavMeshObstacle Carving 반영을 기다린 뒤 ML-Agent 재탐색을 시작합니다.")]
    [Min(0f)]
    public float carvingWaitSeconds = 0.6f;

    [Header("Optional Obstacle Tag/Layer")]
    [Tooltip("체크하면 생성된 부표의 Tag를 지정합니다. 프로젝트에 해당 Tag가 미리 등록되어 있어야 합니다.")]
    public bool assignObstacleTag = false;

    public string obstacleTag = "Obstacle";

    [Tooltip("-1이면 프리팹의 기존 Layer를 유지합니다.")]
    public int obstacleLayer = -1;

    [Header("Debug")]
    public bool printDebugLogs = true;
    public bool drawLastSpawnPoint = true;

    private readonly List<GameObject> runtimeBuoys =
        new List<GameObject>();

    private float lastSpawnTime = -999f;
    private Vector3 lastSpawnPoint;
    private bool hasLastSpawnPoint = false;

    private void Awake()
    {
        if (boatAgent == null)
            boatAgent = GetComponent<BoatAgent>();
    }

    private void Update()
    {
        if (Input.GetKeyDown(clearBuoysKey))
            RemoveAllRuntimeBuoys();

        if (Input.GetKeyDown(spawnBuoyKey))
            TrySpawnBuoyAndRequestMlReplan();
    }

    [ContextMenu("Spawn Buoy And ML-Agent Replan")]
    public void TrySpawnBuoyAndRequestMlReplan()
    {
        if (boatAgent == null)
        {
            Debug.LogWarning(
                "[BoatBuoyReplanController] BoatAgent가 연결되지 않았습니다."
            );
            return;
        }

        // B키는 '새 경로를 실제로 재주행하는 단계'에서 다시 사용할 수 있습니다.
        // ML-Agent가 새 경로를 만드는 동안에는 아직 배치 기준 경로가 없으므로 입력을 받지 않습니다.
        if (!boatAgent.IsLocalGeneratedPathReplayActive())
        {
            string state = boatAgent.IsLocalReplayMlAgentReplanPending()
                ? "현재 ML-Agent 재탐색 준비 중입니다."
                : "현재 생성 경로 재주행 중이 아닙니다.";

            Debug.LogWarning(
                $"[BoatBuoyReplanController] {state} " +
                "새 경로의 재주행이 시작된 뒤 B키를 다시 누르세요."
            );
            return;
        }

        if (Time.time - lastSpawnTime < minimumSpawnInterval)
            return;

        CleanupDestroyedBuoys();

        if (maxRuntimeBuoys > 0 &&
            runtimeBuoys.Count >= maxRuntimeBuoys)
        {
            Debug.LogWarning(
                $"[BoatBuoyReplanController] 최대 부표 개수에 도달했습니다. " +
                $"current={runtimeBuoys.Count}, max={maxRuntimeBuoys}"
            );
            return;
        }

        if (buoyPrefab == null)
        {
            Debug.LogWarning(
                "[BoatBuoyReplanController] Buoy Prefab이 연결되지 않았습니다."
            );
            return;
        }

        Vector3[] replayPath =
            boatAgent.GetLocalReplayPathSnapshot();

        Vector3 spawnPoint;
        bool found = TryFindPointAheadOnPath(
            replayPath,
            boatAgent.transform.position,
            spawnLookAheadDistance,
            minimumDistanceFromGoal,
            out spawnPoint
        );

        if (!found)
        {
            Debug.LogWarning(
                "[BoatBuoyReplanController] 현재 경로에서 부표를 생성할 적절한 앞쪽 지점을 찾지 못했습니다."
            );
            return;
        }

        if (!keepPreviousBuoys)
            RemoveAllRuntimeBuoys();

        spawnPoint.y += buoyYOffset;

        GameObject buoy = Instantiate(
            buoyPrefab,
            spawnPoint,
            buoyPrefab.transform.rotation,
            buoyParent
        );

        buoy.name =
            $"{buoyPrefab.name}_Runtime_{runtimeBuoys.Count + 1}";

        ConfigureObstacle(buoy);
        Physics.SyncTransforms();

        runtimeBuoys.Add(buoy);
        lastSpawnTime = Time.time;
        lastSpawnPoint = spawnPoint;
        hasLastSpawnPoint = true;

        bool accepted =
            boatAgent.RequestMlAgentReplanFromLocalReplay(
                $"buoy_{runtimeBuoys.Count}",
                carvingWaitSeconds
            );

        if (!accepted)
        {
            runtimeBuoys.Remove(buoy);
            Destroy(buoy);

            Debug.LogWarning(
                "[BoatBuoyReplanController] ML-Agent 재탐색 요청이 거절되어 방금 생성한 부표를 제거했습니다."
            );
            return;
        }

        if (printDebugLogs)
        {
            Debug.Log(
                $"[BoatBuoyReplanController] 부표 생성 + ML-Agent 재탐색 요청 | " +
                $"buoyIndex={runtimeBuoys.Count}, " +
                $"position={spawnPoint}, " +
                $"mlReplanCount={boatAgent.GetLocalReplayMlAgentReplanCount()}"
            );
        }
    }

    private void ConfigureObstacle(GameObject buoy)
    {
        if (buoy == null)
            return;

        if (obstacleLayer >= 0 &&
            obstacleLayer <= 31)
        {
            SetLayerRecursively(
                buoy,
                obstacleLayer
            );
        }

        if (assignObstacleTag &&
            !string.IsNullOrWhiteSpace(obstacleTag))
        {
            try
            {
                buoy.tag = obstacleTag;
            }
            catch (UnityException)
            {
                Debug.LogWarning(
                    $"[BoatBuoyReplanController] Tag '{obstacleTag}'가 등록되어 있지 않아 Tag 적용을 건너뜁니다."
                );
            }
        }

        if (addColliderIfMissing &&
            buoy.GetComponentInChildren<Collider>() == null)
        {
            BoxCollider collider =
                buoy.AddComponent<BoxCollider>();

            collider.center = new Vector3(
                0f,
                carvingHeight * 0.5f,
                0f
            );

            collider.size = new Vector3(
                Mathf.Max(0.1f, carvingSizeXZ.x),
                Mathf.Max(0.1f, carvingHeight),
                Mathf.Max(0.1f, carvingSizeXZ.y)
            );
        }

        if (!autoConfigureNavMeshObstacle)
            return;

        NavMeshObstacle obstacle =
            buoy.GetComponent<NavMeshObstacle>();

        if (obstacle == null)
            obstacle = buoy.AddComponent<NavMeshObstacle>();

        obstacle.shape = NavMeshObstacleShape.Box;

        obstacle.center = new Vector3(
            0f,
            carvingHeight * 0.5f,
            0f
        );

        obstacle.size = new Vector3(
            Mathf.Max(0.1f, carvingSizeXZ.x),
            Mathf.Max(0.1f, carvingHeight),
            Mathf.Max(0.1f, carvingSizeXZ.y)
        );

        obstacle.carving = true;
        obstacle.carveOnlyStationary = false;
        obstacle.carvingMoveThreshold = 0.01f;
        obstacle.carvingTimeToStationary = 0.1f;
    }

    private static bool TryFindPointAheadOnPath(
        Vector3[] path,
        Vector3 currentPosition,
        float lookAheadDistance,
        float minimumGoalClearance,
        out Vector3 result
    )
    {
        result = currentPosition;

        if (path == null || path.Length < 2)
            return false;

        int closestSegment = 0;
        float closestT = 0f;
        float closestDistanceSqr = float.MaxValue;

        Vector3 planarCurrent = currentPosition;
        planarCurrent.y = 0f;

        for (int i = 0; i < path.Length - 1; i++)
        {
            Vector3 a = path[i];
            Vector3 b = path[i + 1];
            a.y = 0f;
            b.y = 0f;

            Vector3 ab = b - a;
            float lengthSqr = ab.sqrMagnitude;

            float t = lengthSqr > 0.000001f
                ? Mathf.Clamp01(
                    Vector3.Dot(
                        planarCurrent - a,
                        ab
                    ) / lengthSqr
                )
                : 0f;

            Vector3 closest = a + ab * t;
            float distanceSqr =
                (planarCurrent - closest).sqrMagnitude;

            if (distanceSqr < closestDistanceSqr)
            {
                closestDistanceSqr = distanceSqr;
                closestSegment = i;
                closestT = t;
            }
        }

        Vector3 segmentStart = Vector3.Lerp(
            path[closestSegment],
            path[closestSegment + 1],
            closestT
        );

        float remainingToGoal = 0f;
        remainingToGoal += Vector3.Distance(
            segmentStart,
            path[closestSegment + 1]
        );

        for (int i = closestSegment + 1;
             i < path.Length - 1;
             i++)
        {
            remainingToGoal += Vector3.Distance(
                path[i],
                path[i + 1]
            );
        }

        float required =
            Mathf.Max(0f, lookAheadDistance) +
            Mathf.Max(0f, minimumGoalClearance);

        if (remainingToGoal < required)
            return false;

        float remainingLookAhead =
            Mathf.Max(0f, lookAheadDistance);

        for (int i = closestSegment;
             i < path.Length - 1;
             i++)
        {
            Vector3 a =
                i == closestSegment
                    ? segmentStart
                    : path[i];

            Vector3 b = path[i + 1];

            float segmentLength =
                Vector3.Distance(a, b);

            if (segmentLength >= remainingLookAhead)
            {
                float ratio =
                    segmentLength > 0.000001f
                        ? remainingLookAhead /
                          segmentLength
                        : 0f;

                result = Vector3.Lerp(
                    a,
                    b,
                    ratio
                );

                return true;
            }

            remainingLookAhead -= segmentLength;
        }

        return false;
    }

    private static void SetLayerRecursively(
        GameObject root,
        int layer
    )
    {
        root.layer = layer;

        foreach (Transform child in root.transform)
        {
            if (child != null)
                SetLayerRecursively(
                    child.gameObject,
                    layer
                );
        }
    }

    private void CleanupDestroyedBuoys()
    {
        for (int i = runtimeBuoys.Count - 1;
             i >= 0;
             i--)
        {
            if (runtimeBuoys[i] == null)
                runtimeBuoys.RemoveAt(i);
        }
    }

    [ContextMenu("Remove All Runtime Buoys")]
    public void RemoveAllRuntimeBuoys()
    {
        for (int i = 0;
             i < runtimeBuoys.Count;
             i++)
        {
            if (runtimeBuoys[i] != null)
                Destroy(runtimeBuoys[i]);
        }

        runtimeBuoys.Clear();
        hasLastSpawnPoint = false;

        if (printDebugLogs)
        {
            Debug.Log(
                "[BoatBuoyReplanController] 모든 런타임 부표를 제거했습니다."
            );
        }
    }

    private void OnDrawGizmosSelected()
    {
        if (!drawLastSpawnPoint ||
            !hasLastSpawnPoint)
        {
            return;
        }

        Gizmos.color = Color.magenta;
        Gizmos.DrawWireSphere(
            lastSpawnPoint,
            0.5f
        );
    }
}
