# 통합 범용 프레임워크 실험 계획서

상태: **종료 — E0~E11 승인 범위 3회 실행 및 시각화 검증 완료. 2026-09-03 raw 산출물 삭제됨,
결과는 이 문서(§11~12)와 아래 보고서에만 기록으로 남는다. 후속 실험은 별도 계획으로 새로
시작한다.**
원칙: 실제 데이터와 실제 소프트웨어 인프라를 사용하고, 카메라·환경 센서·로봇·드론·차수벽
같은 물리 하드웨어만 provider mock으로 대체한다. 사용자는 2026-09-02에 제시된 전체 실행
범위를 승인했다. 단, 승인된 조건에서 데이터 manifest·환경·비용이 실질적으로 바뀌면 변경된
조건을 실행 전에 다시 제시한다.

최종 판정과 수치 요약은
[2026-09-02_system-generality-experiment-result.md](../../../reports/2026-09-02_system-generality-experiment-result.md),
SSD 시각 품질 후속 분석은
[2026-09-02_ssd-visual-quality-analysis.md](../../../reports/2026-09-02_ssd-visual-quality-analysis.md)를
따른다. `experiments/system-generality/runs/`의 raw event·metrics·영상·dashboard와
`perception-framework/deploy/integration/artifacts/`의 OTel 증거는 결과를 문서로 기록한 뒤
삭제했다. **(2026-09 갱신)** `experiments/`의 실행 코드·manifest 자체도 재사용 계획이 없어
전체 삭제했다 — 위 보고서의 "부록: 실험 세팅"에 실행 명령·source-lock·environment를
남겨뒀으므로 재현하려면 그 내용을 기준으로 스크립트를 다시 작성해야 한다.
Capability 계약과 외부 기술의 채택 경계는
[design/external-technology-decisions.md](../design/external-technology-decisions.md)를 따른다.

## 1. 목적과 가설

동일한 프레임워크가 시설 감시, 하천 위험 관리, 미확인 객체 지속학습 후보 처리에 재사용되는지
검증한다. 세 시나리오에서 core Python package, 계약, container image, MQTT↔Kafka Bridge,
K3s 제어, OTLP 관측 경로를 고정한다. 도메인 차이는 profile, 데이터 manifest, 규칙과 주입된
hardware provider로만 표현한다.

- H1: 새 도메인을 추가해도 core 코드 변경 LOC는 0이다.
- H2: 세 시나리오 모두 동일 command lifecycle과 wire schema를 통과한다.
- H3: provider 장애가 해당 capability만 축소하며 다른 기능과 관측 경로를 중단하지 않는다.
- H4: 이벤트 기반 수집은 항상 고주기 수집보다 전송량을 줄이되 위험 이벤트 누락을 증가시키지 않는다.
- H5: 사용자 확인을 받은 후보만 학습 가능 상태로 승격되고, 검증·승인 전 모델은 활성화되지 않는다.
- H6: 관리자 화면에서 원본 입력, provider 선택 근거, 시간별 처리 단계, 최종 판정과 명령 결과를
  동일 ID로 추적할 수 있고, 화면의 집계값은 raw artifact에서 코드로 재생성된다.

## 2. 공통 시스템과 고정 조건

| 항목 | 고정 조건 |
|---|---|
| 코드 | `perception-framework/perception_framework/`; run 시작 시 Git commit 기록 |
| 실행 | 동일 OCI image와 Python dependency lock/checksum |
| 오케스트레이션 | 현재 K3s 단일 Ready 노드; namespace는 run별 분리 |
| 말단↔엣지 | 실제 Mosquitto MQTT 5 |
| 엣지↔서버 | 실제 Kafka KRaft 단일 broker |
| 관측 | 실제 OTel Collector; metric·event·trace 분리 |
| 직렬화 | profile의 동일 `SerializationPolicy`; 물리 명령은 Protobuf binding |
| 제어 | `CommandExecutionSupervisor` + `HardwareAdapterHandler`; mock만 교체 |
| 계약 | `TaskIntent → RequiredCapability → Capability → Implementation → ExecutionProfile → RuntimeInstance` |
| 반복 | manifest당 3회; seed와 장애 주입 시각 고정 |
| 시간 | 원본 event 순서를 유지한 accelerated replay; 배속을 run header에 기록 |

