# 360° 앵커 카메라 → 서버 → 디지털트윈 연동 규약 (서버 이관 계획)

> 작성: 2026-11-18 · HW 파트 · 브랜치 `HW`
> 성격: **이관 계획 + 인터페이스 규약.** 2026-11-17 에 PC 한 대에서 검증한 360° 장애물
> 파이프라인을, **카메라 정보값과 객체 탐지를 전부 서버가 맡는 구조**로 옮기기 위한 문서다.
> 근거: `docs/SRS.md` HW-S-06("객체 탐지는 엣지·서버가 수행하고 카메라는 촬영·전달만 담당"),
> `docs/ARCHITECTURE_ALIGNMENT.md` §1·§4, 통합데이터규약 v2(`ldg_BE` 브랜치
> `contracts/common/` — 프레임 헤더 §3-5, 비전 결과 §3-6), `360camera_work` 브랜치 `v2/`.

---

## 0. 요약

| 항목 | 지금 (2026-11-17 로컬 검증판) | 목표 |
|---|---|---|
| 카메라 제어·프레임 수신 | 촬영 PC | 촬영 PC (그대로 — §2-1) |
| 슬라이스·탐지·깊이·마스크·병합 | **촬영 PC** (RTX 3060) | **서버** |
| 카메라 정보값(높이·각도·슬라이스) | PC 실행 인자 | **서버 설정**, 결과 머리에 실어 보냄 |
| 카메라→방 좌표 보정값 | Unity `StreamingAssets` 파일 | **서버**가 보유·적용 |
| 결과 형식 | v1 이름(`name`·`pos3d`…), UDP 5010 직송 | **통합데이터규약 v2 비전 결과** |
| 큐브·라벨·NavMesh | Unity | Unity (그대로) |

로컬판은 서버 접속이 막혀서(§8-1) 임시로 PC 에 전부 올린 것이다. 기능은 로컬판이 앞서 있고
(360° 전 방향·깊이·마스크), 규약은 `360camera_work` 의 v2 판이 앞서 있다(공통 머리·`frame_ref`).
**이관 = 로컬판의 기능을 v2 판의 입출력 규약 위에 올리는 일이다.**

---

## 1. 지금 무엇이 돌고 있나 (로컬 검증판)

```
 Insta360 Pro2 ──RTMP 1935──► [촬영 PC] anchor360_local.py ──UDP 5010──► [같은 PC] Unity
 192.168.100.124              equirect 3840×1920                        Anchor360ObstacleReceiver
                              → 8방향 슬라이스(90°, 720×720)             큐브 + 라벨 + NavMesh
                              → YOLO-World → UniDepthV2 → MobileSAM
                              → 기준 슬라이스 좌표로 병합
```

실측(2026-11-17, RTX 3060 12GB, 104분 연속): 송출 12,567회 = **2.02 Hz**, PC 구간 합계
중앙 379 ms / p90 735 ms, 탐지 중앙 292 ms, 슬라이스 중앙 62 ms, 스트림 수신 25 fps·읽기 실패 0.

로컬판이 v2 판(`360camera_work`)에 없는 것:

| 기능 | 내용 |
|---|---|
| 360° 전 방향 | 슬라이스 8장(45° 간격)을 한 프레임에서 뽑아 기준 슬라이스 좌표로 병합, 겹침 구간 중복 제거 |
| 깊이 기반 위치·크기 | UniDepthV2(ViT-B). 슬라이스마다 바닥 평면으로 스케일 보정. 바닥 접지점이 보이면 접지점 우선 |
| 마스크 기반 크기 | MobileSAM 으로 물체 픽셀만 골라 방 축 기준 5~95 백분위 크기 |
| 캐시·평균 | 같은 자리 검출은 깊이 재계산 생략, 같은 물체 6회 평균 |
| 가구 위 물체 제외 | 바닥에서 떠 있는 검출(`elevated`)은 장애물에서 뺌 |
| 상시 화면 | MJPEG `:8090` (탐지 화면을 브라우저로 계속 봄) |

