# 물리 명령 통신 규약 (Interface Specification)

이 문서는 정해진 토픽에 정해진 형식의 메시지를 주고받기 위한 규약이다. 여기 적힌 형식과
규칙만 만족하면 되고, 내부에서 어떻게 만들고 처리하는지는 언어·SDK·구조 무엇이든 무관하다.

---

## 1. 개요

- **전송 계층**: MQTT (버전 5 권장, 3.1.1도 가능)
- **인코딩**: Protobuf(`schema/physical_command.proto`)를 기본으로 한다. 디버깅·로그 확인용으로
  같은 내용을 JSON으로 표현한 `schema/physical-command.schema.json`도 함께 제공한다 — 다만
  실제 통신의 정본(source of truth)은 Protobuf 쪽이다.
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

정확한 필드와 타입은 `schema/physical_command.proto`(또는 `schema/physical-command.schema.json`)를
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
