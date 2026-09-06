/*
 * WsPlannerClient.cs — Digital Twin WebSocket Client
 *
 * Architecture:
 *   Pyjevsim = Real world  (DEVS 엔진이 Boat 이동, 탑재 센서가 장애물 탐지)
 *   Unity    = Digital twin (현실 미러링, NavMesh + ML-Agents COLREGS 재경로)
 *
 * Message flow (매 Tick):
 *   Pyjevsim → Unity : sim_tick   (현실 위치 + 탐지 장애물)
 *   Unity → Pyjevsim : twin_ack   (가상위치 ACK + 현재/재계획 경로)
 *
 * Dependencies:
 *   - System.Net.WebSockets (기본 .NET — 추가 패키지 불필요)
 *   - Newtonsoft.Json (com.unity.nuget.newtonsoft-json — 이미 설치됨)
 *   - com.unity.ai.navigation (NavMesh 재경로)
 */

using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.AI;
using Unity.MLAgents;
using Unity.MLAgents.Policies;
using Unity.InferenceEngine;
using Newtonsoft.Json;

// ─── JSON 메시지 구조체 ────────────────────────────────────────────────────────

public class SimTickMessage
{
    [JsonProperty("type")]                public string    type;
    [JsonProperty("platform_name")]       public string    platform_name;
    [JsonProperty("position")]            public float[]   position;               // [x, y, z] Pyjevsim 좌표
    [JsonProperty("waypoints")]           public float[][] waypoints;              // [[x,y], ...]
    [JsonProperty("waypoint_idx")]        public int       waypoint_idx;
    [JsonProperty("detected_obstacles")] public float[][] detected_obstacles;     // [[x,y,z], ...] 없으면 []
    [JsonProperty("destination")]         public float[]   destination;            // [x, y]
}

public class TwinAckMessage
{
    [JsonProperty("type")]             public string    type             = "twin_ack";
    [JsonProperty("platform_name")]    public string    platform_name;
    [JsonProperty("virtual_position")] public float[]   virtual_position;  // [x, y, z] Pyjevsim 좌표
    [JsonProperty("waypoints")]        public float[][] waypoints;
    [JsonProperty("replanned")]        public bool      replanned;
    [JsonProperty("status")]           public string    status           = "ok";
}

// 연결 직후 1회 전송 — Pyjevsim 전역 경로계획을 위한 맵 인지 정보
public class MapInfoMessage
{
    [JsonProperty("type")]               public string    type = "map_info";
    [JsonProperty("coordinate_note")]    public string    coordinate_note = "Pyjevsim(x,y) <-> Unity(x,0,y)";
    [JsonProperty("bounds_min")]         public float[]   bounds_min;          // [x, y] 맵 최소 코너
    [JsonProperty("bounds_max")]         public float[]   bounds_max;          // [x, y] 맵 최대 코너
    [JsonProperty("start")]              public float[]   start;               // [x, y] 출발점
    [JsonProperty("destination")]        public float[]   destination;         // [x, y] 목표점
    // ML-Agent(ONNX)가 정상 동작하는 원형 항행영역 — 전역 웨이포인트는 이 원 안에 있어야 함
    [JsonProperty("operational_center")] public float[]   operational_center;  // [x, y] 원 중심
    [JsonProperty("operational_radius")] public float     operational_radius;  // 반경 (m)
    [JsonProperty("static_obstacles")]   public float[][] static_obstacles;    // [[x, y, r], ...] 정적 장애물
}

// 메시지 타입 판별용 최소 봉투
public class TypedMessage
{
    [JsonProperty("type")] public string type;
}

// Pyjevsim → Unity : 시나리오 전달 (연결 후, 초기 경로 생성 트리거)
public class ScenarioMessage
{
    [JsonProperty("type")]          public string  type;
    [JsonProperty("platform_name")] public string  platform_name;
    [JsonProperty("start")]         public float[] start;        // [x, y]
    [JsonProperty("destination")]   public float[] destination;  // [x, y]
}

// Unity → Pyjevsim : 초기 경로 응답 (단독 자율주행 결과)
public class ScenarioAckMessage
{
    [JsonProperty("type")]         public string    type         = "scenario_ack";
    [JsonProperty("platform_name")] public string   platform_name;
    [JsonProperty("initial_path")] public float[][] initial_path;  // [[x, y], ...] (실패 시 null)
    [JsonProperty("status")]       public string    status       = "ok";
}

// ─── MonoBehaviour ────────────────────────────────────────────────────────────

public class WsPlannerClient : MonoBehaviour
{
    [Header("Server (Pyjevsim)")]
    public string serverUri         = "ws://192.168.0.100:8765";  // Pyjevsim PC의 IP로 변경
    public float  reconnectDelaySec = 2f;

    [Header("Arrival (도착 판정)")]
    [Tooltip("목적지 도착 판정 거리 (m). 이 안에 들어오면 twin_ack.status='arrived' 전송")]
    public float  arrivalDistanceM = 12f;

    [Header("Digital Twin — Virtual Boat")]
    [Tooltip("씬에서 Pyjevsim 위치를 미러링할 Boat GameObject (null이면 자동 생성)")]
    public GameObject boatObject;
    [Tooltip("Pyjevsim의 sim_tick이 듬성듬성 도착해도 점프처럼 안 보이도록, 직전 tick 간격만큼 "
           + "부드럽게 이동시킬 때 사용할 최소/최대 보간 시간(초). 너무 작으면 다시 끊겨 보이고, "
           + "너무 크면 실제 위치를 뒤늦게 따라가는 것처럼 보임.")]
    public float mirrorGlideMinSeconds = 0.1f;
    public float mirrorGlideMaxSeconds = 2f;

    [Header("ML-Agents (COLREGS)")]
    [Tooltip("BoatColregAgent 할당. 경로 계획 시 목표 갱신에 사용 (null이면 자동 탐색)")]
    public Agent pathAgent;

    [Header("Obstacles")]
    [Tooltip("장애물 시각화 프리팹 (null이면 기본 실린더 자동 생성)")]
    public GameObject obstaclePrefab;
    [Tooltip("탐지된 장애물이 남은 경로(현재 위치→remaining waypoints)로부터 이 거리(m) 이내일 때만 "
           + "'경로를 막음'으로 판단해 재계획을 트리거함. 시각화(부표 표시)는 이 값과 무관하게 항상 수행. "
           + "너무 작으면(예: 센서 detection_range보다 작음) 탐지는 되지만 '막음' 판정을 못 받아 "
           + "아예 재탐색을 시도하지 않는 상태가 됨 — 그런 로그(blocking=false)가 보이면 이 값을 올릴 것.")]
    public float obstacleBlockRadius = 25f;

    [Header("Traveled Path (지나온 경로 시각화)")]
    [Tooltip("지나온 경로를 그릴 LineRenderer (null이면 자동 생성)")]
    public LineRenderer traveledPathRenderer;
    [Tooltip("경로 라인 두께 (m)")]
    public float traveledPathWidth = 0.6f;
    [Tooltip("경로 라인 색상")]
    public Color traveledPathColor = new Color(1f, 0.85f, 0.1f, 0.9f);
    [Tooltip("직전 기록 지점에서 이 거리(m) 이상 이동했을 때만 새 점을 추가 — 점 수 폭증 방지")]
    public float traveledPathMinPointDistance = 1f;

