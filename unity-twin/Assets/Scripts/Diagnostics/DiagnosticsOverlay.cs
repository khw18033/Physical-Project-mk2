// Assets/Scripts/Diagnostics/DiagnosticsOverlay.cs
//
// 화면 위 진단 패널. **검증 항목을 눈으로 확인하는 자리**이자, 웹 대시보드와 같은 값을
// 보고 있는지 대조하는 창(검증 9)이다.
//
// ── 왜 콘솔이 아니라 화면인가
//
// 집약 표기 차단에서 배운 것과 같다 — 콘솔 경고는 아무도 안 보고 빌드에서는 아예 없다.
// "표기를 못 읽었다", "보간이 멈췄다", "재집약을 막았다"는 **사실 자체가 관제 정보**이므로
// 화면에 있어야 한다.
//
// 단축키 — F1: 패널 접기/펴기 · H: 손잡이 플래그 뒤집기(검증 7)

using System.Text;
using UnityEngine;
using HybridDt.Twin.Data;
using HybridDt.Twin.View;

namespace HybridDt.Twin.Diagnostics
{
    public sealed class DiagnosticsOverlay : MonoBehaviour
    {
        public TwinViewer viewer;

        private bool _open = true;
        private Vector2 _scroll;
        private GUIStyle _mono;

        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.F1)) _open = !_open;
            if (Input.GetKeyDown(KeyCode.H) && viewer != null) viewer.flipHandedness = !viewer.flipHandedness;
        }

        private void OnGUI()
        {
            if (viewer == null) return;

            if (_mono == null)
            {
                _mono = new GUIStyle(GUI.skin.label);
                _mono.fontSize = 12;
                _mono.richText = false;
                _mono.wordWrap = false;
            }

            float w = _open ? 560f : 260f;
            float h = _open ? Mathf.Min(Screen.height - 24f, 640f) : 28f;

            GUILayout.BeginArea(new Rect(10, 10, w, h), GUI.skin.box);

            if (!_open)
            {
                GUILayout.Label("트윈 뷰어 진단 (F1)", _mono);
                GUILayout.EndArea();
                return;
            }

            _scroll = GUILayout.BeginScrollView(_scroll);
            GUILayout.Label(BuildHeader(), _mono);
            GUILayout.Space(6);
            GUILayout.Label(BuildEntities(), _mono);
            GUILayout.Space(6);
            GUILayout.Label(BuildBlocks(), _mono);
            GUILayout.Space(6);
            GUILayout.Label(BuildLog(), _mono);
            GUILayout.EndScrollView();

            GUILayout.EndArea();
        }

        private string BuildHeader()
        {
            StringBuilder sb = new StringBuilder();
            TwinStore store = viewer.Store;
            SceneUpdateMeter m = viewer.Meter;

            sb.AppendLine("■ 트윈 뷰어 (VZ-U-02)   F1 접기 · H 손잡이 뒤집기");
            sb.AppendLine("연결   " + viewer.Connection.Describe());
            sb.AppendLine("좌표   " + FrameConvert.Describe(viewer.flipHandedness));

            if (store != null)
            {
                sb.AppendLine("구성   " + (store.RegistryError ?? ("레지스트리 " + store.Registry.Version
                    + " · 대상 " + store.Registry.Entities.Count + " · 노드 " + store.Registry.Nodes.Count
                    + " · 구역 " + store.Registry.Zones.Count)));

                string role = store.Role == null
                    ? "(역할 미수신)"
                    : store.Role.DisplayName + " · 범위 " + string.Join(", ", store.Role.Scope == null ? new string[0] : store.Role.Scope.Zones.ToArray());
                sb.AppendLine("권한   " + role + "   (VZ-C-04 · 실제 강제는 백엔드)");

                int n, f, nd, u;
                store.CountByStatus(out n, out f, out nd, out u);
                sb.AppendLine("상태   정상 " + n + " · 장애 " + f + " · 미배포 " + nd + " · 판단 불가 " + u);

                int r, s, rp, ou;
                store.CountByOrigin(out r, out s, out rp, out ou);
                sb.AppendLine("원천   실물 " + r + " · 시뮬 " + s + " · 재생 " + rp + " · 미상 " + ou + "   (VZ-C-06)");
            }

            if (m != null)
            {
                sb.AppendLine("계측   씬 반영 " + m.SceneUpdatesPerSec.ToString("0.0") + "/s (최대 "
                    + m.PeakSceneUpdatesPerSec.ToString("0.0") + ") · 렌더 " + m.FramesPerSec.ToString("0") + " fps");
                sb.AppendLine("       수신 " + m.EnvelopesPerSec.ToString("0.0") + "/s · 누적 봉투 "
                    + m.TotalEnvelopes + " vs 씬 반영 " + m.TotalSceneUpdates
                    + "   ← 데이터는 전량, 반영만 병합");
            }

            return sb.ToString();
        }

        private string BuildEntities()
        {
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("■ 대상");

            foreach (EntityState s in viewer.Store.Entities)
            {
                sb.Append(Pad(s.Id, 12));
                sb.Append(Pad(StatusModel.Label(s.Status), 8));
                sb.Append(Pad(s.Origin.ShortLabel(), 12));
                sb.Append(Pad(s.InScope ? "범위내" : "범위밖", 7));

                sb.Append(Pad(StatusModel.FormatLayers(s.Layers), 30));

                double? age = StatusModel.LastSeenAgeMs(s.Layers, s.StateEnvelopeTs);
                sb.Append(Pad(StatusModel.FormatAge(age), 20));

                sb.Append(Pad(s.CoordinateFrame ?? "좌표 없음", 14));
                sb.Append(Pad(s.Aggregation.ShortLabel(), 18));
                sb.Append("봉투 " + s.EnvelopeCount);
                sb.AppendLine();
            }

            return sb.ToString();
        }

        private string BuildBlocks()
        {
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("■ 재집약 차단 (VZ-C-03) — " + ReaggregationGuard.Log.Count + "건");
            for (int i = 0; i < ReaggregationGuard.Log.Count && i < 3; i++)
            {
                sb.AppendLine("  · " + ReaggregationGuard.Log[i].Message);
            }
            if (ReaggregationGuard.Log.Count == 0)
                sb.AppendLine("  (뷰어는 집약 연산을 하지 않는다. 관문은 세워져 있고 걸린 건이 없다)");
            return sb.ToString();
        }

        private string BuildLog()
        {
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("■ 로그");
            foreach (string line in viewer.Log) sb.AppendLine("  " + line);
            return sb.ToString();
        }

        private static string Pad(string s, int width)
        {
            if (s == null) s = "";
            if (s.Length >= width) return s.Substring(0, width - 1) + " ";
            return s.PadRight(width);
        }
    }
}
