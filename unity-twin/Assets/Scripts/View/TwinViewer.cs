// Assets/Scripts/View/TwinViewer.cs
//
// VZ-U-02 — 디지털 트윈 위치 렌더링. **빈 씬의 GameObject 하나에 이 컴포넌트만 붙이면**
// 나머지(카메라·바닥·대상·이름표·마커)는 코드가 만든다. 프리팹이 없으면 프리미티브로 대체한다.
//
// ── 이번 범위는 뷰어뿐이다
//
// 이 파일에도, 이 저장소의 unity-twin 어디에도 **값을 만드는 경로가 없다.** 물리·이동
// 로직·가짜 값 생성은 전부 2단계이고, 제어 명령 발행은 웹 대시보드가 한다. 씬에 보이는
// 모든 위치는 목 게이트웨이에서 받은 봉투에서 온다.
//
// ── 두 리듬을 분리한다
//
//   씬 상태 반영 : 100ms 병합 (VZ-I-01) — 색·이름표·상태 표식. 초당 최대 10회.
//   보간 렌더    : 매 프레임 (VZ-U-02) — 위치. 60fps.
//
// 데이터는 전량 받는다. 병합되는 것은 **그리는 부하**이지 수신이 아니다.

using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using HybridDt.Twin.Data;
using HybridDt.Twin.Transport;
using HybridDt.Twin.Diagnostics;

namespace HybridDt.Twin.View
{
    public sealed class TwinViewer : MonoBehaviour, ITwinTransportSink
    {
        [Header("게이트웨이 접속 (하드코딩 금지 — 여기서 바꾼다)")]
        [Tooltip("목 게이트웨이 기본 포트는 8787. web-dashboard/.env.local 이 8788을 쓰고 있으면 그쪽에 맞춘다.")]
        public string gatewayWsUrl = "ws://127.0.0.1:8787";
        public string gatewayHttpUrl = "http://127.0.0.1:8787";

        [Header("손잡이 (합의 전 — README 참조)")]
        [Tooltip("켜면 수신 좌표를 오른손계로 보고 z 부호를 뒤집어 그린다. 기본값 OFF의 근거는 README.")]
        public bool flipHandedness = false;

        [Header("렌더 예산")]
        [Tooltip("씬 상태 반영 병합 창(ms). 보간 렌더는 이 창과 무관하게 매 프레임이다.")]
        public float sceneMergeWindowMs = 100f;

        [Header("씬 자동 구성 (에디터에서 직접 배치하면 꺼도 된다)")]
        public bool createCameraIfMissing = true;
        public bool createGround = true;
        public bool createLightIfMissing = true;
        public bool showDiagnostics = true;

        [Header("선택 — 프리팹. 비워 두면 프리미티브로 대체 생성한다")]
        public GameObject robotPrefab;
        public GameObject sensorPrefab;
        public GameObject cameraPrefab;
        public GameObject actuatorPrefab;
        public GameObject edgeNodePrefab;
        public GameObject defaultPrefab;

        [Header("선택 — 이름표 폰트. 한글이 네모로 보이면 한글 폰트를 넣는다")]
        public Font labelFont;

        // ── 내부 상태 ─────────────────────────────────────────────────────────

        private ITwinTransport _transport;
        private TwinStore _store;
        private MergeScheduler _merge;
        private SceneUpdateMeter _meter;
        private HandednessMarker _marker;
        private Transform _entityRoot;

        private readonly Dictionary<string, EntityView> _views = new Dictionary<string, EntityView>();
        private readonly List<string> _log = new List<string>();
        private bool _lastFlip;

        public TwinStore Store { get { return _store; } }
        public SceneUpdateMeter Meter { get { return _meter; } }
        public ConnectionStatus Connection { get { return _transport == null ? ConnectionStatus.Closed() : _transport.Status; } }
        public IReadOnlyList<string> Log { get { return _log; } }
        public int ViewCount { get { return _views.Count; } }

        // ── 수명 주기 ─────────────────────────────────────────────────────────

