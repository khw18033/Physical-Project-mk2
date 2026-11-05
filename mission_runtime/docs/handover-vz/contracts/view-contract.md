# 운영 화면 계약 (View Contract) — 가시화 파트가 읽는 문서

대상: **이 저장소의 파이썬을 읽지 않고** 다른 운영 웹(React·Vue·순수 JS)이나 Unity
디지털 트윈 뷰어를 만들려는 팀.
계약 판: 서버가 내는 값 **2.1**(전역 좌표 블록이 더해진 판 — §3.5 · §4).
기계검사: `mission_runtime/schemas/view_snapshot.schema.json` 과 그 형제 파일들,
그리고 `mission_runtime/tests/test_view_contract.py`.

이 문서가 약속하는 것은 하나다 — **가시화 절반은 독립적으로 교체할 수 있다.** 서버는
뜻(상태·좌표·사유·식별자)만 내고, 색·배치·글꼴·아이콘·상호작용은 전부 뷰어의 것이다.
그래서 지금 쓰는 인라인 SVG 렌더러를 Unity WebGL 로 바꾸는 작업에 **서버 변경이 한 줄도
필요하지 않다**(§9·§10). 반대로 우리가 지키는 쪽의 약속은 "응답에 표현을 섞지 않는다"
이고, 그 약속은 문서가 아니라 시험이 지킨다(§11).

---

## 0. 이 계약이 선 요구사항

인용한 요구사항 ID 는 전부 뜻을 함께 적는다 — 바깥 팀이 우리 요구사항 정의서를 들고
있지 않다고 가정한다.

| ID | 요구사항의 뜻 | 이 계약에 남은 흔적 |
|---|---|---|
| **AI-O-06** 통합 운영 상태 뷰 제공 | 운영 화면이 소비하는 상태는 소스별 개별 조회가 아니라 하나의 통합 스냅샷으로 제공하고, 같은 사실이 여러 표시 영역에 나타나면 한 출처에서 파생시켜 값이 상충하지 않게 한다. 일부 소스가 응답하지 않아도 나머지 영역은 정상 제공하고 그 영역은 미수신 사실과 마지막 수신 시각을 명시한다. **한 번도 수신하지 않은 상태와 수신했으나 오래된 상태를 구분한다.** 상태 뷰는 **조회 전용**이어야 하며 이 경로로 실행 상태를 바꿀 수단을 제공해서는 안 된다. 제어가 필요한 기능은 상태 조회 계약과 분리된 별도 계약으로 제공한다 | §2(조회/제어 분리) · §5(신선도 3값) · §3.6(세는 값은 한 출처에서) |
| **AI-C-01** 공통 데이터 규약 | 성격이 다른 정보(원본 관측 · 생성된 근거 · 지속 객체 상태 · 미확정 가설 · capability 와 실행 프로파일)는 의미 수준에서 구분할 수 있어야 하고, 서로의 관계를 참조로 추적할 수 있어야 한다 | §6 각 끝점의 식별자와 참조 칸 |
| **AI-C-02** 좌표계 경계 | AI 가 내는 위치에는 어떤 기준 좌표계에서 나온 값인지 알 수 있는 정보가 포함되어야 한다. **전역 좌표 변환은 2026-11-03 경계 개정으로 AI 가 담당한다**(이전에는 백엔드 디지털 트윈이었다). 다만 그 변환은 현장 로컬↔전역 기준점(site datum)을 통해서만 하고, datum 은 **출처·생성 시점·버전·선언된 정확도를 가진 근거**다. 미측정 정확도는 0 오차가 아니며, 검증되지 않은 datum 으로 유도한 전역 값은 그 재료인 로컬 측정보다 높은 확신을 주장해서는 안 된다. **datum 이 없는 현장은 정상 상태**이고 그때는 전역 계층만 비활성이 된다. 로컬 값과 전역 값은 같은 칸에 담지 않는다 | §3.5(좌표는 전부 현장 로컬 · 전역은 선택 계층 · `at_global` 은 `at` 과 다른 칸) · §6.2~6.4 의 `geo` |
| **AI-C-16** 폐쇄망 배포 경계 | 폐쇄망 배포에서는 공개 인터넷으로 나가는 연결 없이 핵심 기능을 기동·복구할 수 있어야 한다. **어떤 실행 단위가 외부 연결을 요구하는지는 등록 정보로 드러나야 하고** 외부 서비스 provider 는 항상 선택 기능이며, 쓸 수 없으면 그 기능만 비활성화한다 | §3.9(배경 지도는 선택 계층) · §6.2 의 `map_tiles` |
| **AI-C-05** 핵심·선택 기능 및 의존성 격리 | 필수 조건이 없으면 그 기능만 비활성화하고, 선택 조건이 없어지면 축소 모드로 전환한다. 하나의 선택 구성요소 장애가 무관한 기능을 막아서는 안 된다 | §3.2(칸 없음 = 그 기능 없음) · §6.8(503 은 고장이 아니다) |
| **AI-C-15** 도메인·배포 프로파일 분리 | 적용 분야가 달라도 핵심 코드를 분기하지 않고 배포 프로파일로 구성한다. **Unity 를 포함한 특정 디지털 트윈 엔진·시뮬레이터·가시화 기술도 핵심 코드가 아니라 선택 가능한 소비자 또는 배포 구성으로 취급한다** | 이 문서 전체. 어떤 엔진도 의존성이 아니다 |
| **AI-C-19** AI 판단·권한·책임 경계 | AI 는 인지·해석·추가 정보 필요성 판단·capability 선택을 담당하고, 장치의 최종 가용성 판정·물리 명령 발급·실제 제어를 직접 소유하지 않는다. 전역 좌표와 최종 트윈 상태는 2026-11-03 개정으로 AI 소유가 됐지만 **백엔드와의 경계 재합의가 선행 조건**이고, 그 기록이 없는 현장에서는 전역 숫자가 이 계약으로 나가지 않는다. **가시화는 AI 가 제공한 판단 정보를 표현하고 사용자 입력을 전달할 뿐 AI 판단 로직을 중복 구현하지 않는다** | §7(역할) · §3.7(뷰어는 다시 판정하지 않는다) · §3.5 의 `boundary_agreement` |
| **AI-C-18** 구성요소 Capability 선언 규약 | 장치·AI 기능은 자신이 제공할 수 있는 capability 를 공통 의미 규약으로 선언하고, 상위 기능은 장치·모델 **이름이 아니라** 필요한 capability 로 탐색한다 | `served_kinds` · `announced_actions` · `bindings` |
| **AI-B-14** 서브태스크 산출의 capability 접지 | 생성된 단계를 그대로 실행 후보로 삼지 않고 현재 실행 가능한 capability 어휘로 접지·검증한다. 단계 사이 의존은 생성 주체가 적지 않고 **규칙으로 계산해** 순환이 구조적으로 생기지 않게 한다 | §6.7(`edges` 는 자료 흐름에서 유도된다) |
| **AI-B-15** 상황 기반 임무 추천 | 촉발 근거가 성립할 때만 후보를 제시하고, 막힌 후보도 **무엇이 없어서 막혔는지와 함께** 제시한다. AI 는 후보와 사유만 내고 임무 발령·실행을 소유하지 않는다 | §6.6 |

---

## 1. 무엇을 어디서 받는가

읽기는 모두 HTTP GET 이고 JSON 을 낸다. `Content-Type` 은
`application/json; charset=utf-8`, `Cache-Control` 은 `no-store` 다 — 상태 응답은
캐시하지 않는다(오래된 스냅샷을 현재로 그리는 사고를 막는다).

| 메서드 | 경로 | 내는 것 | 스키마 |
|---|---|---|---|
| GET | `/api/bootstrap` | 문자열표·역할·메인 맵 — 뷰어가 처음 한 번 받는 것 | `view_bootstrap.schema.json` |
| GET | `/api/scene` | 메인 맵(도메인 목록) | `view_scene.schema.json` |
| GET | `/api/domain?id=` | 도메인 하나의 장면(구역·장치·로봇 자리) | `view_domain.schema.json` |
| GET | `/api/zone?id=` | 구역 상세(이웃·전파·로봇 상세) | `view_zone.schema.json` |
| GET | `/api/robot?id=&zone=` | 로봇 한 대(자원·기능·존재·추천) | `view_robot.schema.json` |
| GET | `/api/recommend?robot=&zone=` | 임무 후보와 사유 | `view_recommendations.schema.json` |
| GET | `/api/subtasks?robot=&zone=&function=` | 한 목표의 실행 단계 그래프 | `view_subtask_graph.schema.json` |
| GET | `/api/explain?...` | 추론 근거(선택 기능 — 없으면 503) | 미확정 |
| GET | `/api/twin?zone=` | 그 구역에서 여러 장치의 관측을 합친 객체·구조·장치 기여 | 미확정 |
| GET | `/api/object?id=&about=` | 한 객체의 값이 왜 그렇게 나왔는지(장치별 영향) — 개발자 역할 전용 | 미확정 |
| GET | `/api/candidates` | 학습 후보 장부(사람 확인 / 자동 추론으로 분리) | 미확정 |
| GET | `/api/transit?robot=` | 구역 이동 상태 · 링크 품질 · 연결 끊긴 동안의 캐시 | 미확정 |
| GET | `/api/mission?robot=&function=&zones=` | 여러 구역에 걸친 임무의 구역별 계획(순서 포함) | 미확정 |
| GET | `/api/failure?subject=` | 실패한 단계의 원인 후보와 근거 — 개발자 역할 전용 | 미확정 |
| GET | `/api/spatial?zone=` | 선언·센서·사람이 잰 값을 합친 공간 상태 | 미확정 |
| GET | `/api/overlay?kind=&target=` | 운영자가 고친 값의 이력(누가 언제 왜) | 미확정 |
| GET | `/api/deployment` | 들이기·보정·학습·모델 교체의 한 스냅샷. 권한 없는 구역은 비는 대신 필요한 능력 이름을 적는다 | 미확정 |
| GET | `/api/calibration?device=` | 그 카메라의 선언·활성 프로파일·이력·거절 | 미확정 |
| GET | `/api/approval?version=` | 학습 결과를 적용할지 판단할 재료(AI-L-06) | 미확정 |
| POST | `/api/command` · `/api/correction` · `/api/placement` · `/api/survey` · `/api/detection` · `/api/pose` · `/api/join` · `/api/join-step` · `/api/camera-info` · `/api/training` · `/api/model` | **조회가 아니다** — §2 | 이 문서 범위 밖 |

모든 GET 은 `role` 과 `locale` 질의 인자를 받는다. 생략하면 `role=admin`,
`locale=ko` 다. 모르는 값을 주면 400 `unknown_role`·`unknown_locale` 이고, **모르는
인자는 조용히 무시된다** — 뷰어가 자기 추적용 인자(`renderer=unity-webgl` 같은 것)를
붙여도 된다.

