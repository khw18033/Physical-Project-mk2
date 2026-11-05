# 물리 명령 통신 규약 (Interface Specification)

이 문서는 정해진 토픽에 정해진 형식의 메시지를 주고받기 위한 규약이다. 여기 적힌 형식과
규칙만 만족하면 되고, 내부에서 어떻게 만들고 처리하는지는 언어·SDK·구조 무엇이든 무관하다.

---

## 1. 개요

- **전송 계층**: MQTT (버전 5 권장, 3.1.1도 가능)
- **인코딩**: Protobuf(**package `physical`**)를 기본으로 한다. 와이어 정본은 HW 파트의
  `hardware/schema/physical_command.proto` 한 벌이며, 이 저장소는 생성용 사본
  (`mission_runtime/contracts/proto/physical_command.proto`)만
  둔다 — 그 사본에서 생성한 descriptor 바이트가 정본에서 생성한 것과 **같다는 것을**
  회귀 테스트가 고정한다. 사람이 읽는 JSON 표현은
  `schemas/ai/physical-command.schema.json` 에 있고 디버깅용이다.
  2026-09-19에 필드번호·enum 값·oneof 슬롯을 HW 정본과 맞췄고, 2026-11-02에
  `Command.traceparent = 6`(§8-3 P1의 해소)을 받아들였다. 아직 못 싣는 것은 §8에 적는다.
- **메시지 봉투**: 실제로 어떤 메시지인지는 `PhysicalCommandEnvelope`(`.proto` 참고)의
  `oneof body`가 결정한다. 토픽 이름 자체에는 "무슨 내용인지"를 담지 않는다 — 방향(누가
  누구에게 보내는지)만 담는다. 이렇게 나눈 이유는 §2 끝에 적어둔다.

## 2. 토픽 규칙

로봇/장치 하나당 토픽 2개를 쓴다. `<device-id>`는 장치별 고유 식별자로 대체한다.

| 토픽 | 방향 | 실어 나르는 것 |
|---|---|---|
| `terminal/<device-id>/downlink` | 엣지 → 장치 | `Command`, `CancelCommandRequest` |
| `terminal/<device-id>/uplink` | 장치 → 엣지 | `CommandAcceptance`, `CommandStatus`, `CommandResult`, `CancelCommandResponse`, `Capability` |

두 토픽 모두 payload는 `PhysicalCommandEnvelope`를 직렬화한 바이트다. 어떤 메시지가 왔는지는
장치/엣지 각자가 이 봉투를 역직렬화해서 `oneof` 필드로 판단한다.

**왜 메시지 종류별로 토픽을 나누지 않았는가.** 이미 봉투가 종류를 구분해주는데 토픽 이름에서도
구분하면 같은 정보를 두 곳에 유지하는 셈이라 나중에 어긋날 위험이 생긴다. 그리고 토픽을
방향으로만 나누면 "이 장치는 자기 uplink에만 쓸 수 있다" 같은 접근 권한 규칙이 자연스럽게
따라온다.

**생사 신호(장치가 살아있는지)는 이 봉투에 넣지 않는다.** MQTT의 Last Will and Testament(LWT)를
연결 시점에 등록해서 쓴다 — 장치가 전원이 나가거나 네트워크가 끊겨 아무것도 보낼 수 없는
상황에도 감지되어야 하기 때문에, "장치가 스스로 보내는 메시지"로는 이 목적을 만족할 수 없다.

## 3. 메시지 형식

정확한 필드와 타입은 위 §1의 정본 `.proto`(또는 같은 내용의 JSON 표현)를
기준으로 삼는다. 아래는 각 메시지가 언제 쓰이는지에 대한 요약이다.