    [Header("NavMesh Replanning (정책 롤아웃 실패 시 폴백)")]
    [Tooltip("NavMesh 샘플 탐색 반경 (m)")]
    public float navMeshSampleRadius = 5f;
    [Tooltip("정책 롤아웃이 불가하거나 실패할 때만 NavMesh 기하 우회로 폴백. "
           + "기본 OFF — 경로는 항상 ML 정책 궤적을 사용 (NavMesh 기하 경로 배제)")]
    public bool  useNavMeshFallback = false;

    [Header("Deterministic Bypass (ML/NavMesh 모두 실패했을 때 최종 안전망)")]
    [Tooltip("장애물을 기하학적으로 우회하는 결정론적 웨이포인트를 생성 — 학습 없이 즉시 동작. "
           + "ML 롤아웃과 NavMesh 폴백이 모두 실패(또는 미사용)했을 때만 적용.")]
    public bool  useRightBypassFallback = true;
    [Tooltip("장애물 자체 반경으로 가정할 값 (m)")]
    public float bypassObstacleRadius = 3f;
    [Tooltip("장애물 반경에 추가로 더할 안전 여유 (m)")]
    public float bypassMargin = 6f;
    [Tooltip("true=장애물을 오른쪽(우현)으로 우회, false=왼쪽. 실제로 반대 방향으로 돈다면 이 값을 뒤집으세요.")]
    public bool  bypassPreferRight = true;
    [Tooltip("장애물 재계획 시 ML 정책 롤아웃을 먼저 시도할지 여부. 학습된 정책이 특정 장애물을 "
           + "잘 회피하지 못할 때 false로 끄면 충돌 위험 없이 NavMesh/결정론적 우회로 즉시 넘어감 "
           + "(재학습 전 임시 대응용). Phase 0 초기경로 롤아웃(장애물 없음)에는 영향 없음.")]
    public bool  useMlRolloutForObstacles = true;

    [Header("Policy Rollout (COLREGS 정책 기반 회피)")]
    [Tooltip("경로계획에 사용할 학습된 ONNX 모델. 미할당 시 씬의 BoatAutoDriveController/BehaviorParameters에서 자동 탐색")]
    public ModelAsset plannerModel;
    [Tooltip("롤아웃 1회 최대 가상 주행 시간 (초, 시뮬레이션 기준)")]
    public float rolloutMaxSeconds = 20f;
    [Tooltip("롤아웃 중 Time.timeScale 가속 배율 (twin_ack 지연 단축). 물리 정확도상 4~8 권장")]
    [Range(1f, 20f)] public float rolloutTimeScale = 6f;
    [Tooltip("궤적 → 웨이포인트 다운샘플 간격 (m). 작을수록 ML 곡선을 충실히 표현(직선 분절 방지)")]
    public float waypointSpacingM = 4f;
    [Tooltip("플래너 보트 메쉬를 숨김. 씬 Boat를 표시 트윈으로 겸용하면 false 권장(겸용 시 자동으로 숨기지 않음)")]
    public bool  hidePlannerBoat = false;

    [Header("Map Info (Pyjevsim 전역 인지 — 연결 직후 1회 전송)")]
    [Tooltip("맵 최소 코너 마커 (null이면 이름 '0,0' 자동 탐색)")]
    public Transform mapCornerMin;
    [Tooltip("맵 최대 코너 마커 (null이면 이름 '200,200' 자동 탐색)")]
    public Transform mapCornerMax;
    [Tooltip("출발점 (null이면 이름 'startPoint' 자동 탐색)")]
    public Transform startPoint;
    [Tooltip("목표점 (null이면 이름 'GoalPoint' 자동 탐색)")]
    public Transform goalPoint;

    // ── 내부 상태 ────────────────────────────────────────────────────────────

    private ClientWebSocket         _ws;
    private CancellationTokenSource _cts;
    private Thread                  _bgThread;
    private bool                    _isRunning;

    // 배경 스레드 ↔ 메인 스레드 통신
    private readonly ConcurrentQueue<string> _receiveQueue = new ConcurrentQueue<string>();
    private readonly ConcurrentQueue<string> _sendQueue    = new ConcurrentQueue<string>();
    private readonly SemaphoreSlim           _sendReady    = new SemaphoreSlim(0, 1);

    // 좌표(반올림) 키 → 스폰된 부표. 시나리오가 끝날 때까지 지우지 않고 계속 누적/유지
    private readonly Dictionary<string, GameObject> _obstacleRegistry = new Dictionary<string, GameObject>();
    private bool             _coroutineRunning;
    private GameObject       _defaultObstaclePrefab;

    // 연결 직후 전송할 map_info (메인 스레드 Start에서 씬 데이터로 미리 직렬화)
    private string _mapInfoJson;

    // ── 정책 롤아웃 플래너 ────────────────────────────────────────────────────
    private BoatColregAgent    _planner;         // 롤아웃 주행 에이전트 (= pathAgent)
    private BehaviorParameters _plannerBp;
    private Transform          _plannerGoal;     // 롤아웃 목표 Transform
    private int                _plannerLayer;    // 장애물을 배치할 레이어
    private BoatTrainingManager _savedTrainMgr;  // 복원용 (롤아웃 중 null 처리)

    // 경로 캐시 — 동일 장애물 집합에는 재롤아웃하지 않음
    private string    _lastObstacleKey = null;
    private float[][] _cachedPlan      = null;

    // 미러 Boat 헤딩 추정 (이동 방향 기반) — tick 간 원시 위치 이력
    private bool    _hasMirrorHistory;
    private Vector3 _lastMirrorPos;
    private float   _lastMirrorTime;

    // 미러 Boat 위치/회전 보간(glide) 상태 — Update()에서 매 프레임 진행시켜
    // 듬성듬성 도착하는 sim_tick 사이를 부드럽게 이어줌
    private bool       _mirrorGlideActive;
    private Vector3    _mirrorFromPos;
    private Vector3    _mirrorToPos;
    private Quaternion _mirrorFromRot;
    private Quaternion _mirrorToRot;
    private float      _mirrorGlideStart;
    private float      _mirrorGlideDuration;

    // 지나온 경로 기록 (LineRenderer)
    private readonly List<Vector3> _traveledPoints = new List<Vector3>();

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    private void Start()
    {
        // pathAgent 자동 탐색
        if (pathAgent == null)
            pathAgent = FindFirstObjectByType<BoatColregAgent>();

        // 표시용 트윈 Boat: 미할당 시 씬의 에이전트 Boat를 그대로 사용(표시+플래너 겸용).
        // 에이전트가 없을 때만 간단한 큐브 생성.
        if (boatObject == null)
            boatObject = pathAgent != null ? pathAgent.gameObject : CreateVirtualBoat();

        // obstaclePrefab 자동 생성
        if (obstaclePrefab == null)
        {
            _defaultObstaclePrefab = CreateDefaultObstaclePrefab();
            obstaclePrefab = _defaultObstaclePrefab;
        }

        // 정책 롤아웃 플래너 초기화
        SetupPolicyPlanner();

        // 지나온 경로 라인 초기화
        SetupTraveledPathRenderer();

        // map_info(맵/항행영역) 빌드 → 연결. 초기 경로는 Pyjevsim의 scenario 수신 시 생성.
        _mapInfoJson = BuildMapInfoJson();
        StartBgThread();
        Debug.Log("[DigitalTwin] WsPlannerClient 시작 → " + serverUri);
    }

