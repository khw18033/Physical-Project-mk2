using UnityEngine;
using UnityEngine.AI;
using Unity.MLAgents;
using UnityEngine.Networking;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;

/// <summary>
/// 서버의 detection JSON을 주기적으로 받아서 Unity 장애물로 표시하고,
/// 현재 GO1 경로를 막는 장애물이 감지되면 C++ 경로를 취소한 뒤
/// 현재 실제 GO1 pose 기준으로 GO1Agent가 새 경로를 다시 생성하도록 한다.
///
/// 핵심 보완:
/// - detection은 0.2초마다 들어와도 재탐색은 안정 조건을 만족할 때만 수행.
/// - 같은 track_id 장애물은 기본적으로 15초 동안 재탐색 금지.
/// - 단, 장애물이 실제로 많이 움직였다고 판단되면 15초 안에도 재탐색 허용.
/// - GO1 자체 이동 때문에 장애물 world position이 흔들리는 경우를 줄이기 위해
///   GO1 이동량이 큰 상태에서는 "움직였다" 판단을 보수적으로 처리.
/// </summary>
public class ObstacleDetection : MonoBehaviour
{
    [Header("Detection Server")]
    public string detectionUrl = "http://210.110.250.33:5001/detections/go1_front";
    public float pollInterval = 0.2f;
    public bool logReceivedJson = true;
    public bool saveJsonLogToFile = true;
    public string logFilePath = "ObstacleDetectionLog.txt";

    [Header("Obstacle Object")]
    public GameObject obstaclePrefab;
    public Transform go1Transform;

    [Tooltip("position_cam 좌표를 바닥에 투영해서 y를 고정할지 여부")]
    public bool projectObstacleToGround = true;
    public float groundY = 0f;

    [Tooltip("GO1 기준 카메라 오프셋. 필요 없으면 (0,0,0)")]
    public Vector3 cameraOffsetLocal = Vector3.zero;

    [Tooltip("이 프로젝트의 GO1 전진 방향이 -transform.right이면 체크")]
    public bool useNegativeRightAsForward = true;

    [Tooltip("bbox 크기로 오브젝트 스케일을 바꿀지 여부")]
    public bool scaleFromBoundingBox = false;

    public Vector3 defaultObstacleScale = new Vector3(0.5f, 0.5f, 0.5f);
    public float bboxScaleDivider = 100.0f;
    public float minObstacleScale = 0.2f;
    public float maxObstacleScale = 2.0f;

    [Header("Detection Filter")]
    public float confidenceThreshold = 0.4f;

    [Tooltip("distance_m이 이 값보다 크면 장애물 표시/재탐색에서 제외. 0 이하이면 거리 필터 미사용")]
    public float maxDetectionDistance = 6.0f;

    [Tooltip("감지에서 사라진 obstacle을 바로 삭제하지 않고 유지할 시간")]
    public float missingObstacleTimeout = 0.6f;

    [Header("NavMeshObstacle")]
    public bool addNavMeshObstacle = true;
    public bool carveNavMeshObstacle = true;
    public float navMeshObstacleHeight = 1.0f;
    public float navMeshCarveSettleDelay = 0.2f;

    [Header("Replan")]
    public bool enableReplan = true;

    [Tooltip("장애물이 agent-target 경로 근처에 있을 때만 재탐색")]
    public bool onlyReplanIfNearPath = true;

    [Tooltip("장애물이 현재 NavMesh path에서 이 거리 이내면 경로를 막는다고 판단")]
    public float obstacleAffectsPathDistance = 0.8f;

    [Tooltip("전체 재탐색 최소 간격. 여러 장애물이 동시에 들어와도 너무 자주 재탐색하지 않도록 제한")]
    public float replanCooldownSeconds = 2.0f;

    [Tooltip("C++ PATH_CANCEL 이후 대기 시간")]
    public float replanDelayAfterCancel = 0.35f;

    [Tooltip("서버 detection의 reaction 값이 stop/avoid/block 계열일 때만 재탐색")]
    public bool useReactionFilter = false;

    [Header("Replan Stability Filter")]
    [Tooltip("장애물이 경로 근처에 이 시간 이상 계속 있어야 최초 재탐색 허용")]
    public float requiredObstacleStableTime = 1.0f;

