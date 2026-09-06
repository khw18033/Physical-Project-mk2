using UnityEngine;
using Unity.XR.CoreUtils; // XROrigin

/*
===============================================================================
XROriginCCCenterFollowHMD.cs
-------------------------------------------------------------------------------
XR Origin의 HMD(카메라) 위치/키(height)에 맞춰 CharacterController의
center / height를 자동으로 갱신하는 보정 스크립트

[개요]
VR에서 플레이어의 머리(HMD) 위치는 계속 움직이는데,
CharacterController 콜라이더가 고정되어 있으면 다음 문제가 발생한다.

- 머리는 앞으로 가 있는데 콜라이더는 뒤에 남아 충돌이 이상해짐
- 키가 큰/작은 사용자에서 콜라이더 높이가 맞지 않음
- 경사/계단/문턱에서 몸통 충돌이 부자연스러움

이 스크립트는 매 프레임 LateUpdate에서
XR Origin 카메라(HMD)의 로컬 위치/높이를 읽고,
CharacterController가 “HMD 중심을 따라가도록” center와 height를 조정한다.

-------------------------------------------------------------------------------
[필수 조건]

- 이 스크립트가 붙은 GameObject에 CharacterController가 있어야 함
  (RequireComponent 적용)

- xrOrigin:
  - Inspector에서 지정하거나
  - 같은 오브젝트에 XROrigin이 있으면 자동으로 GetComponent로 가져옴

-------------------------------------------------------------------------------
[동작 방식]

LateUpdate()
  1) xrOrigin.Camera 존재 확인
  2) 카메라의 Origin Space 로컬 위치(camLocal)를 읽음
     - xrOrigin.CameraInOriginSpacePos
  3) 카메라의 키(height)를 읽어서 cc.height를 설정
     - xrOrigin.CameraInOriginSpaceHeight
     - minHeight~maxHeight 범위로 Clamp
  4) cc.center를 HMD 위치(x,z)에 맞춰 이동
     - center.x = camLocal.x
     - center.z = camLocal.z
     - center.y = (height/2) + skinWidth 보정
  5) cc.skinWidth를 지정한 값으로 유지

-------------------------------------------------------------------------------
[파라미터 설명]

- skinWidth:
  - 벽/바닥 접촉 시 안정성을 위한 여유 값
  - 너무 크면 좁은 공간에서 밀림이 커질 수 있음

- minHeight / maxHeight:
  - 사용자 키가 비정상적으로 튀는 경우(트래킹 오류 등) 대비 안전 범위

-------------------------------------------------------------------------------
[주의사항]

- 이 스크립트는 CharacterController “중심”만 따라가게 하므로,
  실제 이동은 XR 이동 시스템(Continuous Move Provider 등)과 함께 사용해야 함
- cc.center를 바꾸는 타이밍은 LateUpdate가 안전한 편
  (카메라 트래킹 업데이트 이후 반영)

-------------------------------------------------------------------------------
[확장 가능]

- 앉기/서기 상태에 따른 minHeight 동적 변경
- HMD 높이 변화가 급격할 때 스무딩(EMA) 적용
- 캡슐 콜라이더 대신 CapsuleCollider 사용 구조로 확장

===============================================================================
*/

[RequireComponent(typeof(CharacterController))]
public class XROriginCCCenterFollowHMD : MonoBehaviour
{
    public XROrigin xrOrigin;
    public float skinWidth = 0.08f;  
    public float minHeight = 1.0f;
    public float maxHeight = 2.2f;

    CharacterController cc;

    void Awake()
    {
        cc = GetComponent<CharacterController>();
        if (!xrOrigin) xrOrigin = GetComponent<XROrigin>();
    }

    void LateUpdate()
    {
        if (!xrOrigin || !xrOrigin.Camera) return;

        Vector3 camLocal = xrOrigin.CameraInOriginSpacePos;

        float h = Mathf.Clamp(xrOrigin.CameraInOriginSpaceHeight, minHeight, maxHeight);
        cc.height = h;

        Vector3 c = cc.center;
        c.x = camLocal.x;
        c.z = camLocal.z;
        c.y = (cc.height * 0.5f) + cc.skinWidth;
        cc.center = c;

        cc.skinWidth = skinWidth;
    }
}