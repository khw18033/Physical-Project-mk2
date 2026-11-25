# unity-twin — Unity 디지털 트윈 쪽 변경분 (2026-11-18 ~ 11-25)

Unity 프로젝트(`D:\Go1_Unity`, Unity 6000.3.5f2, URP, ML-Agents) 전체가 아니라 **이 기간에 바뀌거나 새로 만든 소스·설정·도구만** 모은 것이다.
씬(`.unity`), 모형, NavMesh, 영상은 넣지 않았다. 아래 스크립트로 다시 만들 수 있다.

폴더는 Unity 프로젝트 안의 위치를 그대로 따른다 (`Assets/Code/...`, `Assets/Editor/...`).
360° 카메라·Go1 정면 카메라 수신 스크립트와 보정 파일은 [`anchor360/local/unity/`](../anchor360/local/unity/) 에 있다.

## 무엇이 들어 있나

| 묶음 | 파일 | 내용 |
|---|---|---|
| 경로 생성 | `Assets/Code/Go1/GO1Agent.cs` | `virtualPlanTimeScale`(기본 10): M 키로 가상 Go1 이 경로를 만드는 동안만 시뮬레이션 시간을 10배로 돌린다. 한 걸음 크기는 그대로라 경로는 같다 |
| 사람 표시 | `anchor360/local/unity/PersonVisual.cs`, `Assets/Editor/PersonAssetBuilder.cs` | 탐지 이름이 사람이면 상자 대신 사람 모형(서기·걷기)을 세운다. 충돌과 NavMesh 파내기는 상자가 그대로 맡는다 |
| 사람 표시 시연 | `Assets/Code/Manager/PersonDemoRunner.cs`, `Assets/Editor/PersonDemoLauncher.cs` | 카메라 없이 가짜 탐지 신호(UDP 5010·5012)로 확인하고 녹화한다 |
| 발표장 맵 | `Assets/Editor/CapstoneMapBuilder.cs`, `CapstoneBooths.cs`, `CapstoneCamera360Setup.cs` | 캡스톤 발표 배치도로 `Assets/capstone_hall.unity` 를 만든다 (25.1 × 39 m, 전시대 117칸, 360° 카메라 바닥 삼각대 1.5 m) |
| 쇼핑몰 맵 | `Assets/Editor/MallMapBuilder.cs` | `Assets/mall.unity` 를 만든다 (26 × 18 m, 마트·복도·매장 3칸, 360° 카메라 천장 2.5 m). 가상의 배치다 |
| 가상 실험 | `Assets/Code/Manager/Proactive*.cs`, `Assets/Editor/ProactiveBatchLauncher.cs` | 설정에 `scene`·`calibFile`·고정 `scenarios`·`recordAutoFrame`·`obstaclesAsPeople` 추가 |
| 실주행 | `Assets/Code/Manager/RealRunRunner.cs`, `Assets/Editor/RealRunLauncher.cs`, `evaluation/real_run/` | 창 없이 실주행을 돌리고 기록하는 도구. **아래 주의 사항을 먼저 읽을 것** |
| 그 밖 | `MapFix261124.cs`, `MarkerPoseApplier.cs`, `*SnapshotRunner.cs`, `SceneOutlineDump.cs` 등 | 연구실 맵 보정, 마커로 로봇 위치 맞추기, 확인용 출력 |

## 맵과 프리팹 다시 만들기

Unity 에디터를 닫고 실행한다. 그림을 그리므로 `-nographics` 는 붙이지 않는다.

```sh
UNITY="/d/editor/6000.3.5f2/Editor/Unity.exe"
"$UNITY" -batchmode -projectPath "D:\Go1_Unity" -executeMethod PersonAssetBuilder.RunBatch -logFile person.log
"$UNITY" -batchmode -projectPath "D:\Go1_Unity" -executeMethod CapstoneMapBuilder.Run -quit -logFile capstone.log
"$UNITY" -batchmode -projectPath "D:\Go1_Unity" -executeMethod MallMapBuilder.Run -quit -logFile mall.log
```

