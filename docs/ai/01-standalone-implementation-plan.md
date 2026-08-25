# 하드웨어·타 파트 없이 구현·검증 가능한 범위 계획

목적: HW(센서·카메라·GPU), BE(실제 MQTT/Kafka/K3s/백엔드), VZ(Unity 트윈)가 아직 없어도
지금 로컬에서 구현하고 pytest로 검증할 수 있는 요구사항을 가려내고, 각각에 어떤 모델·툴·
테스트 방법·명령·결과 확인법을 쓸지 정리한다.

## 핵심 전제

이 프레임워크는 애초에 "Provider를 fake로 교체해도 상위 로직이 안 바뀐다"는 것이 설계
목표(AI-C-04/12)이므로, **진짜 MQTT 브로커·진짜 카메라·진짜 GPU가 없어도 각 요구사항이
정의한 "동작과 경계"는 fake/synthetic provider로 100% 검증 가능**하다. 막히는 것은 오직
"이 fake를 실제 인프라로 교체했을 때도 동일하게 동작하는가"라는 통합 검증뿐이며, 이는
타 파트가 준비된 뒤 별도 세션에서 진행한다.

즉 아래 표의 "Tier A/B" 항목은 **로직 구현 + 단위 테스트까지 이번에 완결**할 수 있고,
"Tier C"만 실제 통합이 막혀 있다.

## 공통 도구 스택

| 용도 | 라이브러리 | 현재 상태 | 비고 |
|---|---|---|---|
| 테스트 러너 | `pytest` | 설치됨 (`ai-framework/pyproject.toml` dev extra) | 기존과 동일 |
| 수치 연산 (추적·유사도·통계) | `numpy` 2.4.6 | 이미 설치됨 | 추가 설치 불필요 |
| 영상 처리 (캘리브레이션·베이스라인 검출기) | `opencv-python` 5.0.0 | 이미 설치됨 | GUI 없는 `opencv-python-headless`로 나중에 교체 가능 |
| 서브태스크 스키마 검증 | `jsonschema` | 미설치 → `pip install jsonschema` | khw_VZ의 `contracts/*.schema.json` + `validate_examples.py` 패턴과 동일 계열 |
| (선택) 실 탐지모델 스왑 예시 | `ultralytics`(YOLOv8n) | 미설치, 선택사항 | AGPL-3.0 라이선스 확인 필요 — 기본 provider로 채택하지 않고 "교체 가능함을 보여주는 예시"로만 사용 권장 |

기본 원칙: **새 요구사항마다 실제 무거운 모델을 받아오지 않는다.** 대신
`opencv-python`이 이미 내장한 HOG/Haar 같은 가벼운 검출기 하나를 "reference provider"로
쓰고, 필요하면 나중에 다른 provider(YOLO 등)로 교체 가능함을 테스트로 보여주는 정도로
충분하다 — CLAUDE.md 자체가 "검증 목적은 기존 모델보다 정확도를 높이는 것이 아니라 공통
인터페이스·격리 규칙을 만족하는지 확인하는 것"(AI-B-09)이라고 명시한다.

합성 데이터 전략(카메라·로봇 없이 테스트하는 핵심 트릭):

- **추적/연계/위험도(AI-S-*, AI-R-*)**: 실제 영상 대신 결정론적 numpy 배열로 만든 가짜
  bounding box 시퀀스, 가짜 센서 시계열을 테스트 fixture로 만든다. 카메라가 있든 없든
  알고리즘 자체(IOU 매칭, 규칙 기반 위험도)는 좌표·수치 배열만 입력받으므로 동일하게
  검증된다.
- **카메라 캘리브레이션(AI-E-02)**: 실제 체커보드 사진 대신, 알려진 내부파라미터(K)와
  왜곡계수(dist)를 정해두고 `cv2.projectPoints`로 가짜 코너 좌표를 역산해 합성한다.
  `cv2.calibrateCamera`가 원래 K/dist를 오차범위 내로 복원하는지 검증하면 되므로 완전히
  오프라인·결정론적·1초 이내로 끝난다.
- **서브태스크 생성/검증(AI-D-*)**: 실제 로봇 상태 대신 "허용 행동/금지구역/로봇 상태"를
  나타내는 JSON fixture 몇 개를 손으로 만들어 사용한다.

## 영역별 Tier 분류

### Tier A — 순수 로직, 지금 바로 구현+테스트 완결 가능 (외부 라이브러리 불필요 또는 numpy/jsonschema만)