        private void Awake()
        {
            _store = new TwinStore();
            _merge = new MergeScheduler(sceneMergeWindowMs);
            _meter = new SceneUpdateMeter();
            _lastFlip = flipHandedness;

            _entityRoot = new GameObject("Entities").transform;
            _entityRoot.SetParent(transform, false);

            if (createGround) BuildGround();
#if UNITY_2023_1_OR_NEWER
            bool hasLight = FindAnyObjectByType<Light>() != null;
#else
            bool hasLight = FindObjectOfType<Light>() != null;
#endif
            if (createLightIfMissing && !hasLight) BuildLight();
            if (createCameraIfMissing && Camera.main == null) BuildCamera();

            if (showDiagnostics)
            {
                DiagnosticsOverlay overlay = gameObject.AddComponent<DiagnosticsOverlay>();
                overlay.viewer = this;
            }
        }

        private void Start()
        {
            StartCoroutine(Boot());
        }

        private IEnumerator Boot()
        {
            // ① 레지스트리 먼저 (VZ-I-03). **값이 한 번도 안 온 대상도 씬에 세우려면 이게 먼저다.**
            RegistryFetchResult result = new RegistryFetchResult();
            yield return RegistryFetcher.Fetch(gatewayHttpUrl, result);
            _store.SetRegistry(result.Registry, result.Error);
            Note(result.Error ?? ("레지스트리 " + result.Registry.Version + " — 대상 " + result.Registry.Entities.Count + "건"));

            BuildSceneFromRegistry();

            // ② 전송 연결. 구독은 **계약 축**으로만 표현한다 (VZ-I-01).
            _transport = new GatewayWebSocketTransport(gatewayWsUrl);
            _transport.Connect();

            // 구독 즉시 서버가 현재값을 1회 푸시한다 (VZ-I-02 / BE-T-06).
            // 이게 없으면 평시 센서는 최대 1분간 빈 자리로 남는다.
            _transport.Subscribe(new Selector("*", "*", "state"));
            _transport.Subscribe(new Selector("*", "*", "telemetry"));
            _transport.Subscribe(new Selector("*", "*", "actuator_state"));
            _transport.RequestRole();

        }

        private void Update()
        {
            if (_transport == null) return;

            double now = Time.unscaledTimeAsDouble;

            // ① 수신 배출. **전량 저장소에 들어간다** — 병합되는 것은 씬 반영뿐이다.
            _transport.Pump(this);

            // ② 손잡이 플래그가 바뀌었으면 자리·마커를 다시 잡는다 (검증 7).
            if (_lastFlip != flipHandedness)
            {
                _lastFlip = flipHandedness;
                RecomputeAnchors();
                if (_marker != null) _marker.EnsureFlip(flipHandedness);
                Note("손잡이 플래그 변경 — " + FrameConvert.Describe(flipHandedness));
            }

            // ③ 씬 상태 반영 — 100ms 병합 창 (VZ-I-01).
            if (_merge.TryFlush(now))
            {
                ApplySceneState();
                _meter.RecordSceneUpdate(now);
            }

            // ④ 보간 렌더 — 매 프레임 (VZ-U-02). 위 병합과 **다른 축**이다.
            foreach (KeyValuePair<string, EntityView> kv in _views)
            {
                kv.Value.RenderTick(now, flipHandedness);
            }

            _meter.RecordFrame(now);
        }

        private void OnDestroy()
        {
            if (_transport != null)
            {
                _transport.Dispose();
                _transport = null;
            }
        }

        // ── 씬 구성 ───────────────────────────────────────────────────────────

