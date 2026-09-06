using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;
using UnityEngine.AI;

public class Go1ObstacleJsonReceiver : MonoBehaviour
{
    [Header("UDP Settings")]
    public int listenPort = 5009;

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
    [Tooltip("어안 원형 이미지 중심 X. 0.5면 이미지 중앙")]
    [Range(0f, 1f)]
    public float fisheyeCenterX = 0.5f;

    [Tooltip("어안 원형 이미지 중심 Y. 0.5면 이미지 중앙")]
    [Range(0f, 1f)]
    public float fisheyeCenterY = 0.5f;

    [Tooltip("어안 원형 영역 반지름. 이미지 짧은 변 기준 비율. 보통 0.48~0.55")]
    public float fisheyeRadiusNorm = 0.50f;

    [Tooltip("실제 전면 카메라의 대략적인 수평/대각 시야각. 어안이면 140~180부터 조정")]
    public float fisheyeFovDeg = 170f;

    [Tooltip("어안 왜곡 곡률. 1이면 선형 equidistant, 1보다 크면 가장자리 각도가 더 커짐")]
    public float fisheyePower = 1.0f;

    [Tooltip("화면 좌우가 반대로 나오면 체크")]
    public bool mirrorFisheyeX = false;

    [Tooltip("화면 상하가 반대로 나오면 체크")]
    public bool mirrorFisheyeY = false;

    [Header("Camera Direction Correction")]
    public float cameraYawOffsetDeg = 0f;
    public bool invertLocalX = false;
    public bool invertLocalZ = false;

    [Header("Camera Local Position Tuning")]
    [Tooltip("카메라 기준 좌표 보정 사용. 특정 색/객체 이름 기준이 아니라 Go1Cam local 좌표계 전체를 조정한다.")]
    public bool useCameraLocalPositionTuning = true;

    [Tooltip("Go1Cam 기준 오른쪽/왼쪽 위치 보정. +값이면 카메라 기준 오른쪽, -값이면 왼쪽")]
    public float cameraLocalXOffsetM = 0.0f;

    [Tooltip("Go1Cam 기준 앞/뒤 위치 보정. +값이면 카메라 앞쪽, -값이면 카메라 쪽으로 가까워짐")]
    public float cameraLocalZOffsetM = 0.0f;

    [Tooltip("Go1Cam 기준 좌우 퍼짐 배율. 1보다 크면 좌우로 더 벌어지고, 작으면 중앙으로 모임")]
    public float cameraLocalXScale = 1.0f;

    [Tooltip("Go1Cam 기준 거리 배율. 1보다 크면 전체적으로 멀어지고, 작으면 가까워짐")]
    public float cameraLocalZScale = 1.0f;

    [Header("Camera Side Ray Distance Tuning")]
    [Tooltip("화면 좌우 끝 물체를 ray 방향으로 더 멀리 보내는 보정 사용")]
    public bool useSideRayDistanceCorrection = true;

    [Tooltip("0이면 보정 없음, 1이면 distance / cos(theta) 완전 적용")]
    [Range(0f, 1f)]
    public float sideRayDistanceCorrectionStrength = 0.35f;

    [Tooltip("좌우 끝에서 거리 보정이 너무 커지는 것을 막는 최소 dot 값")]
    public float minSideForwardDot = 0.45f;

    [Header("Camera Image Settings")]
    public int imageWidth = 480;
    public int imageHeight = 360;

    [Tooltip("fallback용 수평 시야각")]
    public float horizontalFovDeg = 90f;

    [Tooltip("fallback용 수직 시야각")]
    public float verticalFovDeg = 60f;

    [Header("Distance Settings")]
    [Tooltip("JSON에 distance_cm / distance_cm_raw 값이 있으면 rel_depth보다 우선 사용합니다. 현재 AI 서버가 cm 단위 거리값을 보내는 경우 true 권장")]
    public bool preferJsonDistanceCm = true;

    public float distanceScale = 1.0f;

    [Tooltip("거리 보정값. 기본값은 0")]
    public float distanceOffsetM = 0.0f;

    [Tooltip("true면 JSON rel_depth 값을 cm로 보고 meter로 변환한다. 2차식 보정은 사용하지 않는다.")]
    public bool relDepthIsCentimeter = true;

    public float minDistanceM = 0.1f;
    public float maxDistanceM = 5.0f;

    [Header("Risk Filter")]
    [Tooltip("false면 near/mid/far 모두 표시")]
    public bool onlyShowNearObstacle = false;
    public string visibleRiskLevel = "near";

    [Header("Fire Extinguisher Landmark Correction")]
    [Tooltip("JSON name에 fire extinguisher가 들어오면 near가 아니어도 무조건 후보로 처리합니다.")]
    public bool alwaysShowFireExtinguisherJson = true;

    [Tooltip("소화기 탐지 이름 판별 키워드. 예: fire extinguisher, extinguisher, 소화기") ]
    public string fireExtinguisherNameKeyword = "fire extinguisher";

    [Tooltip("Unity 맵에 이미 배치되어 있는 실제 소화기 Transform. 비워두면 이름으로 자동 탐색합니다.")]
    public Transform knownFireExtinguisher;

    [Tooltip("knownFireExtinguisher가 비어 있을 때 자동으로 찾을 오브젝트 이름 일부") ]
    public string autoFindKnownFireExtinguisherName = "fire extinguisher";

    [Tooltip("소화기 JSON으로 추정한 위치와 맵에 존재하는 소화기 위치 차이를 이용해 가상 GO1 위치를 보정합니다.")]
    public bool correctGo1PoseByFireExtinguisher = true;

    [Tooltip("보정은 UnityTeleopAndMirror의 unityFixedStartPos를 이동시키는 방식으로 적용합니다. 비워두면 자동 탐색합니다.")]
    public UnityTeleopAndMirror unityTeleopAndMirror;

    [Tooltip("UnityTeleopAndMirror를 사용하지 못할 때 직접 이동시킬 GO1 root. 보통 go1 루트입니다.")]
    public Transform go1RootToCorrect;

    [Tooltip("true면 UTM 기준점 보정 사용. driveByState가 켜져 있을 때 위치 보정이 유지되려면 true 권장") ]
    public bool useUnityTeleopCorrectionForFireExtinguisher = true;

    [Tooltip("소화기 위치 오차 보정 반영 비율. 1이면 계산된 오차를 한 번에 적용, 0.5면 절반만 적용") ]
    [Range(0f, 1f)]
    public float fireExtinguisherCorrectionGain = 1.0f;

    [Tooltip("한 번에 적용할 최대 위치 보정 거리. 너무 큰 순간이동을 막기 위한 값") ]
    public float maxFireExtinguisherCorrectionM = 1.0f;

    [Tooltip("이 거리보다 작은 오차는 무시합니다.")]
    public float fireExtinguisherCorrectionDeadzoneM = 0.05f;

    [Tooltip("소화기 기반 위치 보정을 너무 자주 하지 않도록 막는 최소 간격") ]
    public float fireExtinguisherCorrectionCooldown = 0.5f;

    [Tooltip("소화기 장애물 표시 위치를 탐지 추정 위치가 아니라 맵에 존재하는 소화기 위치에 고정합니다.")]
    public bool forceFireExtinguisherObstacleToKnownPosition = true;

    [Tooltip("소화기 landmark 보정 로그 출력") ]
    public bool debugFireExtinguisherCorrection = true;

    [Header("Fire Landmark Global Map Sync")]
    [Tooltip("소화기 landmark 보정이 실제로 적용되면, 기존에 JSON으로 생성된 장애물 지도 전체를 같은 delta만큼 이동합니다.")]
    public bool moveDetectedObstacleMapWithFireCorrection = true;

    [Tooltip("GO1Agent 또는 UTM에 보정이 실제 적용된 경우에만 장애물 지도 전체를 이동합니다. false면 fallback 보정에도 동일하게 이동합니다.")]
    public bool moveDetectedObstacleMapOnlyWhenGo1CorrectionApplied = true;

    [Tooltip("소화기 보정으로 장애물 지도 전체를 이동한 뒤, 소화기 landmark 표시 오브젝트는 Known Fire Extinguisher 위치에 다시 고정합니다.")]
    public bool keepFireLandmarkAtKnownPositionAfterMapShift = true;

    [Tooltip("소화기 기준으로 GO1/장애물 지도 전체를 이동하는 로그 출력")]
    public bool debugFireLandmarkGlobalMapSync = true;

    [Header("Fire Landmark Correction Policy")]
    [Tooltip("true면 소화기 보정은 risk_level이 near인 경우에만 수행합니다. middle/far는 표시만 하고 보정에는 쓰지 않습니다.")]
    public bool correctFireExtinguisherOnlyWhenNear = true;

    [Tooltip("true면 GO1Agent에게 보정 요청을 넘겨 자율주행 중 PATH_CANCEL -> 정지 -> 보정 -> 재탐색 흐름을 사용합니다.")]
    public bool routeFireCorrectionThroughGo1Agent = true;

    [Tooltip("GO1Agent가 보정 요청을 거절했을 때 Receiver에서 즉시 보정을 적용합니다. 반복 재탐색 방지를 위해 기본 false 권장")]
    public bool fallbackImmediateFireCorrectionWhenAgentRejects = false;