    [Tooltip("같은 track_id 장애물은 재탐색 후 이 시간 동안 재탐색 금지")]
    public float sameObstacleReplanBlockTime = 15.0f;

    [Tooltip("15초 금지 중에도 장애물이 이 거리 이상 움직이면 재탐색 후보로 판단")]
    public float obstacleMoveReplanThreshold = 0.6f;

    [Tooltip("움직임이 이 시간 이상 지속되어야 실제 이동으로 보고 재탐색")]
    public float movedObstacleStableTime = 0.8f;

    [Tooltip("장애물 위치 smoothing. 0이면 smoothing 없음, 0.7이면 이전값 70%, 새값 30%")]
    [Range(0f, 0.95f)]
    public float obstaclePositionSmoothing = 0.5f;

    [Header("Ego Motion Guard")]
    [Tooltip("GO1 이동 때문에 정적 장애물이 움직인 것처럼 보이는 현상 완화")]
    public bool guardAgainstGo1MotionFalseMove = true;

    [Tooltip("마지막 재탐색 이후 GO1이 이 거리 이상 움직였으면, 장애물 이동 override를 더 보수적으로 판단")]
    public float go1MotionIgnoreDistance = 0.25f;

    [Tooltip("GO1이 움직인 상태에서 서버 motion/reaction이 움직임을 명시하지 않으면, 이 거리 이상 움직였을 때만 override 허용")]
    public float largeMoveOverrideWhenGo1Moved = 1.0f;

    [Header("C++ Cancel")]
    public bool sendPathCancelToCpp = true;
    public string cppHost = "192.168.50.159";
    public int cppPathPort = 15110;

    [Tooltip("PATH_CANCEL과 함께 UnityTeleopAndMirror로 0속도 estop 명령을 보냄")]
    public bool sendZeroTeleopOnReplan = true;

    [Header("References")]
    public GO1Agent targetAgent;
    public UnityTeleopAndMirror utm;

    [Header("Debug")]
    public bool drawPathAffectDebug = true;
    public Color nearPathDebugColor = Color.red;
    public Color normalPathDebugColor = Color.green;
    public bool logReplanDecision = true;

    // 장애물 트래킹
    private readonly Dictionary<int, GameObject> obstacles = new Dictionary<int, GameObject>();
    private readonly Dictionary<int, float> lastSeenTime = new Dictionary<int, float>();

    // 재탐색 안정화용 상태
    private readonly Dictionary<int, float> firstNearPathTime = new Dictionary<int, float>();
    private readonly Dictionary<int, float> lastReplanByTrackId = new Dictionary<int, float>();
    private readonly Dictionary<int, Vector3> lastReplanObstacleWorldPos = new Dictionary<int, Vector3>();
    private readonly Dictionary<int, Vector3> lastReplanGo1WorldPos = new Dictionary<int, Vector3>();
    private readonly Dictionary<int, float> moveCandidateStartTime = new Dictionary<int, float>();
    private readonly Dictionary<int, Vector3> smoothedObstacleWorldPos = new Dictionary<int, Vector3>();

    private UdpClient cancelUdpClient;
    private IPEndPoint cppPathEndPoint;

    private Coroutine replanRoutine;
    private float lastReplanRequestRealtime = -999f;

    void Start()
    {
        if (targetAgent == null)
            targetAgent = FindFirstObjectByType<GO1Agent>();

        if (utm == null)
            utm = FindFirstObjectByType<UnityTeleopAndMirror>();

        if (go1Transform == null && targetAgent != null)
            go1Transform = targetAgent.transform;

        InitCancelUdp();

        StartCoroutine(PollDetections());
    }

    void OnDestroy()
    {
        if (cancelUdpClient != null)
        {
            cancelUdpClient.Close();
            cancelUdpClient = null;
        }
    }