범용성 판정 시 `perception/`, `planning/`, `risk/`, `runtime/`, `contracts/`의 도메인명 분기와
변경 diff를 자동 검사한다. 시나리오별 adapter·profile·manifest 추가는 허용한다.

### 2.1 계약 적용 규칙

| 단계 | 실험에서 고정·기록할 내용 | 실패 처리 |
|---|---|---|
| `TaskIntent` | required/optional capability, deadline, max input age, minimum evidence, safety invariant | hard constraint 미충족 시 임무 거부 또는 명시적 degraded mode |
| `Capability` | 구현 독립 semantic I/O, property, precondition, limitation | 의미 불일치 provider 제외 |
| `Implementation` | provider/model ID, implementation version, artifact digest | digest·version 누락 시 후보 제외 |
| `ExecutionProfile` | runtime, hardware, input profile, resource, 실측 latency·quality, evidence manifest | 실행 조건이 다른 과거 측정값 재사용 금지 |
| `RuntimeInstance` | 배치 위치, health, health TTL, 현재 load | health 없음·TTL 만료 시 선택 금지 |

selector는 capability 충족 → hard constraint → evidence 유효성 → runtime health → 비용 순으로
평가한다. 선언 성능과 이번 run의 실측 성능은 별도 필드로 저장한다. 현재 단일
`AIProviderCapability` 호환 구조를 사용한다면 위 계층으로 변환된 snapshot도 raw artifact에
남겨 migration 전후 선택 결과가 같은지 검사한다.

## 3. 사용 데이터

### D1. 시설·이동 관측 영상

- 원본: MDDRobots, CC BY 4.0
- 경로:
  - `datasets/mddrobots_subset/DataSet_RobotPiCamera_RGB_test1.zip`
  - `datasets/mddrobots_subset/DataSet_XTION_RGB_test1.zip`
  - `datasets/mddrobots_subset/DataSet_GOPRO_RGB_test3.zip`
  - `datasets/mddrobots_subset/DataSet_P40PRO_RGB_test3.zip`
- 사용법: 원본 zip은 보존하고, 코드가 생성한 frozen manifest에 포함된 프레임만 임시 추출한다.
- 역할: Test 1은 비교적 정상 조건, Test 3은 조명·배치·시점 변화와 이상 조건으로 사용한다.
- 제한: 동기화된 고정 다중 카메라 데이터가 아니다. 서로 다른 실제 영상 source를 논리 카메라로
  replay하여 provider 교체와 임무 흐름을 검증할 뿐, 실제 카메라 간 기하·시간 연계 정확도는 주장하지 않는다.

### D2. 하천 강우·수위

- 출처: WAMIS 공개 API, 2022-08-05~14 서울 집중호우
- provenance: `datasets/climate_hrfco_2022_08/PROVENANCE.json`
- 강우: `datasets/climate_hrfco_2022_08/rainfall/*.csv`
- 수위: `datasets/climate_hrfco_2022_08/water_level/*.csv`
- 제외: `water_level/1018692.csv`는 유효 표본이 0개이므로 사전 규칙으로 제외한다.
- 결측치는 보간하지 않고 `missing=1`로 전달한다. 결측을 정상값 또는 위험 해소 근거로 쓰지 않는다.

### D3. 미확인·환경 변화 후보

- MDDRobots Test 1을 기준 분포, Test 3의 다른 카메라·조명·배치·시점을 변화 분포로 사용한다.
- TAO는 현재 annotation만 있고 대응 frame 전체가 없으므로 본 실행 입력에서 제외한다.
- 사용자 확인은 실제 UI/CLI 입력으로 수행하고 AI 후보와 별도 audit record로 저장한다.

모든 파일은 실행 전 SHA-256, 크기, 선택 이유가 포함된
`experiments/system-generality/manifests/<run-id>.json`으로 동결한다. 임의 프레임 선별은 금지한다.

## 4. 시나리오 A — 감시에서 이동 임무로 전환

