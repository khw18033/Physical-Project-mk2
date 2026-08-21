// Assets/Scripts/View/FrameConvert.cs
//
// ┌──────────────────────────────────────────────────────────────────────────┐
// │ 축을 만지는 코드는 **이 파일 안에만** 있어야 한다.                            │
// │ 다른 곳에서 x·y·z 를 바꿔 넣거나 부호를 뒤집는 줄이 하나라도 생기면          │
// │ 이 파일의 존재 의미가 사라진다.                                            │
// └──────────────────────────────────────────────────────────────────────────┘
//
// ── 이것은 좌표 변환이 아니라 **표현 변환**이다
//
// BE-C-04 · DT-03 에 따라 로컬→글로벌 변환과 좌표계 규약은 **백엔드 단독 책임**이고,
// 가시화는 변환 로직을 구현하지 않는다. 이 파일은 그 금지의 예외가 아니다.
//
// 두 가지가 층이 다르다.
//
//   좌표 변환 (금지)        어느 기준점에서 잰 값인가를 바꾸는 일.
//                          로봇 로컬 → 구역 → 사이트 전역. **백엔드가 한다.**
//                          여기서 하면 두 클라이언트가 각자 다른 전역 좌표를 갖게 된다.
//
//   표현 변환 (여기)        같은 점을 특정 렌더러의 관례로 **그리는** 일.
//                          Unity 는 왼손 좌표계이고, 계약(y=위 · 바닥 x-z · 미터)은
//                          축만 정하고 손잡이를 말하지 않는다. 값이 오른손 관례라면
//                          같은 점이 좌우가 뒤집힌 채 그려진다.
//
// ── 왜 백엔드가 아니라 여기서 하는가
//
// 백엔드가 특정 렌더러의 관례를 떠안기 시작하면 **뷰어가 둘이 될 때 무너진다.**
// 웹 대시보드와 Unity 가 손잡이 관례가 다른데 백엔드가 한쪽에 맞춰 주면, 다른 쪽은
// 되돌려야 하고 그 되돌림은 반드시 어딘가에 흩어진다. 표현은 표현하는 쪽에서 흡수하는 것이
// 뷰어 수가 늘어도 계약이 하나로 남는 유일한 배치다. (VZ-I-01 을 「브라우저」에서
// 「가시화 뷰어」로 일반화한 것과 같은 논리다 — 특정 클라이언트의 사정을 계약에 넣지 않는다.)
//
// ── 아직 합의 전이다
//
// 손잡이 규약은 회의 안건으로 올라가 있다(2026-08-21 17:30 보고서 미결 5번).
// 그래서 플래그로 두고 인스펙터에서 뒤집을 수 있게 했으며, 기본값과 근거는
// unity-twin/README.md 에 적었다. 합의되면 플래그를 없애고 한쪽으로 고정한다.

using UnityEngine;

namespace HybridDt.Twin.View
{
    public static class FrameConvert
    {
        /// <summary>
        /// 계약 좌표 → Unity 월드 좌표.
        ///
        /// <paramref name="flipHandedness"/> 가 참이면 z 부호를 뒤집는다. y=위 인 오른손계에서
        /// 왼손계로 옮길 때 필요한 최소 조작이 그것이고, x 를 뒤집어도 결과는 거울상으로 같지만
        /// **"정면(+z)이 유지되고 좌우가 바뀐다"** 쪽이 관제 화면에서 읽기 쉬워 z 를 골랐다.
        /// 두 선택 중 무엇인지는 씬의 비대칭 마커로 눈으로 확인한다(HandednessMarker).
        /// </summary>
        public static Vector3 ToUnity(double x, double y, double z, bool flipHandedness)
        {
            return new Vector3((float)x, (float)y, flipHandedness ? (float)-z : (float)z);
        }

        /// <summary>
        /// Node 원점의 yaw(도) → Unity yaw.
        /// 손잡이를 뒤집으면 회전 방향도 함께 뒤집힌다. 위치만 뒤집고 회전을 놔두면
        /// 배치는 맞는데 방향이 어긋나는, **눈으로 잡기 가장 어려운 상태**가 된다.
        /// </summary>
        public static Quaternion YawToUnity(double yawDeg, bool flipHandedness)
        {
            return Quaternion.Euler(0f, flipHandedness ? (float)-yawDeg : (float)yawDeg, 0f);
        }

        /// <summary>현재 설정을 사람이 읽는 한 줄로. 진단 오버레이와 README 설명이 같은 문구를 쓴다.</summary>
        public static string Describe(bool flipHandedness)
        {
            return flipHandedness
                ? "손잡이 변환 ON — 수신 좌표를 오른손계로 보고 z 부호를 뒤집어 그린다"
                : "손잡이 변환 OFF — 수신 좌표를 Unity 왼손계 값으로 그대로 그린다 (기본값)";
        }
    }
}
