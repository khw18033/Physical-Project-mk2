using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

/// <summary>
/// 360° 고정 카메라(서버)가 UDP로 보내는 사각지대 장애물 JSON을 수신하여
/// Anchor360 기준으로 큐브를 스폰한다. 기존 Go1ObstacleJsonReceiver(포트 5009)와 완전히 별개.
///
/// 사용법:
///  1) 빈 GameObject "Anchor360"을 만들고 실제 360 카메라의 가로 위치에 놓는다.
///     - +Z(파란 화살표)를 맵의 GO1 주행 방향에 맞춘다.  높이(y)는 상관없음(바닥으로 강제됨).
///  2) 이 컴포넌트를 Anchor360에 붙인다. (anchorTransform 비우면 자기 자신 사용)
///  3) listenPort=5010, obstaclePrefab(선택) 지정.
///  4) 큐브가 실제 장애물과 어긋나면 Inspector에서 yawOffsetDeg / invertX / distanceScale 조정.
/// </summary>
public class Anchor360ObstacleReceiver : MonoBehaviour
{   
    [Header("File Load (정적 환경용 / 슬라이스 시험용)")]
    [Tooltip("true면 UDP 대신 아래 JSON 파일을 읽어 큐브 생성.")]
    public bool loadFromFile = false;
    [Tooltip("Project에서 .json 파일을 여기로 끌어다 놓으면 됨.")]
    public TextAsset jsonFile;

    [Header("Network")]
    public int listenPort = 5010;                 // 기존 5009와 다른 포트

    [Header("Anchor")]
    [Tooltip("360 카메라 기준 오브젝트. 비우면 이 컴포넌트가 붙은 오브젝트를 사용.")]
    public Transform anchorTransform;

    [Header("Calibration (실측 보정용 손잡이)")]
    [Tooltip("큐브 전체가 회전돼 보이면 조정 (도).")]
    public float yawOffsetDeg = 0f;
    [Tooltip("좌우가 뒤집혀 보이면 체크.")]
    public bool invertX = false;
    [Tooltip("거리가 멀거나 가깝게 보이면 조정 (가로거리 배율).")]
    public float distanceScale = 1.0f;

    [Header("Calibration File (있으면 위 값과 앵커 위치를 덮어씀)")]
    [Tooltip("StreamingAssets 아래 보정 파일 이름. 파일이 있으면 Play 시작 때 읽고, 실행 중 파일이 바뀌면 바로 다시 읽는다. 비우면 사용 안 함.")]
    public string calibrationFileName = "anchor360_calib.json";

    [Header("Floor")]
    [Tooltip("장애물은 바닥에 있으므로 큐브 높이를 이 y로 강제한다(맵 바닥 높이). 보통 0.")]
    public float floorWorldY = 0f;

    [Header("Cube")]
    public GameObject obstaclePrefab;             // 비우면 기본 Cube 생성
    public float minCubeSize = 0.15f;
    public float maxCubeSize = 3.0f;
    public float defaultCubeSize = 0.4f;          // size 없을 때
    [Tooltip("bbox 유래 크기가 커서 여유를 주고 싶으면 배율.")]
    public float sizeMultiplier = 1.0f;

    [Header("Tag / Layer (기존과 동일하게 NavMesh/ML-Agent가 인식하도록)")]
    public bool assignObstacleTagAndLayer = true;
    public string obstacleTagName = "Obstacle";
    public string obstacleLayerName = "Obstacle";

    [Header("기존 장애물 제외 (씬에 원래 놓여 있던 물체 자리의 검출은 큐브를 만들지 않음)")]
    [Tooltip("켜면 Play 시작 시점에 씬에 있던 물체들의 바닥 영역을 기억해 두고, 그 안에 떨어진 검출은 건너뛴다.")]
    public bool skipExistingObstacles = true;
    [Tooltip("기존 물체 바닥 영역을 사방으로 이만큼(m) 넓혀서 비교. 검출 위치 오차(10~25cm)를 흡수한다.")]
    public float existingMatchMargin = 0.25f;
    [Tooltip("이름에 이 글자가 들어간 물체는 '기존 장애물'로 치지 않는다(대소문자 무시). 벽·문·바닥은 영역이 넓어 근처 검출을 다 지워버리므로 뺀다.")]
    public string[] existingIgnoreNameContains = { "wall", "door", "plane", "floor", "ceiling", "label" };
    [Tooltip("이 레이어의 물체는 '기존 장애물'로 치지 않는다(시야 표시·UI 등).")]
    public string[] existingIgnoreLayers = { "FovViz", "UI", "VideoUI", "TransparentFX", "Water", "Ignore Raycast" };
    [Tooltip("건너뛴 검출과 겹친 기존 물체 이름을 Console에 찍는다.")]
    public bool logSkippedExisting = false;

    [Header("위치를 믿을 수 없는 검출 제외")]
    [Tooltip("방 바닥 범위를 벗어난 검출은 큐브를 만들지 않는다.")]
    public bool dropOutsideRoom = true;
    [Tooltip("방 바닥 물체 이름. 이 물체의 XZ 범위를 방 경계로 쓴다.")]
    public string roomFloorObjectName = "Plane";
    [Tooltip("방 경계를 안쪽으로 이만큼(m) 줄인다(벽 두께).")]
    public float roomInset = 0.15f;
    [Tooltip("카메라→바닥 지점 시선이 기존 가구에 막히면 제외. 책상 위 물건, 가구에 아랫부분이 가린 물체는 바닥 투영 위치가 실제보다 멀리 틀리게 나오기 때문.")]
    public bool dropSightBlocked = true;
    [Tooltip("실제 카메라 렌즈 높이(m). 0이면 앵커 높이 × Distance Scale 을 쓴다.")]
    public float cameraHeightOverride = 0f;
    [Tooltip("이 높이(m)보다 낮은 기존 물체는 시선을 막지 않는 것으로 본다.")]
    public float sightMinBlockerHeight = 0.3f;
    [Tooltip("도착점 앞 이 거리(m) 구간은 막힘 검사에서 뺀다(가구 앞에 붙은 물체 보호).")]
    public float sightEndClearance = 0.3f;

