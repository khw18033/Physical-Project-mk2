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
3. **Unity 프로젝트**: 이 저장소에는 바뀐 소스만 있고 씬·모형·NavMesh 는 없다. 둘 중 하나로 준비한다.
   - 쉬운 길: 원래 PC 의 `D:\Go1_Unity` 를 통째로 복사한다 (`Library` 폴더는 빼도 된다. Unity 가 다시 만든다).
   - 다시 만드는 길: 기존 프로젝트에 이 저장소의 `unity-twin/Assets/`, `anchor360/local/unity/` 파일을 같은 위치에 넣고, [`README.md`](README.md) 의 "맵과 프리팹 다시 만들기"를 따른다. 사람 모형·매장 모형 에셋은 따로 받아야 한다.
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
