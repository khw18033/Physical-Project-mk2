# 새 PC 인수인계 — Tailscale 로 받는 구성이 다른 환경에서도 되는지 확인 (2026-11-25)

이 문서는 새 PC 에서 작업을 이어받는 사람(또는 Claude)이 앞 내용을 모른다고 보고 썼다.
목표는 하나다: **연구실 공유기 없이, Tailscale 만으로 Unity 디지털 트윈이 데이터를 받는지 확인한다.**

## 0. 반드시 지킬 것

1. **실제 Go1 을 움직이는 명령은 보내기 직전에 매번 사용자에게 허락받는다.** 이전에 받은 허락은 다음 번에 쓰지 않는다.
   Unity 에서 Play 후 M 키, `RealRunLauncher`, 경로 포트 15110 으로 가는 모든 전송이 여기에 든다.
2. 2026-11-24 첫 실주행에서 Go1 이 계획과 다른 방향으로 1.5 m 넘게 걸어가 사람이 손으로 잡았다.
   원인과 다시 시도하기 전 확인 항목은 [`README.md`](README.md) 의 "실주행 주의 사항"에 있다. **이 문제는 아직 고치지 않았다.**
3. `lab`·`mall`·`capstone_hall` 씬에는 로봇 주소가 pi7 의 Tailscale 주소로 저장돼 있다.
   그래서 **에디터에서 M 키만 눌러도 실제 로봇으로 경로가 간다.** 로봇이 켜져 있을 때는 주의한다.
4. pi 들과 서버 노트북은 지금까지 읽기만 했다. 설정을 바꾸려면 사용자에게 먼저 묻는다.
5. 접속 암호는 저장소에 없다. 필요하면 사용자에게 묻는다.

## 1. 전체 구성

- 논문 1: 기존 방식(로봇이 탐지 → 정지 → 재탐색)과 제안 방식(인프라 360° 카메라가 먼저 탐지 → 트윈이 경로를 바꿈 → 로봇은 멈추지 않음) 비교.
- Unity 프로젝트: Unity 6000.3.5f2, URP, ML-Agents. 원래 PC 의 `D:\Go1_Unity`.
- 이 Go1 모델의 앞 방향은 `transform.forward` 가 아니라 `-transform.right` 다.

| 데이터 | 어디서 | 어떻게 받나 | Unity 로 들어오는 곳 |
|---|---|---|---|
| Go1 정면 탐지 (서버가 처리한 결과) | 서버 노트북 Redis `100.125.104.23:6380` | Tailscale, `datastream_front_reader.py` | UDP 5012 → `Go1FrontGuardReceiver` |
| Go1 정면 영상 (이 PC 에서 직접 탐지할 때) | pi7 `http://100.72.109.9:8090/stream/1` | Tailscale, `go1_front_guard.py` | UDP 5012 (위와 같은 포트. 둘 중 하나만 돌린다) |
| 로봇 상태, 경로 전송 | pi7 `100.72.109.9` (15100~15104, 경로 15110, 상태 알림 5009) | Tailscale | `UnityTeleopAndMirror`, `GO1LocalPathUdpSender`, `Go1ObstacleJsonReceiver` |
| 360° 카메라 탐지 | 카메라 `192.168.100.124` | **랜선 직접 연결 (Tailscale 예외, 사용자 결정)**, `anchor360_local.py` | UDP 5010 → `Anchor360ObstacleReceiver` |
| 360° 영상 속 마커로 잡은 로봇 위치 | 위와 같음 | `anchor360_marker_live.py` | UDP 5013 → `Robot360MarkerReceiver` |

Tailscale 주소 (2026-11-25 기준):

| 기기 | 주소 | 비고 |
|---|---|---|
| 원래 Unity PC | `100.68.72.33` | 새 PC 는 주소가 다르다 |
| 서버 노트북 (WSL, 데이터 스트림) | `100.125.104.23` | 같은 노트북의 Windows 쪽은 `100.112.161.94` |
| pi7 (Go1 A) | `100.72.109.9` | 랩 공유기 주소는 `192.168.50.170` |

## 2. 새 PC 에 필요한 것

