# HW ↔ 백엔드 인터페이스 조율 정리 — 물리 명령 통신 규약

> 대상: 백엔드 확정 「물리 명령 통신 규약(Interface Specification)」 (MQTT5 + Protobuf)
> 담당: HW 파트 · 갱신: 2026-09-03 · 브랜치: `HW`
> 관련 커밋: `329ccdb`(구현·검증·배포), `538cbb4`(진행 로그)

이 폴더는 규약을 HW 말단 노드에 맞춰 조율한 결과를 한곳에 모은 것이다.
"무엇을 어떻게 지켰는가"를 **근거 코드 라인**과 **실측 검증**으로 남긴다.

---

## 1. 결론 요약

- 규약의 미준수 항목(형식·행동 규칙)을 **전부 해소**했다.
- 기존 레거시 JSON 명령 엔진은 **그대로 두고**, 규약을 지키는 **새 경로를 정본으로 병행 신설**했다.
- 로컬 → 온디바이스 → **라이브 브로커 E2E** 3단계로 검증했다.
- pi1(`sensor-node.service`)에 배포되어 부팅 시 `terminal/<id>/downlink` 구독 + Capability 발행이 동작한다.

핵심 파일:

| 역할 | 경로 |
|---|---|
| 규약 스키마(정본) | `schema/physical_command.proto` |
| 컴파일 산출 | `pi/common/physical_command_pb2.py` |
| 규약 서버 | `pi/common/physical_command.py` (`PhysicalCommandServer`) |
| 노드 연동 | `pi/common/node.py` (레거시와 병행) |
| 검증 | `pi/bench/physical_command_test.py`, `pi/bench/physical_command_node_test.py` |

---

## 2. 규약 요지 (우리가 지켜야 하는 것)

- **전송**: MQTT 5. payload = `PhysicalCommandEnvelope`(Protobuf) 직렬화 바이트.
- **토픽**: `terminal/<device-id>/downlink`(엣지→장치), `terminal/<device-id>/uplink`(장치→엣지).
  토픽에는 **방향만**, 메시지 종류는 봉투 `oneof body` 가 결정.
- **생사(liveness)**: MQTT LWT — 봉투에 넣지 않는다(연결 계층에서 등록).
- **E-stop**: 이 통신 경로와 **독립**(장치 자체 안전장치).
- **행동 규칙(§5)**: 멱등, deadline 거부, 취소 우선, 미선언 거부 — 형식이 아니라 **결과**로 보장.
- **상태 코드**: gRPC 관례(`INVALID_ARGUMENT`/`FAILED_PRECONDITION`/`UNIMPLEMENTED`/`ALREADY_EXISTS` …).

---

## 3. 준수 대조표 (근거 라인 포함)

### §5 행동 규칙 (안전 직결)

| 규칙 | 규약 | 조율 전 | 조율 후 | 근거 (`pi/common/physical_command.py`) |
|---|---|---|---|---|
| ① 멱등(재실행 금지 + 이전 응답 재송신) | 필수 | ✅ | ✅ | `seen[cid]` + `_send_bytes` 재송신 (156~161) |
| ① 같은 id·다른 내용 → `ALREADY_EXISTS` | 필수 | ❌ 내용 비교 없음 | **✅** | `_sig()` 비교 → 거부 (167~171) |
| ② deadline 경과 거부 | `FAILED_PRECONDITION` | ◐ 코드명 `expired` | **✅** | 코드명 정확 (181~183) |
| ③ 취소 우선(취소 후 성공해도 `CANCELED`) | 필수 | ❌ 미구현 | **✅** | `entry["canceled"]`→`TS.CANCELED` (228, 256) |
| ④ 미선언 action 거부 | `UNIMPLEMENTED` | ◐ 코드명 `unsupported_action` | **✅** | 코드명 정확 (188) |
| §7 E-stop 별도 경로 | 통신과 독립 | ✅ | ✅ | SDK 하드리밋 + 데몬 워치독(무입력 0.4s 정지), 규약 경로 밖 |

### §1~3 와이어 형식

| 항목 | 규약 | 조율 전 | 조율 후 | 근거 |
|---|---|---|---|---|
| 전송 | MQTT 5 | ✅ | ✅ | — |
| 인코딩 | Protobuf | ❌ JSON | **✅** | `SerializeToString()` / pb2 |
| 봉투 | `PhysicalCommandEnvelope` oneof | ❌ JSON channel | **✅** | `schema/physical_command.proto` 8~18 |
| 토픽 | `terminal/<id>/downlink·uplink` (방향만) | ❌ 종류별 토픽 | **✅** | `physical_command.py` 75~76 |
| 메시지 | Command/Cancel±/Acceptance/Status/Result/Capability | ◐ 4단계 stage | **✅** | proto 9~17 |
| 종료 상태값 | `SUCCEEDED/ABORTED/CANCELED` | ❌ completed/failed | **✅** | proto 22~25 |
| Capability 발행 | 필수 | ❌ 미발행 | **✅** | `start()`→`publish_capability()` 81~87 |
| 취소 | `CancelCommandRequest/Response` 별도 | ◐ 일반 action | **✅** | proto 36, 67 |

