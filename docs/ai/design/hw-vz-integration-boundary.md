# HW·가시화 브랜치 병합 경계 — 의존성 제거 설계

상태: 결정 및 저장소 적용 기록.
근거: 2026-09-16/17 `khw18033/Physical-Project-mk2`의 `HW`/`khw_VZ` 브랜치 조사
(에이전트 조사 결과, 이 세션 대화 참고), `docs/ai/design/external-technology-decisions.md`.

## 0. 목적

`HW`/`khw_VZ` 브랜치는 각각 하드웨어 파트·가시화 파트의 **역할**이지 이 저장소
(perception-framework)가 소유하지 않는다. 이번 정리의 목표는 "두 브랜치를 우리
틀에 병합할 때 우리 쪽 코드를 고쳐야 하는 지점이 있는가"를 확인하고, 있다면
없애는 것이다 — 병합 시점에는 **양쪽이 이미 합의된 정보만 주고받으면 되고, 서로의
내부 구현(로봇 SDK 종류, 프론트엔드 프레임워크)을 몰라도 되는 상태**가 목표다.

## 1. 결론 — 코드 의존성은 이미 없다

`perception_framework/` 전체에 HW/VZ 브랜치의 구체 이름(`Go1Link`, `EpLink`,
`ControllerLink`, `viz-debugger`, `door_example` 등)을 문자열로도 import로도
참조하는 코드가 없다(확인: 이 저장소 자체가 두 브랜치와 별도 워킹트리이므로
애초에 import가 물리적으로 불가능하다). 우리 쪽이 실제로 의존하는 것은:

- `contracts/physical_command.py::Command`/`CommandAcceptance`/`ExecutionStatus` —
  HW의 `schema/physical_command.proto`(`Command`/`CommandAcceptance`/`CommandStatus`/
  `CommandResult`/`CancelCommandRequest`/`Capability`)와 **개념적으로 대응**하지만
  이 파일 자체는 protobuf도, HW 저장소의 어떤 파일도 import하지 않는다 — 같은
  모양의 dataclass를 우리가 독립적으로 선언해 뒀을 뿐이다.
- `providers/adapters.py::HardwareCommandProvider`/`ControlProvider` — Protocol
  (구조적 타이핑)이라 HW 쪽이 이 Protocol을 "구현"하기 위해 우리 코드를 import할
  필요조차 없다. `execute(command) -> (bool, dict|None, str|None)` 시그니처만
  맞추면 된다.
- `contracts/data_dictionary.py` — 필드 **이름**의 정본이지만 이것도 이 저장소
  안의 순수 문자열 상수 모음이다. HW `pi/common/schema.py`의 `envelope()`가 만드는
  필드명(schema_version/source_id/node_id/zone_id/timestamp/session_id/
  sequence_id/correlation_id)이 이미 이름 수준에서 일치하는 것을 확인했다(2026-09-17
  조사) — 이건 **우연이 아니라 둘 다 BE-C-01/BE-C-02를 따랐기 때문**이며, 그래서
  코드 의존 없이도 이름이 맞는다.

## 2. 실제 병합 시점에 필요한 것 — 정보 교환 지점 3곳

병합 자체는 브랜치를 우리 트리 옆에 두는 것으로 끝나지 않는다. 아래 3곳에서
**우리 코드가 아니라 배포 설정/등록 데이터**로 연결한다 — 코드 수정이 필요하면
그건 이 경계 설계가 잘못된 것이다.

### 2-1. HW → 우리 (인지 입력)

HW가 만드는 프레임·센서값은 이미 공통 봉투(`message.schema.json`과 정렬된
`envelope()`)로 온다. 우리 쪽은 이걸 `perception.detect` 등 capability의
provider가 받는 원시 입력으로 취급할 뿐, **HW가 그 값을 MQTT로 보냈는지 ROS 2
DDS로 보냈는지 몰라도 된다** — `providers/adapters.py::TransportProvider`/
`MediaSourceProvider` 뒤에 어떤 구현이 오든 우리 provider 코드는 그대로다.

**격차(HW 조사에서 확인, 조율 필요)**: HW의 `Capability` protobuf(`device_id`+
`actions: repeated string`)는 우리 `ProviderRegistration`(5계층: capability_kind,
compatibility, requirement, execution_profile, runtime_instance)보다 훨씬 얇다.
**이 격차는 우리가 메운다** — HW가 선언한 얇은 `actions` 목록을 받아
`CompatibilityProfile`/`ExecutionProfile`로 보강해 등록하는 어댑터를 우리 쪽에
둔다(AI-C-10: "AI capability 등록은 백엔드 정보를 보완하는 역할"과 정확히 일치).
**HW 쪽 코드를 두껍게 만들라고 요구하지 않는다.**

