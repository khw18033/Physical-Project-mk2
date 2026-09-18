"""관측 어댑터 — 백엔드가 관측 평면(OTLP → 서버 Collector)에 신호를 내는 유일한 문.

원칙 1(특정 기술을 핵심에 하드코딩하지 않는다)을 지키는 자리다. `opentelemetry` 패키지를 import
하는 백엔드 모듈은 **이 파일뿐**이다. `bridge.py`·`consumer.py`·`ws_echo.py`·`tsdb_writer.py`·
`registry.py`는 아래 목적 인터페이스만 부른다:

    setup(service_name)                 프로세스 기동 시 1회
    count(name, value=1, **labels)      counter        (단조 증가 — Prometheus 에서 *_total)
    updown(name, delta, **labels)       UpDownCounter  (접속 수처럼 오르내리는 값)
    gauge(name, value, **labels)        gauge          (마지막 값 — C층 절대값)
    observe(name, value, **labels)      histogram      (분포 — be.pipeline.lag)
    log_handler()                       logging.Handler | None  (OTel Logs → Collector → Loki)
    shutdown()

## 반드시 지키는 것 넷 (작업 지시서 단계 6-2)

1. **no-op 규율(제약 20).** `MK2_OTEL_ENDPOINT`가 비었거나, SDK가 없거나, 초기화가 실패하면
   조용히 no-op 으로 떨어지고 업무 경로는 계속 돈다. HW `otel_metrics.create()`와 같은 구조다.
   기동 시 한 줄 로그로 활성/비활성을 남긴다.
2. **라벨 가드 — 금지 라벨은 `ValueError`.** `session_id`·`internal_seq`·`sequence_id`·`timestamp`·
   `ts`·`frame_id`·`capture_timestamp`(Phase 3) + `frame_ref`·`correlation_id`·`command_id`·`mission_id`·
   `node_ref`·`client_request_id`·`plan_id`·`event_key`(Phase 4)는 값이 계속 달라져 시계열을 폭증시킨다.
   **조용히 버리지 않는다** — 버리면 나중에 누가 넣어도 아무도 모른다. 이 예외는 어댑터가 활성이든
   no-op 이든 똑같이 난다(코드 결함은 관측 스택 유무와 무관하게 드러나야 한다). 음성 대조 N1의 대상.
   `node_id`(물리 노드)는 허용이다.
3. **A층에는 `source_id`를 넣지 않는다.** `be.ingest.*`·`be.kafka.*`·`be.storage.*`·`be.registry.*`·
   `be.gateway.*`·`be.pipeline.*`에 `source_id`·`zone_id`·`entity_type`이 붙으면 `ValueError`.
   A층의 질문은 "백엔드가 잘 도는가"라 장치별로 가를 필요가 없고, 달면 장치 수만큼 시계열이
   곱해진다. C층(`be.telemetry.*`)은 반대로 그 넷이 라벨이다. 음성 대조 N2의 대상.
4. **계측 호출이 예외를 밖으로 내보내지 않는다.** 라벨 가드(코드 결함)를 뺀 나머지 — SDK·exporter·
   네트워크 — 는 전부 여기서 삼키고 이름당 한 번만 로그를 남긴다.

## 구현 함정 (지시서 6-2 주의)

- **계기는 이름별로 한 번만 만들어 캐시한다.** 부를 때마다 `create_counter()`를 하면 중복 계기
  경고가 나고 값이 갈린다.
- **히스토그램 버킷은 `View`로 준다.** 기본 버킷 상한이 10초 근처라 우리 값(실측 -30 ~ 344,000초)이
  전부 `+Inf`에 몰린다. `be.pipeline.lag`에 명시적 버킷을 건다(`LAG_BUCKETS`).
- **OTel 히스토그램은 음수를 받지 않는다** — SDK `Histogram.record()`가 경고와 함께 버린다(규격).
  그래서 `observe()`는 음수를 SDK 에 넘기지 않고, 호출부(`consumer.py`)가 절대값 + `outcome`
  라벨(`ok`/`clock_skew`)로 부호를 보존한다. 지시서 6-3 "음수도 버리지 않는다"를 이 방식으로 이행했다.
- **로그 SDK 모듈 경로가 버전에 따라 밑줄일 수 있다**(`opentelemetry.sdk._logs`). 두 경로를 다
  시도하고 실제 잡힌 경로를 기동 로그에 적는다.
- `service.name`은 Collector 의 prometheus exporter 가 `job` 라벨로 내보내고, 스크레이프 잡에
  `honor_labels`가 없어 Prometheus 에서 `exported_job`으로 나타난다. 컴포넌트 구분은 그래서
  우리가 붙이는 `component` 라벨로 한다(Loki 는 `service_name` 라벨로 그대로 색인된다).

implements: BE-S-02 (A층·C층 계측 발신, 로그 경로), BE-S-07 (be.pipeline.lag 가 lag_s 를 관측 평면에 올린다)
tests: tests/test_observability_labels.py (라벨 가드 단위 — 금지 라벨 거부·A층 source_id 거부·허용 통과·no-op) ·
       tests/test_observability_pipeline.py (Prometheus·Loki·Tempo 도달) ·
       tests/test_observability_isolation.py (관측 저장소가 죽어도 업무 경로 유지)
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Dict, Optional, Tuple

from backend import settings

LOG = logging.getLogger("mk2.observability")

# ── 라벨 규약 (결정 4-b) ─────────────────────────────────────────────────────
# 값이 계속 달라지는 것. 하나라도 라벨에 들어가면 시계열이 폭증한다.
# Phase 4(2026-09-18)에서 8종을 더했다 — `frame_ref`·`correlation_id`·`command_id`는 VZ 통지
# (docs/be/vz-observability-namespace.md §2)가 "코드로 막는다"고 적었는데 실제로는 없던 것이고,
# `mission_id`·`node_ref`·`client_request_id`·`plan_id`·`event_key`는 VZ 회신(2026-09-17)이 제안한
# VZ 식별자다. ⚠ `node_id`는 넣지 않는다 — 우리 공통 헤더의 node_id 는 물리 노드(pi1·pi7)라
# 저카디널리티다(VZ 의 DAG 노드는 `node_ref` 로 내보내 달라고 요청했다). 9번째 「발화 원문」은
# 키 이름을 VZ 에게 받은 뒤 넣는다(문자열 집합이라 이름 없이 못 넣는다 — 빠진 것이 아니라 대기).
# 목록의 기준 문서는 contracts/common/README.md 「관측 신호 힌트와 라벨 금지」다.
FORBIDDEN_LABELS = frozenset(
    {
        # Phase 3
        "session_id", "internal_seq", "sequence_id", "timestamp", "ts", "frame_id", "capture_timestamp",
        # Phase 4 — 프레임·명령·임무 식별자
        "frame_ref", "correlation_id", "command_id",
        "mission_id", "node_ref", "client_request_id", "plan_id", "event_key",
    }
)
# A층 계기 이름 접두사. 여기에는 장치 식별 라벨을 붙이지 않는다.
A_LAYER_PREFIXES: Tuple[str, ...] = (
    "be.ingest.", "be.kafka.", "be.storage.", "be.registry.", "be.gateway.", "be.pipeline.",
)
A_LAYER_FORBIDDEN = frozenset({"source_id", "zone_id", "entity_type"})
# C층 계기 이름 접두사. 여기는 반대로 source_id·zone_id·entity_type·channel 이 라벨이다.
C_LAYER_PREFIX = "be.telemetry."

# be.pipeline.lag 버킷(초). 실측 범위 -30 ~ 344,000(retained status 재유입)을 덮는다.
LAG_BUCKETS: Tuple[float, ...] = (0.1, 0.5, 1, 5, 15, 60, 300, 1800, 7200, 86400)
LAG_INSTRUMENT = "be.pipeline.lag"
# be.gateway.media_coldstart 버킷(초) — 뷰어 연결 → 첫 프레임 전송. 초기 WAIT_IDR 때문에 최대 GOP 길이가
# 더해진다(H.264 IDR 간격 실측 0.48초). 값은 항상 양수다. (Phase 4 단계 2-5)
COLDSTART_BUCKETS: Tuple[float, ...] = (0.1, 0.25, 0.5, 1, 2, 5, 10, 30)
COLDSTART_INSTRUMENT = "be.gateway.media_coldstart"

# 계기 종류 → (unit, Prometheus 표기 규칙 메모)
#   counter  unit "1"  → <name>_total            (be_ingest_received_total)
#   updown   unit "1"  → <name>                  (be_gateway_clients — 비단조 합은 _total 이 안 붙는다)
#   gauge    unit ""   → <name>                  (be_telemetry_water_level_m — unit "1" 을 주면 _ratio 가 붙어 이름이 바뀐다)
#   histogram unit "s" → <name>_seconds_{bucket,sum,count}
_UNIT_BY_KIND = {"counter": "1", "updown": "1", "gauge": "", "histogram": "s"}


# ── 상태 ─────────────────────────────────────────────────────────────────────


class _State:
    """프로세스 하나의 어댑터 상태. 모듈 전역 하나(`_S`)만 있다."""

    def __init__(self) -> None:
        self.enabled: bool = False
        self.service_name: str = ""
        self.endpoint: str = ""
        self.meter: Any = None
        self.meter_provider: Any = None
        self.logger_provider: Any = None
        self.handler: Optional[logging.Handler] = None
        self.logs_module: str = ""
        self.instruments: Dict[Tuple[str, str], Any] = {}
        self.failed_once: set = set()


_S = _State()


# ── 라벨 가드 (순수 함수 — 인프라·SDK 없이 시험한다) ───────────────────────


def is_a_layer(name: str) -> bool:
    return name.startswith(A_LAYER_PREFIXES)


def check_labels(name: str, labels: Dict[str, Any]) -> Dict[str, Any]:
    """라벨을 검사하고 SDK 속성 형태로 정리한다. 위반은 **`ValueError`** — 조용히 버리지 않는다.

    - 금지 라벨(`FORBIDDEN_LABELS`)은 어느 계기에도 못 붙는다.
    - A층 계기(`is_a_layer`)에는 `source_id`·`zone_id`·`entity_type`을 못 붙인다.
    - 값이 `None`이면 `"unknown"`으로 채운다 — 라벨을 비우거나 건너뛰면 "왜 안 나오나"를 나중에 헤맨다
      (헤더 없는 옛 메시지의 `entity_type=None`이 그 경우다, 지시서 7-3-a).
    """
    bad = FORBIDDEN_LABELS.intersection(labels)
    if bad:
        raise ValueError(
            "관측 라벨 금지 위반: {} — 계기 {} (값이 계속 달라지는 것은 라벨에 넣지 않는다)".format(
                ", ".join(sorted(bad)), name
            )
        )
    if is_a_layer(name):
        bad = A_LAYER_FORBIDDEN.intersection(labels)
        if bad:
            raise ValueError(
                "A층 계기 {} 에 장치 식별 라벨 {} 을 붙일 수 없다 — 장치 수만큼 시계열이 곱해진다. "
                "장치별 신호는 C층(be.telemetry.*)이다".format(name, ", ".join(sorted(bad)))
            )
    cleaned: Dict[str, Any] = {}
    for key, value in labels.items():
        if value is None:
            value = "unknown"
        elif not isinstance(value, (str, int, float, bool)):
            value = str(value)
        cleaned[key] = value
    return cleaned


# ── 기동·종료 ────────────────────────────────────────────────────────────────


def _resource(service_name: str):
    from opentelemetry.sdk.resources import Resource

    # service.instance.id 는 재기동해도 같은 값이어야 한다 — pid 를 넣으면 Loki 스트림이 재기동마다 는다.
    return Resource.create({
        "service.name": service_name,
        "service.namespace": "mk2",
        "service.instance.id": socket.gethostname(),
    })


def _setup_metrics(resource, endpoint: str, insecure: bool, interval_s: float) -> None:
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=insecure),
        export_interval_millis=int(interval_s * 1000),
    )
    views = [
        View(
            instrument_name=LAG_INSTRUMENT,
            aggregation=ExplicitBucketHistogramAggregation(boundaries=list(LAG_BUCKETS)),
        ),
        View(
            instrument_name=COLDSTART_INSTRUMENT,
            aggregation=ExplicitBucketHistogramAggregation(boundaries=list(COLDSTART_BUCKETS)),
        ),
    ]
    # 전역 provider 를 건드리지 않는다 — 이 프로세스의 계기는 전부 이 meter 에서 나온다.
    _S.meter_provider = MeterProvider(resource=resource, metric_readers=[reader], views=views)
    _S.meter = _S.meter_provider.get_meter("mk2.backend")


class _DropOtelInternal(logging.Filter):
    """SDK 자신의 로그(`opentelemetry.*`)는 관측 경로로 보내지 않는다.

    exporter 가 실패하면 SDK 가 경고를 찍고, 그 경고가 다시 exporter 로 가서 또 실패하는 되먹임을
    끊기 위해서다. 그 로그는 stdout(journald)에는 그대로 남는다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry")


