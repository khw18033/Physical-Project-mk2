// Assets/Scripts/Data/StatusModel.cs
//
// 상태 3층 → 표시 4종 파생 (REQ-203 / REQ-205 / VZ-U-01).
//
// **3층 원본을 그대로 보관하고 표시값은 여기서 파생시킨다.** 단일 값으로 뭉쳐 저장하면
// "연결은 됐는데 기기가 fault"와 "값이 오래됨"을 표현할 수 없고, 원천(기기·서버·오케스트레이터)이
// 섞여 책임 소재가 흐려진다. 세 층은 각각 다른 주체가 채우고 뷰어는 조합할 뿐이다.
//
// **stale 판정은 여기서 하지 않는다.** 서버가 last_seen 과 서버 시각으로 이미 끝냈다.
// 뷰어가 다시 계산하면 사용자 PC 시계에 의존하게 되고, 웹 대시보드와 판정이 갈린다 —
// 두 화면이 같은 대상을 다르게 그리는 가장 흔한 원인이 이것이다(검증 9).

using System;
using HybridDt.Twin.Transport;

namespace HybridDt.Twin.Data
{
    public enum DisplayStatus
    {
        Normal,
        Fault,
        NotDeployed,
        /// <summary>판단 불가. **"사라짐"이 아니다** — 없는 것과 모르는 것은 다르다.</summary>
        Unknown,
    }

    public static class StatusModel
    {
        public static string Label(DisplayStatus s)
        {
            switch (s)
            {
                case DisplayStatus.Normal: return "정상";
                case DisplayStatus.Fault: return "장애";
                case DisplayStatus.NotDeployed: return "의도적 미배포";
                default: return "판단 불가";
            }
        }

        /// <summary>
        /// 매핑표 (웹 대시보드 src/data/statusModel.ts 와 **같은 표**를 따른다).
        ///
        /// | device_status | availability | deployment    | 표시        |
        /// |---------------|--------------|---------------|-------------|
        /// | ok            | online       | deployed      | 정상         |
        /// | fault         | online       | deployed      | 장애         |
        /// | —             | offline      | deployed      | 장애         |
        /// | ok            | stale        | deployed      | 판단 불가     |
        /// | —             | —            | not_deployed  | 의도적 미배포  |
        ///
        /// 판정 **순서**에 의미가 있다.
        ///  - deployment 가 먼저다. 안 켠 것은 고장이 아니다.
        ///  - offline 이 device_status 보다 먼저다. 연락이 끊겼으면 기기 자기보고는 과거의 말이다.
        ///  - stale 도 device_status 보다 먼저다. 그래서 **ok + stale 은 정상이 아니라 판단 불가**다.
        /// </summary>
        public static DisplayStatus Derive(StateLayersWire layers)
        {
            // 상태 봉투를 아직 한 번도 못 받았다면 판단할 근거가 없다.
            if (layers == null) return DisplayStatus.Unknown;

            if (layers.Deployment != "deployed") return DisplayStatus.NotDeployed;
            if (layers.Availability == "offline") return DisplayStatus.Fault;
            if (layers.Availability == "stale") return DisplayStatus.Unknown;
            if (layers.Availability != "online") return DisplayStatus.Unknown;

            if (layers.DeviceStatus == "fault") return DisplayStatus.Fault;
            if (layers.DeviceStatus == "ok") return DisplayStatus.Normal;

            // 연결은 살아 있으나 기기가 자기보고를 한 적이 없는 경우(엣지노드 등).
            return layers.DeviceStatus == null ? DisplayStatus.Normal : DisplayStatus.Unknown;
        }

        /// <summary>3층을 사람이 읽는 한 줄로. 값이 없는 층은 '—'.</summary>
        public static string FormatLayers(StateLayersWire layers)
        {
            if (layers == null) return "— · — · —";
            string dev = layers.DeviceStatus == null ? "—" : "device " + layers.DeviceStatus;
            string avail = layers.Availability ?? "—";
            return dev + " · " + avail + " · " + layers.Deployment;
        }

        /// <summary>
        /// "최근 수신 N초 전".
        ///
        /// **두 시각 모두 서버 시각이다** — 봉투의 ts 에서 last_seen 을 뺀다.
        /// 클라이언트 시계가 개입하지 않으므로 웹과 같은 숫자가 나온다.
        /// </summary>
        public static double? LastSeenAgeMs(StateLayersWire layers, string envelopeTs)
        {
            if (layers == null || layers.LastSeen == null || envelopeTs == null) return null;

            DateTime seen, ts;
            if (!TryParseIso(layers.LastSeen, out seen)) return null;
            if (!TryParseIso(envelopeTs, out ts)) return null;

            double ms = (ts - seen).TotalMilliseconds;
            return ms < 0 ? 0 : ms;
        }

        public static string FormatAge(double? ms)
        {
            if (!ms.HasValue) return "수신 이력 없음";
            double v = ms.Value;
            if (v < 1000) return "최근 수신 " + (v / 1000.0).ToString("0.00") + "초 전";
            if (v < 60000) return "최근 수신 " + Math.Round(v / 1000.0) + "초 전";
            int min = (int)(v / 60000);
            int sec = (int)Math.Round((v % 60000) / 1000.0);
            return "최근 수신 " + min + "분 " + sec + "초 전";
        }

        private static bool TryParseIso(string s, out DateTime value)
        {
            return DateTime.TryParse(
                s,
                System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.AdjustToUniversal | System.Globalization.DateTimeStyles.AssumeUniversal,
                out value);
        }
    }
}
