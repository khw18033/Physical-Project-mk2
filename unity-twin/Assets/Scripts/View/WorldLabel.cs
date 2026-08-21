// Assets/Scripts/View/WorldLabel.cs
//
// 대상 위에 붙는 이름표 (VZ-I-03 — display_name, 없으면 id).
//
// 빌트인 TextMesh 를 쓴다. TextMeshPro 를 쓰면 폰트 에셋을 만들어야 하고, 이번 범위는
// "빈 씬에 스크립트 하나만 붙이면 돈다"가 요건이라 에셋을 요구하는 선택은 맞지 않는다.
//
// ── 카메라를 읽는 것에 대해
//
// 이 컴포넌트는 씬의 카메라 Transform 을 읽어 이름표를 돌려 세운다(빌보드). "씬 안의
// 오브젝트가 서로의 Transform 을 직접 읽는 경로를 두지 않는다"는 이번 작업의 규칙은
// **트윈 상태(위치·상태)가 파이프라인을 우회하는 것**을 막기 위한 것이고, 빌보드는
// 트윈 상태를 하나도 나르지 않는다. 그래서 여기만 예외로 두되, 예외인 이유를 남긴다 —
// 다음 사람이 "여기도 Transform 읽네" 하고 위치를 읽기 시작하면 규칙이 무너진다.

using UnityEngine;

namespace HybridDt.Twin.View
{
    public sealed class WorldLabel : MonoBehaviour
    {
        private TextMesh _text;
        private Transform _cameraTransform;

        public static WorldLabel Create(Transform parent, Vector3 localOffset, float size, Font font)
        {
            GameObject go = new GameObject("Label");
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localOffset;

            WorldLabel label = go.AddComponent<WorldLabel>();
            TextMesh tm = go.AddComponent<TextMesh>();

            tm.anchor = TextAnchor.LowerCenter;
            tm.alignment = TextAlignment.Center;
            tm.characterSize = size;
            tm.fontSize = 64;
            tm.color = Color.white;
            if (font != null)
            {
                tm.font = font;
                MeshRenderer mr = go.GetComponent<MeshRenderer>();
                if (mr != null) mr.sharedMaterial = font.material;
            }

            label._text = tm;
            return label;
        }

        public void SetText(string value)
        {
            if (_text != null) _text.text = value;
        }

        public void SetColor(Color color)
        {
            if (_text != null) _text.color = color;
        }

        private void LateUpdate()
        {
            if (_cameraTransform == null)
            {
                Camera cam = Camera.main ?? Camera.current;
                if (cam == null) return;
                _cameraTransform = cam.transform;
            }

            // 카메라를 향해 세운다. y 축만 돌리면 위에서 내려다볼 때 눕지 않는다.
            Vector3 forward = transform.position - _cameraTransform.position;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.0001f) return;
            transform.rotation = Quaternion.LookRotation(forward.normalized, Vector3.up);
        }
    }
}