1. **Tailscale**: 같은 계정 네트워크에 들어가야 한다. `tailscale status` 에 pi7 과 서버 노트북이 보이는지 확인.
2. **Python 3.10**: `datastream_front_reader.py` 는 추가 패키지 없이 돈다. `go1_front_guard.py`·`anchor360_local.py` 는 탐지 모델과 가중치가 필요하다 ([`../anchor360/local/README.md`](../anchor360/local/README.md)).
3. **Unity 프로젝트**: 원래 PC 의 프로젝트를 복사해 올 수 없다. 이 저장소에는 바뀐 소스만 있고 씬·모형·정책 파일은 없다.
   무엇을 어디서 받았고 무엇이 직접 만든 것인지는 아래 **6. Unity 프로젝트 구성과 에셋 출처**에 적었다.
   **Unity 없이도 3-1 과 3-3 의 1·2 번(Redis 읽기, pi7 연결·영상)은 확인할 수 있다.**
4. Unity 를 창 없이 돌리는 방법 (에디터를 닫고 실행. 그림을 그리는 작업에는 `-nographics` 를 붙이지 않는다):
   ```sh
   Unity.exe -batchmode -projectPath <프로젝트> -executeMethod <클래스.메서드> -quit -logFile <로그>
   ```

## 3. 확인 순서 (로봇을 움직이지 않는 것부터)

각 단계에서 **실제로 본 것만** 됐다고 적는다. 안 되면 거기서 멈추고 원인을 적는다.

### 3-1. 서버 Redis 가 Tailscale 로 읽히는가 — 로봇과 무관

```sh
python anchor360/local/datastream_front_reader.py --seconds 10
```

- `no_video [마지막 결과가 N 초 전 것]` 이 나오면 연결은 되고 서버에 새 데이터가 없는 것이다.
- `--replay` 를 붙이면 남아 있는 마지막 결과를 나이와 상관없이 보낸다 (형식 확인용).
- 서버가 pi7 영상을 받아 처리하고 있을 때는 `clear / warn / stop` 이 바뀌며 나와야 한다. **이 상태는 아직 한 번도 확인하지 못했다.**

Redis 키 형식:

| 키 | 내용 |
|---|---|
| `camera_stream:<소스>` | 원본 프레임(JPEG)과 헤더 |
| `state_stream:<소스>` | 기기의 MQTT 메시지 |
| `vision_stream:<소스>:yoloe` | 탐지: `label`, `confidence`, `bbox`, `polygon` |
| `vision_stream:<소스>:unidepth` | 위에 `depth_m`, `uv`, `intrinsics` 추가. 이름 제한이 없어 배경이 탐지로 섞인다 |
| `vision_stream:<소스>:targeted` | 사람·의자만. 거리 `dist.value` (m). **리더 기본값** |
| `vision_depth:<소스>:unidepth` | 깊이 지도 전체 |

소스는 `robot1`(pi7 Go1 정면), `ep-001`, `pi13` 을 봤다. 결과는 `result` 칸의 JSON (`schema_version` 2.0) 이다.
`cam360` 은 주소 표에는 있으나 Redis 에 결과가 올라온 적이 없다.

### 3-2. Unity 에 그려지는가 — 로봇과 무관

Unity 에서 `lab` 씬을 Play 하고 3-1 의 리더를 돌린다. 로봇 앞에 탐지 상자(사람이면 사람 모형)가 그려지는지 본다.
**M 키는 누르지 않는다.** 이 화면 확인은 원래 PC 에서도 하지 않았다.

### 3-3. pi7 이 Tailscale 로 닿는가 — 로봇은 켜져 있되 서 있기만 한다

1. `tailscale ping 100.72.109.9`
2. 브라우저나 `curl` 로 `http://100.72.109.9:8090/stream/1` 이 열리는가.
3. pi7 이 보내는 상태값이 새 PC 로 들어오는가. Unity 를 Play 한 채(M 키는 누르지 않는다) 가상 로봇이 실제 자세를 따라오는지 본다.
   - 안 들어오면 pi7 쪽에 받는 PC 주소가 랩 주소로 고정돼 있을 수 있다. pi7 의 `go1-sdk` 서비스 설정을 확인하고, 바꿔야 하면 사용자에게 묻는다. **이 부분은 pi7 이 꺼져 있어 확인하지 못했다.**
