# 좌표 규약 — SDK(go1_sdk_pc) ↔ Unity 디지털트윈

2026-09-08 확정. 이전에는 규약이 없었고, 양쪽이 서로 다른 프레임을 가정한 채
각도 오프셋(`UNITY_YAW_OFFSET_RAD=90도`, `+180도` 보정, `invertSdkYawForUnity`,
`unityYawFineOffsetDeg=-3`)으로 어긋남을 덮고 있었다. 그 결과 같은 코드가
프리팹/씬에 따라 다르게 움직였다. 이 문서가 정본이다.

## 1. 규약

**SDK 는 Unity 월드 좌표를 그대로 쓴다.**

| 항목 | 정의 |
|---|---|
| 위치 | `state.x`, `state.z` = Unity world `X`, `Z` (m) |
| 방향 | `state.yaw` (rad) = Unity `transform.eulerAngles.y` 의 라디안. **시계방향 +**, `+Z` 기준 |
| 전진 단위벡터 | `(sin yaw, cos yaw)` |
| 우측 단위벡터 | `(cos yaw, -sin yaw)` |
| 경로 path-local | Unity 로컬 좌표 그대로. `x` = 우, `z` = 전진 |
| 경로 `yaw_deg` | `start_pose` 기준 **상대각**, 같은 시계+ 규약 |
| `start_pose.yaw_deg` | 가상 GO1 의 절대 Unity yaw (`eulerAngles.y`) |

IMU(`state.imu.rpy[2]`)는 **반시계 +** 다. 이 변환은 `go1_sdk_pc.cpp`
`RobotControl()` 의 아래 한 줄에서만 일어난다. 다른 어느 곳에서도 부호를 뒤집지 않는다.

```cpp
double yaw_unity = wrap_pi(-yaw_rel + UNITY_YAW_OFFSET_RAD);
```

따라서 **`GO1CoordinateMapper` 는 항등 변환이어야 한다.** swap / invert / offset
전부 0 이 정상이다. 값을 켜서 방향을 맞추려 하지 말 것 — 그게 이전 상태였다.

## 2. 시작 정합

절대 방위 센서가 없어 로봇이 실제로 어디를 보는지 알 수 없다. 그래서 **경로를 받는
순간** Unity 가 알려준 가상 GO1 의 출발 yaw 에 IMU 각을 짝지어 오프셋을 실측으로 잡는다.

```cpp
UNITY_YAW_OFFSET_RAD = wrap_pi(unity_start_yaw_rad + yaw_rel);   // yaw_unity == start
world_x = world_z = 0;                                            // 위치도 원점 리셋
```

로봇을 어느 방향에 놓든 자동 정합되므로 **Unity Z키(수동 정렬)는 더 이상 필요 없다.**
Z키는 원점 리셋(`YAW_CALIB`) 통지 역할만 남긴다.

## 3. 2026-09-08 변경 내역

### `pi/robot/go1_sdk_pc.cpp` (저장소 추적됨)

| 위치 | 변경 |
|---|---|
| 생성자 | `UNITY_YAW_OFFSET_RAD` 초기값 `M_PI/2` → `0.0` |
| `RobotControl()` | `yaw_unity = wrap_pi(yaw_rel + off)` → `wrap_pi(-yaw_rel + off)` |
| 경로 수신 | 오프셋 자동보정 식 `start - yaw_rel` → `start + yaw_rel` |
| 경로 수신 | `pts[0].yaw_deg` 덮어쓰기 제거 (절대각/상대각이 섞이던 자리) |
| `local_to_world()` | `ox=cos*lz+sin*lx, oz=sin*lz-cos*lx` → `ox=lx*cos+lz*sin, oz=-lx*sin+lz*cos` |
| `activate_path_from_points()` | `wp.yaw_world` 에서 `- p0.yaw_deg` 제거 |
| `run_path_follower()` | `atan2(dz,dx)` → `atan2(dx,dz)`, `cmd_wz = kp*err` → `-kp*err` |
| `send_unity_state()` | DR `(vx*cy-vy*sy, vx*sy+vy*cy)` → `(vx*sy-vy*cy, vx*cy+vy*sy)` |

### `HW/` Unity 프로젝트 (**이 저장소에서 gitignore — 버전관리 안 됨**)

되돌리려면 아래 "변경 전" 값으로 되돌린다.

`HW/Assets/Code/Go1/GO1CoordinateMapper.cs` — 필드 기본값

| 필드 | 변경 전 | 변경 후 |
|---|---|---|
| `pathSwapXZ` | `true` | `false` |
| `pathInvertZ` | `true` | `false` |
| `pathInvertYawSign` | `true` | `false` |
| `invertSdkYawForUnity` | `true` | `false` |

`GO1CoordinateMapper.SdkStateWorldDeltaToUnityBodyDelta()` — 부호 버그

```csharp
// 변경 전 (전진 성분 부호가 뒤집혀 있었다. 같은 클래스의
//          ValidateBodyAxisStateDeltaMapping() 이 이 상태로는 항상 FAIL 이다)
float forwardAmount = -Vector2.Dot(sdkDelta, sdkForward);
// 변경 후
float forwardAmount = Vector2.Dot(sdkDelta, sdkForward);
```

`HW/Assets/Code/UTM/UnityTeleopAndMirror.cs`

- `alignMapperOffsetOnZKey` (신규, 기본 `false`) 추가.
- `AlignVirtualYawToTargetAndNotify()` 의 `Mapper.AlignSdkYawToUnityTarget(...)` 호출을
  이 플래그로 감쌌다. 켜면 항등이어야 할 매퍼에 오프셋이 생겨 각도가 다시 어긋난다.