    [Header("NavMesh (큐브 자리를 주행 가능 영역에서 파냄)")]
    [Tooltip("켜면 큐브마다 NavMeshObstacle(Carve)을 달아 NavMesh 경로가 장애물을 돌아가게 한다.")]
    public bool addNavMeshObstacle = true;
    [Tooltip("파낼 영역을 큐브보다 사방으로 이만큼(m) 넓힌다. 위치 오차만큼 여유를 주고 싶을 때.")]
    public float navMeshPadding = 0f;
    [Tooltip("큐브가 이 시간(초) 동안 가만히 있어야 NavMesh 를 파낸다. 움직이는 사람은 파내지 않는다.")]
    public float navCarveDelaySec = 0.3f;
    [Tooltip("새 검출이 기존 큐브에서 이 거리(m) 안이면 같은 물체로 보고 큐브를 이어 쓴다.")]
    public float trackMatchRadius = 0.5f;
    [Tooltip("위치·크기 변화가 이 값(m)보다 작으면 큐브를 움직이지 않는다(NavMesh 재계산 방지).")]
    public float trackUpdateEps = 0.05f;
    [Tooltip("검출이 사라진 큐브를 이 시간(초) 뒤에 지운다. 잠깐 깜빡이는 검출 때문에 NavMesh 가 흔들리지 않게.")]
    public float missingGraceSec = 2.0f;

    [Header("Label (큐브 위에 이름·거리 표시)")]
    public bool showLabels = true;
    [Tooltip("거리 기준. 비우면 360 카메라(앵커)로부터의 바닥 거리. 로봇을 넣으면 로봇으로부터의 거리.")]
    public Transform labelDistanceFrom;
    public float labelCharacterSize = 0.035f;
    public int labelFontSize = 32;
    [Tooltip("라벨 최소 높이(m). 낮은 물체의 글자가 가구에 가리지 않게.")]
    public float labelMinHeight = 0.85f;
    public Color labelColor = Color.white;

    [Header("색 구분")]
    [Tooltip("360도 카메라가 찾은 장애물 큐브의 색. Go1 이 찾은 것은 Go1FrontGuardReceiver 의 색(하늘색)을 쓴다.")]
    public Color cubeColor = new Color(1f, 0.55f, 0.1f);

    [Header("사람 표시")]
    [Tooltip("탐지 이름이 사람(person 등)이면 상자 대신 사람 모형을 세운다. 프리팹은 Resources/Person360.")]
    public bool showPersonModel = true;
    [Tooltip("사람 머리 위 글자 높이(m).")]
    public float personLabelHeight = 1.95f;

    [Header("탐지 범위")]
    [Tooltip("카메라에서 이 거리(m) 안의 검출만 배치한다. 멀수록 위치·크기가 부정확하다. 0 이하면 제한 없음. 보정 파일의 range360M 이 우선.")]
    public float detectRangeM = 4.0f;
    [Tooltip("가상 로봇에서 이 거리(m) 안의 검출은 로봇 자신으로 보고 버린다(360° 가 로봇을 가방 등으로 잡는다). 0 이면 끔.")]
    public float selfExcludeM = 0.5f;
    private UnityTeleopAndMirror[] robotsCache; private float nextRobotScan;

    [Header("새 장애물만 배치 (보정 파일이 우선. 기본값은 모두 꺼짐 = 예전 동작)")]
    [Tooltip("이 신뢰도 미만의 검출은 배치하지 않는다. 0이면 끔. 보정 파일 minConf360.")]
    public float minPlaceConfidence = 0f;
    [Tooltip("큐브 가로/세로를 이 값(m)으로 자른다. 0이면 maxCubeSize 그대로. 보정 파일 maxFootprint360.")]
    public float maxFootprintM = 0f;
    [Tooltip("로봇이 다닐 수 있는 바닥(NavMesh)에서 이 거리(m) 안의 검출만 배치한다. 0 이하면 끔. 보정 파일 nearFloor360.")]
    public float nearFloorM = 0f;
    [Tooltip("켜면 '원래 있던 물건' 목록(배경)에 있는 자리의 검출은 배치하지 않는다. 보정 파일 useBaseline360.")]
    public bool useBaseline = false;
    [Tooltip("배경 목록의 자리에서 이 거리(m) 안이면 원래 있던 물건으로 본다.")]
    public float baselineMatchM = 0.4f;
    [Tooltip("배경 목록 파일(StreamingAssets). 배경 기록을 끝내면 여기에 저장하고, 시작할 때 읽는다.")]
    public string baselineFileName = "anchor360_baseline.json";
    [Tooltip("Play 중 이 키를 누르면 그때부터 baselineCaptureSec 동안 보이는 것을 배경으로 기록한다.")]
    public KeyCode baselineCaptureKey = KeyCode.F7;
    public float baselineCaptureSec = 5f;

    [Serializable] public class BaselineItem { public string label; public float x, z; }
    [Serializable] public class BaselineFile { public string savedAt; public List<BaselineItem> items = new List<BaselineItem>(); }
    private BaselineFile baseline = new BaselineFile();
    private float baselineCaptureUntil = -1f;
    public int BaselineCount => baseline.items.Count;
    // 마지막 패킷 처리 결과 (확인용)
    public int statDetections, statPlaced, statLowConf, statBaseline, statOffFloor, statElevated;

    // 장애물을 놓기 전(시작 시점)의 주행 가능 바닥. 큐브가 NavMesh 를 파내도 판정이 흔들리지 않게 따로 기억한다.
    private bool[] floorGrid; private int floorW, floorH; private float floorX0, floorZ0;
    private const float FloorCell = 0.1f;

    void SnapshotFloor()
    {
        var tri = UnityEngine.AI.NavMesh.CalculateTriangulation();
        if (tri.vertices.Length == 0) return;
        float x0 = float.MaxValue, z0 = float.MaxValue, x1 = float.MinValue, z1 = float.MinValue, y = 0f;
        foreach (var v in tri.vertices)
        { x0 = Mathf.Min(x0, v.x); z0 = Mathf.Min(z0, v.z); x1 = Mathf.Max(x1, v.x); z1 = Mathf.Max(z1, v.z); y += v.y; }
        y /= tri.vertices.Length;
        floorX0 = x0; floorZ0 = z0;
        floorW = Mathf.CeilToInt((x1 - x0) / FloorCell) + 1; floorH = Mathf.CeilToInt((z1 - z0) / FloorCell) + 1;
        floorGrid = new bool[floorW * floorH];
        for (int iz = 0; iz < floorH; iz++)
            for (int ix = 0; ix < floorW; ix++)
            {
                var c = new Vector3(x0 + ix * FloorCell, y, z0 + iz * FloorCell);
                floorGrid[ix + iz * floorW] =
                    UnityEngine.AI.NavMesh.SamplePosition(c, out UnityEngine.AI.NavMeshHit h, 0.3f, UnityEngine.AI.NavMesh.AllAreas) &&
                    new Vector2(h.position.x - c.x, h.position.z - c.z).magnitude < 0.03f;
            }
    }