    private void SnapPlannerTo(Vector3 pos)
    {
        if (boatObject == null) return;
        var rb = boatObject.GetComponent<Rigidbody>();
        if (rb != null)
        {
            rb.linearVelocity  = Vector3.zero;
            rb.angularVelocity = Vector3.zero;
            rb.position        = pos;
        }
        else
        {
            boatObject.transform.position = pos;
        }
    }

    // ── 정책 롤아웃 플래너 설정 ────────────────────────────────────────────────

    private void SetupPolicyPlanner()
    {
        _planner = pathAgent as BoatColregAgent;
        if (_planner == null)
        {
            Debug.LogWarning("[DigitalTwin] BoatColregAgent 없음 → 정책 롤아웃 불가, NavMesh 폴백만 동작");
            return;
        }

        // 학습 매니저가 살아있으면 트윈과 충돌(8척 스폰/랜덤 재배치). 경고.
        var trainMgr = FindFirstObjectByType<BoatTrainingManager>();
        if (trainMgr != null && trainMgr.isActiveAndEnabled && trainMgr.boatPrefab != null)
            Debug.LogWarning("[DigitalTwin] 씬에 BoatTrainingManager가 활성화됨 — 디지털 트윈에서는 "
                           + "TrainingManager 오브젝트를 비활성화하세요 (보트 8척 스폰/랜덤 재배치 충돌).");

        // 롤아웃 중 학습매니저 재배치 콜백 차단 (경계값·위치 유지)
        _savedTrainMgr           = _planner.trainingManager;
        _planner.trainingManager = null;

        _plannerBp    = _planner.GetComponent<BehaviorParameters>();
        _plannerLayer = _planner.gameObject.layer;

        // ONNX 모델 자동 탐색 (Inspector 미할당 시)
        if (plannerModel == null)
        {
            var autoDrive = FindFirstObjectByType<BoatAutoDriveController>();
            if (autoDrive != null && autoDrive.onnxModel != null)
                plannerModel = autoDrive.onnxModel;
            else if (_plannerBp != null && _plannerBp.Model != null)
                plannerModel = _plannerBp.Model;
        }
        if (plannerModel == null)
            Debug.LogWarning("[DigitalTwin] ONNX 모델을 찾지 못함 → plannerModel 할당 필요 (NavMesh 폴백 동작)");

        // 롤아웃 목표 Transform 생성
        var goalGo   = new GameObject("DT_PlannerGoal");
        _plannerGoal = goalGo.transform;

        // 유휴 상태에서 플래너가 스스로 움직이지 않도록 정지
        // (프리팹의 BehaviorType이 InferenceOnly로 저장돼 있어도 시작 시 자율주행 방지)
        if (_plannerBp != null)
            _plannerBp.BehaviorType = BehaviorType.HeuristicOnly;
        _planner.StopPlanningRollout();

        // 플래너 보트 메쉬 숨김 (표시 트윈으로 겸용 중이면 숨기지 않음)
        if (hidePlannerBoat && _planner.gameObject != boatObject)
            foreach (var r in _planner.GetComponentsInChildren<Renderer>())
                r.enabled = false;

        Debug.Log($"[DigitalTwin] 정책 롤아웃 플래너 준비 완료 (layer={_plannerLayer}, "
                + $"model={(plannerModel != null ? plannerModel.name : "없음")})");
    }

    // ── 맵 인지 정보 구성 (메인 스레드) ──────────────────────────────────────────

    private string BuildMapInfoJson()
    {
        // 씬 마커 자동 탐색 (Inspector 미할당 시)
        if (mapCornerMin == null) mapCornerMin = FindTransformByName("0,0");
        if (mapCornerMax == null) mapCornerMax = FindTransformByName("200,200");
        if (startPoint   == null) startPoint   = FindTransformByName("startPoint");
        if (goalPoint    == null) goalPoint    = FindTransformByName("GoalPoint");

        // 기본값 (마커 없을 때) — 현재 씬 구성 기준
        float[] boundsMin = mapCornerMin != null ? UnityToSim(mapCornerMin.position) : new float[] { 0f,   0f   };
        float[] boundsMax = mapCornerMax != null ? UnityToSim(mapCornerMax.position) : new float[] { 200f, 200f };
        float[] start     = startPoint   != null ? UnityToSim(startPoint.position)   : new float[] { 10f,  10f  };
        float[] dest      = goalPoint    != null ? UnityToSim(goalPoint.position)    : new float[] { 40f,  60f  };

        // ML-Agent 학습 항행영역 (BoatColregAgent에서 읽음)
        float[] opCenter = new float[] { 0f, 60f };
        float   opRadius = 100f;
        if (pathAgent is BoatColregAgent colreg)
        {
            opCenter = new float[] { colreg.boundaryCenter.x, colreg.boundaryCenter.z };
            opRadius = colreg.boundaryRadius;
        }

        MapInfoMessage map = new MapInfoMessage
        {
            bounds_min         = boundsMin,
            bounds_max         = boundsMax,
            start              = start,
            destination        = dest,
            operational_center = opCenter,
            operational_radius = opRadius,
            static_obstacles   = new float[0][]   // 현재 씬에 정적 장애물 없음
        };

        Debug.Log($"[DigitalTwin] map_info 준비  bounds=({boundsMin[0]},{boundsMin[1]})~({boundsMax[0]},{boundsMax[1]})"
                + $"  op_center=({opCenter[0]},{opCenter[1]}) r={opRadius}");

        return JsonConvert.SerializeObject(map);
    }

    private static Transform FindTransformByName(string name)
    {
        GameObject go = GameObject.Find(name);
        return go != null ? go.transform : null;
    }

    private static float[] UnityToSim(Vector3 p) => new float[] { p.x, p.z };

    private void Update()
    {
        // 매 프레임 진행 — 롤아웃이 보트를 직접 조작 중일 때는 건드리지 않음
        UpdateMirrorGlide();

        // 코루틴이 실행 중이 아닐 때만 다음 메시지 처리 (직렬 처리 보장)
        if (_coroutineRunning)
            return;

        if (_receiveQueue.TryDequeue(out string json))
            StartCoroutine(ProcessIncomingCoroutine(json));
    }