def _setup_logs(resource, endpoint: str, insecure: bool) -> None:
    """OTel Logs SDK → OTLP → Collector → Loki (결정 4-c). 경로가 밑줄인 버전을 함께 지원한다.

    **핸들러는 `opentelemetry-instrumentation-logging`의 것을 먼저 쓴다**(Phase 4 단계 5-3 #9). SDK 1.44 가
    자기 `LoggingHandler`를 deprecated 로 표시했고(pytest 경고 2건), 대체 클래스는 패키지 최상위가 아니라
    `opentelemetry.instrumentation.logging.handler.LoggingHandler`에 있다(0.65b0 실측 — 생성자 모양은
    `(level, logger_provider, log_code_attributes=False)`로 SDK 것과 같다). `LoggingInstrumentor().instrument()`는
    쓰지 않는다 — 루트 로거에 핸들러를 스스로 붙이고 `logging.basicConfig`를 감싸는데, 우리는 핸들러를 어디에
    붙일지 호출부(`main()`)가 정한다. 패키지가 없으면 SDK 핸들러로 물러선다(경고만 남고 동작은 같다).
    """
    try:
        from opentelemetry.sdk.logs import LoggerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.logs.export import BatchLogRecordProcessor  # type: ignore[import-not-found]
        _S.logs_module = "opentelemetry.sdk.logs"
    except ImportError:
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        _S.logs_module = "opentelemetry.sdk._logs"
    try:
        from opentelemetry.instrumentation.logging.handler import LoggingHandler  # type: ignore[import-not-found]
        _S.logs_module += " + instrumentation.logging.handler"
    except ImportError:
        try:
            from opentelemetry.sdk.logs import LoggingHandler  # type: ignore[import-not-found]
        except ImportError:
            from opentelemetry.sdk._logs import LoggingHandler
        _S.logs_module += " + sdk LoggingHandler(deprecated)"
    try:
        from opentelemetry.exporter.otlp.proto.grpc.log_exporter import OTLPLogExporter  # type: ignore[import-not-found]
    except ImportError:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

    _S.logger_provider = LoggerProvider(resource=resource)
    _S.logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=insecure))
    )
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=_S.logger_provider)
    handler.addFilter(_DropOtelInternal())
    _S.handler = handler