    bool NearFloor(Vector3 world, float r)
    {
        if (floorGrid == null) return true;
        int n = Mathf.CeilToInt(r / FloorCell);
        int cx = Mathf.RoundToInt((world.x - floorX0) / FloorCell), cz = Mathf.RoundToInt((world.z - floorZ0) / FloorCell);
        for (int dz = -n; dz <= n; dz++)
            for (int dx = -n; dx <= n; dx++)
            {
                int x = cx + dx, z = cz + dz;
                if (x < 0 || z < 0 || x >= floorW || z >= floorH || !floorGrid[x + z * floorW]) continue;
                if (dx * dx + dz * dz <= n * n) return true;
            }
        return false;
    }

    string BaselinePath => System.IO.Path.Combine(Application.streamingAssetsPath, baselineFileName);

    void LoadBaseline()
    {
        try
        {
            if (System.IO.File.Exists(BaselinePath))
            {
                baseline = JsonUtility.FromJson<BaselineFile>(System.IO.File.ReadAllText(BaselinePath)) ?? new BaselineFile();
                Debug.Log($"[Anchor360] 배경(원래 있던 물건) {baseline.items.Count}개 읽음 ← {baselineFileName}");
            }
        }
        catch (Exception e) { Debug.LogWarning("[Anchor360] 배경 파일 읽기 실패: " + e.Message); }
    }

    /// <summary>지금부터 seconds 동안 보이는 검출을 '원래 있던 물건'으로 기록한다. 끝나면 파일로 저장.</summary>
    public void BeginBaselineCapture(float seconds, bool clearOld = true)
    {
        if (clearOld) baseline = new BaselineFile();
        baselineCaptureUntil = Time.unscaledTime + seconds;
        Debug.Log($"[Anchor360] 배경 기록 시작 ({seconds:F0}초). 이 동안 보이는 물건은 앞으로 새 장애물로 치지 않는다.");
    }

    bool InBaseline(Vector3 world)
    {
        foreach (var b in baseline.items)
        {
            float dx = b.x - world.x, dz = b.z - world.z;
            if (dx * dx + dz * dz <= baselineMatchM * baselineMatchM) return true;
        }
        return false;
    }

    void FinishBaselineCaptureIfDue()
    {
        if (baselineCaptureUntil < 0f || Time.unscaledTime < baselineCaptureUntil) return;
        baselineCaptureUntil = -1f;
        baseline.savedAt = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
        try
        {
            System.IO.File.WriteAllText(BaselinePath, JsonUtility.ToJson(baseline, true));
            Debug.Log($"[Anchor360] 배경 기록 끝: {baseline.items.Count}개 저장 → {baselineFileName}");
        }
        catch (Exception e) { Debug.LogWarning("[Anchor360] 배경 파일 저장 실패: " + e.Message); }
    }

    // 확인용 큐브(가구와 겹친 검출)는 보이기만 한다: 충돌체와 Obstacle 태그/레이어가 있으면 경로 검사가 막힌다
    void SetDisplayOnly(GameObject obj, bool displayOnly)
    {
        var col = obj.GetComponent<Collider>();
        if (col != null && col.enabled == displayOnly) col.enabled = !displayOnly;
        if (displayOnly)
        {
            if (obj.layer != 0) obj.layer = 0;
            if (!obj.CompareTag("Untagged")) obj.tag = "Untagged";
        }
        else if (obj.CompareTag("Untagged")) ApplyTagAndLayer(obj);
    }
    [Tooltip("범위를 바닥에 보라색으로 표시")]
    public bool showRangeZone = true;
    public Color rangeZoneColor = new Color(0.6f, 0.2f, 1f, 0.18f);
    private GameObject rangeZone;

    [Header("Debug")]
    public bool printReceivedJson = false;

    // ---- JSON 구조 — 통합데이터규약 v2 (서버 anchor360_live.py · 2026-10-27 전환) ----
    // v2 이름: label · position · ground_dist_m · size_m · bbox · confidence (+ 패킷 머리 schema_version · source_id)
    // 옛 v1 이름(name · pos3d · dist_m · size · bbox_xyxy · conf)도 받는다 — 서버를 바꾸는 동안 큐브가 끊기지 않게.
    // JsonUtility 는 빠진 중첩 객체를 null 이 아니라 빈 객체로 만든다 → v2/v1 판정은 label 문자열로 한다.
    [Serializable] public class Pos3D { public float x, y, z; }
    [Serializable] public class Size  { public float w, h, d; }
    [Serializable]
    public class Det360
    {
        public int id;
        public string group;
        public bool ground_clipped;
        // v2
        public string label;
        public float confidence;
        public float[] bbox;
        public float conf;         // v1 신뢰도
        public bool elevated;      // 바닥이 아니라 가구 위에 있는 물체
        public Pos3D position;
        public float ground_dist_m;
        public Size size_m;
        // v1 (옛 서버)
        public string name;
        public Pos3D pos3d;
        public float dist_m;
        public Size size;
        public int[] bbox_xyxy;
        // 깊이 모델로 다듬은 검출(anchor360_local.py): position 이 물체 '중심'이고 크기·방향이 실측에 가깝다
        public bool oriented;      // true면 yaw_deg 사용
        public float yaw_deg;      // 앵커 좌표계 기준 물체 방향(위에서 보아 시계방향 +)
        public string pos_src;     // "depth" 면 깊이 기반 위치

        public bool IsV2   => !string.IsNullOrEmpty(label);
        public string Label => IsV2 ? label : name;
        public Pos3D Pos    => IsV2 ? position : pos3d;
        public Size Dim     => IsV2 ? size_m : size;
    }
    [Serializable]
    public class Anchor360Packet
    {
        public string schema_version;  // v2: "2.0"
        public string source_id;       // v2: 보낸 쪽 (v1 의 camera_id 자리)
        public string timestamp;
        public string emitted_at;
        public string camera_id;       // v1
        public string frame;           // v1
        public Det360[] detections;

        public string Source => !string.IsNullOrEmpty(source_id) ? source_id : camera_id;
    }