    // sim_tick 사이 구간을 매 프레임 보간 이동 — RolloutFromTo가 보트를 점유 중일 때는
    // (_mirrorGlideActive를 그쪽에서 꺼두므로) 자동으로 개입하지 않음
    private void UpdateMirrorGlide()
    {
        if (!_mirrorGlideActive || boatObject == null) return;

        float t = Mathf.Clamp01((Time.time - _mirrorGlideStart) / Mathf.Max(0.0001f, _mirrorGlideDuration));
        Vector3    pos = Vector3.Lerp(_mirrorFromPos, _mirrorToPos, t);
        Quaternion rot = Quaternion.Slerp(_mirrorFromRot, _mirrorToRot, t);

        ApplyMirrorTransform(pos, rot);

        if (t >= 1f) _mirrorGlideActive = false;
    }

    private void OnDestroy()         => Shutdown();
    private void OnDisable()         => Shutdown();
    private void OnApplicationQuit() => Shutdown();

    // ── WebSocket 배경 스레드 ──────────────────────────────────────────────────

    private void StartBgThread()
    {
        _isRunning = true;
        _cts       = new CancellationTokenSource();
        _bgThread  = new Thread(BgLoop) { IsBackground = true };
        _bgThread.Start();
    }

    private void Shutdown()
    {
        if (!_isRunning) return;
        _isRunning = false;

        try { _cts?.Cancel(); } catch { }
        try { _sendReady.Release(); } catch { }  // WaitAsync 해제

        try { _ws?.Abort(); _ws?.Dispose(); } catch { }

        if (_bgThread != null && _bgThread.IsAlive)
            _bgThread.Join(500);

        _cts?.Dispose();

        if (_defaultObstaclePrefab != null)
            Destroy(_defaultObstaclePrefab);

        // 플래너 상태 복원
        if (_planner != null) _planner.trainingManager = _savedTrainMgr;
        if (_plannerGoal != null) Destroy(_plannerGoal.gameObject);

        // 재연결 시 이전 세션의 위치를 기준으로 헤딩을 계산하지 않도록 초기화
        _hasMirrorHistory  = false;
        _mirrorGlideActive = false;
    }

    private void BgLoop()
    {
        while (_isRunning)
        {
            try
            {
                ConnectAndRun().GetAwaiter().GetResult();
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception e)
            {
                if (!_isRunning) break;
                Debug.LogWarning($"[DigitalTwin] 연결 오류: {e.Message} → {reconnectDelaySec}s 후 재연결");
            }

            if (!_isRunning) break;
            Thread.Sleep((int)(reconnectDelaySec * 1000));
        }
    }

    private async Task ConnectAndRun()
    {
        CancellationToken token = _cts.Token;

        _ws?.Dispose();
        _ws = new ClientWebSocket();

        Debug.Log($"[DigitalTwin] 연결 시도: {serverUri}");
        await _ws.ConnectAsync(new Uri(serverUri), token);
        Debug.Log($"[DigitalTwin] Connected to Pyjevsim @ {serverUri}");

        // ── 핸드셰이크: 맵 인지 정보(map_info) 1회 전송 ──────────────────────────
        if (!string.IsNullOrEmpty(_mapInfoJson))
        {
            byte[] mapBytes = Encoding.UTF8.GetBytes(_mapInfoJson);
            await _ws.SendAsync(
                new ArraySegment<byte>(mapBytes),
                WebSocketMessageType.Text, true, token);
            Debug.Log("[DigitalTwin] map_info 전송 완료 → Pyjevsim 전역 인지 초기화");
        }

        byte[]        buffer  = new byte[65536];
        StringBuilder builder = new StringBuilder();

        while (_isRunning && _ws.State == WebSocketState.Open)
        {
            // ── 수신 ──────────────────────────────────────────────────────────
            WebSocketReceiveResult result =
                await _ws.ReceiveAsync(new ArraySegment<byte>(buffer), token);

            if (result.MessageType == WebSocketMessageType.Close)
            {
                Debug.Log("[DigitalTwin] 서버가 연결을 닫았습니다.");
                break;
            }

            builder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
            if (!result.EndOfMessage) continue;

            // 메인 스레드로 전달
            _receiveQueue.Enqueue(builder.ToString());
            builder.Clear();

            // ── 메인 스레드의 twin_ack 응답 대기 ─────────────────────────────
            await _sendReady.WaitAsync(token);

            // ── 송신 ──────────────────────────────────────────────────────────
            if (_sendQueue.TryDequeue(out string ack))
            {
                byte[] bytes = Encoding.UTF8.GetBytes(ack);
                await _ws.SendAsync(
                    new ArraySegment<byte>(bytes),
                    WebSocketMessageType.Text, true, token);
            }
        }
    }

    // ── 메인 스레드: 수신 메시지 디스패처 ────────────────────────────────────

    private IEnumerator ProcessIncomingCoroutine(string json)
    {
        _coroutineRunning = true;

        string type = null;
        try { type = JsonConvert.DeserializeObject<TypedMessage>(json)?.type; }
        catch (Exception e)
        {
            Debug.LogError($"[DigitalTwin] JSON 파싱 실패: {e.Message}");
            EnqueueErrorAck();
            _coroutineRunning = false;
            yield break;
        }

        if (type == "scenario")
            yield return StartCoroutine(ProcessScenario(json));
        else if (type == "sim_tick")
            yield return StartCoroutine(ProcessSimTick(json));
        else
        {
            Debug.LogWarning($"[DigitalTwin] 알 수 없는 메시지 type={type}");
            EnqueueErrorAck();
        }

        _coroutineRunning = false;
    }

    // ── Phase 0~1: 시나리오 수신 → 초기 경로 단독 생성 → scenario_ack ──────────

    private IEnumerator ProcessScenario(string json)
    {
        ScenarioMessage sc;
        try { sc = JsonConvert.DeserializeObject<ScenarioMessage>(json); }
        catch (Exception e)
        {
            Debug.LogError($"[DigitalTwin] scenario 파싱 실패: {e.Message}");
            EnqueueErrorAck();
            yield break;
        }

        if (startPoint == null) startPoint = FindTransformByName("startPoint");
        if (goalPoint  == null) goalPoint  = FindTransformByName("GoalPoint");

        Vector3 startPos = (sc.start != null && sc.start.Length >= 2)
            ? SimToUnity(sc.start[0], sc.start[1])
            : (startPoint != null ? startPoint.position : Vector3.zero);
        Vector3 goalPos  = (sc.destination != null && sc.destination.Length >= 2)
            ? SimToUnity(sc.destination[0], sc.destination[1])
            : (goalPoint != null ? goalPoint.position : startPos);

        // 씬 목표/에이전트 목표를 시나리오 목적지로 동기화
        if (goalPoint != null) goalPoint.position = goalPos;

        Debug.Log($"[DigitalTwin] scenario 수신 → 초기 경로 생성 "
                + $"start=({startPos.x:F0},{startPos.z:F0}) goal=({goalPos.x:F0},{goalPos.z:F0})");

        // 장애물 없는 상태에서 start→goal 단독 자율주행 → 초기 경로
        float[][] initPath = null;
        if (_planner != null && plannerModel != null)
            yield return StartCoroutine(RolloutFromTo(startPos, goalPos, r => initPath = r));

        // Phase 1: 시작점 복귀 (합동 주행 대기)
        SnapPlannerTo(startPos);
        _hasMirrorHistory  = false;  // 롤아웃 이동 이력을 헤딩 계산에 반영하지 않도록 초기화
        _mirrorGlideActive = false;  // SnapPlannerTo 직후 이전 글라이드가 위치를 덮어쓰지 않도록

        // 새 에피소드 시작 — 이전 에피소드의 재계획 캐시가 우연히 같은 키로 재사용되지 않도록 초기화
        _lastObstacleKey = null;
        _cachedPlan      = null;

        // 새 에피소드 시작 — 이전 에피소드의 부표/지나온 경로 정리 (같은 에피소드 안에서는 유지)
        ClearObstacles();
        ClearTraveledPath();

        if (initPath != null)
            Debug.Log($"[DigitalTwin] 초기 경로 생성 완료: {initPath.Length}개 웨이포인트");
        else
            Debug.LogWarning("[DigitalTwin] 초기 경로 생성 실패 → Pyjevsim이 자체 경로 사용");

        var ack = new ScenarioAckMessage
        {
            platform_name = sc.platform_name,
            initial_path  = initPath,
            status        = initPath != null ? "ok" : "failed"
        };
        _sendQueue.Enqueue(JsonConvert.SerializeObject(ack));
        _sendReady.Release();
    }