    [Header("Obstacle Prefab")]
    public GameObject obstaclePrefab;

    [Header("Obstacle Tag / Layer")]
    [Tooltip("JSON으로 생성/갱신된 장애물을 ML-Agent Ray Sensor와 LayerMask가 감지할 수 있도록 Tag/Layer를 자동 지정합니다.")]
    public bool assignObstacleTagAndLayer = true;

    [Tooltip("ML-Agent Ray Perception Sensor의 Detectable Tags에 들어가는 장애물 태그 이름")]
    public string obstacleTagName = "Obstacle";

    [Tooltip("GO1Agent의 Obstacle Layer Mask와 Physics.Check 계열에서 사용하는 장애물 레이어 이름")]
    public string obstacleLayerName = "Obstacle";

    [Tooltip("프리팹 자식에 Collider가 있는 경우를 위해 자식 오브젝트까지 같은 Tag/Layer를 적용합니다.")]
    public bool applyObstacleTagAndLayerRecursively = true;

    [Header("Obstacle Size Settings")]
    public float minCubeSize = 0.15f;
    public float maxCubeSize = 3.0f;

    [Tooltip("BBOX 기반으로 계산된 장애물 박스 크기 배율. 1.5면 기존보다 1.5배 크게 생성됩니다.")]
    public float bboxSizeMultiplier = 1.5f;

    public float depthRatio = 0.6f;
    public float yOffset = 0.0f;
    public bool placeOnGround = true;

    [Header("Obstacle Merge / Tracking")]
    public bool mergeSameNameByPosition = true;
    public float mergeDistanceM = 0.45f;
    public bool matchSameGroupOnly = true;

    [Tooltip("이름/group이 달라도 위치가 매우 비슷하면 같은 장애물로 병합합니다. 탐지 모델이 같은 물체를 chair/person/trash bin처럼 다르게 분류할 때 중복 생성을 줄입니다.")]
    public bool mergeDifferentNameByPosition = true;

    [Tooltip("이름/group이 다른 물체를 같은 장애물로 볼 최대 수평 거리(m). 너무 크면 서로 다른 물체가 합쳐질 수 있으므로 0.25~0.45 권장")]
    public float differentNameMergeDistanceM = 0.35f;

    [Tooltip("한 JSON 패킷 안에서 이미 매칭된 장애물도, 위치가 매우 가까우면 다시 같은 장애물로 병합합니다. 같은 물체가 한 프레임에서 여러 class로 잡힐 때 사용합니다.")]
    public bool allowSamePacketDifferentNameMerge = true;

    [Header("Near BBOX Duplicate / Fixed Map")]
    [Tooltip("같은 JSON 안에서 큰 near BBOX 안에 들어간 작은 near BBOX는 같은 물체의 중복 탐지로 보고 무시합니다.")]
    public bool ignoreNestedNearBboxes = true;

    [Range(0f, 1f)]
    [Tooltip("작은 BBOX 면적 중 몇 % 이상이 큰 BBOX 안에 들어가면 중복으로 볼지 설정합니다.")]
    public float nestedBboxContainmentThreshold = 0.75f;

    [Tooltip("같은 JSON 안에서 서로 많이 겹치는 near BBOX는 하나만 남깁니다. 기본적으로 더 큰 BBOX를 유지합니다.")]
    public bool ignoreOverlappingNearBboxesInSamePacket = true;

    [Range(0f, 1f)]
    [Tooltip("같은 JSON 안의 BBOX IoU가 이 값 이상이면 중복 near BBOX로 판단합니다.")]
    public float samePacketBboxIouThreshold = 0.55f;

    [Tooltip("이미 생성된 near 장애물과 겹치는 새 JSON은 새 장애물로 만들지 않고 기존 장애물로 흡수합니다.")]
    public bool ignoreJsonOverlappingExistingNearObstacle = true;

    [Tooltip("이미 생성된 near 장애물과 이 거리 이내면 같은 장애물로 취급합니다. 이름이 달라도 적용됩니다.")]
    public float existingNearWorldMergeDistanceM = 0.55f;

    [Tooltip("Go1이 이동하면서 같은 물체의 추정 worldPosition이 크게 흔들릴 때, 카메라 ray가 기존 고정 near 장애물을 지나가면 같은 물체로 흡수합니다.")]
    public bool mergeExistingNearByCameraRay = true;

    [Tooltip("카메라 ray와 기존 고정 near 장애물 중심 사이의 허용 수평 거리(m). 같은 물체가 이동 중 여러 위치로 찍히면 0.6~1.0 권장")]
    public float existingNearRayMergeRadiusM = 0.8f;

    [Tooltip("카메라 ray 방향 기준 깊이 차이 허용값(m). depth 추정이 흔들릴수록 크게 둡니다. 1.0~2.5 권장")]
    public float existingNearRayDepthToleranceM = 2.0f;

    [Tooltip("ray 기반 병합은 이미 고정된 near 장애물에만 적용합니다. 새로 생성된 지도 장애물이 끌려가지 않도록 true 권장")]
    public bool rayMergeOnlyFrozenNearObstacle = true;

    [Tooltip("near 장애물이 한 번 생성되면 이후 같은 장애물로 판단된 JSON이 들어와도 위치/크기를 갱신하지 않습니다. 가상 Go1 이동 때문에 장애물이 같이 끌려가는 현상을 막습니다.")]
    public bool freezeNearObstacleAfterCreate = true;

    [Tooltip("고정된 near 장애물에 중복 JSON이 들어와도 GO1Agent 재탐색 알림을 반복하지 않습니다.")]
    public bool suppressNotifyForFrozenDuplicate = true;

    public bool clearOldObstaclesOnStart = false;

    [Header("Obstacle Lifetime")]
    [Tooltip("true면 한 번 생성된 장애물을 staleTime이 지나도 삭제하지 않습니다. 재탐색/경로검사용 장애물 지도를 유지할 때 사용합니다.")]
    public bool keepDetectedObstaclesForever = true;

    [Tooltip("keepDetectedObstaclesForever가 false일 때만 적용됩니다. 이 시간 동안 다시 탐지되지 않은 장애물을 삭제합니다.")]
    public float staleTime = 2.0f;

    [Header("Smoothing")]
    public bool useSmoothing = true;
    public float smoothSpeed = 15f;

    [Header("Runtime Replan Notify")]
    [Tooltip("장애물이 생성/갱신될 때 GO1Agent에게 알려서 현재 이동 경로 차단 여부를 검사하게 한다.")]
    public bool notifyAgentsOnObstacleUpdate = true;

    [Tooltip("장애물 프리팹에 NavMeshObstacle이 없으면 자동으로 추가한다.")]
    public bool autoAddNavMeshObstacle = true;

    [Tooltip("NavMeshObstacle carving을 켜서 재탐색 시 장애물을 피하도록 한다.")]
    public bool navMeshObstacleCarving = true;

    [Tooltip("GO1Agent 검색 캐시 갱신 주기")]
    public float agentCacheRefreshInterval = 0.5f;

    [Header("Virtual Path Planning JSON Ignore")]
    [Tooltip("가상 GO1이 경로 탐색 중일 때만 JSON 장애물 생성/갱신을 무시한다. 실제 GO1과 함께 이동 중일 때는 JSON을 허용한다.")]
    public bool ignoreJsonWhileVirtualPathPlanning = true;

    [Tooltip("가상 경로 탐색 중 들어온 JSON 큐를 비운다. 탐색 종료 후 오래된 JSON이 한 번에 반영되는 것을 막는다.")]
    public bool clearQueuedJsonWhileVirtualPathPlanning = true;

    [Tooltip("가상 경로 탐색 중에는 기존 장애물 stale 제거도 멈춘다. 기존 장애물을 유지한 채 경로 탐색하기 위함.")]
    public bool pauseStaleRemovalWhileVirtualPathPlanning = true;

    [Tooltip("가상 경로 탐색 중 JSON 무시 로그를 출력한다.")]
    public bool printVirtualPlanningIgnoreLog = true;

    [Header("Rotation JSON Ignore")]
    [Tooltip("GO1Cam 또는 cameraAnchor가 회전 중이면 JSON 장애물 생성/갱신을 잠시 무시한다. 회전 중 들어온 JSON은 카메라 방향 딜레이 때문에 위치가 틀어질 수 있다.")]
    public bool ignoreJsonWhileCameraRotating = true;

    [Tooltip("이 값 이상으로 yaw가 변하면 회전 중으로 판단한다. 단위: deg/sec")]
    public float rotationYawSpeedThresholdDegPerSec = 8.0f;

    [Tooltip("회전이 멈춘 뒤 이 시간만큼 더 기다린 후 JSON 처리를 재개한다. 카메라/탐지 딜레이 보정용")]
    public float rotationSettleTime = 0.45f;

    [Tooltip("회전 중 들어온 JSON 큐를 비운다. 회전 중 오래된 JSON이 회전 종료 후 반영되는 것을 막는다.")]
    public bool clearQueuedJsonWhileRotating = true;

    [Tooltip("회전 중에는 기존 장애물 stale 제거를 멈춘다. 기존 장애물이 회전 중 사라지는 것을 방지한다.")]
    public bool pauseStaleRemovalWhileRotating = true;

