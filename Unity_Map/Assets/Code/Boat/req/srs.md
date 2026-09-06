# SRS — COLREG 선박 자율항해 ML-Agents 시스템

> **작성일**: 2026-06-29  
> **버전**: 1.0.0  
> **대상 브랜치**: 현재 작업 디렉토리 (`D:\My project`)

---

## 1. 수정/생성 파일 내역

### 1.1 신규 생성 파일

| 파일 경로 | 역할 |
|-----------|------|
| `Assets/Code/Boat/BoatColregAgent.cs` | COLREG 기반 ML-Agents 에이전트 (독립 구현체) |
| `Assets/Code/Boat/BoatTrainingManager.cs` | 선박 전용 학습 관리자 — 경로 장애물 배치 및 커리큘럼 |
| `Assets/Code/Boat/req/srs.md` | 본 요구사항/변경이력 문서 |
| `Assets/Code/Go1/WebSocket/Go1ObstacleWebSocketReceiver.cs` | UDP 대체 WebSocket 장애물 수신기 |
| `D:/mlagent/BoatConfig/boat_colreg.yaml` | ML-Agents PPO 학습 설정 파일 |
| `D:/mlagent/BoatConfig/plot_training.py` | 학습 진행 시각화 Python 스크립트 |

### 1.2 수정 금지 파일

| 파일 경로 | 이유 |
|-----------|------|
| `Assets/Code/Go1/GO1Agent.cs` | 기존 GO1 로봇 로직 보존 — 변경 금지 |

### 1.3 기존 파일 (변경 없음, 참조만)

| 파일 경로 | 역할 |
|-----------|------|
| `Assets/Code/Boat/BoatAgent.cs` | GO1Agent 상속 선박 에이전트 (기존 경로 재주행 로직) |
| `Assets/Code/Boat/BoatBuoyReplanController.cs` | 부표 기반 경로 재탐색 컨트롤러 |
| `Assets/Code/Boat/BoatPathVisualizer.cs` | 경로 LineRenderer 시각화 |
| `Assets/Code/Receiver/Go1ObstacleJsonReceiver.cs` | UDP 장애물 수신기 (기존 유지) |

---

## 2. 요구사항

### 2.1 시스템 요구사항

| ID | 요구사항 | 우선순위 |
|----|---------|---------|
| SR-01 | ML-Agents 학습 에이전트는 GO1Agent를 수정하지 않고 독립 구현 | 필수 |
| SR-02 | 보상체계는 COLREG Rule 13/14/15/16/17을 준수하는 방향으로 설계 | 필수 |
| SR-03 | 연속 행동 공간(추력, 선회) 2차원으로 설계 | 필수 |
| SR-04 | 관측 공간은 자선 상태·목표·타선(최대 3척) 포함 28차원 | 필수 |
| SR-05 | 학습 진행이 시각적으로 확인 가능한 그래프 제공 | 필수 |
| SR-06 | 학습 설정(YAML)은 `D:/mlagent/BoatConfig/` 에 위치 | 필수 |

### 2.2 기능 요구사항 — BoatColregAgent

| ID | 기능 | 설명 |
|----|------|------|
| FR-01 | COLREG 상황 자동 분류 | Rule 13(추월)/14(정면)/15(횡단) 실시간 감지 |
| FR-02 | DCPA/TCPA 계산 | 최근접점거리 및 시간 계산으로 위험도 판단 |
| FR-03 | 타선 탐지 | OverlapSphere로 반경 내 `Vessel` 태그 오브젝트 탐지 |
| FR-04 | 물리 기반 이동 | Rigidbody 추력/선회 적용, 관성 모델링 |
| FR-05 | 에피소드 관리 | 목표 도달/충돌/타임아웃 판정 및 에피소드 종료 |
| FR-06 | Heuristic 지원 | W/S/A/D로 수동 조종 가능 (테스트용) |

---

## 3. COLREG 보상 설계

