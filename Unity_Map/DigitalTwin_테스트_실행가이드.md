# Unity ↔ Pyjevsim 디지털 트윈 테스트 실행 가이드

**작성일:** 2026-07-01  
**대상:** Unity + Pyjevsim 연동 테스트 담당자

---

## 빠른 시작 순서

```
1. Pyjevsim WebSocket 서버 실행  (Python)
2. Unity Play 버튼              (Unity Editor)
3. 로그 확인                    (양쪽 콘솔)
4. sim_tick 전송 시작           (Pyjevsim)
```

> **순서 중요:** Pyjevsim 서버를 먼저 켜야 합니다.  
> Unity가 클라이언트이므로 서버가 없으면 연결을 시도하다 2초마다 재시도합니다.

---

## Step 1 — Pyjevsim 서버 실행

터미널에서 Pyjevsim 프로젝트 루트로 이동 후:

```bash
python examples/pathplan/ws_server.py --port 8765
```

**정상 출력:**
```
[Digital Twin] WsPlannerServer uri=ws://localhost:8765
```

서버가 Unity 접속을 대기합니다.

---

## Step 2 — Unity Play 실행

1. Unity Editor에서 씬 열기:  
   `Assets/Procedural Water Shader/Demo/Procedural Water Shader.unity`

2. **Play 버튼** 클릭

**Unity Console 정상 출력 (순서대로):**
```
[DigitalTwin] WsPlannerClient 시작 → ws://localhost:8765
[DigitalTwin] 연결 시도: ws://localhost:8765
[DigitalTwin] Connected to Pyjevsim @ ws://localhost:8765
```

**Pyjevsim 콘솔 정상 출력:**
```
[WsServer] Unity connected from 127.0.0.1:xxxxx
```

---

## Step 3 — 연결 확인 체크리스트

```
[ ] Pyjevsim 콘솔: "Unity connected from …" 출력
[ ] Unity Console: "Connected to Pyjevsim" 출력 (빨간 에러 없음)
[ ] Hierarchy 창: DT_VirtualBoat 오브젝트 생성됨 (boatObject 미할당 시 자동 생성)
[ ] Hierarchy 창: WsPlannerClient 오브젝트 활성화됨
```

---

## Step 4 — sim_tick 전송 테스트

### 4-1. 장애물 없는 단순 주행 테스트

Pyjevsim에서 시뮬레이션 시작. 매 Tick 아래와 같은 메시지가 오가야 합니다:

**Pyjevsim → Unity (sim_tick 예시):**
```json
{
  "type": "sim_tick",
  "platform_name": "mobile_0",
  "position": [10.0, 10.0, 0.0],
  "waypoints": [[30.0, 50.0], [45.0, 90.0], [40.0, 135.0]],
  "waypoint_idx": 0,
  "detected_obstacles": [],
  "destination": [40.0, 135.0]
}
```

**Unity → Pyjevsim (twin_ack 예시):**
```json
{
  "type": "twin_ack",
  "platform_name": "mobile_0",
  "virtual_position": [10.0, 10.0, 0.0],
  "waypoints": [[30.0, 50.0], [45.0, 90.0], [40.0, 135.0]],
  "replanned": false,
  "status": "ok"
}
```

**Unity Console 정상 출력:**
```
[DigitalTwin] sim_tick  platform=mobile_0  pos=(10.0,10.0)  obstacles=0
```

**확인 포인트:**
- `virtual_position` ≈ `position` (오차 0)
- `replanned: false`

---

### 4-2. 장애물 탐지 → 재경로 테스트

장애물이 탐지된 sim_tick 전송 시:

**Pyjevsim → Unity:**
```json
{
  "type": "sim_tick",
  "platform_name": "mobile_0",
  "position": [23.0, 18.0, 0.0],
  "waypoints": [[30.0, 50.0], [45.0, 90.0], [40.0, 135.0]],
  "waypoint_idx": 0,
  "detected_obstacles": [[25.0, 22.0, 0.0]],
  "destination": [40.0, 135.0]
}
```

**Unity Console 정상 출력:**
```
[DigitalTwin] sim_tick  platform=mobile_0  pos=(23.0,18.0)  obstacles=1
[DigitalTwin] 정책 롤아웃 완료: N개 웨이포인트 (reached=True, t=…s ×6)
```

**Unity → Pyjevsim:**
```json
{
  "type": "twin_ack",
  "platform_name": "mobile_0",
  "virtual_position": [23.0, 18.0, 0.0],
  "waypoints": [[28.0, 26.0], [30.0, 50.0], [45.0, 90.0], [40.0, 135.0]],
  "replanned": true,
  "status": "ok"
}
```