def setup(service_name: str) -> None:
    """프로세스 기동 시 1회. 실패해도 예외를 내지 않는다 — 계측 없이 업무 경로가 계속 돈다."""
    _S.service_name = settings.otel_service_name(service_name)
    _S.endpoint = settings.otel_endpoint()
    if not _S.endpoint:
        LOG.info("관측 비활성: MK2_OTEL_ENDPOINT 가 비어 있다 — 계측 no-op, 업무 경로는 그대로 돈다")
        return
    insecure = not _S.endpoint.startswith("https://")
    interval_s = settings.otel_export_interval()
    try:
        resource = _resource(_S.service_name)
        _setup_metrics(resource, _S.endpoint, insecure, interval_s)
    except Exception as exc:  # noqa: BLE001 - SDK 미설치(ImportError)·초기화 실패 전부 no-op 으로
        LOG.warning(
            "관측 초기화 실패(%s: %s) — 계측 없이 계속 동작한다 (SDK 설치·MK2_OTEL_ENDPOINT 확인)",
            type(exc).__name__, exc,
        )
        _S.meter = None
        _S.meter_provider = None
        return
    try:
        _setup_logs(resource, _S.endpoint, insecure)
    except Exception as exc:  # noqa: BLE001 - 로그 경로만 없어도 metric 은 계속 낸다
        LOG.warning("관측 로그 경로 초기화 실패(%s: %s) — 로그는 stdout(journald)에만 남는다", type(exc).__name__, exc)
        _S.handler = None
        _S.logger_provider = None
    _S.enabled = True
    LOG.info(
        "관측 활성: service.name=%s → %s (metric export %.0fs, 로그 경로 %s)",
        _S.service_name, _S.endpoint, interval_s, _S.logs_module or "없음",
    )