1. `facility.json` profile로 복수 논리 카메라 stream을 replay한다.
2. 추적 객체가 관측 범위를 벗어나거나 근거 충분도 기준 아래로 내려가면 메인 임무를 생성한다.
3. 동일 planning contract가 재관측 위치 이동, 추가 관측, 결과 보고 서브태스크로 분할한다.
4. selector가 capability·배터리·링크 상태로 mock 로봇 또는 드론 provider를 선택한다.
5. 실제 MQTT→Bridge→Kafka와 역방향 명령 경로로 acceptance/status/result를 수집한다.
6. 정상, 명령 거부, 중복 명령, 이동 중 cancel, 링크 단절·복구를 동일 장애 schedule로 실행한다.

지표: 임무 생성률, 불필요 임무율, 서브태스크 완결률, command 중복 실행 0건, cancel terminal 상태,
왕복 지연 p50/p95, outbox 재전송 성공률, 장애 영향 capability 수.

관리자용 영상에는 frame timestamp, logical camera, track ID, bounding box/mask, class 또는
`unknown`, confidence/evidence, 사용 provider와 execution profile ID를 overlay한다. 다중 모델은
동일 프레임을 좌우 비교하거나 시간축 layer로 표시하여 **어느 시각에 어떤 모델이 실행·추가·
fallback되었는지** 보여준다. 객체가 관측 범위를 벗어난 시각, 임무 생성, provider 선택,
acceptance, 이동·재관측, terminal result를 영상 timeline marker로 연결한다.

화면에는 계약 계층을 축약하지 않고 `TaskIntent → RequiredCapability → Capability →
Implementation → ExecutionProfile → RuntimeInstance` 순서로 표시한다. 모델명만 보여주지 않고
선택된 구현, 제외된 후보와 제외 사유, health TTL, deadline·resource 조건, 실제 실행 device,
fallback 전후 상태를 동일 `frame_id`와 timestamp로 연결한다. 관리자는 영상 위의 모델 badge를
선택해 해당 시점의 계약 snapshot과 raw record를 확인할 수 있어야 한다.

모델별로 end-to-end/inference latency p50·p95, effective FPS, CPU/GPU memory, 처리·누락 frame 수,
detection 수, track 지속 길이·ID switch, provider 선택·fallback 횟수와 모델 간 box/label 불일치를
표시한다. precision/recall·mAP는 검증된 ground truth가 manifest에 포함된 구간에만 계산한다.
annotation이 없는 frame의 confidence나 모델 간 합의를 정확도로 표현하지 않는다.

## 5. 시나리오 B — 하천 이벤트 기반 수집과 차수벽 제어

“방화벽”은 본 계획에서 **차수벽/수문 mock actuator**로 해석한다. 의미가 네트워크 방화벽이면
별도 계획이 필요하다.

비교군은 같은 WAMIS 시계열과 위험 규칙을 사용한다.

- B0: 모든 센서를 전체 구간 고주기로 전송한다.
- B1: 평상시 저주기, 강우·수위 event 발생 시 고주기로 전환한다.
- B2: B1과 같지만 강우 source 하나를 정해진 구간 동안 unavailable로 만든다.

위험 전이는 차수벽 mock에 Protobuf 명령을 보내고 acceptance와 terminal result를 분리 기록한다.
지표는 전송 message/byte, CPU·메모리, 위험 사건 recall, 탐지 지연, 결측 상태에서의 잘못된 안전
판정 수, 중복 actuation 0건이다. B1의 자원 절감만 좋아지고 recall이 악화되면 H4는 기각한다.

관리자 화면은 강우·수위 원시 시계열, 수집 주기 전환, 결측 구간, 위험 threshold, 명령 상태를
동일 시간축에 표시한다. B0/B1/B2의 누적 message·byte와 위험 탐지 지연은 비교 chart로 만들고,
차수벽 이미지는 실제 동작 영상처럼 꾸미지 않고 `MOCK ACTUATOR` 상태 panel로 명확히 구분한다.

## 6. 시나리오 C — 미확인 객체와 승인형 지속학습

1. 기준 조건에서 threshold와 baseline을 고정한다.
2. Test 3 변화 입력에서 unknown·저신뢰·근거 부족 후보를 자동 생성한다.
3. 기존 provider와 가용 보조 provider의 추정을 함께 제시하되 unknown을 임의 이름으로 확정하지 않는다.
4. 실제 사용자가 확인·거부·보류 중 하나를 입력한다.
5. 확인된 항목만 lineage의 학습 후보로 승격하고, 거부·보류 항목은 분리 보존한다.
6. 1차 실행은 후보 생성과 gate까지만 검증한다. 실제 재학습은 별도 실행 승인 후 수행한다.
7. 재학습 시 고정 검증셋, 기존 조건 회귀, 망각 평가, shadow/canary, 사용자 승인, rollback을 순서대로 적용한다.