---

## 4. 조율 방식 — 왜 "병행"인가

레거시 명령 엔진(`pi/common/commands.py`, JSON·종류별 토픽·4단계 stage)은 이미 다른 소비자와
관측 파이프라인이 물려 있다. 이를 한 번에 걷어내면 기존 기능이 끊긴다. 그래서:

- 규약 서버를 **별도 토픽 네임스페이스**(`terminal/<id>/…`)로 신설해 레거시(`{zone}/{type}/{id}/cmd…`)와 충돌 없이 공존.
- `pi/common/node.py` 가 수신 토픽으로 라우팅: downlink → 규약 서버, `{base}/cmd` → 레거시.
- 명령 어휘(`owner.ACTIONS`)·검증(`owner.validate`)은 **양쪽이 그대로 공유** — 규약 서버가
  레거시 owner 인터페이스를 재사용(예외는 duck-type 으로 흡수해 `CommandError` 클래스 차이 무해화).
- publish/subscribe 는 어댑터로 주입 → 재접속으로 MQTT client 가 갈려도 항상 현재 것을 사용.

> 결과: 규약 준수는 **새 경로가 정본**으로 담당하고, 레거시는 하위호환으로 유지된다.

---

## 5. 검증 (3단계)

1. **로컬 벤치** (`bench/physical_command_test.py`)
   §6 예시 흐름 전부 + §5 규칙 전부. 실제 Protobuf 직렬화/역직렬화로 바이트 수준 확인.
   - 6(a) 성공, 6(b) 미선언 거부, 6(c) 취소, 6(d) 재전송, ①ALREADY_EXISTS, ②deadline,
     ③취소 우선, ④UNIMPLEMENTED, Capability, uplink 방향 규칙 → **전부 통과**.
   - 노드 연동 (`bench/physical_command_node_test.py`): 규약/레거시 병행 + 재접속 안전 → **통과**.

2. **온디바이스** (pi1, protobuf 7.36.1 / Python 3.13 / aarch64)
   위 두 벤치 동일 실행 → **전부 통과**.

3. **라이브 브로커 E2E** (pi1 → 192.168.50.244)
   실제 downlink 로 Protobuf Command 발행, uplink 관찰:
   - `ping` → `acceptance{accepted=true}` → `status(EXECUTING)`×2 → `result{SUCCEEDED, uptime_s}`
   - `teleport`(미선언) → `acceptance{accepted=false, UNIMPLEMENTED}`, result 없음
   → 규약대로 동작 **확인**.

재현:

```bash
# 로컬/온디바이스 (pi/ 디렉터리)
python -m bench.physical_command_test
python -m bench.physical_command_node_test
```

---

## 6. 배포 상태 & 부수 조치

- pi1: 코드 `~/hw/pi`, venv `~/venv`(protobuf·paho 포함), 서비스 `sensor-node.service`(entity `wl-001`).
- **부수 발견**: SD 재구축 후 유닛의 `WorkingDirectory` 가 옛 경로(`~/Physical-Project-mk2/pi`)를 가리켜
  `200/CHDIR` 로 크래시루프(1848회) 중이었다. `/home/physical/hw/pi` 로 교정 → 노드 `active` 복구.
  그 위에서 규약 검증을 진행했다.

---

## 7. 백엔드와 확인/합의가 필요한 사항

1. **레거시 경로 존치 여부** — 규약 정본 경로는 완비됐고, 레거시 JSON `cmd` 경로는 하위호환으로 병행 중.
   백엔드가 규약 경로만 사용한다면 레거시를 단계적으로 폐기할 수 있다. (요청 시 정리)
2. **device-id ↔ target 규칙** — 현재 `terminal/<device-id>` 의 device-id 는 노드 `entity_id`(예 `wl-001`)를 사용.
   `Command.target` 과 device-id 의 관계(동일/매핑) 확정 필요.
3. **parameters/result 타입** — 규약 `map<string,double>` 기준으로 구현. 문자열/열거형 파라미터가 필요하면 스키마 확장 협의.
4. **배포 경로 표준화** — 저장소 systemd 유닛 기본 경로가 실제 배치(`~/hw/pi`)와 달라 재구축 시 재발 소지. 표준화 대상.

---

## 8. 파일 색인

```
schema/physical_command.proto              규약 스키마(정본)
pi/common/physical_command_pb2.py          컴파일 산출
pi/common/physical_command.py              PhysicalCommandServer
pi/common/node.py                          노드 연동(레거시 병행)
pi/bench/physical_command_test.py          §5·§6 검증
pi/bench/physical_command_node_test.py     노드 연동·재접속 검증
```