def log_handler() -> Optional[logging.Handler]:
    """루트 로거에 붙일 OTel 핸들러. 비활성이면 `None`(아무 일도 하지 않는다)."""
    return _S.handler if _S.enabled else None


def enabled() -> bool:
    return _S.enabled


def shutdown() -> None:
    """남은 표본을 밀어내고 닫는다. 실패해도 조용히 지나간다(종료를 막지 않는다)."""
    for provider in (_S.meter_provider, _S.logger_provider):
        if provider is None:
            continue
        try:
            provider.shutdown(timeout_millis=5000)
        except TypeError:
            try:
                provider.shutdown()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    _S.enabled = False
    _S.meter = None
    _S.meter_provider = None
    _S.logger_provider = None
    _S.handler = None
    _S.instruments.clear()


# ── 계기 ─────────────────────────────────────────────────────────────────────


def _instrument(kind: str, name: str):
    """(종류, 이름) → 계기. 한 번 만들고 재사용한다."""
    key = (kind, name)
    inst = _S.instruments.get(key)
    if inst is not None:
        return inst
    meter = _S.meter
    unit = _UNIT_BY_KIND[kind]
    if kind == "counter":
        inst = meter.create_counter(name, unit=unit)
    elif kind == "updown":
        inst = meter.create_up_down_counter(name, unit=unit)
    elif kind == "gauge":
        inst = meter.create_gauge(name, unit=unit)
    elif kind == "histogram":
        inst = meter.create_histogram(name, unit=unit)
    else:  # pragma: no cover - 호출부 오타
        raise ValueError("알 수 없는 계기 종류: {}".format(kind))
    _S.instruments[key] = inst
    return inst