        private void BuildSceneFromRegistry()
        {
            // Node 원점의 전역 배치 (REQ-302). **변환은 백엔드가 끝냈고 여기서는 놓기만 한다.**
            foreach (RegistryNode node in _store.Registry.Nodes)
            {
                if (node.Origin == null || node.Origin.Position == null) continue;
                Vector3 p = FrameConvert.ToUnity(node.Origin.Position.X, node.Origin.Position.Y, node.Origin.Position.Z, flipHandedness);
                Quaternion r = node.Origin.Rotation == null
                    ? Quaternion.identity
                    : FrameConvert.YawToUnity(node.Origin.Rotation.YawDeg, flipHandedness);

                GameObject go = new GameObject("node:" + node.Id);
                go.transform.SetParent(transform, false);
                go.transform.SetPositionAndRotation(p, r);

                GameObject plate = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                plate.name = "Origin";
                Collider c = plate.GetComponent<Collider>();
                if (c != null) Destroy(c);
                plate.transform.SetParent(go.transform, false);
                plate.transform.localScale = new Vector3(3.4f, 0.008f, 3.4f);
                plate.GetComponent<Renderer>().sharedMaterial = StatusPalette.Get(StatusPalette.NodeOrigin, 0.18f);

                WorldLabel label = WorldLabel.Create(go.transform, new Vector3(0f, 0.2f, 0f), 0.15f, labelFont);
                label.SetText((string.IsNullOrEmpty(node.DisplayName) ? node.Id : node.DisplayName)
                    + "\n원점 " + (node.Origin.Frame ?? "(기준계 미표기)"));
                label.SetColor(new Color(0.75f, 0.82f, 0.95f));
            }

            // 대상 — **레지스트리에 있으면 값이 없어도 만든다** (VZ-I-03). robot-03 이 여기서 생긴다.
            foreach (EntityState s in _store.Entities) EnsureView(s);

            // 비대칭 마커. 계약 원점 근처에 세운다.
            _marker = HandednessMarker.Create(transform, Vector3.zero, labelFont, flipHandedness);
        }

        private void EnsureView(EntityState s)
        {
            if (_views.ContainsKey(s.Id)) return;
            EntityView view = EntityView.Create(_entityRoot, s, AnchorFor(s), PrefabFor(s.EntityType), labelFont);
            _views[s.Id] = view;
        }

        /// <summary>
        /// 좌표를 못 받은 대상을 놓을 자리.
        ///
        /// **좌표 변환이 아니다.** node 원점(전역, 백엔드가 준 값)에 같은 node 안에서
        /// 겹치지 않게 벌리는 **배치 오프셋**을 더한 것뿐이며, 값이 도착하는 순간
        /// 대상은 수신 좌표로 옮겨 간다. 이 오프셋을 좌표로 오인하지 않도록 자리 표식은
        /// 좌표가 없는 동안에만 뜬다(EntityView).
        /// </summary>
        private Vector3 AnchorFor(EntityState s)
        {
            RegistryNode node = _store.Registry.FindNode(s.Node);
            Vector3 origin = node == null || node.Origin == null || node.Origin.Position == null
                ? Vector3.zero
                : FrameConvert.ToUnity(node.Origin.Position.X, node.Origin.Position.Y, node.Origin.Position.Z, flipHandedness);

            int index = 0, count = 0;
            foreach (EntityState other in _store.Entities)
            {
                if (other.Node != s.Node) continue;
                if (other.Id == s.Id) index = count;
                count++;
            }
            if (count <= 0) count = 1;

            float angle = (Mathf.PI * 2f * index) / count;
            return origin + new Vector3(Mathf.Cos(angle) * 2.4f, 0f, Mathf.Sin(angle) * 2.4f);
        }

        private void RecomputeAnchors()
        {
            foreach (KeyValuePair<string, EntityView> kv in _views) kv.Value.SetAnchor(AnchorFor(kv.Value.State));

            foreach (RegistryNode node in _store.Registry.Nodes)
            {
                if (node.Origin == null || node.Origin.Position == null) continue;
                Transform t = transform.Find("node:" + node.Id);
                if (t == null) continue;
                t.SetPositionAndRotation(
                    FrameConvert.ToUnity(node.Origin.Position.X, node.Origin.Position.Y, node.Origin.Position.Z, flipHandedness),
                    node.Origin.Rotation == null ? Quaternion.identity : FrameConvert.YawToUnity(node.Origin.Rotation.YawDeg, flipHandedness));
            }
        }

        private GameObject PrefabFor(string entityType)
        {
            switch (entityType)
            {
                case "robot": return robotPrefab ?? defaultPrefab;
                case "sensor": return sensorPrefab ?? defaultPrefab;
                case "camera": return cameraPrefab ?? defaultPrefab;
                case "actuator": return actuatorPrefab ?? defaultPrefab;
                case "edge_node": return edgeNodePrefab ?? defaultPrefab;
                default: return defaultPrefab;
            }
        }