### 2-2. 우리 → HW (물리 명령)

우리는 `Command`(command_id, target, action, parameters)까지만 만들고
`CommandExecutionSupervisor.submit()`에 넣는다. HW가 이걸 실제 로봇 SDK
호출(`ControllerLink.send_command()`)로 번역하는 어댑터를 **자기 브랜치 안에서**
구현한다 — 우리는 그 어댑터의 존재도, 내부 구현도 몰라도 된다.

**격차(확인 필요, "추가 요구사항 필요"로 남김)**: HW의 물리명령 파라미터가
`map<string,double>`로 고정돼 있어(HW 조사 결과) 문자열 파라미터(예: `mission_id`,
`subtask`)를 못 싣는다. AI-S-05가 구조화된 문자열 조건을 실어야 하는 관측 요청을
만들 경우 이 제약과 충돌할 수 있다 — 코드로 미리 우회하지 않고 HW 쪽과 조율이
필요한 지점으로 명시해 둔다.

**비동기 특성 조정**: `HardwareCommandProvider.execute()`가 동기 3-tuple을
반환하는데 HW 규약은 수락→실행중→결과의 비동기 다단계다. 이 어댑터를 실제로
구현할 때 `execute()`는 수락 여부만 즉시 반환하고, 이후 상태·결과는 별도
콜백/폴링으로 `CommandExecutionSupervisor`에 반영하는 방식으로 조정한다(계약
자체 시그니처는 지금 이대로 유지 — Protocol을 넓히면 다른 구현체가 다 깨진다).

### 2-3. 우리 → 가시화 (판단 결과)

`edge/object_evidence_fusion.py`의 `ObjectRecord`, `edge/self_localization.py`의
`NavigationPlan`이 최종 산출물이다. 가시화가 이걸 어떤 화면 컴포넌트로 그리든
우리 코드는 모른다 — 단, **필드 이름은 `contracts/data_dictionary.py`가 정본**
이므로 가시화 쪽이 새 이름을 즉흥적으로 쓰면 안 되고, 필요한 이름이 사전에 없으면
먼저 등록을 요청해야 한다(AI-C-01).

**격차(khw_VZ 조사에서 확인, 조율 필요)**:
1. 탐지/객체 스키마가 가시화의 정식 `contracts/*.schema.json` 계층에 없고
   `viz-debugger/src/detect/types.ts`라는 프론트 전용 코드에만 있다 — 우리
   `data_dictionary.py`의 이름과 다시 어긋날 위험이 항상 있다. **병합 시 이
   TS 타입을 지우고 우리 이름으로 다시 맞추는 작업이 필요**하다(반대로 우리가
   그쪽 이름에 맞추지 않는다 — 정본은 데이터 사전이다).
2. 우리 로컬 cm 좌표(`robot_position_cm` 등)와 디지털트윈의 `places/` 월드 좌표(m)
   사이 매핑이 없다 — `COORDINATE_FRAME`(IMAGE/CAMERA_LOCAL/ZONE/GLOBAL) 중
   우리는 ZONE까지만 내고 GLOBAL 승격은 백엔드 소관이라는 원칙(AI-C-02, AI-C-19)은
   이미 데이터 사전에 있으므로, 가시화/백엔드가 이 승격 단계를 구현하면 된다 —
   우리 쪽 추가 작업 없음.
3. `command_id`/`mission_id` 같은 상관식별자가 지금 가시화 폴링 경로에 없다 —
   `contracts/data_dictionary.py::CORRELATION_ID`가 이미 있으므로 가시화가 이
   이름으로 실어 보내기만 하면 된다(우리 쪽엔 이미 있음, 저쪽에 없음).

## 3. 결론 — 우리 쪽에서 지금 바꿔야 하는 코드는 없다

이번 검토로 확인된 격차 4가지(HW의 얇은 Capability 선언, 물리명령 파라미터
타입 제약, 가시화의 비공식 타입 정의, 좌표계/상관식별자 매핑)는 **전부 HW·가시화
쪽에서 채우거나, 우리 쪽이 이미 가진 보강 책임(AI-C-10)으로 흡수되는 것**이다.
`perception-framework`의 provider/capability/data_dictionary 구조 자체를 바꿀
필요는 없다 — 이 구조가 이미 "구체 기술을 모르는 채로 등록만으로 확장"을
만족하기 때문이다(절대 준수 원칙 #1, #7). 다음에 실제 두 브랜치를 이 저장소
옆에 붙일 때는 이 문서의 §2-1~2-3에 적은 어댑터/등록 작업만 하면 된다.