직렬화 값 — 아래 3개 파일의 `GO1CoordinateMapper` 블록을 전부 항등으로 통일했다.

| 파일 | 변경 전 |
|---|---|
| `HW/Assets/ADI/go1.prefab` | `pathSwapXZ:1 pathInvertZ:1 pathInvertYawSign:1 invertSdkYawForUnity:1 unityYawFineOffsetDeg:-3` |
| `HW/Assets/prefab/go1 1.prefab` | `invertBodyAxisStateLateral:1 invertSdkYawForUnity:1` |
| `HW/Assets/Scenes/Go1_Training.unity` | `pathSwapXZ:1 pathInvertZ:1 pathInvertYawSign:1 invertBodyAxisStateLateral:1 invertSdkYawForUnity:1` |

`HW/Assets/lab.unity` 는 매퍼 값을 직렬화하지 않아 C# 기본값을 따른다(수정 불필요).

## 4. 검증

### 오프라인 (실기 없이)

```bash
python pi/robot/tools/coord_contract_check.py
```

Unity 경로계획 → UDP 송신 → C++ 경로추종/DR → 상태 송신 → Unity 표시 전 구간을
양쪽 코드 그대로 재현한다. 출발 yaw 0/37/90/−120/180도 × 경로 4종(직진·ㄱ자·ㄴ자·S자)에서

- 계획 경로와 C++ waypoint 의 최대 오차 < 1e-9 m
- 표시 yaw == 가상 GO1 출발 yaw
- 실로봇 좌회전 → Unity 표시각 감소(시계+ 규약이므로 좌회전)

규약이나 매퍼 값을 건드리면 이 스크립트부터 돌려서 회귀를 잡는다.

### 실기 (pi7 + 로봇 + Unity)

1. pi7 에서 빌드 · 기동
   ```bash
   cp ~/hw/pi/robot/go1_sdk_pc.cpp ~/go1sdk/ && cd ~/go1sdk
   g++ -O2 -std=c++17 -I include go1_sdk_pc.cpp libunitree_legged_sdk.a -lpthread -o go1_sdk_pc
   sudo systemctl restart go1-sdk
   ```
2. 로봇을 **일부러 비스듬히**(0/180도가 아닌 각도로) 놓는다. 예전 버그는 0/180도에서
   우연히 맞아 안 보였다.
3. Unity Play → 경로 생성. `[PATH]` 로그의 `correction` 이 0 에 가까운지 확인.
4. 가상 GO1 의 머리 방향이 실로봇과 같은 쪽인지 눈으로 확인. Z키는 누르지 않는다.
5. 실로봇을 좌회전시켰을 때 화면의 가상 GO1 도 좌회전하는지 확인.
6. 2회차 경로(리플랜)에서도 1~5 가 유지되는지 확인.

---

## 부록. 중립 좌표로의 이행 (2026-09-10 추가)

### 왜 지금 규약이 결합인가

위 규약은 **SDK 가 Unity 월드 좌표를 그대로 쓴다**로 되어 있다. 동작에는 문제가 없지만,
이건 **트윈이 바뀌면 로봇 코드가 바뀌는** 구조다. Unity 를 다른 트윈으로 교체하거나
로봇을 레인보우로보틱스로 바꾸면 양쪽이 같이 흔들린다
(docs/ARCHITECTURE_ALIGNMENT.md §2 — 로봇과 1:1 결합 금지).

### 목표 — 물리 좌표를 정본으로

| 항목 | 지금 (결합) | 목표 (중립) |
|---|---|---|
| 프레임 | Unity 월드 X/Z | **건물 기준 로컬 ENU** (x=동, y=북, z=상, m) |
| 방향 | Unity `eulerAngles.y`, 시계+ | **yaw, 반시계+, +x 기준 (rad)** |
| 원점 | Unity 씬 원점 | 건물/구역 기준점 (`zone_id` 가 정의) |
| 변환 주체 | 로봇(SDK) | **트윈**(받는 쪽이 자기 프레임으로 바꾼다) |

변환식(트윈이 수행):

```
unity_x = enu_x
unity_z = enu_y
unity_yaw_deg = 90 - degrees(enu_yaw)      # 반시계·+x 기준 -> 시계·+Z 기준
```

### 언제 바꾸나 — 지금은 아니다

**직결 경로(15101)를 쓰는 동안은 현행 규약을 유지한다.** 지금 바꾸면 Unity 가 즉시 깨지고
시연이 멈춘다. 이행은 서버 경유(ARCHITECTURE_ALIGNMENT §2-3 **2단계**)와 **같이** 한다:

1. 서버가 로봇 상태를 받기 시작한다(백엔드 #16 회신 필요).
2. 그 경로의 페이로드에 `frame: "enu_local"` 을 명시하고 물리 좌표를 싣는다.
3. 트윈이 새 경로로 갈아탄다.
4. 직결(15101)을 걷어낸다. 이때 이 문서의 본문(Unity 좌표 규약)이 폐기된다.

프레임 이름을 페이로드에 **명시**하는 것이 핵심이다. 지금 사고가 났던 이유가
"양쪽이 서로 다른 프레임을 가정한 채 각도 오프셋으로 덮은 것"이었는데, 프레임을
값으로 싣고 다니면 그 종류의 어긋남이 애초에 성립하지 않는다.