**확인 포인트:**
- `replanned: true`
- `waypoints[0]`이 기존 경로에 없는 우회 경유점
- Scene 뷰에서 빨간 실린더 오브젝트(`DT_Obs_25_22`) 생성됨

---

## 좌표 확인 방법

Unity와 Pyjevsim 좌표 변환 규칙:

```
Pyjevsim (x, y, 0)  →  Unity (x, 0, y)
Unity (X, 0, Z)     →  Pyjevsim (X, Z, 0)
```

Unity Scene 뷰에서 `DT_VirtualBoat` 위치가 `(sim_x, 0, sim_y)`인지 확인.

예: Pyjevsim `position: [23.0, 18.0, 0.0]` → Unity `(23, 0, 18)`

---

## 오류 상황별 대처

### Unity Console에 연결 오류 반복
```
[DigitalTwin] 연결 오류: … → 2s 후 재연결
```
→ Pyjevsim 서버가 실행 중인지 확인  
→ 포트 8765이 다른 프로세스에 점유되지 않았는지 확인 (`netstat -an | findstr 8765`)

---

### Unity Console에 JSON 파싱 실패
```
[DigitalTwin] JSON 파싱 실패: …
```
→ Pyjevsim이 보내는 JSON 형식 확인 (`detected_obstacles` 필드가 `null`이 아닌 `[]`인지)  
→ `float[][]` 형식: `[[x,y,z], ...]` — 중첩 배열 형식 확인

---

### twin_ack에서 `replanned: false` (장애물 있는데)
```
[DigitalTwin] NavMesh 경로 계산 실패 → 기존 경로 유지
```
→ NavMesh가 해당 위치에 베이크되어 있는지 확인  
→ `navMeshSampleRadius`를 Inspector에서 더 크게 설정 (기본 5m)  
→ 장애물 위치와 목표 웨이포인트가 NavMesh 범위 내에 있는지 확인 (맵: 0~200 × 0~200)

---

### twin_ack 응답이 10초 이상 없음
→ Unity가 NavMesh 계산 중이거나 장애물 처리 중  
→ Unity Console 에러 메시지 확인  
→ Pyjevsim이 `twin_ack` 대기 시간을 10초 이상으로 설정했는지 확인

---

### `DT_VirtualBoat`가 Scene에 없음
→ `WsPlannerClient` Inspector에서 `boatObject`가 null인 경우 Start()에서 자동 생성됨  
→ Unity Hierarchy 창에서 `DT_VirtualBoat` 검색  
→ 없으면 Unity Console에서 에러 확인

---

## Inspector 설정 (선택사항)

Play 전 `WsPlannerClient` 오브젝트 선택 후 Inspector에서 수동 설정 가능:

| 필드 | 기본값 | 설명 |
|------|--------|------|
| `Server Uri` | `ws://localhost:8765` | Pyjevsim 서버 주소 |
| `Reconnect Delay Sec` | `2` | 재연결 대기 시간 |
| `Boat Object` | 비어있음 → 자동 생성 | 씬의 Boat 할당 시 해당 오브젝트 미러링 |
| `Path Agent` | 비어있음 → 자동 탐색 | `BoatColregAgent` 자동 찾음 |
| `Obstacle Prefab` | 비어있음 → 자동 생성 | 커스텀 장애물 프리팹 사용 시 할당 |
| `Nav Mesh Sample Radius` | `5` | NavMesh 탐색 반경 (m) |

---

## 전체 흐름 확인 순서 요약

```
[Terminal]  python examples/pathplan/ws_server.py --port 8765
            → "[Digital Twin] WsPlannerServer uri=ws://localhost:8765"

[Unity]     Play 버튼 클릭
            → Console: "[DigitalTwin] Connected to Pyjevsim @ ws://localhost:8765"
            → Python: "[WsServer] Unity connected from 127.0.0.1:…"

[Pyjevsim]  시뮬레이션 시작 (sea_colregs.yaml)
            → 매 Tick: sim_tick 전송
            → Unity Console: "[DigitalTwin] sim_tick platform=…" 반복 출력
            → Python Console: twin_ack 수신 확인

[장애물 탐지 시]
            → Unity Scene: 빨간 실린더 DT_Obs_XX_XX 생성
            → Unity Console: "NavMesh 재경로 완료: N개 웨이포인트"
            → twin_ack.replanned = true

[시뮬레이션 종료]
            → Pyjevsim 시뮬레이션 완료
            → Unity: "[DigitalTwin] 서버가 연결을 닫았습니다."
            → Unity: 2초 후 재연결 시도 (무시해도 됨)
            → Unity Play 정지
```
