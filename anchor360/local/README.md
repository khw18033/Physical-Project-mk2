# anchor360 로컬 검증판 (2026-11-17)

Insta360 Pro2 영상으로 장애물을 탐지해 Unity 가상 공간에 배치하는 파이프라인을 **PC 한 대에서**
돌린 판이다. 서버로 옮기는 계획과 규약은
[`HW-interface/anchor360-server-contract.md`](../../HW-interface/anchor360-server-contract.md) 에 있다.

> ⚠ 이 판은 **9월 21일 판**(`stream_to_server.py`·`anchor360_live.py` v1)을 바탕으로 한다.
> 통합데이터규약 v2(2026-10-14, `360camera_work` 브랜치 `v2/`)는 반영돼 있지 않다 —
> 출력 필드가 v1 이름(`name`·`pos3d`·`dist_m`·`size`·`bbox_xyxy`)이다.

## 파일

| 파일 | 역할 |
|---|---|
| `anchor360_local.py` | 본체. RTMP 수신 → 8방향 슬라이스 → YOLO-World → UniDepthV2 → MobileSAM → 병합 → UDP 5010. MJPEG `:8090` |
| `stream_to_server.py` | 카메라 제어(접속·프리뷰·하트비트)를 `anchor360_local` 이 가져다 쓴다 (v1) |
| `anchor360_live.py` | 설정 로더·탐지기·바닥 투영을 `anchor360_local` 이 가져다 쓴다 (v1) |
| `anchor360_bridge.py` | 서버 JSON → Unity UDP 중계 (서버 경유 구성에서만 씀) |
| `run_anchor360_local.bat` | 실행 (`--show --quiet`) |
| `unity/Anchor360ObstacleReceiver.cs` | Unity 수신기. 보정 파일·기존 장애물 제외·방 경계·라벨·NavMeshObstacle. 위치: `Assets/Code/insta360/` |
| `unity/anchor360_calib.json` | 카메라→방 보정 4값. 위치: `Assets/StreamingAssets/` |

## 저장소에 넣지 않은 것

- `unidepth_duel_yolo_config.yaml` — 클래스·그룹·클래스별 conf 설정. **접속 암호가 들어 있어 올리지 않았다.**
  실행하려면 `--cfg` 로 경로를 준다.
- 가중치: `yolov8s-world.pt`, `weights/clip/ViT-B-32.pt`, `unidepth-v2-vitb14/`, `mobile_sam.pt`, UniDepth 저장소.

## 실행

기본 경로가 촬영 PC 기준(`D:\capstone\…`, `D:\Go1_Unity\…`)으로 박혀 있다. 다른 곳에서는 인자로 바꾼다.

```bat
python anchor360_local.py --show --quiet ^
  --cfg <설정 yaml> --depth-model <unidepth-v2-vitb14> --depth-repo <UniDepth> ^
  --calib <anchor360_calib.json> --unity-ip 127.0.0.1
```

- 카메라: `192.168.100.124` (제어 20000, RTMP 1935). 제어 세션은 하나만 된다.
- 탐지 화면: `http://localhost:8090/`
- 주요 값: `--u 230 --slices 8 --v -36.35 --pitch -35 --cam-h 1.85 --max-dist 8`
- 깊이·마스크 끄기: `--no-depth`, `--no-mask`

## 실측 (RTX 3060 12GB, 104분 연속)

송출 2.02 Hz · PC 구간 합계 중앙 379 ms / p90 735 ms · 탐지 중앙 292 ms · 스트림 25 fps, 읽기 실패 0.

## 알려진 한계

- 책상 통로 구간에서 Unity 모델과 x 로 약 0.23 m 차이(원인 미확정), 방향별 스케일 치우침 ±5%.
- 스트림이 끊기면 Unity 에 마지막 큐브가 남는다.
- Unity 의 NavMesh 파임은 컴파일만 확인했고 화면 확인은 안 했다.

## 2026-11-25 갱신 (11-18 이후 바뀐 것)

위 본문은 11-17 판 기준이다. 그 뒤 바뀐 것만 적는다.

| 파일 | 내용 |
|---|---|
| `anchor360_local.py` | 수평·방위 자동 맞춤(`anchor360_pose`, 기준 파일 `--pose-ref`, 끄려면 `--no-level`), 카메라 높이를 `--calib` 보정 파일의 `camH` 에서 읽기, 보낼 물체 그룹 `--groups`, 손떨림 보정 `--stab`(기본 끔). 출력 필드는 여전히 v1 이름이고 Unity 수신기는 v1·v2 를 모두 받는다 |
| `anchor360_marker_live.py`, `anchor360_aruco.py`, `anchor360_pose.py`, `aruco_check.py` | 360° 영상에서 ArUco 마커를 찾아 로봇 위치를 Unity 로 보낸다 (UDP 5013). `--cam-h`, `--marker-h` |
| `go1_front_guard.py` | Go1 정면 카메라(pi7 MJPEG)에서 탐지해 Unity 로 보낸다 (UDP 5012). 주의 ≤ 1.0 m, 정지 권고 ≤ 0.6 m, 통로 폭 ±0.35 m. **표시만 하고 로봇을 세우지 않는다.** 기본 영상 주소는 pi7 의 Tailscale 주소이고, 랩 공유기로 받으려면 `--url` 로 준다 |
| `unity/Anchor360ObstacleReceiver.cs` | 배치 필터(신뢰도·바닥 근처·배경 목록·탐지 범위·로봇 자신 제외), 같은 물체 이어 쓰기, 사람이면 사람 모형 표시 |
| `unity/Go1FrontGuardReceiver.cs`, `unity/RangeZone.cs` | Go1 정면 탐지 수신·표시. 11-24: 로봇 앞 방향을 `-transform.right` 로 고쳤다 (전에는 90° 틀어 그렸다) |
| `unity/Robot360MarkerReceiver.cs` | 마커로 잡은 로봇 위치 수신 |
| `unity/PersonVisual.cs` | 탐지 이름이 사람이면 상자 그림 대신 사람 모형. 프리팹은 `Resources/Person360/` ([`unity-twin`](../../unity-twin/) 의 `PersonAssetBuilder` 가 만든다) |
| `unity/anchor360_calib.json` | 연구실. 배치 필터 값 추가, `navMeshPadding` -0.03 |
| `unity/anchor360_calib_capstone.json` | 캡스톤 발표장 맵용. 카메라 위치는 배치도에서 잡은 예정 자리, `yawOffsetDeg` 0 은 임시값 — **현장에서 다시 맞출 것** |
| `unity/anchor360_calib_mall.json` | 쇼핑몰 맵용 (가상 배치, 천장 2.5 m, 범위 6 m) |
| `unity/anchor360_baseline.json` | 연구실에 원래 놓여 있던 물건 목록 (`useBaseline360` 이 켜졌을 때만 쓴다) |

- 넣지 않은 것: `anchor360_pose_ref.jpg`·`.npz` (연구실 기준 영상, 약 1.7 MB). `anchor360_marker_live.py` 와 `anchor360_local.py` 의 자동 맞춤에 쓰인다. 없으면 `anchor360_local.py` 는 자동 맞춤 없이 돈다.
- 사람 표시는 가짜 탐지 신호로만 확인했고 실제 카메라로는 확인하지 않았다.
- Unity 쪽 나머지 변경(맵, 가상 실험, 실주행 도구, 실주행 주의 사항)은 [`unity-twin/README.md`](../../unity-twin/README.md) 에 있다.
