// Assets/Scripts/View/HandednessMarker.cs
//
// 비대칭 마커 — **이번 작업에서 가장 값싼 보험이다.**
//
// 대칭인 물체(캡슐·구·원기둥)만 있는 씬은 좌우가 뒤집혀도 아무도 못 알아챈다. 로봇이
// 원을 그리며 돌면 뒤집힌 궤적도 똑같이 원이다. 그래서 **정면과 오른쪽이 다르게 생긴
// 표식**을 하나 세워 둔다.
//
// 모양은 대문자 F 다. 손대칭(chirality)을 눈으로 확인하는 고전적인 도형이고, 거울에
// 비추면 즉시 알아볼 수 있는 몇 안 되는 형태다. F 를 z-y 평면에 세워 두었으므로
// **z 부호를 뒤집는 손잡이 변환이 정확히 이 F 를 뒤집는다.**
//
// ── 마커도 FrameConvert 를 거친다
//
// 마커를 Unity 좌표로 직접 그리면 플래그를 뒤집어도 마커는 그대로 있고 대상만 뒤집혀,
// 무엇이 기준인지 알 수 없게 된다. 마커는 **계약 좌표로 정의되고 다른 모든 것과 같은
// 변환을 거쳐** 그려진다. 그래야 "계약이 말하는 +Z 가 화면의 어느 쪽인가"를 읽을 수 있다.

using UnityEngine;

namespace HybridDt.Twin.View
{
    public sealed class HandednessMarker : MonoBehaviour
    {
        private Vector3 _contractOrigin;
        private Font _font;
        private bool _built;
        private bool _builtFlip;

        public static HandednessMarker Create(Transform parent, Vector3 contractOrigin, Font font, bool flipHandedness)
        {
            GameObject go = new GameObject("HandednessMarker (비대칭 마커)");
            go.transform.SetParent(parent, false);

            HandednessMarker m = go.AddComponent<HandednessMarker>();
            m._contractOrigin = contractOrigin;
            m._font = font;
            m.Rebuild(flipHandedness);
            return m;
        }

        /// <summary>손잡이 플래그가 바뀌면 다시 세운다. 인스펙터에서 켜고 끄면 즉시 반영된다.</summary>
        public void EnsureFlip(bool flipHandedness)
        {
            if (_built && _builtFlip == flipHandedness) return;
            Rebuild(flipHandedness);
        }

        private void Rebuild(bool flip)
        {
            for (int i = transform.childCount - 1; i >= 0; i--) Destroy(transform.GetChild(i).gameObject);

            _built = true;
            _builtFlip = flip;

            // 계약 좌표계의 축 세 개. 색은 Unity 기즈모 관례를 따른다(x 빨강 · y 초록 · z 파랑).
            Axis(flip, new Vector3(1.6f, 0f, 0f), new Color(0.90f, 0.30f, 0.30f), "계약 +X");
            Axis(flip, new Vector3(0f, 1.6f, 0f), new Color(0.35f, 0.85f, 0.40f), "계약 +Y (위)");
            Axis(flip, new Vector3(0f, 0f, 1.6f), new Color(0.35f, 0.55f, 0.95f), "계약 +Z (정면)");

            BuildF(flip);

            GameObject caption = new GameObject("Caption");
            caption.transform.SetParent(transform, false);
            WorldLabel label = WorldLabel.Create(caption.transform, Place(flip, new Vector3(0f, 2.4f, 0f)), 0.14f, _font);
            label.SetText("비대칭 마커 (F)\n" + FrameConvert.Describe(flip));
            label.SetColor(new Color(1f, 0.95f, 0.7f));
        }

        private Vector3 Place(bool flip, Vector3 contractOffset)
        {
            return FrameConvert.ToUnity(
                _contractOrigin.x + contractOffset.x,
                _contractOrigin.y + contractOffset.y,
                _contractOrigin.z + contractOffset.z,
                flip);
        }

        private void Axis(bool flip, Vector3 contractEnd, Color color, string caption)
        {
            Vector3 a = Place(flip, Vector3.zero);
            Vector3 b = Place(flip, contractEnd);

            GameObject shaft = GameObject.CreatePrimitive(PrimitiveType.Cube);
            shaft.name = "Axis " + caption;
            Collider c = shaft.GetComponent<Collider>();
            if (c != null) Destroy(c);
            shaft.transform.SetParent(transform, true);
            shaft.transform.position = (a + b) * 0.5f;
            shaft.transform.rotation = Quaternion.LookRotation((b - a).normalized, Vector3.up);
            shaft.transform.localScale = new Vector3(0.05f, 0.05f, (b - a).magnitude);
            shaft.GetComponent<Renderer>().sharedMaterial = StatusPalette.Get(color, 1f);

            GameObject tipHolder = new GameObject("AxisLabel");
            tipHolder.transform.SetParent(transform, true);
            tipHolder.transform.position = b;
            WorldLabel label = WorldLabel.Create(tipHolder.transform, Vector3.zero, 0.11f, _font);
            label.SetText(caption);
            label.SetColor(color);
        }

        /// <summary>
        /// 계약 좌표의 z-y 평면에 선 대문자 F.
        /// 세로 기둥은 +Y, 두 팔은 +Z 로 뻗는다 — 손잡이 변환이 z 부호를 뒤집으므로
        /// **팔이 반대쪽으로 넘어가는 것**이 그대로 보인다.
        /// </summary>
        private void BuildF(bool flip)
        {
            Color ink = new Color(0.98f, 0.85f, 0.25f);

            // 세로 기둥.
            Block(flip, new Vector3(0f, 0.9f, 0.05f), new Vector3(0.08f, 1.8f, 0.10f), ink, "F-stem");
            // 위쪽 긴 팔.
            Block(flip, new Vector3(0f, 1.72f, 0.45f), new Vector3(0.08f, 0.16f, 0.80f), ink, "F-arm-top");
            // 가운데 짧은 팔.
            Block(flip, new Vector3(0f, 1.05f, 0.32f), new Vector3(0.08f, 0.14f, 0.54f), ink, "F-arm-mid");
        }

        private void Block(bool flip, Vector3 contractCenter, Vector3 size, Color color, string name)
        {
            GameObject go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = name;
            Collider c = go.GetComponent<Collider>();
            if (c != null) Destroy(c);
            go.transform.SetParent(transform, true);
            go.transform.position = Place(flip, contractCenter);
            go.transform.localScale = size;
            go.GetComponent<Renderer>().sharedMaterial = StatusPalette.Get(color, 1f);
        }
    }
}
