using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// AI 서버에서 WebSocket으로 장애물 JSON을 수신해 Unity 씬에 장애물 오브젝트를 생성/갱신한다.
/// Go1ObstacleJsonReceiver(UDP)와 동일한 패킷 구조 및 장애물 처리 로직을 사용하며,
/// 전송 계층만 UDP → WebSocket으로 교체한 버전이다.
/// </summary>
public class Go1ObstacleWebSocketReceiver : MonoBehaviour
{
    [Header("WebSocket Settings")]
    [Tooltip("연결할 AI 서버 WebSocket URI. 예: ws://192.168.0.100:8080/obstacle")]
    public string serverUri = "ws://192.168.0.100:8080/obstacle";

    [Tooltip("연결 실패/끊김 후 재연결을 시도하는 간격(초)")]
    public float reconnectIntervalSec = 3.0f;

    [Tooltip("연결이 끊기면 자동으로 재연결을 시도한다")]
    public bool autoReconnect = true;

    [Tooltip("WebSocket 수신 버퍼 크기(byte). 한 메시지가 이보다 크면 분할 수신한다")]
    public int receiveBufferSize = 65536;

    [Header("Camera Anchor")]
    public Transform cameraAnchor;
    public string autoFindCameraName = "Go1Cam";

    [Header("Virtual GO1 Camera")]
    [Tooltip("가상 GO1Cam Camera 컴포넌트. 비워두면 cameraAnchor 또는 자식에서 자동 탐색")]
    public Camera go1ViewCamera;

    [Tooltip("일반 Unity 카메라 ray 대신 실제 어안 카메라 형태에 맞춘 Fisheye Projection을 사용")]
    public bool useFisheyeProjection = true;

    [Tooltip("Fisheye Projection을 끄는 경우 Unity Camera의 ViewportPointToRay 방식으로 fallback 계산")]
    public bool useUnityCameraRayProjection = true;

    [Header("Fisheye Projection Settings")]
    [Range(0f, 1f)]
    public float fisheyeCenterX = 0.5f;

    [Range(0f, 1f)]
    public float fisheyeCenterY = 0.5f;

    public float fisheyeRadiusNorm = 0.50f;
    public float fisheyeFovDeg = 170f;
    public float fisheyePower = 1.0f;
    public bool mirrorFisheyeX = false;
    public bool mirrorFisheyeY = false;

    [Header("Camera Direction Correction")]
    public float cameraYawOffsetDeg = 0f;
    public bool invertLocalX = false;
    public bool invertLocalZ = false;

    [Header("Camera Local Position Tuning")]
    public bool useCameraLocalPositionTuning = true;
    public float cameraLocalXOffsetM = 0.0f;
    public float cameraLocalZOffsetM = 0.0f;
    public float cameraLocalXScale = 1.0f;
    public float cameraLocalZScale = 1.0f;

    [Header("Camera Side Ray Distance Tuning")]
    public bool useSideRayDistanceCorrection = true;

    [Range(0f, 1f)]
    public float sideRayDistanceCorrectionStrength = 0.35f;

    public float minSideForwardDot = 0.45f;

    [Header("Camera Image Settings")]
    public int imageWidth = 480;
    public int imageHeight = 360;
    public float horizontalFovDeg = 90f;
    public float verticalFovDeg = 60f;

    [Header("Distance Settings")]
    [Tooltip("JSON에 distance_cm / distance_cm_raw 값이 있으면 rel_depth보다 우선 사용한다")]
    public bool preferJsonDistanceCm = true;

    public float distanceScale = 1.0f;
    public float distanceOffsetM = 0.0f;
    public bool relDepthIsCentimeter = true;
    public float minDistanceM = 0.1f;
    public float maxDistanceM = 5.0f;

    [Header("Risk Filter")]
    [Tooltip("false면 near/mid/far 모두 표시")]
    public bool onlyShowNearObstacle = false;
    public string visibleRiskLevel = "near";

    [Header("Fire Extinguisher Landmark Correction")]
    public bool alwaysShowFireExtinguisherJson = true;
    public string fireExtinguisherNameKeyword = "fire extinguisher";
    public Transform knownFireExtinguisher;
    public string autoFindKnownFireExtinguisherName = "fire extinguisher";
    public bool correctGo1PoseByFireExtinguisher = true;
    public UnityTeleopAndMirror unityTeleopAndMirror;
    public Transform go1RootToCorrect;
    public bool useUnityTeleopCorrectionForFireExtinguisher = true;

    [Range(0f, 1f)]
    public float fireExtinguisherCorrectionGain = 1.0f;

    public float maxFireExtinguisherCorrectionM = 1.0f;
    public float fireExtinguisherCorrectionDeadzoneM = 0.05f;
    public float fireExtinguisherCorrectionCooldown = 0.5f;
    public bool forceFireExtinguisherObstacleToKnownPosition = true;
    public bool debugFireExtinguisherCorrection = true;
    public bool correctFireExtinguisherOnlyWhenNear = true;
    public bool routeFireCorrectionThroughGo1Agent = true;
    public bool fallbackImmediateFireCorrectionWhenAgentRejects = false;

    [Header("Fire Landmark Global Map Sync")]
    public bool moveDetectedObstacleMapWithFireCorrection = true;
    public bool moveDetectedObstacleMapOnlyWhenGo1CorrectionApplied = true;
    public bool keepFireLandmarkAtKnownPositionAfterMapShift = true;
    public bool debugFireLandmarkGlobalMapSync = true;

    [Header("Obstacle Prefab")]
    public GameObject obstaclePrefab;

    [Header("Obstacle Tag / Layer")]
    public bool assignObstacleTagAndLayer = true;
    public string obstacleTagName = "Obstacle";
    public string obstacleLayerName = "Obstacle";
    public bool applyObstacleTagAndLayerRecursively = true;

    [Header("Obstacle Size Settings")]
    public float minCubeSize = 0.15f;
    public float maxCubeSize = 3.0f;
    public float bboxSizeMultiplier = 1.5f;
    public float depthRatio = 0.6f;
    public float yOffset = 0.0f;
    public bool placeOnGround = true;

    [Header("Obstacle Merge / Tracking")]
    public bool mergeSameNameByPosition = true;
    public float mergeDistanceM = 0.45f;
    public bool matchSameGroupOnly = true;
    public bool mergeDifferentNameByPosition = true;
    public float differentNameMergeDistanceM = 0.35f;
    public bool allowSamePacketDifferentNameMerge = true;

    [Header("Near BBOX Duplicate / Fixed Map")]
    public bool ignoreNestedNearBboxes = true;

    [Range(0f, 1f)]
    public float nestedBboxContainmentThreshold = 0.75f;

    public bool ignoreOverlappingNearBboxesInSamePacket = true;

    [Range(0f, 1f)]
    public float samePacketBboxIouThreshold = 0.55f;

    public bool ignoreJsonOverlappingExistingNearObstacle = true;
    public float existingNearWorldMergeDistanceM = 0.55f;
    public bool mergeExistingNearByCameraRay = true;
    public float existingNearRayMergeRadiusM = 0.8f;
    public float existingNearRayDepthToleranceM = 2.0f;
    public bool rayMergeOnlyFrozenNearObstacle = true;
    public bool freezeNearObstacleAfterCreate = true;
    public bool suppressNotifyForFrozenDuplicate = true;
    public bool clearOldObstaclesOnStart = false;

    [Header("Obstacle Lifetime")]
    public bool keepDetectedObstaclesForever = true;
    public float staleTime = 2.0f;

    [Header("Smoothing")]
    public bool useSmoothing = true;
    public float smoothSpeed = 15f;

    [Header("Runtime Replan Notify")]
    public bool notifyAgentsOnObstacleUpdate = true;
    public bool autoAddNavMeshObstacle = true;
    public bool navMeshObstacleCarving = true;
    public float agentCacheRefreshInterval = 0.5f;

    [Header("Virtual Path Planning JSON Ignore")]
    public bool ignoreJsonWhileVirtualPathPlanning = true;
    public bool clearQueuedJsonWhileVirtualPathPlanning = true;
    public bool pauseStaleRemovalWhileVirtualPathPlanning = true;
    public bool printVirtualPlanningIgnoreLog = true;

    [Header("Rotation JSON Ignore")]
    public bool ignoreJsonWhileCameraRotating = true;
    public float rotationYawSpeedThresholdDegPerSec = 8.0f;
    public float rotationSettleTime = 0.45f;
    public bool clearQueuedJsonWhileRotating = true;
    public bool pauseStaleRemovalWhileRotating = true;
    public bool printRotationIgnoreLog = true;
    public bool allowJsonWhileRealGo1PathActive = true;

    [Header("Post Runtime Replan JSON Ignore")]
    public bool ignoreJsonDuringPostReplanLock = true;
    public bool clearQueuedJsonDuringPostReplanLock = true;
    public bool pauseStaleRemovalDuringPostReplanLock = true;
    public bool printPostReplanLockLog = true;

    [Header("GO1 Real Motion State JSON")]
    public bool receiveGo1MotionStateJson = true;
    public bool useStateChangeAsRealGo1Moving = true;
    public float go1MotionStateTimeoutSec = 1.0f;
    public bool processMotionStateEvenWhenIgnoringObstacleJson = true;
    public bool printGo1MotionStateLog = true;

    [Header("Debug")]
    public bool printReceivedJson = false;
    public bool printObstacleInfo = true;
    public bool drawDebugRay = true;