지표: 사용자 확정 표본에서의 unknown precision/recall, 사용자 질의 수, 확인·거부·보류 비율,
미승인 모델 활성화 0건,
사건→후보→확인→데이터→모델→배포 lineage 완전성이다. 학습 후에는 새 조건 성능과 기존 조건
성능을 함께 보고하며 개선이 없거나 기존 성능이 악화된 결과도 그대로 기록한다.

관리자용 review 화면은 후보 frame 전후 구간, 기존·보조 provider의 box/mask/label/confidence,
unknown 근거, 사용자 확인·거부·보류 control을 함께 제공한다. 실제 재학습 승인 후에는 동일
검증 frame의 before/after 결과를 나란히 표시하되 threshold와 표본 순서를 고정하고, 개선·회귀·
미변화 수를 모두 표시한다.

## 7. 범용성 비교와 합격 기준

| 기준 | 합격 조건 |
|---|---|
| 동일 core | 시나리오 전환을 위한 core 변경 LOC = 0 |
| 동일 계약 | 세 시나리오 payload의 schema/Protobuf validation 100% |
| 동일 인프라 | 동일 MQTT, Kafka, K3s, OTel 배포 사용 |
| provider 교체 | hardware mock 종류가 바뀌어도 상위 호출 코드 변경 0 |
| 장애 격리 | 장애와 무관한 core capability가 계속 ACTIVE |
| 추적성 | 모든 명령·후보·모델 단계가 ID와 timestamp로 연결 |
| 재현성 | 같은 manifest·seed·version에서 사건 순서와 판정 일치 |
| 계약 추적 | 모든 선택이 intent/capability/implementation/profile/instance ID로 역추적 가능 |
| 가시화 무결성 | 화면 수치·overlay가 raw record에서 재생성되며 metrics JSON과 일치 |

단일 정확도 수치가 범용성을 증명하지 않는다. 위 구조적 조건을 모두 만족하고, 각 도메인의 불리한
결과와 실패가 같은 관측·감사 계약으로 남는지를 함께 확인한다.

## 8. 관리자 결과 가시화와 코드 산출물

가시화는 수작업 편집이나 유리한 frame 선별 없이 committed code가 frozen manifest와 raw event를
읽어 생성한다. 추론 경로는 시각화 코드와 분리하고, overlay 실패가 metric 계산을 바꾸지 않게 한다.

### 8.1 구현 단위

아래 코드는 현재 구현되어 E0~E11 결과 생성에 사용됐다. 신규 모델·데이터·threshold를 사용하는
후속 실험은 같은 인터페이스와 검증 절차를 재사용하되 변경된 실행 조건을 다시 승인받는다.

| 코드 | 입력 | 출력 |
|---|---|---|
| `experiments/system-generality/render_video.py` | manifest, frame, detection/track/provider event JSONL | timestamp·box/mask·track·provider·상태가 포함된 MP4 |
| `experiments/system-generality/render_timeline.py` | command, selection, fault, OTel export | 단계별 HTML timeline과 PNG |
| `experiments/system-generality/render_dashboard.py` | raw metrics/event bundle | 시나리오 비교 HTML dashboard |
| `experiments/system-generality/verify_visualization.py` | raw bundle, 생성된 visualization manifest | frame/event 수, metric 값, artifact hash 일치 검사 |
| `experiments/system-generality/build_vision_visualization.py` | 모델별 raw JSONL, frozen manifest | 비교용 event bundle·영상·dashboard 입력 |

각 overlay record는 `run_id`, `frame_id`, `timestamp`, `task_intent_id`, `capability_id`,
`implementation_id`, `execution_profile_id`, `runtime_instance_id`, `model_start/end`,
`selection_reason`, detection/track 결과, `command_id`를 포함한다. 해당 단계가 실행되지 않았으면
빈 값을 숨기지 않고 `NOT_RUN`과 사유를 표시한다.

### 8.2 공통 화면