4. 상태 알림(UDP 5009, `state_change`)이 Unity 에 도착하는가. 11-24 사고 때는 오지 않았다.

### 3-4. 실주행 — 사용자 허락을 받은 뒤에만

3-3 이 모두 되고, `README.md` "실주행 주의 사항"의 네 항목을 확인하고, 사용자가 그 자리에서 허락했을 때만 한다.
급할 때: `python unity-twin/evaluation/real_run/estop.py` (주소 없이 실행하면 Tailscale·랩 주소 양쪽으로 `PATH_CANCEL` 을 보낸다).

### 3-5. 360° 카메라 — 랜선

카메라 수신기를 새 PC 유선 랜에 꽂고, 유선 랜이 `192.168.100.x` 대역으로 잡혀야 한다. 그다음 `run_anchor360_local.bat`.
카메라 제어 세션은 한 번에 하나만 된다. 장소가 바뀌면 `anchor360_calib*.json` 의 카메라 위치·방향을 다시 맞춰야 한다.

## 4. 지금까지 된 것과 안 된 것

된 것 (원래 PC 에서 확인):

- 서버 Redis 를 Tailscale 로 읽었다. 어제(11-24) 남은 `robot1` 결과로 리더가 의자 1개·사람 2명을 앞 1.5 ~ 2.4 m 로 바꿔 UDP 5012 로 내보냈다.
- 사람 모형 표시, 쇼핑몰·발표장 맵, 가상 실험 (결과는 [`README.md`](README.md)).
- 360° 랜선 방식은 연구실에서 104분 연속으로 돌린 적이 있다.

확인하지 못한 것:

- pi7 과 Tailscale 로 주고받는 것 전부 (영상, 상태, 경로 포트). 주소만 바꿔 뒀다.
- 서버에 새 데이터가 흐르는 상태에서의 리더 동작, Unity 화면 표시.
- 리더의 거리 계산이 실제 거리와 맞는지 (`depth_m`·`dist.value` 를 앞 방향 거리로 보고 계산했다).
- 사람 모형 표시는 가짜 신호로만 봤다.

정하지 않은 것 (사용자에게 물을 것):

- `GO1AutoPolicyController.commandHost` (`192.168.50.63`): 후진·정지 속도 명령을 로봇에 직접 보내는 주소다. Tailscale 로 바꾸면 Unity 가 로봇에 속도 명령을 보내는 길이 새로 열려서 그대로 뒀다.
- GO1_B (`192.168.50.165`): Tailscale 주소를 받지 못해 그대로 뒀다.
- 360° 를 데이터 스트림(`cam360`)으로 받을지: 서버에 결과가 올라온 뒤에 형식을 보고 정한다.

## 5. 이번에 추가·변경한 파일

| 파일 | 내용 |
|---|---|
| `anchor360/local/datastream_front_reader.py` | 서버 Redis → Unity 5012. 새로 만듦 |
| `anchor360/local/go1_front_guard.py` | 기본 영상 주소가 pi7 Tailscale |
| `unity-twin/Assets/Editor/TailscaleAddressApplier.cs` | 씬 세 개의 GO1_A 주소를 `100.72.109.9` 로 바꿔 저장. 메뉴 "Tools/Go1/로봇 주소를 Tailscale 로 바꾸기" |
| `unity-twin/Assets/Editor/RealRunLauncher.cs`, `evaluation/real_run/config.json` | 실주행 도구의 로봇 주소 `100.72.109.9` |
| `unity-twin/evaluation/real_run/estop.py` | Tailscale·랩 주소 양쪽으로 취소 신호 |

## 6. Unity 프로젝트 구성과 에셋 출처

원래 PC 의 `D:\Go1_Unity` 는 git 저장소가 아니고 원격도 없다. 아래는 2026-11-25 에 그 프로젝트를 조사한 결과다.
씬 세 개(`lab`·`mall`·`capstone_hall`)와 사람 프리팹이 실제로 쓰는 에셋은 216개, 약 65 MB 다 (Unity 의 의존성 조회로 뽑았다).

### 6-1. 편집기와 패키지 (`Packages/manifest.json`)