    // ---- UDP ----
    private UdpClient udp;
    private Thread rxThread;
    private volatile bool running = false;
    private readonly object lockObj = new object();
    private string latestJson = null;            // 최신 패킷만 유지(스냅샷)

    // ---- 스폰된 큐브 ----
    private readonly List<GameObject> spawned = new List<GameObject>();
    private GameObject root;

    void Start()
    {
        if (anchorTransform == null) anchorTransform = transform;
        root = new GameObject("Anchor360_Obstacles");
        labelRoot = new GameObject("Anchor360_Labels");   // 큐브 루트와 분리(CubeLogger 가 큐브만 세도록)
        LoadCalibrationIfChanged();
        FindRoomBounds();
        SnapshotFloor();
        LoadBaseline();
        if (skipExistingObstacles || dropSightBlocked) SnapshotExistingFootprints();
        if (loadFromFile) LoadFromFileOnce();
        else StartReceiver();
    }

    void LoadFromFileOnce()
    {
        if (jsonFile == null) { Debug.LogError("[Anchor360] jsonFile 슬롯이 비어있음"); return; }
        try {
            var pkt = JsonUtility.FromJson<Anchor360Packet>(jsonFile.text);
            if (pkt?.detections == null) { Debug.LogWarning("[Anchor360] 파싱 실패/빈 detections"); return; }
            if (printReceivedJson) Debug.Log("[Anchor360] FILE: " + jsonFile.text);
            RebuildObstacles(pkt);
            Debug.Log($"[Anchor360] '{jsonFile.name}'에서 {pkt.detections.Length}개 로드");
        } catch (System.Exception e) { Debug.LogError("[Anchor360] 로드 실패: " + e.Message); }
    }

    // ---- 보정 파일 ----
    [Serializable]
    private class CalibFile
    {
        public float anchorX, anchorZ;      // 카메라의 맵 위치(m). 높이는 건드리지 않는다
        public float yawOffsetDeg;
        public float distanceScale = 1f;
        public bool invertX;
        public float range360M = -1f;       // 0 초과면 탐지 범위(m)로 쓴다
        public float navMeshPadding = -99f;  // 0 이상이면 Inspector 값 대신 이 값을 쓴다(m)
        public bool showOverlapping;        // true: 씬에 원래 있던 물체와 겹치는 검출도 그대로 표시(탐지 확인용)
        public float minConf360 = -1f;      // 0 이상이면 배치 최소 신뢰도
        public float maxFootprint360 = -1f; // 0 초과면 큐브 가로/세로 상한(m)
        public float nearFloor360 = -99f;   // -90 초과면 주행 가능 바닥에서 이 거리 안만 배치(0 이하 = 끔)
        public int useBaseline360 = -1;     // 0/1 이면 배경 빼기 끔/켬
    }
    private bool calibShowOverlapping = false;
    private DateTime calibStamp = DateTime.MinValue;
    private float nextCalibCheck = 0f;

    void LoadCalibrationIfChanged()
    {
        if (string.IsNullOrEmpty(calibrationFileName)) return;
        string path = System.IO.Path.Combine(Application.streamingAssetsPath, calibrationFileName);
        try
        {
            if (!System.IO.File.Exists(path)) return;
            DateTime stamp = System.IO.File.GetLastWriteTimeUtc(path);
            if (stamp == calibStamp) return;
            calibStamp = stamp;

            // 파일에 없는 항목은 현재 값을 유지하도록 현재 값으로 채운 뒤 덮어쓴다
            var c = new CalibFile {
                anchorX = anchorTransform.position.x, anchorZ = anchorTransform.position.z,
                yawOffsetDeg = yawOffsetDeg, distanceScale = distanceScale, invertX = invertX };
            JsonUtility.FromJsonOverwrite(System.IO.File.ReadAllText(path), c);

            Vector3 p = anchorTransform.position;
            anchorTransform.position = new Vector3(c.anchorX, p.y, c.anchorZ);
            yawOffsetDeg = c.yawOffsetDeg;
            distanceScale = c.distanceScale > 0f ? c.distanceScale : 1f;
            invertX = c.invertX;
            calibShowOverlapping = c.showOverlapping;
            if (c.navMeshPadding > -90f) navMeshPadding = c.navMeshPadding;     // 음수도 허용(파는 영역을 큐브보다 줄임)
            if (c.range360M > 0f) detectRangeM = c.range360M;
            if (c.minConf360 >= 0f) minPlaceConfidence = c.minConf360;
            if (c.maxFootprint360 > 0f) maxFootprintM = c.maxFootprint360;
            if (c.nearFloor360 > -90f) nearFloorM = c.nearFloor360;
            if (c.useBaseline360 >= 0) useBaseline = c.useBaseline360 == 1;
            UpdateRangeZone();
            Debug.Log($"[Anchor360] 보정 파일 적용: 위치 ({c.anchorX:F2}, {c.anchorZ:F2})  yaw {yawOffsetDeg:F1}°  배율 {distanceScale:F3}  ← {calibrationFileName}");
        }
        catch (Exception e) { Debug.LogWarning("[Anchor360] 보정 파일 읽기 실패: " + e.Message); }
    }

    /// <summary>탐지 범위를 바닥에 보라색 원판으로 그린다.</summary>
    void UpdateRangeZone()
    {
        if (!showRangeZone || detectRangeM <= 0f)
        {
            if (rangeZone != null) rangeZone.SetActive(false);
            return;
        }
        if (rangeZone == null) rangeZone = RangeZone.Make("Range360", rangeZoneColor);
        rangeZone.SetActive(true);
        Vector3 a = anchorTransform.position;
        rangeZone.transform.position = new Vector3(a.x, floorWorldY + 0.02f, a.z);
        RangeZone.Set(rangeZone, detectRangeM, 180f);
    }

    // ---- 기존 장애물 바닥 영역 ----
    private struct Footprint { public float minX, maxX, minZ, maxZ, topY; public string name; }
    private bool hasRoomBounds = false;
    private float roomMinX, roomMaxX, roomMinZ, roomMaxZ;