1. **Run 요약:** dataset·manifest hash, Git commit, image digest, hardware/runtime, 반복 번호.
2. **영상 재생:** 원본/overlay toggle, frame timestamp, 모델별 색상 legend, track trail.
3. **처리 과정:** 입력→provider 후보→선택/제외 이유→모델 실행 구간→fusion/fallback→판정.
4. **임무·명령 timeline:** task 생성부터 acceptance/status/result 및 fault 주입까지 연결.
5. **지표 비교:** 반복별 개별값과 평균·분산, p50/p95, null·실패 결과를 함께 표시.
6. **근거 drill-down:** 화면 요소를 클릭하면 대응 raw JSONL record와 artifact ID를 표시.
7. **계약 상태:** intent 요구사항, capability semantic I/O, implementation digest, profile 자원 조건,
   runtime health와 TTL, 후보별 선택·제외 사유.
8. **모델 비교:** 같은 원본 frame을 기준으로 모델별 box/mask/label/confidence와 `NOT_RUN`을
   나란히 표시하고, 추가 모델 호출·fusion·fallback 시각을 timeline cursor와 동기화.

영상은 기본 1배속과 event 중심 seek index를 제공한다. 빠른 구간도 원래 timestamp를 유지하며,
관리자가 처리 시간을 오해하지 않도록 replay 배속과 실제 inference duration을 별도로 표시한다.
색상만으로 상태를 구분하지 않고 label·pattern을 병행한다.

### 8.3 공정성·무결성 규칙

- manifest의 모든 대상 frame을 처리하고 실패 frame도 검은 화면으로 대체하지 않고 오류 상태로 남긴다.
- 대표 영상 clip은 사전에 고정한 시간 구간 또는 모든 event window로 생성하며 사후 선별하지 않는다.
- box/mask는 raw 좌표에서 코드로 투영하고 사람이 위치를 보정하지 않는다.
- 원본을 resize 또는 letterbox할 때 `scale_x`, `scale_y`, `pad_x`, `pad_y`를 artifact에 기록하고
  box·mask·track에도 이미지와 정확히 같은 affine transform을 적용한다. 원본 좌표와 화면 좌표를
  함께 보존하며 synthetic corner box round-trip unit test를 통과하지 못하면 영상을 배포하지 않는다.
- renderer는 frame 원본 크기와 모델 출력 좌표계(`pixel`, `normalized`, `letterboxed`)를 확인한다.
  좌표계가 누락되거나 box가 화면 경계를 벗어나면 조용히 clamp하지 않고 검증 실패로 처리한다.
- chart 축, threshold, 색상 범례는 비교군 전체에서 고정한다.
- raw artifact는 불변으로 보존하고 visualization manifest에 입력·출력 SHA-256과 생성 명령을 기록한다.
- UI 표시값과 `metrics.json`의 불일치는 검증 실패로 처리한다.

### 8.4 관리자에게 보여줄 최소 결과 세트

| 관리자 질문 | 필수 화면·지표 | 계약 근거 |
|---|---|---|
| 무엇을 보았는가 | 원본/overlay, box·mask·track, unknown, 모델별 detection 수 | capability output schema |
| 왜 이 모델인가 | 선택·제외 후보, deadline/resource/input/health 판단 | intent, profile, runtime instance |
| 언제 추가 분석했는가 | model start/end, gate, escalation, fusion, fallback timeline | execution event와 동일 timestamp |
| 얼마나 빨랐는가 | end-to-end/inference p50·p95, FPS, CPU/GPU memory, 누락 frame | execution profile evidence |
| 결과를 믿을 수 있는가 | ground truth 유무, precision/recall 계산 가능 여부, 실패·null 결과 | evidence manifest와 limitation |
| 이후 무엇을 했는가 | mission/command ID, acceptance/status/result, cancel·fault 상태 | physical command lifecycle |

모델 다중 사용 결과는 대표 이미지만 따로 고르지 않고 frozen manifest 전체 영상과 event seek index를
제공한다. 관리자는 한 frame에서 원본, 각 모델 결과, 최종 fusion 또는 선택 결과를 동시에 보고,
timeline을 이동해 경량 gate→1차 모델→추가 open-vocabulary 모델→fallback 과정과 각 단계 소요
시간을 확인할 수 있어야 한다. 정확도 정답이 없는 실행은 화면 상단에 `GROUND TRUTH UNAVAILABLE`을
고정 표시하고 confidence나 모델 합의를 precision·recall처럼 표현하지 않는다.