Unity **6000.3.5f2**, 템플릿은 URP. Package Manager 에서 아래 버전으로 넣는다.

| 패키지 | 버전 | 쓰는 곳 |
|---|---|---|
| `com.unity.render-pipelines.universal` | 17.3.0 | 렌더링 (재질이 모두 URP Lit) |
| `com.unity.ml-agents` | 4.0.2 | 강화학습 정책 실행 (`GO1Agent`) |
| `com.unity.ai.navigation` | 2.0.9 | NavMesh 굽기, 장애물 파내기 |
| `com.unity.cloud.gltfast` | 5.2.0 | Go1 모형 `go1.glb` 불러오기. **없으면 로봇 모형이 안 뜬다** |
| `com.unity.inputsystem` | 1.17.0 | 키 입력 (M 키 등) |
| `com.unity.xr.interaction.toolkit` | 3.3.1 | 씬의 XR 리그. 샘플 "Starter Assets" 도 가져와야 한다 |
| `com.unity.xr.management` / `com.unity.xr.openxr` | 4.5.4 / 1.16.1 | XR |
| `com.meta.xr.sdk.all` | 85.0.0 | Meta XR (헤드셋용. PC 에서 창으로만 볼 때는 쓰지 않는다) |
| `com.unity.probuilder` | 6.0.8 | 맵 도형 |
| `com.unity.ugui`, `com.unity.timeline`, `com.unity.visualscripting` | 2.0.0 / 1.8.10 / 1.9.9 | UI 등 |

- TextMesh Pro: `Window > TextMeshPro > Import TMP Essential Resources` 로 `Assets/TextMesh Pro/` 를 만든다.
- XRI 샘플: Package Manager 의 XR Interaction Toolkit > Samples > Starter Assets → `Assets/Samples/XR Interaction Toolkit/3.3.1/Starter Assets/`.

### 6-2. 밖에서 가져온 에셋 (다시 받을 수 있다)

| 에셋 | 놓는 위치 | 출처 | 쓰는 곳 | 비고 |
|---|---|---|---|---|
| Human Basic Motions FREE 2.4 (Kevin Iglesias) | `Assets/Kevin Iglesias/Human Animations/` | Unity Asset Store (무료) | 사람 모형과 서기·걷기 동작. `HumanM_Model.fbx`, `HumanF_Model.fbx`, `HumanM@Idle01`, `HumanM@Walk01_Forward`, 여성용 같은 이름 | 재배포 불가라 저장소에 넣지 않는다. 받은 뒤 `PersonAssetBuilder.RunBatch` 로 프리팹을 만든다 |
| Kenney Mini Market 2.1 | `Assets/KenneyMiniMarket/` (FBX 전부와 `Textures/colormap.png`, `License.txt`) | <https://kenney.nl/assets/mini-market> (CC0). 원래 PC 에서는 OpenGameArt 미러에서 받았다 | 쇼핑몰 맵의 진열대·계산대 등 48개 | FBX 만 넣으면 하얗게 나온다. `colormap.png` 를 꼭 같이 넣는다. `MallMapBuilder` 가 공용 재질을 만들어 붙인다 |
| Unitree Go1 모형 `go1.glb` (7.6 MB) | `Assets/robot-dog-unitree-go1/source/go1.glb`, 텍스처는 `.../textures/` | 폴더 이름이 Sketchfab 내려받기 형식(`robot-dog-unitree-go1/source`, `textures`)이라 Sketchfab 로 보인다. **정확한 주소와 라이선스는 확인하지 못했다. 사용자에게 물을 것** | 세 씬 모두의 로봇 모형 | 이 모형의 앞은 `-transform.right` 다 |
| Voxel Office Props (Air Dinghy) | `Assets/ADI/Voxel Office Props/` | Unity Asset Store 로 보인다 (동봉 문서의 연락처가 `support@airdinghy.com`). **확인하지 못했다** | 연구실 맵의 의자·키보드·노트북·모니터·PC·프린터 | 연구실 맵에만 쓴다 |
| 닉스곤폰트 M | `Assets/N4_5F_Corrider/Fonts/닉스곤폰트M TTF SDF.asset` (38 MB) | 닉스곤(NIXGON) 배포 글꼴을 TextMesh Pro 의 Font Asset Creator 로 변환한 것 | 화면 글자 | 없으면 글자가 기본 글꼴로 나오거나 비어 보인다. 동작에는 영향 없다 |

