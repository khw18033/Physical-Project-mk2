// Assets/Scripts/Data/AggregationSpec.cs
//
// VZ-C-03 — 집약 계층 경계 표기와 **재집약 차단**.
//
// ── 왜 뷰어에도 이게 있나
//
// 이번 범위의 뷰어는 값을 평균 내지 않는다. 그런데도 이 파일을 두는 이유는 둘이다.
//  1. 씬에 표기를 띄워야 한다 — 웹 화면과 같은 값을 보고 있는지 대조하려면 "이 값이
//     원본인가 요약인가"가 양쪽에 똑같이 보여야 한다(검증 9).
//  2. 나중에 뷰어가 구역 요약을 그리기 시작하는 순간 반드시 필요해지는데, 그때 만들면
//     이미 재집약 코드가 여기저기 들어간 뒤다. 관문을 먼저 세워 두면 우회로가 안 생긴다.
//
// ── 모르는 표기는 원본이 아니라 **차단**이다 (웹의 실패 방향 정정을 그대로 따른다)
//
// web-dashboard/src/data/aggregation.ts 가 한 번 밟은 함정이다. 못 읽는 표기를 raw 로
// 떨어뜨리면 조용히 통과하고 **숫자가 틀린다.** 차단으로 떨어뜨리면 계산이 멈추고
// 그 사실이 화면에 뜬다. 실패는 드러나는 쪽으로 나야 한다.
//
// **웹 코드를 옮기지 않았다.** 같은 규칙을 C# 관용구로 다시 썼고, 계약이 바뀌면
// 두 파일의 같은 자리(Normalize 함수 하나)를 고치면 된다.