## 9. 실행 환경·비용·산출물

- 환경: 현재 PC, RTX 3060/OpenCL CPU fallback, Docker Compose의 MQTT·Kafka·OTel, 기존 K3s.
- 예상 시간: 데이터 manifest 작성·부분 추출 1~2시간, 시나리오별 3회 실행 약 1~3시간,
  분석 2~4시간. 실제 재학습 시간과 비용은 모델이 확정되지 않아 산정하지 않는다.
- 추가 데이터 다운로드: 없음. 기존 zip에서 manifest 표본만 추출한다.
- raw: `experiments/system-generality/runs/<run-id>/raw/`
- metric: `experiments/system-generality/runs/<run-id>/metrics.json`
- run bundle: `experiments/system-generality/runs/<run-id>/bundle.json`
- 구조화 event: `experiments/system-generality/runs/<run-id>/raw/events.jsonl`
- overlay 영상: `experiments/system-generality/runs/<run-id>/visualizations/videos/`
- dashboard/timeline: `experiments/system-generality/runs/<run-id>/visualizations/dashboard.html`
- 가시화 manifest·검증: `experiments/system-generality/runs/<run-id>/visualizations/manifest.json`,
  `verification.json`
- OTel 증거: `perception-framework/deploy/integration/artifacts/`
- 최종 보고서: `reports/YYYY-MM-DD_HHMM_주제.md` 형식 — E0~E11 실행분은
  `reports/2026-09-02_system-generality-experiment-result.md`,
  `reports/2026-09-02_ssd-visual-quality-analysis.md`

**(2026-09-03 갱신)** 위 `runs/<run-id>/` 산출물과 OTel 증거는 결과를 보고서·본 문서 §11~12로
기록한 뒤 삭제했다. 코드(`*.py`)와 `manifests/`, `model-source-lock.*`는 다음 실행을 위해
남겨뒀다. 새 실험을 시작하면 이 절의 경로는 새 `<run-id>` 기준으로 다시 채워진다.

가시화 생성 시간과 저장량은 manifest의 frame 수·해상도·codec을 확정한 뒤 승인 요청에 별도
산정한다. HTML/PNG는 추가 외부 서비스 없이 로컬에서 열 수 있어야 하며, MP4 codec과 renderer
dependency version도 image/lock에 고정한다.

## 10. 알려진 한계와 승인 Gate

- mock은 물리 이동, 비행 안정성, 차수벽 동작, 제동거리, 발열과 실제 센서 지연을 증명하지 않는다.
- MDDRobots로 진짜 동기화 다중 고정 카메라 연계 성능을 증명할 수 없다.
- WAMIS replay는 현장 센서와 actuator의 폐루프 안전성을 증명하지 않는다.
- 실제 재학습은 모델·학습 데이터·GPU 시간·평가 threshold를 별도로 제시하고 다시 승인받는다.
- overlay는 판정 근거를 보여주는 감사·설명 수단이지 실제 물리 안전 검증을 대신하지 않는다.
- bounding box나 confidence가 모델의 내부 인과 설명을 의미하지 않는다.

실행 전에는 최종 manifest 경로, 정확한 표본 수, image/tag, hardware·software version, 각 비교군,
threshold, 반복 수, 예상 시간·저장량, raw·metric·영상·dashboard·검증 산출물 경로와 관리자에게
보일 예시 layout을 출력한다. 또한 사용할 capability/implementation/execution profile/runtime
instance 목록과 digest, health TTL, selector 제외 규칙을 제시한다. 사용자 승인 전에는 데이터
추출, 모델 실행, fault 주입, 시나리오 실행 또는 결과 가시화를 시작하지 않는다.

## 11. E5~E11 인프라 실행 결과

이 절은 계획이 아니라 2026-09-02에 승인 후 실행한 결과다. 최종 판정 대상은 동일 코드로 실행한
`infra-20260902-r6`, `infra-20260902-r7`, `infra-20260902-r8` 세 run이며 모두 `PASS`였다.
각 run의 raw event와 코드 산출 metric은
`experiments/system-generality/runs/<run-id>/infra/`에 보존한다.