    [Tooltip("회전 중 JSON 무시 로그 출력")]
    public bool printRotationIgnoreLog = true;

    [Tooltip("실제 GO1과 가상 GO1이 같이 경로를 따라 이동 중이면 회전 중이어도 JSON 생성을 허용한다.")]
    public bool allowJsonWhileRealGo1PathActive = true;

    [Header("Post Runtime Replan JSON Ignore")]
    [Tooltip("재탐색으로 새 경로를 전송한 직후 일정 시간 동안 JSON 장애물 생성/갱신을 막는다.")]
    public bool ignoreJsonDuringPostReplanLock = true;

    [Tooltip("재탐색 직후 잠금 시간 동안 들어온 JSON 큐를 비운다.")]
    public bool clearQueuedJsonDuringPostReplanLock = true;

    [Tooltip("재탐색 직후 잠금 시간 동안 기존 장애물 stale 제거를 멈춘다.")]
    public bool pauseStaleRemovalDuringPostReplanLock = true;

    [Tooltip("재탐색 직후 JSON 잠금 로그 출력")]
    public bool printPostReplanLockLog = true;

    [Header("GO1 Real Motion State JSON")]
    [Tooltip("5009 포트로 장애물 JSON과 함께 들어오는 GO1 실제 이동 상태 JSON을 처리합니다. state_change 값만 실제 이동 판단에 사용합니다.")]
    public bool receiveGo1MotionStateJson = true;

    [Tooltip("true면 state_change=true를 현실 GO1 이동 중으로, false를 정지로 판단합니다.")]
    public bool useStateChangeAsRealGo1Moving = true;

    [Tooltip("이 시간 동안 새 GO1 상태 JSON이 안 들어오면 현실 GO1이 안 움직이는 것으로 봅니다. 0 이하면 timeout을 사용하지 않습니다.")]
    public float go1MotionStateTimeoutSec = 1.0f;

    [Tooltip("가상 경로 탐색/회전/재탐색 잠금으로 장애물 JSON을 버릴 때도 GO1 이동 상태 JSON은 계속 읽습니다.")]
    public bool processMotionStateEvenWhenIgnoringObstacleJson = true;

    [Tooltip("state_change 값이 바뀔 때 로그를 출력합니다.")]
    public bool printGo1MotionStateLog = true;

    [Header("Debug")]
    public bool printReceivedJson = false;
    public bool printObstacleInfo = true;
    public bool drawDebugRay = true;

    private UdpClient udpClient;
    private Thread receiveThread;
    private bool isRunning;

    private readonly ConcurrentQueue<string> jsonQueue = new ConcurrentQueue<string>();

    private readonly Dictionary<string, GameObject> obstacleObjects = new Dictionary<string, GameObject>();
    private readonly Dictionary<string, float> lastSeenTimes = new Dictionary<string, float>();
    private readonly Dictionary<string, string> obstacleNames = new Dictionary<string, string>();
    private readonly Dictionary<string, string> obstacleGroups = new Dictionary<string, string>();
    private readonly Dictionary<string, Vector3> obstacleLastPositions = new Dictionary<string, Vector3>();
    private readonly Dictionary<string, Rect> obstacleLastImageBboxes = new Dictionary<string, Rect>();
    private readonly HashSet<string> frozenNearObstacleKeys = new HashSet<string>();

    private GameObject obstacleRoot;
    private int nextTrackId = 0;

    private GO1Agent[] cachedAgents;
    private float lastAgentRefreshTime = -999f;
    private bool wasIgnoringJsonBecauseVirtualPlanning = false;

    // 폐루프 인과 타임라인용: 탐지 패킷이 트윈에 도달한 순간(obstacle_detected 이벤트)을 기록한다.
    // 패킷의 timestamp(센서 쪽 시각)를 함께 남겨 "탐지→트윈 도달" 편도 지연을 계산할 수 있게 한다.
    private RealGo1CaseStudyLogger caseStudyLogger;
    private bool caseStudyLoggerSearched = false;

    private bool hasLastCameraYaw = false;
    private float lastCameraYawDeg = 0f;
    private float currentCameraYawSpeedDegPerSec = 0f;
    private float lastCameraRotationDetectedTime = -999f;
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
        // 사용자 정책: 이 값만 실제 GO1 이동 판단에 사용한다.
        // true  = 현실 GO1이 움직이는 중
        // false = 현실 GO1이 움직이지 않는 중
        public bool state_change;

        // 아래 값들은 로그/디버그용으로만 보관한다. 이동 판단에는 사용하지 않는다.
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

    private void Start()
    {
        SetupCameraAnchor();
        SetupFireExtinguisherLandmark();
        SetupObstacleRoot();
        StartReceiver();
    }

    private void Update()
    {
        UpdateCameraRotationState();

        // 핵심 정책:
        // 1) 가상 GO1이 "경로 탐색만" 하는 동안에는 JSON 장애물 생성을 막는다.
        //    - 기존 장애물은 유지한 채 그 장애물을 기준으로 경로를 찾게 하기 위함.
        // 2) 가상 경로 탐색이 끝나고 현실 GO1 + 가상 GO1이 같이 이동하는 동안에는 JSON을 허용한다.
        // 3) 단, GO1Cam/cameraAnchor가 회전 중이면 JSON 생성/갱신을 잠시 막는다.
        //    - 회전 중 들어온 JSON은 카메라 방향 딜레이 때문에 장애물 위치가 흔들리기 때문.
        if (ShouldIgnoreJsonBecauseVirtualPathPlanning())
        {
            if (!wasIgnoringJsonBecauseVirtualPlanning && printVirtualPlanningIgnoreLog)
            {
                Debug.Log("[GO1 Obstacle Receiver] 가상 GO1 경로 탐색 중이므로 새 JSON 장애물 생성/갱신을 일시 중지합니다.");
            }

            wasIgnoringJsonBecauseVirtualPlanning = true;

            if (processMotionStateEvenWhenIgnoringObstacleJson)
            {
                DrainQueuedJsonForMotionState(clearQueuedJsonWhileVirtualPathPlanning);
            }
            else if (clearQueuedJsonWhileVirtualPathPlanning)
            {
                ClearQueuedJson();
            }

            if (!pauseStaleRemovalWhileVirtualPathPlanning)
            {
                RemoveStaleObstacles();
            }

            return;
        }

        if (wasIgnoringJsonBecauseVirtualPlanning && printVirtualPlanningIgnoreLog)
        {
            Debug.Log("[GO1 Obstacle Receiver] 가상 경로 탐색 종료 → JSON 장애물 생성/갱신 재개 가능");
        }

        wasIgnoringJsonBecauseVirtualPlanning = false;

        if (ShouldIgnoreJsonBecausePostReplanLock())
        {
            if (!wasIgnoringJsonBecausePostReplanLock && printPostReplanLockLog)
            {
                Debug.Log(
                    "[GO1 Obstacle Receiver] 재탐색 직후 잠금 중이므로 JSON 장애물 생성/갱신을 일시 중지합니다. " +
                    "remaining=" + GetPostReplanLockRemaining().ToString("F1") + "s"
                );
            }

            wasIgnoringJsonBecausePostReplanLock = true;

            if (processMotionStateEvenWhenIgnoringObstacleJson)
            {
                DrainQueuedJsonForMotionState(clearQueuedJsonDuringPostReplanLock);
            }
            else if (clearQueuedJsonDuringPostReplanLock)
            {
                ClearQueuedJson();
            }

            if (!pauseStaleRemovalDuringPostReplanLock)
            {
                RemoveStaleObstacles();
            }

            return;
        }

        if (wasIgnoringJsonBecausePostReplanLock && printPostReplanLockLog)
        {
            Debug.Log("[GO1 Obstacle Receiver] 재탐색 직후 잠금 종료 → JSON 장애물 생성/갱신 재개");
        }

        wasIgnoringJsonBecausePostReplanLock = false;

        if (ShouldIgnoreJsonBecauseCameraRotating())
        {
            if (!wasIgnoringJsonBecauseRotation && printRotationIgnoreLog)
            {
                Debug.Log(
                    "[GO1 Obstacle Receiver] GO1Cam 회전 중/회전 직후 안정화 대기 중이므로 JSON 장애물 생성/갱신을 일시 중지합니다. " +
                    "yawSpeed=" + currentCameraYawSpeedDegPerSec.ToString("F1") + " deg/s"
                );
            }

            wasIgnoringJsonBecauseRotation = true;

            if (processMotionStateEvenWhenIgnoringObstacleJson)
            {
                DrainQueuedJsonForMotionState(clearQueuedJsonWhileRotating);
            }
            else if (clearQueuedJsonWhileRotating)
            {
                ClearQueuedJson();
            }

            if (!pauseStaleRemovalWhileRotating)
            {
                RemoveStaleObstacles();
            }

            return;
        }

        if (wasIgnoringJsonBecauseRotation && printRotationIgnoreLog)
        {
            Debug.Log("[GO1 Obstacle Receiver] GO1Cam 회전 안정화 완료 → JSON 장애물 생성/갱신 재개");
        }

        wasIgnoringJsonBecauseRotation = false;

        while (jsonQueue.TryDequeue(out string json))
        {
            if (printReceivedJson)
                Debug.Log("[UDP 5009 JSON 수신]\n" + json);

            ProcessJson(json);
        }

        RemoveStaleObstacles();
    }