### 3.1 적용 규칙 및 보상 정의

| COLREG Rule | 상황 | 준수 행동 | 보상/패널티 |
|------------|------|---------|------------|
| Rule 13 | 추월 (타선 후방 ±22.5°에서 접근) | 피추월선 우현측으로 통과 | +0.03 / -0.04 |
| Rule 14 | 정면조우 (±6° 이내, 반대 선수) | 우현 변침 (turn > 0) | +0.03 / -0.08 |
| Rule 15 | 횡단-피항선 (타선이 우현 선방) | 우현 변침 or 감속 | +0.03 / -0.08 |
| Rule 17 | 횡단-유지선 (타선이 좌현 선방) | 침로·속력 유지 | +0.015 |
| 공통 | 위험 CPA (< 8m) 진입 | — | 거리에 반비례 패널티 |
| 공통 | 안전 CPA (8~25m) 유지 | — | +0.01 |

### 3.2 전체 보상 항목 요약

```
스텝 패널티          -0.001  (에이전트가 빠르게 목표 도달하도록 유도)
회전 저크 패널티     -jerk * 0.003  (안정적 항법 유도)
목표 접근 보상       Δdistance * 0.04  (clamp ±0.05)
목표 도달 보상       +1.0  (에피소드 종료)
충돌 패널티          -1.0  (에피소드 종료)
타임아웃 패널티      -0.5  (에피소드 종료)
COLREG 준수         +0.03 ~ +0.015
COLREG 위반         -0.04 ~ -0.08
위험 CPA 패널티      -(dangerDcpa - dcpa)/dangerDcpa * 0.05
```

---

## 4. 관측 공간 (28차원)

```
[0]  heading_sin          자선 선수 sin
[1]  heading_cos          자선 선수 cos
[2]  speed_norm           전진속도 정규화 [-1, 1]
[3]  angular_vel_norm     선회속도 정규화 [-1, 1]

[4]  goal_bearing_sin     목표 방위 sin
[5]  goal_bearing_cos     목표 방위 cos
[6]  goal_dist_norm       목표 거리 정규화 [0, 1]

타선 슬롯 × 3 (슬롯당 7차원, 없으면 0 패딩):
[7+i*7+0]  bearing_sin         타선 방위 sin
[7+i*7+1]  bearing_cos         타선 방위 cos
[7+i*7+2]  dist_norm           타선 거리 정규화
[7+i*7+3]  rel_heading_sin     타선 상대 선수각 sin
[7+i*7+4]  rel_heading_cos     타선 상대 선수각 cos
[7+i*7+5]  rel_speed_norm      상대 속도 정규화
[7+i*7+6]  colreg_situation    상황 코드 /5 정규화
                                (0=없음, 1=정면, 2=피항, 3=유지, 4=추월, 5=피추월)
```

---

## 5. 행동 공간 (연속 2차원)

| 인덱스 | 범위 | 의미 |
|--------|------|------|
| `[0]` | [-1, 1] | 추력 (음수=후진, 양수=전진) |
| `[1]` | [-1, 1] | 선회 (음수=좌현/port, 양수=우현/starboard) |

---

## 6. 학습 설정 (boat_colreg.yaml)

| 하이퍼파라미터 | 값 | 선택 이유 |
|--------------|-----|---------|
| `trainer_type` | `ppo` | 연속 행동 공간에 표준 |
| `batch_size` | 2048 | 연속 행동·장기 보상에 큰 배치 유리 |
| `gamma` | 0.995 | 120초 에피소드 → 장기 할인 필요 |
| `lambd` | 0.99 | GAE 장기 보상 반영 |
| `learning_rate` | 3e-4 → 1e-4 linear decay | 초반 빠른 학습, 후반 안정 수렴 |
| `beta` | 5e-3 | COLREG 다양한 상황 탐색 유도 |
| `curiosity strength` | 0.015 | 새 상황 탐색 촉진 |
| `max_steps` | 10M | Rule 4가지 모두 학습하기 위한 충분한 예산 |

