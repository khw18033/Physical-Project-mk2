// Assets/Scripts/View/OrbitCamera.cs
//
// 씬을 돌려 보기 위한 최소 카메라. **뷰어의 계약과 무관한 편의 기능**이며,
// 트윈 상태를 하나도 읽지 않는다(대상 Transform 을 따라가지 않는다는 뜻이다).
// 에디터에서 직접 카메라를 배치하면 TwinViewer 의 createCameraIfMissing 을 끄면 된다.
//
// 조작 — 우클릭 드래그: 회전 · 휠: 확대 · 가운데 드래그: 평행 이동

using UnityEngine;

namespace HybridDt.Twin.View
{
    public sealed class OrbitCamera : MonoBehaviour
    {
        public Vector3 target = Vector3.zero;
        public float distance = 34f;
        public float yaw = 0f;
        public float pitch = 30f;

        public float rotateSpeed = 220f;
        public float zoomSpeed = 14f;
        public float panSpeed = 0.05f;

        private void Start()
        {
            Vector3 offset = transform.position - target;
            if (offset.sqrMagnitude > 0.001f) distance = offset.magnitude;
            Apply();
        }

        private void LateUpdate()
        {
            if (Input.GetMouseButton(1))
            {
                yaw += Input.GetAxis("Mouse X") * rotateSpeed * Time.unscaledDeltaTime;
                pitch -= Input.GetAxis("Mouse Y") * rotateSpeed * Time.unscaledDeltaTime;
                pitch = Mathf.Clamp(pitch, 5f, 85f);
            }

            if (Input.GetMouseButton(2))
            {
                Vector3 right = transform.right;
                Vector3 up = transform.up;
                target -= (right * Input.GetAxis("Mouse X") + up * Input.GetAxis("Mouse Y")) * distance * panSpeed;
            }

            float scroll = Input.GetAxis("Mouse ScrollWheel");
            if (Mathf.Abs(scroll) > 0.0001f)
            {
                distance = Mathf.Clamp(distance - scroll * zoomSpeed * Mathf.Max(1f, distance * 0.1f), 3f, 300f);
            }

            Apply();
        }

        private void Apply()
        {
            Quaternion rot = Quaternion.Euler(pitch, yaw, 0f);
            transform.position = target + rot * new Vector3(0f, 0f, -distance);
            transform.rotation = rot;
        }
    }
}