    // ── WebSocket 전용 내부 상태 ──────────────────────────────────────────
    private ClientWebSocket webSocket;
    private CancellationTokenSource cancelTokenSource;
    private Thread receiveThread;
    private bool isRunning;
    private bool isConnected;

    /// <summary>현재 WebSocket 연결 상태를 외부에서 읽을 수 있다.</summary>
    public bool IsConnected => isConnected;

    // ── 공통 내부 상태 (UDP 버전과 동일) ─────────────────────────────────
    private readonly ConcurrentQueue<string> jsonQueue = new ConcurrentQueue<string>();

    private readonly Dictionary<string, GameObject> obstacleObjects   = new Dictionary<string, GameObject>();
    private readonly Dictionary<string, float>      lastSeenTimes     = new Dictionary<string, float>();
    private readonly Dictionary<string, string>     obstacleNames     = new Dictionary<string, string>();
    private readonly Dictionary<string, string>     obstacleGroups    = new Dictionary<string, string>();
    private readonly Dictionary<string, Vector3>    obstacleLastPositions    = new Dictionary<string, Vector3>();
    private readonly Dictionary<string, Rect>       obstacleLastImageBboxes  = new Dictionary<string, Rect>();
    private readonly HashSet<string>                frozenNearObstacleKeys   = new HashSet<string>();

    private GameObject obstacleRoot;
    private int nextTrackId = 0;

    private GO1Agent[] cachedAgents;
    private float lastAgentRefreshTime = -999f;

    private bool hasLastCameraYaw = false;
    private float lastCameraYawDeg = 0f;
    private float currentCameraYawSpeedDegPerSec = 0f;
    private float lastCameraRotationDetectedTime = -999f;

    private bool wasIgnoringJsonBecauseVirtualPlanning = false;
    private bool wasIgnoringJsonBecauseRotation = false;
    private bool wasIgnoringJsonBecausePostReplanLock = false;

    private float lastFireExtinguisherCorrectionTime = -999f;
    private bool warnedMissingObstacleTag = false;
    private bool warnedMissingObstacleLayer = false;

    private bool hasGo1MotionState = false;
    private bool lastGo1StateChange = false;
    private float lastGo1MotionStateUnityTime = -999f;
    private string lastGo1MotionStateSource = "";
    private string lastGo1MotionStateReason = "";
    private float lastGo1MotionStateTimestamp = 0f;
    private string lastProcessedObstacleTimestamp = null;

    // 폐루프 인과 타임라인용: 탐지 패킷이 트윈에 도달한 순간(obstacle_detected 이벤트)을 기록한다.
    private RealGo1CaseStudyLogger caseStudyLogger;
    private bool caseStudyLoggerSearched = false;

    // ── 패킷 구조체 (UDP 버전과 동일) ────────────────────────────────────

    [Serializable]
    public class Go1ObstaclePacket
    {
        public string timestamp;
        public string camera_id;
        public Detection[] detections;
        public bool has_near_obstacle;
    }

    [Serializable]
    public class Detection
    {
        public int id;
        public string name;
        public string group;
        public float rel_depth;
        public float distance_cm;
        public float distance_cm_raw;
        public string risk_level;
        public int[] bbox_xyxy;
    }

    [Serializable]
    public class Go1MotionStatePacket
    {
        public bool state_change;
        public bool motion_active;
        public string source;
        public float ts;
        public string reason;
        public int mode;
        public float vx_cmd;
        public float vy_cmd;
        public float wz_cmd;
        public bool special_active;
        public string auto_status;
        public bool json_motion_active;
        public float control_latency_ms;
        public float world_x;
        public float world_z;
        public float yaw_unity;
    }

    // ═════════════════════════════════════════════════════════════════════
    // Unity 생명주기
    // ═════════════════════════════════════════════════════════════════════

    private void Start()
    {
        SetupCameraAnchor();
        SetupFireExtinguisherLandmark();
        SetupObstacleRoot();
        StartWebSocketReceiver();
    }

    private void Update()
    {
        UpdateCameraRotationState();

        if (ShouldIgnoreJsonBecauseVirtualPathPlanning())
        {
            if (!wasIgnoringJsonBecauseVirtualPlanning && printVirtualPlanningIgnoreLog)
                Debug.Log("[GO1 WS Receiver] 가상 GO1 경로 탐색 중 — JSON 장애물 생성/갱신 일시 중지");

            wasIgnoringJsonBecauseVirtualPlanning = true;

            if (processMotionStateEvenWhenIgnoringObstacleJson)
                DrainQueuedJsonForMotionState(clearQueuedJsonWhileVirtualPathPlanning);
            else if (clearQueuedJsonWhileVirtualPathPlanning)
                ClearQueuedJson();

            if (!pauseStaleRemovalWhileVirtualPathPlanning)
                RemoveStaleObstacles();

            return;
        }

        if (wasIgnoringJsonBecauseVirtualPlanning && printVirtualPlanningIgnoreLog)
            Debug.Log("[GO1 WS Receiver] 가상 경로 탐색 종료 → JSON 장애물 생성/갱신 재개");

        wasIgnoringJsonBecauseVirtualPlanning = false;

        if (ShouldIgnoreJsonBecausePostReplanLock())
        {
            if (!wasIgnoringJsonBecausePostReplanLock && printPostReplanLockLog)
                Debug.Log("[GO1 WS Receiver] 재탐색 직후 잠금 중 — JSON 장애물 생성/갱신 일시 중지");

            wasIgnoringJsonBecausePostReplanLock = true;

            if (processMotionStateEvenWhenIgnoringObstacleJson)
                DrainQueuedJsonForMotionState(clearQueuedJsonDuringPostReplanLock);
            else if (clearQueuedJsonDuringPostReplanLock)
                ClearQueuedJson();

            if (!pauseStaleRemovalDuringPostReplanLock)
                RemoveStaleObstacles();

            return;
        }

        if (wasIgnoringJsonBecausePostReplanLock && printPostReplanLockLog)
            Debug.Log("[GO1 WS Receiver] 재탐색 잠금 종료 → JSON 장애물 생성/갱신 재개");

        wasIgnoringJsonBecausePostReplanLock = false;

        if (ShouldIgnoreJsonBecauseCameraRotating())
        {
            if (!wasIgnoringJsonBecauseRotation && printRotationIgnoreLog)
                Debug.Log("[GO1 WS Receiver] GO1Cam 회전 중 — JSON 장애물 생성/갱신 일시 중지");

            wasIgnoringJsonBecauseRotation = true;

            if (processMotionStateEvenWhenIgnoringObstacleJson)
                DrainQueuedJsonForMotionState(clearQueuedJsonWhileRotating);
            else if (clearQueuedJsonWhileRotating)
                ClearQueuedJson();

            if (!pauseStaleRemovalWhileRotating)
                RemoveStaleObstacles();

            return;
        }

        if (wasIgnoringJsonBecauseRotation && printRotationIgnoreLog)
            Debug.Log("[GO1 WS Receiver] GO1Cam 회전 안정화 완료 → JSON 장애물 생성/갱신 재개");

        wasIgnoringJsonBecauseRotation = false;

        while (jsonQueue.TryDequeue(out string json))
        {
            if (printReceivedJson)
                Debug.Log("[WS JSON 수신]\n" + json);

            ProcessJson(json);
        }

        RemoveStaleObstacles();
    }

    private void OnApplicationQuit() => StopWebSocketReceiver();
    private void OnDestroy()         => StopWebSocketReceiver();
    private void OnDisable()         => StopWebSocketReceiver();

    // ═════════════════════════════════════════════════════════════════════
    // WebSocket 연결 / 수신
    // ═════════════════════════════════════════════════════════════════════

    private void StartWebSocketReceiver()
    {
        isRunning = true;
        cancelTokenSource = new CancellationTokenSource();

        receiveThread = new Thread(WebSocketLoop);
        receiveThread.IsBackground = true;
        receiveThread.Start();

        Debug.Log("[GO1 WS Receiver] WebSocket 수신 시작. URI = " + serverUri);
    }

    private void StopWebSocketReceiver()
    {
        isRunning = false;
        isConnected = false;

        try { cancelTokenSource?.Cancel(); } catch { }

        if (webSocket != null)
        {
            try { webSocket.Abort(); } catch { }
            webSocket.Dispose();
            webSocket = null;
        }

        if (receiveThread != null && receiveThread.IsAlive)
        {
            receiveThread.Join(500);
            receiveThread = null;
        }

        cancelTokenSource?.Dispose();
        cancelTokenSource = null;

        Debug.Log("[GO1 WS Receiver] WebSocket 수신 종료");
    }

    /// <summary>백그라운드 스레드에서 연결 → 수신 → 재연결을 반복한다.</summary>
    private void WebSocketLoop()
    {
        while (isRunning)
        {
            try
            {
                ConnectAndReceiveAsync().GetAwaiter().GetResult();
            }
            catch (OperationCanceledException)
            {
                // StopWebSocketReceiver()가 cancelToken을 취소했을 때 — 정상 종료
                break;
            }
            catch (Exception e)
            {
                if (!isRunning)
                    break;

                isConnected = false;
                Debug.LogWarning(
                    "[GO1 WS Receiver] 연결 오류: " + e.Message +
                    (autoReconnect ? " → " + reconnectIntervalSec + "초 후 재연결 시도" : "")
                );
            }

            if (!isRunning || !autoReconnect)
                break;

            Thread.Sleep(Mathf.Max(100, (int)(reconnectIntervalSec * 1000)));
        }
    }