    // ── 메인 스레드: sim_tick 처리 ────────────────────────────────────────────

    private IEnumerator ProcessSimTick(string json)
    {
        SimTickMessage msg;
        try
        {
            msg = JsonConvert.DeserializeObject<SimTickMessage>(json);
        }
        catch (Exception e)
        {
            Debug.LogError($"[DigitalTwin] sim_tick 파싱 실패: {e.Message}");
            EnqueueErrorAck();
            yield break;
        }

        bool hasObstacles = msg.detected_obstacles != null && msg.detected_obstacles.Length > 0;
        bool blocking     = hasObstacles && IsPathBlocked(msg);

        Debug.Log($"[DigitalTwin] sim_tick  platform={msg.platform_name}"
                + $"  pos=({msg.position[0]:F1},{msg.position[1]:F1})"
                + $"  obstacles={msg.detected_obstacles?.Length ?? 0}  blocking={blocking}");

        // ── 1. 가상 Boat 위치 동기화 (Pyjevsim XZ → Unity XZ) ───────────────
        SyncBoatPosition(msg);
        RecordTraveledPoint(msg);

        // ── 2. 장애물 씬 갱신 (막고 있는지 여부와 무관하게 탐지된 것은 모두 시각화) ──
        SpawnObstacles(msg.detected_obstacles);

        // ── 3. 경로 결정 ───────────────────────────────────────────────────
        float[][] outWaypoints;
        bool replanned = false;

        if (blocking)
        {
            string obsKey = ObstacleKey(msg.detected_obstacles);

            // 동일 장애물 집합이면 캐시된 경로 재사용 (매 틱 롤아웃 방지)
            if (obsKey == _lastObstacleKey && _cachedPlan != null)
            {
                outWaypoints = _cachedPlan;
                replanned    = false;   // 이미 재계획된 경로 유지 중
            }
            else
            {
                float[][] plan = null;

                // ① 정책(ONNX) 롤아웃: 탐지 지점(현재 위치) → 목적지까지 전체 재계획
                // (useMlRolloutForObstacles=false면 건너뜀 — 특정 장애물에서 정책이 잘 회피 못할 때
                //  재학습 없이 즉시 ②/③ 결정론적 우회로 넘어가기 위한 임시 스위치)
                if (useMlRolloutForObstacles && _planner != null && plannerModel != null)
                {
                    Vector3 curPos  = SimToUnity(msg.position[0], msg.position[1]);
                    Vector3 destPos = (msg.destination != null && msg.destination.Length >= 2)
                        ? SimToUnity(msg.destination[0], msg.destination[1])
                        : (goalPoint != null ? goalPoint.position : curPos);
                    yield return StartCoroutine(RolloutFromTo(curPos, destPos, r => plan = r));
                }

                // ② 폴백: NavMesh 기하 우회
                if (plan == null && useNavMeshFallback)
                {
                    yield return null;   // 장애물 카빙 반영 대기
                    yield return null;
                    plan = ComputeNavMeshWaypoints(msg);
                    if (plan != null)
                        Debug.Log($"[DigitalTwin] NavMesh 폴백 경로: {plan.Length}개 웨이포인트");
                }

                // ③ 최종 폴백: 결정론적 기하 우회 (학습/NavMesh 베이크 여부와 무관하게 항상 동작)
                if (plan == null && useRightBypassFallback)
                {
                    plan = ComputeRightBypassWaypoints(msg);
                    if (plan != null)
                        Debug.Log($"[DigitalTwin] 결정론적 우회 폴백 경로: {plan.Length}개 웨이포인트");
                }

                if (plan != null)
                {
                    outWaypoints     = plan;
                    replanned        = true;
                    _cachedPlan      = plan;
                    _lastObstacleKey = obsKey;
                }
                else
                {
                    outWaypoints = GetRemainingWaypoints(msg);
                    Debug.LogWarning("[DigitalTwin] 경로 재계획 실패 → 기존 경로 유지");
                }
            }
        }
        else
        {
            // 장애물 없음 또는 경로를 막지 않음 → 캐시 초기화, 기존 경로 유지
            _lastObstacleKey = null;
            _cachedPlan      = null;
            outWaypoints     = GetRemainingWaypoints(msg);
        }

        // ── 4. twin_ack 응답 생성 & 송신 큐 ──────────────────────────────────
        // 롤아웃으로 보트가 이동했을 수 있으므로 표시 트윈을 실제 위치로 즉시 복원
        // (씬 Boat를 표시+플래너 겸용할 때 virtual_position 오차 방지, 글라이드 없이 스냅)
        SyncBoatPosition(msg, smooth: false);

        Vector3 vpos = boatObject != null
            ? boatObject.transform.position
            : SimToUnity(msg.position[0], msg.position[1]);

        // 목적지 도착 판정 (vpos = 실제 미러 위치, destination = Pyjevsim [x,y])
        string status = "ok";
        if (msg.destination != null && msg.destination.Length >= 2)
        {
            float destDist = Vector2.Distance(
                new Vector2(vpos.x, vpos.z),
                new Vector2(msg.destination[0], msg.destination[1]));
            if (destDist <= arrivalDistanceM)
            {
                status = "arrived";
                Debug.Log($"[DigitalTwin] 목적지 도착 → status=arrived "
                        + $"(dist={destDist:F1}m ≤ {arrivalDistanceM}m)");
            }
        }

        TwinAckMessage ack = new TwinAckMessage
        {
            platform_name    = msg.platform_name,
            virtual_position = new float[] { vpos.x, vpos.z, 0f },  // Unity XZ → Sim XY
            waypoints        = outWaypoints,
            replanned        = replanned,
            status           = status
        };

        _sendQueue.Enqueue(JsonConvert.SerializeObject(ack));
        _sendReady.Release();
    }

    // ── 위치 동기화 ───────────────────────────────────────────────────────────