영상 픽셀은 이 계약으로 오지 않는다. 업무·상태 경로에 픽셀을 싣지 않고 별도 미디어
경로를 쓴다(요구사항 AI-C-08: "영상 픽셀은 대용량이므로 업무 데이터나 관측 경로에
실어 보내지 않고 별도 미디어 경로를 사용해야 한다"). 뷰어가 영상을 띄워야 하면 그
경로를 따로 붙이고, 이 계약에서는 `frame_ref` 같은 **참조**만 받는다.

---

## 2. 조회와 제어는 다른 계약이다

이것이 이 경계의 가장 강한 규칙이고, 문서의 약속이 아니라 메서드 차원의 성질이다.

- **조회(GET)로는 아무것도 바뀌지 않는다.** 서버에 상태를 바꾸는 GET 은 없다.
- **조회 경로에 POST 를 보내면 본문을 읽기도 전에 405 `read_only_path` 로 끊긴다.**
  뷰어가 실수로 상태 경로에 쓰기를 보내도 그것이 실행에 닿을 길이 없다.
- 바꾸는 것은 **목록에 적힌 경로**뿐이다: `POST /api/command`(물리 명령 발급),
  `POST /api/correction`(융합 결과·추론 단서 수정 = 사람이 확인한 학습 후보 등록),
  `POST /api/placement`(고정 장치 자리 수정), `POST /api/survey`(사람이 잰 공간 실측값),
  `POST /api/detection`(장치가 본 것 1건), `POST /api/pose`(장치가 알리는 자기 자세),
  `POST /api/join`·`/api/join-step`(장치 조인 선언과 남은 할 일),
  `POST /api/camera-info`(카메라 정보 선언 + 보정 실행),
  `POST /api/training`(학습·검증·승인요청), `POST /api/model`(승인·적용·넓히기·되돌리기).
  이 경로들에 GET 을 보내면 404 다. 읽는 쪽은 **다른 이름**을 쓴다 —
  `/api/deployment`·`/api/calibration`·`/api/approval` — 같은 이름으로 읽고 쓰면 위의
  405 보장이 그 경로에서만 사라진다.

  뒤의 셋이 "제어" 목록에 있는 이유는 장비를 움직이기 때문이 아니라 **서버의 상태를
  바꾸기 때문**이다. 조회로 들어온 값이 융합된 그림을 바꿀 수 있으면 "화면을 열었더니
  지도가 달라졌다"가 가능해지고, 그러면 무엇이 관측이고 무엇이 조회의 부작용인지
  구분할 수 없다.

왜 이렇게까지 가르는가. 관찰이 실행에 개입할 수 있으면 "화면을 보다가 장비가 움직였다"
가 가능해지고, 그 사고는 로그에서 조회와 구분되지 않는다. 그래서 AI-O-06 은 상태 뷰에
"실행 상태를 변경하는 수단을 제공해서는 안 된다"고 못 박았고, 우리는 그것을 경로
목록과 405 로 구현했다. 뷰어 쪽에서도 같은 선을 지키기를 권한다 — 상태를 읽는 모듈과
명령을 보내는 모듈을 같은 코드에 섞지 않는 것이 좋다.

물리 명령 자체의 의미(수락·거부·실행 lifecycle·동일 명령 재전달 금지)는 이 문서가
아니라 `specs/physical-command-interface.md` 가 소유한다. 뷰어는 명령을 **발급하지
않고** 사용자의 뜻을 전달할 뿐이며, 명령 식별자(`command_id`)는 백엔드가 발급한다
(AI-C-19).

---

## 3. 공통 규칙 아홉 가지

### 3.1 서버는 뜻만 낸다

응답에는 색, 픽셀, 글꼴, 도형, 아이콘 이름, 배치, 애니메이션, 머티리얼이 **없다.**
`state: "limited"` 는 상태이고 노란색이 아니다. `role: "uav"` 는 역할 토큰이고 삼각형이
아니다. `kind: "fixed_camera"` 는 장치 종류이고 아이콘 파일 이름이 아니다.

이 규칙이 뷰어 교체 가능성의 전부다. 색 하나가 응답에 들어오는 순간 그 색을 쓰지 않는
뷰어(예: Unity 머티리얼)는 계약의 일부를 버려야 하고, 버린 칸은 다음 변경에서 조용히
어긋난다. 우리 쪽 시험
(`test_no_payload_carries_a_presentation_decision`)이 모든 응답의 칸 이름을 낱말 단위로
훑어 `color`·`fill`·`font`·`icon`·`shape`·`opacity` 같은 낱말이 나타나면 실패한다.

예외는 두 칸뿐이고 둘 다 **표현이 아니라 글**이다: `strings`(지역화 문자열표, §8)와
`facts_vocabulary`(사실 토큰의 뜻풀이). 둘에는 색·배치·글꼴이 없다.

### 3.2 칸 없음 · `null` · `0` 은 서로 다른 뜻이다

| 모양 | 뜻 | 뷰어가 할 일 |
|---|---|---|
| 칸이 아예 없다 | 그런 사실이 없다 / 그 기능이 이 배치에 없다 | 그 자리를 **비워 두고 비었다는 사실을 적는다**. 0 으로 채우지 않는다 |
| `null` | 아는데 값이 없다(선언되지 않았다 · 한 번도 받지 않았다) | 칸 없음과 **같게** 다루면 된다 |
| `0` | 재어 보니 0 이다 | 값으로 그린다 |

구체적으로:

- `last_seen_age_s: null` = 공지를 **한 번도** 받지 않았다. 0 이 아니다(0 은 "방금
  받았다"). 둘을 같게 그리면 죽은 장치가 가장 싱싱한 장치로 보인다.
- `resources.compute_units` 칸 없음 = **미측정**. 0 으로 채우면 "자원 없음"으로 보인다.
- `infrastructure[].calibration` 칸 없음 = 유효한 보정 프로파일이 없다. 그 사실이 임무
  추천의 촉발 근거이므로 지어내 채우지 않는다.
- `robot_detail.command_vocabulary` 칸 없음 = 이 배치에 **명령 경로가 없다**. 권한
  부족과 다르다 — 둘을 같은 문구로 적으면 운영자가 권한을 요청하다가 경로가 없다는
  사실을 끝까지 모른다. 경로 유무는 `bootstrap.commanding_available` 이 말한다.
- `missing_required` · `missing_optional` 칸 없음 = 결손이 없다(빈 목록과 같다).

`null` 과 "칸 없음"을 섞어 쓰는 이유를 솔직히 적는다: 파트 간 와이어 계약
(`schemas/ai/`)은 "모르는 값에 `null` 을 싣지 않고 칸을 뺀다"는 더 엄한 규칙을 쓰지만,
이 화면 계약은 **둘 다 나온다.** 그래서 뷰어는 두 모양을 같게 다뤄야 하고, 그 요구를
숨기지 않고 여기 적는다.

### 3.3 모르는 칸은 양쪽이 통과시킨다

- **서버 → 뷰어**: 우리가 칸을 더해도 뷰어가 깨지지 않아야 한다. 스키마는 모든 객체에
  `additionalProperties: true` 를 두어 모르는 칸을 **허용한다.** 뷰어는 모르는 칸을
  무시하고 나머지를 그려야 하며, 모르는 칸이 있다고 응답을 버려서는 안 된다.
- **뷰어 → 서버**: 제어 POST 본문에 뷰어가 자기 칸(`"renderer": "unity-webgl"` 등)을
  덧붙여도 서버가 거절하지 않는다. 서버는 자기가 아는 칸만 읽는다.

이 두 방향이 모두 성립해야 두 팀이 서로의 배포 주기에 묶이지 않는다. 한 방향만
성립하면 결국 한쪽이 다른 쪽의 판올림을 기다리게 되고, 기다림이 경계를 썩게 한다.

### 3.4 상태·사유는 통제 어휘 토큰이고 표시 문구가 아니다

`state`, `presence`, `reason`, `source`, `error`, `at_origin` 같은 칸의 값은 기계가
읽는 토큰(`operable`, `no_triggering_evidence`, `read_only_path` …)이다. 사람에게 보일
문구는 뷰어가 §8 의 문자열표에서 만든다. 서버가 문장을 내면 그 문장의 언어·말투·길이가
서버의 결정이 되어 버리고, 뷰어는 그것을 바꿀 수 없다.

닫힌 어휘(스키마 `enum`)와 열린 어휘를 구분해 둔다.

| 칸 | 어휘 | 값 |
|---|---|---|
| 구역·도메인 `state` | **닫힘** | `operable` · `limited` · `idle` · `no_robot` |
| capability `state` | **닫힘** | `ACTIVE` · `DEGRADED` · `DISABLED` |
| `presence` | **닫힘** | `discovered` · `declared` · `unexpected` |
| `at_origin` | **닫힘** | `declared` · `operator_edit` |
| `bindings[].source` | **닫힘** | `registry`(로봇에서 돈다) · `executor`(구역이 공급한다) |
| `runs_on[]` | **닫힘** | `robot` · `zone` |
| 추천 `reason` · 계획 `reason` · `error` | **열림** | 토큰이 늘 수 있다 |

닫힌 어휘에 값이 하나 더 생기는 것은 **계약 변경**이고, 그때 이 문서와 스키마와 판
번호가 함께 바뀐다. 열린 어휘는 늘 수 있으니 뷰어는 모르는 토큰을 받으면 토큰 자체를
그대로 보여 주면 된다(빈칸으로 두지 않는다).

### 3.5 좌표는 전부 현장 로컬이고, 전역은 **선택 계층**이다

모든 `at`·`rect`·`space`·`wifi.at` 은 **현장 로컬 좌표**이고 전역 좌표가 아니다.
단위는 그 장면의 `space.unit` 이 말한다 — 지금 배포에서 `meter`(구역·도메인 내부)와
`index`(메인 맵의 무차원 격자)가 함께 나온다. 두 도메인이 같은 화면에 섞여 있어도 글자
크기나 눈금을 한쪽 단위로 고정해서는 안 된다(SVG 렌더러가
`scaleOf(space) = max(width, height)/100` 로 모든 치수를 정규화하는 이유가 이것이다).

전역 좌표 변환의 주인은 2026-11-03 경계 개정으로 백엔드 디지털 트윈에서 **AI** 로
옮겼다(AI-C-02). 소유권만 옮기면 개정 전 규칙이 막고 있던 실패("같은 사실에
authoritative 주인이 둘")가 없어지지 않고 자리만 바뀌므로, 요구사항 자체가 백엔드
(BE-C-04)·디지털 트윈(DT-03)과의 **경계 재합의를 선행 조건**으로 둔다(AI-C-19). 그래서
전역 좌표 **숫자**는 그 재합의가 **기록된 현장에서만** 이 계약으로 온다.

그 판정은 우리 코드의 상수가 아니라 **현장 선언**이다. 상수로 두면 둘 중 하나가 된다 —
거짓으로 두어 재합의가 끝난 현장에서도 숫자를 막거나, 참으로 올려 아직 합의하지 않은
현장에서도 내보내거나. 사실은 현장마다 다르고(재합의 기록은 그 현장의 트윈 소비자와
함께 생긴다) 그래서 조건도 현장마다 답한다. 네 조건이 **모두** 성립해야 숫자가 나온다.

| 조건 | 어디서 보는가 | 없으면 사유 토큰 |
|---|---|---|
| 그 현장에 기준점 선언이 있다 | `geo.datum` | `no_datum` |
| 그 기준점이 현장 실측으로 확인됐다 | `geo.datum.verified` | `datum_unverified` |
| 그 기준점의 정확도가 **선언돼 있다** | `geo.datum.accuracy_m` | `accuracy_unmeasured` |
| AI↔백엔드 경계 재합의가 기록돼 있다 | `geo.boundary_agreement` | `boundary_not_reagreed` |

하나라도 없으면 `geo.coordinates_in_view_contract` 가 거짓이고
`geo.coordinates_withheld_reason` 이 **무엇이 없어서**인지 말한다. "안 온다" 만 말하면
그 현장이 다음에 무엇을 해야 하는지 알 수 없기 때문이다. 선언되지 않은 현장이
**기본값**이고 그것은 오류가 아니다 — 지금 배포의 실제 현장 둘(`college`·`river`)이 그
상태이고, 그 현장에서 지도·구역·로봇은 로컬 좌표로 그대로 돈다.

정확도를 조건에 넣은 이유는 AI-C-02 의 한 문장이다 — **미측정 정확도는 0 오차가
아니다.** 확신을 모르는 전역 숫자를 공개 계약에 실으면 받는 쪽은 그 값을 대개
"정확하다" 로 읽는다.

`geo` 블록은 이렇게 생겼다. **datum 이 없는 현장이 정상 배치**이므로(예시 도메인
`facility`·`defense`) 그때는 사유만 온다.

```json
{ "layer": "disabled", "reason": "no_datum" }
```

기준점이 선언되어 있지만 아직 실측으로 확인되지 않은 현장(지금의 `college`·`river`):

```json
{
  "layer": "disabled",
  "reason": "datum_unverified",
  "coordinates_in_view_contract": false,
  "coordinates_withheld_reason": "datum_unverified",
  "datum": {
    "datum_id": "hanbat-n4-site-2026-11-03",
    "version": "2026-11-03.1",
    "created_at": "2026-11-03T10:00:00+09:00",
    "verified": false,
    "crs": "EPSG:4326",
    "accuracy_m": null,
    "accuracy_state": "unmeasured",
    "accuracy_basis": "unmeasured",
    "source": { "kind": "public_map", "name": "...", "url": "https://...", "retrieved_at": "2026-11-03", "license": "ODbL 1.0" },
    "local_frame": { "anchor": "space_origin", "anchor_basis": "assumed",
                     "x_bearing_deg": 90.0, "y_bearing_deg": 180.0,
                     "bearing_basis": "assumed", "level_stacked": true }
  }
}
```

| 칸 | 뜻 |
|---|---|
| `layer` | `active` \| `disabled`. 이 현장에서 전역 값을 유도할 수 있는가. capability 의 `ACTIVE`/`DEGRADED`/`DISABLED` 와는 **다른 축**이다 |
| `reason` | 비활성 사유 토큰: `no_datum`(선언이 없다) · `datum_unverified`(있지만 미검증). `null` 은 사유가 없다는 뜻이고 칸 없음과 다르다 |
| `datum.verified` | 현장 실측으로 확인됐는가. **거짓이면 그 datum 에서 나온 값은 검증된 값으로 보여서는 안 된다** |
| `datum.accuracy_m` | **선언된** 정확도(미터). `null` 은 미측정이고 **0 이 아니다** — 미측정을 0 으로 적으면 공개 지도에서 받아 적은 기준점으로 만든 전역 값이 사람이 줄자로 잰 로컬 값을 이긴다. 서버는 `0` 선언 자체를 거절한다 |
| `datum.accuracy_state` | `unmeasured` \| `declared`. 같은 사실을 토큰으로 한 번 더 말한다 — 뷰어가 `null` 을 0 으로 접지 않도록 |
| `datum.source` | 어디서 가져온 기준점인가(출처·URL·받은 날짜·라이선스). **출처 없는 datum 은 공리이고 AI-C-02 가 금지한다** |
| `datum.local_frame` | 로컬 평면이 그 기준점과 어떤 관계인가. `anchor` 는 로컬 (0,0) 의 자리, `*_bearing_deg` 는 로컬 축의 방위(진북 기준 시계방향 도), `*_basis` 는 그 값이 실측인가 가정인가. `level_stacked` 가 참이면 여러 층을 `levels[].y_offset` 으로 +y 에 쌓은 장면이므로 평면 y 는 `y - y_offset` 이다 |
| `coordinates_in_view_contract` | 이 계약으로 전역 **숫자**(`at_global`)가 오는가. 위 네 조건의 논리곱이다 |
| `coordinates_withheld_reason` | 오지 않는 사유 토큰(위 표). 숫자가 올 때는 이 칸이 **없다** |
| `boundary_agreement` | 경계 재합의의 **기록**. 선언된 현장에서만 온다 |

뷰어는 이 상태를 **표현**할 뿐 전역 값을 스스로 유도해서는 안 된다(AI-C-19: 가시화는
AI 판단 로직을 중복 구현하지 않는다). 특히 `datum.reference_point` 를 받아 직접
변환하는 길은 열어 두지 않았다 — 같은 변환이 두 곳에 있으면 두 화면이 서로 다른 전역
값을 말한다. `layer: "disabled"` 는 고장이 아니고, 그 도메인의 지도·구역·로봇은 로컬
좌표로 **그대로** 나온다.

#### 재합의가 기록된 현장 — `boundary_agreement` 와 `at_global`

재합의가 기록된 현장에서는 `geo` 에 그 기록이 함께 온다. 이것은 **주장이 아니라
기록**이다: 누가·언제·어느 문서로 합의했고 어떤 기존 기록을 대체하는지가 전부 들어
있어야 하고, 하나라도 빠진 선언은 서버가 읽는 자리에서 거절한다.

```json
{
  "layer": "active",
  "reason": null,
  "coordinates_in_view_contract": true,
  "datum": { "datum_id": "...", "verified": true, "accuracy_m": 0.8,
             "accuracy_state": "declared", "...": "..." },
  "boundary_agreement": {
    "subject": "global_coordinate_ownership",
    "agreed_by": ["ai", "backend", "visualisation"],
    "agreed_at": "2026-12-01",
    "document": { "name": "경계 재합의 회의록", "url": "https://...", "section": "..." },
    "supersedes": ["BE-C-04", "DT-03"],
    "example": false
  }
}
```

| 칸 | 뜻 |
|---|---|
| `subject` | 무엇에 대한 합의인가. 지금 이 문을 여는 값은 `global_coordinate_ownership` 하나다 |
| `agreed_by[]` | 합의한 파트 토큰. `ai` 와 `backend` 가 **반드시** 들어 있다 — AI-C-19 가 선행 조건으로 적은 것이 그 둘의 경계이고, 한쪽만 적힌 것은 합의가 아니라 통보다 |
| `agreed_at` · `document` | 언제, 어디에 적혀 있는가. 아무도 읽을 수 없는 합의는 기록이 아니다 |
| `supersedes[]` | 이 합의가 대체한 기록의 ID(`BE-C-04` · `DT-03`). 비어 있으면 소유권이 어디서 왔는지 역추적이 끊긴다 |
| `example` | 참이면 **예시 선언**이고 실제 합의 기록이 아니다. 예시 현장(`site.example`)은 예시 합의만, 실제 현장은 실제 합의만 가질 수 있고 서버가 그 짝을 검사한다. 배포된 예시 프로파일의 `logistics` 도메인이 그 예시다 |

그 현장에서는 **자리 칸 옆에** 전역 블록이 하나 더 붙는다. 로컬 값과 전역 값을 같은
칸에 담지 않는다는 규칙(AI-C-02 의 마지막 문장)이 이 모양을 정했다 — 한 칸에 담으면
받는 쪽이 단위와 기준을 추측하고, 추측은 반드시 틀린다.

```json
{
  "id": "wh-inbound-cam", "kind": "fixed_camera",
  "at": { "x": 6, "y": 6 },
  "at_origin": "declared",
  "at_global": {
    "lat": 35.9999459, "lon": 127.0000665, "crs": "EPSG:4326",
    "verified": true, "accuracy_m": 0.8, "accuracy_state": "declared",
    "datum_id": "example-logistics-site-2026-11-03", "datum_version": "2026-11-03.1",
    "derived_from": { "kind": "site_local", "domain_id": "logistics",
                      "level_id": "wh-ground", "unit": "meter" }
  }
}
```

| 칸 | 뜻 |
|---|---|
| `lat` · `lon` · `crs` | 전역 값과 그 좌표계. 숫자만 주고 평면을 말하지 않는 칸은 이 계약에 없다 |
| `verified` · `accuracy_m` · `accuracy_state` | **재료인 datum 의** 검증 상태와 선언된 정확도다. 유도가 정확도를 좋게 만드는 일은 없으므로 이 값은 datum 의 값 그대로다 — 전역 숫자가 그 재료인 로컬 측정보다 정확한 척해서는 안 된다 |
| `datum_id` · `datum_version` | 어느 기준점에서 유도했는가. 같은 id 의 `geo.datum` 이 그 출처를 말한다 |
| `derived_from` | 재료가 살던 프레임(`site_local` · 도메인 · 층 · 단위). **숫자는 들어가지 않는다** — 그것은 형제 칸 `at` 의 것이다 |

읽는 쪽이 지켜야 하는 것 세 가지:

- **칸이 없는 것이 보통이다.** 대부분의 현장에는 `at_global` 이 없고, 없는 것을 고장으로
  그리면 멀쩡한 배치가 장애로 읽힌다(§3.2 · §6.8).
- **두 값을 섞지 않는다.** 로컬 좌표로 그리던 화면은 그대로 로컬 좌표로 그린다. 배경
  타일이나 외부 지도에 얹을 때만 `at_global` 을 쓴다.
- **정확도를 함께 읽는다.** `accuracy_m` 이 2 m 인 점을 1 m 격자에 딱 맞춰 그리면 없는
  정밀도를 화면이 만들어 낸다.

### 3.6 같은 사실은 한 곳에서 나온다

AI-O-06 은 "같은 사실이 여러 표시 영역에 나타나는 경우 한 출처에서 파생시켜 값이
상충하지 않아야 한다"고 요구한다. 그래서:

- 세면 나오는 값 중 **그 응답에 목록이 없는 것만** 서버가 센다.
  `domain_summary.zone_count`·`discovered_count` 는 메인 맵에 구역 목록이 실리지 않으니
  서버가 센다. 반대로 구역 상세의 로봇 수는 `robots[]` 를 뷰어가 세면 된다.
- 구역 상세의 `robots[]` 원소는 `GET /api/robot` 과 **같은 모양**이다(자리 칸만 더
  붙는다). 같은 사실을 두 모양으로 내면 뷰어가 두 갈래 코드를 들고 가야 한다.
- `usable_functions` 는 구역 요약과 로봇 상세가 **같은 기준**으로 센 값이다. 특히 구역
  요약은 아직 탐지되지 않은 로봇(`presence: "declared"`)의 기능을 넣지 않는다 — 없는
  로봇의 기능을 쓸 수 있다고 적으면 운영자가 할 수 없는 일을 시킨다.

### 3.7 뷰어는 판정을 다시 하지 않는다

서버는 판정을 하지 않고 다른 모듈이 이미 낸 값을 모아 낸다. 뷰어도 같아야 한다
(AI-C-19: "가시화는 AI 판단·학습 정보를 표현하고 사용자 입력을 전달할 뿐 AI 판단 로직을
중복 구현하지 않는다"). 구체적으로 뷰어가 **다시 계산하면 안 되는** 것:

- 기능 가용성(`ACTIVE`/`DEGRADED`/`DISABLED`) — `functions[].state` 를 그대로 쓴다.
  특히 `DEGRADED` 는 고장이 아니라 **정상 축소**다(선택 capability 결손은 `DEGRADED`
  까지만 내려가고 필수 결손만 `DISABLED` 가 된다 — AI-C-05). 뷰어가 이것을 오류처럼
  그리면 운영자가 멀쩡한 구성을 장애로 읽는다.
- 장치의 최종 가용성 — AI 도 판정하지 않고 백엔드가 통합 판정한다. 이 계약의
  `presence`·`last_seen_age_s` 는 **탐지 사실**이고 최종 가용성 판정이 아니다.
- 추천 순서 — 서버가 `(추천 여부, priority, mission_kind)` 로 결정적으로 정렬한다.
  뷰어가 다시 정렬하면 "같은 입력에 같은 순서"라는 보장이 깨진다.
- 서브태스크 간선 — 규칙이 자료 흐름에서 계산한 결과이고 뷰어가 추측할 것이 아니다.

### 3.8 같은 질문에 같은 답이 온다

`/api/subtasks` 의 분해는 시계도 난수도 생성 모델도 쓰지 않는다. 같은 (로봇, 구역,
목표) 에 **같은 그래프**가 나온다. 뷰어가 두 번 물어 다른 답을 받는 일이 없어야 화면이
깜빡이지 않고, 운영자가 본 화면을 그대로 재현할 수 있다.

### 3.9 배경 지도는 선택 계층이고 기본값은 "타일 없음" 이다

메인 맵의 배경 타일은 `GET /api/scene` 의 `map_tiles` 가 선언으로 말한다. 기본값은
타일 없음이다 — 공개 타일 서버(OSM 등)를 기본으로 두면 폐쇄망 배치에서 메인 화면이
깨지고, 배치 전 검증에도 걸린다(AI-C-16: "어떤 실행 단위가 외부 연결을 요구하는지는
등록 정보로 드러나야 하며 폐쇄망 프로파일에서는 배치 전에 이를 검증할 수 있어야 한다").
외부 연결을 요구하는 레이어는 선언에 **있을 수는 있어도 켜져 있지 않다**: 그 사실이
`requires_external_connection` 과 `external_hosts` 로 드러나고, 폐쇄망 선언에서 그런
레이어를 켜면 서버가 선언 자체를 거절한다.

타일을 전역 좌표에 맞춰 놓는 일은 site datum 이 검증된 현장에서만 가능하다(§3.5). 그
전까지 배경 타일은 꺼져 있고 지도는 지금처럼 로컬 좌표 평면으로 그려진다.

### 3.10 바탕 그림은 **자리마다** 걸리고, 자리마다 프레임이 다르다

타일과 별개로 **한 장짜리 바탕 그림**(캠퍼스 조감도 · 층 도면 · 방 도면)을 걸 수 있다.
선언은 `GET /api/background` 가 내고 그림 **바이트**는 `GET /api/media?kind=map` 이
따로 낸다 — 픽셀은 상태 계약으로 나가지 않는다(AI-C-08).

```
GET /api/background                                   → 현장 그림
GET /api/background?domain=<d>                        → 그 도메인 그림
GET /api/background?domain=<d>&level=<l>              → 그 층 도면
GET /api/background?domain=<d>&level=<l>&zone=<z>     → 그 구역 도면
```

**좁은 자리가 이긴다**(구역 → 층 → 도메인 → 현장). 방 하나를 보려던 화면에 층 도면을
깔면 그 화면은 틀린 것을 보여 주고, 층 도면이 있는데 캠퍼스 조감도를 깔면 로봇이 건물
지붕 위에 선다.

여기서 **반드시 지켜야 하는 것**: 자리마다 앵커의 **기준계가 다르다.** 현장 그림의
앵커는 현장 로컬 좌표(원점 = site datum)이고, 층·구역 도면의 앵커는 그 구역의 로컬
좌표다. 같은 그림을 두 자리에 깔면 둘 중 한 화면의 자리가 **조용히** 틀어진다 — 핀은
여전히 "건물 위" 에 보이기 때문에 틀어진 줄 아무도 모른다(AI-C-02).

응답의 `scale`·`offset` 은 `px = local * scale + offset` 의 계수다. 뷰어가 앵커 두
점에서 같은 계산을 다시 하면 두 화면이 반올림 한 자리에서 갈리므로 **계산은 서버에서
한 번만** 한다.

그림이 없는 자리는 `declared: false` 이고 그것이 **기본값**이다. 그때 지도는 로컬 좌표
도면으로 그려지고 아무것도 깨지지 않는다(AI-C-05).

---

## 4. 판 교섭 (contract version)

- 판 형식은 `<major>.<minor>` 다. **major** 가 오르면 기존 칸의 뜻이 바뀌었다는 말이고
  뷰어는 해석을 거부해야 한다. **minor** 는 칸이 늘기만 한 변화라 옛 뷰어가 계속 돈다.
- 서버가 내는 현재 판은 **2.1** 이다.
- 판은 **문서에만 있지 않고 응답으로 실려 온다.** 지금 서비스는 모든 응답의 HTTP
  `Server` 머리에 `FMS/2.1` 으로 낸다(`Server: FMS/2.1 Python/3.x`). 뷰어는
  `FMS/(\d+\.\d+)` 로 뽑아 읽고, major 가 자기가 아는 값과 다르면 화면을 그리지 않고
  그 사실을 운영자에게 말해야 한다.
- 공표한 스키마의 `x-view-contract-version` 과 서버가 내는 판은 **같아야** 하고, 그
  동일성은 시험(`test_the_contract_version_is_served_not_only_documented`)이 묶는다.
  한쪽만 올리면 거기서 깨진다.
- HTTP 가 아닌 전송(예: Unity 가 WebSocket 으로 같은 본문을 받는 구성)을 쓰는 뷰어를
  위해 **본문 칸** `view_contract_version` 을 예약해 두었다. 지금 서비스는 내지 않고,
  내기 시작하면 머리의 값과 같아야 한다(§12 에 미결 항목으로 적었다).

판을 올리는 기준:

| 변경 | 판 |
|---|---|
| 칸을 더한다 | minor |
| 열린 어휘에 토큰을 더한다 | minor |
| 닫힌 어휘(`enum`)에 값을 더한다 | **major** — 뷰어가 모르는 상태를 그릴 수 없기 때문이다 |
| 칸의 뜻·타입·단위를 바꾼다 | **major** |
| 칸을 없앤다 | **major** |

### 2.1 에서 더해진 것 — 전역 좌표 블록

§3.5 의 `at_global` · `geo.boundary_agreement` · `geo.coordinates_withheld_reason` 은
**칸이 늘기만 한** 변화라 위 표대로 minor 이고, 그래서 판이 2.0 → 2.1 로 올랐다.
올린 자리는 두 곳이고 같은 변경에서 함께 올랐다 — 공표 스키마의
`x-view-contract-version` 과 서버가 `Server` 머리에 내는 값이다(한쪽만 올리면 §4 의
동일성 시험에서 깨진다).

2.0 만 아는 뷰어에게 이 칸들은 **모르는 칸**으로 오고, 모르는 칸은 통과시키면
된다(§3.3). `FMS/2.1` 은 그 칸이 **있을 수 있다**는 뜻이지 **있다**는 뜻이 아니다 —
칸이 실제로 나오는가는 현장의 datum 과 경계 재합의 선언이 정한다(§3.5).

---

## 5. 신선도 — 미수신 · 노후 · 현재는 세 가지다

AI-O-06: "한 번도 수신하지 않은 상태와 수신했으나 오래된 상태를 구분해야 한다."

지금 계약이 내는 재료는 두 칸이다.

| 칸 | 뜻 |
|---|---|
| `last_seen_age_s` | 마지막 공지로부터 지난 시간(초). `null`(또는 칸 없음)이면 **한 번도 받지 않았다** |
| `presence` | `declared` = 공지가 한 번도 없었다 · `discovered` = 공지가 왔고 선언에도 있다 · `unexpected` = 공지는 왔는데 그 구역 선언에 없다 |

뷰어가 구현할 규칙:

```text
freshness(age) =
    age 가 null 또는 칸 없음        -> never   (한 번도 수신하지 않음)
    age  >  stale_after_s           -> stale   (수신했으나 오래됨)
    age <=  stale_after_s           -> fresh   (현재)
```

세 상태는 **서로 다르게** 그려야 하고, 특히 `never` 를 0 초로 그려서는 안 된다. 뷰어가
각 상태에서 지켜야 할 것:

| 상태 | 뷰어가 반드시 하는 것 | 하면 안 되는 것 |
|---|---|---|
| `never` | "한 번도 수신하지 않음"을 명시한다. 선언된 자리는 그려도 되지만 **선언된 자리임을 함께 밝힌다**(`at_origin`) | 나이를 0 으로 적기 · 마지막 수신 시각을 지어내기 · 목록에서 빼기(빼면 선언된 장비가 사라진다) |
| `stale` | 마지막 수신으로부터 지난 시간을 적는다. 그 장치가 내는 값은 **그때의 값**임을 밝힌다 | 현재 값처럼 그리기 |
| `fresh` | 값을 그대로 그린다 | — |

`stale_after_s` 경계는 **배포가 정하는 값**이고 이 계약은 숫자만 낸다. 왜 서버가 정하지
않는가: 5 Hz 로 공지하는 말단과 분 단위로 공지하는 고정 카메라에 같은 경계를 쓰면 한쪽은
항상 노후로 보이고 다른 쪽은 끊긴 뒤에도 한참 싱싱해 보인다. 경계를 서버가 못 박으면 그
오판이 모든 뷰어에 박힌다. 다만 **경계를 계약으로 받아야 한다**는 요구는 정당하므로
`bootstrap` 에 `freshness` 묶음을 더하는 것을 미결 항목으로 적어 두었다(§12).

선택 칸 `freshness`(`never`/`stale`/`fresh`)를 스키마에 열어 두었다. 서버가 직접 환산해
보내기 시작하면 그 값이 위 규칙과 어긋나서는 안 된다.

### 소스별로 가른다

"일부 소스가 응답하지 않더라도 나머지 영역은 정상 제공"(AI-O-06)은 이 계약에서 **칸
단위의 결손**으로 나타난다. 로봇 하나의 공지가 끊겨도 같은 구역의 다른 로봇·고정
장치·전파 모델은 그대로 온다. 뷰어는 결손을 **그 칸에만** 표시하고 화면 전체를 오류로
덮지 않아야 한다. 선택 기능이 아예 없는 배치(`evidence_available: false`,
`commanding_available: false`)도 정상 배치이고 장애가 아니다(AI-C-05).

---

## 6. 끝점별 계약

여기서는 뜻과 선택 여부를 적는다. 정확한 타입·필수 칸 목록은 스키마가 정본이다.
모든 객체는 **모르는 칸을 허용**하므로 아래 표에 없는 칸이 와도 뷰어는 무시하면 된다.

### 6.1 `GET /api/bootstrap?role=&locale=`

뷰어가 처음 한 번 받는 것. 문자열표·역할·메인 맵을 한 번에 주어 화면이 뜨기 전에 여러
번 묻지 않게 한다.

| 칸 | 뜻 |
|---|---|
| `locale` · `locales[]` | 지금 고른 언어와 서버가 가진 언어 전부 |
| `strings` | 그 언어의 문자열표(§8). 키는 `구역.항목` 꼴 |
| `role` · `roles{}` · `capabilities` | 지금 역할, 서버가 아는 역할 전부와 각자의 할 수 있는 일, 지금 역할의 그것(§7) |
| `commanding_available` | 거짓이면 이 배치에 **명령 경로가 아예 없다**. 권한 부족과 다르다 |
| `evidence_available` | 거짓이면 `/api/explain` 과 `POST /api/correction` 이 503 으로 답한다 |
| `scene` | 메인 맵. `/api/scene` 과 같은 모양이라 뷰어가 바로 그릴 수 있다 |
| `domains[]` | 도메인 요약 목록(`scene.domains` 와 같은 원소) |
| `functions[]` | 이 배치가 아는 기능 id 전부 |
| `facts_vocabulary{}` | 사전조건 사실 토큰의 뜻풀이. `unverified_preconditions[].fact` 를 사람 말로 적을 때 쓴다 |

### 6.2 `GET /api/scene`

메인 맵. `space`(좌표 평면) · `domains[]`(도메인 요약) · `map_tiles`(배경 타일 선언)
이고 **구역은 들어 있지 않다** — 층이 여러 개인 도메인에서 쓰지 않는 구역까지 실리기
때문이다. 구역은 도메인을 열 때 받는다.

#### 메인 맵의 평면은 두 모양 중 하나다

| `space.unit` | 언제 | 도메인을 무엇으로 그리는가 |
|---|---|---|
| `index` | 현장 배경 그림이 없을 때 (**기본값**) | `rect` — 무차원 격자 위의 네모. 자리가 아니라 **목록**이다 |
| `meter` | 현장 배경 그림이 걸렸을 때 | `site_at` — 현장 평면 위의 **점**(맵 포인트) |

미터 평면일 때 `space` 는 `origin`·`frame`·`datum_id`·`background_layer` 를 함께 낸다.

- **`origin` 을 무시하지 않는다.** 현장 평면의 원점은 (0,0) 이 아니다 — datum 이
  가리키는 점이 (0,0) 이라 평면은 그 둘레로 **음수 쪽까지** 뻗는다. 0 에서 그리면
  지도의 한쪽이 화면 밖으로 나가고 핀이 엉뚱한 자리에 선다.
- **평면은 배경 그림에서 유도된 값이다**(`background_layer` 가 그 그림을 가리킨다).
  뷰어가 평면을 따로 선언해 두면 그림을 갈아 끼운 날 핀만 제자리에 남는다.
- **`frame` 이 기준계를 말한다.** 현장 평면은 `site-local` 이고 구역 안의 좌표와
  교환 가능하지 않다 — 같은 칸에 담지 않는다(AI-C-02).

`site_at` 은 **선언이지 측량값이 아니다.** 공개 지도가 적어 둔 건물 윤곽의 중심이고,
`verified: false` 와 `source` 가 값과 함께 다닌다. 뷰어는 이것을 선언으로 그려야 하고
측량된 자리처럼 보이게 해서는 안 된다(AI-S-08). 자리를 모르는 도메인은 **칸 자체가
없다** — 0 으로 채우면 지도 왼쪽 위 구석에 건물이 하나 생긴다.

`level_ids[]` 는 그 도메인의 층 이름이다. 도메인을 열기 전에 층에 걸린 것(배경 도면
같은 것)을 물어볼 수 있게 한다 — 개수만으로는 물어볼 수 없고, 못 물으면 층에 도면이
걸려 있는데도 "도면 없음" 으로 보인다.

`map_tiles` 는 배경 지도의 **조달 선언**이다(§3.9). 기본값은 타일 없음이고 그 값은 어떤
외부 연결도 요구하지 않는다.

```json
{
  "declared": true,
  "closed_network": true,
  "default_layer_id": "none",
  "requires_external_connection": false,
  "external_hosts": [],
  "layers": [
    { "layer_id": "none", "kind": "none", "label": { "ko": "배경 없음", "en": "No basemap" },
      "enabled": true, "available": true,
      "requires_external_connection": false, "external_hosts": [] },
    { "layer_id": "site-offline-pack", "kind": "offline_pack",
      "enabled": false, "available": false, "unavailable_reason": "pack_missing",
      "requires_external_connection": false, "external_hosts": [],
      "url_template": "{z}/{x}/{y}.png", "min_zoom": 14, "max_zoom": 19 },
    { "layer_id": "osm-public", "kind": "remote_xyz",
      "enabled": false, "available": false,
      "unavailable_reason": "external_connection_required",
      "requires_external_connection": true,
      "external_hosts": ["tile.openstreetmap.org"],
      "url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      "attribution": "© OpenStreetMap contributors (ODbL 1.0)" }
  ]
}
```

| 칸 | 뜻 |
|---|---|
| `declared` | 타일 선언 파일이 이 배치에 있는가. 거짓이면 서버의 내장 기본값(타일 없음)이다 |
| `closed_network` | 폐쇄망 프로파일로 선언됐는가. 참이면 외부 연결을 요구하는 레이어를 **켠** 선언이 거절된다 |
| `default_layer_id` | 처음 보여 줄 레이어. 기본은 `none` |
| `requires_external_connection` | 지금 **켜져 있고 쓸 수 있는** 레이어 중 하나라도 외부로 나가야 하는가. 적혀만 있고 꺼진 레이어는 세지 않는다 — 그래야 이 값이 폐쇄망 검증에 쓸 수 있는 답이 된다 |
| `layers[].kind` | 벤더 이름이 아니라 **조달 방식**이다: `none` · `offline_pack`(내부에 둔 묶음) · `remote_xyz`(외부 XYZ 서버). 열린 어휘이므로 모르는 값은 통과시킨다 |
| `layers[].available` · `unavailable_reason` | 지금 실제로 쓸 수 있는가, 못 쓰면 왜(`pack_missing` · `external_connection_required`). 못 쓰는 레이어는 목록에서 **지우지 않는다** — 없는 것과 못 쓰는 것은 다르다(§6.8) |
| `layers[].attribution` | 라이선스가 요구하는 출처 표기 **문구**다. 표현 결정이 아니라 사실이므로 서버가 낸다 |

타일 자체는 이 계약으로 오지 않는다 — 픽셀은 별도 경로다(AI-C-08). 여기 있는 것은
"어디서 가져올 수 있는가" 뿐이고, 어떤 색으로 어떻게 겹쳐 그릴지는 뷰어의 몫이다.

도메인 요약의 칸:

| 칸 | 뜻 |
|---|---|
| `domain_id` · `label` | 식별자와 언어별 이름 |
| `rect` | 메인 맵 평면에서 그 도메인이 차지한 사각형(`space.unit` 단위) |
| `state` · `reachable` | 그 도메인을 대표하는 구역 상태와 접근 가능 여부. **가장 좋은 구역**이 도메인을 대표한다 — 평균을 내면 한 구역만 살아 있는 도메인과 전부 유휴인 도메인이 같아 보인다 |
| `zone_count` · `level_count` · `declared_count` · `discovered_count` · `reachable_zone_count` | 서버가 센 값(§3.6) |
| `usable_functions[]` | 그 도메인에서 지금 가능한 기능 id |
| `site` | 실제 현장 정보. `verified_fields`/`unverified_fields` 로 실측과 미실측을 가른다. `example: true` 면 실제 현장이 아니라 예시 배치이고 뷰어는 **이 사실을 반드시 드러내야 한다** |
| `domain_profile` | 그 도메인이 도는 배포 프로파일 이름. **분기 근거로 쓰지 않는다** — 도메인 이름으로 갈라지는 코드는 서버에도 없고 뷰어에도 있어서는 안 된다(AI-C-15) |
| `rf{}` | 전파 모델 표. 키는 모델 이름이고 구역의 `wifi.rf` 가 이 키를 가리킨다 |
| `geo` | 그 현장의 **전역 좌표 계층** 상태와 사유(§3.5). datum 이 없는 현장은 `{"layer": "disabled", "reason": "no_datum"}` 하나이고 그것이 정상이다. 전역 숫자가 이 계약으로 오는가는 `coordinates_in_view_contract` 가, 오지 않는 사유는 `coordinates_withheld_reason` 이 말한다 |

### 6.3 `GET /api/domain?id=`

도메인 하나를 열었을 때의 장면. `space`·`levels[]`·`site`·`geo`·`rf{}`·`zones[]`.

- `geo` — §3.5 의 전역 계층 블록이고 **메인 맵의 같은 도메인 칸과 같은 값**이다(AI-O-06:
  같은 사실은 한 출처에서 파생된다). `site` 에는 기준점도 경계 재합의 기록도 오지 않는다 —
  같은 사실을 두 칸에 담으면 두 칸이 갈라진다. `site.unverified_fields` 에 `datum` 이
  있으면 그 현장의 기준점이 미검증이라는 뜻이고, 그때 `geo.layer` 는 `disabled` 다.

- `levels[]` — 층. `y_offset` 은 여러 층을 한 평면에 펼친 장면에서 그 층이 차지한 띠의
  시작이다. 뷰어가 한 층만 보여 줄 때는 `zones[].level_id` 로 걸러 `y_offset` 만큼
  올려 그린다.
- `zones[]` — 구역 요약 + `rect` + `robots[]`(마커용 축약: `node_id`·`role`·`at`·
  `at_origin`·`presence`·`usable_function_count`) + `infrastructure[]`(`id`·`kind`·
  `at`·`at_origin`·`pose`). 경계 재합의가 기록된 현장에서는 두 목록의 원소에
  `at_global` 이 **더** 붙는다(§3.5). 그 칸이 없는 것이 보통이고 없는 것은 고장이
  아니다.

`at` 이 `null` 이면 **자리를 모른다**는 뜻이고 원점이 아니다. 그 장치를 (0,0) 에 그리면
없는 위치를 있다고 그리는 것이다 — 목록에는 남기고 지도에서는 빼거나, 자리 미지정임을
밝혀 따로 모아 보여 준다.

### 6.4 `GET /api/zone?id=`

구역 상세. 구역 요약의 모든 칸에 다음이 더해진다.

| 칸 | 뜻 |
|---|---|
| `rect` · `space` | 그 구역의 사각형과 좌표 평면(단위 포함) |
| `rf` | 그 구역 AP 의 전파 모델 하나(`kind` + 모델 칸). `radius_m.handover` 가 **구역 한 칸의 크기를 정한 근거**다 |
| `wifi` | `ap_id`·`at`·`rf`. 빈 객체일 수 있다(무선 선언이 없는 구역은 정상) |
| `neighbours[]` | 맞닿은 구역과 `same_ap`·`radio_handover_required`. 같은 AP 를 공유하는 두 구역 사이의 이동은 **무선 전환이 아니다** — 옥외에서는 한 AP 가 수백 m 를 덮어 구역 경계가 전파 경계와 일치하지 않는다. 이 구분을 지우면 "구역을 넘었으니 재접속했을 것"이라는 틀린 가정이 생긴다 |
| `movable_devices[]` | 자리를 고칠 수 있는 장치 — **고정 장치만**이다 |
| `infrastructure[]` | 고정 장치 상세: `id`·`kind`·`at`·`at_origin`·`pose`·`calibration`·`resources`. `resources` 는 **칸이 없을 수 있다** — 아직 조인하지 않아 자원을 모르는 장치이고, 빈 객체로 적으면 "태그가 없는 장치" 로 읽힌다(§3.2) |
| `robots[]` | 로봇 상세(`/api/robot` 과 같은 모양) + `at`·`at_origin` |
| `access_point` | 그 구역의 무선 송출기 하나(`id`·`kind`·`at`·`declared_at`·`rf`·`joins_as_node`·`placement_verified`). 노드로 조인하지 않는 물건이므로 자원도 capability 도 없다 |
| `interiors[]` | **더 들어갈 수 있는 방.** `room_id`·`label`·`rect`(구역 로컬)·`size_m`·`verified`, 그리고 실내 장면 **참조**인 `interior`. 기하가 선언된 방만 들어오고 이름만 있는 방(`rooms[]`)은 들어오지 않는다 — 화면이 "들어갈 수 있다"고 말한 자리가 실제로 열려야 한다. 비어 있는 것이 정상이다 |

자리 칸이 있는 원소(`infrastructure[]` · `robots[]` · `access_point`)에는 경계 재합의가
기록된 현장에서만 `at_global` 이 더 붙는다(§3.5).

**이동형 로봇은 `movable_devices` 에 들어오지 않는다.** 그 자리는 관측이 정하므로 사람이
끌어다 놓은 값이 관측을 덮으면 화면과 실제가 갈린다. 뷰어가 목록 밖의 장치를 끌 수 있게
만들면 서버가 400 `device_not_movable` 로 거절한다. 고친 자리도 선언을 지우지 않고 위에
덧대이므로 `at_origin` 이 `operator_edit` 으로 바뀌고 원래 선언이 무엇이었는지는 남는다.

### 6.5 `GET /api/robot?id=&zone=`

| 칸 | 뜻 |
|---|---|
| `node_id` · `zone_id` · `domain_id` | 식별자. 뒤 둘은 `null` 일 수 있다(어느 구역에도 선언되지 않은 장치는 정상이다) |
| `role` | 역할 토큰(`ugv`·`uav`·`fixed_camera`·`edge_node`·`server` 등 **등록 데이터**). 도형 이름이 아니다 |
| `label` | 사람이 읽는 이름. 도메인·구역의 `label` 과 달리 **평평한 문자열**이다(배치 설정에서 한 언어로 온다) |
| `verified` | 거짓이면 그 하드웨어 구성이 아직 실물로 확인되지 않았다 |
| `presence` · `last_seen_age_s` | §5 |
| `announced_actions[]` | 장치가 접속 직후 **스스로 알린** action 이름(AI-C-18). 선언 파일이 아니라 장치가 말한 것이다 |
| `resources` | `tags[]`(하드웨어·런타임 조건을 나타내는 자유 문자열 태그 — 벤더 열거형이 아니다) + `compute_units`·`memory_mb`(없으면 미측정) |
| `served_kinds[]` | 그 로봇이 실제로 제공하는 capability kind |
| `infrastructure_kinds[]` | 그 구역 고정 인프라가 더해 주는 kind |
| `functions[]` | 기능별 판정: `function_id`·`state`·`missing_required`·`missing_optional`·`from_infrastructure`. 마지막 칸은 "로봇 자신은 못 내지만 구역 인프라가 메워 준다"는 **협동 지점**이다 |
| `usable_functions[]` | `ACTIVE`·`DEGRADED` 인 기능의 id |
| `recommendations[]` | §6.6 과 같은 원소. `/api/robot` 에서만 붙는다 |
| `command_vocabulary[]` | 지금 이 장치에 보낼 수 있는 action. **칸이 없으면 명령 경로가 없다**. 이것은 조회 계약이 알려 주는 **별도 제어 계약의 어휘**일 뿐이고 발급은 `POST /api/command` 로만 된다 |

### 6.6 `GET /api/recommend?robot=&zone=`

`{"recommendations": [...]}`. 빈 배열은 정상이다 — 추천할 것이 없는 배치에서도 이 끝점은
사라지지 않는다.

| 칸 | 뜻 |
|---|---|
| `mission_kind` · `title` · `priority` | 임무 종류 토큰, 영문 제목, 정렬 우선순위(작을수록 먼저) |
| `goal_kind` | `/api/subtasks` 의 `function` 인자와 **같은 어휘**다. 그래서 추천을 누르면 그대로 분해로 이어진다 |
| `recommended` | 참이면 지금 권할 수 있다 |
| `reason` | 열린 토큰: `recommended` · `no_triggering_evidence` · `missing_required_capability` |
| `matched_triggers[]` | 성립한 촉발 근거. 비어 있으면 근거 없이 올라온 후보이고 `recommended` 는 거짓이다 |
| `missing_capabilities[]` | 막힌 후보가 **무엇이 없어서** 막혔는가 |
| `subjects[]` | 그 추천이 가리키는 대상(미확정 객체 id·카메라 id 등) |

막힌 후보를 감추지 말라는 것이 AI-B-15 의 요구다 — 감추면 운영자가 다음에 무엇을
보완해야 하는지 알 수 없다. 뷰어는 막힌 후보를 **흐리게라도 보여 주고** 사유를 함께
적는 것을 권한다(어떻게 보일지는 뷰어의 결정이다).

### 6.7 `GET /api/subtasks?robot=&zone=&function=`

한 목표를 실행 단계로 분해한 그래프. 노드 수·깊이·분기 수에 상한이 없다.

| 칸 | 뜻 |
|---|---|
| `plan_id` · `goal_id` · `goal_kind` · `zone_id` · `robot_id` | 식별자와 맥락 |
| `generator` · `template_version` | 그 그래프를 낸 방식과 템플릿 판. 생성 제공자가 바뀌어도 모양은 같다 — 특정 생성 모델·서비스는 필수 의존성이 아니다(AI-B-14) |
| `reason` | 열린 토큰: `fully_executable` · `partially_executable` · `no_template_for_goal_kind` · `no_executor_candidate` · `no_executor_meets_required_capabilities` |
| `executor` | 그 구역이 공급하는 가상 실행자(`executor_id`·`state`·`reason`). `executor_id: null` 이면 공급자를 고르지 못했다 |
| `nodes[]` | 단계. 아래 표 |
| `edges[]` | `{from, to, item}` — 단계 사이의 **자료 흐름**. 같은 쌍에 여러 자료가 흐를 수 있어 `(from, to)` 는 유일하지 않다(SVG 렌더러가 같은 쌍의 간선마다 곡률을 달리하는 이유) |
| `escalation_capabilities[]` | 지금 아무도 못 내서 외부 개발 요청으로 올려야 하는 capability |
| `cost_total` | 선언된 비용 합(`compute_units`·`memory_mb`). 측정값이 아니라 **선언값**이다 |
| `zone_supply_placements[]` | 구역이 공급하는 `(capability_kind, provider_id)` 쌍 |

단계(`nodes[]`)의 칸:

| 칸 | 뜻 |
|---|---|
| `subtask_id` · `action` · `order_index` | 식별자, 하는 일의 토큰, 순서 |
| `state` · `executable` | 기능 가용성과 실행 가능성. **다른 축이다** — 한 칸에 합치면 "기능이 없다"와 "사전조건이 미확인이다"가 구분되지 않는다 |
| `runs_on[]` | `robot` · `zone`. 비어 있으면 capability 를 요구하지 않는 단계다 |
| `bindings[]` | `{capability_kind, provider_id, source, optional}`. `source` 가 **실행 위치**를 말한다: `registry` = 로봇 위에서 돈다, `executor` = 구역이 공급한다. 운영자가 알아야 하는 "이 단계는 어디서 도는가"가 이 값이다 |
| `missing_required[]` · `missing_optional[]` | 결손 capability |
| `unverified_preconditions[]` | `{fact, means}` — 참이라고 **확인되지 않은** 사전조건. 모르는 것을 참으로 채우지 않기 때문에 생긴다. 채우면 막혀야 할 단계가 통과한 것처럼 보인다 |
| `violated_forbidden[]` | 금지 조건 위반 |
| `unmet_inputs[]` | 그 단계가 받아야 하는데 **내는 앞 단계가 없는** 입력. 조용히 이어 붙이지 않는다 |
| `cost` | 그 단계의 선언 비용 |

간선을 생성 주체가 적지 않는 이유(AI-B-14): 각 단계가 무엇을 내고 받는지만 데이터로
적고 간선은 규칙이 계산한다. 그래서 순환이 구조적으로 생기지 않고, 뷰어는 받은
`edges[]` 를 **그대로** 그리면 된다.

### 6.8 없는 것과 못 쓰는 것을 가른다

`/api/explain` 은 추론 근거 제공자가 없는 배치에서 503 `no_evidence_path` 를 낸다 —
**경로는 있고 그 기능이 이 배치에 없다**는 뜻이다. 아예 없는 경로는 404
`unknown_path` 다. 둘을 같게 그리면 뷰어가 "판이 낮아 아직 없는 기능"과 "고장"을
가를 수 없다.

개발자 역할 전용 끝점(`/api/object`, `/api/failure`)에 운영자 역할로 들어오면 403
`role_may_not_see_internals` 다. 이것도 고장이 아니다 — 그 역할에서는 그 영역을 아예
그리지 않는 것이 맞다.

**뷰어는 이 503 을 고장으로 그려서는 안 된다.** AI-C-05 에 따라 선택 기능의 부재는
정상적인 축소 운용이고, 그것을 장애로 그리면 멀쩡한 배치가 장애로 읽힌다. 그 기능의
탭·영역을 "이 배치에 없음"으로 적고 나머지는 그대로 돌려야 한다.

### 6.9 오류 본문

모든 4xx·5xx 응답의 본문은 `{"error": "<토큰>"}` 이다. 값은 문장이 아니라 통제 어휘
토큰이고 `[a-z0-9_]+` 꼴이다.

| 상태 | 토큰 | 뜻 |
|---|---|---|
| 400 | `unknown_role` · `unknown_locale` | 모르는 역할·언어 |
| 400 | `id_required` · `robot_required` · `robot_and_function_required` · `zone_required` | 질의 인자 누락 |
| 400 | `device_and_zone_required` · `device_not_movable` · `bad_placement` | 자리 수정 요청이 틀렸다 |
| 400 | `body_not_json` · `body_must_be_object` | POST 본문이 JSON 객체가 아니다 |
| 403 | `role_may_not_command` · `role_may_not_correct` · `role_may_not_edit_placement` | 그 역할이 할 수 없는 일 |
| 404 | `unknown_domain` · `unknown_zone` · `unknown_robot` · `unknown_goal_kind` · `unknown_path` | 없는 대상 |
| 405 | `read_only_path` | **조회 경로로 바꾸려 했다**(§2) |
| 503 | `no_command_path` · `no_evidence_path` · `not_wired_yet` | 그 기능이 이 배치에 없다 — 고장이 아니다 |

---

## 7. 역할 — 그리고 진짜 권한 경계는 어디인가

`bootstrap.roles` 는 서버가 아는 역할 전부와 각자의 할 수 있는 일을 **데이터로** 낸다.
역할 이름을 뷰어에 박으면 역할이 늘 때 뷰어를 고쳐야 하므로 이 표를 읽는다.

현재 역할은 둘이고 차이는 "무엇을 할 수 있는가"다(보기 편의가 아니다).

| 역할 | `may_command` | `may_correct` | `sees_internals` |
|---|---|---|---|
| `admin` | 참 — 물리 명령 발급 | 참 — 근거 수정·자리 수정 | 거짓 |
| `developer` | 거짓 | 거짓 | 참 — 계약 원문·provider 내부 화면 |

`sees_internals` 는 권한이 아니라 **화면 범위**다. 개발자 화면에만 있는 내부 표시를 켤지
말지의 값이다.

**솔직히 적어 둘 것**: 이 역할 분리는 **뷰어를 위한 편의이고 운영의 실제 권한 경계가
아니다.** 뷰어가 `may_command: false` 를 보고 버튼을 감추지 않아도 서버가 403 으로
끊고(그 동작은 시험이 고정한다), 운영의 최종 차단은 백엔드가 역할·범위로 한다. 즉 이
표는 "화면을 어떻게 구성할지"의 재료이고 "무엇이 허용되는지"의 정본이 아니다. 뷰어는
이 표로 UI 를 줄일 수 있지만 이것을 보안 경계로 **믿어서는 안 된다**.

이 사실은 **문서에 적고 화면 문구로는 쓰지 않는다.** 운영자에게 "이 권한 표는 사실
권한이 아닙니다"라고 적는 것은 혼란만 주고, 필요한 사람(뷰어를 만드는 사람)은 이 문서를
읽는다.

---

## 8. 지역화 — 언어는 뷰어가 늘린다

`GET /api/bootstrap?locale=ko` 는 그 언어의 문자열표를 통째로 낸다.

```json
{
  "locale": "ko",
  "locales": ["en", "ko"],
  "strings": { "app.title": "FMS", "map.state.operable": "운용 가능", "...": "..." }
}
```

규칙:

1. 키는 `구역.항목` 꼴이고(`map.state.operable`, `robot.presence.declared`,
   `fn.state.ACTIVE`) **상태 토큰이 키 안에 들어간다.** 그래서 뷰어는 서버가 낸 토큰을
   `"map.state." + zone.state` 로 이어 붙여 문구를 찾는다 — 상태마다 조건문을 쓰지 않는다.
2. **모든 언어의 키 집합은 같다.** 한쪽에만 있는 키는 화면에서 빈칸이나 영어 잔재로
   나타나므로, 그 불변조건을 시험(`test_both_locales_carry_exactly_the_same_keys`)이
   지킨다.
3. 뷰어는 **문자열표에 없는 문구를 화면에 박지 않는다.** 박으면 언어를 바꿀 때 그
   자리만 바뀌지 않는다.
4. 값이 없는 키는 없다(빈 문자열도 쓰지 않는다).

### 새 언어를 더하는 두 가지 길

- **뷰어 안에서 더한다(파이썬을 고치지 않는다).** `GET /api/bootstrap?locale=en` 으로
  키 집합을 받아 그 키들을 그대로 가진 자기 쪽 표(`ja.json` 등)를 만들고, 뷰어가 고른
  언어일 때 서버 표 위에 덮는다. 서버가 모르는 locale 을 질의 인자로 보내면 400
  `unknown_locale` 이므로 **서버에는 서버가 아는 언어로 묻고 표만 바꿔 쓴다.**
  모르는 키가 생기면 영어로 떨어뜨린다(fallback). 이 길이 권장 경로다.
- **서버 표에 더한다.** `tools/fms_console/strings.py` 의 `STRINGS` 에 locale 키를
  더하면 모든 뷰어가 함께 쓴다. 이쪽은 우리 저장소 변경이므로 요청으로 들어온다.

`label` 칸(도메인·구역·층·현장 이름)은 문자열표가 아니라 **배치 데이터**에 언어별로
들어 있다(`{"ko": "...", "en": "..."}`). 뷰어는 고른 locale 을 먼저 찾고 없으면 아무
하나를 써서 **빈칸을 그리지 않는다.** 로봇 `label` 은 평평한 문자열이라 번역이 없다 —
그 자리에 번역이 필요하면 `node_id`/`role` 을 키로 뷰어 표에서 찾는 쪽을 권한다.

---

## 9. 렌더러 인터페이스 — 무엇을 구현하면 교체되는가

지금 운영 페이지(`tools/fms_console/index.html`)에는 객체 하나가 맵을 그린다.

```js
const SvgMapRenderer = (() => { /* ... */ })();

const Map3D = SvgMapRenderer;   /* 교체 지점: 여기 한 줄만 다른 렌더러로 바꾼다. */
```

**교체 지점은 저 한 줄이다.** 같은 메서드 이름을 가진 객체를 만들어 `Map3D` 에 넣으면
서버도, 나머지 화면 코드도, 이 계약도 그대로다. 색·픽셀·글꼴·도형은 전부 그 객체 안에만
있다.

구현할 메서드는 넷이다.

| 메서드 | 소비하는 응답 | 하는 일 |
|---|---|---|
| `drawDomains(host, scene, handlers)` | `GET /api/scene`(또는 `bootstrap.scene`) | 메인 맵 — 도메인들을 그린다 |
| `drawDomain(host, domain, handlers, levelId)` | `GET /api/domain?id=` | 그 도메인의 구역·고정 장치·로봇 마커. `levelId` 가 주어지면 그 층만 |
| `drawZone(host, zone, handlers)` | `GET /api/zone?id=` | 구역 상세 — 로봇·고정 장치·AP 커버리지·눈금 |
| `drawGraph(host, graph)` | `GET /api/subtasks?...` | 서브태스크 그래프(노드=단계, 간선=자료 흐름) |

`host` 는 그릴 컨테이너다. SVG 구현에서는 DOM 요소이고, Unity 구현에서는 캔버스 요소나
씬 핸들처럼 **그 구현이 아는 무엇이든** 될 수 있다 — 호출하는 쪽은 `host` 를 들여다보지
않는다. 메서드는 호출될 때마다 그 컨테이너의 내용을 **전부 다시 그린다**(부분 갱신
계약이 없다. 상태가 바뀌면 화면 코드가 다시 받아 다시 그린다).

### 콜백

`handlers` 는 뷰어가 아니라 **화면 코드**가 준다. 렌더러는 사용자 조작을 받아 아래를
부르기만 하고, 팝업·탭 전환·요청은 전부 화면 코드가 한다. 그래서 렌더러를 바꿔도 화면
흐름은 그대로다.

| 메서드 | 콜백 | 언제 · 무엇을 넘기는가 |
|---|---|---|
| `drawDomains` | `onHover(domain, event)` | 도메인에 커서가 올라갔다. `domain` 은 **받은 도메인 요약 객체 그대로**, `event` 는 팝업 자리를 잡을 포인터 사건 |
| | `onLeave()` | 커서가 벗어났다 |
| | `onClick(domain_id)` | 도메인을 골랐다. 넘기는 것은 **id 문자열** |
| `drawDomain` | `onHover(zone, event)` · `onLeave()` · `onClick(zone_id)` | 같은 모양. `zone` 은 구역 요약 객체, 클릭은 `zone_id` 문자열 |
| `drawZone` | `onRobotHover(robot, event)` | 로봇 마커에 커서. `robot` 은 `zone.robots[]` 의 원소 그대로 |
| | `onRobotClick(node_id)` | 로봇을 골랐다 |
| | `onDeviceHover(device, event)` | 고정 장치에 커서. `device` 는 `zone.infrastructure[]` 의 원소 |
| | `onLeave()` | 커서가 벗어났다 |
| | `onDeviceMoved(device, {x, y})` *(선택)* | 고정 장치를 끌어다 놓았다. **좌표는 화면 픽셀이 아니라 그 구역 `space.unit` 의 로컬 좌표여야 한다** — 화면 좌표를 장면 좌표로 되돌리는 일은 렌더러의 책임이다(SVG 구현의 `toSpace()`). 화면 코드는 이 값을 `POST /api/placement` 로 보낸다 |
| | `onUnplaced(robots[])` *(선택)* | `at` 이 없는 로봇들. 지도에 찍을 수 없으니 목록으로 따로 보여 주라는 뜻이다. 구현하지 않으면 그 로봇들은 지도에서만 빠진다 |
| `drawGraph` | — | 콜백 없음 |

선택 콜백을 주지 않으면 그 상호작용만 없고 나머지는 그대로 돈다 — 선택 기능의 부재가
다른 기능을 막지 않는다는 규칙(AI-C-05)을 화면에도 적용한 것이다. 예컨대 자리 수정이
없는 뷰어는 `onDeviceMoved` 를 비우면 되고, 서버 쪽에 바뀌는 것은 없다.

### 렌더러가 **하지 않는** 일

- 상태를 다시 판정하지 않는다(§3.7).
- 서버에 직접 요청하지 않는다. 데이터는 화면 코드가 받아 넘긴다 — 그래서 렌더러를
  Unity 로 바꿀 때 HTTP 코드를 다시 쓸 필요가 없다.
- 전역 좌표를 만들지 않는다(§3.5). 받은 `at_global` 은 그릴 수 있지만 `at` 에서 스스로
  유도해서는 안 된다 — 같은 변환이 두 곳에 있으면 두 화면이 다른 값을 말한다.
- 문자열을 만들지 않는다. 그릴 글자는 `label`·`id` 처럼 받은 값이거나 문자열표에서
  꺼낸 문구다.

---

## 10. 걸어 보기 — 맵 렌더러를 Unity WebGL 로 바꾸기

목표: SVG 맵을 Unity WebGL 씬으로 바꾼다. **서버 변경 0, 계약 변경 0.**

### 1단계 — 교체 지점만 바꾼다

```js
// const Map3D = SvgMapRenderer;
const Map3D = UnityMapRenderer;   // 아래에서 만든다
```

### 2단계 — Unity 쪽에 네 개의 진입점을 만든다

Unity WebGL 빌드는 `unityInstance.SendMessage(object, method, payloadJson)` 으로 JS
에서 호출된다. 그러니 JS 쪽 어댑터는 이 모양이면 된다.

```js
const UnityMapRenderer = (() => {
  let unity = null;                   // createUnityInstance(...) 의 결과
  let handlers = {};                  // 지금 화면의 콜백 묶음

  // Unity → JS. jslib 플러그인에서 부른다.
  window.FmsViewBridge = {
    hover(json)        { const d = JSON.parse(json); handlers.onHover?.(d.payload, d.pointer); },
    leave()            { handlers.onLeave?.(); },
    click(id)          { handlers.onClick?.(id); },
    robotHover(json)   { const d = JSON.parse(json); handlers.onRobotHover?.(d.payload, d.pointer); },
    robotClick(id)     { handlers.onRobotClick?.(id); },
    deviceHover(json)  { const d = JSON.parse(json); handlers.onDeviceHover?.(d.payload, d.pointer); },
    // 좌표는 Unity 안에서 이미 구역 로컬 좌표(space.unit)로 되돌려 보낸다.
    deviceMoved(json)  { const d = JSON.parse(json); handlers.onDeviceMoved?.(d.device, d.at); },
    unplaced(json)     { handlers.onUnplaced?.(JSON.parse(json)); },
  };

  const send = (method, payload) =>
    unity?.SendMessage("ViewRoot", method, JSON.stringify(payload));

  return {
    drawDomains(host, scene, h) { handlers = h; send("DrawDomains", scene); },
    drawDomain(host, domain, h, levelId) {
      handlers = h; send("DrawDomain", {domain, level_id: levelId ?? null});
    },
    drawZone(host, zone, h) { handlers = h; send("DrawZone", zone); },
    drawGraph(host, graph)  { send("DrawGraph", graph); },
  };
})();
```

C# 쪽은 `DrawDomains(string json)` 같은 메서드 넷을 가진 `ViewRoot` 하나와, 받은 JSON 을
그대로 역직렬화하는 DTO 들을 둔다. **DTO 는 스키마에서 생성하는 쪽을 권한다**(§11) —
손으로 적으면 우리가 칸을 더할 때 조용히 어긋난다. 모르는 칸은 버리도록 설정한다(§3.3).

### 3단계 — 각 메서드가 실제로 쓰는 칸

아래가 **그리는 데 필요한 전부**다. 이 목록 밖의 칸은 그리지 않아도 화면이 선다.

`DrawDomains` ← `GET /api/scene`

| 쓰는 칸 | 어디에 |
|---|---|
| `space.width` · `space.height` · `space.unit` | 카메라·평면 크기와 글자 크기 정규화 |
| `domains[].rect {x,y,w,h}` | 도메인 한 칸의 자리 |
| `domains[].state` | 뷰어가 고른 표현으로 가른다(머티리얼·테두리 등) |
| `domains[].reachable` | 접근 가능 강조 |
| `domains[].example` | 예시 배치임을 반드시 드러낸다 |
| `domains[].label` | 고른 locale 의 이름 |
| `domains[].zone_count` · `level_count` · `declared_count` · `discovered_count` | 칸 안에 적는 숫자 |
| `domains[].domain_id` | `click` 으로 돌려보낼 id |

`DrawDomain` ← `GET /api/domain?id=` (+ 선택 `level_id`)

| 쓰는 칸 | 어디에 |
|---|---|
| `space.{width,height}` | 평면 크기(한 층만 그릴 때는 그 층 구역들의 최대 `y+h` 에서 `levels[].y_offset` 을 뺀 값) |
| `levels[].level_id` · `y_offset` | 층 선택과 평면 이동 |
| `zones[].rect` · `label` · `rooms` · `state` · `reachable` · `verified` | 구역 칸 |
| `zones[].wifi.at` · `zones[].wifi.rf` + `rf[<키>].radius_m.handover` | AP 커버리지 원 — 구역 크기의 근거를 눈에 보이게 한다 |
| `zones[].infrastructure[].{at, kind}` | 고정 장치 마커(`kind` → 뷰어가 고른 형태) |
| `zones[].robots[].{at, role, presence}` | 로봇 마커 |
| `zones[].zone_id` | `click` 으로 돌려보낼 id |

`DrawZone` ← `GET /api/zone?id=`

| 쓰는 칸 | 어디에 |
|---|---|
| `rect` · `space.unit` | 바닥 평면과 눈금 단위(1 격자가 몇 m 인지 함께 적는다) |
| `state` | 바닥 테두리 표현 |
| `wifi.at` · `rf.radius_m.{handover, excellent}` · `wifi.ap_id` | AP 와 두 반경 |
| `infrastructure[].{id, kind, at, at_origin, pose}` | 고정 장치. `pose.yaw_deg` 로 바라보는 방향, `at_origin === "operator_edit"` 이면 사람이 고친 자리임을 드러낸다 |
| `movable_devices[]` | 끌 수 있는 장치만 끌리게 한다. 이동형 로봇은 여기 없다(§6.4) |
| `robots[].{node_id, role, at, presence}` | 로봇 마커와 이름 |
| `robots[]` 중 `at` 이 없는 것 | `unplaced` 로 올려보낸다 |

`DrawGraph` ← `GET /api/subtasks?...`

| 쓰는 칸 | 어디에 |
|---|---|
| `nodes[].{subtask_id, action, state, runs_on}` | 노드 하나 |
| `edges[].{from, to, item}` | 간선과 그 위의 자료 이름. 같은 쌍이 여러 번 나오므로 겹치지 않게 흩뜨린다 |

### 4단계 — 자리 수정을 되돌려 보낸다

Unity 안에서 끌어다 놓은 좌표는 **구역 로컬 좌표로 되돌려** `deviceMoved` 로 올린다.
화면 코드가 그것을 그대로

```http
POST /api/placement?role=admin
{"device_id": "...", "zone_id": "...", "at": {"x": 12.5, "y": 7.0}, "reason": "..."}
```

로 보낸다. 서버는 `movable_devices` 밖의 장치를 400 `device_not_movable` 로, 권한이
없으면 403 `role_may_not_edit_placement` 로 거절한다. `{"reset": true}` 를 보내면 선언된
자리로 되돌아간다.

### 5단계 — 끝. 확인할 것

- 서버 코드·스키마·문서 변경: 없음.
- 같은 데이터로 두 렌더러가 **같은 사실**을 그린다. 다른 것은 표현뿐이다.
- `handlers` 를 선택적으로 비워도(`onDeviceMoved` 없음 등) 나머지가 돈다.

Unity 를 쓰지 않는 뷰어(React + Canvas, deck.gl, three.js 등)도 같은 넷을 구현하면
된다. 어떤 엔진도 이 계약의 의존성이 아니다(AI-C-15).

---

## 11. 계약을 기계로 검사하는 법

### 스키마 파일

| 파일 | 대상 |
|---|---|
| `schemas/view_snapshot.schema.json` | **허브** — 모든 공유 모양(`$defs`)과, 여러 응답을 한 덩어리로 묶은 스냅샷. 끝점 파일은 모두 이 파일의 `$defs` 를 가리킨다 |
| `schemas/view_bootstrap.schema.json` | `GET /api/bootstrap` |
| `schemas/view_scene.schema.json` | `GET /api/scene` |
| `schemas/view_domain.schema.json` | `GET /api/domain?id=` |
| `schemas/view_zone.schema.json` | `GET /api/zone?id=` |
| `schemas/view_robot.schema.json` | `GET /api/robot?id=` (구역 상세의 `robots[]` 원소도 같다) |
| `schemas/view_recommendations.schema.json` | `GET /api/recommend?robot=` |
| `schemas/view_subtask_graph.schema.json` | `GET /api/subtasks?...` |
| `schemas/view_error.schema.json` | 모든 4xx·5xx 본문 |

JSON Schema 2020-12 이고, 끝점 파일은 허브의 `$defs` 를 가리키는 얇은 포장이다 — 모양을
두 곳에 적으면 두 곳이 갈라지기 때문이다.

### 뷰어 쪽에서 쓰는 법

```python
import json, urllib.request
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

registry = Registry()
for path in Path("schemas").glob("view_*.schema.json"):
    schema = json.loads(path.read_text(encoding="utf-8"))
    registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))

zone_schema = json.loads(Path("schemas/view_zone.schema.json").read_text(encoding="utf-8"))
validator = Draft202012Validator(zone_schema, registry=registry)

with urllib.request.urlopen("http://127.0.0.1:8800/api/zone?id=N4-1F-W&role=admin") as r:
    validator.validate(json.loads(r.read()))
```

TypeScript·C# 뷰어는 같은 파일로 타입을 **생성**하는 쪽을 권한다(예: 스키마 →
TypeScript 타입, 스키마 → C# DTO). 손으로 적으면 우리가 칸을 더할 때 그 사실이 조용히
묻힌다.

### 우리 쪽에서 돌리는 검사

```bash
cd mission_runtime
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OTEL_SDK_DISABLED=true \
  python -m pytest -q tests/test_view_contract.py
```

이 시험은 **실제 서비스를 실제 설정으로 세워 실제 HTTP 로 받은 응답**을 검사한다
(가짜 payload 를 만들지 않는다). 지키는 것:

| 시험 | 막는 썩음 |
|---|---|
| 모든 GET 응답이 공표한 스키마를 통과한다 | 스키마와 실제 응답이 갈라져 바깥 뷰어가 우리 변경 없이 깨지는 일 |
| 조회 경로의 POST 가 405 다 | 관찰이 실행에 개입할 길이 생기는 일 |
| 제어 경로 목록이 조회 경로와 겹치지 않는다 | 제어가 조회로 새어 들어오는 일 |
| 어떤 응답에도 표현 낱말(색·픽셀·글꼴·도형)이 없다 | **서버가 표현을 내기 시작하는 일** — 이 경계가 썩는 가장 흔한 길이다 |
| 전역 좌표 낱말이 `at_global` **밖**에는 없다 | 전역 숫자가 로컬 칸에 섞여 받는 쪽이 기준을 추측하는 일 |
| 경계 재합의를 선언하지 않은 현장에는 전역 블록이 아예 없다 | 합의하지 않은 사실을 합의한 것처럼 내보내 전역 상태의 주인이 둘이 되는 일(§3.5) |
| 선언된 현장에서는 네 조건이 실제로 전부 성립했고 블록이 재료의 정확도를 들고 온다 | 유도한 전역 값이 재료인 로컬 측정보다 정확한 척하는 일 |
| datum 이 없는 도메인에서 전역 계층만 꺼지고 로컬은 그대로 돈다 | datum 없는 현장이 고장처럼 읽히는 일 (`tests/test_fms_map_datum.py`) |
| 미검증 datum 이 전역 값을 거절하고, 유도한 값이 "검증됨" 으로 보이지 않는다 | 공개 지도에서 받아 적은 기준점이 실측처럼 쓰이는 일 |
| 미측정 정확도가 0 으로 새지 않고 `0` 선언이 거절된다 | 유도한 전역 값이 재료인 로컬 측정을 이기는 일 |
| 배경 타일 기본값이 외부 연결을 요구하지 않는다 | 폐쇄망 배치에서 메인 화면이 깨지는 일 (AI-C-16) |
| 모르는 칸이 양방향으로 살아남는다 | 두 팀이 서로의 배포 주기에 묶이는 일 |
| 계약 판이 응답으로 실려 오고 스키마의 판과 같다 | 판을 한쪽만 올리는 일 |
| 두 언어의 키 집합이 같다 | 한 언어에만 있는 키가 빈칸으로 나타나는 일 |
| `never`·`stale`·`fresh` 가 모두 표현되고 서로 다르다 | 미수신을 0 으로 적어 죽은 장치가 싱싱해 보이는 일 |
| 역할 표가 데이터로 오고 서버가 같은 판정을 한다 | 뷰어가 감추기만으로 권한을 대신하는 일 |
| 미연결 끝점이 503 으로 "기능 없음"을 말한다 | 정상 축소가 장애로 읽히는 일 |

---

## 12. 이 계약이 아직 주지 않는 것

솔직히 적는다. 아래는 **지금 없는 것**이고, 필요하면 요청으로 들어온다.

| 없는 것 | 왜 아쉬운가 | 지금의 우회 |
|---|---|---|
| `bootstrap` 본문의 `view_contract_version` | HTTP 머리를 못 읽는 전송(WebSocket 중계 등)에서는 판을 알 수 없다 | `Server` 머리에서 뽑는다. 스키마에는 칸을 예약해 두었다 |
| `bootstrap` 의 `freshness` 묶음(소스 종류별 `stale_after_s`) | 노후 경계를 뷰어마다 따로 정하면 같은 배치를 두 화면이 다르게 읽는다 | 뷰어 설정으로 둔다(§5) |
| 소스별 `last_received_at`(절대 시각) | 나이(초)만 있어 "몇 시에 끊겼는가"를 말할 수 없다 | `last_seen_age_s` 와 응답 수신 시각으로 추산한다 |
| `/api/trace` · `/api/mission` 의 모양 | 실패 원인 추적과 다중 구역 임무 화면을 아직 그릴 수 없다 | 503 `not_wired_yet` 을 "기능 없음"으로 그린다 |
| `/api/explain` 의 스키마 | 추론 근거 화면의 계약이 굳지 않았다 | `evidence_available` 로 있는지 확인하고, 모양은 아직 고정하지 말 것 |
| 구독(push) | 상태가 바뀔 때 받는 길이 없어 뷰어가 주기적으로 다시 묻는다 | 뷰어가 폴링한다. 전송 규약은 백엔드 결정을 따른다 |
| 영상 | 픽셀은 이 계약으로 오지 않는다(AI-C-08) | 별도 미디어 경로를 붙인다 |
| **실제 현장의** 전역 좌표 숫자 | 배경 지도 위에 실제 현장의 로봇을 올릴 수 없다 | 계약에는 길이 있다(§3.5 의 `at_global`) — 막고 있는 것은 그 현장의 네 조건이다. 실제 현장 둘은 기준점이 미검증이고(`datum_unverified`) 경계 재합의 기록도 없다(`boundary_not_reagreed`). 요청은 `docs/integration-handover.md` 에 있고, 예시 현장 `logistics` 가 선언된 경로의 모양을 그대로 보여 준다 |
| 검증된 site datum | 두 실제 현장의 기준점이 아직 공개 지도에서 받아 적은 미검증 값이다(`accuracy_m: null`) | 전역 계층은 비활성이고 로컬 좌표로 운영한다. 검증은 현장 실측(예: 건물·수로 양 끝 GNSS 두 점이면 기준점과 회전이 함께 나온다)으로만 올린다 |
| 배경 타일 묶음 | 오프라인 타일 팩이 아직 배치에 없어 `pack_missing` 이다 | 지도는 로컬 좌표 평면으로 그린다(§3.9) |

이 목록이 줄어들면 §4 의 규칙대로 판이 올라가고, 이 문서와 스키마와 시험이 같이 바뀐다.
