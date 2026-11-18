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