    // GO1Agent가 M키 경로 생성 직전/경로 전송 직전에 호출한다.
    // 일반 Update()의 가상 경로 탐색 ignore/큐 삭제 타이밍 때문에
    // 소화기 보정 JSON이 경로 생성 이후에 처리되는 문제를 막기 위한 강제 처리 루틴이다.
    public int ProcessQueuedJsonForPathPlanningGate(int maxPackets = 50)
    {
        int processed = 0;
        int limit = Mathf.Max(1, maxPackets);

        while (processed < limit && jsonQueue.TryDequeue(out string json))
        {
            if (printReceivedJson)
                Debug.Log("[UDP 5009 JSON 수신 - path planning gate]\n" + json);

            ProcessJson(json);
            processed++;
        }

        return processed;
    }

    public int GetQueuedJsonCount()
    {
        return jsonQueue.Count;
    }

    private void SetupCameraAnchor()
    {
        if (cameraAnchor != null)
        {
            Debug.Log("[GO1 Obstacle Receiver] Camera Anchor 사용: " + cameraAnchor.name);
        }
        else
        {
            Transform found = FindDeepChild(transform, autoFindCameraName);

            if (found != null)
            {
                cameraAnchor = found;
                Debug.Log("[GO1 Obstacle Receiver] 자동으로 Camera Anchor 찾음: " + cameraAnchor.name);
            }
            else
            {
                cameraAnchor = transform;
                Debug.LogWarning("[GO1 Obstacle Receiver] Go1Cam을 찾지 못했습니다. 현재 go1 transform 기준으로 생성합니다.");
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
                Debug.Log("[GO1 Obstacle Receiver] Unity Camera 사용: " + go1ViewCamera.name);
            else
                Debug.LogWarning("[GO1 Obstacle Receiver] Camera 컴포넌트를 찾지 못했습니다. 수동 FOV 계산으로 fallback 합니다.");
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
                "[GO1 Obstacle Receiver] 소화기 landmark 설정 | " +
                "known=" + (knownFireExtinguisher != null ? knownFireExtinguisher.name : "null") +
                ", utm=" + (unityTeleopAndMirror != null ? unityTeleopAndMirror.name : "null") +
                ", go1Root=" + (go1RootToCorrect != null ? go1RootToCorrect.name : "null")
            );
        }
    }

    private Transform FindSceneTransformNameContains(string namePart)
    {
        if (string.IsNullOrEmpty(namePart))
            return null;

        Transform[] all = FindObjectsByType<Transform>(FindObjectsSortMode.None);
        foreach (Transform t in all)
        {
            if (t == null || t.gameObject == null)
                continue;

            if (!t.gameObject.scene.IsValid())
                continue;

            if (t.name.IndexOf(namePart, StringComparison.OrdinalIgnoreCase) >= 0)
                return t;
        }

        return null;
    }

