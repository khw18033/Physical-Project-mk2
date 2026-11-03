# 인터페이스 규약 (interface-spec)

파트 경계를 넘나드는 통신에 쓰이는 규약 문서를 모아두는 곳이다. 코드가 아니라
**"어떤 형식의 메시지를, 어떤 규칙으로 주고받는가"만 고정한 문서**이며, 하드웨어·백엔드·
가시화 등 어느 파트가 어느 쪽을 구현하든 이 문서 하나만 보고 맞춰 구현하면 통신이
성립하도록 하는 것이 목적이다. 내부 구현(언어, SDK, 코드 구조)은 각 파트 재량이다.

```text
spec/     규약 문서 — 파트별로 실제로 지켜야 할 내용
```

## 메시지 형식은 여기 두지 않는다 (2026-11-02)

`schema/` 에 있던 `physical_command.proto` 와 `physical-command.schema.json` 을
지웠다. 같은 내용의 사본이 세 곳에 있었고, 사본은 언젠가 서로 어긋난다 —
2026-09 에 oneof 번호가 어긋나 로봇이 취소 요청을 완료 보고로 읽을 수 있었던 사고가
그 사본들 사이에서 났다. 통합 저장소도 같은 결론을 내렸다(PR #38).

| 무엇 | 어디 |
|---|---|
| 와이어 정본(Protobuf) | HW 파트 `hardware/schema/physical_command.proto` |
| 이 저장소의 생성용 사본 | `mission_runtime/contracts/proto/physical_command.proto` — 정본과 **필드 단위로 같고** 생성된 descriptor 바이트가 정본과 일치한다(`tests/test_physical_command_wire_alignment.py` 가 고정) |
| 사람이 읽는 JSON 표현(디버깅용) | `schemas/ai/physical-command.schema.json` |

## 지금 있는 규약

| 문서 | 대상 경계 | 무엇을 정하는가 |
|---|---|---|
| [`spec/physical-command-interface.md`](spec/physical-command-interface.md) | 엣지 ↔ 로봇/온디바이스 | 물리 명령 전송 토픽, 메시지 형식, 상태 그림, 재전송·취소·마감시각 규칙 |

새 파트 경계 규약이 필요하면 이 디렉터리에 문서를 추가한다 — 형식은 위 문서를 따른다
(무엇을 주고받는가만 정의하고, 어떻게 내부적으로 처리하는지는 다루지 않는다).