def _emit(kind: str, name: str, value: Any, labels: Dict[str, Any]) -> None:
    attrs = check_labels(name, labels)       # 코드 결함(금지 라벨)은 여기서 ValueError 로 드러난다
    if not _S.enabled:
        return
    try:
        inst = _instrument(kind, name)
        if kind == "counter" or kind == "updown":
            inst.add(value, attrs)
        elif kind == "gauge":
            inst.set(value, attrs)
        else:
            inst.record(value, attrs)
    except Exception as exc:  # noqa: BLE001 - 계측 실패가 업무 경로를 막지 않는다
        if name not in _S.failed_once:
            _S.failed_once.add(name)
            LOG.warning("계측 실패(이후 같은 계기는 조용히 지나간다): %s %s: %s", name, type(exc).__name__, exc)


def count(name: str, value: int = 1, **labels: Any) -> None:
    """counter — 단조 증가. 재기동하면 0부터 다시 센다(조회는 `rate()`/`increase()`로)."""
    if value < 0:
        raise ValueError("counter 는 음수를 더할 수 없다: {} {}".format(name, value))
    _emit("counter", name, value, labels)


def updown(name: str, delta: int, **labels: Any) -> None:
    """UpDownCounter — 접속 수처럼 오르내리는 값(+1/-1)."""
    _emit("updown", name, delta, labels)


def gauge(name: str, value: float, **labels: Any) -> None:
    """gauge — 마지막 값. C층 절대값(수위·배터리·말단 누적 카운터)이 여기로 온다."""
    _emit("gauge", name, value, labels)


def observe(name: str, value: float, **labels: Any) -> None:
    """histogram — 분포. **음수는 SDK 가 버리므로 여기서 먼저 막는다**(한 번만 경고).

    부호가 의미 있는 값(`lag_s`)은 호출부가 절대값 + `outcome` 라벨로 넘긴다.
    """
    if value < 0:
        if name not in _S.failed_once:
            _S.failed_once.add(name)
            LOG.warning("히스토그램 %s 에 음수(%s)를 넣을 수 없다 — 호출부가 절대값+라벨로 넘겨야 한다", name, value)
        return
    _emit("histogram", name, value, labels)


def reset_for_tests() -> None:
    """테스트가 상태를 깨끗이 되돌릴 때 쓴다."""
    shutdown()
    _S.failed_once.clear()
    _S.service_name = ""
    _S.endpoint = ""
    _S.logs_module = ""
