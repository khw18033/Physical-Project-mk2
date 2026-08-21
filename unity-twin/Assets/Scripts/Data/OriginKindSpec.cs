// Assets/Scripts/Data/OriginKindSpec.cs
//
// VZ-C-06 — 원천 종류(실물 / 시뮬레이션 / 기록 재생) 표기.
//
// ── 왜 뷰어 단계에서 이걸 하나
//
// 2단계에서 Unity 가 시뮬레이터를 겸하는 순간, 가짜 로봇 상태가 진짜와 **똑같은 봉투로**
// 올라온다. 그때 가서 구분 표시를 붙이려 하면 이미 늦다 — 표시가 먼저 있어야
// "지금 보고 있는 게 시뮬레이션이다"가 씬에서 보이고, 그게 곧 1단계와 2단계를
// 구분하는 눈이다.
//
// 더 큰 것은 감사다(VZ-O-03). 훈련으로 연 수문과 실제로 연 수문이 같은 모양으로 남으면
// 사후 조사가 성립하지 않는다.
//
// ── 실패 방향을 미리 정해 둔다 — 집약 표기에서 밟은 함정을 반복하지 않는다
//
// 집약 표기(AggregationSpec)는 한때 "모르면 raw" 로 떨어져 재집약 차단이 조용히 풀렸다.
// 여기서 같은 실수를 하면 **표기가 없는 시뮬레이션 값이 실물로 단정된다.** 그래서
// 규칙이 하나다 —
//
//   **표기가 없거나 못 읽으면 Unknown 으로 두고 그 사실을 화면에 표시한다.**
//
// 집약 표기와 실패 방향이 갈리는 지점이 하나 있다. 집약은 "필드가 없는 채널"이 정상이라
// 부재를 raw 로 본다. 원천 종류는 **모든 값에 붙는 메타**이므로 부재가 정상이 아니다.
// 그래서 부재도 Unknown 이고, 다만 사유를 나눠 둔다(NotLabelled / Unreadable) —
// 통합 첫날에 "아직 안 붙였다"와 "붙였는데 못 읽는다"는 대응이 다르기 때문이다.
//
// ── 필드 형태는 **제안이다**
//
// 목 게이트웨이는 아직 이 표기를 싣지 않고, 형식은 전 파트 합의 대기다. 아래 형태는
// 회의에 가져갈 안이며 계약이 아니다. 확정되면 이 파일의 Normalize 하나만 고친다.
// 자세한 제안은 contracts/twin-viewer.md 참조.

using System;
using Newtonsoft.Json.Linq;

namespace HybridDt.Twin.Data
{
    public enum OriginKind
    {
        /// <summary>실물 장치.</summary>
        Real,
        /// <summary>시뮬레이터가 만든 값. 2단계의 Unity 시뮬이 여기에 해당한다.</summary>
        Simulated,
        /// <summary>기록 재생.</summary>
        Replay,
        /// <summary>판단 불가. **실물로 단정하지 않는다.**</summary>
        Unknown,
    }

    public enum OriginUnknownReason
    {
        None,
        /// <summary>표기 자체가 봉투에 없다. 지금 목 게이트웨이가 여기다.</summary>
        NotLabelled,
        /// <summary>표기는 있는데 계약이 정의하지 않은 값이다. **계약 불일치 신호.**</summary>
        Unreadable,
    }

    public struct OriginKindSpec
    {
        public OriginKind Kind;
        public OriginUnknownReason Reason;
        /// <summary>표기를 붙인 주체(제안 필드). 시뮬레이터가 둘 이상일 때 어느 것인지 구분한다.</summary>
        public string Producer;
        /// <summary>훈련 세션 식별자(제안 필드). 감사에서 같은 훈련의 조작을 묶는 근거.</summary>
        public string SessionId;
        /// <summary>못 읽은 원본 표기. Unreadable 일 때만 채워진다.</summary>
        public string RawSpec;

        public static OriginKindSpec NotLabelled()
        {
            return new OriginKindSpec { Kind = OriginKind.Unknown, Reason = OriginUnknownReason.NotLabelled };
        }