- E5: health TTL 만료와 GPU 후보 제외 후 CPU/local capability fallback
- E6: 과부하·입력 modality 불일치·논리 기기 자원 차이에 따른 후보 제외
- E7: 논리 network 단절 중 device-local 보호 capability 유지
- E8: runtime instance와 execution profile ID가 포함된 선택 근거 기록
- E9: Robot/Drone 배터리·링크·action hard constraint 기반 선택
- E10: 실제 MQTT↔Kafka 전달 및 물리 command lifecycle/cancel
- E11: WAMIS B0/B1/B2 전송량 비교

E8에서 검증한 것은 선택·instance/profile 추적성이다. 실제 원격 artifact download, container
cache eviction 또는 model cold-load 성능은 이 run에서 실행하지 않았다.

### 11.1 실제 실행과 mock 경계

| 검증 항목 | 실행 방식 | 범위 |
|---|---|---|
| MQTT↔Kafka | 실제 Mosquitto·Kafka·Bridge | 고유 topic을 사용한 양방향 업무 메시지 전달 |
| K3s | 실제 K3s API 조회 | Ready 물리 노드 1개; 다중 물리 노드 검증 아님 |
| provider 선택 | 실제 selector 코드 + 동결된 논리 자원 profile | Device/Edge/Server와 GPU/CPU 자원 차이는 mock |
| TTL·과부하·입력 비호환·GPU 부재 | selector 상태·제약 주입 | 실제 GPU 전원 차단이나 물리 노드 장애 아님 |
| 네트워크 단절 | 논리 link 상태 주입 | 케이블·4G·무선 링크를 물리적으로 끊지 않음 |
| Robot/Drone·명령 취소 | 실제 command lifecycle 코드 | 이동·비행·vendor SDK와 물리 actuator는 mock |
| WAMIS B0/B1/B2 | 실제 저장 CSV replay | 현장 센서·차수벽 폐루프 검증 아님 |

네트워크 단절 mock에서는 device-local `motion-risk-cpu`를 `AVAILABLE`로 유지하고 server의
`open-vocabulary-gpu`를 `UNAVAILABLE`로 제외했다. Robot/Drone 선택에서는 배터리 12%인 논리
로봇을 제외하고 배터리 74%인 논리 드론을 선택했다. 세 run 모두
`Command → Acceptance → EXECUTING → Cancel → CANCELED` terminal 상태를 기록했다.

### 11.2 반복 결과

| run | MQTT→Kafka 전달 | Kafka→MQTT 전달 | MQTT→Kafka p50 | Kafka→MQTT p50 | K3s 물리 노드 | 결과 |
|---|---:|---:|---:|---:|---:|---|
| `r6` | 3/3 | 3/3 | 1.273 ms | 2.961 ms | 1 | PASS |
| `r7` | 3/3 | 3/3 | 1.225 ms | 3.730 ms | 1 | PASS |
| `r8` | 3/3 | 3/3 | 1.941 ms | 2.762 ms | 1 | PASS |

세 run의 방향별 p50 중앙값은 MQTT→Kafka 1.273 ms, Kafka→MQTT 2.961 ms다. 표본이 방향별
9건뿐이므로 운영 지연 보장이나 대규모 부하 성능으로 일반화하지 않는다. TTL 만료 후 유효한
70 ms motion provider fallback, overload·입력 modality 불일치·GPU tag 부재 후보 제외는 세
run 모두 확인했다.

WAMIS 입력은 run마다 10개 series, 총 2,160표본이다. B0는 2,160건(100%), B1 event gate는
674건(31.20%), B2 event+직전 문맥은 807건(37.36%)을 전송 대상으로 선택했고 결측치를 보간하지
않았다. 이번 B2 실행은 계획 본문의 “source unavailable” 장애군이 아니라 event 직전 문맥을
추가한 비교군이다. 따라서 source unavailable에서의 위험 recall은 아직 검증 완료로 표시하지 않는다.

### 11.3 실패·중간 run 보존

- `infra-20260902-r1`: sandbox 권한 때문에 K3s와 localhost transport가 `NOT_RUN`인 실패 run.
- `infra-20260902-r2`: Kafka consumer를 표본마다 추가해 consumer-group rebalance가 발생했고
  MQTT→Kafka 2건을 놓친 실패 run. raw를 삭제하지 않고 실행기를 단일 dispatcher로 수정했다.