    private async Task ConnectAndReceiveAsync()
    {
        CancellationToken token = cancelTokenSource.Token;

        webSocket?.Dispose();
        webSocket = new ClientWebSocket();

        Debug.Log("[GO1 WS Receiver] 서버 연결 시도: " + serverUri);
        await webSocket.ConnectAsync(new Uri(serverUri), token);

        isConnected = true;
        Debug.Log("[GO1 WS Receiver] 연결 성공: " + serverUri);

        byte[] buffer = new byte[receiveBufferSize];
        StringBuilder messageBuilder = new StringBuilder();

        while (isRunning && webSocket.State == WebSocketState.Open)
        {
            WebSocketReceiveResult result = await webSocket.ReceiveAsync(
                new ArraySegment<byte>(buffer), token
            );

            if (result.MessageType == WebSocketMessageType.Close)
            {
                isConnected = false;
                Debug.Log("[GO1 WS Receiver] 서버가 연결을 닫았습니다.");
                break;
            }

            messageBuilder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));

            if (result.EndOfMessage)
            {
                jsonQueue.Enqueue(messageBuilder.ToString());
                messageBuilder.Clear();
            }
        }

        isConnected = false;
    }

    // ═════════════════════════════════════════════════════════════════════
    // JSON 처리 (UDP 버전과 동일한 로직)
    // ═════════════════════════════════════════════════════════════════════

    public int ProcessQueuedJsonForPathPlanningGate(int maxPackets = 50)
    {
        int processed = 0;
        int limit = Mathf.Max(1, maxPackets);

        while (processed < limit && jsonQueue.TryDequeue(out string json))
        {
            if (printReceivedJson)
                Debug.Log("[WS JSON 수신 - path planning gate]\n" + json);

            ProcessJson(json);
            processed++;
        }

        return processed;
    }

    public int GetQueuedJsonCount() => jsonQueue.Count;

    private void ProcessJson(string json)
    {
        if (TryProcessGo1MotionStateJson(json))
            return;

        Go1ObstaclePacket packet;

        try
        {
            packet = JsonUtility.FromJson<Go1ObstaclePacket>(json);
        }
        catch (Exception e)
        {
            Debug.LogError("[GO1 WS Receiver] JSON 파싱 실패: " + e.Message);
            return;
        }

        if (packet == null || packet.detections == null)
            return;

        if (!string.IsNullOrEmpty(packet.timestamp) &&
            packet.timestamp == lastProcessedObstacleTimestamp)
            return;

        if (!string.IsNullOrEmpty(packet.timestamp))
            lastProcessedObstacleTimestamp = packet.timestamp;

        // 폐루프 타임라인: 새 탐지 패킷이 트윈에 도달한 순간을 기록.
        if (packet.detections.Length > 0)
        {
            if (!caseStudyLoggerSearched)
            {
                caseStudyLoggerSearched = true;
                caseStudyLogger = FindFirstObjectByType<RealGo1CaseStudyLogger>();
            }

            caseStudyLogger?.LogObstacleDetected(
                Vector3.zero,
                "websocket:" + (packet.camera_id ?? "unknown"),
                packet.timestamp,
                packet.detections.Length);
        }

        HashSet<string> matchedKeysThisPacket = new HashSet<string>();
        List<Detection> candidates = new List<Detection>();

        foreach (Detection detection in packet.detections)
        {
            if (detection == null)
                continue;

            if (detection.bbox_xyxy == null || detection.bbox_xyxy.Length < 4)
                continue;

            bool isFireExtinguisher = IsFireExtinguisherDetection(detection);

            if (onlyShowNearObstacle && !(alwaysShowFireExtinguisherJson && isFireExtinguisher))
            {
                if (string.IsNullOrEmpty(detection.risk_level))
                    continue;

                if (!string.Equals(detection.risk_level, visibleRiskLevel, StringComparison.OrdinalIgnoreCase))
                    continue;
            }

            candidates.Add(detection);
        }

        candidates = FilterDuplicateNearBboxes(candidates);

        foreach (Detection detection in candidates)
            CreateOrUpdateObstacle(packet.camera_id, detection, matchedKeysThisPacket);
    }

    // ═════════════════════════════════════════════════════════════════════
    // GO1 이동 상태 JSON
    // ═════════════════════════════════════════════════════════════════════

    private bool TryProcessGo1MotionStateJson(string json)
    {
        if (!receiveGo1MotionStateJson || string.IsNullOrEmpty(json))
            return false;

        if (json.IndexOf("\"state_change\"", StringComparison.OrdinalIgnoreCase) < 0)
            return false;

        if (json.IndexOf("\"motion_active\"", StringComparison.OrdinalIgnoreCase) < 0)
            return false;

        Go1MotionStatePacket packet;

        try
        {
            packet = JsonUtility.FromJson<Go1MotionStatePacket>(json);
        }
        catch (Exception e)
        {
            Debug.LogError("[GO1 WS Motion State] JSON 파싱 실패: " + e.Message + "\n" + json);
            return true;
        }

        if (packet == null)
            return true;

        bool previousValid = hasGo1MotionState;
        bool previousStateChange = lastGo1StateChange;

        hasGo1MotionState = true;
        lastGo1StateChange = packet.state_change;
        lastGo1MotionStateUnityTime = Time.time;
        lastGo1MotionStateSource = packet.source ?? "";
        lastGo1MotionStateReason = packet.reason ?? "";
        lastGo1MotionStateTimestamp = packet.ts;

        bool changed = !previousValid || previousStateChange != lastGo1StateChange;

        if (printGo1MotionStateLog && changed)
        {
            Debug.Log(
                "[GO1 WS Motion State] state_change=" + lastGo1StateChange +
                " → realGo1Moving=" + IsRealGo1MovingByStateChange() +
                ", source=" + lastGo1MotionStateSource +
                ", reason=" + lastGo1MotionStateReason +
                ", mode=" + packet.mode +
                ", vx_cmd=" + packet.vx_cmd.ToString("F3") +
                ", wz_cmd=" + packet.wz_cmd.ToString("F3") +
                ", latency=" + packet.control_latency_ms.ToString("F1") + "ms"
            );
        }

        return true;
    }

    public bool HasRecentGo1MotionState()
    {
        if (!hasGo1MotionState)
            return false;

        if (go1MotionStateTimeoutSec <= 0f)
            return true;

        return Time.time - lastGo1MotionStateUnityTime <= go1MotionStateTimeoutSec;
    }

    public bool IsRealGo1MovingByStateChange()
    {
        if (!useStateChangeAsRealGo1Moving)
            return false;

        if (!HasRecentGo1MotionState())
            return false;

        return lastGo1StateChange;
    }

    public bool ShouldMoveVirtualGo1AfterPathSent() => IsRealGo1MovingByStateChange();
    public bool GetLastGo1StateChange()               => lastGo1StateChange;

    public float GetLastGo1MotionStateAgeSec()
    {
        if (!hasGo1MotionState)
            return float.PositiveInfinity;

        return Time.time - lastGo1MotionStateUnityTime;
    }

    public string GetLastGo1MotionStateSummary()
    {
        if (!hasGo1MotionState)
            return "GO1 motion state not received";

        return "state_change=" + lastGo1StateChange +
               ", moving=" + IsRealGo1MovingByStateChange() +
               ", age=" + GetLastGo1MotionStateAgeSec().ToString("F2") + "s" +
               ", source=" + lastGo1MotionStateSource +
               ", reason=" + lastGo1MotionStateReason +
               ", ts=" + lastGo1MotionStateTimestamp.ToString("F3");
    }

    private void DrainQueuedJsonForMotionState(bool discardNonMotionJson)
    {
        int count = jsonQueue.Count;

        for (int i = 0; i < count; i++)
        {
            if (!jsonQueue.TryDequeue(out string json))
                break;

            if (TryProcessGo1MotionStateJson(json))
                continue;

            if (!discardNonMotionJson)
                jsonQueue.Enqueue(json);
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    // 장애물 생성 / 갱신
    // ═════════════════════════════════════════════════════════════════════

    private void CreateOrUpdateObstacle(string cameraId, Detection detection, HashSet<string> matchedKeysThisPacket)
    {
        if (cameraAnchor == null)
            return;

        string safeCameraId = string.IsNullOrEmpty(cameraId) ? "go1_camera" : cameraId;

        float distanceM = CalibrateDetectionDistanceToMeter(detection);
        distanceM *= distanceScale;
        distanceM += distanceOffsetM;
        distanceM = Mathf.Clamp(distanceM, minDistanceM, maxDistanceM);

        int x1 = detection.bbox_xyxy[0];
        int y1 = detection.bbox_xyxy[1];
        int x2 = detection.bbox_xyxy[2];
        int y2 = detection.bbox_xyxy[3];

        float bboxCenterX = (x1 + x2) * 0.5f;
        float bboxCenterY = (y1 + y2) * 0.5f;
        float bboxWidthPx  = Mathf.Abs(x2 - x1);
        float bboxHeightPx = Mathf.Abs(y2 - y1);
        Rect currentBbox = GetBboxRect(detection);

        Vector3 cubeScale = EstimateCubeScale(distanceM, bboxWidthPx, bboxHeightPx);
        Vector3 worldPosition = EstimateObstacleWorldPosition(distanceM, bboxCenterX, bboxCenterY, cubeScale);

        bool isFireExtinguisher = IsFireExtinguisherDetection(detection);
        Vector3 detectedFireExtinguisherWorldPosition = worldPosition;

        if (isFireExtinguisher)
        {
            ApplyFireExtinguisherLandmarkCorrection(detectedFireExtinguisherWorldPosition, detection);

            if (forceFireExtinguisherObstacleToKnownPosition && knownFireExtinguisher != null)
            {
                Vector3 knownPos = knownFireExtinguisher.position;
                worldPosition = new Vector3(knownPos.x, worldPosition.y, knownPos.z);
            }
        }

        string objectKey = isFireExtinguisher
            ? MakeFireExtinguisherObstacleKey(safeCameraId)
            : FindMatchingObstacleKey(detection, worldPosition, matchedKeysThisPacket);

        bool isNewObstacle = false;
        bool alreadyMatchedThisPacket = !string.IsNullOrEmpty(objectKey) &&
                                        matchedKeysThisPacket != null &&
                                        matchedKeysThisPacket.Contains(objectKey);

        if (!isFireExtinguisher &&
            !string.IsNullOrEmpty(objectKey) &&
            alreadyMatchedThisPacket &&
            ignoreJsonOverlappingExistingNearObstacle)
        {
            lastSeenTimes[objectKey] = Time.time;

            if (printObstacleInfo)
                Debug.Log("[GO1 WS Receiver] 같은 패킷 중복 near JSON 무시 | key=" + objectKey + ", ignoredName=" + detection.name);

            return;
        }

        GameObject obstacleObj;

        if (string.IsNullOrEmpty(objectKey) || !obstacleObjects.ContainsKey(objectKey))
        {
            if (string.IsNullOrEmpty(objectKey))
                objectKey = MakeNewObstacleKey(safeCameraId, detection);

            obstacleObj = CreateObstacleObject(detection);
            obstacleObjects[objectKey] = obstacleObj;
            isNewObstacle = true;
        }
        else
        {
            obstacleObj = obstacleObjects[objectKey];
        }

        if (matchedKeysThisPacket != null)
            matchedKeysThisPacket.Add(objectKey);

        bool isNear = IsNearRisk(detection.risk_level);
        bool freezeExistingNear = !isNewObstacle &&
                                  isNear &&
                                  freezeNearObstacleAfterCreate &&
                                  frozenNearObstacleKeys.Contains(objectKey);

        obstacleObj.name = (isFireExtinguisher ? "Landmark_FireExtinguisher_" : "Obstacle_") +
                           detection.name + "_" + objectKey + "_" + detection.risk_level;

        ApplyObstacleTagAndLayer(obstacleObj);

        if (isNewObstacle)
        {
            obstacleObj.transform.localScale = cubeScale;
            obstacleObj.transform.position   = worldPosition;

            if (isNear && freezeNearObstacleAfterCreate)
                frozenNearObstacleKeys.Add(objectKey);
        }
        else if (freezeExistingNear)
        {
            if (printObstacleInfo)
            {
                Debug.Log(
                    "[GO1 WS Receiver] 고정 near 장애물 중복 JSON 흡수 | " +
                    "key=" + objectKey +
                    ", oldPos=" + obstacleObj.transform.position +
                    ", ignoredTargetPos=" + worldPosition +
                    ", name=" + detection.name
                );
            }
        }
        else
        {
            obstacleObj.transform.localScale = cubeScale;

            obstacleObj.transform.position = useSmoothing
                ? Vector3.Lerp(obstacleObj.transform.position, worldPosition, Time.deltaTime * smoothSpeed)
                : worldPosition;
        }

        UpdateObstacleColor(obstacleObj, detection.risk_level);
        UpdateLabel(obstacleObj, detection, distanceM);
        UpdateNavMeshObstacle(obstacleObj);

        bool shouldNotifyAgent = isNewObstacle || !freezeExistingNear || !suppressNotifyForFrozenDuplicate;
        if (shouldNotifyAgent)
            NotifyAgentsObstacleUpdated(obstacleObj);

        obstacleNames[objectKey]         = detection.name;
        obstacleGroups[objectKey]        = detection.group;
        obstacleLastPositions[objectKey] = obstacleObj.transform.position;
        obstacleLastImageBboxes[objectKey] = currentBbox;
        lastSeenTimes[objectKey]         = Time.time;

        if (drawDebugRay)
            Debug.DrawLine(cameraAnchor.position, worldPosition, Color.magenta, 0.2f);

        if (printObstacleInfo)
        {
            Debug.Log(
                "[WS 장애물 생성/갱신] " +
                "key=" + objectKey +
                ", name=" + detection.name +
                ", group=" + detection.group +
                ", risk=" + detection.risk_level +
                ", distanceM=" + distanceM.ToString("F2") +
                ", isNew=" + isNewObstacle +
                ", isFireExtinguisher=" + isFireExtinguisher +
                ", frozenNear=" + freezeExistingNear +
                ", pos=" + obstacleObj.transform.position +
                ", scale=" + obstacleObj.transform.localScale
            );
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    // 소화기 Landmark 보정
    // ═════════════════════════════════════════════════════════════════════

    private void ApplyFireExtinguisherLandmarkCorrection(Vector3 detectedWorldPosition, Detection detection)
    {
        if (!correctGo1PoseByFireExtinguisher || detection == null)
            return;

        bool isNear = IsNearRisk(detection.risk_level);

        if (correctFireExtinguisherOnlyWhenNear && !isNear)
        {
            if (debugFireExtinguisherCorrection)
                Debug.Log("[GO1 WS Receiver] 소화기 landmark 보정 생략: near가 아님 | risk=" + detection.risk_level);

            return;
        }

        if (knownFireExtinguisher == null)
            SetupFireExtinguisherLandmark();

        if (knownFireExtinguisher == null)
        {
            if (debugFireExtinguisherCorrection)
                Debug.LogWarning("[GO1 WS Receiver] 소화기 landmark 보정 실패: knownFireExtinguisher가 없습니다.");

            return;
        }

        if (Time.time - lastFireExtinguisherCorrectionTime < Mathf.Max(0f, fireExtinguisherCorrectionCooldown))
            return;

        Vector3 knownPos = knownFireExtinguisher.position;
        Vector3 delta    = knownPos - detectedWorldPosition;
        delta.y = 0f;

        float error = delta.magnitude;

        if (error < fireExtinguisherCorrectionDeadzoneM)
            return;

        float maxCorrection = Mathf.Max(0.01f, maxFireExtinguisherCorrectionM);
        if (delta.magnitude > maxCorrection)
            delta = delta.normalized * maxCorrection;

        delta *= Mathf.Clamp01(fireExtinguisherCorrectionGain);

        bool acceptedByAgent = false;
        Vector3 actuallyAppliedDelta = delta;

        if (routeFireCorrectionThroughGo1Agent)
        {
            acceptedByAgent = TryRequestFireCorrectionFromAgents(
                delta, detection, detectedWorldPosition, knownPos, isNear, out actuallyAppliedDelta
            );

            if (acceptedByAgent)
            {
                lastFireExtinguisherCorrectionTime = Time.time;
                ApplyFireLandmarkDeltaToDetectedObstacleMap(actuallyAppliedDelta, "agent-accepted");
                return;
            }
        }

        if (!fallbackImmediateFireCorrectionWhenAgentRejects)
            return;

        bool applied = ApplyFireCorrectionImmediately(delta);

        if (applied)
        {
            lastFireExtinguisherCorrectionTime = Time.time;
            ApplyFireLandmarkDeltaToDetectedObstacleMap(delta, "immediate-fallback");
        }
    }

    private bool TryRequestFireCorrectionFromAgents(
        Vector3 correctionDelta,
        Detection detection,
        Vector3 detectedWorldPosition,
        Vector3 knownPosition,
        bool isNear,
        out Vector3 actuallyAppliedDelta)
    {
        actuallyAppliedDelta = correctionDelta;

        RefreshAgentCacheIfNeeded();

        if (cachedAgents == null || cachedAgents.Length == 0)
            return false;

        foreach (GO1Agent agent in cachedAgents)
        {
            if (agent == null)
                continue;

            try
            {
                Vector3 agentAppliedDelta;
                bool result = agent.RequestFireLandmarkCorrectionReplan(
                    correctionDelta, "fire extinguisher", isNear, out agentAppliedDelta, unityTeleopAndMirror
                );

                if (result)
                {
                    actuallyAppliedDelta = agentAppliedDelta;
                    return true;
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[GO1 WS Receiver] GO1Agent 소화기 보정 요청 중 예외: " + ex.Message);
            }
        }

        return false;
    }

    private bool ApplyFireCorrectionImmediately(Vector3 delta)
    {
        bool applied = false;

        if (useUnityTeleopCorrectionForFireExtinguisher)
        {
            if (unityTeleopAndMirror == null)
                unityTeleopAndMirror = FindFirstObjectByType<UnityTeleopAndMirror>();

            if (unityTeleopAndMirror != null)
            {
                unityTeleopAndMirror.ApplyExternalUnityPositionCorrection(delta, "fire-extinguisher landmark immediate-fallback", true);
                applied = true;
            }
        }

        if (!applied && go1RootToCorrect != null)
        {
            go1RootToCorrect.position += delta;
            applied = true;
        }

        return applied;
    }

    private void ApplyFireLandmarkDeltaToDetectedObstacleMap(Vector3 delta, string reason)
    {
        if (!moveDetectedObstacleMapWithFireCorrection)
            return;

        delta.y = 0f;

        if (delta.sqrMagnitude < 0.000001f)
            return;

        HashSet<GameObject> movedObjects = new HashSet<GameObject>();

        foreach (KeyValuePair<string, GameObject> pair in obstacleObjects)
        {
            if (pair.Value == null)
                continue;

            pair.Value.transform.position += delta;
            movedObjects.Add(pair.Value);
        }

        if (obstacleRoot != null)
        {
            foreach (Transform child in obstacleRoot.transform)
            {
                if (child == null || child.gameObject == null || movedObjects.Contains(child.gameObject))
                    continue;

                child.position += delta;
            }
        }

        List<string> keys = new List<string>(obstacleLastPositions.Keys);
        foreach (string key in keys)
            obstacleLastPositions[key] = obstacleLastPositions[key] + delta;

        if (keepFireLandmarkAtKnownPositionAfterMapShift && knownFireExtinguisher != null)
        {
            foreach (KeyValuePair<string, GameObject> pair in obstacleObjects)
            {
                string key = pair.Key;
                GameObject obj = pair.Value;

                if (obj == null)
                    continue;

                bool keyLooksFire  = key.IndexOf("fire_extinguisher", StringComparison.OrdinalIgnoreCase) >= 0;
                bool nameLooksFire = obj.name.IndexOf("fire", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                     obj.name.IndexOf("extinguisher", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                     obj.name.IndexOf("소화기", StringComparison.OrdinalIgnoreCase) >= 0;

                if (!keyLooksFire && !nameLooksFire)
                    continue;

                Vector3 p = obj.transform.position;
                obj.transform.position = new Vector3(knownFireExtinguisher.position.x, p.y, knownFireExtinguisher.position.z);
                obstacleLastPositions[key] = obj.transform.position;
            }
        }

        if (debugFireLandmarkGlobalMapSync)
        {
            Debug.Log(
                "[GO1 WS Receiver] 소화기 landmark 기준 장애물 지도 전체 보정 | " +
                "reason=" + reason +
                ", delta=(" + delta.x.ToString("F3") + "," + delta.z.ToString("F3") + ")" +
                ", movedObjects=" + movedObjects.Count
            );
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    // 초기화 헬퍼
    // ═════════════════════════════════════════════════════════════════════

    private void SetupCameraAnchor()
    {
        if (cameraAnchor != null)
        {
            Debug.Log("[GO1 WS Receiver] Camera Anchor 사용: " + cameraAnchor.name);
        }
        else
        {
            Transform found = FindDeepChild(transform, autoFindCameraName);

            if (found != null)
            {
                cameraAnchor = found;
                Debug.Log("[GO1 WS Receiver] 자동으로 Camera Anchor 찾음: " + cameraAnchor.name);
            }
            else
            {
                cameraAnchor = transform;
                Debug.LogWarning("[GO1 WS Receiver] Go1Cam을 찾지 못했습니다. 현재 go1 transform 기준으로 생성합니다.");
            }
        }

        if (go1ViewCamera == null)
        {
            if (cameraAnchor != null)
            {
                go1ViewCamera = cameraAnchor.GetComponent<Camera>();

                if (go1ViewCamera == null)
                    go1ViewCamera = cameraAnchor.GetComponentInChildren<Camera>(true);
            }

            if (go1ViewCamera != null)
                Debug.Log("[GO1 WS Receiver] Unity Camera 사용: " + go1ViewCamera.name);
            else
                Debug.LogWarning("[GO1 WS Receiver] Camera 컴포넌트를 찾지 못했습니다. 수동 FOV 계산으로 fallback 합니다.");
        }
    }

    private void SetupFireExtinguisherLandmark()
    {
        if (unityTeleopAndMirror == null)
            unityTeleopAndMirror = FindFirstObjectByType<UnityTeleopAndMirror>();

        if (go1RootToCorrect == null && cameraAnchor != null)
        {
            GO1Agent agent = cameraAnchor.GetComponentInParent<GO1Agent>();
            if (agent != null)
                go1RootToCorrect = agent.transform;
        }

        if (knownFireExtinguisher == null && !string.IsNullOrEmpty(autoFindKnownFireExtinguisherName))
        {
            GameObject exact = GameObject.Find(autoFindKnownFireExtinguisherName);

            if (exact != null)
            {
                knownFireExtinguisher = exact.transform;
            }
            else
            {
                Transform found = FindSceneTransformNameContains(autoFindKnownFireExtinguisherName);
                if (found != null)
                    knownFireExtinguisher = found;
            }
        }

        if (debugFireExtinguisherCorrection)
        {
            Debug.Log(
                "[GO1 WS Receiver] 소화기 landmark 설정 | " +
                "known=" + (knownFireExtinguisher != null ? knownFireExtinguisher.name : "null") +
                ", utm=" + (unityTeleopAndMirror != null ? unityTeleopAndMirror.name : "null") +
                ", go1Root=" + (go1RootToCorrect != null ? go1RootToCorrect.name : "null")
            );
        }
    }

    private void SetupObstacleRoot()
    {
        obstacleRoot = GameObject.Find("GO1_Detected_Obstacles_WS");

        if (obstacleRoot == null)
            obstacleRoot = new GameObject("GO1_Detected_Obstacles_WS");

        obstacleRoot.transform.SetParent(null, true);

        if (clearOldObstaclesOnStart)
        {
            for (int i = obstacleRoot.transform.childCount - 1; i >= 0; i--)
                Destroy(obstacleRoot.transform.GetChild(i).gameObject);
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    // 위치 추정
    // ═════════════════════════════════════════════════════════════════════

    private Vector3 EstimateObstacleWorldPosition(float distanceM, float bboxCenterX, float bboxCenterY, Vector3 cubeScale)
    {
        if (useFisheyeProjection && go1ViewCamera != null)
            return EstimateWorldPositionByFisheyeProjection(distanceM, bboxCenterX, bboxCenterY, cubeScale);

        if (useUnityCameraRayProjection && go1ViewCamera != null)
            return EstimateWorldPositionByUnityCameraRay(distanceM, bboxCenterX, bboxCenterY, cubeScale);

        Vector3 localPosition = EstimateCameraLocalPosition(distanceM, bboxCenterX, bboxCenterY);
        localPosition = ApplyCameraLocalTuningToLocalPosition(localPosition);
        return ConvertCameraLocalToWorld(localPosition, cubeScale);
    }

    private Vector3 EstimateWorldPositionByFisheyeProjection(float distanceM, float bboxCenterX, float bboxCenterY, Vector3 cubeScale)
    {
        Vector3 cameraForward, cameraRight;
        BuildCameraBasis(out cameraForward, out cameraRight);

        float u = bboxCenterX / Mathf.Max(1f, imageWidth);
        float v = bboxCenterY / Mathf.Max(1f, imageHeight);

        float dx = u - fisheyeCenterX;
        float dy = v - fisheyeCenterY;

        if (mirrorFisheyeX) dx = -dx;
        if (mirrorFisheyeY) dy = -dy;
        if (invertLocalX)   dx = -dx;

        float shortAspect = Mathf.Min(imageWidth, imageHeight);
        float radiusPx    = shortAspect * Mathf.Max(0.0001f, fisheyeRadiusNorm);
        float dxPx = dx * imageWidth;
        float dyPx = dy * imageHeight;

        float rNorm = Mathf.Sqrt(dxPx * dxPx + dyPx * dyPx) / radiusPx;
        rNorm = Mathf.Clamp01(rNorm);

        float theta = Mathf.Pow(rNorm, Mathf.Max(0.01f, fisheyePower)) * (fisheyeFovDeg * 0.5f * Mathf.Deg2Rad);
        float phi   = Mathf.Atan2(dxPx, -dyPx);

        float localRight   = Mathf.Sin(theta) * Mathf.Sin(phi);
        float localForward = Mathf.Cos(theta);

        Vector3 forwardDir = cameraForward * localForward + cameraRight * localRight;

        if (forwardDir.sqrMagnitude < 0.0001f)
            forwardDir = cameraForward;

        forwardDir.y = 0f;
        forwardDir.Normalize();

        if (Mathf.Abs(cameraYawOffsetDeg) > 0.0001f)
        {
            forwardDir = Quaternion.Euler(0f, cameraYawOffsetDeg, 0f) * forwardDir;
            forwardDir.y = 0f;
            forwardDir.Normalize();
        }

        return BuildWorldPositionFromDirection(distanceM, forwardDir, cameraForward, cameraRight, cubeScale);
    }

    private Vector3 EstimateWorldPositionByUnityCameraRay(float distanceM, float bboxCenterX, float bboxCenterY, Vector3 cubeScale)
    {
        float viewportX = Mathf.Clamp01(bboxCenterX / Mathf.Max(1f, imageWidth));
        float viewportY = 1f - Mathf.Clamp01(bboxCenterY / Mathf.Max(1f, imageHeight));

        if (invertLocalX)
            viewportX = 1f - viewportX;

        Ray ray = go1ViewCamera.ViewportPointToRay(new Vector3(viewportX, viewportY, 0f));

        Vector3 forwardDir = Vector3.ProjectOnPlane(ray.direction, Vector3.up);

        if (forwardDir.sqrMagnitude < 0.0001f)
            forwardDir = Vector3.ProjectOnPlane(cameraAnchor.forward, Vector3.up);

        forwardDir.Normalize();

        if (Mathf.Abs(cameraYawOffsetDeg) > 0.0001f)
        {
            forwardDir = Quaternion.Euler(0f, cameraYawOffsetDeg, 0f) * forwardDir;
            forwardDir.y = 0f;
            forwardDir.Normalize();
        }

        Vector3 cameraForward, cameraRight;
        BuildCameraBasis(out cameraForward, out cameraRight);

        return BuildWorldPositionFromDirection(distanceM, forwardDir, cameraForward, cameraRight, cubeScale);
    }

    private void BuildCameraBasis(out Vector3 cameraForward, out Vector3 cameraRight)
    {
        cameraForward = go1ViewCamera != null
            ? Vector3.ProjectOnPlane(go1ViewCamera.transform.forward, Vector3.up)
            : Vector3.ProjectOnPlane(cameraAnchor.forward, Vector3.up);

        if (cameraForward.sqrMagnitude < 0.0001f)
            cameraForward = Vector3.ProjectOnPlane(cameraAnchor.forward, Vector3.up);

        cameraForward.Normalize();

        cameraRight = go1ViewCamera != null
            ? Vector3.ProjectOnPlane(go1ViewCamera.transform.right, Vector3.up)
            : Vector3.ProjectOnPlane(cameraAnchor.right, Vector3.up);

        if (cameraRight.sqrMagnitude < 0.0001f)
            cameraRight = Vector3.ProjectOnPlane(cameraAnchor.right, Vector3.up);

        cameraRight.Normalize();
    }

    private Vector3 BuildWorldPositionFromDirection(float distanceM, Vector3 forwardDir, Vector3 cameraForward, Vector3 cameraRight, Vector3 cubeScale)
    {
        float rayDistance = distanceM;

        if (useSideRayDistanceCorrection)
        {
            float forwardDot = Mathf.Clamp(Vector3.Dot(forwardDir, cameraForward), minSideForwardDot, 1.0f);
            float correctedRayDistance = distanceM / forwardDot;
            rayDistance = Mathf.Lerp(distanceM, correctedRayDistance, sideRayDistanceCorrectionStrength);
        }

        Vector3 fromCamera = forwardDir * rayDistance;

        float localForward = Vector3.Dot(fromCamera, cameraForward);
        float localRight   = Vector3.Dot(fromCamera, cameraRight);

        if (useCameraLocalPositionTuning)
        {
            localForward = localForward * cameraLocalZScale + cameraLocalZOffsetM;
            localRight   = localRight   * cameraLocalXScale + cameraLocalXOffsetM;
        }

        if (invertLocalZ)
            localForward = -localForward;

        Vector3 worldPosition =
            cameraAnchor.position
            + cameraForward * localForward
            + cameraRight * localRight;

        if (placeOnGround)
            worldPosition.y = yOffset + cubeScale.y * 0.5f;
        else
            worldPosition.y = cameraAnchor.position.y + yOffset;

        return worldPosition;
    }

    private Vector3 EstimateCameraLocalPosition(float distanceM, float bboxCenterX, float bboxCenterY)
    {
        float normalizedX = (bboxCenterX - imageWidth * 0.5f) / (imageWidth * 0.5f);

        if (invertLocalX)
            normalizedX = -normalizedX;

        float halfViewWidthAtDistance = Mathf.Tan(horizontalFovDeg * 0.5f * Mathf.Deg2Rad) * distanceM;
        float localX = normalizedX * halfViewWidthAtDistance;
        float localZ = distanceM;

        if (invertLocalZ)
            localZ = -localZ;

        return new Vector3(localX, 0f, localZ);
    }

    private Vector3 ApplyCameraLocalTuningToLocalPosition(Vector3 localPosition)
    {
        if (!useCameraLocalPositionTuning)
            return localPosition;

        localPosition.x = localPosition.x * cameraLocalXScale + cameraLocalXOffsetM;
        localPosition.z = localPosition.z * cameraLocalZScale + cameraLocalZOffsetM;

        return localPosition;
    }

    private Vector3 ConvertCameraLocalToWorld(Vector3 localPosition, Vector3 cubeScale)
    {
        Quaternion yawCorrection = Quaternion.Euler(0f, cameraYawOffsetDeg, 0f);

        Vector3 correctedRight   = yawCorrection * cameraAnchor.right;
        Vector3 correctedForward = yawCorrection * cameraAnchor.forward;

        correctedRight.y   = 0f;
        correctedForward.y = 0f;

        if (correctedRight.sqrMagnitude   < 0.0001f) correctedRight   = transform.right;
        if (correctedForward.sqrMagnitude < 0.0001f) correctedForward = transform.forward;

        correctedRight.Normalize();
        correctedForward.Normalize();

        Vector3 worldPosition =
            cameraAnchor.position
            + correctedRight   * localPosition.x
            + correctedForward * localPosition.z;

        if (placeOnGround)
            worldPosition.y = yOffset + cubeScale.y * 0.5f;
        else
            worldPosition.y = cameraAnchor.position.y + yOffset;

        return worldPosition;
    }

    // ═════════════════════════════════════════════════════════════════════
    // 장애물 오브젝트 유틸리티
    // ═════════════════════════════════════════════════════════════════════

    private GameObject CreateObstacleObject(Detection detection)
    {
        GameObject obj = obstaclePrefab != null
            ? Instantiate(obstaclePrefab)
            : GameObject.CreatePrimitive(PrimitiveType.Cube);

        obj.name = "Obstacle_" + detection.name + "_" + detection.id;

        if (obstacleRoot != null)
            obj.transform.SetParent(obstacleRoot.transform, true);

        if (obj.GetComponent<BoxCollider>() == null)
            obj.AddComponent<BoxCollider>();

        ApplyObstacleTagAndLayer(obj);

        return obj;
    }

    private void ApplyObstacleTagAndLayer(GameObject obj)
    {
        if (!assignObstacleTagAndLayer || obj == null)
            return;

        if (!string.IsNullOrEmpty(obstacleTagName))
        {
            if (applyObstacleTagAndLayerRecursively)
                SetTagRecursively(obj, obstacleTagName);
            else
                TrySetObstacleTag(obj, obstacleTagName);
        }

        if (!string.IsNullOrEmpty(obstacleLayerName))
        {
            int obstacleLayer = LayerMask.NameToLayer(obstacleLayerName);

            if (obstacleLayer < 0)
            {
                if (!warnedMissingObstacleLayer)
                {
                    Debug.LogError("[GO1 WS Receiver] Unity Layer '" + obstacleLayerName + "'가 없습니다. Project Settings > Tags and Layers에서 추가하세요.");
                    warnedMissingObstacleLayer = true;
                }
                return;
            }

            if (applyObstacleTagAndLayerRecursively)
                SetLayerRecursively(obj, obstacleLayer);
            else
                obj.layer = obstacleLayer;
        }
    }

    private void SetTagRecursively(GameObject obj, string tagName)
    {
        if (obj == null || !TrySetObstacleTag(obj, tagName))
            return;

        foreach (Transform child in obj.transform)
        {
            if (child != null)
                SetTagRecursively(child.gameObject, tagName);
        }
    }

    private bool TrySetObstacleTag(GameObject obj, string tagName)
    {
        if (obj == null || string.IsNullOrEmpty(tagName))
            return false;

        try
        {
            obj.tag = tagName;
            return true;
        }
        catch (UnityException)
        {
            if (!warnedMissingObstacleTag)
            {
                Debug.LogError("[GO1 WS Receiver] Unity Tag '" + tagName + "'가 없습니다. Project Settings > Tags and Layers에서 추가하세요.");
                warnedMissingObstacleTag = true;
            }
            return false;
        }
    }

    private void SetLayerRecursively(GameObject obj, int layer)
    {
        if (obj == null)
            return;

        obj.layer = layer;

        foreach (Transform child in obj.transform)
        {
            if (child != null)
                SetLayerRecursively(child.gameObject, layer);
        }
    }

    private void UpdateObstacleColor(GameObject obj, string riskLevel)
    {
        Renderer rend = obj.GetComponent<Renderer>() ?? obj.GetComponentInChildren<Renderer>();

        if (rend == null)
            return;

        string risk = string.IsNullOrEmpty(riskLevel) ? "" : riskLevel.Trim().ToLower();
        Color color = risk == "near"                   ? Color.red
                    : (risk == "mid" || risk == "middle") ? Color.yellow
                    : risk == "far"                    ? Color.green
                    : Color.white;

        MaterialPropertyBlock mpb = new MaterialPropertyBlock();
        rend.GetPropertyBlock(mpb);
        mpb.SetColor("_Color", color);
        rend.SetPropertyBlock(mpb);
    }

    private void UpdateLabel(GameObject obj, Detection detection, float distanceM)
    {
        Transform labelTransform = obj.transform.Find("ObstacleLabel");
        TextMesh textMesh;

        if (labelTransform == null)
        {
            GameObject labelObj = new GameObject("ObstacleLabel");
            labelObj.transform.SetParent(obj.transform);
            labelObj.transform.localPosition = new Vector3(0f, 0.8f, 0f);
            labelObj.transform.localRotation = Quaternion.Euler(0f, 180f, 0f);

            textMesh = labelObj.AddComponent<TextMesh>();
            textMesh.fontSize      = 32;
            textMesh.characterSize = 0.05f;
            textMesh.anchor        = TextAnchor.MiddleCenter;
            textMesh.alignment     = TextAlignment.Center;
        }
        else
        {
            textMesh = labelTransform.GetComponent<TextMesh>() ?? labelTransform.gameObject.AddComponent<TextMesh>();
        }

        textMesh.text = detection.name + "\n" + detection.risk_level + "\n" + distanceM.ToString("F2") + "m";
    }

    private void UpdateNavMeshObstacle(GameObject obj)
    {
        NavMeshObstacle navObstacle = obj.GetComponent<NavMeshObstacle>();

        if (navObstacle == null && autoAddNavMeshObstacle)
            navObstacle = obj.AddComponent<NavMeshObstacle>();

        if (navObstacle == null)
            return;

        navObstacle.shape   = NavMeshObstacleShape.Box;
        navObstacle.size    = Vector3.one;
        navObstacle.center  = Vector3.zero;
        navObstacle.carving = navMeshObstacleCarving;
    }

    // ═════════════════════════════════════════════════════════════════════
    // 장애물 병합 / 추적
    // ═════════════════════════════════════════════════════════════════════

    private List<Detection> FilterDuplicateNearBboxes(List<Detection> detections)
    {
        if (detections == null || detections.Count <= 1)
            return detections ?? new List<Detection>();

        if (!ignoreNestedNearBboxes && !ignoreOverlappingNearBboxesInSamePacket)
            return detections;

        bool[] ignored = new bool[detections.Count];

        for (int i = 0; i < detections.Count; i++)
        {
            Detection a = detections[i];
            if (a == null || !IsNearRisk(a.risk_level) || IsFireExtinguisherDetection(a))
                continue;

            Rect rectA = GetBboxRect(a);
            float areaA = RectArea(rectA);
            if (areaA <= 0f) continue;

            for (int j = 0; j < detections.Count; j++)
            {
                if (i == j) continue;

                Detection b = detections[j];
                if (b == null || !IsNearRisk(b.risk_level) || IsFireExtinguisherDetection(b))
                    continue;

                Rect rectB = GetBboxRect(b);
                float areaB = RectArea(rectB);
                if (areaB <= 0f) continue;

                if (ignoreNestedNearBboxes && areaA <= areaB)
                {
                    float containment = RectIntersectionArea(rectA, rectB) / areaA;
                    if (containment >= nestedBboxContainmentThreshold)
                    {
                        ignored[i] = true;
                        break;
                    }
                }

                if (ignoreOverlappingNearBboxesInSamePacket && areaA <= areaB)
                {
                    float iou = RectIoU(rectA, rectB);
                    if (iou >= samePacketBboxIouThreshold)
                    {
                        ignored[i] = true;
                        break;
                    }
                }
            }
        }

        List<Detection> result = new List<Detection>();
        for (int i = 0; i < detections.Count; i++)
        {
            if (!ignored[i])
                result.Add(detections[i]);
        }

        return result;
    }

    private string FindMatchingObstacleKey(Detection detection, Vector3 newWorldPosition, HashSet<string> matchedKeysThisPacket)
    {
        if (!mergeSameNameByPosition && !mergeDifferentNameByPosition && !ignoreJsonOverlappingExistingNearObstacle)
            return null;

        string bestKey = null;
        float bestDistance = float.MaxValue;

        string newName  = string.IsNullOrEmpty(detection.name)  ? "" : detection.name;
        string newGroup = string.IsNullOrEmpty(detection.group) ? "" : detection.group;
        bool newIsNear  = IsNearRisk(detection.risk_level);
        Rect newBbox    = GetBboxRect(detection);

        foreach (KeyValuePair<string, GameObject> pair in obstacleObjects)
        {
            string key = pair.Key;
            bool alreadyMatchedInThisPacket = matchedKeysThisPacket != null && matchedKeysThisPacket.Contains(key);

            string oldName  = obstacleNames.ContainsKey(key)  ? obstacleNames[key]  : "";
            string oldGroup = obstacleGroups.ContainsKey(key) ? obstacleGroups[key] : "";

            bool sameName  = string.Equals(oldName, newName, StringComparison.OrdinalIgnoreCase);
            bool sameGroup = true;

            if (matchSameGroupOnly)
            {
                if (!string.IsNullOrEmpty(oldGroup) && !string.IsNullOrEmpty(newGroup))
                    sameGroup = string.Equals(oldGroup, newGroup, StringComparison.OrdinalIgnoreCase);
            }

            Vector3 oldPosition;
            if (obstacleLastPositions.ContainsKey(key))
                oldPosition = obstacleLastPositions[key];
            else if (pair.Value != null)
                oldPosition = pair.Value.transform.position;
            else
                continue;

            float distance = HorizontalDistance(oldPosition, newWorldPosition);

            bool canMerge = false;
            float allowedDistance = -1f;

            if (mergeSameNameByPosition && sameName && sameGroup)
            {
                canMerge = true;
                allowedDistance = mergeDistanceM;
            }
            else if (mergeDifferentNameByPosition && (!alreadyMatchedInThisPacket || allowSamePacketDifferentNameMerge))
            {
                canMerge = true;
                allowedDistance = differentNameMergeDistanceM;
            }

            if (ignoreJsonOverlappingExistingNearObstacle && newIsNear)
            {
                bool isFrozenNear = frozenNearObstacleKeys.Contains(key);

                if (!rayMergeOnlyFrozenNearObstacle || isFrozenNear)
                {
                    float nearMergeDistance = Mathf.Max(allowedDistance, existingNearWorldMergeDistanceM);
                    allowedDistance = nearMergeDistance;
                    canMerge = true;

                    if (obstacleLastImageBboxes.ContainsKey(key))
                    {
                        Rect oldBbox = obstacleLastImageBboxes[key];
                        float iou = RectIoU(oldBbox, newBbox);
                        float newArea = RectArea(newBbox);
                        float contained = newArea > 0f ? RectIntersectionArea(newBbox, oldBbox) / newArea : 0f;

                        if (iou >= samePacketBboxIouThreshold || contained >= nestedBboxContainmentThreshold)
                            distance = Mathf.Min(distance, 0f);
                    }

                    if (mergeExistingNearByCameraRay && cameraAnchor != null)
                    {
                        float rayPerp, depthDiff;
                        if (IsExistingObstacleOnDetectionRay(oldPosition, newWorldPosition, out rayPerp, out depthDiff))
                        {
                            distance = Mathf.Min(distance, rayPerp);
                            allowedDistance = Mathf.Max(allowedDistance, existingNearRayMergeRadiusM);
                        }
                    }
                }
            }

            if (!canMerge)
                continue;

            if (alreadyMatchedInThisPacket && mergeSameNameByPosition && sameName && sameGroup)
                continue;

            if (distance <= allowedDistance && distance < bestDistance)
            {
                bestDistance = distance;
                bestKey = key;
            }
        }

        return bestKey;
    }

    private bool IsExistingObstacleOnDetectionRay(Vector3 existingObstaclePos, Vector3 newEstimatedWorldPos, out float perpendicularDistance, out float depthDifference)
    {
        perpendicularDistance = float.MaxValue;
        depthDifference = float.MaxValue;

        if (cameraAnchor == null)
            return false;

        Vector3 cam = cameraAnchor.position;
        Vector3 ray = newEstimatedWorldPos - cam;
        ray.y = 0f;

        float newDepth = ray.magnitude;
        if (newDepth < 0.05f)
            return false;

        Vector3 dir   = ray / newDepth;
        Vector3 toOld = existingObstaclePos - cam;
        toOld.y = 0f;

        float oldProjection = Vector3.Dot(toOld, dir);
        if (oldProjection < 0f)
            return false;

        Vector3 closest = cam + dir * oldProjection;
        perpendicularDistance = HorizontalDistance(existingObstaclePos, closest);
        depthDifference       = Mathf.Abs(oldProjection - newDepth);

        return perpendicularDistance <= existingNearRayMergeRadiusM &&
               depthDifference       <= existingNearRayDepthToleranceM;
    }

    private string MakeNewObstacleKey(string cameraId, Detection detection)
    {
        string safeName = string.IsNullOrEmpty(detection.name) ? "unknown" : detection.name;
        string key = cameraId + "_" + safeName + "_track_" + nextTrackId;
        nextTrackId++;
        return key;
    }

    private string MakeFireExtinguisherObstacleKey(string safeCameraId) =>
        safeCameraId + "_fire_extinguisher_landmark";

    private float HorizontalDistance(Vector3 a, Vector3 b)
    {
        float dx = a.x - b.x;
        float dz = a.z - b.z;
        return Mathf.Sqrt(dx * dx + dz * dz);
    }

    // ═════════════════════════════════════════════════════════════════════
    // 거리 보정
    // ═════════════════════════════════════════════════════════════════════

    private float CalibrateDetectionDistanceToMeter(Detection detection)
    {
        if (detection == null)
            return minDistanceM;

        if (preferJsonDistanceCm && IsValidPositiveDistance(detection.distance_cm))
            return detection.distance_cm / 100.0f;

        if (preferJsonDistanceCm && IsValidPositiveDistance(detection.distance_cm_raw))
            return detection.distance_cm_raw / 100.0f;

        return CalibrateDepthToMeter(detection.rel_depth);
    }

    private bool IsValidPositiveDistance(float value) =>
        !float.IsNaN(value) && !float.IsInfinity(value) && value > 0.001f;

    private float CalibrateDepthToMeter(float relDepth)
    {
        if (float.IsNaN(relDepth) || float.IsInfinity(relDepth))
            return 0f;

        float value = Mathf.Max(0.0f, relDepth);
        return relDepthIsCentimeter ? value / 100.0f : value;
    }

    private Vector3 EstimateCubeScale(float distanceM, float bboxWidthPx, float bboxHeightPx)
    {
        float viewWidthAtDistance  = 2f * Mathf.Tan(horizontalFovDeg * 0.5f * Mathf.Deg2Rad) * distanceM;
        float viewHeightAtDistance = 2f * Mathf.Tan(verticalFovDeg   * 0.5f * Mathf.Deg2Rad) * distanceM;

        float estimatedWidth  = viewWidthAtDistance  * (bboxWidthPx  / imageWidth);
        float estimatedHeight = viewHeightAtDistance * (bboxHeightPx / imageHeight);
        float estimatedDepth  = Mathf.Max(estimatedWidth * depthRatio, minCubeSize);

        float sizeMultiplier = Mathf.Max(0.01f, bboxSizeMultiplier);
        estimatedWidth  *= sizeMultiplier;
        estimatedHeight *= sizeMultiplier;
        estimatedDepth  *= sizeMultiplier;

        return new Vector3(
            Mathf.Clamp(estimatedWidth,  minCubeSize, maxCubeSize),
            Mathf.Clamp(estimatedHeight, minCubeSize, maxCubeSize),
            Mathf.Clamp(estimatedDepth,  minCubeSize, maxCubeSize)
        );
    }

    // ═════════════════════════════════════════════════════════════════════
    // Stale / 전체 삭제
    // ═════════════════════════════════════════════════════════════════════

    private void RemoveStaleObstacles()
    {
        if (keepDetectedObstaclesForever)
            return;

        List<string> removeKeys = new List<string>();

        foreach (KeyValuePair<string, float> pair in lastSeenTimes)
        {
            if (Time.time - pair.Value > staleTime)
                removeKeys.Add(pair.Key);
        }

        foreach (string key in removeKeys)
        {
            if (obstacleObjects.TryGetValue(key, out GameObject obj))
            {
                Destroy(obj);
                obstacleObjects.Remove(key);
            }

            lastSeenTimes.Remove(key);
            obstacleNames.Remove(key);
            obstacleGroups.Remove(key);
            obstacleLastPositions.Remove(key);
            obstacleLastImageBboxes.Remove(key);
            frozenNearObstacleKeys.Remove(key);
        }
    }

    public void ClearAllDetectedObstacles()
    {
        foreach (KeyValuePair<string, GameObject> pair in obstacleObjects)
        {
            if (pair.Value != null)
                Destroy(pair.Value);
        }

        obstacleObjects.Clear();
        lastSeenTimes.Clear();
        obstacleNames.Clear();
        obstacleGroups.Clear();
        obstacleLastPositions.Clear();
        obstacleLastImageBboxes.Clear();
        frozenNearObstacleKeys.Clear();
    }

    // ═════════════════════════════════════════════════════════════════════
    // 카메라 회전 상태
    // ═════════════════════════════════════════════════════════════════════

    private void UpdateCameraRotationState()
    {
        Transform yawSource = cameraAnchor != null ? cameraAnchor : transform;

        if (yawSource == null)
        {
            currentCameraYawSpeedDegPerSec = 0f;
            return;
        }

        float currentYawDeg = yawSource.eulerAngles.y;

        if (!hasLastCameraYaw)
        {
            hasLastCameraYaw = true;
            lastCameraYawDeg = currentYawDeg;
            currentCameraYawSpeedDegPerSec = 0f;
            return;
        }

        float dt       = Mathf.Max(Time.deltaTime, 0.0001f);
        float yawDelta = Mathf.DeltaAngle(lastCameraYawDeg, currentYawDeg);
        currentCameraYawSpeedDegPerSec = Mathf.Abs(yawDelta) / dt;
        lastCameraYawDeg = currentYawDeg;

        if (currentCameraYawSpeedDegPerSec >= rotationYawSpeedThresholdDegPerSec)
            lastCameraRotationDetectedTime = Time.time;
    }

    // ═════════════════════════════════════════════════════════════════════
    // JSON 무시 조건
    // ═════════════════════════════════════════════════════════════════════

    private bool ShouldIgnoreJsonBecauseVirtualPathPlanning()
    {
        if (!ignoreJsonWhileVirtualPathPlanning)
            return false;

        RefreshAgentCacheIfNeeded();

        if (cachedAgents == null || cachedAgents.Length == 0)
            return false;

        foreach (GO1Agent agent in cachedAgents)
        {
            if (agent != null && agent.IsVirtualPathPlanning())
                return true;
        }

        return false;
    }

    private bool ShouldIgnoreJsonBecausePostReplanLock()
    {
        if (!ignoreJsonDuringPostReplanLock)
            return false;

        RefreshAgentCacheIfNeeded();

        if (cachedAgents == null || cachedAgents.Length == 0)
            return false;

        foreach (GO1Agent agent in cachedAgents)
        {
            if (agent != null && agent.IsPostReplanJsonBlocked())
                return true;
        }

        return false;
    }

    private bool ShouldIgnoreJsonBecauseCameraRotating()
    {
        if (!ignoreJsonWhileCameraRotating)
            return false;

        if (allowJsonWhileRealGo1PathActive && IsAnyAgentRealPathFollowingPhase())
            return false;

        if (!hasLastCameraYaw)
            return false;

        bool currentlyRotating    = currentCameraYawSpeedDegPerSec >= rotationYawSpeedThresholdDegPerSec;
        bool settlingAfterRotation = Time.time - lastCameraRotationDetectedTime < rotationSettleTime;

        return currentlyRotating || settlingAfterRotation;
    }

    private bool IsAnyAgentRealPathFollowingPhase()
    {
        RefreshAgentCacheIfNeeded();

        if (cachedAgents == null || cachedAgents.Length == 0)
            return false;

        foreach (GO1Agent agent in cachedAgents)
        {
            if (agent != null && agent.IsMoving() && !agent.IsVirtualPathPlanning())
                return true;
        }

        return false;
    }

    // ═════════════════════════════════════════════════════════════════════
    // Agent / 씬 탐색 유틸리티
    // ═════════════════════════════════════════════════════════════════════

    private void RefreshAgentCacheIfNeeded()
    {
        if (cachedAgents == null || Time.time - lastAgentRefreshTime > agentCacheRefreshInterval)
        {
            cachedAgents = FindObjectsByType<GO1Agent>(FindObjectsSortMode.None);
            lastAgentRefreshTime = Time.time;
        }
    }

    private void NotifyAgentsObstacleUpdated(GameObject obstacleObj)
    {
        if (!notifyAgentsOnObstacleUpdate || obstacleObj == null)
            return;

        RefreshAgentCacheIfNeeded();

        if (cachedAgents == null || cachedAgents.Length == 0)
            return;

        foreach (GO1Agent agent in cachedAgents)
        {
            if (agent == null)
                continue;

            try
            {
                agent.OnRuntimeObstacleUpdated(obstacleObj);
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[GO1 WS Receiver] 장애물 갱신 알림 중 GO1Agent 예외: " + ex.Message);
            }
        }
    }

    private Transform FindDeepChild(Transform parent, string targetName)
    {
        if (parent.name == targetName)
            return parent;

        foreach (Transform child in parent)
        {
            Transform result = FindDeepChild(child, targetName);
            if (result != null)
                return result;
        }

        return null;
    }

    private Transform FindSceneTransformNameContains(string namePart)
    {
        if (string.IsNullOrEmpty(namePart))
            return null;

        Transform[] all = FindObjectsByType<Transform>(FindObjectsSortMode.None);

        foreach (Transform t in all)
        {
            if (t == null || t.gameObject == null || !t.gameObject.scene.IsValid())
                continue;

            if (t.name.IndexOf(namePart, StringComparison.OrdinalIgnoreCase) >= 0)
                return t;
        }

        return null;
    }

    // ═════════════════════════════════════════════════════════════════════
    // Bbox 유틸리티
    // ═════════════════════════════════════════════════════════════════════

    private bool IsFireExtinguisherDetection(Detection detection)
    {
        if (detection == null)
            return false;

        string keyword = string.IsNullOrEmpty(fireExtinguisherNameKeyword) ? "fire extinguisher" : fireExtinguisherNameKeyword;
        string name    = detection.name  ?? "";
        string group   = detection.group ?? "";

        return name.IndexOf(keyword,         StringComparison.OrdinalIgnoreCase) >= 0 ||
               group.IndexOf(keyword,        StringComparison.OrdinalIgnoreCase) >= 0 ||
               name.IndexOf("extinguisher",  StringComparison.OrdinalIgnoreCase) >= 0 ||
               group.IndexOf("extinguisher", StringComparison.OrdinalIgnoreCase) >= 0 ||
               name.IndexOf("소화기",         StringComparison.OrdinalIgnoreCase) >= 0 ||
               group.IndexOf("소화기",        StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private bool IsNearRisk(string riskLevel) =>
        string.Equals(riskLevel, "near", StringComparison.OrdinalIgnoreCase);

    private Rect GetBboxRect(Detection detection)
    {
        if (detection == null || detection.bbox_xyxy == null || detection.bbox_xyxy.Length < 4)
            return new Rect(0f, 0f, 0f, 0f);

        float x1 = detection.bbox_xyxy[0];
        float y1 = detection.bbox_xyxy[1];
        float x2 = detection.bbox_xyxy[2];
        float y2 = detection.bbox_xyxy[3];

        return Rect.MinMaxRect(Mathf.Min(x1, x2), Mathf.Min(y1, y2), Mathf.Max(x1, x2), Mathf.Max(y1, y2));
    }

    private float RectArea(Rect r) =>
        Mathf.Max(0f, r.width) * Mathf.Max(0f, r.height);

    private float RectIntersectionArea(Rect a, Rect b)
    {
        float w = Mathf.Max(0f, Mathf.Min(a.xMax, b.xMax) - Mathf.Max(a.xMin, b.xMin));
        float h = Mathf.Max(0f, Mathf.Min(a.yMax, b.yMax) - Mathf.Max(a.yMin, b.yMin));
        return w * h;
    }

    private float RectIoU(Rect a, Rect b)
    {
        float intersection = RectIntersectionArea(a, b);
        float union = RectArea(a) + RectArea(b) - intersection;
        return union <= 0f ? 0f : intersection / union;
    }

    private void ClearQueuedJson()
    {
        while (jsonQueue.TryDequeue(out _)) { }
    }
}