Unity 쪽(`Anchor360ObstacleReceiver.cs`)에 추가된 것: 보정 파일 자동 재적용, **씬에 이미 있는
장애물과 겹치는 검출 제외**, 방 밖 검출 제외, 시야가 막힌 검출 제외, 이름·거리 라벨,
`NavMeshObstacle`(Carve) + 큐브 재사용(2초 유예).

---

## 2. 무엇을 어디에 두나

### 2-1. 촬영 PC 에 남는 것 — 카메라 제어와 프레임 번호

카메라는 사설 링크(`192.168.100.x`)에만 붙어 있어 **서버가 직접 닿지 못한다.** 그리고 Pro2 는
제어 세션을 하나만 허용하고 1초 하트비트가 끊기면 프리뷰를 내린다. 그래서 아래는 PC 에 남는다.

- `camera._connect` → `camera._startPreview`, `/osc/state` 1초 하트비트, 끊김 시 재접속
- 프레임 번호(`sequence_id`)·시각(`timestamp`) 부여 — **프레임을 처음 손에 넣은 기기가 한 번
  붙인다**(통합데이터규약 원칙 10). 서버·탐지는 다시 만들지 않는다.
- 서버로 업로드. 구현은 이미 있다: `360camera_work` 의 `v2/stream_to_server.py`(CAM360-01).

PC 는 **탐지를 하지 않는다.** GPU 가 필요 없어지므로 노트북·라즈베리파이급으로 내려도 된다.

### 2-2. 서버로 가는 것

| 기능 | 로컬판 위치 | 비고 |
|---|---|---|
| equirect → 슬라이스 | `MultiSlicer` | 입력만 RTMP → 업로드된 `equirect.jpg` 로 교체 |
| 탐지 | `detect_batch` (YOLO-World, 59 클래스) | 서버 기존 설정 yaml 을 그대로 읽는 구조 |
| 깊이·마스크·크기 | `DepthRefiner`, `Segmenter` | UniDepthV2 ViT-B, MobileSAM |
| 병합·중복 제거·캐시·평균 | `merge_slices`, `blend_fields` | |
| **카메라 정보값** | 실행 인자 | §5. 서버 설정으로 고정하고 결과 머리에 실어 보냄 |
| **카메라→방 보정** | Unity 파일 | §4-3. 2단계에서 서버로 |
| 상시 화면(MJPEG) | `MjpegServer` | 서버에서 띄우거나 미디어 게이트웨이로 대체 |

### 2-3. 트윈(Unity)에 남는 것

큐브·라벨 표시, `NavMeshObstacle`, 그리고 **씬 기하를 알아야 하는 판정**(기존 장애물과 겹침,
방 경계, 시야 가림). 마지막 셋은 구역 지도가 서버(엣지)로 올라가면 따라 올라가야 한다
(ARCHITECTURE_ALIGNMENT §4-2 "구역 지도·구역 장애물 = 엣지") — 지금은 지도가 Unity 씬에만 있다.

---

## 3. 경로와 포트

```
 Pro2 ─RTMP 1935─► [촬영 PC] stream_to_server ─HTTP POST─► [서버] pano_receiver :7866
 (사설 링크)        번호·시각 부여                           │  equirect.jpg + equirect.json
                                                            ▼
                                                   anchor360 탐지 데몬 (이 문서의 이관 대상)
                                                            │  anchor360_latest.json
 [Unity] ◄─UDP 5010─ [PC] anchor360_bridge ◄─HTTP GET /anchor360_latest─┘
```

| 포트 | 위치 | 용도 |
|---|---|---|
| 20000 / 1935 | 카메라 | 제어 API / RTMP `live/preview` |
| 7866 | 서버 | `POST /upload_pano`, `GET /pano_health`, `GET /anchor360_latest` |
| 10001 | 서버 | 데이터 스트림 360 입구(같은 `/upload_pano` 모양) |
| 5010/udp | Unity PC | `Anchor360ObstacleReceiver` |
| 8090 | 탐지가 도는 곳 | 탐지 화면 MJPEG (`/`, `/stream.mjpg`, `/snapshot.jpg`) |