| 메시지 | 보내는 쪽 | 언제 |
|---|---|---|
| `Command` | 엣지 | 새 명령을 내릴 때. `command_id`(재전송 식별용 고유값), `target`, `action`, `parameters`, 선택적 `deadline` 포함 |
| `CommandAcceptance` | 장치 | `Command`를 받은 직후, 수락/거부를 즉시 응답할 때. 거부 시 `rejection.code`/`message` 포함 |
| `CommandStatus` | 장치 | (선택) 실행 중 상태를 중간에 알리고 싶을 때 |
| `CommandResult` | 장치 | 명령이 최종적으로 끝났을 때(성공/실패/취소 중 하나로 확정된 뒤) |
| `CancelCommandRequest` | 엣지 | 이미 보낸 명령을 취소하고 싶을 때. `command_id`만 포함 |
| `CancelCommandResponse` | 장치 | 취소 요청을 받았을 때 즉시 응답. **아직 실제로 멈췄다는 뜻이 아니다** — §4, §6 참고 |
| `Capability` | 장치 | 이 장치가 지원하는 action을 알릴 때(최초 연결 시, 또는 지원 목록이 바뀔 때) |

`Rejection`/`Failure`의 `code`는 자유 문자열이지만 `INVALID_ARGUMENT`, `FAILED_PRECONDITION`,
`UNIMPLEMENTED`, `PERMISSION_DENIED`, `RESOURCE_EXHAUSTED`, `ALREADY_EXISTS` 중 맞는 게 있으면
그걸 쓴다(gRPC 상태 코드 관례를 참고했다 — 새로운 오류 분류 체계를 또 만들지 않기 위해서다).

## 4. 상태 그림 (의미 계약)

```text
Command 도착
    │
    ├─ 거부 ──────────────► CommandAcceptance{accepted:false, rejection:...}
    │                        (여기서 끝. 아래 상태 그림에 들어가지 않는다)
    ▼
CommandAcceptance{accepted:true}
    │
    ▼
ACCEPTED
    │
    ▼
EXECUTING
    │
    ├────────────────────────────► SUCCEEDED / ABORTED   (CommandResult로 보고)
    │
    └─ CancelCommandRequest 도착
          │
          ▼
      CancelCommandResponse{accepted:true}   ← "취소 절차 진입"을 수락한 것.
          │                                     아직 실제로 멈췄다는 뜻 아님.
          ▼
      CANCELING
          │
          ▼
      CANCELED   (CommandResult로 보고)
```

- `REJECTED`는 상태가 아니다 — `CommandAcceptance.accepted = false`로만 표현하고, 이후
  `CommandResult`를 보낼 필요가 없다(애초에 시작되지 않았으므로).
- `CommandResult.status`는 반드시 종료 상태(`SUCCEEDED`/`ABORTED`/`CANCELED`) 중 하나여야
  한다. `ACCEPTED`/`EXECUTING`/`CANCELING`으로 `CommandResult`를 보내지 않는다(그 상태를
  보고하고 싶으면 `CommandStatus`를 쓴다).

## 5. 반드시 지켜야 할 행동 규칙

메시지 형식만 맞춰도 통신은 되지만, 아래 4가지를 지키지 않으면 실제 운영에서 사고가 난다.
내부 구현 방식은 자유이되, 아래 결과는 반드시 만족해야 한다.

1. **같은 `command_id`가 다시 오면 물리 동작을 다시 실행하지 않는다.** 이전에 보냈던
   `CommandAcceptance`/`CommandResult`를 그대로 다시 보낸다. (같은 `command_id`인데 내용이
   다르면 — 즉 `target`/`action`/`parameters`가 다르면 — `ALREADY_EXISTS`로 거부한다.)
2. **`deadline`이 지난 뒤에는 새로 시작하지 않는다.** 수신 시각이 `deadline`을 넘었으면 바로
   `FAILED_PRECONDITION`으로 거부한다.
3. **취소가 완료보다 우선한다.** `CancelCommandRequest`를 받아들인 뒤에는, 설령 동작이 마침
   그때 성공적으로 끝났더라도 최종 `CommandResult.status`는 `SUCCEEDED`가 아니라 `CANCELED`로
   보고한다.
4. **선언하지 않은 action은 실행을 시도하지 않는다.** `Capability`로 알린 적 없는 `action`이
   오면 `execute` 로직에 들어가기 전에 `UNIMPLEMENTED`로 거부한다.

## 6. 예시 흐름

`E`= 엣지가 보냄, `D`= 장치가 보냄. 실제 필드는 일부만 표시했다.

