// Assets/Scripts/View/EntityView.cs
//
// 대상 하나의 씬 표현.
//
// ── 이 컴포넌트가 위치를 얻는 경로는 하나뿐이다
//
//   수신 봉투 → TwinStore → PoseBuffer → PoseInterpolator → 여기
//
// **다른 오브젝트의 Transform 을 읽어 위치를 얻는 경로가 없다.** 이번 작업에서 가장
// 중요한 구조 규칙이고, 이유는 2단계 때문이다 — Unity 가 시뮬레이터를 겸하는 순간
// "씬 안에서 바로 읽으면 되는데"라는 지름길이 생기고, 그 지름길을 한 번 쓰면 화면은
// 완벽한데 파이프라인은 한 번도 안 거친 상태가 된다. 그 상태로 실제 백엔드를 붙이면
// 전부 어긋난다. 그래서 지금 그 경로를 만들지 않는다.
//
// ── 자리(anchor)와 위치(pose)를 나눈 이유
//
// 루트는 레지스트리가 정한 **자리**에 고정되고 몸체만 수신 좌표로 움직인다. 그래서
// 값이 한 번도 안 온 대상(robot-03)도 자리 표식이 남고, 값이 끊긴 대상은 자리에서
// 얼마나 떨어진 곳에 멈춰 섰는지가 보인다. 자리 표식을 몸체에 붙이면 몸체가 사라질 때
// 자리도 같이 사라져 "여기 있어야 할 게 안 왔다"가 안 보인다.

using UnityEngine;
using HybridDt.Twin.Data;

namespace HybridDt.Twin.View
{
    public sealed class EntityView : MonoBehaviour
    {
        public EntityState State { get; private set; }

        private Transform _body;
        private Renderer _bodyRenderer;
        private Transform _slot;
        private Renderer _slotRenderer;
        private Transform _topMarker;
        private Renderer _topRenderer;
        private Transform _originBadge;
        private Renderer _originRenderer;
        private WorldLabel _label;

        private readonly PoseInterpolator _interpolator = new PoseInterpolator();
        private Vector3 _anchor;
        private float _bodyHeight = 1f;
        private float _baseScale = 1f;
        /// <summary>상태별 높이 보정(미배포는 살짝 가라앉는다). 씬 반영에서 정하고 렌더가 쓴다.</summary>
        private float _statusYOffset;

        public PoseInterpolator Interpolator { get { return _interpolator; } }

        /// <summary>
        /// 프리팹이 없어도 프리미티브로 대체 생성한다 — 빈 씬에서 바로 돌아야 한다는 요건.
        /// </summary>
        public static EntityView Create(Transform parent, EntityState state, Vector3 anchor, GameObject prefab, Font labelFont)
        {
            GameObject root = new GameObject("entity:" + state.Id);
            root.transform.SetParent(parent, false);
            root.transform.position = anchor;

            EntityView view = root.AddComponent<EntityView>();
            view.State = state;
            view._anchor = anchor;

            // ── 자리 표식. **항상 있다.** 미배포도 판단 불가도 자리는 남는다.
            GameObject slot = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            slot.name = "Slot";
            Destroy(slot.GetComponent<Collider>());
            slot.transform.SetParent(root.transform, false);
            slot.transform.localPosition = new Vector3(0f, 0.01f, 0f);
            slot.transform.localScale = new Vector3(0.9f, 0.01f, 0.9f);
            view._slot = slot.transform;
            view._slotRenderer = slot.GetComponent<Renderer>();

            // ── 몸체.
            GameObject body;
            if (prefab != null)
            {
                body = Instantiate(prefab);
                body.name = "Body";
            }
            else
            {
                body = GameObject.CreatePrimitive(StatusPalette.BodyFor(state.EntityType));
                body.name = "Body";
                Collider c = body.GetComponent<Collider>();
                if (c != null) Destroy(c);
            }
            body.transform.SetParent(root.transform, true);
            body.transform.position = anchor;
            view._body = body.transform;
            view._bodyRenderer = body.GetComponentInChildren<Renderer>();
            view._baseScale = body.transform.localScale.y <= 0f ? 1f : body.transform.localScale.y;
            view._bodyHeight = view.MeasureHeight(body);

            // ── 상태 표식(윗머리). 색과 별개로 **형태가 달라야** 흑백에서도 구분된다.
            GameObject top = GameObject.CreatePrimitive(PrimitiveType.Cube);
            top.name = "StatusMark";
            Destroy(top.GetComponent<Collider>());
            top.transform.SetParent(body.transform, false);
            view._topMarker = top.transform;
            view._topRenderer = top.GetComponent<Renderer>();

            // ── 원천 종류 표식 (VZ-C-06). 실물과 시뮬레이션이 똑같이 보이면 안 된다.
            GameObject badge = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            badge.name = "OriginBadge";
            Destroy(badge.GetComponent<Collider>());
            badge.transform.SetParent(body.transform, false);
            view._originBadge = badge.transform;
            view._originRenderer = badge.GetComponent<Renderer>();

            view._label = WorldLabel.Create(body.transform, new Vector3(0f, view._bodyHeight * 0.5f + 0.55f, 0f), 0.16f, labelFont);

            view.ApplySceneState();
            return view;
        }