**서버 → Unity PC UDP 직송은 안 된다**(서버에 `192.168.50.x` 경로가 없고, `sendto()` 는 그래도
성공을 반환한다 — 360 총정리 v2 §2.2). 그래서 결과는 PC 의 브리지가 **가져온다**(pull).
이 구간은 3단계에서 백엔드 업무 경로로 바꾼다(§7).

---

## 4. 규약

### 4-1. 입력 — 프레임 (PC → 서버)

`POST /upload_pano`, multipart. 통합데이터규약 §3-5 프레임 헤더. **이미 구현·시험됨**(CAM360-01).

| 칸 | 값 |
|---|---|
| `capture_id` | `LIVE_STREAM` (한 폴더를 덮어씀 — 서버 디스크 증가 0) |
| `camera_id` | `cam360-001_main` |
| `meta` (JSON) | `schema_version "2.0"` · `source_id "cam360-001"` · `node_id` · `zone_id` · `camera_id` · `sequence_id` · `session_id` · `timestamp`(ISO, 밀리초, `+09:00`) · `encoding "jpeg"` · `width` · `height` |
| `file` | `equirect.jpg` (3840×1920, 실측 약 780 KB) |

서버는 `equirect.json`(meta + 사진 SHA-1)을 같이 남기고, 탐지 데몬은 **사진 바이트의 SHA-1 이
같을 때만** 그 meta 로 `frame_ref` 를 만든다(CAM360-02).

> RTMP 를 서버로 그대로 중계하는 방법은 쓰지 않는다. 대역은 줄지만(10 Mbps) H.264 에는 장마다
> 헤더를 실을 자리가 없어 **번호·시각을 촬영 PC 가 붙일 수 없게 된다**(원칙 10 위반).

### 4-2. 출력 — 비전 결과 (서버 → 트윈)

`contracts/common/detections.schema.json`(§3-6)을 따른다. 로컬판은 아직 **v1 이름**으로 내보내므로
이관하면서 바꾼다.

| 로컬판 (v1) | 규약 v2 | 비고 |
|---|---|---|
| `timestamp` (epoch 초 문자열) | `timestamp` (ISO) = 원본 프레임 시각 | 패킷 만든 순간은 `emitted_at` |
| `camera_id`·`frame` = `"anchor360"` | `coordinate_frame` | 머리에 `source_id "anchor360-live"`·`node_id`·`zone_id` 추가 |
| — | `frame_ref{camera_id, sequence_id, timestamp}` | meta 가 맞을 때만 |
| — | `producer{tier:"server", kind:"precise"}` | 가시화는 `producer` 없는 결과를 버린다 |
| `anchor_dir{u_deg,v_deg,roll_deg,slices}` | `view{…}` | §4-2-1 |
| `name` / `conf` / `bbox_xyxy` | `label` / `confidence` / `bbox` | |
| `pos3d` / `dist_m` / `size` | `position` / `ground_dist_m` / `size_m` | |
| `group`·`ground_clipped`·`wy`·`id` | 그대로 | |

로컬판이 **새로 싣는 칸**(규격이 바깥 칸 추가를 허용하므로 그대로 지나간다. 이름은 확정 필요 — §8-3):

| 칸 | 뜻 | 쓰는 곳 |
|---|---|---|
| `pos_src` | 위치를 어떻게 구했나: `depth` / `depth+mask` / `depth+contact`(바닥 접지점으로 고정). 깊이를 못 써서 박스 아랫변의 바닥 투영만 쓴 검출에는 **이 칸이 없다**(v2 에서는 `null`) | Unity: 깊이 기반이면 시야 가림 판정을 건너뜀 |
| `elevated`, `base_h` | 바닥에서 떠 있는가(밑면 0.3 m 초과), 밑면 높이(m) | 가구 위 물체 제외 |
| `oriented`, `yaw_deg` | `oriented=false` 면 `size_m` 이 **방 축 기준**이라 회전 없이 놓는다(현재 깊이 기반 검출은 전부 false). true 일 때만 `yaw_deg` 로 돌린다 | Unity 큐브 회전 |
| `slice_u` | 이 검출이 나온 슬라이스 방향(°) | §4-2-1 |
| `edge_cut` | 슬라이스 가장자리에 잘린 검출 | 병합 시 우선순위 |