**(a) 정상 성공**

```text
E → downlink : Command{command_id=c-1, target=robot1, action=navigate.relative,
                        parameters={distance:1.0}, deadline=t+30s}
D → uplink   : CommandAcceptance{command_id=c-1, accepted=true}
      ... (실제 이동 수행) ...
D → uplink   : CommandResult{command_id=c-1, status=SUCCEEDED, result={distance_moved:1.0}}
```

**(b) 거부**

```text
E → downlink : Command{command_id=c-2, target=robot1, action=fly, parameters={}}
D → uplink   : CommandAcceptance{command_id=c-2, accepted=false,
                                  rejection={code:UNIMPLEMENTED, message:"action not supported"}}
      (CommandResult 없음 — 애초에 시작되지 않았으므로)
```

**(c) 취소**

```text
E → downlink : Command{command_id=c-3, target=robot1, action=navigate.relative, ...}
D → uplink   : CommandAcceptance{command_id=c-3, accepted=true}
      ... (실행 중) ...
E → downlink : CancelCommandRequest{command_id=c-3}
D → uplink   : CancelCommandResponse{command_id=c-3, accepted=true}
      ... (정지 동작 수행) ...
D → uplink   : CommandResult{command_id=c-3, status=CANCELED}
```

**(d) 네트워크 재시도로 같은 명령이 두 번 도착**

```text
E → downlink : Command{command_id=c-4, target=robot1, action=navigate.relative, ...}
      (엣지가 CommandAcceptance를 못 받음 — 응답 유실인지 명령 유실인지 엣지는 알 수 없음)
E → downlink : Command{command_id=c-4, ...}   ← 동일 내용으로 재전송
D → uplink   : CommandAcceptance{command_id=c-4, accepted=true}
      ← 장치는 c-4를 이미 처리했다는 걸 알고 있으므로, 물리 동작을 다시 하지 않고
        처음 만들었던 응답을 그대로 다시 보낸다(§5-1).
```

## 7. 안전 관련 원칙

**긴급정지(E-stop)는 `CancelCommandRequest`와 다른 별도 경로여야 한다.** 이 문서의 취소
규약은 정상 업무 명령을 취소하는 절차이지, 안전 기능이 아니다. 네트워크로 오는
`CancelCommandRequest` 하나에만 의존해서 장치의 비상정지를 구현하지 않는다 — 네트워크
자체가 끊기거나 지연되는 상황에서도 동작해야 하는 안전 기능은 이 통신 경로와 독립적으로
장치 자체에 있어야 한다.

---

## 8. 와이어 정렬 (2026-09-19)

### 8-1. 무엇을 맞췄나

이 저장소에는 같은 메시지 이름을 쓰면서 **인코딩이 다른** `.proto`가 두 벌 있었다.
우리 쪽(`package physical_project.ai.v1`)과 HW 파트 쪽(`package physical`)이다. 가시화
파트의 `viz-debugger/src/physical/protocol.js`가 이미 HW 쪽 번호로 인코딩하고 있었으므로
**실제 배포된 인코딩은 HW 쪽**이었고, 2026-09-19 결정에 따라 우리가 그쪽에 맞췄다.

가장 위험했던 것은 enum이다. 정렬 전 우리 `ExecutionStatus`는 진행·종료를 한 enum으로
표현했고 그 **값 1이 `ACCEPTED`**, HW `TerminalStatus`의 **값 1은 `SUCCEEDED`**였다.
같은 바이트가 한쪽에서는 "수락했다", 다른 쪽에서는 "성공했다"로 읽힌다 — 오류 없이
조용히 뒤바뀐다. §4가 수락과 완료를 구분하라고 못 박은 바로 그 지점이었다.

