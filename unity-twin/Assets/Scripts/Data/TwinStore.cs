// Assets/Scripts/Data/TwinStore.cs
//
// 봉투를 받아 entity 별로 보관하는 곳. **씬은 여기만 읽는다.**
//
// ── 이 파일이 지키는 계약 (전부 계약이지 구현 선택이 아니다)
//
//  1. **상태 3층 원본을 각각 보관한다** (REQ-205 / VZ-U-01). 표시값은 StatusModel 이 파생한다.
//  2. **stale 을 다시 계산하지 않는다.** availability 는 서버가 판정해 봉투에 실어 준 값이다.
//  3. **좌표를 변환하지 않는다** (BE-C-04 · DT-03). 받은 전역 좌표를 그대로 담고,
//     coordinate_frame 은 읽어서 표시만 한다.
//  4. **집약 표기와 원천 종류 표기를 읽는다** (VZ-C-03 · VZ-C-06). 값에 집약 연산을 다시 걸지 않는다.
//  5. **미배포 대상도 레지스트리를 근거로 존재한다** (VZ-I-03). robot-03 은 값을 한 번도
//     발행하지 않지만 여기 목록에 있고, 씬에도 있다.
//  6. **권한 범위 밖 대상을 지우지 않는다** (VZ-C-04). 구분해서 표시할 뿐이다 —
//     조작을 막는 것과 존재를 숨기는 것은 다르다.
//
// ── 씬 오브젝트를 알지 못한다
//
// 여기에는 GameObject·Transform 이 하나도 없다. 씬이 저장소를 읽는 방향은 있어도
// 저장소가 씬을 읽는 방향은 없다 — 그래야 "씬 안의 오브젝트가 서로의 Transform 을 읽는"
// 지름길이 애초에 만들어지지 않는다. 위치는 오직 수신한 봉투에서만 온다.

using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using HybridDt.Twin.Transport;

namespace HybridDt.Twin.Data
{
    public sealed class EntityState
    {
        public string Id;
        public string Node;
        public string Zone;
        public string EntityType;
        /// <summary>display_name 이 있으면 그것, 없으면 id (VZ-I-03).</summary>
        public string DisplayName;
        public List<string> Aliases = new List<string>();
        public string RegistryNote;

        /// <summary>**3층 원본.** 단일 값으로 뭉치지 않는다. null 이면 상태 봉투를 아직 못 받았다.</summary>
        public StateLayersWire Layers;
        /// <summary>마지막 상태 봉투의 **서버 시각**. 최근 수신 경과 계산에 쓴다.</summary>
        public string StateEnvelopeTs;

        /// <summary>VZ-U-01 — 액추에이터 도메인 어휘. 표준 3층과 별개다.</summary>
        public ActuatorStateWire Actuator;

        /// <summary>VZ-C-03 — 마지막으로 받은 값의 집약 표기.</summary>
        public AggregationSpec Aggregation = AggregationSpec.Raw();
        /// <summary>VZ-C-06 — 마지막으로 받은 봉투의 원천 종류. **기본은 Unknown 이다.**</summary>
        public OriginKindSpec Origin = OriginKindSpec.NotLabelled();

        /// <summary>BE-C-04 — 받은 좌표의 기준계 표기. **읽어서 표시만 한다.**</summary>
        public string CoordinateFrame;

        public readonly PoseBuffer Pose = new PoseBuffer();

        /// <summary>VZ-C-04 — 권한 범위 안인가. 범위 밖이어도 씬에서 지우지 않는다.</summary>
        public bool InScope = true;

        /// <summary>진단용 — 이 대상으로 들어온 봉투 수.</summary>
        public long EnvelopeCount;
        /// <summary>씬 반영이 필요한가. 병합 창이 열릴 때 한 번에 처리된다.</summary>
        public bool Dirty = true;

        // 이름표에 얹는 부수 정보. 없으면 표시하지 않는다.
        public double? BatteryPct;
        public bool IsMoving;

        public DisplayStatus Status { get { return StatusModel.Derive(Layers); } }

        /// <summary>
        /// 보간 정지 임계 (ms). **서버가 준 값을 그대로 쓴다** — 뷰어가 임의 상수를 새로 만들지 않는다.
        /// 상태 봉투를 아직 못 받았으면 hello 의 값으로 대체한다.
        /// </summary>
        public double StaleThresholdMs = 60000;