    private void InitCancelUdp()
    {
        if (!sendPathCancelToCpp)
            return;

        try
        {
            cancelUdpClient = new UdpClient();
            cppPathEndPoint = new IPEndPoint(IPAddress.Parse(cppHost), cppPathPort);
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"[ObstacleDetection] C++ cancel UDP 초기화 실패: {e.Message}");
        }
    }

    IEnumerator PollDetections()
    {
        while (true)
        {
            UnityWebRequest www = UnityWebRequest.Get(detectionUrl);
            yield return www.SendWebRequest();

            if (www.result == UnityWebRequest.Result.Success)
            {
                string json = www.downloadHandler.text;

                if (logReceivedJson)
                    Debug.Log($"[ObstacleDetection] JSON 수신: {json}");

                if (saveJsonLogToFile)
                    SaveLogToFile(json);

                DetectionFrame frame = JsonUtility.FromJson<DetectionFrame>(json);

                if (frame != null)
                    UpdateObstacles(frame);
            }
            else
            {
                Debug.LogError("[ObstacleDetection] Failed to get data: " + www.error);
            }

            yield return new WaitForSeconds(pollInterval);
        }
    }

    // =========================================================
    // Detection → Unity obstacle
    // =========================================================
    void UpdateObstacles(DetectionFrame frame)
    {
        if (frame == null || frame.detections == null)
            return;

        HashSet<int> currentValidIds = new HashSet<int>();
        bool shouldReplan = false;

        foreach (Detection detection in frame.detections)
        {
            if (!IsValidDetection(detection))
                continue;

            currentValidIds.Add(detection.track_id);

            if (!obstacles.ContainsKey(detection.track_id) || obstacles[detection.track_id] == null)
            {
                GameObject newObstacle = CreateObstacle(detection);
                obstacles[detection.track_id] = newObstacle;
            }

            GameObject obstacle = obstacles[detection.track_id];

            Vector3 rawWorldPos = CalculateObstaclePosition(detection.position_cam);
            Vector3 filteredWorldPos = GetSmoothedObstaclePosition(detection.track_id, rawWorldPos);

            UpdateObstaclePositionAndScale(obstacle, detection, filteredWorldPos);
            ConfigureObstacleComponents(obstacle);

            lastSeenTime[detection.track_id] = Time.realtimeSinceStartup;

            if (enableReplan && ShouldTriggerReplan(detection, filteredWorldPos))
                shouldReplan = true;
        }

        RemoveMissingObstacles(currentValidIds);

        if (shouldReplan)
            QueueReplan("server_detection_obstacle");
    }

    private bool IsValidDetection(Detection detection)
    {
        if (detection == null)
            return false;

        if (detection.confidence < confidenceThreshold)
            return false;

        if (maxDetectionDistance > 0f && detection.distance_m > maxDetectionDistance)
            return false;

        if (detection.position_cam == null)
            return false;

        return true;
    }

    private Vector3 GetSmoothedObstaclePosition(int trackId, Vector3 rawWorldPos)
    {
        if (obstaclePositionSmoothing <= 0f)
        {
            smoothedObstacleWorldPos[trackId] = rawWorldPos;
            return rawWorldPos;
        }

        if (!smoothedObstacleWorldPos.ContainsKey(trackId))
        {
            smoothedObstacleWorldPos[trackId] = rawWorldPos;
            return rawWorldPos;
        }

        Vector3 prev = smoothedObstacleWorldPos[trackId];
        Vector3 smoothed = Vector3.Lerp(rawWorldPos, prev, obstaclePositionSmoothing);
        smoothedObstacleWorldPos[trackId] = smoothed;

        return smoothed;
    }

    private GameObject CreateObstacle(Detection detection)
    {
        GameObject obj;

        if (obstaclePrefab != null)
        {
            obj = Instantiate(obstaclePrefab);
        }
        else
        {
            obj = GameObject.CreatePrimitive(PrimitiveType.Cube);
        }

        obj.name = $"Obstacle_{detection.track_id}_{detection.class_name}";
        obj.transform.localScale = defaultObstacleScale;

        return obj;
    }

    private void UpdateObstaclePositionAndScale(GameObject obstacle, Detection detection, Vector3 worldPos)
    {
        if (obstacle == null)
            return;

        obstacle.transform.position = worldPos;

        Vector3 scale = defaultObstacleScale;

        if (scaleFromBoundingBox &&
            detection.bbox_xyxy != null &&
            detection.bbox_xyxy.Length >= 4)
        {
            float bboxW = Mathf.Abs(detection.bbox_xyxy[2] - detection.bbox_xyxy[0]);
            float bboxH = Mathf.Abs(detection.bbox_xyxy[3] - detection.bbox_xyxy[1]);

            float sx = Mathf.Clamp(bboxW / bboxScaleDivider, minObstacleScale, maxObstacleScale);
            float sz = Mathf.Clamp(bboxH / bboxScaleDivider, minObstacleScale, maxObstacleScale);

            scale = new Vector3(sx, defaultObstacleScale.y, sz);
        }

        obstacle.transform.localScale = scale;
    }

    private void ConfigureObstacleComponents(GameObject obstacle)
    {
        if (obstacle == null)
            return;

        Collider col = obstacle.GetComponent<Collider>();
        if (col == null)
            col = obstacle.AddComponent<BoxCollider>();

        if (addNavMeshObstacle)
        {
            NavMeshObstacle nmo = obstacle.GetComponent<NavMeshObstacle>();
            if (nmo == null)
                nmo = obstacle.AddComponent<NavMeshObstacle>();

            Vector3 s = obstacle.transform.localScale;

            nmo.shape = NavMeshObstacleShape.Box;
            nmo.size = new Vector3(
                Mathf.Max(0.05f, s.x),
                Mathf.Max(0.05f, navMeshObstacleHeight),
                Mathf.Max(0.05f, s.z)
            );
            nmo.center = new Vector3(0f, navMeshObstacleHeight * 0.5f, 0f);
            nmo.carving = carveNavMeshObstacle;
            nmo.carveOnlyStationary = false;
        }
    }

    // 카메라 좌표 → Unity world 좌표 변환
    Vector3 CalculateObstaclePosition(PositionCam positionCam)
    {
        if (go1Transform == null)
        {
            return new Vector3(positionCam.x, projectObstacleToGround ? groundY : positionCam.y, positionCam.z);
        }

        Vector3 go1Pos = go1Transform.position;

        Vector3 forward = useNegativeRightAsForward ? -go1Transform.right : go1Transform.forward;
        Vector3 right = useNegativeRightAsForward ? go1Transform.forward : go1Transform.right;
        Vector3 up = Vector3.up;

        Vector3 cameraOffsetWorld =
            right * cameraOffsetLocal.x +
            up * cameraOffsetLocal.y +
            forward * cameraOffsetLocal.z;

        // position_cam 해석:
        // x = 카메라 기준 좌우
        // y = 카메라 기준 높이
        // z = 카메라 기준 전방 거리
        Vector3 world =
            go1Pos +
            cameraOffsetWorld +
            right * positionCam.x +
            up * positionCam.y +
            forward * positionCam.z;

        if (projectObstacleToGround)
            world.y = groundY;

        return world;
    }

    private void RemoveMissingObstacles(HashSet<int> currentValidIds)
    {
        List<int> toRemove = new List<int>();

        foreach (var kv in obstacles)
        {
            int id = kv.Key;

            if (currentValidIds.Contains(id))
                continue;

            float lastSeen = lastSeenTime.ContainsKey(id) ? lastSeenTime[id] : -999f;

            if (Time.realtimeSinceStartup - lastSeen > missingObstacleTimeout)
                toRemove.Add(id);
        }

        foreach (int id in toRemove)
        {
            if (obstacles.ContainsKey(id) && obstacles[id] != null)
                Destroy(obstacles[id]);

            obstacles.Remove(id);
            lastSeenTime.Remove(id);
            firstNearPathTime.Remove(id);
            moveCandidateStartTime.Remove(id);
            smoothedObstacleWorldPos.Remove(id);
        }
    }

    // =========================================================
    // Replan decision
    // =========================================================
    private bool ShouldTriggerReplan(Detection detection, Vector3 obstacleWorldPos)
    {
        int id = detection.track_id;
        float now = Time.realtimeSinceStartup;

        if (useReactionFilter && !DetectionReactionRequiresReplan(detection))
        {
            if (logReplanDecision)
                Debug.Log($"[ObstacleDetection] id={id} reaction filter로 재탐색 제외 reaction={detection.reaction}");
            return false;
        }

        bool nearPath = true;

        if (onlyReplanIfNearPath)
            nearPath = IsObstacleNearCurrentAgentPath(obstacleWorldPos);

        if (!nearPath)
        {
            firstNearPathTime.Remove(id);
            moveCandidateStartTime.Remove(id);

            if (logReplanDecision)
                Debug.Log($"[ObstacleDetection] id={id} 경로 근처 아님 → 재탐색 안 함");

            return false;
        }

        // 경로 근처에 처음 들어온 시점 기록
        if (!firstNearPathTime.ContainsKey(id))
        {
            firstNearPathTime[id] = now;

            if (logReplanDecision)
                Debug.Log($"[ObstacleDetection] id={id} 경로 근처 최초 감지. stable 대기 시작");

            return false;
        }

        float nearDuration = now - firstNearPathTime[id];

        if (nearDuration < requiredObstacleStableTime)
        {
            if (logReplanDecision)
                Debug.Log($"[ObstacleDetection] id={id} stable 대기 {nearDuration:F1}/{requiredObstacleStableTime:F1}s");
            return false;
        }

        // 아직 이 obstacle로 재탐색한 적 없으면 최초 재탐색 허용
        if (!lastReplanByTrackId.ContainsKey(id))
        {
            MarkObstacleReplanned(id, obstacleWorldPos, now);

            if (logReplanDecision)
                Debug.Log($"[ObstacleDetection] id={id} 최초 재탐색 허용");

            return true;
        }

        float sinceLastReplan = now - lastReplanByTrackId[id];

        // 15초 이후에는 같은 obstacle도 재탐색 가능
        if (sinceLastReplan >= sameObstacleReplanBlockTime)
        {
            MarkObstacleReplanned(id, obstacleWorldPos, now);

            if (logReplanDecision)
                Debug.Log($"[ObstacleDetection] id={id} 15초 block 만료 → 재탐색 허용");

            return true;
        }

        // 15초 block 중이면, 장애물이 실제로 움직였을 때만 재탐색 허용
        bool movedEnough = HasObstacleMovedEnoughDuringBlock(id, detection, obstacleWorldPos, sinceLastReplan, now);

        if (movedEnough)
        {
            MarkObstacleReplanned(id, obstacleWorldPos, now);

            if (logReplanDecision)
                Debug.Log($"[ObstacleDetection] id={id} 15초 block 중이지만 실제 이동 판단 → 재탐색 허용");

            return true;
        }

        if (logReplanDecision)
        {
            Debug.Log(
                $"[ObstacleDetection] id={id} 같은 장애물 재탐색 금지 중 " +
                $"{sinceLastReplan:F1}/{sameObstacleReplanBlockTime:F1}s"
            );
        }

        return false;
    }

    private bool HasObstacleMovedEnoughDuringBlock(
        int id,
        Detection detection,
        Vector3 obstacleWorldPos,
        float sinceLastReplan,
        float now)
    {
        if (!lastReplanObstacleWorldPos.ContainsKey(id))
            return false;

        Vector3 lastObsPos = lastReplanObstacleWorldPos[id];
        float obstacleMoved = Vector3.Distance(obstacleWorldPos, lastObsPos);

        bool detectionSaysMoving = DetectionSaysMoving(detection);

        float go1Moved = 0f;
        if (lastReplanGo1WorldPos.ContainsKey(id) && go1Transform != null)
            go1Moved = Vector3.Distance(go1Transform.position, lastReplanGo1WorldPos[id]);

        // GO1이 이동하면서 상대좌표 기반 obstacle world position이 흔들릴 수 있다.
        // GO1이 많이 움직였고 detection 자체가 moving이라고 말하지 않는다면,
        // 일반 threshold보다 큰 움직임일 때만 진짜 obstacle 이동으로 인정한다.
        float effectiveMoveThreshold = obstacleMoveReplanThreshold;

        if (guardAgainstGo1MotionFalseMove &&
            go1Moved >= go1MotionIgnoreDistance &&
            !detectionSaysMoving)
        {
            effectiveMoveThreshold = Mathf.Max(obstacleMoveReplanThreshold, largeMoveOverrideWhenGo1Moved);
        }

        if (obstacleMoved < effectiveMoveThreshold)
        {
            moveCandidateStartTime.Remove(id);

            if (logReplanDecision)
            {
                Debug.Log(
                    $"[ObstacleDetection] id={id} 이동 부족 obsMoved={obstacleMoved:F2}/{effectiveMoveThreshold:F2}, " +
                    $"go1Moved={go1Moved:F2}, detectionMoving={detectionSaysMoving}"
                );
            }

            return false;
        }

        if (!moveCandidateStartTime.ContainsKey(id))
        {
            moveCandidateStartTime[id] = now;

            if (logReplanDecision)
            {
                Debug.Log(
                    $"[ObstacleDetection] id={id} 이동 후보 시작 obsMoved={obstacleMoved:F2}, " +
                    $"go1Moved={go1Moved:F2}, threshold={effectiveMoveThreshold:F2}"
                );
            }

            return false;
        }

        float movedStable = now - moveCandidateStartTime[id];

        if (movedStable < movedObstacleStableTime)
        {
            if (logReplanDecision)
                Debug.Log($"[ObstacleDetection] id={id} 이동 stable 대기 {movedStable:F1}/{movedObstacleStableTime:F1}s");

            return false;
        }

        if (logReplanDecision)
        {
            Debug.Log(
                $"[ObstacleDetection] id={id} 실제 이동 확정 obsMoved={obstacleMoved:F2}, " +
                $"go1Moved={go1Moved:F2}, sinceLast={sinceLastReplan:F1}s"
            );
        }

        return true;
    }

    private bool DetectionSaysMoving(Detection detection)
    {
        string motion = detection.motion == null ? "" : detection.motion.ToLower();
        string reaction = detection.reaction == null ? "" : detection.reaction.ToLower();

        return motion.Contains("moving") ||
               motion.Contains("move") ||
               motion.Contains("approach") ||
               motion.Contains("left") ||
               motion.Contains("right") ||
               reaction.Contains("moving") ||
               reaction.Contains("move");
    }

    private bool DetectionReactionRequiresReplan(Detection detection)
    {
        string r = detection.reaction == null ? "" : detection.reaction.ToLower();

        return r.Contains("stop") ||
               r.Contains("avoid") ||
               r.Contains("block") ||
               r.Contains("replan");
    }

    private void MarkObstacleReplanned(int id, Vector3 obstacleWorldPos, float now)
    {
        lastReplanByTrackId[id] = now;
        lastReplanObstacleWorldPos[id] = obstacleWorldPos;

        if (go1Transform != null)
            lastReplanGo1WorldPos[id] = go1Transform.position;
        else
            lastReplanGo1WorldPos[id] = Vector3.zero;

        moveCandidateStartTime.Remove(id);
    }

    private bool IsObstacleNearCurrentAgentPath(Vector3 obstacleWorldPos)
    {
        if (targetAgent == null)
            targetAgent = FindFirstObjectByType<GO1Agent>();

        if (targetAgent == null || targetAgent.target == null)
            return false;

        NavMeshPath path = new NavMeshPath();
        bool hasPath = NavMesh.CalculatePath(
            targetAgent.transform.position,
            targetAgent.target.position,
            NavMesh.AllAreas,
            path
        );

        if (!hasPath || path.corners == null || path.corners.Length < 2)
            return true;

        float minDist = float.MaxValue;

        for (int i = 0; i < path.corners.Length - 1; i++)
        {
            Vector3 a = path.corners[i];
            Vector3 b = path.corners[i + 1];

            float d = DistancePointToSegmentXZ(obstacleWorldPos, a, b);
            minDist = Mathf.Min(minDist, d);

            if (drawPathAffectDebug)
            {
                Debug.DrawLine(
                    a + Vector3.up * 0.1f,
                    b + Vector3.up * 0.1f,
                    d <= obstacleAffectsPathDistance ? nearPathDebugColor : normalPathDebugColor,
                    1.0f
                );
            }
        }

        bool near = minDist <= obstacleAffectsPathDistance;

        if (logReplanDecision)
            Debug.Log($"[ObstacleDetection] obstacle-path distance={minDist:F2}, near={near}");

        return near;
    }

    private float DistancePointToSegmentXZ(Vector3 p, Vector3 a, Vector3 b)
    {
        Vector2 pp = new Vector2(p.x, p.z);
        Vector2 aa = new Vector2(a.x, a.z);
        Vector2 bb = new Vector2(b.x, b.z);

        Vector2 ab = bb - aa;

        if (ab.sqrMagnitude < 0.0001f)
            return Vector2.Distance(pp, aa);

        float t = Mathf.Clamp01(Vector2.Dot(pp - aa, ab) / ab.sqrMagnitude);
        Vector2 proj = aa + ab * t;

        return Vector2.Distance(pp, proj);
    }

    private void QueueReplan(string reason)
    {
        float now = Time.realtimeSinceStartup;

        if (now - lastReplanRequestRealtime < replanCooldownSeconds)
        {
            Debug.Log($"[ObstacleDetection] 전체 재탐색 쿨다운 생략 reason={reason}");
            return;
        }

        lastReplanRequestRealtime = now;

        if (replanRoutine != null)
            StopCoroutine(replanRoutine);

        replanRoutine = StartCoroutine(ReplanRoutine(reason));
    }

    private IEnumerator ReplanRoutine(string reason)
    {
        Debug.Log($"[ObstacleDetection] 재탐색 시작 reason={reason}");

        if (utm == null)
            utm = FindFirstObjectByType<UnityTeleopAndMirror>();

        if (targetAgent == null)
            targetAgent = FindFirstObjectByType<GO1Agent>();

        SendPathCancelToCpp();

        if (sendZeroTeleopOnReplan && utm != null)
            utm.SendTeleopCmd(0f, 0f, 0f, 1);

        if (utm != null)
            utm.driveByState = true;

        if (navMeshCarveSettleDelay > 0f)
            yield return new WaitForSecondsRealtime(navMeshCarveSettleDelay);

        if (replanDelayAfterCancel > 0f)
            yield return new WaitForSecondsRealtime(replanDelayAfterCancel);

        if (targetAgent != null && targetAgent.target != null)
        {
            targetAgent.StartNewMission();
            Debug.Log("[ObstacleDetection] GO1Agent StartNewMission 호출 완료");
        }
        else
        {
            Debug.LogWarning("[ObstacleDetection] 재탐색 실패: targetAgent 또는 target 없음");
        }

        replanRoutine = null;
    }

    private void SendPathCancelToCpp()
    {
        if (!sendPathCancelToCpp)
            return;

        try
        {
            if (cancelUdpClient == null || cppPathEndPoint == null)
                InitCancelUdp();

            if (cancelUdpClient == null || cppPathEndPoint == null)
                return;

            byte[] msg = Encoding.UTF8.GetBytes("PATH_CANCEL");
            cancelUdpClient.Send(msg, msg.Length, cppPathEndPoint);

            Debug.Log($"[ObstacleDetection] C++ PATH_CANCEL 전송 → {cppHost}:{cppPathPort}");
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"[ObstacleDetection] PATH_CANCEL 전송 실패: {e.Message}");
        }
    }

    // 로그 파일에 JSON 데이터 저장
    void SaveLogToFile(string logText)
    {
        if (!File.Exists(logFilePath))
        {
            File.WriteAllText(logFilePath, "Log Start: " + System.DateTime.Now + "\n");
        }

        File.AppendAllText(logFilePath, System.DateTime.Now + "\n" + logText + "\n\n");
    }

    // 클래스 정의: 서버 JSON 구조
    [System.Serializable]
    public class DetectionFrame
    {
        public float timestamp;
        public string camera_id;
        public int frame_seq;
        public FrameInfo frame_info;
        public List<Detection> detections;
    }

    [System.Serializable]
    public class FrameInfo
    {
        public int width;
        public int height;
        public float focal_length_px;
    }

    [System.Serializable]
    public class Detection
    {
        public int track_id;
        public string class_name;
        public string group;
        public string reaction;
        public string motion;
        public float confidence;
        public float distance_m;
        public int[] bbox_xyxy;
        public float[] bbox_center_px;
        public PositionCam position_cam;
    }

    [System.Serializable]
    public class PositionCam
    {
        public float x;
        public float y;
        public float z;
    }
}