값이 없으면 **0 이 아니라 `null`**(ARCHITECTURE_ALIGNMENT §1-3). 예: 깊이를 못 구한 검출의 `base_h`.

#### 4-2-1. 슬라이스가 여러 장일 때의 `bbox`

규약의 `bbox` 는 "결과의 `width`·`height` 기준 픽셀"이고 `view` 는 하나다. 그런데 8장을 합치면
**검출마다 다른 슬라이스의 픽셀 좌표**가 된다. 그래서:

- 머리: `width 720`, `height 720`, `view{u_deg: 230, v_deg: -36.35, roll_deg: 0, slices: 8}`
  — `u_deg` 는 **기준 슬라이스**(좌표의 정면)다.
- 검출: `slice_u` 가 그 `bbox` 가 속한 슬라이스를 가리킨다.
- `alignment` 는 싣지 않는다(= `unaligned`). 박스가 원본 equirect 위 좌표가 아니기 때문이다.

#### 4-2-2. 예

```json
{ "schema_version": "2.0", "source_id": "anchor360-live", "node_id": "sysai-server2",
  "zone_id": "zoneA", "timestamp": "2026-11-17T17:02:11.204+09:00",
  "frame_ref": {"camera_id": "cam360-001_main", "sequence_id": 8812,
                "timestamp": "2026-11-17T17:02:11.204+09:00"},
  "emitted_at": "2026-11-17T17:02:11.611+09:00",
  "producer": {"tier": "server", "kind": "precise"},
  "model": "yoloworld", "model_file": "yolov8s-world.pt",
  "width": 720, "height": 720,
  "view": {"u_deg": 230.0, "v_deg": -36.35, "roll_deg": 0, "slices": 8},
  "coordinate_frame": "anchor360",
  "detections": [
    { "id": 5, "label": "trash bin", "group": "HARD_OBSTACLE", "confidence": 0.325,
      "bbox": [325, 310, 408, 477], "slice_u": 140.0,
      "position": {"x": -1.594, "y": 0.0, "z": 0.05}, "ground_dist_m": 1.595,
      "size_m": {"w": 0.324, "h": 0.829, "d": 0.436},
      "pos_src": "depth+contact", "base_h": 0.11, "elevated": false,
      "oriented": false, "ground_clipped": false, "edge_cut": false, "wy": -0.841 } ] }
```

검출이 0건이어도 빈 배열을 **계속 보낸다.** Unity 는 패킷이 와야 사라진 큐브를 지운다(§8-5).

### 4-3. 좌표

**`anchor360`** (지금 결과가 쓰는 좌표)

- 원점 = 카메라를 바닥에 수직으로 내린 점. `+x` 오른쪽, `+y` 위(바닥 0), `+z` **기준 슬라이스
  (`u=230°`)가 보는 정면**. 단위 m.
- 다른 슬라이스(`u_s`)의 값은 `Δ = u_s − u_ref` 로 돌려 합친다:
  `X = x·cosΔ + z·sinΔ`, `Z = −x·sinΔ + z·cosΔ`.

**방 좌표로의 변환** (지금은 Unity 가 수행)

```
p' = distanceScale · p
unity_x = anchorX + p'.x·cos(yaw) + p'.z·sin(yaw)
unity_z = anchorZ − p'.x·sin(yaw) + p'.z·cos(yaw)
```

현재값(`Assets/StreamingAssets/anchor360_calib.json`, 2026-11-17, `lab.unity` 기준):
`anchorX 3.35`, `anchorZ 6.28`, `yawOffsetDeg 79.2`, `distanceScale 1.075`, `invertX false`.

- 보정은 문·돌출부·탁자 등 기준점 6개에 최소제곱으로 맞췄고 그 점들에서 잔차 3~11 cm 다.
- `distanceScale 1.075` 는 바닥 투영에서 **카메라 높이를 1.85 → 1.99 m 로 본 것과 같다.**
  높이를 실측하면 이 값은 1.0 으로 돌아가야 한다.
- **카메라를 옮기면 네 값을 다시 구해야 한다.**