| 자리 | 정렬 전(우리) | 지금(= HW·VZ) |
|---|---|---|
| package | `physical_project.ai.v1` | `physical` |
| Envelope oneof | acceptance=2, result=3, cancel_request=5 | cancel_request=2, acceptance=3, result=5 |
| 진행 상태 | `ExecutionStatus` enum(ACCEPTED=1…) | `CommandStatus.state` **문자열**(ACCEPTED/EXECUTING/CANCELING) |
| 종료 상태 | 같은 enum(SUCCEEDED=4, ABORTED=5, CANCELED=6) | `TerminalStatus` enum(SUCCEEDED=1, ABORTED=2, CANCELED=3) |
| `Command` 필드 5 | `correlation_id`(string) | `deadline_unix_ms`(int64) |
| `Command.parameters` | `google.protobuf.Struct` | `map<string,double>` |
| `CommandAcceptance` 필드 3 | `accepted_at`(double) | `rejection`(message) |
| `CommandResult` 필드 3·4 | `completed_at`, `result`(Struct) | `result`(map), `failure` |
| `CancelCommandResponse` 필드 3 | `reason`(string) | 없음 |
| `Capability` | name/version/schema/cancel_supported/required_resources (2026-11-04: + idempotent/invocation/basis/scope_tags/optional_resources/execution_profile_ref, cancel_supported 는 3값) | device_id/actions[] |

생성된 descriptor 바이트가 HW가 배포 중인 `pi/common/physical_command_pb2.py`의 것과
**완전히 동일함**을 확인했다(1330바이트 일치). 회귀는 `tests/test_physical_command_wire_alignment.py`가
번호와 바이트로 고정한다 — 우리 코드끼리의 왕복 시험은 양쪽이 같이 틀려 있어도 통과하므로
그것만으로는 이 사고를 못 잡는다.

### 8-2. §4 의미 계약은 그대로 유지된다

정렬 후에도 §4가 요구하는 구분은 전부 표현된다. 오히려 HW 와이어는 진행 상태(문자열)와
종료 상태(enum)를 **타입으로** 갈라 두었기 때문에 "완료를 진행 상태로 보고"하는 실수가
형식 수준에서 막힌다.

| §4가 요구하는 구분 | 정렬 후 표현 |
|---|---|
| 전달 ≠ 수락 | 전달은 MQTT 계층, 수락은 `CommandAcceptance` |
| 거부는 상태가 아니다 | `CommandAcceptance.accepted=false` + `rejection`. `TerminalStatus`에 REJECTED가 없다 |
| 진행 상태 | `CommandStatus.state` = ACCEPTED / EXECUTING / CANCELING |
| 종료 결과 | `CommandResult.status` = SUCCEEDED / ABORTED / CANCELED |
| 취소 수락 ≠ CANCELED 도달 | `CancelCommandResponse.accepted=true`(절차 진입)와 `CommandResult.status=CANCELED`(도달)는 **다른 메시지** |
| 같은 command_id 재실행 금지 | 모든 메시지가 `command_id`를 싣는다 |
| 긴급정지는 별도 경로 | §7 그대로 — 이 규약은 관여하지 않는다 |

### 8-3. 아직 못 싣는 것 — HW와 협의해야 하는 목록

아래는 우리 의미 계약에는 있으나 지금 와이어에 자리가 없는 정보다. **임의로 필드번호를
쓰지 않는다** — 우리가 마음대로 번호를 쓰면 HW가 나중에 같은 번호를 다른 뜻으로 쓸 때
이번 사고가 그대로 재발한다. 제안 번호만 적고 합의 전에는 사용하지 않는다.

| # | 잃은 정보 | 왜 필요한가 | 제안 |
|---|---|---|---|
| ~~P1~~ | ~~`Command.correlation_id`~~ | **해소(2026-11-02)** — HW가 번호 6을 `traceparent`로 정했다. 기술 추적 연결은 이 칸으로 간다 | `string traceparent = 6` — 적용됨 |
| P2 | 숫자가 아닌 `parameters`/`result` | `map<string,double>`이라 문자열·불리언·중첩 불가. HW도 이 제약 때문에 `assign_mission`을 못 쓰고 action 이름 자체를 어휘로 쓰는 우회를 택했다(HW README §7의 "우선순위 높음" 협의 항목) | `map<string,string> parameters_text = 7` / `result_text = 5`, 또는 공용 Value 타입 |
| P3 | `CommandAcceptance.accepted_at` | 장치가 **수락한 시각**. 지금은 엣지 수신 시각으로 대체된다 | `double accepted_at = 4` |
| P4 | `CommandStatus.observed_at` | 상태 관측 시각(AI-C-03) | `double observed_at = 4` |
| P5 | `CommandResult.completed_at` | 장치가 **끝낸 시각**. 지연 분석과 재현(AI-O-03)에 필요 | `double completed_at = 5` |
| P6 | `CancelCommandResponse.reason` | 취소 거부 사유. 지금은 accepted=false만 오고 이유를 모른다 | `string reason = 3`(현재 미사용 번호) |
| P7 | `Capability`의 선언 항목 전부 | AI-C-18이 요구하는 입출력 schema·단위·좌표·시간 기준·취소 가능 여부·멱등성·동기/비동기·버전·품질/지연/자원 중 **하나도 못 싣는다.** 지금 오는 것은 action 이름 목록뿐 | 별도 `CapabilityDetail` 메시지(봉투 슬롯 8) 또는 `Capability`에 `repeated ActionDetail details = 3` |