    private bool IsFireExtinguisherDetection(Detection detection)
    {
        if (detection == null)
            return false;

        string keyword = string.IsNullOrEmpty(fireExtinguisherNameKeyword)
            ? "fire extinguisher"
            : fireExtinguisherNameKeyword;

        string name = detection.name ?? "";
        string group = detection.group ?? "";

        return name.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0 ||
               group.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0 ||
               name.IndexOf("extinguisher", StringComparison.OrdinalIgnoreCase) >= 0 ||
               group.IndexOf("extinguisher", StringComparison.OrdinalIgnoreCase) >= 0 ||
               name.IndexOf("소화기", StringComparison.OrdinalIgnoreCase) >= 0 ||
               group.IndexOf("소화기", StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private string MakeFireExtinguisherObstacleKey(string safeCameraId)
    {
        return safeCameraId + "_fire_extinguisher_landmark";
    }

    private void ApplyFireExtinguisherLandmarkCorrection(Vector3 detectedWorldPosition, Detection detection)
    {
        if (!correctGo1PoseByFireExtinguisher)
            return;

        if (detection == null)
            return;

        bool isNear = IsNearRisk(detection.risk_level);

        // 정책: 소화기 correction은 near로 들어온 경우에만 사용한다.
        // middle/far 소화기는 Always Show 옵션으로 표시할 수는 있지만 위치 보정에는 사용하지 않는다.
        if (correctFireExtinguisherOnlyWhenNear && !isNear)
        {
            if (debugFireExtinguisherCorrection)
            {
                Debug.Log(
                    "[GO1 Obstacle Receiver] 소화기 landmark 보정 생략: near가 아님 | " +
                    "risk=" + detection.risk_level + ", name=" + detection.name
                );
            }
            return;
        }

        if (knownFireExtinguisher == null)
            SetupFireExtinguisherLandmark();

        if (knownFireExtinguisher == null)
        {
            if (debugFireExtinguisherCorrection)
                Debug.LogWarning("[GO1 Obstacle Receiver] 소화기 landmark 보정 실패: knownFireExtinguisher가 없습니다.");
            return;
        }

        if (Time.time - lastFireExtinguisherCorrectionTime < Mathf.Max(0f, fireExtinguisherCorrectionCooldown))
            return;

        Vector3 knownPos = knownFireExtinguisher.position;
        Vector3 delta = knownPos - detectedWorldPosition;
        delta.y = 0f;

        float error = delta.magnitude;
        if (error < fireExtinguisherCorrectionDeadzoneM)
        {
            if (debugFireExtinguisherCorrection)
            {
                Debug.Log(
                    "[GO1 Obstacle Receiver] 소화기 landmark 오차가 작아 보정 생략 | " +
                    $"error={error:F3}m, detected=({detectedWorldPosition.x:F3},{detectedWorldPosition.z:F3}), " +
                    $"known=({knownPos.x:F3},{knownPos.z:F3})"
                );
            }
            return;
        }

        float maxCorrection = Mathf.Max(0.01f, maxFireExtinguisherCorrectionM);
        if (delta.magnitude > maxCorrection)
            delta = delta.normalized * maxCorrection;

        delta *= Mathf.Clamp01(fireExtinguisherCorrectionGain);

        bool acceptedByAgent = false;
        Vector3 actuallyAppliedDelta = delta;

        if (routeFireCorrectionThroughGo1Agent)
        {
            acceptedByAgent = TryRequestFireCorrectionFromAgents(
                delta,
                detection,
                detectedWorldPosition,
                knownPos,
                isNear,
                out actuallyAppliedDelta
            );

            if (acceptedByAgent)
            {
                lastFireExtinguisherCorrectionTime = Time.time;

                // 핵심: 소화기 기준으로 GO1 기준점을 보정했으면,
                // 이미 JSON으로 생성되어 있던 장애물 지도도 같은 delta만큼 같이 이동한다.
                ApplyFireLandmarkDeltaToDetectedObstacleMap(actuallyAppliedDelta, "agent-accepted");

                if (debugFireExtinguisherCorrection)
                {
                    Debug.Log(
                        "[GO1 Obstacle Receiver] 소화기 landmark 보정 요청을 GO1Agent로 전달 완료 | " +
                        $"risk={detection.risk_level}, rawError={error:F3}m, " +
                        $"rawCorrection=({delta.x:F3},{delta.z:F3}), appliedCorrection=({actuallyAppliedDelta.x:F3},{actuallyAppliedDelta.z:F3}), " +
                        $"detected=({detectedWorldPosition.x:F3},{detectedWorldPosition.z:F3}), " +
                        $"known=({knownPos.x:F3},{knownPos.z:F3}), name={detection.name}"
                    );
                }

                return;
            }
        }

        if (!fallbackImmediateFireCorrectionWhenAgentRejects)
        {
            if (debugFireExtinguisherCorrection)
            {
                Debug.Log(
                    "[GO1 Obstacle Receiver] 소화기 landmark 보정 요청이 적용되지 않음 | " +
                    "agentAccepted=false, fallback=false, risk=" + detection.risk_level +
                    ", correction=(" + delta.x.ToString("F3") + "," + delta.z.ToString("F3") + ")"
                );
            }
            return;
        }

        bool applied = ApplyFireCorrectionImmediately(delta);

        if (applied)
        {
            lastFireExtinguisherCorrectionTime = Time.time;
            ApplyFireLandmarkDeltaToDetectedObstacleMap(delta, "immediate-fallback");
        }

        if (debugFireExtinguisherCorrection)
        {
            Debug.Log(
                "[GO1 Obstacle Receiver] 소화기 landmark 기반 GO1 위치 즉시 보정 | " +
                $"applied={applied}, rawError={error:F3}m, correction=({delta.x:F3},{delta.z:F3}), " +
                $"detected=({detectedWorldPosition.x:F3},{detectedWorldPosition.z:F3}), " +
                $"known=({knownPos.x:F3},{knownPos.z:F3}), name={detection.name}"
            );
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
                    correctionDelta,
                    "fire extinguisher",
                    isNear,
                    out agentAppliedDelta,
                    unityTeleopAndMirror
                );

                if (result)
                {
                    actuallyAppliedDelta = agentAppliedDelta;
                    return true;
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning(
                    "[GO1 Obstacle Receiver] GO1Agent 소화기 보정 요청 중 예외를 무시했습니다: " +
                    ex.Message
                );
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
                unityTeleopAndMirror.ApplyExternalUnityPositionCorrection(
                    delta,
                    "fire-extinguisher landmark immediate-fallback",
                    true
                );
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
            GameObject obj = pair.Value;
            if (obj == null)
                continue;

            obj.transform.position += delta;
            movedObjects.Add(obj);
        }

        if (obstacleRoot != null)
        {
            foreach (Transform child in obstacleRoot.transform)
            {
                if (child == null || child.gameObject == null)
                    continue;

                if (movedObjects.Contains(child.gameObject))
                    continue;

                child.position += delta;
            }
        }

        List<string> keys = new List<string>(obstacleLastPositions.Keys);
        foreach (string key in keys)
        {
            obstacleLastPositions[key] = obstacleLastPositions[key] + delta;
        }

        // 소화기 landmark는 지도 보정 후에도 항상 맵에 배치된 Known Fire Extinguisher 위치에 고정한다.
        if (keepFireLandmarkAtKnownPositionAfterMapShift && knownFireExtinguisher != null)
        {
            foreach (KeyValuePair<string, GameObject> pair in obstacleObjects)
            {
                string key = pair.Key;
                GameObject obj = pair.Value;
                if (obj == null)
                    continue;

                bool keyLooksFire = key.IndexOf("fire_extinguisher", StringComparison.OrdinalIgnoreCase) >= 0;
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
                "[GO1 Obstacle Receiver] 소화기 landmark 기준 장애물 지도 전체 보정 | " +
                "reason=" + reason +
                ", delta=(" + delta.x.ToString("F3") + "," + delta.z.ToString("F3") + ")" +
                ", movedObjects=" + movedObjects.Count
            );
        }
    }

    private void SetupObstacleRoot()
    {
        obstacleRoot = GameObject.Find("GO1_Detected_Obstacles");

        if (obstacleRoot == null)
            obstacleRoot = new GameObject("GO1_Detected_Obstacles");

        // 장애물 지도는 GO1/카메라 자식이 아니라 월드 기준으로 고정되어야 한다.
        // 부모가 GO1이면 로봇 이동 시 과거 장애물도 같이 움직이는 것처럼 보일 수 있다.
        obstacleRoot.transform.SetParent(null, true);

        if (clearOldObstaclesOnStart)
        {
            for (int i = obstacleRoot.transform.childCount - 1; i >= 0; i--)
                Destroy(obstacleRoot.transform.GetChild(i).gameObject);
        }
    }

    private void StartReceiver()
    {
        try
        {
            udpClient = new UdpClient(listenPort);
            isRunning = true;

            receiveThread = new Thread(ReceiveLoop);
            receiveThread.IsBackground = true;
            receiveThread.Start();

            Debug.Log("[GO1 Obstacle Receiver] UDP 수신 시작. Port = " + listenPort);
        }
        catch (Exception e)
        {
            Debug.LogError("[GO1 Obstacle Receiver] UDP 시작 실패: " + e.Message);
        }
    }

    private void ReceiveLoop()
    {
        IPEndPoint remoteEndPoint = new IPEndPoint(IPAddress.Any, listenPort);

        while (isRunning)
        {
            try
            {
                byte[] data = udpClient.Receive(ref remoteEndPoint);
                string json = Encoding.UTF8.GetString(data);
                jsonQueue.Enqueue(json);
            }
            catch (SocketException)
            {
            }
            catch (ObjectDisposedException)
            {
            }
            catch (Exception e)
            {
                Debug.LogError("[GO1 Obstacle Receiver] 수신 오류: " + e.Message);
            }
        }
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

    public bool ShouldMoveVirtualGo1AfterPathSent()
    {
        // GO1Agent에서 경로 전송 이후 가상 GO1 이동 허용 기준으로 이 함수를 호출하면 된다.
        // 현재 정책은 state_change=true일 때만 가상 GO1을 움직이게 하는 것이다.
        return IsRealGo1MovingByStateChange();
    }

    public bool GetLastGo1StateChange()
    {
        return lastGo1StateChange;
    }

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

    private bool TryProcessGo1MotionStateJson(string json)
    {
        if (!receiveGo1MotionStateJson)
            return false;

        if (string.IsNullOrEmpty(json))
            return false;

        // JsonUtility는 없는 bool 필드를 false로 채우기 때문에,
        // state_change 필드가 실제로 들어온 JSON인지 문자열로 먼저 확인한다.
        if (json.IndexOf("\"state_change\"", StringComparison.OrdinalIgnoreCase) < 0)
            return false;

        // AI 서버 detection JSON도 "state_change" 필드를 포함할 수 있다.
        // motion state JSON에만 존재하는 "motion_active" 필드로 두 JSON을 구분한다.
        if (json.IndexOf("\"motion_active\"", StringComparison.OrdinalIgnoreCase) < 0)
            return false;

        Go1MotionStatePacket packet;

        try
        {
            packet = JsonUtility.FromJson<Go1MotionStatePacket>(json);
        }
        catch (Exception e)
        {
            Debug.LogError("[GO1 Motion State] JSON 파싱 실패: " + e.Message + "\n" + json);
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
                "[GO1 Motion State] state_change=" + lastGo1StateChange +
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

    private void ProcessJson(string json)
    {
        // 5009 포트에는 장애물 JSON과 GO1 실제 이동 상태 JSON이 같이 들어올 수 있다.
        // state_change가 있는 JSON이면 장애물로 처리하지 않고 이동 상태만 갱신한다.
        if (TryProcessGo1MotionStateJson(json))
            return;

        Go1ObstaclePacket packet;

        try
        {
            packet = JsonUtility.FromJson<Go1ObstaclePacket>(json);
        }
        catch (Exception e)
        {
            Debug.LogError("[GO1 Obstacle Receiver] JSON 파싱 실패: " + e.Message);
            return;
        }

        if (packet == null || packet.detections == null)
            return;

        // 같은 timestamp면 이미 처리한 패킷 — 중복 생성/갱신 방지
        if (!string.IsNullOrEmpty(packet.timestamp) &&
            packet.timestamp == lastProcessedObstacleTimestamp)
            return;

        if (!string.IsNullOrEmpty(packet.timestamp))
            lastProcessedObstacleTimestamp = packet.timestamp;

        // 폐루프 타임라인: 새 탐지 패킷이 트윈에 도달한 순간을 기록.
        // (obstacle_in_unity/replan_triggered 등 후속 이벤트는 GO1Agent 쪽에서 이미 기록됨)
        if (packet.detections.Length > 0)
        {
            if (!caseStudyLoggerSearched)
            {
                caseStudyLoggerSearched = true;
                caseStudyLogger = FindFirstObjectByType<RealGo1CaseStudyLogger>();
            }

            caseStudyLogger?.LogObstacleDetected(
                Vector3.zero,
                "json_udp:" + (packet.camera_id ?? "unknown"),
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
        {
            CreateOrUpdateObstacle(packet.camera_id, detection, matchedKeysThisPacket);
        }
    }

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
        float bboxWidthPx = Mathf.Abs(x2 - x1);
        float bboxHeightPx = Mathf.Abs(y2 - y1);
        Rect currentBbox = GetBboxRect(detection);

        Vector3 cubeScale = EstimateCubeScale(distanceM, bboxWidthPx, bboxHeightPx);

        Vector3 worldPosition = EstimateObstacleWorldPosition(
            distanceM,
            bboxCenterX,
            bboxCenterY,
            cubeScale
        );

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
            // 같은 JSON 안에서 이미 near 장애물로 흡수된 다른 class/BBOX는 완전히 무시한다.
            // 이렇게 해야 person/chair/trash_bin 등이 같은 위치에 여러 개 생성되지 않는다.
            lastSeenTimes[objectKey] = Time.time;
            if (printObstacleInfo)
            {
                Debug.Log(
                    "[GO1 Obstacle Receiver] 같은 패킷 중복 near JSON 무시 | " +
                    "key=" + objectKey +
                    ", ignoredName=" + detection.name
                );
            }
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
            obstacleObj.transform.position = worldPosition;

            if (isNear && freezeNearObstacleAfterCreate)
                frozenNearObstacleKeys.Add(objectKey);
        }
        else if (freezeExistingNear)
        {
            // 한 번 near로 만들어진 장애물은 월드맵에 고정한다.
            // 이후 가상 Go1/카메라가 움직이면서 같은 물체가 다시 들어와도
            // 새 계산 위치로 갱신하지 않기 때문에 장애물이 Go1을 따라 움직이지 않는다.
            if (printObstacleInfo)
            {
                Debug.Log(
                    "[GO1 Obstacle Receiver] 고정 near 장애물 중복 JSON 흡수 | " +
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

            if (useSmoothing)
            {
                obstacleObj.transform.position = Vector3.Lerp(
                    obstacleObj.transform.position,
                    worldPosition,
                    Time.deltaTime * smoothSpeed
                );
            }
            else
            {
                obstacleObj.transform.position = worldPosition;
            }
        }

        UpdateObstacleColor(obstacleObj, detection.risk_level);
        UpdateLabel(obstacleObj, detection, distanceM);
        UpdateNavMeshObstacle(obstacleObj);

        bool shouldNotifyAgent = isNewObstacle || !freezeExistingNear || !suppressNotifyForFrozenDuplicate;
        if (shouldNotifyAgent)
            NotifyAgentsObstacleUpdated(obstacleObj);

        obstacleNames[objectKey] = detection.name;
        obstacleGroups[objectKey] = detection.group;
        obstacleLastPositions[objectKey] = obstacleObj.transform.position;
        obstacleLastImageBboxes[objectKey] = currentBbox;
        lastSeenTimes[objectKey] = Time.time;

        if (drawDebugRay)
            Debug.DrawLine(cameraAnchor.position, worldPosition, Color.magenta, 0.2f);

        if (printObstacleInfo)
        {
            Debug.Log(
                "[장애물 생성/갱신] " +
                "key=" + objectKey +
                ", name=" + detection.name +
                ", group=" + detection.group +
                ", risk=" + detection.risk_level +
                ", rel_depth=" + detection.rel_depth.ToString("F3") +
                ", distance_cm=" + detection.distance_cm.ToString("F2") +
                ", distance_cm_raw=" + detection.distance_cm_raw.ToString("F2") +
                ", distanceM=" + distanceM.ToString("F2") +
                ", isNew=" + isNewObstacle +
                ", isFireExtinguisher=" + isFireExtinguisher +
                ", frozenNear=" + freezeExistingNear +
                ", pos=" + obstacleObj.transform.position +
                ", targetPos=" + worldPosition +
                ", scale=" + obstacleObj.transform.localScale
            );
        }
    }

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
            if (areaA <= 0f)
                continue;

            for (int j = 0; j < detections.Count; j++)
            {
                if (i == j)
                    continue;

                Detection b = detections[j];
                if (b == null || !IsNearRisk(b.risk_level) || IsFireExtinguisherDetection(b))
                    continue;

                Rect rectB = GetBboxRect(b);
                float areaB = RectArea(rectB);
                if (areaB <= 0f)
                    continue;

                // 큰 BBOX 안에 작은 BBOX가 들어간 경우 작은 쪽을 무시한다.
                if (ignoreNestedNearBboxes && areaA <= areaB)
                {
                    float containment = RectIntersectionArea(rectA, rectB) / areaA;
                    if (containment >= nestedBboxContainmentThreshold)
                    {
                        ignored[i] = true;
                        if (printObstacleInfo)
                        {
                            Debug.Log(
                                "[GO1 Obstacle Receiver] 내부 near BBOX 무시 | " +
                                "ignored=" + a.name +
                                ", kept=" + b.name +
                                ", containment=" + containment.ToString("F2")
                            );
                        }
                        break;
                    }
                }

                // 서로 거의 같은 위치/크기의 BBOX가 여러 class로 잡히면 작은 쪽을 무시한다.
                if (ignoreOverlappingNearBboxesInSamePacket && areaA <= areaB)
                {
                    float iou = RectIoU(rectA, rectB);
                    if (iou >= samePacketBboxIouThreshold)
                    {
                        ignored[i] = true;
                        if (printObstacleInfo)
                        {
                            Debug.Log(
                                "[GO1 Obstacle Receiver] 겹치는 near BBOX 무시 | " +
                                "ignored=" + a.name +
                                ", kept=" + b.name +
                                ", iou=" + iou.ToString("F2")
                            );
                        }
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

    private bool IsNearRisk(string riskLevel)
    {
        return string.Equals(riskLevel, "near", StringComparison.OrdinalIgnoreCase);
    }

    private Rect GetBboxRect(Detection detection)
    {
        if (detection == null || detection.bbox_xyxy == null || detection.bbox_xyxy.Length < 4)
            return new Rect(0f, 0f, 0f, 0f);

        float x1 = detection.bbox_xyxy[0];
        float y1 = detection.bbox_xyxy[1];
        float x2 = detection.bbox_xyxy[2];
        float y2 = detection.bbox_xyxy[3];

        float minX = Mathf.Min(x1, x2);
        float minY = Mathf.Min(y1, y2);
        float maxX = Mathf.Max(x1, x2);
        float maxY = Mathf.Max(y1, y2);

        return Rect.MinMaxRect(minX, minY, maxX, maxY);
    }

    private float RectArea(Rect r)
    {
        return Mathf.Max(0f, r.width) * Mathf.Max(0f, r.height);
    }

    private float RectIntersectionArea(Rect a, Rect b)
    {
        float xMin = Mathf.Max(a.xMin, b.xMin);
        float yMin = Mathf.Max(a.yMin, b.yMin);
        float xMax = Mathf.Min(a.xMax, b.xMax);
        float yMax = Mathf.Min(a.yMax, b.yMax);

        float w = Mathf.Max(0f, xMax - xMin);
        float h = Mathf.Max(0f, yMax - yMin);
        return w * h;
    }

    private float RectIoU(Rect a, Rect b)
    {
        float intersection = RectIntersectionArea(a, b);
        float union = RectArea(a) + RectArea(b) - intersection;
        if (union <= 0f)
            return 0f;
        return intersection / union;
    }

    private Vector3 EstimateObstacleWorldPosition(
        float distanceM,
        float bboxCenterX,
        float bboxCenterY,
        Vector3 cubeScale)
    {
        if (useFisheyeProjection && go1ViewCamera != null)
        {
            return EstimateWorldPositionByFisheyeProjection(
                distanceM,
                bboxCenterX,
                bboxCenterY,
                cubeScale
            );
        }

        if (useUnityCameraRayProjection && go1ViewCamera != null)
        {
            return EstimateWorldPositionByUnityCameraRay(
                distanceM,
                bboxCenterX,
                bboxCenterY,
                cubeScale
            );
        }

        Vector3 localPosition = EstimateCameraLocalPosition(distanceM, bboxCenterX, bboxCenterY);
        localPosition = ApplyCameraLocalTuningToLocalPosition(localPosition);
        return ConvertCameraLocalToWorld(localPosition, cubeScale);
    }

    private Vector3 EstimateWorldPositionByFisheyeProjection(
        float distanceM,
        float bboxCenterX,
        float bboxCenterY,
        Vector3 cubeScale)
    {
        Vector3 cameraForward;
        Vector3 cameraRight;
        BuildCameraBasis(out cameraForward, out cameraRight);

        float u = bboxCenterX / Mathf.Max(1f, imageWidth);
        float v = bboxCenterY / Mathf.Max(1f, imageHeight);

        float dx = u - fisheyeCenterX;
        float dy = v - fisheyeCenterY;

        if (mirrorFisheyeX)
            dx = -dx;

        if (mirrorFisheyeY)
            dy = -dy;

        if (invertLocalX)
            dx = -dx;

        float shortAspect = Mathf.Min(imageWidth, imageHeight);
        float radiusPx = shortAspect * Mathf.Max(0.0001f, fisheyeRadiusNorm);

        float dxPx = dx * imageWidth;
        float dyPx = dy * imageHeight;

        float rNorm = Mathf.Sqrt(dxPx * dxPx + dyPx * dyPx) / radiusPx;
        rNorm = Mathf.Clamp01(rNorm);

        float theta = Mathf.Pow(rNorm, Mathf.Max(0.01f, fisheyePower)) *
                      (fisheyeFovDeg * 0.5f * Mathf.Deg2Rad);

        float phi = Mathf.Atan2(dxPx, -dyPx);

        float localRight = Mathf.Sin(theta) * Mathf.Sin(phi);
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

        return BuildWorldPositionFromDirection(
            distanceM,
            forwardDir,
            cameraForward,
            cameraRight,
            cubeScale
        );
    }

    private Vector3 EstimateWorldPositionByUnityCameraRay(
        float distanceM,
        float bboxCenterX,
        float bboxCenterY,
        Vector3 cubeScale)
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

        Vector3 cameraForward;
        Vector3 cameraRight;
        BuildCameraBasis(out cameraForward, out cameraRight);

        return BuildWorldPositionFromDirection(
            distanceM,
            forwardDir,
            cameraForward,
            cameraRight,
            cubeScale
        );
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

    private Vector3 BuildWorldPositionFromDirection(
        float distanceM,
        Vector3 forwardDir,
        Vector3 cameraForward,
        Vector3 cameraRight,
        Vector3 cubeScale)
    {
        float rayDistance = distanceM;

        if (useSideRayDistanceCorrection)
        {
            float forwardDot = Vector3.Dot(forwardDir, cameraForward);
            forwardDot = Mathf.Clamp(forwardDot, minSideForwardDot, 1.0f);

            float correctedRayDistance = distanceM / forwardDot;

            rayDistance = Mathf.Lerp(
                distanceM,
                correctedRayDistance,
                sideRayDistanceCorrectionStrength
            );
        }

        Vector3 fromCamera = forwardDir * rayDistance;

        float localForward = Vector3.Dot(fromCamera, cameraForward);
        float localRight = Vector3.Dot(fromCamera, cameraRight);

        if (useCameraLocalPositionTuning)
        {
            localForward = localForward * cameraLocalZScale + cameraLocalZOffsetM;
            localRight = localRight * cameraLocalXScale + cameraLocalXOffsetM;
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

        float halfViewWidthAtDistance =
            Mathf.Tan(horizontalFovDeg * 0.5f * Mathf.Deg2Rad) * distanceM;

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

    private string FindMatchingObstacleKey(Detection detection, Vector3 newWorldPosition, HashSet<string> matchedKeysThisPacket)
    {
        if (!mergeSameNameByPosition && !mergeDifferentNameByPosition && !ignoreJsonOverlappingExistingNearObstacle)
            return null;

        string bestKey = null;
        float bestDistance = float.MaxValue;

        string newName = string.IsNullOrEmpty(detection.name) ? "" : detection.name;
        string newGroup = string.IsNullOrEmpty(detection.group) ? "" : detection.group;
        bool newIsNear = IsNearRisk(detection.risk_level);
        Rect newBbox = GetBboxRect(detection);

        foreach (KeyValuePair<string, GameObject> pair in obstacleObjects)
        {
            string key = pair.Key;
            bool alreadyMatchedInThisPacket = matchedKeysThisPacket != null && matchedKeysThisPacket.Contains(key);

            string oldName = obstacleNames.ContainsKey(key) ? obstacleNames[key] : "";
            string oldGroup = obstacleGroups.ContainsKey(key) ? obstacleGroups[key] : "";

            bool sameName = string.Equals(oldName, newName, StringComparison.OrdinalIgnoreCase);
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
            string mergeReason = "";

            if (mergeSameNameByPosition && sameName && sameGroup)
            {
                canMerge = true;
                allowedDistance = mergeDistanceM;
                mergeReason = "same-name";
            }
            else if (mergeDifferentNameByPosition)
            {
                if (!alreadyMatchedInThisPacket || allowSamePacketDifferentNameMerge)
                {
                    canMerge = true;
                    allowedDistance = differentNameMergeDistanceM;
                    mergeReason = "near-position-different-name";
                }
            }

            // 한 번 near로 만들어진 장애물 주변에 들어오는 다른 near JSON은 이름/group과 무관하게 흡수한다.
            if (ignoreJsonOverlappingExistingNearObstacle && newIsNear)
            {
                bool isFrozenNear = frozenNearObstacleKeys.Contains(key);

                if (!rayMergeOnlyFrozenNearObstacle || isFrozenNear)
                {
                    float nearMergeDistance = Mathf.Max(allowedDistance, existingNearWorldMergeDistanceM);
                    allowedDistance = nearMergeDistance;
                    canMerge = true;
                    mergeReason = "existing-near-fixed-map";

                    if (obstacleLastImageBboxes.ContainsKey(key))
                    {
                        Rect oldBbox = obstacleLastImageBboxes[key];
                        float iou = RectIoU(oldBbox, newBbox);
                        float contained = 0f;
                        float newArea = RectArea(newBbox);
                        if (newArea > 0f)
                            contained = RectIntersectionArea(newBbox, oldBbox) / newArea;

                        if (iou >= samePacketBboxIouThreshold || contained >= nestedBboxContainmentThreshold)
                        {
                            distance = Mathf.Min(distance, 0f);
                        }
                    }

                    // Go1이 움직이면 depth/world position 오차 때문에 같은 물체가 0.5m 이상 떨어진 곳에 새로 찍힐 수 있다.
                    // 이때 새 추정 위치까지의 카메라 ray가 기존 고정 near 장애물을 지나가면 같은 물체로 보고 흡수한다.
                    if (mergeExistingNearByCameraRay && cameraAnchor != null)
                    {
                        float rayPerp;
                        float depthDiff;
                        if (IsExistingObstacleOnDetectionRay(oldPosition, newWorldPosition, out rayPerp, out depthDiff))
                        {
                            distance = Mathf.Min(distance, rayPerp);
                            allowedDistance = Mathf.Max(allowedDistance, existingNearRayMergeRadiusM);
                            mergeReason = "existing-near-camera-ray";
                        }
                    }
                }
            }

            if (!canMerge)
                continue;

            if (alreadyMatchedInThisPacket && mergeReason == "same-name")
                continue;

            if (distance <= allowedDistance && distance < bestDistance)
            {
                bestDistance = distance;
                bestKey = key;
            }
        }

        if (!string.IsNullOrEmpty(bestKey) && printObstacleInfo)
        {
            string oldName = obstacleNames.ContainsKey(bestKey) ? obstacleNames[bestKey] : "unknown";
            Debug.Log(
                "[GO1 Obstacle Receiver] 기존 장애물 병합 | " +
                "key=" + bestKey +
                ", oldName=" + oldName +
                ", newName=" + detection.name +
                ", dist=" + bestDistance.ToString("F2") + "m" +
                ", sameNameMergeDist=" + mergeDistanceM.ToString("F2") +
                ", diffNameMergeDist=" + differentNameMergeDistanceM.ToString("F2") +
                ", existingNearMergeDist=" + existingNearWorldMergeDistanceM.ToString("F2")
            );
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

        Vector3 dir = ray / newDepth;

        Vector3 toOld = existingObstaclePos - cam;
        toOld.y = 0f;

        float oldProjection = Vector3.Dot(toOld, dir);
        if (oldProjection < 0f)
            return false;

        Vector3 closest = cam + dir * oldProjection;
        perpendicularDistance = HorizontalDistance(existingObstaclePos, closest);
        depthDifference = Mathf.Abs(oldProjection - newDepth);

        bool closeToRay = perpendicularDistance <= existingNearRayMergeRadiusM;
        bool similarDepth = depthDifference <= existingNearRayDepthToleranceM;

        if (closeToRay && similarDepth && printObstacleInfo)
        {
            Debug.Log(
                "[GO1 Obstacle Receiver] 카메라 ray 기반 기존 near 장애물 흡수 후보 | " +
                "rayPerp=" + perpendicularDistance.ToString("F2") + "m" +
                ", depthDiff=" + depthDifference.ToString("F2") + "m" +
                ", oldProjection=" + oldProjection.ToString("F2") + "m" +
                ", newDepth=" + newDepth.ToString("F2") + "m"
            );
        }

        return closeToRay && similarDepth;
    }

    private string MakeNewObstacleKey(string cameraId, Detection detection)
    {
        string safeName = string.IsNullOrEmpty(detection.name) ? "unknown" : detection.name;
        string key = cameraId + "_" + safeName + "_track_" + nextTrackId;
        nextTrackId++;
        return key;
    }

    private float HorizontalDistance(Vector3 a, Vector3 b)
    {
        float dx = a.x - b.x;
        float dz = a.z - b.z;
        return Mathf.Sqrt(dx * dx + dz * dz);
    }

    private GameObject CreateObstacleObject(Detection detection)
    {
        GameObject obj;

        if (obstaclePrefab != null)
            obj = Instantiate(obstaclePrefab);
        else
            obj = GameObject.CreatePrimitive(PrimitiveType.Cube);

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
                    Debug.LogError(
                        "[GO1 Obstacle Receiver] Unity Layer '" + obstacleLayerName + "'가 없습니다. " +
                        "Project Settings > Tags and Layers에서 Layer를 먼저 추가하세요."
                    );
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
        if (obj == null)
            return;

        if (!TrySetObstacleTag(obj, tagName))
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
                Debug.LogError(
                    "[GO1 Obstacle Receiver] Unity Tag '" + tagName + "'가 없습니다. " +
                    "Project Settings > Tags and Layers에서 Tag를 먼저 추가하세요."
                );
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

    private float CalibrateDetectionDistanceToMeter(Detection detection)
    {
        if (detection == null)
            return minDistanceM;

        // 1순위: AI 서버가 직접 보내는 cm 거리값 사용
        // 예: distance_cm=51.8 -> 0.518m
        if (preferJsonDistanceCm && IsValidPositiveDistance(detection.distance_cm))
            return detection.distance_cm / 100.0f;

        // 2순위: raw cm 값 사용
        if (preferJsonDistanceCm && IsValidPositiveDistance(detection.distance_cm_raw))
            return detection.distance_cm_raw / 100.0f;

        // 3순위: 기존 rel_depth fallback
        return CalibrateDepthToMeter(detection.rel_depth);
    }

    private bool IsValidPositiveDistance(float value)
    {
        if (float.IsNaN(value) || float.IsInfinity(value))
            return false;

        return value > 0.001f;
    }

    private float CalibrateDepthToMeter(float relDepth)
    {
        // 2차 depth 보정식은 제거한다.
        // 현재 JSON rel_depth 값이 cm 단위에 가까운 값으로 들어오면
        // relDepthIsCentimeter=true 상태에서 cm -> m 단위 변환만 수행한다.
        if (float.IsNaN(relDepth) || float.IsInfinity(relDepth))
            return 0f;

        float value = Mathf.Max(0.0f, relDepth);

        if (relDepthIsCentimeter)
            return value / 100.0f;

        return value;
    }

    private Vector3 EstimateCubeScale(float distanceM, float bboxWidthPx, float bboxHeightPx)
    {
        float viewWidthAtDistance =
            2f * Mathf.Tan(horizontalFovDeg * 0.5f * Mathf.Deg2Rad) * distanceM;

        float viewHeightAtDistance =
            2f * Mathf.Tan(verticalFovDeg * 0.5f * Mathf.Deg2Rad) * distanceM;

        float estimatedWidth = viewWidthAtDistance * (bboxWidthPx / imageWidth);
        float estimatedHeight = viewHeightAtDistance * (bboxHeightPx / imageHeight);
        float estimatedDepth = Mathf.Max(estimatedWidth * depthRatio, minCubeSize);

        // BBOX로 계산한 장애물 크기를 전체적으로 키워서
        // 실제 경로/재탐색에서 더 안전한 여유 공간을 확보한다.
        float sizeMultiplier = Mathf.Max(0.01f, bboxSizeMultiplier);
        estimatedWidth *= sizeMultiplier;
        estimatedHeight *= sizeMultiplier;
        estimatedDepth *= sizeMultiplier;

        estimatedWidth = Mathf.Clamp(estimatedWidth, minCubeSize, maxCubeSize);
        estimatedHeight = Mathf.Clamp(estimatedHeight, minCubeSize, maxCubeSize);
        estimatedDepth = Mathf.Clamp(estimatedDepth, minCubeSize, maxCubeSize);

        return new Vector3(estimatedWidth, estimatedHeight, estimatedDepth);
    }

    private Vector3 ConvertCameraLocalToWorld(Vector3 localPosition, Vector3 cubeScale)
    {
        Quaternion yawCorrection = Quaternion.Euler(0f, cameraYawOffsetDeg, 0f);

        Vector3 correctedRight = yawCorrection * cameraAnchor.right;
        Vector3 correctedForward = yawCorrection * cameraAnchor.forward;

        correctedRight.y = 0f;
        correctedForward.y = 0f;

        if (correctedRight.sqrMagnitude < 0.0001f)
            correctedRight = transform.right;

        if (correctedForward.sqrMagnitude < 0.0001f)
            correctedForward = transform.forward;

        correctedRight.Normalize();
        correctedForward.Normalize();

        Vector3 worldPosition =
            cameraAnchor.position
            + correctedRight * localPosition.x
            + correctedForward * localPosition.z;

        if (placeOnGround)
            worldPosition.y = yOffset + cubeScale.y * 0.5f;
        else
            worldPosition.y = cameraAnchor.position.y + yOffset;

        return worldPosition;
    }

    private void UpdateObstacleColor(GameObject obj, string riskLevel)
    {
        Renderer renderer = obj.GetComponent<Renderer>();

        if (renderer == null)
            renderer = obj.GetComponentInChildren<Renderer>();

        if (renderer == null)
            return;

        string risk = string.IsNullOrEmpty(riskLevel) ? "" : riskLevel.Trim().ToLower();

        Color color;
        if (risk == "near")
            color = Color.red;
        else if (risk == "mid" || risk == "middle")
            color = Color.yellow;
        else if (risk == "far")
            color = Color.green;
        else
            color = Color.white;

        // MaterialPropertyBlock으로 색 적용 — renderer.material 접근 시 매번
        // Material clone이 생성되는 문제를 방지한다.
        MaterialPropertyBlock mpb = new MaterialPropertyBlock();
        renderer.GetPropertyBlock(mpb);
        mpb.SetColor("_Color", color);
        renderer.SetPropertyBlock(mpb);
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
            textMesh.fontSize = 32;
            textMesh.characterSize = 0.05f;
            textMesh.anchor = TextAnchor.MiddleCenter;
            textMesh.alignment = TextAlignment.Center;
        }
        else
        {
            textMesh = labelTransform.GetComponent<TextMesh>();

            if (textMesh == null)
                textMesh = labelTransform.gameObject.AddComponent<TextMesh>();
        }

        textMesh.text =
            detection.name +
            "\n" + detection.risk_level +
            "\n" + distanceM.ToString("F2") + "m";
    }

    private void UpdateNavMeshObstacle(GameObject obj)
    {
        NavMeshObstacle navObstacle = obj.GetComponent<NavMeshObstacle>();

        if (navObstacle == null && autoAddNavMeshObstacle)
            navObstacle = obj.AddComponent<NavMeshObstacle>();

        if (navObstacle == null)
            return;

        navObstacle.shape = NavMeshObstacleShape.Box;
        navObstacle.size = Vector3.one;
        navObstacle.center = Vector3.zero;
        navObstacle.carving = navMeshObstacleCarving;
    }

    private void RemoveStaleObstacles()
    {
        // 경로 재탐색/누적 지도 생성을 위해 한 번 찾은 장애물을 계속 남겨둔다.
        // 수동 삭제가 필요하면 ClearAllDetectedObstacles()를 호출하면 된다.
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

        float dt = Mathf.Max(Time.deltaTime, 0.0001f);
        float yawDelta = Mathf.DeltaAngle(lastCameraYawDeg, currentYawDeg);

        currentCameraYawSpeedDegPerSec = Mathf.Abs(yawDelta) / dt;
        lastCameraYawDeg = currentYawDeg;

        if (currentCameraYawSpeedDegPerSec >= rotationYawSpeedThresholdDegPerSec)
        {
            lastCameraRotationDetectedTime = Time.time;
        }
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
            if (agent == null)
                continue;

            if (agent.IsPostReplanJsonBlocked())
                return true;
        }

        return false;
    }

    private float GetPostReplanLockRemaining()
    {
        RefreshAgentCacheIfNeeded();

        float maxRemaining = 0f;

        if (cachedAgents == null || cachedAgents.Length == 0)
            return 0f;

        foreach (GO1Agent agent in cachedAgents)
        {
            if (agent == null)
                continue;

            maxRemaining = Mathf.Max(maxRemaining, agent.GetPostReplanJsonBlockRemaining());
        }

        return maxRemaining;
    }

    private bool ShouldIgnoreJsonBecauseCameraRotating()
    {
        if (!ignoreJsonWhileCameraRotating)
            return false;

        // 중요:
        // 가상 GO1이 경로를 찾는 중에는 위쪽 ShouldIgnoreJsonBecauseVirtualPathPlanning()에서 이미 JSON을 막는다.
        // 그 이후 실제 GO1과 가상 GO1이 같이 움직이는 구간에서는 장애물을 계속 생성해야
        // 경로 차단 감지 -> 정지 -> 재탐색이 가능하다.
        if (allowJsonWhileRealGo1PathActive && IsAnyAgentRealPathFollowingPhase())
            return false;

        if (!hasLastCameraYaw)
            return false;

        bool currentlyRotating =
            currentCameraYawSpeedDegPerSec >= rotationYawSpeedThresholdDegPerSec;

        bool settlingAfterRotation =
            Time.time - lastCameraRotationDetectedTime < rotationSettleTime;

        return currentlyRotating || settlingAfterRotation;
    }

    private bool IsAnyAgentRealPathFollowingPhase()
    {
        RefreshAgentCacheIfNeeded();

        if (cachedAgents == null || cachedAgents.Length == 0)
            return false;

        foreach (GO1Agent agent in cachedAgents)
        {
            if (agent == null)
                continue;

            // IsMoving()은 가상 경로 탐색 + 실제 경로 추종을 모두 포함한다.
            // 그런데 이 함수가 호출되는 시점에는 virtual planning ignore가 먼저 처리되므로,
            // IsMoving()==true && IsVirtualPathPlanning()==false이면 실제 GO1 경로 추종 구간으로 본다.
            if (agent.IsMoving() && !agent.IsVirtualPathPlanning())
                return true;
        }

        return false;
    }

    private void RefreshAgentCacheIfNeeded()
    {
        if (cachedAgents == null || Time.time - lastAgentRefreshTime > agentCacheRefreshInterval)
        {
            cachedAgents = FindObjectsByType<GO1Agent>(FindObjectsSortMode.None);
            lastAgentRefreshTime = Time.time;
        }
    }

    private bool ShouldIgnoreJsonBecauseVirtualPathPlanning()
    {
        if (!ignoreJsonWhileVirtualPathPlanning)
            return false;

        RefreshAgentCacheIfNeeded();

        if (cachedAgents == null || cachedAgents.Length == 0)
            return false;

        foreach (GO1Agent agent in cachedAgents)
        {
            if (agent == null)
                continue;

            // GO1Agent.IsVirtualPathPlanning():
            // - true  : M키 이후 가상 GO1이 경로를 찾는 중
            // - false : 실제 GO1이 경로를 따라 이동 중이거나, 정지 상태
            if (agent.IsVirtualPathPlanning())
                return true;
        }

        return false;
    }

    private void NotifyAgentsObstacleUpdated(GameObject obstacleObj)
    {
        if (!notifyAgentsOnObstacleUpdate)
            return;

        if (obstacleObj == null)
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
                Debug.LogWarning(
                    "[GO1 Obstacle Receiver] 장애물 갱신 알림 중 GO1Agent 예외를 무시했습니다: " +
                    ex.Message
                );
            }
        }
    }

    private void ClearQueuedJson()
    {
        while (jsonQueue.TryDequeue(out _))
        {
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

    private void OnApplicationQuit()
    {
        StopReceiver();
    }

    private void OnDestroy()
    {
        StopReceiver();
    }

    private void OnDisable()
    {
        StopReceiver();
    }

    private void StopReceiver()
    {
        isRunning = false;

        if (udpClient != null)
        {
            udpClient.Close();
            udpClient = null;
        }

        if (receiveThread != null && receiveThread.IsAlive)
        {
            receiveThread.Join(100);
            receiveThread = null;
        }

        Debug.Log("[GO1 Obstacle Receiver] UDP 수신 종료");
    }
}