    /// <summary>방 바닥 물체(기본 "Plane")의 XZ 범위를 방 경계로 삼는다.</summary>
    void FindRoomBounds()
    {
        hasRoomBounds = false;
        if (!dropOutsideRoom || string.IsNullOrEmpty(roomFloorObjectName)) return;
        var go = GameObject.Find(roomFloorObjectName);
        var r = go != null ? go.GetComponent<Renderer>() : null;
        if (r == null)
        {
            Debug.LogWarning($"[Anchor360] 방 바닥 '{roomFloorObjectName}'을 못 찾아 방 밖 검출 제외를 끕니다.");
            return;
        }
        Bounds b = r.bounds;
        roomMinX = b.min.x + roomInset; roomMaxX = b.max.x - roomInset;
        roomMinZ = b.min.z + roomInset; roomMaxZ = b.max.z - roomInset;
        hasRoomBounds = true;
        Debug.Log($"[Anchor360] 방 경계 x {roomMinX:F2}~{roomMaxX:F2}, z {roomMinZ:F2}~{roomMaxZ:F2} (밖의 검출은 제외)");
    }

    /// <summary>
    /// 카메라에서 바닥 지점 ground 로 가는 시선이 기존 물체에 막히면 그 물체 이름을 돌려준다.
    /// 막혔다는 것은 화면에 보인 물체가 그 바닥 지점에 있는 게 아니라 가구 위에 놓였거나
    /// 가구에 아랫부분이 가려졌다는 뜻이다. 그런 검출은 바닥 투영 위치가 실제보다 멀리 틀리게 나온다.
    /// </summary>
    string FindSightBlocker(Vector3 cam, float camHeight, Vector3 ground)
    {
        float dx = ground.x - cam.x, dz = ground.z - cam.z;
        float len = Mathf.Sqrt(dx * dx + dz * dz);
        if (len < 0.05f || camHeight <= 0.1f) return null;
        // 도착점 직전 구간은 뺀다(가구 앞에 바짝 붙은 물체를 가구 탓으로 지우지 않게)
        float sEnd = 1f - Mathf.Min(0.5f, sightEndClearance / len);
        const float shrink = 0.03f;

        for (int i = 0; i < existingFootprints.Count; i++)
        {
            var f = existingFootprints[i];
            float top = f.topY - floorWorldY;
            if (top < sightMinBlockerHeight) continue;
            // 카메라가 이 물체 영역 안에 서 있으면(책상 사이 삼각대 등) 막는 것으로 치지 않는다
            if (cam.x >= f.minX && cam.x <= f.maxX && cam.z >= f.minZ && cam.z <= f.maxZ) continue;
            // 시선 높이 = camHeight·(1−s). 이 물체 꼭대기보다 낮아지는 구간만 막힐 수 있다
            float s0 = Mathf.Max(0f, 1f - top / camHeight);
            if (s0 >= sEnd) continue;

            // 선분 [s0, sEnd] 와 사각형(조금 줄인 것)의 교차 — slab 방식
            float a = s0, b = sEnd;
            if (!ClipSlab(cam.x, dx, f.minX + shrink, f.maxX - shrink, ref a, ref b)) continue;
            if (!ClipSlab(cam.z, dz, f.minZ + shrink, f.maxZ - shrink, ref a, ref b)) continue;
            if (b - a > 1e-4f) return f.name;
        }
        return null;
    }

    static bool ClipSlab(float o, float d, float lo, float hi, ref float a, ref float b)
    {
        if (lo > hi) return false;
        if (Mathf.Abs(d) < 1e-6f) return o >= lo && o <= hi;
        float t0 = (lo - o) / d, t1 = (hi - o) / d;
        if (t0 > t1) { float t = t0; t0 = t1; t1 = t; }
        if (t0 > a) a = t0;
        if (t1 < b) b = t1;
        return a <= b;
    }
    private readonly List<Footprint> existingFootprints = new List<Footprint>();
    private int lastSkippedCount = -1;

    /// <summary>
    /// Play 시작 시점에 씬에 있던 물체(렌더러·콜라이더)의 바닥 영역(XZ 사각형)을 기억한다.
    /// 이후 런타임에 생기는 큐브(이 수신기·다른 수신기 것)는 포함되지 않는다.
    /// 움직이는 것(로봇·플레이어), 벽·문·바닥, 납작한 표시물, 지나치게 넓은 것은 뺀다.
    /// </summary>
    void SnapshotExistingFootprints()
    {
        existingFootprints.Clear();
        int ignoreMask = 0;
        foreach (var ln in existingIgnoreLayers)
        {
            int l = LayerMask.NameToLayer(ln);
            if (l >= 0) ignoreMask |= 1 << l;
        }

        foreach (var r in FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None))
            if (r.enabled) TryAddFootprint(r.transform, r.bounds, ignoreMask);
        foreach (var c in FindObjectsByType<Collider>(FindObjectsSortMode.None))
            if (c.enabled && !c.isTrigger && !(c is CharacterController))
                TryAddFootprint(c.transform, c.bounds, ignoreMask);