| ID | 무엇을 만드나 | 테스트 방법 |
|---|---|---|
| AI-D-01 | 제약(허용행동/금지구역/로봇상태) 기반 서브태스크 생성기 | 합성 zone/mission fixture로 "이 조건에서 이 행동만 나와야 한다" 검증 |
| AI-D-02 | JSON Schema + 규칙 검증기 | `jsonschema`로 구조 검증 + 커스텀 rule(구역경계·순서·자원조건) 검증, invalid/valid fixture 쌍으로 테스트 (khw_VZ `contracts/examples/*` 패턴과 동일) |
| AI-D-04 | 사전조건 유효성 기반 재생성 FSM | "경로 차단"과 "단순 관측 변화"를 다른 이벤트 타입으로 주입해 재생성 여부 분기 검증 |
| AI-R-01 | 가용 sensor/event 기반 FSM (평시/관찰/경보/복구) | 이벤트 스트림을 합성해 상태 전이 시퀀스 검증, 입력 0개일 때 "비활성화만 되고 나머지는 영향 없음" 검증 |
| AI-R-02 | 교체 가능한 위험 규칙 provider + 근거 충분도 | 저비용 규칙 provider 하나, "고급" provider 하나를 fake로 등록해 `CapabilitySelector`로 선택 검증 |
| AI-R-03 | 위험 Domain Object + Serializer/Transport provider 호출 | fake Serializer/Transport로 인코딩·전송 호출까지 검증(실 MQTT/Kafka 없이) |
| AI-R-04 | capability-aware FSM (관측·분석 수준 조정 요청) | `CapabilitySelector.select_with_degrade` 재사용, 위험도↑→고비용 요청, 위험도↓→축소 요청 검증 |
| AI-S-01 | IOU 기반 순수 Python/numpy 추적기 | 합성 bbox 시퀀스(동일 객체가 프레임마다 조금씩 이동)로 track id 유지 검증, 추적기 없을 때 프레임별 결과만 유지되는지 검증 |
| AI-S-02 | 시간·공간·외형 유사도 기반 선택적 연계 | 두 "카메라"의 합성 track + 가짜 임베딩 벡터(코사인 유사도)로 연계/미연계 케이스 검증 |
| AI-S-03 | 신뢰도 vs 근거충분도 분리 평가 | 신뢰도·근거개수 조합별로 상태(확정/미확정) 분기 검증 |
| AI-S-04 | 미확인 상태 관리 + 원본 이력 보존 | 저신뢰 분류 입력 시 UNCONFIRMED 유지, 추가 근거 주입 후에만 승격되는지 검증 |
| AI-S-05 | 가용 capability 필터 + 규칙 기반 점수 | 여러 fake 추가정보 provider를 등록하고 점수 상위만 선택 + 충분해지면 중단되는지 검증 |
| AI-B-03 | 공통 실행 제어 인터페이스 + fake 로컬 supervisor | in-process fake ControlProvider(스레드/더미 프로세스)로 시작/중지/재시작/상태조회·거부사유 반환 검증 |
| AI-B-05 | 독립 실행 lifecycle + 버전 배포/롤백 상태기계 | fake 배포 대상으로 PENDING→RUNNING→DEGRADED 등 전이, 선택기능 실패가 핵심기능 재시작을 유발하지 않음을 검증 |
| AI-B-08 | (기존 인터페이스에 실제 구현체 2개 추가) | 이미 정의된 `AIRuntimeProvider`에 "로컬 스텁"·"원격 스텁" 두 구현체를 붙이고 교체해도 호출부가 안 바뀌는 것을 테스트로 증명 |
| AI-B-09 | provider 정합성 자체 검증 하네스 | 임의의 Provider 구현을 넣으면 "필수 필드 선언·health probe 응답·장애 시 정상 격리"를 자동 점검하는 conformance 테스트 함수 작성 |
| AI-O-01/02/03/04 | in-memory ObservabilityProvider(로컬 sink) | 치명 오류는 즉시/개별로, 일반 metric은 집계 가능하게 남기고, "collector가 죽어도 로컬 기록은 남는다"를 fake sink 장애 주입으로 검증 |
| AI-C-02 | 좌표계 태그(로컬/전역) 부착 로직 | 보정 프로파일 유무에 따라 결과에 붙는 좌표계 태그가 달라지는지 검증 |
| AI-C-03 | 프레임 참조·타임스탬프·순서 규약 | 가짜 clock으로 시간 동기화 깨짐을 주입해도 로컬 순서는 유지되는지 검증 |
| AI-C-14 | 데이터 유형(업무/관측/미디어) 분류 로직 | 객체를 넣으면 어떤 경로(태그)로 가야 하는지 판정하는 순수 함수 + 표 기반 테스트 |
| AI-C-15 | DeploymentProfile 로더 (이미 데이터 구조는 있음) | robot/facility/river 3개 JSON 프로파일 fixture를 만들어 로딩만으로 활성 capability 셋이 바뀌는지 검증 — 핵심 코드에 도메인 분기 없음을 정적으로도 보장 |
| AI-C-04/06/07/08/09/12 | 기존 Protocol에 **fake 구현체** 추가 (in-memory pub/sub, in-memory encode/decode, 로컬 파일 프레임 reader, 즉시 응답 stub runtime) | "fake provider 교체 시 상위 코드 무변경"을 테스트로 실증 — 지금 있는 인터페이스만으로는 부족했던 "부분" 상태를 "완료"로 승격 |
| AI-E-04 | 가용 기능 탐색 + 즉시 해제 오케스트레이션 | 비용이 큰 fake provider(딜레이로 비용 흉내)를 등록, 근거 충족 즉시 중단되는지 검증 |
| AI-N-02 | 버전 기반 전체/변경분 구성 적용 | fake TransportProvider로 "엣지→말단" push를 흉내내 최초 전체 수신, 이후 변경분만 반영, 검증 실패 시 기존 유지 검증 |