---

## 7. 학습 시작 방법

```bash
# 1. ML-Agents 패키지 설치
pip install mlagents

# 2. Unity 씬에서 Play 시작 (BoatColregAgent 포함)

# 3. 학습 실행
cd D:\mlagent
mlagents-learn BoatConfig/boat_colreg.yaml --run-id=boat_colreg_v1

# 4. TensorBoard로 모니터링
tensorboard --logdir results/

# 5. 학습 곡선 그래프 확인
python BoatConfig/plot_training.py --logdir results/BoatColregAgent/boat_colreg_v1
```

---

## 8. BoatTrainingManager 설계

### 8.1 경로 장애물 배치 방식

```
[Start] ──────────────────────────────────── [Goal]
         |           |           |
         ●(obs 0)    ●(obs 1)   ●(obs 2)
         ↑ 법선 오프셋 ±  ↑           ↑ 교차 배치
```

- 이상 경로(직선)를 장애물 수로 균등 분할
- 각 구간 중점에서 법선 방향으로 ±오프셋 (홀짝 교차)
- `obstacleStartFraction`~`obstacleEndFraction` 범위에만 배치 (시작/목표 직전 제외)

### 8.2 레이어 격리 방식

```
선박 A (layer 8) + A의 장애물 (layer 8)  →  서로 충돌 ✓
선박 B (layer 9) + B의 장애물 (layer 9)  →  서로 충돌 ✓
IgnoreLayerCollision(8, 9) = true         →  A ↔ B 물리 무시 ✓
COLREG 탐지 (태그 기반 OverlapSphere)     →  레이어 무관 ✓
```

### 8.3 커리큘럼 흐름

```
레벨 0: 장애물 1개  →  성공률 ≥ 70%  →  레벨 1: 장애물 2개
레벨 1: 장애물 2개  →  성공률 ≥ 70%  →  레벨 2: 장애물 3개
레벨 2: 장애물 3개  →  성공률 ≥ 70%  →  레벨 3: 장애물 5개
성공률 < 30%       →  레벨 하향 (최소 0)
```

---

## 9. Unity Inspector 설정 체크리스트

```
BoatTrainingManager (빈 GameObject에 부착):
  [ ] Boat Prefab        → BoatColregAgent가 부착된 선박 프리팹
  [ ] Boat Count         → 4
  [ ] Water Center       → 수면 중심 Transform
  [ ] Water Area Radius  → 100
  [ ] Obstacle Prefab    → 부표/장애물 프리팹 (Collider 필수)
  [ ] Obstacles Per Level → { 1, 2, 3, 5 }
  [ ] Layer Base         → 8

BoatColregAgent 컴포넌트 (프리팹 내부):
  [ ] Behavior Parameters → Behavior Name: "BoatColregAgent"
  [ ] Behavior Parameters → Space Type: Continuous
  [ ] Behavior Parameters → Vector Observation Size: 28
  [ ] Behavior Parameters → Continuous Actions: 2
  [ ] Vessel Tag: "Vessel"
  [ ] Max Tracked Vessels: 3
  (Training Manager는 런타임에 자동 연결됨)

Rigidbody 설정 (선박 프리팹):
  [ ] Freeze Position Y: true
  [ ] Freeze Rotation X/Z: true
  [ ] Linear Drag: 1.2
  [ ] Angular Drag: 2.0

Unity 레이어 (Project Settings → Tags and Layers):
  [ ] Layer 8:  BoatGroup_0
  [ ] Layer 9:  BoatGroup_1
  [ ] Layer 10: BoatGroup_2
  [ ] Layer 11: BoatGroup_3

타선 오브젝트 (COLREG 상호작용):
  [ ] Tag: "Vessel"
  [ ] Rigidbody 컴포넌트 부착 (속도 계산용)
```

---

*문서 위치: `Assets/Code/Boat/req/srs.md`*