    // smooth=true(기본): 다음 sim_tick까지 부드럽게 보간 이동(글라이드) 시작.
    // smooth=false: 롤아웃으로 흐트러진 표시 트윈을 즉시 원위치로 복원할 때 사용(글라이드 없이 스냅).
    private void SyncBoatPosition(SimTickMessage msg, bool smooth = true)
    {
        if (boatObject == null) return;

        Vector3 target = SimToUnity(msg.position[0], msg.position[1]);

        // 이동 방향으로 헤딩 계산 (BowDir=transform.right 기준, RolloutFromTo와 동일한 변환식)
        Quaternion targetRot = boatObject.transform.rotation;
        float      tickDt    = 0f;
        if (_hasMirrorHistory)
        {
            Vector3 dir = target - _lastMirrorPos;
            dir.y = 0f;
            tickDt = Time.time - _lastMirrorTime;
            if (dir.sqrMagnitude > 0.0001f)
                targetRot = Quaternion.Euler(0f, Mathf.Atan2(-dir.z, dir.x) * Mathf.Rad2Deg, 0f);
        }
        _hasMirrorHistory = true;
        _lastMirrorPos    = target;
        _lastMirrorTime   = Time.time;

        if (!smooth)
        {
            // 롤아웃 후 복원 — 시각적으로 되감기는 모습이 보이면 안 되므로 글라이드 없이 즉시 스냅
            _mirrorGlideActive = false;
            ApplyMirrorTransform(target, targetRot);
            return;
        }

        // 이전 tick 간격만큼(min~max로 clamp) 부드럽게 이동 — 현재 화면상 위치/회전에서 시작해
        // 진행 중이던 글라이드가 있어도 끊기지 않고 자연스럽게 이어짐
        _mirrorFromPos       = boatObject.transform.position;
        _mirrorFromRot       = boatObject.transform.rotation;
        _mirrorToPos         = target;
        _mirrorToRot         = targetRot;
        _mirrorGlideDuration = Mathf.Clamp(tickDt, mirrorGlideMinSeconds, mirrorGlideMaxSeconds);
        _mirrorGlideStart    = Time.time;
        _mirrorGlideActive   = true;
    }

    // Rigidbody 있으면 MovePosition/MoveRotation(물리 충돌 보존), 없으면 직접 이동
    private void ApplyMirrorTransform(Vector3 pos, Quaternion rot)
    {
        var rb = boatObject.GetComponent<Rigidbody>();
        if (rb != null)
        {
            rb.linearVelocity  = Vector3.zero;
            rb.angularVelocity = Vector3.zero;
            rb.MovePosition(pos);
            rb.MoveRotation(rot);
        }
        else
        {
            boatObject.transform.position = pos;
            boatObject.transform.rotation = rot;
        }
    }

    // ── NavMesh 경로 계산 ─────────────────────────────────────────────────────

    private float[][] ComputeNavMeshWaypoints(SimTickMessage msg)
    {
        if (msg.waypoints == null || msg.waypoints.Length == 0) return null;

        int     idx       = Mathf.Clamp(msg.waypoint_idx, 0, msg.waypoints.Length - 1);
        float[] targetWp  = msg.waypoints[idx];
        Vector3 startPos  = boatObject != null
            ? boatObject.transform.position
            : SimToUnity(msg.position[0], msg.position[1]);
        Vector3 targetPos = SimToUnity(targetWp[0], targetWp[1]);

        if (!NavMesh.SamplePosition(startPos,  out NavMeshHit sh, navMeshSampleRadius, NavMesh.AllAreas) ||
            !NavMesh.SamplePosition(targetPos, out NavMeshHit th, navMeshSampleRadius, NavMesh.AllAreas))
            return null;

        NavMeshPath path = new NavMeshPath();
        if (!NavMesh.CalculatePath(sh.position, th.position, NavMesh.AllAreas, path))
            return null;
        if (path.status != NavMeshPathStatus.PathComplete || path.corners.Length < 2)
            return null;

        // NavMesh 코너 → Pyjevsim 좌표 ([x, z] → [simX, simY])
        var result = new List<float[]>();
        // 시작점(corners[0])은 현재 위치라 스킵, corners[1]부터 추가
        for (int i = 1; i < path.corners.Length; i++)
            result.Add(new float[] { path.corners[i].x, path.corners[i].z });

        // 나머지 원래 웨이포인트 추가
        for (int i = idx + 1; i < msg.waypoints.Length; i++)
            result.Add(msg.waypoints[i]);

        return result.Count > 0 ? result.ToArray() : null;
    }

    // ── 결정론적 기하 우회 (ML/NavMesh 모두 실패했을 때 최종 안전망) ────────────
    // 학습된 정책이 특정 배치의 장애물을 잘 피하지 못할 때, 재학습 없이 즉시 쓸 수 있는
    // "장애물 옆(우측 기본)으로 한 점 찍고 목적지로" 방식의 단순하고 예측 가능한 우회.
    private float[][] ComputeRightBypassWaypoints(SimTickMessage msg)
    {
        if (msg.detected_obstacles == null || msg.detected_obstacles.Length == 0)
            return null;

        Vector2 curPos = new Vector2(msg.position[0], msg.position[1]);
        Vector2 dest;
        if (msg.destination != null && msg.destination.Length >= 2)
            dest = new Vector2(msg.destination[0], msg.destination[1]);
        else if (msg.waypoints != null && msg.waypoints.Length > 0)
        {
            float[] last = msg.waypoints[msg.waypoints.Length - 1];
            dest = new Vector2(last[0], last[1]);
        }
        else return null;

        // 현재 위치에서 가장 가까운(가장 위협적인) 장애물 하나를 기준으로 우회
        float   bestDist = float.MaxValue;
        Vector2 obsPos   = curPos;
        bool    found    = false;
        foreach (var obs in msg.detected_obstacles)
        {
            if (obs == null || obs.Length < 2) continue;
            Vector2 op = new Vector2(obs[0], obs[1]);
            float   d  = Vector2.Distance(curPos, op);
            if (d < bestDist) { bestDist = d; obsPos = op; found = true; }
        }
        if (!found) return null;

        Vector2 travelDir = dest - curPos;
        if (travelDir.sqrMagnitude < 0.01f) return null;
        travelDir.Normalize();

        // 진행방향 기준 우측 수직 벡터 (bypassPreferRight=false면 좌측으로 반전)
        Vector2 rightPerp = new Vector2(travelDir.y, -travelDir.x);
        if (!bypassPreferRight) rightPerp = -rightPerp;

        Vector2 bypass = obsPos + rightPerp * (bypassObstacleRadius + bypassMargin);

        return new float[][]
        {
            new float[] { bypass.x, bypass.y },
            new float[] { dest.x,   dest.y   }
        };
    }

    // ── 정책(ONNX) 롤아웃: startPos → goalPos 전체 경로 생성 ────────────────────
    // Phase 0(초기 경로)·Phase 4(장애물 재계획) 공용. 현재 씬의 장애물을 그대로 반영.