- `infra-20260902-r3`~`r5`: 수정 과정의 중간 통과 run. 최종 3회 판정에는 사용하지 않는다.

실패 run을 성공 통계에서 제거해 숨기지 않으며, r2는 실제 인프라 손실률이 아니라 실험 실행기
결함으로 분류한다. E5~E11 결과는 계약·선택·단일 노드 통신 동작을 지지하지만 실제 다중 기기,
열·전력, 무선 품질, 로봇 제어 안전성 또는 차수벽 작동 성능을 증명하지 않는다.

## 12. E0~E4 영상 실행 결과

고정 manifest SHA-256 `46533b649b3103a5d58564c4770a34ab3eb5942478133191d2b9beba1d71f28b`의
495프레임을 사용했다. 정규 arm 27개(직접 모델 CPU 9, 실제 CUDA 9, gate 9)를 각 3회
완주했으며 완료 run의 처리 실패는 0건이다. 초기 CUDA library 탐색 실패로 CPU에 fallback된
run과 중단된 partial run도 `complete=false`와 실제 provider를 기록해 보존했다.

| arm | 3회 평균 지연 범위 | 관측 결과 |
|---|---:|---|
| SSD CPU | 49.9~57.1 ms | 회당 detection 1,172건 |
| SSD CUDA | 61.7~65.9 ms | 회당 detection 1,173건 |
| TinyYOLO CPU | 62.9~67.2 ms | 회당 detection 199건 |
| TinyYOLO CUDA | 59.9~63.3 ms | 회당 detection 199건 |
| OWL-ViT CPU | 971~1,004 ms | 회당 evidence 16건 |
| OWL-ViT CUDA | 1,039~1,098 ms | 회당 evidence 18건 |
| frame difference | 15.9~17.1 ms | 회당 445/495 변화 판정 |
| MOG2 | 17.9~20.4 ms | 회당 439/495 변화 판정 |
| 조건부 escalation | 690~706 ms | 회당 OWL-ViT 317회 호출 |

CUDA가 항상 더 빠르지 않았다. 측정에는 프레임별 `nvidia-smi` 호출과 CPU↔GPU 복사 노드가
포함되고 arm을 병렬 수행했으므로 독립 실행 성능 순위나 운영 SLA로 해석하지 않는다. annotation이
없는 데이터이므로 detection/evidence 수와 confidence는 정확도·recall이 아니다. 변화 threshold
0.08은 사전 고정값이나 데이터 최적값이 아니며 stride 30 표본은 원 영상의 연속 프레임이 아니다.

관리자 확인용 산출물은
`experiments/system-generality/runs/vision-e0-e4/visualizations/`에 있다. SSD CPU,
OWL-ViT CUDA, 조건부 escalation 영상은 각각 manifest 전체 495프레임, 1280×720, 10 FPS다.
timeline과 dashboard도 생성했으며 검증 결과는 `passed=true`, 누락 프레임 0개, raw 집계와 일치한
metric leaf 641개다. 모든 영상·화면에는 입력과 출력 SHA-256 receipt가 있다.

단, 후속 육안 감사에서 기존 renderer가 원본 frame을 1280×720으로 resize하면서 원본 픽셀
`box_xyxy`에 같은 축척을 적용하지 않은 결함을 확인했다. 위 `passed=true`는 frame 수·hash·metric
일치만 검증한 결과이며 **박스의 공간 정합성을 검증한 결과가 아니다**. 따라서 기존 overlay는
처리 흐름 확인용으로만 사용하고 검출 precision·recall 또는 box 품질 판정에 사용하지 않는다.
후속 YOLO-World 비교부터는 §8.3의 좌표계·affine transform·corner-box 검증을 합격 조건에
포함하며, 기존 SSD도 수정된 renderer로 함께 재생성해 동일 조건에서 비교한다.

이번 실행은 보유 SSD·TinyYOLO·OWL-ViT와 변화 gate만 검증했다. 신규 후보 artifact 전체
25.16 GiB와 권고 최소 subset 5.30 GiB는 아직 다운로드 승인이 확정되지 않아 실행 범위에
포함하지 않았다. 물리 기기 분리 배포, 다중 K3s 노드, 실제 카메라 동기화, 실제 로봇·드론 제어,
MobileCLIP·tracking·SLAM·depth·pose의 정확도는 미검증이다.