        /// <summary>실물이 아닌 값인가. **Unknown 은 여기서 참이다** — 모르는 것을 실물로 치지 않는다.</summary>
        public bool IsNotConfirmedReal { get { return Kind != OriginKind.Real; } }

        public string ShortLabel()
        {
            switch (Kind)
            {
                case OriginKind.Real: return "실물";
                case OriginKind.Simulated: return "시뮬레이션";
                case OriginKind.Replay: return "기록 재생";
                default:
                    return Reason == OriginUnknownReason.Unreadable ? "원천 표기 불명" : "원천 미상";
            }
        }

        public string Detail()
        {
            switch (Kind)
            {
                case OriginKind.Real:
                case OriginKind.Simulated:
                case OriginKind.Replay:
                {
                    string s = ShortLabel();
                    if (!string.IsNullOrEmpty(Producer)) s += " · " + Producer;
                    if (!string.IsNullOrEmpty(SessionId)) s += " · 세션 " + SessionId;
                    return s;
                }
                default:
                    if (Reason == OriginUnknownReason.Unreadable)
                    {
                        return "원천 종류 표기를 읽을 수 없다(VZ-C-06 계약 불일치). 수신한 표기: " + RawSpec;
                    }
                    return "원천 종류 표기가 봉투에 없다. 실물인지 시뮬레이션인지 판단할 수 없으므로 "
                         + "실물로 단정하지 않는다(VZ-C-06). 표기를 붙이는 것은 발행 주체의 몫이다.";
            }
        }
    }

    public static class OriginKinds
    {
        /// <summary>
        /// **제안 중인 봉투 필드 이름.** 계약이 다른 이름으로 확정되면 이 상수 하나만 바꾼다.
        /// 다른 철자를 추측해서 늘리지 않는다 — 집약 표기에서 배운 것이다.
        /// </summary>
        public const string EnvelopeField = "origin_kind";

        /// <summary>
        /// 봉투에서 읽는다. <paramref name="present"/> 가 거짓이면 키 자체가 없었다는 뜻이고,
        /// 그것과 "키는 있는데 값이 이상하다"는 다른 사건이므로 사유를 나눈다.
        /// </summary>
        public static OriginKindSpec Normalize(JToken token, bool present)
        {
            if (!present || token == null || token.Type == JTokenType.Null || token.Type == JTokenType.Undefined)
                return OriginKindSpec.NotLabelled();

            if (token.Type == JTokenType.String)
                return FromKindString(token.Value<string>(), null, null, token);

            JObject o = token as JObject;
            if (o == null) return Unreadable(token);

            JToken kindToken = o["kind"];
            string kind = kindToken != null && kindToken.Type == JTokenType.String ? kindToken.Value<string>() : null;
            return FromKindString(kind, ReadString(o, "producer"), ReadString(o, "session_id"), token);
        }

        private static OriginKindSpec FromKindString(string kind, string producer, string sessionId, JToken raw)
        {
            switch (kind)
            {
                case "real":
                    return new OriginKindSpec { Kind = OriginKind.Real, Producer = producer, SessionId = sessionId };
                case "simulated":
                    return new OriginKindSpec { Kind = OriginKind.Simulated, Producer = producer, SessionId = sessionId };
                case "replay":
                    return new OriginKindSpec { Kind = OriginKind.Replay, Producer = producer, SessionId = sessionId };
                default:
                    // 표기는 왔는데 계약이 정의하지 않은 값이다. **실물로 떨어뜨리지 않는다.**
                    return Unreadable(raw);
            }
        }

        private static OriginKindSpec Unreadable(JToken raw)
        {
            return new OriginKindSpec
            {
                Kind = OriginKind.Unknown,
                Reason = OriginUnknownReason.Unreadable,
                RawSpec = Describe(raw),
            };
        }

        private static string ReadString(JObject o, string key)
        {
            JToken t = o[key];
            return t == null || t.Type != JTokenType.String ? null : t.Value<string>();
        }

        private static string Describe(JToken token)
        {
            try { return token.ToString(Newtonsoft.Json.Formatting.None); }
            catch (Exception) { return "(표기를 문자열로 옮기지 못함)"; }
        }
    }
}
