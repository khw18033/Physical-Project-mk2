// Assets/Scripts/Transport/Wire.cs
//
// 와이어 계약의 Unity 측 정의.
//
// **원본은 web-dashboard/mock-gateway/protocol.ts 다.** 이 파일은 그 계약을 C#으로
// 다시 적은 것이지 웹 코드를 옮긴 것이 아니다 — 프로세스 경계를 넘는 계약이므로
// 두 클라이언트가 각자의 언어로 같은 계약을 적는 편이 맞다. 계약이 바뀌면
// protocol.ts 와 이 파일 두 곳을 같이 고쳐야 하고, 그 사실을 잊지 않도록
// 각 타입에 요구사항 ID를 달아 둔다.
//
// 이 폴더 밖으로 나가는 것은 Envelope 과 몇 개의 payload 타입뿐이다.
// WebSocket·URL·재연결은 여기서 끝난다 (VZ-I-01).

using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace HybridDt.Twin.Transport
{
    /// <summary>
    /// 구독 축 (VZ-I-01 / REQ-704).
    /// **토픽 문자열을 조립하지 않는다.** 전송 규격이 바뀌어도 상위 코드가 안 깨지게 하는 것이
    /// 이 축의 존재 이유이므로, "entity/node/channel" 같은 문자열을 만드는 코드가
    /// 이 저장소 어디에도 있으면 안 된다.
    /// </summary>
    public sealed class Selector
    {
        [JsonProperty("entity")] public string Entity = "*";
        [JsonProperty("node")] public string Node = "*";
        [JsonProperty("channel")] public string Channel = "*";

        public Selector() { }

        public Selector(string entity, string node, string channel)
        {
            Entity = entity;
            Node = node;
            Channel = channel;
        }

        public override string ToString()
        {
            return "{entity=" + Entity + ", node=" + Node + ", channel=" + Channel + "}";
        }
    }

    /// <summary>
    /// 서버 → 클라이언트 봉투. 필드 구성은 고정이다.
    ///
    /// **origin_kind 를 선언 필드로 두지 않았다.** VZ-C-06 의 표기는 아직 계약에 없고,
    /// 지금 필요한 것은 "표기가 아예 없다"와 "표기가 있는데 못 읽는다"를 구분하는 능력이다.
    /// 선언 필드로 두면 둘 다 null 이 되어 구분이 사라진다. 그래서 확장 데이터로 받아
    /// 키의 존재 여부 자체를 읽는다 (<see cref="Extra"/>).
    /// </summary>
    public sealed class Envelope
    {
        [JsonProperty("zone")] public string Zone;
        [JsonProperty("node")] public string Node;
        [JsonProperty("entity")] public string Entity;
        [JsonProperty("channel")] public string Channel;

        /// <summary>**서버 시각** ISO-8601. 클라이언트 시계를 신뢰하지 않는다.</summary>
        [JsonProperty("ts")] public string Ts;

        /// <summary>대상×채널별 단조 증가 시퀀스. 유실·역전 감지용.</summary>
        [JsonProperty("seq")] public long Seq;

        [JsonProperty("payload")] public JToken Payload;
        [JsonProperty("quality")] public string Quality;

        /// <summary>VZ-C-03 — 축약형('raw')과 객체형이 둘 다 올 수 있어 원시 토큰으로 받는다.</summary>
        [JsonProperty("aggregation")] public JToken Aggregation;

        [JsonProperty("scope")] public JToken Scope;

        /// <summary>
        /// BE-C-04 — 이 payload 의 좌표가 어느 기준계인가. 좌표를 담지 않는 채널은 null.
        /// **읽어서 표시만 한다.** 이 값을 근거로 무언가를 환산하면 계약 위반이다.
        /// </summary>
        [JsonProperty("coordinate_frame")] public string CoordinateFrame;

        /// <summary>
        /// 계약에 선언되지 않은 필드 전부. VZ-C-06 의 원천 종류 표기가 여기로 들어온다.
        /// 진단 화면이 "실제로 무엇이 왔는가"를 보여줄 수 있는 것도 이 사전 덕분이다.
        /// </summary>
        [JsonExtensionData] public IDictionary<string, JToken> Extra = new Dictionary<string, JToken>();

        /// <summary>확장 필드 조회. 키가 없으면 false — **null 값과 구분된다.**</summary>
        public bool TryGetExtra(string key, out JToken token)
        {
            if (Extra != null && Extra.TryGetValue(key, out token)) return true;
            token = null;
            return false;
        }
    }

    /// <summary>
    /// 상태 3층 원본 (REQ-205 / VZ-U-01). **단일 값으로 뭉치지 않는다.**
    /// 표시값은 <see cref="Data.StatusModel"/> 이 파생시킨다.
    /// </summary>
    public sealed class StateLayersWire
    {
        /// <summary>기기 자기보고.</summary>
        [JsonProperty("device_status")] public string DeviceStatus;

        /// <summary>**서버 판정.** 클라이언트는 이 값을 다시 계산하지 않는다.</summary>
        [JsonProperty("availability")] public string Availability;

        /// <summary>오케스트레이터 파생 (REQ-201).</summary>
        [JsonProperty("deployment")] public string Deployment;

        /// <summary>마지막 수신 시각(서버 시각). 발행한 적이 없으면 null.</summary>
        [JsonProperty("last_seen")] public string LastSeen;

        /// <summary>
        /// 서버가 stale 판정에 쓴 임계. 화면은 이 값을 문구로 그리고,
        /// **보간 정지 임계로도 이 값을 쓴다** — 뷰어가 임의 상수를 새로 만들지 않기 위함.
        /// </summary>
        [JsonProperty("stale_threshold_ms")] public double StaleThresholdMs = 60000;

        [JsonProperty("reason")] public string Reason;
    }

    /// <summary>액추에이터 도메인 어휘 (VZ-U-01). 표준 3층과 별개로 다룬다.</summary>
    public sealed class ActuatorStateWire
    {
        [JsonProperty("phase")] public string Phase;
        [JsonProperty("progress_pct")] public double? ProgressPct;
        [JsonProperty("position_pct")] public double? PositionPct;
        [JsonProperty("control_locked")] public bool ControlLocked;
        [JsonProperty("lock_reason")] public string LockReason;
        [JsonProperty("command_id")] public string CommandId;
    }

    /// <summary>
    /// telemetry payload 중 좌표 부분. **이미 전역 좌표로 변환된 값이다**(BE-C-04 · DT-03).
    /// 뷰어는 로컬→글로벌 변환을 하지 않는다.
    /// </summary>
    public sealed class PositionWire
    {
        [JsonProperty("x")] public double X;
        [JsonProperty("y")] public double Y;
        [JsonProperty("z")] public double Z;

        /// <summary>payload 안에도 기준계 표기가 실려 온다. 봉투의 coordinate_frame 과 같은 값.</summary>
        [JsonProperty("frame")] public string Frame;
    }

    public sealed class VelocityWire
    {
        [JsonProperty("linear_mps")] public double LinearMps;
        [JsonProperty("angular_rps")] public double AngularRps;
    }

    /// <summary>로봇 telemetry (HW-R-03). 좌표 외 필드는 이름표·진단 표시용이다.</summary>
    public sealed class RobotTelemetryWire
    {
        [JsonProperty("position")] public PositionWire Position;
        [JsonProperty("battery_pct")] public double? BatteryPct;
        [JsonProperty("velocity")] public VelocityWire Velocity;
        [JsonProperty("is_moving")] public bool IsMoving;
    }

    // ── 권한 범위 (VZ-C-04 / BE-Q-04) ─────────────────────────────────────────

    public sealed class RoleScopeWire
    {
        /// <summary><c>["*"]</c> 이면 전 범위. 기준 계층은 Zone (BE-C-02).</summary>
        [JsonProperty("zones")] public List<string> Zones = new List<string>();
    }

    public sealed class RoleInfoWire
    {
        [JsonProperty("role")] public string Role;
        [JsonProperty("display_name")] public string DisplayName;
        [JsonProperty("scope")] public RoleScopeWire Scope;
        [JsonProperty("issued_at")] public string IssuedAt;
        [JsonProperty("source")] public string Source;
    }

    /// <summary>접속 직후 서버가 내려주는 값. stale 임계는 **표시와 보간 정지에만** 쓴다.</summary>
    public sealed class HelloWire
    {
        [JsonProperty("server_time")] public string ServerTime;
        [JsonProperty("stale_threshold_ms")] public double StaleThresholdMs = 60000;
        [JsonProperty("protocol")] public string Protocol;
    }
}