        /// <summary>씬 상태 반영. **더러운 것만** 건드린다.</summary>
        private void ApplySceneState()
        {
            foreach (EntityState s in _store.Entities)
            {
                if (!_views.ContainsKey(s.Id)) EnsureView(s);
                if (!s.Dirty) continue;
                s.Dirty = false;
                _views[s.Id].ApplySceneState();
            }
        }

        // ── ITwinTransportSink — **전부 메인 스레드에서 불린다** ─────────────────

        public void OnHello(HelloWire hello)
        {
            if (hello == null) return;
            // 표시와 보간 정지 임계로만 쓴다. **stale 판정 자체는 서버가 한다.**
            _store.ServerStaleThresholdMs = hello.StaleThresholdMs;
            Note("hello — protocol " + hello.Protocol + " · stale 임계 " + hello.StaleThresholdMs + "ms · 서버시각 " + hello.ServerTime);
        }

        public void OnSubscribed(string subId, Selector selector, int snapshotCount)
        {
            // VZ-I-02 — 이 숫자가 0이면 초기 스냅샷이 오지 않은 것이다. 검증 1이 보는 값.
            Note("구독 " + (selector == null ? subId : selector.ToString()) + " → 즉시 스냅샷 " + snapshotCount + "건");
        }

        public void OnEnvelope(Envelope envelope)
        {
            double now = Time.unscaledTimeAsDouble;
            bool immediate = _store.Apply(envelope, now);
            _meter.RecordEnvelope(now);

            // 끊김·정지 전이는 창을 건너뛴다. 나머지는 100ms 창에 묶인다.
            if (immediate) _merge.MarkImmediate(now);
            else _merge.Mark(now);
        }

        public void OnRole(RoleInfoWire role)
        {
            _store.SetRole(role);
            string zones = role == null || role.Scope == null ? "(범위 없음)" : string.Join(", ", role.Scope.Zones.ToArray());
            Note("역할 " + (role == null ? "?" : role.DisplayName) + " · 범위 " + zones + " (VZ-C-04)");
        }

        public void OnStatus(ConnectionStatus status)
        {
            Note("연결 — " + status.Describe() + (status.LastError == null ? "" : " · " + status.LastError));
        }

        public void OnTransportError(string message)
        {
            Note("오류 — " + message);
        }

        private void Note(string line)
        {
            _log.Insert(0, line);
            if (_log.Count > 12) _log.RemoveAt(_log.Count - 1);
            Debug.Log("[TwinViewer] " + line);
        }

        // ── 씬 보조물 ─────────────────────────────────────────────────────────

        private void BuildGround()
        {
            GameObject ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "Ground";
            ground.transform.SetParent(transform, false);
            ground.transform.position = new Vector3(26f, 0f, -4.5f);
            ground.transform.localScale = new Vector3(6f, 1f, 6f);
            Collider c = ground.GetComponent<Collider>();
            if (c != null) Destroy(c);
            ground.GetComponent<Renderer>().sharedMaterial = StatusPalette.Get(new Color(0.13f, 0.14f, 0.17f), 1f);
        }

        private void BuildLight()
        {
            GameObject go = new GameObject("Directional Light");
            go.transform.SetParent(transform, false);
            go.transform.rotation = Quaternion.Euler(48f, -30f, 0f);
            Light l = go.AddComponent<Light>();
            l.type = LightType.Directional;
            l.intensity = 1.05f;
        }

        private void BuildCamera()
        {
            GameObject go = new GameObject("Main Camera");
            go.tag = "MainCamera";
            Camera cam = go.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.06f, 0.07f, 0.09f);
            go.transform.position = new Vector3(26f, 16f, -26f);
            go.transform.rotation = Quaternion.Euler(32f, 0f, 0f);
            go.AddComponent<OrbitCamera>().target = new Vector3(26f, 0f, -4.5f);
        }

        private void OnValidate()
        {
            if (sceneMergeWindowMs < 16f) sceneMergeWindowMs = 16f;
        }
    }
}