        /// <summary>availability 가 stale·offline 이면 참. **서버 판정이 우선이다.**</summary>
        public bool ServerSaysNotCurrent
        {
            get
            {
                if (Layers == null) return true;
                return Layers.Availability == "stale" || Layers.Availability == "offline";
            }
        }
    }

    public sealed class TwinStore
    {
        private readonly Dictionary<string, EntityState> _entities = new Dictionary<string, EntityState>();
        private readonly List<EntityState> _ordered = new List<EntityState>();

        public Registry Registry { get; private set; }
        public string RegistryError { get; private set; }
        public RoleInfoWire Role { get; private set; }
        /// <summary>hello 가 준 임계. 상태 봉투가 오기 전 구간의 대체값이다.</summary>
        public double ServerStaleThresholdMs = 60000;

        public IReadOnlyList<EntityState> Entities { get { return _ordered; } }

        public EntityState Find(string id)
        {
            EntityState s;
            return _entities.TryGetValue(id, out s) ? s : null;
        }

        /// <summary>
        /// VZ-I-03 — 레지스트리로 존재 목록을 세운다.
        /// **값이 한 번도 안 온 대상도 여기서 생긴다.** 이것이 '의도적 미배포'를 그릴 수 있는 근거다.
        /// </summary>
        public void SetRegistry(Registry registry, string error)
        {
            Registry = registry ?? new Registry();
            RegistryError = error;

            foreach (RegistryEntity e in Registry.Entities)
            {
                EntityState s;
                if (!_entities.TryGetValue(e.Id, out s))
                {
                    s = new EntityState { Id = e.Id };
                    _entities[e.Id] = s;
                    _ordered.Add(s);
                }
                s.Node = e.Node;
                s.Zone = e.Zone;
                s.EntityType = e.EntityType;
                s.DisplayName = string.IsNullOrEmpty(e.DisplayName) ? e.Id : e.DisplayName;
                s.Aliases = e.Aliases ?? new List<string>();
                s.RegistryNote = e.Note;
                s.StaleThresholdMs = ServerStaleThresholdMs;
                s.Dirty = true;
            }

            ApplyScope();
        }

        /// <summary>
        /// VZ-C-04 / BE-Q-04 — 역할이 적용되는 범위를 반영한다.
        /// **화면 구분은 편의이고 실제 강제는 백엔드다.** 그래서 여기서는 표시 구분만 세우고,
        /// 범위 밖 대상을 목록에서 빼지 않는다.
        /// </summary>
        public void SetRole(RoleInfoWire role)
        {
            Role = role;
            ApplyScope();
        }

        private void ApplyScope()
        {
            foreach (EntityState s in _ordered)
            {
                bool inScope = true;
                if (Role != null && Role.Scope != null && Role.Scope.Zones != null && Role.Scope.Zones.Count > 0)
                {
                    inScope = Role.Scope.Zones.Contains("*") || (s.Zone != null && Role.Scope.Zones.Contains(s.Zone));
                }
                if (s.InScope != inScope)
                {
                    s.InScope = inScope;
                    s.Dirty = true;
                }
            }
        }