### Tier B — 가벼운 CV 계산 필요 (opencv-python만, 실 카메라 불필요)

| ID | 무엇을 만드나 | 테스트 방법 |
|---|---|---|
| AI-E-02 | `cv2.calibrateCamera` 기반 캘리브레이션 provider | 알려진 K/dist로 합성한 가짜 체커보드 코너 → 복원된 K/dist가 원본과 오차범위 내인지 검증 (재투영 오차 RMS < 임계값) |
| AI-E-03 | 보정 프로파일 버전관리·검증·배포 로직 | E-02 출력(합성) 여러 버전 중 검증 통과분만 활성화, 실패 시 이전 버전 유지 검증 |
| AI-E-01 | 공통 인지 인터페이스 + 베이스라인 검출기(OpenCV HOG/Haar, 가벼움) | 정적 합성 이미지(또는 무작위 노이즈+도형)로 검출 호출이 되는지, 검출기가 없을 때도 "영상 좌표 결과"는 유지되는지 검증. 상위 인지 코드는 검출기 구현을 몰라야 함 — provider 2개(HOG, 더미)를 바꿔 끼우는 테스트로 이를 증명 |

### Tier C — 실제로 막혀 있음 (타 파트/실 인프라 필요)

| ID | 막힌 이유 |
|---|---|
| AI-C-06 실제 연동 | 실제 MQTT 브로커·서버 Kafka·양방향 Bridge는 BE/HW가 구축 (BE-T-01) — 지금은 fake TransportProvider로 계약만 검증 |
| AI-B-02/05 실제 배포 | 실제 컨테이너 런타임·K3s/Helm 오케스트레이터 필요 (HW-C-03) — 지금은 lifecycle 상태기계 로직만 fake로 검증 |
| AI-B-10 실제 검증 | 실제 말단 하드웨어에 경량 클라이언트만 설치되는지는 실물 배포 후 확인 가능 |
| AI-O-01 실제 관측 스택 | 실제 OpenTelemetry Collector/Prometheus 연동은 BE-S-02 이후 |
| AI-C-10 백엔드 연계 | "장치 최종 가용성"은 백엔드가 판정 — 백엔드 API 완성 전에는 fake로만 대체 |
| AI-C-01 데이터 사전 통일 | 의도적 보류 (§6-8: 전체 기능 구현 후 진행), 하드웨어와 무관 |
| AI-S-02 실제 다중카메라 | 실제 ReID 모델·다중 카메라 시간동기화 하드웨어 필요 — 로직/합성데이터 검증까지는 Tier A |

## 테스트 실행 명령

```bash
cd ai-framework
pip install -e ".[dev]" jsonschema      # 최초 1회, jsonschema만 추가 설치
pytest -q                                # 전체 스위트 (Tier A + Tier B, 합성 데이터라 전부 1초 내외)
pytest -q -k local_safety                # 특정 모듈만
pytest -q -v                             # 테스트 이름까지 보고 싶을 때
```

- 모든 Tier A/B 테스트는 외부 네트워크·GPU·카메라 없이 CI에서도 그대로 돌아간다.
- 결과 확인은 기존과 동일하게 `pytest` 종료 코드 + `N passed` 로만 판단한다. 숫자 허용오차가
  있는 테스트(캘리브레이션 재투영 오차, 위험도 임계값 등)는 각 테스트 docstring/주석에
  통과 기준값을 명시해 둔다 (예: `# RMS reprojection error must stay < 0.5px`).
- 별도 커버리지·통합 테스트 도구는 요청 전까지 추가하지 않는다.

## 권장 구현 순서 (다음 세션들)

1. Provider fake 구현체 보강 (AI-C-04/06/07/08/09/12, AI-B-08) — 나머지 모든 기능이 이걸
   딛고 서므로 최우선.
2. AI-D-01/02/04 (서브태스크 생성·검증·재생성) — 서로 강하게 연결되어 있어 한 묶음으로.
3. AI-S-01~05 (추적·연계·불확실성·미확인·추가정보) — 값 흐름이 순차적이라 순서대로.
4. AI-R-01~04 (위험 분석) — S-그룹의 근거충분도 개념을 재사용.
5. AI-B-03/05/09 + AI-O-01~04 (실행제어·배포·관측) — 운영 골격.
6. AI-E-01/02/03 + AI-E-04, AI-N-02 (인지·캘리브레이션·환경설정 적용) — OpenCV 의존 부분이라
   마지막.
7. Tier C는 각 항목이 실제로 필요로 하는 타 파트 산출물이 준비되는 대로 통합 테스트 추가.