    private IEnumerator RolloutFromTo(Vector3 startPos, Vector3 goalPos,
                                      System.Action<float[][]> onComplete)
    {
        if (_planner == null || plannerModel == null) { onComplete(null); yield break; }

        // 초기 heading: BowDir(=transform.right)을 목표 방향으로 정렬
        Vector3    dir     = goalPos - startPos; dir.y = 0f;
        Quaternion startRot = _planner.transform.rotation;
        if (dir.sqrMagnitude > 0.01f)
            startRot = Quaternion.Euler(0f, Mathf.Atan2(-dir.z, dir.x) * Mathf.Rad2Deg, 0f);

        // 목표/모델/추론 모드 설정
        _plannerGoal.position = goalPos;
        if (_plannerBp != null)
        {
            _plannerBp.Model        = plannerModel;
            _plannerBp.BehaviorType = BehaviorType.InferenceOnly;
        }

        // 롤아웃 동안은 같은 오브젝트(표시+플래너 겸용)를 정책 물리가 직접 움직이므로
        // 미러 글라이드가 매 프레임 MovePosition으로 끼어들어 충돌하지 않도록 비활성화
        _mirrorGlideActive = false;
        _planner.BeginPlanningRollout(startPos, startRot, _plannerGoal);

        // 롤아웃 스텝 & 궤적 기록 (timeScale 가속)
        var   traj    = new List<Vector3> { startPos };
        float simTime = 0f;
        float oldScale = Time.timeScale;
        Time.timeScale = Mathf.Max(1f, rolloutTimeScale);

        float arrival  = _planner.goalArrivalDistance;
        bool  reached  = false;
        bool  collided = false;

        while (simTime < rolloutMaxSeconds)
        {
            yield return new WaitForFixedUpdate();
            simTime += Time.fixedDeltaTime;

            Vector3 p = _planner.transform.position;
            traj.Add(p);

            if (Vector2.Distance(new Vector2(p.x, p.z), new Vector2(goalPos.x, goalPos.z)) <= arrival)
            { reached = true; break; }

            if (_planner.EpisodeEnded) { collided = true; break; }  // 충돌/경계 이탈
        }

        Time.timeScale = oldScale;
        _planner.StopPlanningRollout();
        if (_plannerBp != null) _plannerBp.BehaviorType = BehaviorType.HeuristicOnly;

        // 충돌로 목표 미도달 → 폴백 유도
        if (collided && !reached)
        {
            Debug.LogWarning($"[DigitalTwin] 롤아웃 충돌/이탈 (t={simTime:F1}s) → 폴백 시도");
            onComplete(null);
            yield break;
        }

        float[][] wp = TrajectoryToWaypoints(traj, goalPos);
        Debug.Log($"[DigitalTwin] 정책 롤아웃 완료: {wp.Length}개 웨이포인트 "
                + $"(reached={reached}, t={simTime:F1}s ×{rolloutTimeScale})");
        onComplete(wp);
    }

    // 궤적 → 간격 기준 다운샘플 웨이포인트 (목적지까지 전체 경로)
    private float[][] TrajectoryToWaypoints(List<Vector3> traj, Vector3 goalPos)
    {
        var pts = new List<float[]>();

        if (traj.Count > 0)
        {
            Vector2 last = new Vector2(traj[0].x, traj[0].z);  // 시작점은 현재 위치 → 스킵
            for (int i = 1; i < traj.Count; i++)
            {
                Vector2 cur = new Vector2(traj[i].x, traj[i].z);
                if (Vector2.Distance(cur, last) >= waypointSpacingM)
                {
                    pts.Add(new float[] { traj[i].x, traj[i].z });
                    last = cur;
                }
            }
        }

        // 목적지 보장
        pts.Add(new float[] { goalPos.x, goalPos.z });

        return pts.ToArray();
    }

    // 장애물 집합 식별 키 (1m 반올림) — 동일하면 재롤아웃 생략
    private static string ObstacleKey(float[][] obs)
    {
        if (obs == null || obs.Length == 0) return "";
        var sb = new StringBuilder();
        foreach (var o in obs)
        {
            if (o == null || o.Length < 2) continue;
            sb.Append(Mathf.RoundToInt(o[0])).Append(',')
              .Append(Mathf.RoundToInt(o[1])).Append(';');
        }
        return sb.ToString();
    }

    // 탐지된 장애물이 남은 경로(현재 위치 → remaining waypoints)를 실제로 막고 있는지 판단.
    // '탐지됨'과 '막고 있음'을 분리해 경로에서 벗어난 장애물까지 매번 재롤아웃하는 것을 방지.
    private bool IsPathBlocked(SimTickMessage msg)
    {
        if (msg.detected_obstacles == null || msg.detected_obstacles.Length == 0)
            return false;

        // 남은 경로 정보가 없으면 판단 불가 → 안전하게 '막힘'으로 간주해 재계획 유도
        if (msg.waypoints == null || msg.waypoints.Length == 0)
            return true;

        var pathPts = new List<Vector2> { new Vector2(msg.position[0], msg.position[1]) };
        int idx = Mathf.Clamp(msg.waypoint_idx, 0, msg.waypoints.Length - 1);
        for (int i = idx; i < msg.waypoints.Length; i++)
        {
            if (msg.waypoints[i] == null || msg.waypoints[i].Length < 2) continue;
            pathPts.Add(new Vector2(msg.waypoints[i][0], msg.waypoints[i][1]));
        }

        foreach (var obs in msg.detected_obstacles)
        {
            if (obs == null || obs.Length < 2) continue;
            Vector2 op = new Vector2(obs[0], obs[1]);

            for (int i = 0; i < pathPts.Count - 1; i++)
            {
                float d = DistancePointToSegment(op, pathPts[i], pathPts[i + 1]);
                if (d <= obstacleBlockRadius)
                    return true;
            }
        }
        return false;
    }

    private static float DistancePointToSegment(Vector2 p, Vector2 a, Vector2 b)
    {
        Vector2 ab    = b - a;
        float   lenSq = ab.sqrMagnitude;
        if (lenSq < 1e-6f) return Vector2.Distance(p, a);

        float   t    = Mathf.Clamp01(Vector2.Dot(p - a, ab) / lenSq);
        Vector2 proj = a + ab * t;
        return Vector2.Distance(p, proj);
    }

    // ── COLREGS Agent 목표 갱신 ───────────────────────────────────────────────

    private void UpdateColregsAgentGoal(SimTickMessage msg)
    {
        if (pathAgent == null || msg.destination == null || msg.destination.Length < 2)
            return;

        var boatAgent = pathAgent as BoatColregAgent;
        if (boatAgent?.goalTransform == null) return;

        boatAgent.goalTransform.position = SimToUnity(msg.destination[0], msg.destination[1]);
    }

    // ── 장애물 관리 ───────────────────────────────────────────────────────────