        /// <summary>
        /// 봉투 1건 적재. **매 수신마다 호출된다** — 병합되는 것은 씬 반영이지 수신이 아니다.
        /// </summary>
        /// <param name="localTime">로컬 단조 시각(초). 보간 재생 전용이며 상태 판정에 쓰지 않는다.</param>
        /// <returns>씬에 즉시 반영해야 하는 전이였는가 (offline·stale 진입).</returns>
        public bool Apply(Envelope env, double localTime)
        {
            if (env == null || env.Entity == null) return false;

            EntityState s = Find(env.Entity);
            if (s == null)
            {
                // 레지스트리에 없는 대상이 값을 보냈다. **버리지 않고 만든다** —
                // "명단에 없는데 말하고 있다"는 것 자체가 관제가 알아야 할 사실이고,
                // 조용히 무시하면 통합 때 원인 모를 누락으로 나타난다.
                s = new EntityState
                {
                    Id = env.Entity,
                    Node = env.Node,
                    Zone = env.Zone,
                    EntityType = "unregistered",
                    DisplayName = env.Entity,
                    RegistryNote = "레지스트리에 없는 대상이 값을 발행했다 (VZ-I-03 불일치)",
                    StaleThresholdMs = ServerStaleThresholdMs,
                };
                _entities[env.Entity] = s;
                _ordered.Add(s);
            }

            s.EnvelopeCount++;
            s.Dirty = true;

            // VZ-C-03 — 표기를 읽는다. 값에 평균·합계를 다시 적용하지 않는다.
            s.Aggregation = Aggregation.Normalize(env.Aggregation);

            // VZ-C-06 — 표기가 없으면 raw 처럼 통과시키지 않고 Unknown 으로 둔다.
            JToken originToken;
            bool present = env.TryGetExtra(OriginKinds.EnvelopeField, out originToken);
            s.Origin = OriginKinds.Normalize(originToken, present);

            // BE-C-04 — 좌표계 표기는 읽어서 표시만 한다.
            if (env.CoordinateFrame != null) s.CoordinateFrame = env.CoordinateFrame;

            bool immediate = false;

            switch (env.Channel)
            {
                case "state":
                {
                    StateLayersWire layers = env.Payload == null ? null : env.Payload.ToObject<StateLayersWire>();
                    string before = s.Layers == null ? null : s.Layers.Availability;
                    s.Layers = layers;
                    s.StateEnvelopeTs = env.Ts;
                    if (layers != null) s.StaleThresholdMs = layers.StaleThresholdMs;

                    string after = layers == null ? null : layers.Availability;
                    // 끊김을 100ms 늦게 아는 것은 상관없지만, 규칙을 코드에 남겨 둔다.
                    if (after != before && (after == "offline" || after == "stale")) immediate = true;
                    break;
                }

                case "telemetry":
                {
                    ApplyTelemetry(s, env, localTime);
                    break;
                }

                case "actuator_state":
                {
                    s.Actuator = env.Payload == null ? null : env.Payload.ToObject<ActuatorStateWire>();
                    break;
                }

                // heartbeat·metrics 등은 뷰어가 그리지 않는다. 수신은 하되 담지 않는다.
                default:
                    break;
            }

            return immediate;
        }

        /// <summary>
        /// 좌표 적재. **변환하지 않는다** — payload 의 값은 백엔드가 이미 전역으로 바꾼 것이고,
        /// 손잡이(왼손/오른손) 보정은 표현 계층인 View/FrameConvert 한 곳에서만 일어난다.
        /// </summary>
        private static void ApplyTelemetry(EntityState s, Envelope env, double localTime)
        {
            if (env.Payload == null || env.Payload.Type != JTokenType.Object) return;
            JObject p = (JObject)env.Payload;

            JToken posToken = p["position"];
            if (posToken != null && posToken.Type == JTokenType.Object)
            {
                PositionWire pos = posToken.ToObject<PositionWire>();
                s.Pose.Push(pos.X, pos.Y, pos.Z, pos.Frame ?? env.CoordinateFrame, env.Seq, localTime);
                if (pos.Frame != null) s.CoordinateFrame = pos.Frame;
            }

            JToken battery = p["battery_pct"];
            if (battery != null && (battery.Type == JTokenType.Float || battery.Type == JTokenType.Integer))
                s.BatteryPct = battery.Value<double>();

            JToken moving = p["is_moving"];
            if (moving != null && moving.Type == JTokenType.Boolean) s.IsMoving = moving.Value<bool>();
        }

        /// <summary>씬 상태 요약. 진단 오버레이가 읽는다.</summary>
        public void CountByStatus(out int normal, out int fault, out int notDeployed, out int unknown)
        {
            normal = fault = notDeployed = unknown = 0;
            foreach (EntityState s in _ordered)
            {
                switch (s.Status)
                {
                    case DisplayStatus.Normal: normal++; break;
                    case DisplayStatus.Fault: fault++; break;
                    case DisplayStatus.NotDeployed: notDeployed++; break;
                    default: unknown++; break;
                }
            }
        }

        public void CountByOrigin(out int real, out int simulated, out int replay, out int unknown)
        {
            real = simulated = replay = unknown = 0;
            foreach (EntityState s in _ordered)
            {
                switch (s.Origin.Kind)
                {
                    case OriginKind.Real: real++; break;
                    case OriginKind.Simulated: simulated++; break;
                    case OriginKind.Replay: replay++; break;
                    default: unknown++; break;
                }
            }
        }
    }
}