        private float MeasureHeight(GameObject body)
        {
            Renderer r = body.GetComponentInChildren<Renderer>();
            return r == null ? 1f : Mathf.Max(0.2f, r.bounds.size.y);
        }

        /// <summary>레지스트리가 정한 자리. node 원점 배치가 바뀌면 갱신된다.</summary>
        public void SetAnchor(Vector3 anchor)
        {
            _anchor = anchor;
            transform.position = anchor;
            _interpolator.PlaceWithoutData(anchor);
        }

        // ── 씬 상태 반영 — **100ms 병합 창에서만 호출된다** (VZ-I-01) ─────────────

        public void ApplySceneState()
        {
            DisplayStatus status = State.Status;

            float scale, yOffset, alpha;
            StatusPalette.ShapeFor(status, out scale, out yOffset, out alpha);

            Color color = StatusPalette.For(status);
            // VZ-C-04 — 범위 밖 대상은 **지우지 않고** 채도를 낮춰 구분한다.
            // 조작을 막는 것과 존재를 숨기는 것은 다르다.
            if (!State.InScope) color = Color.Lerp(color, StatusPalette.OutOfScope, 0.55f);

            if (_bodyRenderer != null) _bodyRenderer.sharedMaterial = StatusPalette.Get(color, alpha);
            _body.localScale = Vector3.one * (_baseScale * scale);

            // 자리 표식은 **좌표를 한 번도 못 받은 대상**에만 띄운다. 좌표가 오는 대상은
            // 제 좌표가 곧 자리이고, 레지스트리 근거로 임의 배치한 자리에 고리를 그리면
            // "저기 있어야 한다"는 잘못된 정보가 된다.
            bool showSlot = !State.Pose.HasAny;
            if (_slot != null && _slot.gameObject.activeSelf != showSlot) _slot.gameObject.SetActive(showSlot);
            if (_slotRenderer != null)
            {
                _slotRenderer.sharedMaterial = StatusPalette.Get(color, status == DisplayStatus.Normal ? 0.18f : 0.4f);
            }

            ApplyStatusMark(status, yOffset);
            ApplyOriginBadge();
            ApplyLabel(status);
        }

        /// <summary>
        /// 상태 4종을 **형태로** 가른다.
        ///  정상        — 표식 없음
        ///  장애        — 머리 위 세로 막대(멀리서·가려져도 보인다)
        ///  의도적 미배포 — 납작한 판(몸체가 작고 흐려진 것과 함께 읽는다)
        ///  판단 불가    — 머리 위 원반(후광). **작게 그리지 않는다** — 모르는 것은 덜 중요한 것이 아니다.
        /// </summary>
        private void ApplyStatusMark(DisplayStatus status, float yOffset)
        {
            // 몸체의 실제 배치는 매 프레임 RenderTick 이 한다. 여기서는 보정값만 남긴다 —
            // 씬 반영(10Hz)과 보간 렌더(60fps)가 같은 Transform 을 두 리듬으로 쓰면 떨린다.
            _statusYOffset = yOffset;

            bool visible = status != DisplayStatus.Normal;
            _topMarker.gameObject.SetActive(visible);
            if (!visible) return;

            float top = _bodyHeight * 0.5f + 0.12f;

            switch (status)
            {
                case DisplayStatus.Fault:
                    _topMarker.localScale = new Vector3(0.09f, 0.9f, 0.09f);
                    _topMarker.localPosition = new Vector3(0f, top + 0.45f, 0f);
                    _topMarker.localRotation = Quaternion.identity;
                    break;
                case DisplayStatus.NotDeployed:
                    _topMarker.localScale = new Vector3(0.7f, 0.03f, 0.7f);
                    _topMarker.localPosition = new Vector3(0f, top + 0.1f, 0f);
                    _topMarker.localRotation = Quaternion.identity;
                    break;
                default: // 판단 불가
                    _topMarker.localScale = new Vector3(0.55f, 0.05f, 0.55f);
                    _topMarker.localPosition = new Vector3(0f, top + 0.35f, 0f);
                    _topMarker.localRotation = Quaternion.Euler(0f, 0f, 20f);
                    break;
            }

            if (_topRenderer != null) _topRenderer.sharedMaterial = StatusPalette.Get(StatusPalette.For(status), 0.95f);
        }

