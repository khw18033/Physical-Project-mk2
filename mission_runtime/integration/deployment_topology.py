"""The current deployment's transport topology, as data rather than code.

implements: AI-C-06 (데이터 유형별 전송 경계), AI-C-04 (외부 기술은 provider 경계 뒤),
            AI-O-01 (엣지 상세·서버 요약), AI-O-05 (미측정을 0 과 섞지 않는다)
관련: AI-B-10 (말단 경량), AI-B-11 (복수 실행영역), AI-C-16 (폐쇄망), AI-O-06
tests: tests/test_deployment_topology.py

왜 이 모듈이 있나 — **우리가 어디로 보내는지 모르면 안 보내진다.**

프레임워크는 토픽 문자열을 몰라야 하고(전송은 provider 의 일), 그래도 누군가는 현재
배포의 토픽 모양을 알아야 한다. 그 자리를 모듈 하나로 두고, 상위 로직은 여전히 채널
이름만 쓴다. 배포가 바뀌면 이 파일만 바뀐다.

## 현재 배포(2026-11-02 통합 저장소 기준)에서 확인한 사실

    업무   장치 ─MQTT─▶ 엣지 Mosquitto(1883) ══브릿지(터널)══▶ 중앙 Mosquitto(1883)
                                                              └─▶ be-ingest ─▶ Kafka
    명령   장치 ◀────── 엣지 Mosquitto ◀══브릿지══ 중앙 Mosquitto ◀─ 명령 발행자
    관측   장치 ─OTLP─▶ 엣지 Collector(4317) ─┬─ metric ─▶ 엣지 Prometheus ◀─federate─ 중앙
                                              └─ log·trace ─▶ 중앙 Collector(4317)

**엣지는 Kafka 에 붙지 않는다.** 엣지↔중앙은 MQTT 브릿지이고 Kafka 는 중앙의
`be-ingest` 뒤에만 있다. 우리 `edge/bridge.py` 는 처음부터 "uplink transport →
downlink transport" 로 쓰여 있어 이 사실에 코드가 바뀌지 않는다 — 바뀌는 것은 어느
transport provider 를 양쪽에 꽂는가뿐이다. 다만 **문서에 Kafka 로 적혀 있던 자리**는
이 모듈이 정정한다.

## 브릿지가 넘기는 토픽만 중앙에 도달한다

이것이 이 모듈의 핵심이다. 엣지 Mosquitto 의 브릿지는 아래 목록만 중앙으로 넘기고,
**그 밖의 토픽은 엣지 안에 머문다.** 우리 AI 채널을 엣지에서 발행해도 목록에 없으면
중앙에서는 오지 않는다 — 오류도 로그도 없이 그냥 오지 않는다. 그 사실을 코드가 알고
있어야 사이트에서 발견하지 않는다(`UNBRIDGED_AI_CHANNELS`).

## 관측 평면에도 같은 종류의 벽이 하나 더 있다 (2026-11-03 추가)

업무 평면의 브릿지 토픽 목록과 **똑같은 모양의 벽**이 계측에도 있다. 중앙 Prometheus
는 엣지 raw 전량을 받지 않고 `/federate` 로 `match[]` 가 고른 것만 당겨 간다. 지금
그 목록은 `hw_.*` 와 `system_cpu_.*|system_memory_.*` 뿐이라 **우리 계측은 중앙
Prometheus 에 없다**(`FEDERATED_METRIC_NAME_PATTERNS`).

그 자체는 잘못이 아니다 — AI-O-01·원칙 #14 가 "엣지에 상세, 서버에 요약"이라고 했고
우리 실패 분석도 엣지 엔드포인트를 본다. 다만 **중앙 화면이 AI 계측을 읽는다고 가정한
코드를 두면 안 된다**. 반대로 치명 사건·장치 생사는 계측이 아니라 log·trace 경로로
가고 그 경로는 요약 없이 중앙까지 원본이 간다 — 그래서 요약 벽 뒤에서도 개별 사건은
가려지지 않는다. 이 두 사실이 같은 자리에 적혀 있어야 "요약을 넓히자"는 잘못된 해법이
나오지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 사이트 설정 환경변수 이름. 통합 저장소의 `deploy/.env` 와 **같은 이름을 쓴다** —
#: 이름이 다르면 사이트가 같은 값을 두 번 적어야 하고, 한쪽만 고치는 날이 온다.
ENV_ZONE_ID = "MK2_ZONE_ID"
ENV_CENTRAL_MQTT_HOST = "MK2_CENTRAL_MQTT_HOST"
ENV_CENTRAL_MQTT_PORT = "MK2_CENTRAL_MQTT_PORT"
ENV_CENTRAL_OTLP = "MK2_CENTRAL_OTLP"
ENV_EDGE_TUNNEL_BIND = "MK2_EDGE_TUNNEL_BIND"
#: ⚠ 두 이름이 비슷하고 **가리키는 기계가 다르다.** `MK2_EDGE_BIND` 는 중앙 서버가
#: 엣지에게 열어 주는 입구(중앙 `deploy/.env`)이고, 엣지 호스트에서 말단이 붙는 입구는
#: `MK2_EDGE_LAN_BIND`(엣지 `deploy/edge/.env`)다. 하나로 줄이면 사이트가 반대로 적는다.
ENV_EDGE_BIND = "MK2_EDGE_BIND"
ENV_EDGE_LAN_BIND = "MK2_EDGE_LAN_BIND"
ENV_CENTRAL_MQTT_USER = "MK2_CENTRAL_MQTT_USER"
ENV_CENTRAL_MQTT_PASSWORD = "MK2_CENTRAL_MQTT_PASSWORD"
ENV_EDGE_METRIC_RETENTION = "MK2_EDGE_PROMETHEUS_RETENTION"
ENV_CENTRAL_METRIC_RETENTION = "MK2_PROMETHEUS_RETENTION"

#: 현재 배포의 포트. 교체 가능한 값이고 여기 적어 두는 것은 **대조용**이다.
PORT_MQTT = 1883
PORT_OTLP = 4317
#: 중앙 Collector 는 4316 과 4317 을 **같은 수신단**으로 연다. 4316 은 백엔드 문서의
#: 기존 기본값이고 4317 이 OTLP 표준이며 우리·하드웨어의 기본값이다. 둘 중 어느 쪽으로
#: 설정해도 붙으므로 우리는 표준 번호를 쓴다(통합 저장소 `docs/PORTS.md:12`).
PORT_OTLP_ALT = 4316
#: Kafka 엣지 리스너. 1.0 배포에서는 **쓰지 않는다**(엣지는 Kafka 에 붙지 않는다).
PORT_KAFKA_EDGE_UNUSED = 9095

#: 업무 텔레메트리 토픽 모양 — `{zone}/{entity_type}/{entity_id}/{channel}`.
TELEMETRY_TOPIC_TEMPLATE = "{zone}/{entity_type}/{entity_id}/{channel}"

#: 브릿지가 중앙으로 넘기는 텔레메트리 채널. 이 셋만 넘어간다.
BRIDGED_TELEMETRY_CHANNELS: frozenset[str] = frozenset({"state", "status", "heartbeat"})

#: 물리 명령 경로. 방향만 토픽에 담고 종류는 봉투가 정한다(AI-C-20).
TERMINAL_DOWNLINK_TEMPLATE = "terminal/{device_id}/downlink"
TERMINAL_UPLINK_TEMPLATE = "terminal/{device_id}/uplink"

#: 우리 AI 채널 중 **지금 브릿지가 넘기지 않는** 것. 엣지에서 발행하면 엣지에 머문다.
#: 넘기려면 브릿지 토픽 목록에 추가가 필요하고 그것은 배포·하드웨어 파트의 변경이다
#: (인수인계 문서 참고). 그때까지 중앙 소비자는 이 채널을 받지 못한다 — 받는 척하는
#: 코드를 두지 않기 위해 목록으로 적어 둔다.
UNBRIDGED_AI_CHANNELS: tuple[str, ...] = (
    "detections",
    "risk_state",
    "ai_failure",
    "capability_status",
    "model_deployment_result",
    "status_snapshot",
)


class TopologyError(ValueError):
    """토픽을 만들 수 없다. 빈 식별자는 토픽을 조용히 망가뜨린다."""


def telemetry_topic(zone: str, entity_type: str, entity_id: str, channel: str) -> str:
    """업무 텔레메트리 토픽 하나. 빈 칸을 허용하지 않는다.

    빈 문자열을 끼우면 `zoneA//x/state` 같은 토픽이 생기고, 와일드카드 구독
    `+/+/+/state` 에는 걸리지만 사람이 읽을 수 없는 자리가 된다.
    """
    for name, value in (("zone", zone), ("entity_type", entity_type),
                        ("entity_id", entity_id), ("channel", channel)):
        if not value or "/" in value or "+" in value or "#" in value:
            raise TopologyError(f"{name} must be non-empty and free of MQTT wildcards: {value!r}")
    return TELEMETRY_TOPIC_TEMPLATE.format(
        zone=zone, entity_type=entity_type, entity_id=entity_id, channel=channel
    )


def terminal_topic(device_id: str, *, downlink: bool) -> str:
    if not device_id or "/" in device_id:
        raise TopologyError(f"device_id must be non-empty and free of '/': {device_id!r}")
    template = TERMINAL_DOWNLINK_TEMPLATE if downlink else TERMINAL_UPLINK_TEMPLATE
    return template.format(device_id=device_id)


def reaches_central(topic: str) -> bool:
    """이 토픽이 엣지 브릿지를 넘어 중앙까지 가는가.

    가지 않는 것을 가는 것처럼 다루면, 사이트에서 "중앙에 안 온다"를 한참 뒤에
    발견한다. 그래서 발행 전에 물어볼 수 있는 자리를 둔다.
    """
    parts = topic.split("/")
    if len(parts) == 4 and parts[3] in BRIDGED_TELEMETRY_CHANNELS:
        return True
    return len(parts) == 3 and parts[0] == "terminal" and parts[2] in {"uplink", "downlink"}


@dataclass(frozen=True)
class CentralEndpoint:
    """중앙 쪽 접점 하나. 터널 위에서만 연결한다(원칙 #10)."""

    host: str
    port: int
    purpose: str

    def __post_init__(self) -> None:
        if not self.host:
            raise TopologyError("central endpoint host must be set (MK2_CENTRAL_* 를 읽는다)")
        if not 1 <= self.port <= 65535:
            raise TopologyError(f"port out of range: {self.port}")


#: 공개 인터넷으로 보이는 주소인가를 가리는 간단한 판정. 터널(Tailscale) 주소는
#: 100.64.0.0/10(CGNAT) 대역이고, 사설망·loopback 도 터널 밖으로 나가지 않는다.
#: **이 함수는 보안 장치가 아니다** — 설정 실수를 조기에 잡는 검사다.
def is_tunnel_or_private(host: str) -> bool:
    import ipaddress

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # 이름은 판정하지 않는다. tailnet 이름(`*.ts.net`)만 통과시키면 사이트가
        # 쓰는 다른 이름을 거짓으로 막는다.
        return host.endswith(".ts.net") or host in {"localhost"}
    if address.is_loopback or address.is_private or address.is_link_local:
        return True
    return address in ipaddress.ip_network("100.64.0.0/10")


# ── 관측 평면 (AI-O-01, AI-O-05) ─────────────────────────────────────────────
#
# 아래는 2026-11-03 에 통합 저장소 `main` @ `30f5ee94a` 를 읽어 맞춘 값이다. 추측이
# 아니라 그쪽 설정 파일에서 옮겨 적었고, 어긋나면 시험이 깨진다
# (`tests/test_deployment_topology.py`).

#: Collector 의 prometheus exporter 와 Collector 자기 관측. 엣지 Prometheus 가 둘을
#: 긁는다(`deploy/edge/config/prometheus.yml`, `deploy/server/config/prometheus.yml`).
PORT_COLLECTOR_METRIC_EXPORT = 8889
PORT_COLLECTOR_SELF_METRICS = 8888
#: 구역 엣지의 계측 질의 입구. 터널 주소에만 바인딩된다(`MK2_EDGE_TUNNEL_BIND`).
#: `providers/observability_query.py` 의 기본 엔드포인트가 이 번호다.
PORT_EDGE_METRIC_QUERY = 9090
#: 중앙 Prometheus 는 컨테이너 안에서 9090 이고 호스트에는 운영자용 7861 로 나온다.
#: 우리가 붙는 자리는 아니다 — 실패 분석은 엣지 상세값을 본다.
PORT_CENTRAL_METRIC_QUERY_ADMIN = 7861

#: 수집 간격. 엣지·중앙 모두 global 15초이고, Collector 의 exporter 만 5초로 더 자주
#: 긁는다("백엔드 export 15초 × 표본 3 이 되도록"). 우리 질의 step 이 이보다 굵으면
#: 창 안에서 치솟은 한 점이 묻힌다 — `MetricQueryEndpoint.step_s` 가 5초인 이유다.
SCRAPE_INTERVAL_S = 15.0
COLLECTOR_SCRAPE_INTERVAL_S = 5.0
#: prometheus exporter 의 `metric_expiration`. 5분 갱신이 없으면 시계열이 **사라진다**
#: — 0 이 되는 것이 아니다. 그 공백을 정상으로 읽으면 안 되고 `NOT_SCRAPED` 다.
METRIC_EXPIRATION_S = 300.0
#: 계측 보존. 장기 재현은 계측이 아니라 업무 저장소·아카이브의 몫이다(AI-O-03, 원칙 #17).
EDGE_METRIC_RETENTION_DAYS = 7
CENTRAL_METRIC_RETENTION_DAYS = 15

#: 파트별 계측 이름 접두. 점 구분 OTel 이름으로 내고 Prometheus 표기는 Collector 가
#: 만든다 — 우리가 `_` 를 직접 넣지 않는다.
#: ⚠ `ai.` 는 **우리가 고른 값이고 아직 그쪽 규약에 등재되지 않았다.** 그쪽 문서는
#: 아직 옛 패키지 이름(`perception_framework.*`)으로 우리 자리를 적고 있다. 등재를
#: 요청했고(`docs/integration-handover.md`), 그 전까지도 `hw.`·`be.`·`vz.` 와 겹치지
#: 않으므로 충돌은 나지 않는다.
METRIC_NAME_PREFIX_BY_PART: dict[str, str] = {
    "hardware": "hw.",
    "backend": "be.",
    "visualisation": "vz.",
    "ai": "ai.",
}
AI_METRIC_NAME_PREFIX = METRIC_NAME_PREFIX_BY_PART["ai"]

#: 중앙이 `/federate` 로 당겨 가는 이름 패턴. **이 둘만 중앙에 도달한다.**
#: (`deploy/server/config/prometheus.yml:68-71` 의 `params["match[]"]`)
FEDERATED_METRIC_NAME_PATTERNS: tuple[str, ...] = (
    r"hw_.*",
    r"system_cpu_.*|system_memory_.*",
)

#: 어느 층에도 라벨로 쓰지 않는 이름. 백엔드 어댑터는 이것을 `ValueError` 로 **막는다**
#: (`server/contracts/common/README.md:215-222`). 즉 이 이름으로 라벨이 붙은 시계열은
#: 애초에 생기지 않으므로, 이 이름으로 선택자를 걸면 영원히 표본 0 이다. 그 사실을
#: 모르면 "계측이 왜 안 보이나"를 백엔드 쪽에서 찾게 된다.
FORBIDDEN_METRIC_LABELS: frozenset[str] = frozenset({
    "session_id",
    "internal_seq",
    "sequence_id",
    "timestamp",
    "ts",
    "capture_timestamp",
    "sent_at",
    "received_at",
    "emitted_at",
    "frame_id",
    "frame_ref",
    "correlation_id",
    "command_id",
    "mission_id",
    "node_ref",
    "client_request_id",
    "plan_id",
    "event_key",
    "utterance_text",
})

#: 자기 관측 지표에 허용되는 라벨. 값의 종류가 한정된 것만 쓴다.
SELF_METRIC_LABELS: frozenset[str] = frozenset({
    "component", "channel", "outcome", "stage", "endpoint",
})
#: 장치별이어야 의미가 있는 지표에만 더한다 — 자기 관측에 붙이면 장치 수만큼
#: 시계열이 곱해진다(층에 따라 기준이 다르다).
DEVICE_SCOPED_METRIC_LABELS: frozenset[str] = frozenset({
    "source_id", "zone_id", "entity_type",
})

#: Collector 의 prometheus exporter 는 `service.name` 을 `job` 라벨로 내보내는데,
#: 수집 잡에 `honor_labels` 가 없어 Prometheus 가 `exported_job` 으로 바꿔 넣는다
#: (`mk2/ai-...` 처럼 namespace 가 앞에 붙는다). **그래서 `job` 으로 우리 서비스를
#: 고를 수 없다** — 컴포넌트를 가르려면 `component` 라벨을 직접 붙인다.
SERVICE_LABEL_AS_SCRAPED = "exported_job"
#: 엣지 Collector·Prometheus 가 붙이는 리소스 속성·external label. ⚠ `external_labels`
#: 는 `/federate`·remote-write 에만 실리고 **엣지에 직접 질의할 때는 보이지 않는다**
#: (2026-11-03 실측). 엣지 엔드포인트에 `agg_layer` 선택자를 걸면 표본 0 이다.
EDGE_EXTERNAL_LABELS: dict[str, str] = {"agg_layer": "edge"}


def prometheus_metric_name(otel_name: str) -> str:
    """점 구분 OTel 이름 → Prometheus 표기. Collector 가 하는 변환의 **앞부분만** 한다.

    Collector 는 여기에 더해 counter 에 `_total` 을, `unit` 이 있으면 `_seconds`·
    `_bytes`·`_ratio` 같은 접미사를 붙인다. 그 접미사는 계기 종류와 단위에 달린
    것이어서 이름만 보고 알 수 없다 — 여기서 지어내지 않고, 접미사가 필요한 이름은
    질의하는 쪽이 그대로 적는다.
    """
    return re.sub(r"[^a-zA-Z0-9_:]", "_", otel_name)


def metric_reaches_central(prometheus_name: str) -> bool:
    """이 계측이 엣지 페더레이션을 넘어 중앙 Prometheus 까지 가는가.

    `reaches_central()` 이 업무 평면에서 하는 일을 관측 평면에서 한다. 가지 않는 것을
    가는 것처럼 다루면 중앙 화면이 비는 이유를 한참 뒤에 찾는다.
    """
    return any(re.fullmatch(pattern, prometheus_name) for pattern in FEDERATED_METRIC_NAME_PATTERNS)


def forbidden_labels_in(selector) -> tuple[str, ...]:
    """선택자에 섞인 금지 라벨 이름. 없으면 빈 튜플.

    예외를 던지지 않는다 — 관측 질의가 실패 분석을 멈추게 하면 안 되고(AI-O-01),
    부르는 쪽은 이것을 "표본이 없을 이유"로 적는 데 쓴다.
    """
    if not selector:
        return ()
    return tuple(sorted(set(selector) & FORBIDDEN_METRIC_LABELS))
