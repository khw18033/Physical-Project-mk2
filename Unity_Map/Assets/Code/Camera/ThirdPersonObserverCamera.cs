using UnityEngine;

/*
===============================================================================
ThirdPersonObserverCameraFollowYaw.cs
-------------------------------------------------------------------------------
타겟(로봇/피벗)의 yaw(방향)에 따라 함께 회전하며 따라가는 3인칭 관찰 카메라

[개요]
이 스크립트는 target의 로컬 좌표계 기준(localOffset)으로 카메라 위치를 유지한다.
따라서 target이 회전(yaw)하면 카메라도 같은 방향으로 돌아가면서
항상 “로봇 뒤/위에서 따라보는” 3인칭 관찰 시점을 제공한다.

또한 lookAtLocalOffset을 target 기준으로 변환하여
항상 로봇의 약간 앞쪽/위쪽을 바라보도록 설정할 수 있다.

-------------------------------------------------------------------------------
[추천 타겟]
- 로봇 본체 바로 Transform보다
  방향 기준점(ForwardPivot) 같은 피벗 오브젝트를 target으로 두는 것이 안정적이다.
  (로봇 애니메이션/기울기/자식 구조 변화에 덜 영향을 받음)

-------------------------------------------------------------------------------
[핵심 파라미터]

1) target
   - 따라갈 기준 Transform (추천: ForwardPivot)

2) localOffset (Local to Target)
   - target 기준 로컬 오프셋
   - 예) (0, 6.5, -4.5) → 위에서 약간 뒤쪽 “가까운 탑뷰 3인칭” 느낌

3) lookAtLocalOffset
   - target 기준으로 바라볼 지점의 로컬 오프셋
   - 로봇 중심보다 약간 앞/위쪽으로 맞추면 보기 좋음

4) Smoothing
   - positionSmoothTime : SmoothDamp로 위치 이동의 부드러움(작을수록 빠름)
   - rotationSmoothSpeed: Slerp 회전 추종 속도(클수록 빠름)

-------------------------------------------------------------------------------
[동작 흐름]

LateUpdate()
  1) desiredPos = target.TransformPoint(localOffset)
     → target 로컬 오프셋을 월드 좌표로 변환
  2) transform.position = SmoothDamp(현재, desiredPos, ...)
     → 카메라 위치 부드럽게 추종
  3) lookAtWorld = target.TransformPoint(lookAtLocalOffset)
     desiredRot = LookRotation(lookAtWorld - cameraPos)
  4) transform.rotation = Slerp(현재, desiredRot, speed * dt)
     → 카메라가 target을 자연스럽게 바라보도록 회전

-------------------------------------------------------------------------------
[주의사항]

- LateUpdate()를 사용하므로:
  target 이동/회전이 Update()에서 완료된 뒤 카메라가 따라가
  떨림(jitter)이 줄어든다.
- target이 null이면 아무 동작도 하지 않는다.
- rotationSmoothSpeed는 “초당 속도 개념”에 가까우므로
  너무 크면 급격히 돌아 어지러울 수 있음(특히 VR에서는 주의)

-------------------------------------------------------------------------------
[확장 가능]

- target 속도에 따라 localOffset 자동 변경(가속 시 더 멀리)
- 장애물 가림 방지(레이캐스트로 카메라 거리 조절)
- y축 고정/제한(탑뷰 유지)
- 마우스/스틱으로 orbit 카메라(사용자 관찰각 조절)

===============================================================================
*/

public class ThirdPersonObserverCameraFollowYaw : MonoBehaviour
{
    [Header("Target (추천: ForwardPivot)")]
    [SerializeField] private Transform target;

    [Header("Offset (Local to Target)")]
    // 가까운 탑뷰 3인칭 느낌
    [SerializeField] private Vector3 localOffset = new Vector3(0f, 6.5f, -4.5f);

    [Header("Look At")]
    [SerializeField] private Vector3 lookAtLocalOffset = new Vector3(0f, 0.6f, 0.8f);

    [Header("Smoothing")]
    [SerializeField] private float positionSmoothTime = 0.08f;
    [SerializeField] private float rotationSmoothSpeed = 14f;

    private Vector3 _posVelocity;

    private void LateUpdate()
    {
        if (target == null) return;

        Vector3 desiredPos = target.TransformPoint(localOffset);
        transform.position = Vector3.SmoothDamp(transform.position, desiredPos, ref _posVelocity, positionSmoothTime);

        Vector3 lookAtWorld = target.TransformPoint(lookAtLocalOffset);
        Quaternion desiredRot = Quaternion.LookRotation(lookAtWorld - transform.position, Vector3.up);
        transform.rotation = Quaternion.Slerp(transform.rotation, desiredRot, rotationSmoothSpeed * Time.deltaTime);
    }
}