        /// <summary>
        /// VZ-C-06 — 원천 종류 표식. 색과 모양이 함께 바뀐다.
        /// 목 게이트웨이가 아직 표기를 싣지 않으므로 지금은 전부 '원천 미상'(납작한 원반)이다 —
        /// **그것이 이번 검증에서 확인해야 하는 상태다.** 실물로 단정하지 않는다.
        /// </summary>
        private void ApplyOriginBadge()
        {
            OriginKind kind = State.Origin.Kind;
            PrimitiveType want = StatusPalette.OriginShape(kind);

            // 모양이 바뀌어야 하면 표식을 다시 만든다. 상태 변화가 잦지 않아 비용은 무시할 수준이다.
            if (_originBadge != null && _originBadge.GetComponent<MeshFilter>() != null)
            {
                MeshFilter mf = _originBadge.GetComponent<MeshFilter>();
                string wantName = want.ToString();
                if (mf.sharedMesh == null || !mf.sharedMesh.name.StartsWith(wantName))
                {
                    Transform parent = _originBadge.parent;
                    Destroy(_originBadge.gameObject);
                    GameObject badge = GameObject.CreatePrimitive(want);
                    badge.name = "OriginBadge";
                    Collider c = badge.GetComponent<Collider>();
                    if (c != null) Destroy(c);
                    badge.transform.SetParent(parent, false);
                    _originBadge = badge.transform;
                    _originRenderer = badge.GetComponent<Renderer>();
                }
            }

            float top = _bodyHeight * 0.5f + 0.12f;
            bool flat = kind == OriginKind.Unknown;
            _originBadge.localScale = flat ? new Vector3(0.22f, 0.02f, 0.22f) : Vector3.one * 0.16f;
            _originBadge.localPosition = new Vector3(0.32f, top + 0.12f, 0f);

            if (_originRenderer != null)
                _originRenderer.sharedMaterial = StatusPalette.Get(StatusPalette.OriginColor(kind), 1f);
        }

        private void ApplyLabel(DisplayStatus status)
        {
            if (_label == null) return;

            string name = string.IsNullOrEmpty(State.DisplayName) ? State.Id : State.DisplayName;
            string line = name + "\n" + StatusModel.Label(status);

            // VZ-C-06 — 원천이 실물로 확인되지 않은 것은 이름표에도 남긴다.
            line += " · " + State.Origin.ShortLabel();

            // VZ-U-01 — 액추에이터는 표준 3층과 별개인 도메인 어휘를 갖는다.
            if (State.Actuator != null) line += "\n" + ActuatorPhaseLabel(State.Actuator.Phase);

            // VZ-C-03 — 집약 표기. 웹 화면과 같은 값을 보고 있는지 대조하는 근거다.
            if (State.Aggregation.Mode != AggregationMode.Raw) line += "\n" + State.Aggregation.ShortLabel();

            // VZ-C-04 — 범위 밖.
            if (!State.InScope) line += "\n[권한 범위 밖]";

            _label.SetText(line);
            _label.SetColor(State.InScope ? Color.white : new Color(0.75f, 0.75f, 0.78f));
        }

        private static string ActuatorPhaseLabel(string phase)
        {
            switch (phase)
            {
                case "idle": return "대기";
                case "moving": return "동작 중";
                case "completed": return "완료";
                case "error": return "오류";
                case "unverified": return "확인 불가";
                default: return phase ?? "";
            }
        }

        // ── 보간 렌더 — **매 프레임 호출된다** (VZ-U-02) ────────────────────────

        public void RenderTick(double now, bool flipHandedness)
        {
            Vector3 pos;

            if (State.Pose.HasAny)
            {
                pos = _interpolator.Evaluate(
                    State.Pose,
                    now,
                    State.ServerSaysNotCurrent,
                    State.StaleThresholdMs / 1000.0,
                    flipHandedness);
            }
            else
            {
                // 좌표를 한 번도 못 받은 대상. **씬에서 빼지 않는다** —
                // 레지스트리가 정한 자리에 세워야 '의도적 미배포'가 보인다(VZ-I-03).
                _interpolator.PlaceWithoutData(_anchor);
                pos = _interpolator.Rendered;
            }

            _body.position = new Vector3(pos.x, pos.y + _bodyHeight * 0.5f + _statusYOffset, pos.z);
        }
    }
}
