using UnityEngine;


/*
===============================================================================
CameraIdleMotion.cs
-------------------------------------------------------------------------------
카메라(또는 오브젝트)에 자연스러운 Idle 흔들림(Motion)을 적용하는 스크립트

[개요]
Sin 파형 기반의 위치(Position) + 회전(Rotation) 오프셋을 적용하여
정지 상태에서도 약간의 움직임을 만들어준다.

목적:
- VR 환경에서 정적인 화면의 답답함 완화
- GO1 카메라 뷰에 "호흡/미세 흔들림" 연출
- 디지털 트윈 데모에서 현실감 향상

-------------------------------------------------------------------------------
[동작 원리]

1) 시작 시점(Start)
   - 현재 localPosition / localRotation 저장
   - 랜덤 seed 값 생성 (여러 카메라가 동일하게 움직이지 않도록)

2) 매 프레임(Update)
   - Time.time 기반 Sin 함수로 주기 운동 계산
   - Position:
       offset = sin(t * speed) * amplitude
   - Rotation:
       rotOffset = sin(t * speed) * amplitude
   - 초기값(startPos, startRot)에 오프셋을 더해 적용

-------------------------------------------------------------------------------
[Inspector 파라미터]

▶ Position Motion
- positionAmplitude : 각 축 이동 최대 범위
- positionSpeed     : 각 축 움직임 속도

▶ Rotation Motion
- rotationAmplitude : 각 축 회전 최대 각도(degree)
- rotationSpeed     : 각 축 회전 속도

-------------------------------------------------------------------------------
[주의사항]

- XR Origin의 Camera에 직접 적용 시
  XROriginCCCenterFollowHMD 같은 스크립트와 충돌 가능
- VR HMD 실제 위치 추적과 함께 쓰면 멀미 유발 가능
- 반드시 localPosition / localRotation 기준으로 동작

-------------------------------------------------------------------------------
[권장 사용 케이스]

✔ GO1 1인칭 카메라 연출
✔ Cutscene / Demo 화면
✔ 고정 카메라에 생동감 추가
✔ 실험 시 "완전 정지 화면" 방지

-------------------------------------------------------------------------------
[확장 아이디어]

- breathing 모드 / wind 모드 분리
- 랜덤 노이즈(Perlin Noise) 기반 흔들림 추가
- 속도에 따라 흔들림 강도 변화 (로봇 이동 시 증가)
- VR 멀미 방지를 위한 amplitude 자동 감소 옵션

===============================================================================
*/

public class CameraIdleMotion : MonoBehaviour
{
    [Header("Position Motion")]
    [SerializeField] private Vector3 positionAmplitude = new Vector3(0.15f, 0.05f, 0.2f);
    [SerializeField] private Vector3 positionSpeed = new Vector3(0.3f, 0.2f, 0.25f);

    [Header("Rotation Motion")]
    [SerializeField] private Vector3 rotationAmplitude = new Vector3(0.8f, 1.2f, 0.0f);
    [SerializeField] private Vector3 rotationSpeed = new Vector3(0.15f, 0.2f, 0.1f);

    private Vector3 startPos;
    private Quaternion startRot;
    private float seed;

    private void Start()
    {
        startPos = transform.localPosition;
        startRot = transform.localRotation;
        seed = Random.Range(0f, 100f);
    }

    private void Update()
    {
        float t = Time.time + seed;

        Vector3 offset = new Vector3(
            Mathf.Sin(t * positionSpeed.x) * positionAmplitude.x,
            Mathf.Sin(t * positionSpeed.y) * positionAmplitude.y,
            Mathf.Sin(t * positionSpeed.z) * positionAmplitude.z
        );

        Vector3 rotOffset = new Vector3(
            Mathf.Sin(t * rotationSpeed.x) * rotationAmplitude.x,
            Mathf.Sin(t * rotationSpeed.y) * rotationAmplitude.y,
            Mathf.Sin(t * rotationSpeed.z) * rotationAmplitude.z
        );

        transform.localPosition = startPos + offset;
        transform.localRotation = startRot * Quaternion.Euler(rotOffset);
    }
}