    // 탐지된 장애물을 부표로 표시. 한 번 표시된 부표는 센서 범위를 벗어나 detected_obstacles에서
    // 빠지더라도 지우지 않고 시나리오가 끝날 때까지 유지 (ClearObstacles에서만 정리).
    private void SpawnObstacles(float[][] positions)
    {
        if (positions == null || positions.Length == 0 || obstaclePrefab == null)
            return;

        foreach (var obs in positions)
        {
            if (obs == null || obs.Length < 2) continue;

            string key = ObstaclePointKey(obs);
            if (_obstacleRegistry.ContainsKey(key)) continue;  // 이미 표시됨 — 유지

            Vector3 pos = SimToUnity(obs[0], obs[1]);
            pos.y = 0f;

            GameObject go = Instantiate(obstaclePrefab, pos, Quaternion.identity);
            go.name       = $"DT_Obs_{obs[0]:F0}_{obs[1]:F0}";
            go.SetActive(true);

            // 플래너 에이전트 레이어로 설정 → 정책 레이캐스트(mask=1<<layer) 감지 + 충돌
            if (_planner != null)
                SetLayerRecursive(go, _plannerLayer);

            _obstacleRegistry[key] = go;
        }
    }

    private static string ObstaclePointKey(float[] obs) =>
        $"{Mathf.RoundToInt(obs[0])},{Mathf.RoundToInt(obs[1])}";

    // 새 시나리오 시작 시에만 호출 — 이전 에피소드의 부표를 전부 정리
    private void ClearObstacles()
    {
        foreach (var go in _obstacleRegistry.Values)
            if (go != null) Destroy(go);
        _obstacleRegistry.Clear();
    }

    // ── 헬퍼 ─────────────────────────────────────────────────────────────────

    private float[][] GetRemainingWaypoints(SimTickMessage msg)
    {
        if (msg.waypoints == null) return new float[0][];
        int idx = Mathf.Clamp(msg.waypoint_idx, 0, msg.waypoints.Length);
        var rem = new float[msg.waypoints.Length - idx][];
        for (int i = idx; i < msg.waypoints.Length; i++)
            rem[i - idx] = msg.waypoints[i];
        return rem;
    }

    private void EnqueueErrorAck()
    {
        var ack = new TwinAckMessage
        {
            platform_name    = "unknown",
            virtual_position = new float[] { 0f, 0f, 0f },
            waypoints        = new float[0][],
            replanned        = false,
            status           = "ok"
        };
        _sendQueue.Enqueue(JsonConvert.SerializeObject(ack));
        _sendReady.Release();
    }

    // ── 좌표 변환 (Pyjevsim XY ↔ Unity XZ) ──────────────────────────────────

    private static Vector3 SimToUnity(float simX, float simY)
        => new Vector3(simX, 0f, simY);

    // ── 런타임 오브젝트 생성 ─────────────────────────────────────────────────

    // ── 지나온 경로(LineRenderer) ────────────────────────────────────────────

    private void SetupTraveledPathRenderer()
    {
        if (traveledPathRenderer == null)
        {
            var go = new GameObject("DT_TraveledPath");
            traveledPathRenderer = go.AddComponent<LineRenderer>();
        }

        traveledPathRenderer.positionCount   = 0;
        traveledPathRenderer.widthMultiplier = traveledPathWidth;
        traveledPathRenderer.useWorldSpace   = true;
        traveledPathRenderer.numCapVertices    = 4;
        traveledPathRenderer.numCornerVertices = 2;
        traveledPathRenderer.startColor = traveledPathColor;
        traveledPathRenderer.endColor   = traveledPathColor;

        if (traveledPathRenderer.sharedMaterial == null)
        {
            var shader = Shader.Find("Universal Render Pipeline/Unlit")
                      ?? Shader.Find("Unlit/Color")
                      ?? Shader.Find("Standard");
            var mat = new Material(shader) { color = traveledPathColor };
            traveledPathRenderer.material = mat;
        }
    }

    // sim_tick의 실위치를 지나온 경로에 기록 (직전 점에서 일정 거리 이상 이동했을 때만 추가)
    private void RecordTraveledPoint(SimTickMessage msg)
    {
        if (traveledPathRenderer == null) return;

        Vector3 p = SimToUnity(msg.position[0], msg.position[1]);
        p.y = 0.05f;  // 수면 위로 살짝 띄워서 z-fighting 방지

        if (_traveledPoints.Count > 0 &&
            Vector3.Distance(_traveledPoints[_traveledPoints.Count - 1], p) < traveledPathMinPointDistance)
            return;

        _traveledPoints.Add(p);
        traveledPathRenderer.positionCount = _traveledPoints.Count;
        traveledPathRenderer.SetPosition(_traveledPoints.Count - 1, p);
    }

    // 새 시나리오 시작 시 이전 에피소드의 경로 지우기
    private void ClearTraveledPath()
    {
        _traveledPoints.Clear();
        if (traveledPathRenderer != null)
            traveledPathRenderer.positionCount = 0;
    }

    private GameObject CreateVirtualBoat()
    {
        // 단순 시각화용 보트 모양 오브젝트
        var root  = new GameObject("DT_VirtualBoat");
        var body  = GameObject.CreatePrimitive(PrimitiveType.Cube);
        body.transform.SetParent(root.transform);
        body.transform.localScale    = new Vector3(3f, 1f, 6f);
        body.transform.localPosition = Vector3.zero;

        Destroy(body.GetComponent<Collider>());

        var rend = body.GetComponent<Renderer>();
        if (rend != null)
        {
            var mat = new Material(
                Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("Unlit/Color") ?? Shader.Find("Standard"));
            mat.color = new Color(0.2f, 0.6f, 1f, 0.85f);
            rend.material = mat;
        }

        Debug.Log("[DigitalTwin] 가상 Boat 자동 생성: DT_VirtualBoat");
        return root;
    }

    private GameObject CreateDefaultObstaclePrefab()
    {
        // 기본 장애물 템플릿:
        //  - Collider 유지 → 정책 레이캐스트 감지 + 물리 충돌 (정책 롤아웃용)
        //  - NavMeshObstacle 카빙 → NavMesh 폴백 우회용
        var go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        go.name = "_DT_ObstacleTemplate";
        go.transform.localScale = new Vector3(3f, 0.5f, 3f);
        go.SetActive(false);  // 인스턴스 생성 시 SetActive(true)

        // Collider는 유지 (정책 회피 감지에 필수). 트리거 아님 → OnCollisionEnter 발생.
        var col = go.GetComponent<Collider>();
        if (col != null) col.isTrigger = false;

        var rend = go.GetComponent<Renderer>();
        if (rend != null)
        {
            var mat = new Material(
                Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("Unlit/Color") ?? Shader.Find("Standard"));
            mat.color = new Color(1f, 0.3f, 0.1f, 0.8f);
            rend.material = mat;
        }

        var navObs = go.AddComponent<NavMeshObstacle>();
        navObs.shape              = NavMeshObstacleShape.Capsule;
        navObs.radius             = 1.5f;
        navObs.height             = 1f;
        navObs.carving            = true;
        navObs.carveOnlyStationary = false;

        return go;
    }

    private static void SetLayerRecursive(GameObject obj, int layer)
    {
        obj.layer = layer;
        foreach (Transform t in obj.GetComponentsInChildren<Transform>(true))
            t.gameObject.layer = layer;
    }
}