**시각 3종(P3·P4·P5)의 현재 처리**: 와이어에 없으므로 `decode()`가 **엣지 수신 시각**으로
채우고 `time_source="edge_receipt"`를 함께 넣는다. 장치가 그 동작을 실제로 한 시각이
아니라는 뜻이다. 없는 값을 장치 보고인 척 넣지 않기 위한 표시다.

**P2의 현재 처리**: 숫자가 아닌 값은 **보내기 전에 거부한다**(`ValueError`). 조용히
떨어뜨리면 장치가 받는 명령의 의미가 달라지기 때문이다. 결측(`None`)은 0으로 채우지 않고
키를 아예 넣지 않는다.

**P6·P7의 현재 처리**: 버릴 때마다 직렬화기의 `wire_gaps` 카운터에 남는다. 관측
경로로 흘려보내면(`on_gap`) 운영 중에도 무엇이 잘려 나가는지 볼 수 있다.

**P7의 2026-11-04 보강 — 우리 쪽에서 할 수 있는 몫은 끝냈다.** 와이어가 넓어지는
것은 여전히 협의 대상이지만, 그때까지 우리 쪽이 하던 처리에 **두 가지 구멍**이
있었고 그것은 우리 몫이었다.

1. **담을 칸이 없던 항목들.** 단위·좌표·시간 기준 / 멱등성 / 동기·비동기 /
   수행·관측 범위 / 선택 실행 조건은 `Capability` 에 자리가 아예 없었다. 와이어가
   넓어져도 받을 곳이 없었다는 뜻이고, 그러면 "와이어가 못 싣는 것"과 "우리가 못
   받는 것"이 구분되지 않는다. 지금은 `contracts/physical_command.py::Capability`
   가 AI-C-18 항목 전부에 칸을 가지고, 일반 구성요소 선언
   (`contracts/capability_contract.py`)으로 **손실 없이** 옮겨진다
   (`to_declaration()`).
2. **"모른다"가 "안 된다"로 접혀 있었다.** `cancel_supported` 가 `bool = False`
   여서, 아무도 선언하지 않은 장치와 **취소를 지원하지 않는다고 선언한** 장치가
   같은 값이었다. 이 와이어는 그 항목을 싣지 못하므로 **들어오는 모든 선언이**
   그 거짓에 걸려 있었다 — 상위 기능이 보기에 모든 장치가 "취소를 거부하는
   장치"였다. 지금은 세 값(True/False/None)이고, §4가 구분하라고 못 박은 취소
   수락 ≠ CANCELED 도달이 그 선언 위에 선다.

그래서 지금 이 와이어로 온 선언의 처리는 이렇다.

| 무엇 | 어디에 |
|---|---|
| 선언 항목이 비어 있다는 사실 | `undeclared_items()` 가 **항목 이름으로** 돌려준다. 디코드된 payload 에도 `undeclared_items` 로 실린다 |
| 그 수 | 항목마다 따로 센다 — `wire_gaps["capability.undeclared.<item>"]` |
| 선언된 값을 버릴 때 | 전과 같이 `wire_gaps["capability.<field>"]`. `False` 와 빈 묶음도 **선언된 값이므로 센다**(미선언만 세지 않는다) |
| 선택에서 | `CapabilityRegistry.providers_declaring()` 이 "그렇다고 선언한 것"과 "아무도 선언하지 않은 것"을 **다른 묶음으로** 돌려준다. 미선언을 거부로 접지도, 충족으로 세지도 않는다 |
| 조인에서 | `JoinOutcome.under_declared_actions` 에 action 별로 적힌다. 덜 찬 선언은 조인을 막지 않는다 |