        Debug.Log($"[Anchor360] 기존 장애물 영역 {existingFootprints.Count}개 기억 (이 자리의 검출은 제외, 여유 {existingMatchMargin:F2}m)");
    }

    void TryAddFootprint(Transform t, Bounds b, int ignoreMask)
    {
        if (((1 << t.gameObject.layer) & ignoreMask) != 0) return;
        if (root != null && t.IsChildOf(root.transform)) return;
        if (anchorTransform != null && t.IsChildOf(anchorTransform)) return;      // 카메라·삼각대 모형
        if (t.GetComponentInParent<CharacterController>() != null) return;        // 로봇·플레이어
        if (t.GetComponentInParent<UnityEngine.AI.NavMeshAgent>() != null) return;

        // 자기 이름이나 부모 이름에 제외 글자가 있으면 뺀다
        for (Transform p = t; p != null; p = p.parent)
        {
            string n = p.name.ToLowerInvariant();
            foreach (var key in existingIgnoreNameContains)
                if (!string.IsNullOrEmpty(key) && n.Contains(key.ToLowerInvariant())) return;
        }

        if (b.size.y < 0.05f) return;                       // 납작한 표시물(바닥 마커·경로선 등)
        if (b.max.y < floorWorldY + 0.05f) return;          // 바닥 아래
        if (b.min.y > floorWorldY + 2.0f) return;           // 천장 쪽(조명 등) — 바닥 장애물이 아님
        if (b.size.x * b.size.z > 30f) return;              // 방 전체를 덮는 것

        existingFootprints.Add(new Footprint {
            minX = b.min.x, maxX = b.max.x, minZ = b.min.z, maxZ = b.max.z, topY = b.max.y, name = t.name });
    }

    /// <summary>world 지점이 기존 물체 바닥 영역(+여유) 안이면 그 물체 이름, 아니면 null.</summary>
    string FindExistingAt(Vector3 world)
    {
        float m = existingMatchMargin;
        for (int i = 0; i < existingFootprints.Count; i++)
        {
            var f = existingFootprints[i];
            if (world.x >= f.minX - m && world.x <= f.maxX + m &&
                world.z >= f.minZ - m && world.z <= f.maxZ + m)
                return f.name;
        }
        return null;
    }

    void StartReceiver()
    {
        try
        {
            udp = new UdpClient(listenPort);
            running = true;
            rxThread = new Thread(ReceiveLoop) { IsBackground = true };
            rxThread.Start();
            Debug.Log($"[Anchor360] UDP {listenPort} 수신 시작");
        }
        catch (Exception e)
        {
            Debug.LogError($"[Anchor360] 포트 {listenPort} 열기 실패: {e.Message}");
        }
    }

    void ReceiveLoop()
    {
        IPEndPoint any = new IPEndPoint(IPAddress.Any, 0);
        while (running)
        {
            try
            {
                byte[] data = udp.Receive(ref any);   // blocking
                string s = Encoding.UTF8.GetString(data);
                lock (lockObj) { latestJson = s; }    // 최신만 보관
            }
            catch (Exception) { /* 소켓 종료 시 무시 */ }
        }
    }

    void Update()
    {
        if (Time.unscaledTime >= nextCalibCheck)
        {
            nextCalibCheck = Time.unscaledTime + 1f;
            LoadCalibrationIfChanged();
        }

        if (Input.GetKeyDown(baselineCaptureKey)) BeginBaselineCapture(baselineCaptureSec);
        FinishBaselineCaptureIfDue();

        string json = null;
        lock (lockObj) { if (latestJson != null) { json = latestJson; latestJson = null; } }
        if (json == null) return;

        if (printReceivedJson) Debug.Log("[Anchor360] RX: " + json);

        Anchor360Packet pkt;
        try { pkt = JsonUtility.FromJson<Anchor360Packet>(json); }
        catch (Exception e) { Debug.LogWarning("[Anchor360] JSON 파싱 실패: " + e.Message); return; }
        if (pkt == null || pkt.detections == null) return;

        RebuildObstacles(pkt);   // 스냅샷: 이전 것 제거 후 새로 생성
    }

    void RebuildObstacles(Anchor360Packet pkt)
    {
        // 큐브를 매번 지웠다 만들지 않고 같은 물체는 이어서 쓴다.
        // NavMesh 를 파내는 장애물이 매 패킷 사라졌다 생기면 경로가 계속 흔들리기 때문.
        // 이번 패킷에 안 보인 큐브는 아래에서 missingGraceSec 뒤에 지운다(사라진 장애물 정리).
        foreach (var t in tracked) t.used = false;

        Quaternion yawFix = Quaternion.Euler(0f, yawOffsetDeg, 0f);
        int skipped = 0, nOutside = 0, nBlocked = 0;
        int nLowConf = 0, nBaseline = 0, nOffFloor = 0, nElevated = 0;
        bool capturing = baselineCaptureUntil >= 0f;
        Vector3 camPos = anchorTransform.position;
        float camHeight = cameraHeightOverride > 0f
            ? cameraHeightOverride
            : (camPos.y - floorWorldY) * distanceScale;

        foreach (var det in pkt.detections)
        {
            var p3 = det.Pos;
            if (p3 == null) continue;

            // anchor 로컬 좌표(가로만 사용). y는 뒤에서 바닥으로 강제.
            float lx = p3.x * (invertX ? -1f : 1f) * distanceScale;
            float lz = p3.z * distanceScale;
            Vector3 local = yawFix * new Vector3(lx, 0f, lz);

            Vector3 world = anchorTransform.TransformPoint(local);

            // 탐지 범위(보라색) 밖이면 버린다 — 멀수록 위치·크기를 믿을 수 없다
            if (detectRangeM > 0f)
            {
                float ddx = world.x - camPos.x, ddz = world.z - camPos.z;
                if (ddx * ddx + ddz * ddz > detectRangeM * detectRangeM) { nOutside++; continue; }
            }

            // 로봇 자신이면 버린다 — 로봇 발밑의 NavMesh 를 파면 출발 자체가 안 된다
            if (selfExcludeM > 0f)
            {
                if (robotsCache == null || Time.unscaledTime >= nextRobotScan)
                {
                    robotsCache = FindObjectsByType<UnityTeleopAndMirror>(FindObjectsSortMode.None);
                    nextRobotScan = Time.unscaledTime + 3f;
                }
                bool isSelf = false;
                foreach (var utm in robotsCache)
                {
                    if (utm == null) continue;
                    Transform rt = utm.driver != null ? utm.driver.transform : utm.robotRoot;
                    if (rt == null) continue;
                    float sx = world.x - rt.position.x, sz = world.z - rt.position.z;
                    if (sx * sx + sz * sz <= selfExcludeM * selfExcludeM) { isSelf = true; break; }
                }
                if (isSelf) { nOutside++; continue; }
            }

            // 방 밖이면 버린다
            if (hasRoomBounds && (world.x < roomMinX || world.x > roomMaxX ||
                                  world.z < roomMinZ || world.z > roomMaxZ))
            {
                nOutside++;
                if (logSkippedExisting)
                    Debug.Log($"[Anchor360] 제외(방 밖): {det.Label} ({world.x:F2}, {world.z:F2})");
                continue;
            }

            // 배경 기록 중: 지금 보이는 것은 전부 '원래 있던 물건'으로 적어 둔다
            if (capturing && !InBaseline(world))
                baseline.items.Add(new BaselineItem { label = det.Label, x = world.x, z = world.z });

            // 신뢰도가 낮으면 배치하지 않는다
            if (minPlaceConfidence > 0f && Mathf.Max(det.confidence, det.conf) < minPlaceConfidence) { nLowConf++; continue; }
            // 원래 있던 물건 자리면 새 장애물이 아니다
            if (useBaseline && InBaseline(world)) { nBaseline++; continue; }
            // 로봇이 다닐 수 있는 바닥 근처가 아니면(책상 위, 가구 안쪽) 경로와 상관없다
            if (nearFloorM > 0f && (det.elevated || !NearFloor(world, nearFloorM)))
            {
                if (det.elevated) nElevated++; else nOffFloor++;
                continue;
            }

            // 씬에 원래 있던 물체 자리면 큐브를 만들지 않는다
            // (겹침 표시를 켠 경우: 큐브는 보여 주되 NavMesh 는 파지 않는다 — 그 가구는 이미 NavMesh 에 반영돼 있다)
            bool overlapsExisting = skipExistingObstacles && calibShowOverlapping && FindExistingAt(world) != null;
            if (skipExistingObstacles && !calibShowOverlapping)
            {
                string hit = FindExistingAt(world);
                if (hit != null)
                {
                    skipped++;
                    if (logSkippedExisting)
                        Debug.Log($"[Anchor360] 제외: {det.Label} ({world.x:F2}, {world.z:F2}) ← 기존 '{hit}'");
                    continue;
                }
            }

            // 시선이 기존 가구에 막혔으면(가구 위 물건·가려진 물체) 위치를 믿을 수 없다
            // (깊이 기반 위치는 바닥 가정을 쓰지 않으므로 이 검사가 필요 없다)
            if (dropSightBlocked && (det.pos_src == null || !det.pos_src.StartsWith("depth")))
            {
                string blocker = FindSightBlocker(camPos, camHeight, world);
                if (blocker != null)
                {
                    nBlocked++;
                    if (logSkippedExisting)
                        Debug.Log($"[Anchor360] 제외(시선 막힘): {det.Label} ({world.x:F2}, {world.z:F2}) ← '{blocker}'");
                    continue;
                }
            }

            // 크기
            Vector3 scale = ComputeScale(det.Dim);
            if (maxFootprintM > 0f)
            {
                scale.x = Mathf.Min(scale.x, maxFootprintM);
                scale.z = Mathf.Min(scale.z, maxFootprintM);
            }
            // 바닥에 세우기: 높이는 맵 바닥으로 강제, 큐브 중심은 절반 위로
            Vector3 pos = new Vector3(world.x, floorWorldY + scale.y * 0.5f, world.z);

            Quaternion rot = det.oriented
                ? Quaternion.Euler(0f, anchorTransform.eulerAngles.y + yawOffsetDeg +
                                       (invertX ? -det.yaw_deg : det.yaw_deg), 0f)
                : Quaternion.identity;

            Tracked tr = FindTrack(det.Label, pos);
            if (tr == null)
            {
                GameObject obj = (obstaclePrefab != null)
                    ? Instantiate(obstaclePrefab)
                    : GameObject.CreatePrimitive(PrimitiveType.Cube);
                obj.transform.SetParent(root.transform, true);
                obj.transform.SetPositionAndRotation(pos, rot);
                obj.transform.localScale = scale;
                if (obj.GetComponent<Collider>() == null) obj.AddComponent<BoxCollider>();
                ApplyTagAndLayer(obj);
                var rend = obj.GetComponent<Renderer>();
                if (rend != null) rend.material.color = cubeColor;      // 360도 카메라 = 주황

                tr = new Tracked { go = obj };
                if (addNavMeshObstacle)
                {
                    // 큐브 자리를 NavMesh 에서 파내 경로가 돌아가게 한다
                    tr.nav = obj.GetComponent<UnityEngine.AI.NavMeshObstacle>();
                    if (tr.nav == null) tr.nav = obj.AddComponent<UnityEngine.AI.NavMeshObstacle>();
                    tr.nav.shape = UnityEngine.AI.NavMeshObstacleShape.Box;
                    tr.nav.center = Vector3.zero;
                    tr.nav.carving = true;
                    tr.nav.carveOnlyStationary = true;          // 움직이는 동안(사람 등)은 파내지 않는다
                    tr.nav.carvingMoveThreshold = 0.1f;
                    tr.nav.carvingTimeToStationary = navCarveDelaySec;
                    ApplyNavSize(tr.nav, scale);
                    tr.nav.enabled = !overlapsExisting;
                }
                tracked.Add(tr);
            }
            else
            {
                if (tr.nav != null && tr.nav.enabled == overlapsExisting) tr.nav.enabled = !overlapsExisting;
                // 조금 흔들린 정도면 그대로 둔다(움직일 때마다 NavMesh 를 다시 파므로)
                Transform tf = tr.go.transform;
                if ((tf.position - pos).sqrMagnitude > trackUpdateEps * trackUpdateEps)
                    tf.position = pos;
                if ((tf.localScale - scale).sqrMagnitude > trackUpdateEps * trackUpdateEps)
                {
                    tf.localScale = scale;
                    if (tr.nav != null) ApplyNavSize(tr.nav, scale);
                }
                if (Quaternion.Angle(tf.rotation, rot) > 3f) tf.rotation = rot;
            }
            SetDisplayOnly(tr.go, overlapsExisting);
            tr.used = true;
            tr.lastSeen = Time.time;
            tr.go.name = $"Obs360_{det.Label}_{det.id}";
            tr.labelKey = det.Label;
            // 사람이면 상자 그림 대신 사람 모형을 세운다 (상자는 충돌·NavMesh 용으로 남는다)
            bool isPerson = showPersonModel && PersonVisual.IsPerson(det.Label);
            if (showPersonModel) PersonVisual.Sync(tr.go, det.Label, floorWorldY, cubeColor);

            if (showLabels)
            {
                Vector3 cubePos = tr.go.transform.position;
                Vector3 from = labelDistanceFrom != null ? labelDistanceFrom.position : camPos;
                float dist = new Vector2(cubePos.x - from.x, cubePos.z - from.z).magnitude;
                float h = Mathf.Max(tr.go.transform.localScale.y + 0.15f, labelMinHeight);
                if (isPerson) h = Mathf.Max(h, personLabelHeight);
                Vector3 labelPos = new Vector3(cubePos.x, floorWorldY + h, cubePos.z);
                string text = $"{det.Label}\n{dist:F1}m";
                if (tr.label == null)
                {
                    tr.label = MakeLabel(labelPos, text);
                    tr.labelText = tr.label.GetComponent<TextMesh>();
                }
                else
                {
                    tr.label.transform.position = labelPos;
                    if (tr.labelText.text != text) tr.labelText.text = text;   // 외곽선은 자동으로 따라온다
                }
            }
        }

        // 이번 패킷에 안 보인 큐브: 잠깐 깜빡인 검출일 수 있으니 조금 기다렸다가 지운다
        for (int i = tracked.Count - 1; i >= 0; i--)
        {
            var t = tracked[i];
            if (t.used || Time.time - t.lastSeen < missingGraceSec) continue;
            if (t.go != null) Destroy(t.go);
            if (t.label != null) Destroy(t.label);
            tracked.RemoveAt(i);
        }

        // 구성이 바뀔 때만 한 줄 (초당 여러 번 오므로 매번 찍지 않는다)
        statDetections = pkt.detections.Length; statPlaced = tracked.Count; statLowConf = nLowConf;
        statBaseline = nBaseline; statOffFloor = nOffFloor; statElevated = nElevated;
        int sig = skipped * 10000 + nOutside * 100 + nBlocked + (nLowConf + nBaseline * 7 + nOffFloor * 13 + nElevated * 17) * 1000000;
        if (sig != lastSkippedCount)
        {
            lastSkippedCount = sig;
            Debug.Log($"[Anchor360] 검출 {pkt.detections.Length}개 → 큐브 {tracked.Count}개 " +
                      $"(제외: 방 밖 {nOutside}, 기존 장애물 자리 {skipped}, 시선 막힘 {nBlocked}, " +
                      $"낮은 신뢰도 {nLowConf}, 원래 있던 물건 {nBaseline}, 바닥 밖 {nOffFloor}, 가구 위 {nElevated})");
        }
    }

    // ---- 큐브 이어 쓰기 ----
    private class Tracked
    {
        public GameObject go;
        public UnityEngine.AI.NavMeshObstacle nav;
        public GameObject label;
        public TextMesh labelText;
        public string labelKey;
        public float lastSeen;
        public bool used;
    }
    private readonly List<Tracked> tracked = new List<Tracked>();

    /// <summary>
    /// 이번 검출과 같은 물체로 볼 기존 큐브. 이름이 같으면 trackMatchRadius 안에서,
    /// 이름이 달라도(box ↔ storage box 처럼 바뀌는 경우) 그 절반 거리 안이면 같은 물체로 본다.
    /// </summary>
    Tracked FindTrack(string label, Vector3 pos)
    {
        Tracked best = null;
        float bestD = float.MaxValue;
        foreach (var t in tracked)
        {
            if (t.used || t.go == null) continue;
            Vector3 p = t.go.transform.position;
            float d = new Vector2(p.x - pos.x, p.z - pos.z).magnitude;
            float limit = t.labelKey == label ? trackMatchRadius : trackMatchRadius * 0.5f;
            if (d <= limit && d < bestD) { best = t; bestD = d; }
        }
        return best;
    }

    /// <summary>NavMesh 에서 파낼 상자 크기. 큐브(1×1×1) 기준 배율이라 여유(m)를 큐브 크기로 나눠 더한다.</summary>
    void ApplyNavSize(UnityEngine.AI.NavMeshObstacle nav, Vector3 cubeScale)
    {
        nav.size = new Vector3(
            Mathf.Max(0.1f, 1f + 2f * navMeshPadding / Mathf.Max(cubeScale.x, 0.01f)),
            1f,
            Mathf.Max(0.1f, 1f + 2f * navMeshPadding / Mathf.Max(cubeScale.z, 0.01f)));
    }

    // ---- 라벨 ----
    private GameObject labelRoot;
    private Font labelFont;

    /// <summary>흰 글자 + 검은 외곽선 4장. 항상 카메라를 향한다(FaceCameraLabel).</summary>
    GameObject MakeLabel(Vector3 worldPos, string text)
    {
        if (labelFont == null) labelFont = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");

        var label = new GameObject("ObstacleLabel");
        label.transform.SetParent(labelRoot.transform, true);
        label.transform.position = worldPos;
        SetupLabelText(label, text, labelColor);
        label.GetComponent<MeshRenderer>().sortingOrder = 1;      // 본문을 외곽선보다 나중에 그림
        label.AddComponent<FaceCameraLabel>().yawOnly = false;

        const float o = 0.005f;
        for (int i = 0; i < 4; i++)
        {
            float a = (i * 90f + 45f) * Mathf.Deg2Rad;
            var outline = new GameObject("Outline");
            outline.transform.SetParent(label.transform, false);
            var offset = new Vector3(Mathf.Cos(a) * o, Mathf.Sin(a) * o, 0.002f);
            outline.transform.localPosition = offset;
            SetupLabelText(outline, text, new Color(0f, 0f, 0f, 0.9f));
            var face = outline.AddComponent<FaceCameraLabel>();
            face.yawOnly = false;
            face.viewOffset = offset;
        }
        return label;
    }

    void SetupLabelText(GameObject go, string text, Color color)
    {
        var tm = go.AddComponent<TextMesh>();
        tm.text = text;
        tm.font = labelFont;
        tm.fontSize = labelFontSize;
        tm.characterSize = labelCharacterSize;
        tm.anchor = TextAnchor.LowerCenter;
        tm.alignment = TextAlignment.Center;
        tm.color = color;
        go.GetComponent<MeshRenderer>().sharedMaterial = labelFont.material;
    }

    Vector3 ComputeScale(Size s)
    {
        float w = defaultCubeSize, h = defaultCubeSize, d = defaultCubeSize;
        if (s != null && s.w > 0f) { w = s.w; h = (s.h > 0f ? s.h : s.w); d = (s.d > 0f ? s.d : s.w); }
        w *= sizeMultiplier; h *= sizeMultiplier; d *= sizeMultiplier;
        w = Mathf.Clamp(w, minCubeSize, maxCubeSize);
        h = Mathf.Clamp(h, minCubeSize, maxCubeSize);
        d = Mathf.Clamp(d, minCubeSize, maxCubeSize);
        return new Vector3(w, h, d);
    }

    void ApplyTagAndLayer(GameObject obj)
    {
        if (!assignObstacleTagAndLayer) return;
        try { if (!string.IsNullOrEmpty(obstacleTagName)) obj.tag = obstacleTagName; }
        catch { Debug.LogWarning($"[Anchor360] Tag '{obstacleTagName}' 없음. Tags & Layers에 추가 필요."); }
        if (!string.IsNullOrEmpty(obstacleLayerName))
        {
            int layer = LayerMask.NameToLayer(obstacleLayerName);
            if (layer >= 0) obj.layer = layer;
            else Debug.LogWarning($"[Anchor360] Layer '{obstacleLayerName}' 없음. Tags & Layers에 추가 필요.");
        }
    }

    void OnDestroy()  { StopReceiver(); }
    void OnApplicationQuit() { StopReceiver(); }
    void StopReceiver()
    {
        running = false;
        try { udp?.Close(); } catch { }
        try { rxThread?.Join(200); } catch { }
    }
}