**이행** — `coordinate-contract.md` 부록의 원칙("프레임 이름을 페이로드에 명시, 변환은 받는 쪽이
아니라 좌표의 주인이")을 따른다.

| 단계 | `coordinate_frame` | 보정값 주인 | Unity |
|---|---|---|---|
| 1 | `anchor360` | Unity 파일(현행) | 변환 수행 |
| 2 | 방 좌표(이름 확정 필요 — §8-4) | **서버**(`camera_id` 별 설정) | 변환 없음. 프레임 이름이 다르면 그리지 않음 |

로컬판은 방 축 정렬에 `yawOffsetDeg` 를 **이미 탐지 쪽에서 읽고 있다**(크기를 방 축 기준으로
재려고). 즉 보정값은 지금도 양쪽이 같이 쓰는 값이고, 서버로 올리는 것이 자연스럽다.

---

## 5. 카메라 정보값 — 서버가 가져야 할 값

| 값 | 현재 | 뜻 |
|---|---|---|
| 스트림 | 3840×1920, 10240 kbps, 손떨림 보정 on | `_startPreview` 인자 (촬영 PC 가 설정) |
| 슬라이스 | 8장, 45° 간격, FOV 90°, 720×720 | `fx = fy = cx = cy = 360` |
| `u` (기준 방향) | 230° | 좌표의 `+z` |
| `v` (슬라이스 고저각) | −36.35° | |
| `pitch` (바닥 계산용 하향각) | −35° | 영상으로 확인한 물리값 |
| `cam_h` (렌즈 높이) | 1.85 m | **미실측** — 위 `distanceScale` 참조 |
| `max_dist` | 8 m | 넘는 검출 제외 |
| 방 보정 4값 | §4-3 | 2단계부터 서버 |

이 값들은 **결과를 해석하는 데 필요한 값**이므로 서버가 설정으로 갖고, 바뀌면 결과 머리(`view`,
`coordinate_frame`)에 드러나야 한다. 트윈이 따로 알고 있어야 하는 값이 있으면 안 된다.

---

## 6. 서버 준비물

| 항목 | 내용 |
|---|---|
| 가중치 | YOLO-World(로컬 `yolov8s-world.pt`, 서버 기존 `yolov8x-worldv2.pt`), UniDepthV2 ViT-B(`unidepth-v2-vitb14`), `mobile_sam.pt` |
| 패키지 | `torch`, `ultralytics`, `py360convert`, `opencv-python`, `pyyaml`, UniDepth 저장소 |
| 설정 | `unidepth_dual_yolo_config.yaml`(클래스·그룹·클래스별 conf — UTF-8 로 읽을 것) |
| GPU | 로컬 실측은 RTX 3060 12GB 에서 2 Hz. 서버(RTX A6000) 수치는 **미측정** |
| 주의 | UniDepth 는 카메라 내부값을 줄 때 배치 추론이 깨진다 — 슬라이스를 한 장씩 넣는다 |

---

## 7. 이관 단계

시연을 깨지 않도록 ARCHITECTURE_ALIGNMENT §2-3 과 같은 방식으로 간다 — 새 경로를 띄우고 갈아탄다.

**1단계 — 탐지를 서버로.** 로컬판의 입력을 RTMP 리더에서 `pano_captures/cam360-001_main` 감시로
바꿔 서버에서 띄운다(v2 `anchor360_live.py` 의 감시·`frame_ref` 부분을 그대로 쓴다). 출력은 §4-2
v2 이름. 결과는 기존 브리지(pull → UDP 5010)로 Unity 에 간다. Unity 수신기는 v2 이름을 읽도록
고친다(`360camera_work` 의 `v2/Anchor360ObstacleReceiver.cs` 에 로컬판 추가 기능을 합친다).
보정은 아직 Unity.

**2단계 — 카메라 정보값·보정을 서버로.** 서버가 방 좌표로 내보내고 Unity 의 yaw/anchor/scale 을
걷어낸다. 서버 쪽에 물체 추적 ID 를 둔다(§8-3).

**3단계 — 결과를 백엔드 업무 경로로.** PC 브리지와 UDP 5010 을 걷어내고 트윈이 서버에서 받는다.
구역 지도가 서버에 생기면 "기존 장애물 제외·방 경계" 판정도 서버로 옮긴다.

---

## 8. 미결·확인 필요

1. **서버 접속.** 2026-11-17 촬영 PC 에서 `210.110.250.33:7866` 이 닫혀 있었고 SSH 는
   `Permission denied` 였다. 로컬판을 만든 이유가 이것이다. 1단계의 선행 조건.
2. **두 판의 합치기.** 로컬판은 `anchor360/local/` 에 올렸다. 9월 21일 판(`stream_to_server`·
   `anchor360_live` v1)을 바탕으로 만들어져 10월 14일 v2 변경이 반영돼 있지 않다. 설정 yaml 은
   접속 암호가 들어 있어 올리지 않았다.
3. **추가 칸 이름과 추적 ID.** §4-2 의 새 칸 이름을 백엔드·가시화와 확정. 지금 `id` 는 **패킷 안
   번호**일 뿐이라 Unity 가 0.5 m 이내 같은 종류를 같은 물체로 본다. 구역 내 추적 ID
   (`zone_local_track_id`)는 탐지 쪽이 부여하는 것이 규약이다 — 서버 캐시가 이미 같은 자리 검출을
   짝짓고 있으므로 거기서 번호를 내면 된다.
4. **방 좌표 프레임의 이름과 정의.** `coordinate-contract.md` 부록은 건물 기준 로컬 ENU 를 목표로
   하지만 구역 원점·방위가 아직 없다. 그때까지 쓸 이름(예: `lab.unity` 월드 X/Z 를 그대로 가리키는
   이름)을 정해야 한다.
5. **끊겼을 때의 동작.** 스트림이 멈추면 **마지막 큐브와 NavMesh 구멍이 그대로 남는다**(Unity 는
   패킷이 올 때만 정리). 오래된 값을 최신인 척하지 않도록(§1-3 규칙) Unity 에 "N초 무수신 시
   전부 지움 또는 stale 표시"가 필요하다. 서버는 검출 0건이어도 패킷을 계속 내야 한다.
6. **위치 정확도 — 실로봇 주행에 쓰기 전에 풀어야 한다.** 책상 통로 구간에서 카메라가 잰 책상
   모서리가 Unity 모델보다 x 로 약 +0.23 m 다(가운데 책상 2.79 vs 2.57, 벽쪽 책상 1.14 vs 0.90).
   모델이 틀린지 보정이 틀린지는 줄자 실측 두 군데(벽 → 벽쪽 책상 앞 모서리, 돌출부 면 → 가운데
   책상 통로쪽 모서리)로 가른다. 방향에 따른 스케일 치우침(±5%)도 남아 있다.
7. **Unity 쪽 미검증.** NavMesh 파임은 컴파일만 확인했고 화면으로는 확인하지 못했다.

---

## 9. 파일 색인

```
[360camera_work 브랜치 — 통합데이터규약 v2 적용판]
v2/stream_to_server.py            촬영 PC. 카메라 제어 + 프레임 헤더 + 업로드 (CAM360-01)
v2/pano_receiver.py               서버 7866. 수신 + equirect.json (CAM360-02)
v2/anchor360_live.py              서버. 슬라이스 1장 탐지, v2 패킷 (CAM360-03)
v2/Anchor360ObstacleReceiver.cs   Unity. v2 패킷 수신 (CAM360-04)

[HW 브랜치 — 로컬 검증판 (anchor360/local/README.md)]
anchor360/local/anchor360_local.py                  8방향 + 깊이 + 마스크 + 캐시 + MJPEG
anchor360/local/stream_to_server.py                 카메라 제어부 (v1, 본체가 가져다 씀)
anchor360/local/anchor360_live.py                   설정·탐지기·바닥 투영 (v1, 본체가 가져다 씀)
anchor360/local/unity/Anchor360ObstacleReceiver.cs  보정·기존 장애물 제외·라벨·NavMesh
anchor360/local/unity/anchor360_calib.json          카메라→방 보정 4값

[ldg_BE 브랜치 — 규격 정본]
contracts/common/media-header.schema.json      프레임 헤더 (§3-5)
contracts/common/detections.schema.json        비전 결과 (§3-6, 초안)
contracts/common/frame-reference.schema.json   frame_ref
```