- 맵 스크립트는 `Assets/lab.unity` 를 복사해서 시작한다. **다시 실행하면 그 씬에서 손으로 고친 내용은 사라진다.**
- 저장소에 없는 에셋 (직접 넣어야 한다):
  - 사람 모형: Unity Asset Store "Human Basic Motions FREE"(Kevin Iglesias) → `Assets/Kevin Iglesias/`. 재배포할 수 없어 넣지 않았다.
  - 매장 모형: Kenney "Mini Market" 2.1 (CC0, <https://kenney.nl/assets/mini-market>) 의 FBX 와 `Textures/colormap.png` → `Assets/KenneyMiniMarket/`.

## 가상 실험 돌리기

```sh
cd GO1_Proactive_Evaluation
sh run_batch_video.sh configs/mall_verify.json        # 또는 configs/capstone_verify.json
python make_videos.py <프레임 폴더> <세션 폴더> <출력 폴더> <이름 앞머리> [trial]
```

`make_videos.py` 의 비교 영상은 다섯 방식 기준 배치라 두 방식만 돌린 세션에서는 쓰지 않는다. 한 설정에 세션을 둘 이상 넣으면 녹화 폴더 이름이 겹쳐 덮어쓴다.

## 검증 결과 (`evaluation/results/`)

실제 추종기 모델 0.22 m/s, 방식 A = 로봇이 탐지 후 정지·재탐색, C = 인프라가 먼저 탐지해 멈추지 않고 전환.

| 맵 | 구간 | 도착 | 강화학습 경로 길이 (최단 대비) | 장애물이 경로를 막은 구간 |
|---|---|---|---|---|
| 발표장 (장애물 1개) | 8 | 15 / 16 | 1.1 ~ 3.5배 | 2 — C 는 전환 1회씩, A 는 정지 후 재탐색 |
| 발표장 (장애물 3개) | 1 | C 도착, A 시간 초과 | — | C 전환 3회 |
| 쇼핑몰 (장애물 1개, 사람 모형) | 8 | 15 / 16 | 1.0 ~ 1.4배 | 5 — C 는 모두 전환 1회 후 도착, A 는 4개 도착·1개 시간 초과 |

- 경로 생성 10배속 실측: 발표장 21회, 쇼핑몰 56회 모두 9.9 ~ 10.0배.
- 발표장은 경로가 길게 돈다. 정책을 연구실(7.5 × 9.5 m)에서 학습했기 때문으로 보지만 따로 실험해 확인한 것은 아니다.
- 사람·장애물 표면과의 최소 간격이 0.16 ~ 0.29 m 까지 내려간 run 이 있다 (로봇 몸체 반경 0.162 m).
- 사람 표시는 가짜 탐지 신호로만 확인했다. 실제 카메라로는 확인하지 않았다.

## 실주행 주의 사항

2026-11-24 연구실 첫 실주행에서 Go1 이 계획과 다른 방향으로 1.5 m 넘게 걸어가 사람이 손으로 붙잡았다.

- 원인: `GO1Agent` 는 경로를 보낸 뒤 로봇의 `state_change=true`(UDP 5009)를 기다리다 시간이 넘으면 **같은 경로를 다시 보낸다.** 추종기(`go1_sdk_pc`)는 경로를 받을 때마다 지금 위치·방향을 경로 시작점으로 다시 잡는다. 로봇이 이미 돌아선 뒤에 재전송이 도착해 같은 모양의 경로가 돌아간 방향 기준으로 다시 실행됐다. 그 실행에서는 5009 신호가 Unity 에 오지 않았다.
- 다시 시도하기 전에 로봇이 움직이지 않는 상태에서 확인할 것:
  1. 5009 `state_change` 가 Unity 에 도착하는가
  2. 재전송을 껐거나 무해하게 만들었는가
  3. 로봇 명령 주소(`real_run/config.json` 의 `robotHost`)로 경로 포트 15110 이 닿는가 — 11-25 에 pi7 의 Tailscale 주소로 바꿨고, 그때 pi7 이 꺼져 있어 **연결을 확인하지 못했다**
  4. pi7 이 보내는 상태값이 Unity PC 로 돌아오는가
- `evaluation/real_run/estop.py` 는 주소 없이 실행하면 Tailscale 주소와 랩 공유기 주소 양쪽으로 `PATH_CANCEL` 을 보낸다.
- Go1 정면 탐지(`Go1FrontGuardReceiver`)는 표시만 하고 로봇을 세우지 않는다.

## 알려진 한계

- 발표장 맵: 전시대 치수(패널 1 m, 데스크 1.0 × 0.5 × 0.75 m)는 사진을 보고 잡은 가정이고, 배치도가 잘려 있어 바닥을 39 m 까지만 만들었다. 360° 카메라 보정값(`yawOffsetDeg` 0)은 임시값이라 현장에서 다시 맞춰야 한다.
- 이 Go1 모델의 앞은 `transform.forward` 가 아니라 `-transform.right` 다. 11-24 에 `Go1FrontGuardReceiver` 가 이 때문에 탐지를 90° 틀어 그리던 것을 고쳤다.
- 씬에 저장된 로봇 주소(`sdkPcIp` 등)는 예전 랩 주소 그대로다. `RealRunLauncher` 만 `robotHost` 로 덮어쓴다.