세 씬이 쓰지 않아 없어도 되는 것: `CGIndi/Sea`, `Bitgem/Toilet Paper - Proto Series`, `Procedural Water Shader`, `ocean`, `TestMab`, `Oculus`, `_Recovery`, `Scenes/`·`XRI/`·`N4_5F_Corrider/` 의 다른 씬, `Code/Boat`, `Code/onnx/boat`.

### 6-3. 직접 만든 것 (어디서도 다시 받을 수 없다)

**이 묶음이 없으면 에셋을 다 받아도 연구실 씬을 똑같이 만들 수 없다.** 지금 저장소에는 ★ 표시한 것만 들어 있다.

| 무엇 | 위치 | 설명 |
|---|---|---|
| 연구실 씬 | `Assets/lab.unity` (1.1 MB) | 손으로 만든 연구실 모델 (약 7.5 × 9.5 m). **쇼핑몰·발표장 맵 스크립트는 이 씬을 복사해서 시작한다.** 로봇, 수신기, 카메라, 목표 지점 설정이 모두 여기 있다 |
| 로봇 프리팹 | `Assets/prefab/go1 (1).prefab`, `Assets/prefab/go1 1.prefab`, `Assets/ADI/go1.prefab`, `Assets/prefab/Cube.prefab` | Go1 모형에 스크립트·충돌체·송수신 설정을 붙인 것 |
| 학습된 정책 | `Assets/Code/onnx/GO1Agent13.onnx` (0.6 MB) | 세 씬이 쓰는 강화학습 경로 생성 정책. 연구실 크기에서 학습했다 |
| 스크립트 전체 | `Assets/Code/**` (약 2 MB, onnx 제외) | ★ 일부만 저장소에 있다 (`Go1`, `Manager`, `UTM`, `insta360`). 나머지 폴더(`Receiver`, `Json`, `Logging`, `Streaming`, `UI`, `VR`, `YOLO`, `Aruco`, `delete` 등)도 씬이 참조한다 |
| 편집기 도구 | `Assets/Editor/*.cs` | ★ 저장소에 있다 |
| 소품 재질 | `Assets/Models/Props/Materials/` | 드론·360° 카메라 소품 재질 |
| 어안 보정 셰이더 | `Assets/settings 1/` | Go1 카메라 화면용 |
| 연구실 NavMesh | `Assets/lab/NavMesh-Plane.asset` | 다시 구울 수 있다 |
| 보정 파일 | `Assets/StreamingAssets/anchor360_calib*.json`, `anchor360_baseline.json` | ★ 저장소 `anchor360/local/unity/` 에 있다 |
| 프로젝트 설정 | `ProjectSettings/`, `Packages/manifest.json` | 태그(`Obstacle` 등)·레이어·입력 설정. 태그가 없으면 맵 스크립트가 실패한다 |
| `.meta` 파일 | 위 모든 파일 옆 | 씬과 프리팹은 파일을 GUID 로 가리킨다. **`.meta` 가 바뀌면 참조가 끊어진다.** 밖에서 받은 에셋 가운데 `go1.glb` 처럼 `.meta` 가 딸려 오지 않는 것은 원래 `.meta` 가 있어야 프리팹이 모형을 찾는다 |

### 6-4. 새 PC 에서 할 수 있는 범위

- 직접 만든 묶음(6-3)을 받지 못한 상태: Unity 화면 확인(3-2), 가상 로봇이 실제 자세를 따라오는지(3-3 의 3번), 실주행(3-4)은 **할 수 없다.** Redis 읽기와 pi7 연결·영상 확인까지만 한다.
- 6-3 묶음을 받은 뒤: 6-1 패키지와 6-2 에셋을 넣고 `PersonAssetBuilder.RunBatch` → `MallMapBuilder.Run` / `CapstoneMapBuilder.Run` 순서로 돌리면 쇼핑몰·발표장 맵이 다시 만들어진다.
- 6-3 묶음을 새 PC 로 옮기는 방법은 아직 정하지 않았다 (사용자에게 물을 것).