using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace HybridDt.Twin.Data
{
    public enum AggregationMode
    {
        Raw,
        Aggregated,
        /// <summary>"표기가 없다"가 아니라 **"표기가 있는데 읽을 수 없다"**.</summary>
        Unknown,
    }

    public struct AggregationSpec
    {
        public AggregationMode Mode;
        /// <summary>어느 계층에서 집약되었나. 평시 지표는 zone. 원본이면 null.</summary>
        public string Level;
        public string Method;
        public double? WindowSec;
        /// <summary>**못 읽은 원본 표기.** Unknown 일 때만 채워진다. 진단의 전부가 이 문자열이다.</summary>
        public string RawSpec;

        public static AggregationSpec Raw()
        {
            return new AggregationSpec { Mode = AggregationMode.Raw };
        }

        /// <summary>씬 이름표에 붙는 짧은 표기.</summary>
        public string ShortLabel()
        {
            switch (Mode)
            {
                case AggregationMode.Raw: return "원본";
                case AggregationMode.Unknown: return "집약 표기 불명";
                default:
                    string level = Level == null ? "계층 미표기" : LevelLabel(Level);
                    string window = WindowSec.HasValue ? WindowSec.Value + "초" : "창 미표기";
                    return "요약 · " + level + " · " + window;
            }
        }

        private static string LevelLabel(string level)
        {
            switch (level)
            {
                case "device": return "장치";
                case "edge": return "엣지";
                case "zone": return "구역";
                case "server": return "서버";
                default: return level;
            }
        }
    }

    public static class Aggregation
    {
        /// <summary>
        /// 와이어 값 정규화.
        ///
        /// **표기 필드가 아예 없는 경우는 raw 다.** 상태·명령·계획 채널은 집약 개념이 없어
        /// 이 필드를 싣지 않는다. 그것까지 Unknown 으로 떨어뜨리면 그 채널 전부가 차단에 걸린다.
        /// "필드가 없는 것"과 "필드가 있는데 못 읽는 것"은 다른 사건이다.
        ///
        /// ※ 정식 계약이 축약형/객체형 중 무엇을 쓸지, 필드 이름을 kind/level/window_sec 로 할지
        ///   mode/layer/window_ms 로 할지 아직 확정 전이라 **둘 다 받는다.** 확정되면 이 함수
        ///   하나만 좁히면 되고, 웹의 normalizeAggregation() 과 같은 자리다.
        ///
        ///   **모르는 철자를 추측해서 늘리지 않는다.** 세 번째 철자를 넣으면 같은 함정을 하나 더
        ///   만드는 것이고, 못 읽는 값은 아래 Unknown 으로 떨어져 차단된다.
        /// </summary>
        public static AggregationSpec Normalize(JToken token)
        {
            if (token == null || token.Type == JTokenType.Null || token.Type == JTokenType.Undefined)
                return AggregationSpec.Raw();

            if (token.Type == JTokenType.String)
            {
                string s = token.Value<string>();
                if (s == "raw") return AggregationSpec.Raw();
                // 축약형인데 raw 가 아니다 — 계약이 정의하지 않은 문자열이므로 판단할 수 없다.
                return new AggregationSpec { Mode = AggregationMode.Unknown, RawSpec = Describe(token) };
            }

            JObject o = token as JObject;
            if (o == null) return new AggregationSpec { Mode = AggregationMode.Unknown, RawSpec = Describe(token) };

            string kind = ReadString(o, "kind") ?? ReadString(o, "mode");
            string level = ReadString(o, "level") ?? ReadString(o, "layer");
            string method = ReadString(o, "method");

            double? windowSec = ReadDouble(o, "window_sec");
            if (!windowSec.HasValue)
            {
                double? windowMs = ReadDouble(o, "window_ms");
                if (windowMs.HasValue) windowSec = Math.Round(windowMs.Value / 1000.0);
            }

            if (kind == "raw")
                return new AggregationSpec { Mode = AggregationMode.Raw, Level = level, Method = method, WindowSec = windowSec };
            if (kind == "aggregated")
                return new AggregationSpec { Mode = AggregationMode.Aggregated, Level = level, Method = method, WindowSec = windowSec };

            // kind·mode 가 둘 다 없거나 모르는 값이다. level 이나 window 가 실려 있어도
            // 원본/집약 여부를 단정하지 않는다 — 그 추측이 틀리면 이 파일이 막으려던 사고가 그대로 난다.
            return new AggregationSpec
            {
                Mode = AggregationMode.Unknown,
                Level = level,
                Method = method,
                WindowSec = windowSec,
                RawSpec = Describe(token),
            };
        }

        private static string ReadString(JObject o, string key)
        {
            JToken t = o[key];
            return t == null || t.Type != JTokenType.String ? null : t.Value<string>();
        }

        private static double? ReadDouble(JObject o, string key)
        {
            JToken t = o[key];
            if (t == null) return null;
            if (t.Type == JTokenType.Integer || t.Type == JTokenType.Float) return t.Value<double>();
            return null;
        }

        private static string Describe(JToken token)
        {
            try { return token.ToString(Newtonsoft.Json.Formatting.None); }
            catch (Exception) { return "(표기를 문자열로 옮기지 못함)"; }
        }
    }

    /// <summary>왜 막혔는가. 통합 때 대응이 갈리므로 두 갈래를 구분한다.</summary>
    public enum BlockReason
    {
        /// <summary>이미 집약된 값. 원본 질의로 우회하면 된다.</summary>
        Aggregated,
        /// <summary>표기를 읽을 수 없다. **계약을 맞춰야** 한다.</summary>
        Unknown,
    }

    public struct BlockRecord
    {
        public DateTime At;
        public string Context;
        public string Operation;
        public BlockReason Reason;
        public string Message;
    }

    /// <summary>
    /// **재집약 차단.** 집약 연산을 적용하면 안 되는 값에 그것을 적용하려 하면 여기서 막는다.
    ///
    /// 개발 빌드 여부를 보지 않는다 — 운영에서만 조용히 통과하면 그게 가장 위험한 조합이다.
    /// 차단 이력은 진단 오버레이가 **콘솔이 아니라 화면에** 띄운다.
    /// </summary>
    public static class ReaggregationGuard
    {
        private const int MaxRecords = 20;
        private static readonly List<BlockRecord> Records = new List<BlockRecord>();

        public static IReadOnlyList<BlockRecord> Log { get { return Records; } }

        /// <returns>참이면 **호출부는 계산 결과 대신 표시로 대체해야 한다.**</returns>
        public static bool Block(AggregationSpec spec, string operation, string context)
        {
            if (spec.Mode == AggregationMode.Raw) return false;

            BlockReason reason = spec.Mode == AggregationMode.Aggregated ? BlockReason.Aggregated : BlockReason.Unknown;

            string message = reason == BlockReason.Aggregated
                ? context + " 의 값은 이미 " + spec.ShortLabel() + " 인데 " + operation +
                  " 을(를) 적용하려 했다. 집약값을 다시 집약하면 가중치가 무너지므로 계산하지 않았다."
                : context + " 의 집약 표기를 읽을 수 없어 원본인지 집약인지 판단할 수 없는데 " + operation +
                  " 을(를) 적용하려 했다. 판단이 되지 않는 값에 집약 연산을 적용하지 않는다." +
                  (spec.RawSpec == null ? "" : " 수신한 표기: " + spec.RawSpec);

            Records.Insert(0, new BlockRecord
            {
                At = DateTime.Now,
                Context = context,
                Operation = operation,
                Reason = reason,
                Message = message,
            });
            if (Records.Count > MaxRecords) Records.RemoveAt(Records.Count - 1);

            UnityEngine.Debug.LogWarning("[VZ-C-03 차단] " + message);
            return true;
        }

        public static void Clear()
        {
            Records.Clear();
        }
    }
}