**와이어가 넓어질 때 필요한 것(변경 없음).** 아래 이름으로 오면 우리 쪽은 코드
변경 없이 받는다 — `Capability` 에 그 칸이 이미 있다.

| 필요한 필드 | 우리 칸 | 모르면 |
|---|---|---|
| `bool cancel_supported` (optional 로, **presence 가 필요하다**) | `cancel_supported` | **보내지 않는다.** `false` 로 채우면 미선언과 "취소 불가" 가 같아진다 |
| `bool idempotent` (같은 이유로 optional) | `idempotent` | 보내지 않는다 |
| `string invocation` (`synchronous`/`asynchronous`) | `invocation` | 빈 문자열로 보내지 않는다 |
| `string parameter_schema` · `result_schema` · `version` | 같은 이름 | 보내지 않는다 |
| `map<string,string> units` · `string reference_frame` · `string time_basis` | `basis` | 객체를 **만들지 않는다**(빈 객체는 "기준을 선언했다" 가 된다) |
| `Scope { repeated string tags }` — **중첩 메시지로** | `scope_tags` | 메시지를 보내지 않는다. proto3 의 `repeated` 는 presence 가 없어 빈 목록과 미선언이 같아지므로, "범위 제약 없음"(빈 목록)을 선언하려면 포장이 필요하다 |
| `repeated string required_resources` · `optional_resources` | 같은 이름 | — |
| `string execution_profile_ref` | `execution_profile_ref` | 실측 숫자를 이 메시지에 싣지 않는다. 숫자의 주인은 AI-B-01 의 `ExecutionProfile` 이다 |

proto3 에서 스칼라의 presence 는 `optional` 키워드가 주고, 그것이 없으면 "false 를
보냈다"와 "안 보냈다"가 와이어에서 같아진다. `repeated`·`map` 은 `optional` 을 붙일
수 없으므로 빈 것과 미선언을 갈라야 하는 자리는 중첩 메시지로 포장한다(메시지 필드는
presence 가 있다). P7 의 핵심이 이 구분이므로 **필드 번호보다 이 점이 먼저다** — 번호만
맞추고 presence 를 빼면 이번에 고친 "모른다 ≠ 안 된다"가 와이어에서 다시 사라진다.

**P1(해소)의 현재 처리**: `correlation_id`가 **유효한 W3C traceparent일 때만**
`Command.traceparent`에 싣고, 형식이 아니면 싣지 않고 `wire_gaps`에 남긴다. 아무 문자열이나
넣지 않는 이유는 받는 쪽이 이 칸으로 trace를 잇기 때문이다 — 형식이 틀리면 거부도 없이
trace 조립만 조용히 깨진다. 받을 때는 비어 있지 않은 `traceparent`만 `correlation_id`로
올린다(빈 문자열을 상관 ID로 만들지 않는다).

### 8-4. 정렬 이전 바이트는 어떻게 되나

**다시 읽으면 안 된다.** 옛 봉투는 acceptance를 슬롯 2에 실었는데 지금 슬롯 2는
`CancelCommandRequest`다. 즉 옛 바이트는 **오류 없이 다른 메시지로 읽힌다** — 수락이
취소요청으로 보인다.

다만 이 저장소 안에서 옛 인코딩의 소비자는 테스트뿐이었다. 데모 경로의
`_send_to_device()`는 실제 전송을 하지 않고(주석 처리 상태), 저장된 protobuf 캡처도
찾지 못했다. 그래도 누군가의 로컬에 캡처가 남아 있다면 옛 `.proto`(git 이력)로만 읽고
새 코드로 파싱하지 않는다 — 파싱이 **성공하면서 틀리기** 때문이다.
