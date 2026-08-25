# 잔여 실 인프라 통합 보고 (Kafka·Bridge·OTel·K3s)

- 일시: 2026-08-25
- 범위: `docs/ai/02-infra-mock-plan.md` §3의 4~6번 (K3s, Kafka+Bridge, OpenTelemetry)
- 결과: **46/48 완료, 1 부분(AI-B-10), 1 보류(AI-C-01)**

## 1. 기동한 인프라

| 인프라 | 방식 | 상태 |
|---|---|---|
| MQTT | 기존 `eclipse-mosquitto:2` 컨테이너 (:1883) | 사용 |
| Kafka | `apache/kafka:3.9.0` KRaft 단일 노드 (:9092) — 신규 기동 | 사용 |
| OTel Collector | `otel/opentelemetry-collector-contrib` (:4317/:4318, file exporter) — 신규 기동 | 사용 |
| K3s | 기존 클러스터 (control-plane Ready) | 사용 |

## 2. 구현 내역

### AI-C-06 — Kafka + 엣지 양방향 Bridge

- `providers/kafka.py::KafkaTransportProvider` — MQTT provider와 **동일한 TransportProvider
  계약**. `kafka` 클라이언트 import는 이 파일에만 존재하며 정적 검사로 고정.
- `edge/bridge.py::EdgeTransportBridge` — 두 개의 `TransportProvider`만 알고 있어서
  코드상 "MQTT→Kafka" 컴포넌트가 아니라 "말단측 전송 ↔ 서버측 전송" 컴포넌트다.
  테스트가 fake 2개로도, 실제 mosquitto+Kafka 쌍으로도 동일하게 통과하는 것이 근거.
- 원칙 #11(엣지에 Kafka 서버 없음)이 배포 설정이 아니라 **코드 구조**로 표현됐다.
- 원칙 #17에 맞춰 `ReplayReference`(topic/partition/offset)는 단기 재현 포인터로만 정의.

**여기서 실제 결함 1건을 테스트가 잡았다.** 초기 bridge는 자신이 전달한 메시지를 반대편
구독에서 다시 받아 무한 루프를 돌았다(양쪽 모두 자기가 publish하는 토픽을 구독하므로 실제
브로커에서도 동일하게 발생). payload 지문 기반 echo 억제로 수정하고, 루프 회귀 테스트와
"동일 payload의 정당한 재전송은 계속 전달된다" 테스트를 함께 추가했다.

### AI-O-01/02 — 실 OpenTelemetry

- `providers/otel.py::OtlpObservabilityProvider` — metric은 OTLP metric 파이프라인,
  event는 **별도의 log 파이프라인**으로 내보낸다. 원칙 #14(장치 생사·치명 오류를 metric
  요약에 섞지 않는다)가 두 파이프라인 분리로 구현됐다.
- 이벤트는 내보내기 전에 로컬 버퍼에 먼저 남긴다 → 수집기가 죽어도 기록이 남는다(AI-O-02).
- 모든 내보내기 경로를 감싸 수집기 장애가 호출자에게 전파되지 않게 했다(AI-O-01).
- Collector의 file exporter 출력에 실행별 마커가 실제로 도착하는지까지 확인(e2e).

### AI-B-03/05/07 — K3s 제어 provider

- `providers/k3s.py::K3sControlProvider` — `LocalControlSupervisor`와 동일한
  ControlProvider 계약. 실 클러스터에 대해 생성·기동·중지·상태조회·rollout undo를 검증.
- 파이썬 k8s 클라이언트가 아니라 `kubectl` CLI를 사용한다. 배포를 전혀 하지 않을 수도 있는
  말단에 런타임 의존성을 추가하지 않기 위함이다(AI-B-10, 원칙 #12).
- 오케스트레이터 부재·거부는 예외가 아니라 `rejection_reason`으로 반환 → 호출자는
  standalone supervisor로 계속 간다(AI-B-05의 핵심 주장).
- 테스트는 클러스터에 남는 워크로드가 없도록 fixture에서 정리하며, 정리 확인까지 마쳤다.

## 3. 검증 결과

```
호스트(인프라 전부 기동) : 191 passed,  1 skipped   (skip = OpenCL 플랫폼)
최소 컨테이너            : 170 passed, 22 skipped   (skip = 선택 의존성·인프라 전부 부재)
```

**두 숫자의 차이가 AI-C-11의 증거다.** 선택 구성요소(MQTT/Kafka 클라이언트, 브로커,
Collector, 클러스터, OpenCL)가 하나도 없는 환경에서 170건이 그대로 통과한다.

이번에 추가된 정적 불변식 검사(총 6건):

- `paho` import는 `providers/mqtt.py`에만
- `from kafka import`는 `providers/kafka.py`에만
- `opentelemetry` import는 `providers/otel.py`에만
- `edge/bridge.py` 실행 코드에 `paho`/`kafka`/`mqtt` 토큰 부재
- 패키지 실행 코드에 GPU 벤더명 부재
- 패키지 실행 코드에 도메인 ID 부재

## 4. 남은 항목

| 항목 | 사유 |
|---|---|
| AI-C-01 데이터 사전 통일 | 의도적 보류 — §6-8이 "전체 기능 구현 후 일괄"로 규정. 이제 선행 조건이 갖춰졌으므로 다음 작업 후보 |
| AI-B-10 실물 말단 검증 | 엣지 집약 배치는 코드로 표현했으나 실물 보드 성능·발열은 하드웨어 필요 |
| AI-N-01 최소 처리주기 | 요구사항이 실측 시험으로 확정하도록 규정 |
| AI-C-10 백엔드 통합 가용성 | 백엔드 API 필요 (타 파트 산출물) |
| Intel OpenCL 활성화 | `intel-opencl-icd` 설치에 sudo 필요 — 미실행. 설치 시 skip된 1건이 pass로 전환 |

## 5. 환경 관련 메모

- K3s API가 간헐적으로 재시작 중이라(`systemctl is-active k3s` = activating ↔ active)
  클러스터 테스트가 수집 시점에 따라 skip될 수 있다. 이는 테스트 설계상 정상 동작이며,
  API가 떠 있을 때 재실행하면 11건 전부 통과한다.
- 개발용으로 기동한 컨테이너는 `aif-kafka`, `aif-otel` 두 개다. 기존에 돌던
  mosquitto/redis/grafana와 K3s 클러스터에는 변경을 가하지 않았다.

## 6. 추가 요구사항 필요 여부

없음. 모든 작업이 기존 요구사항 ID의 통합 검증에 해당한다. 선택 의존성을 optional extra
(`[mqtt]`, `[kafka]`, `[otel]`)로 둔 것은 AI-C-12에서 직접 따라 나오는 결론이다.
