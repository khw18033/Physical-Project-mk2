"""관측 데이터를 **읽는** provider 구현. 질의 프로토콜과 저장 형식이 사는 유일한 곳.

implements: AI-O-01, AI-O-02, AI-O-03, AI-O-05
관련: AI-C-04 (외부 기술은 provider 경계 뒤), AI-C-06 (데이터 유형별 전송 경계),
      AI-C-05 (결손은 축소이지 실패가 아니다)
tests: tests/test_failure_trace.py, tests/test_real_prometheus_path.py

`observability/failure_trace.py` 는 계측·구간·사건이라는 의미만 말한다. 그 의미를
현재 배포의 실물에서 긁어 오는 일이 이 모듈의 전부다 — Prometheus 호환 HTTP 질의
API, OTel Collector 의 파일 exporter 출력(NDJSON OTLP), 그리고 백엔드가 없는 노드의
로컬 사건 버퍼. 상위 코드는 이 중 무엇이 쓰이는지 모른다(요건 6).

쓰는 쪽은 이미 있다 — `providers/otel.py` 가 OTLP 로 내보낸다. 이 모듈은 그 짝인
읽는 쪽이고 SDK 를 다시 들이지 않는다(`opentelemetry` import 는 `providers/otel.py`
한 곳이라는 경계 시험이 있다). 그래서 여기서는 표준 라이브러리로 **이미 내보낸
것**을 읽는다: HTTP 질의와 파일 exporter 의 JSON 이다.

네 가지 구현과 각각이 못 하는 일
--------------------------------

    HttpMetricQueryProvider   계측만. 구간·사건은 못 긁는다 → NOT_SCRAPED
    CollectorFileExportReader 계측·구간·사건 전부. 파일이 없으면 → BACKEND_UNREACHABLE
    LocalEventQueryProvider   사건만 (쓰는 provider 의 로컬 버퍼). 계측은 → NOT_SCRAPED
    CompositeQueryProvider    축마다 다른 reader 를 붙인다. 한 축 결손은 그 축만 비운다

"못 긁는다"를 BACKEND_UNREACHABLE 로 적지 않는 것이 중요하다 — 닿지 못한 것과 이
reader 에 그 평면이 없는 것은 다른 사실이고, 둘 다 미측정이지만 사유가 다르다.
`note` 가 그 사유를 들고 다닌다.

선택자로 고를 수 없는 라벨이 있다
---------------------------------
배포 규약이 **라벨로 쓰는 것을 금지한 이름**이 있고(명령·프레임·임무 식별자, 시각 등
`integration/deployment_topology.FORBIDDEN_METRIC_LABELS`), 쓰는 쪽이 그것을 거부하기
때문에 그 라벨이 붙은 시계열은 애초에 생기지 않는다. 그런 선택자를 받으면 질의를
보내지 않고 사유를 적어 NOT_SCRAPED 로 답한다 — 보내도 답은 같지만, 그러면 "왜
비었는가"가 사라진다. 명령 하나를 되짚는 일은 계측이 아니라 업무 축(command_id)과
구간(trace)의 몫이고, 이 거부가 그 경계를 지킨다.

그리고 `service.name` 으로도 고를 수 없다 — Collector 가 그것을 `job` 라벨로 내보내는데
수집 쪽에서 `exported_job` 으로 바뀐다(`SERVICE_LABEL_AS_SCRAPED`). 컴포넌트를 가르려면
`component` 라벨로 고른다.

예외를 내보내지 않는다
----------------------
AI-O-01: "외부 관측 기능 장애가 실제 기능 실행을 중단시키지 않아야 한다." 그래서
모든 메서드는 `DataState` 를 돌려주는 것으로 실패를 표현하고 던지지 않는다. 호출자
쪽(`FailureTraceService`)도 한 겹 더 감싸지만, 계약은 여기서 지킨다.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from mission_runtime.observability.failure_trace import (
    UNKNOWN_UNIT,
    DataState,
    EventView,
    MetricSeries,
    ObservedEvent,
    SpanRow,
    SpanView,
    TimeWindow,
)
from mission_runtime.observability.layered_metrics import Measurement
from mission_runtime.integration.deployment_topology import (
    PORT_EDGE_METRIC_QUERY,
    COLLECTOR_SCRAPE_INTERVAL_S,
    forbidden_labels_in,
)

#: 질의가 매달리지 않게 하는 상한. 관측 조회가 실패 분석을 멈추게 하면 안 된다.
DEFAULT_TIMEOUT_S = 2.0

_NANOS = 1_000_000_000.0


# ── Prometheus 호환 HTTP 질의 ────────────────────────────────────────────────


@dataclass(frozen=True)
class MetricQueryEndpoint:
    """현재 배포의 계측 질의 엔드포인트. 값은 배포 프로파일에서 온다(AI-C-04).

    구역 엣지가 상세값을 들고 서버는 요약만 받으므로(AI-O-01) 실패 분석은 **엣지의**
    엔드포인트를 본다. 어느 주소인지는 이 자료구조가 받고 코드가 정하지 않는다.
    """

    base_url: str = f"http://127.0.0.1:{PORT_EDGE_METRIC_QUERY}"
    timeout_s: float = DEFAULT_TIMEOUT_S
    #: 창 안에서 몇 점을 받을지. 평균 한 점만 받으면 치솟은 한 번이 묻힌다. 기본값은
    #: 실제 배포가 Collector exporter 를 긁는 간격과 같다 — 더 굵게 잡으면 표본이
    #: 있는데도 건너뛴 점이 생긴다(`deployment_topology.COLLECTOR_SCRAPE_INTERVAL_S`).
    step_s: float = COLLECTOR_SCRAPE_INTERVAL_S


class HttpMetricQueryProvider:
    """Prometheus 호환 `query_range` 로 계측을 읽는다.

    이 이름이 이 파일 밖으로 새지 않는 것이 요점이다 — 상위에서 보이는 것은
    `MetricSeries` 와 `DataState` 뿐이다.
    """

    def __init__(self, endpoint: MetricQueryEndpoint | None = None) -> None:
        self._endpoint = endpoint or MetricQueryEndpoint()

    # -- ObservabilityQueryProvider ---------------------------------------
    def is_reachable(self) -> bool:
        """값이 아니라 **닿는지**를 묻는다. 비어 있는 답도, 거부도 닿은 것이다."""
        url = f"{self._endpoint.base_url.rstrip('/')}/api/v1/query?query=1"
        body, refusal = self._get(url)
        return body is not None or refusal is not None

    def metric_series(
        self, name: str, window: TimeWindow, selector: Mapping[str, str] | None = None
    ) -> MetricSeries:
        refused = forbidden_labels_in(selector)
        if refused:
            # 이 라벨들은 쓰는 쪽에서 거부된다(백엔드 어댑터가 `ValueError`). 그러니
            # 이 선택자로 걸린 시계열은 **존재할 수 없다** — 질의를 보내 봐도 답은
            # 같고, 다만 "왜 비었는지"를 아무도 모르게 된다. 보내지 않고 사유를 적는다.
            # 닿지 못한 것이 아니므로 BACKEND_UNREACHABLE 이 아니고, 네 번째 상태를
            # 만들지도 않는다 — 미측정이고 사유는 `note` 가 들고 다닌다.
            return MetricSeries(
                name=name,
                state=DataState.NOT_SCRAPED,
                note="label refused at write time, so no such series exists: "
                + ", ".join(refused),
            )
        query = _selector_query(name, selector)
        params = urllib.parse.urlencode(
            {
                "query": query,
                "start": f"{window.start:.3f}",
                "end": f"{window.end:.3f}",
                "step": f"{max(self._endpoint.step_s, 0.001):.3f}",
            }
        )
        url = f"{self._endpoint.base_url.rstrip('/')}/api/v1/query_range?{params}"
        body, refusal = self._get(url)
        if body is None and refusal is not None:
            # 백엔드는 답했고 **우리 질의를 거부했다.** 닿지 못한 것이 아니므로
            # BACKEND_UNREACHABLE 이 아니다. 실제로 이렇게 되는 경우가 있다 —
            # 점 구분 OTel 이름을 그대로 물으면 질의 문법에 걸린다(Collector 가
            # `_` 로 바꿔 내보내므로 그 이름은 애초에 없다). 그 사실을 "수집기가
            # 죽었다"로 적으면 사람이 엉뚱한 곳을 본다.
            return MetricSeries(name=name, state=DataState.NOT_SCRAPED, note=refusal)
        if body is None:
            return MetricSeries(
                name=name,
                state=DataState.BACKEND_UNREACHABLE,
                note="metric endpoint unreachable",
            )
        samples = tuple(_parse_range_samples(body))
        if not samples:
            # 닿았는데 이 이름으로 긁힌 표본이 없다. 정상이 아니라 공백이다.
            return MetricSeries(
                name=name, state=DataState.NOT_SCRAPED, note="no samples in window"
            )
        return MetricSeries(name=name, state=DataState.PRESENT, samples=samples)

    def span_view(self, window: TimeWindow, *, trace_id: str | None = None) -> SpanView:
        # 계측 질의 API 에는 구간이 없다. 닿지 못한 것이 아니라 여기에 없는 것이다.
        return SpanView(DataState.NOT_SCRAPED, note="this reader serves metrics only")

    def event_view(self, window: TimeWindow, *, subject_id: str | None = None) -> EventView:
        return EventView(DataState.NOT_SCRAPED, note="this reader serves metrics only")

    # -- 내부 -------------------------------------------------------------
    def _get(self, url: str) -> tuple[dict | None, str | None]:
        """`(본문, 거부 사유)`. 둘 다 None 이면 **닿지 못했다**.

        거부(4xx)와 못 닿음을 가르는 이유는 둘이 다른 사실이고 다른 사람을 부르기
        때문이다 — 거부는 우리 질의가 틀렸다는 뜻이고, 못 닿음은 수집기·망을 봐야
        한다는 뜻이다. 5xx 는 거부가 아니라 백엔드가 답을 못 하는 상태이므로 못
        닿음 쪽으로 둔다.
        """
        try:
            with urllib.request.urlopen(url, timeout=self._endpoint.timeout_s) as response:
                return json.loads(response.read().decode("utf-8", errors="replace")), None
        except urllib.error.HTTPError as error:
            if 400 <= error.code < 500:
                return None, f"metric backend refused the query: {_refusal_text(error)}"
            return None, None
        except (urllib.error.URLError, OSError, socket.timeout, ValueError):
            # 닿지 못함·시간 초과·망가진 본문 — 전부 "값을 못 얻었다" 한 가지로 환산한다.
            return None, None


def _refusal_text(error: urllib.error.HTTPError) -> str:
    """거부 응답에서 사람이 읽을 한 줄. 못 읽으면 상태 코드만 적는다.

    질의 API 는 거부 사유를 본문에 담아 준다(`{"error": "..."}`). 그 문장이 "이름을
    잘못 적었다"를 가장 빠르게 알려 주므로 버리지 않고 **잘라서** 들고 온다.
    """
    fallback = f"HTTP {error.code}"
    try:
        body = json.loads(error.read().decode("utf-8", errors="replace"))
    except (OSError, ValueError, AttributeError):
        return fallback
    message = body.get("error") if isinstance(body, dict) else None
    return f"{fallback}: {str(message)[:200]}" if message else fallback


def _selector_query(name: str, selector: Mapping[str, str] | None) -> str:
    if not selector:
        return name
    labels = ",".join(f'{key}="{value}"' for key, value in sorted(selector.items()))
    return f"{name}{{{labels}}}"


def _parse_range_samples(body: Mapping) -> Iterable[Measurement]:
    """`data.result[*].values` → `Measurement`. 파싱 못한 점은 **버린다**.

    못 읽은 점을 0 으로 채우면 유휴와 고장이 같아진다(AI-O-05). 하나도 못 읽으면
    표본이 비고 호출자는 NOT_SCRAPED 로 적는다.
    """
    data = body.get("data") or {}
    for series in data.get("result") or []:
        for point in series.get("values") or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                yield Measurement(float(point[1]), UNKNOWN_UNIT, at=float(point[0]))
            except (TypeError, ValueError):
                continue


# ── Collector 파일 exporter 출력 ─────────────────────────────────────────────


class CollectorFileExportReader:
    """OTel Collector 의 파일 exporter 출력(NDJSON OTLP)을 읽는다.

    현재 개발·시험 스택(`deploy/integration/docker-compose.yml`)의 collector 가 metric·
    log·trace 세 pipeline 을 모두 한 파일로 내보낸다. 폐쇄망 배치에서도 쓸 수 있는
    경로다 — 질의 서버가 없어도 파일은 있다(AI-C-16).

    한 줄이 깨져 있어도 나머지를 읽는다. 관측 파일은 여러 프로세스가 덧붙이는 중일
    수 있어서 마지막 줄이 잘려 있는 것이 정상 상태다.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def is_reachable(self) -> bool:
        return self._path.is_file()

    def metric_series(
        self, name: str, window: TimeWindow, selector: Mapping[str, str] | None = None
    ) -> MetricSeries:
        documents = self._read()
        if documents is None:
            return MetricSeries(
                name=name, state=DataState.BACKEND_UNREACHABLE, note="export file not readable"
            )
        samples: list[Measurement] = []
        for doc in documents:
            for resource in doc.get("resourceMetrics") or []:
                for scope in resource.get("scopeMetrics") or []:
                    for metric in scope.get("metrics") or []:
                        if metric.get("name") != name:
                            continue
                        samples.extend(_metric_points(metric, window, selector))
        if not samples:
            return MetricSeries(
                name=name, state=DataState.NOT_SCRAPED, note="no data points in window"
            )
        samples.sort(key=lambda m: m.at if m.at is not None else 0.0)
        return MetricSeries(name=name, state=DataState.PRESENT, samples=tuple(samples))

    def span_view(self, window: TimeWindow, *, trace_id: str | None = None) -> SpanView:
        documents = self._read()
        if documents is None:
            return SpanView(DataState.BACKEND_UNREACHABLE, note="export file not readable")
        rows: list[SpanRow] = []
        for doc in documents:
            for resource in doc.get("resourceSpans") or []:
                for scope in resource.get("scopeSpans") or []:
                    for span in scope.get("spans") or []:
                        row = _span_row(span)
                        if trace_id is not None and row.trace_id != trace_id:
                            continue
                        if not window.contains(row.started_at):
                            continue
                        rows.append(row)
        if not rows:
            return SpanView(DataState.NOT_SCRAPED, note="no spans in window")
        rows.sort(key=lambda r: r.started_at if r.started_at is not None else 0.0)
        return SpanView(DataState.PRESENT, tuple(rows))

    def event_view(self, window: TimeWindow, *, subject_id: str | None = None) -> EventView:
        documents = self._read()
        if documents is None:
            return EventView(DataState.BACKEND_UNREACHABLE, note="export file not readable")
        events: list[ObservedEvent] = []
        for doc in documents:
            for resource in doc.get("resourceLogs") or []:
                for scope in resource.get("scopeLogs") or []:
                    for record in scope.get("logRecords") or []:
                        event = _log_event(record)
                        if not window.contains(event.at):
                            continue
                        if subject_id is not None and event.subject_id not in (None, subject_id):
                            continue
                        events.append(event)
        if not events:
            return EventView(DataState.NOT_SCRAPED, note="no events in window")
        return EventView(DataState.PRESENT, tuple(events))

    def _read(self) -> list[dict] | None:
        try:
            text = self._path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        documents: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                documents.append(parsed)
        return documents


def _attr_pairs(attributes) -> tuple[tuple[str, str], ...]:
    """OTLP 속성 배열 → 평평한 (key, value) 쌍. 값은 전부 문자열로 둔다."""
    out: list[tuple[str, str]] = []
    for item in attributes or []:
        key = item.get("key")
        if key is None:
            continue
        out.append((str(key), _any_value(item.get("value"))))
    return tuple(out)


def _any_value(value) -> str:
    if not isinstance(value, dict):
        return "" if value is None else str(value)
    for field_name in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if field_name in value:
            return str(value[field_name])
    return json.dumps(value, sort_keys=True)


def _metric_points(
    metric: Mapping, window: TimeWindow, selector: Mapping[str, str] | None
) -> list[Measurement]:
    out: list[Measurement] = []
    # gauge 와 sum 만 읽는다. histogram 은 분포이고 한 점으로 접으면 그 자체가
    # 요약 손실이라 여기서 만들지 않는다 — 없는 값을 지어내지 않는 쪽을 택한다.
    for container_name in ("gauge", "sum"):
        container = metric.get(container_name) or {}
        for point in container.get("dataPoints") or []:
            at = _nano_to_epoch(point.get("timeUnixNano"))
            if not window.contains(at):
                continue
            if selector and not _selector_matches(point.get("attributes"), selector):
                continue
            value = point.get("asDouble", point.get("asInt"))
            if value is None:
                continue
            try:
                out.append(Measurement(float(value), UNKNOWN_UNIT, at=at))
            except (TypeError, ValueError):
                continue
    return out


def _selector_matches(attributes, selector: Mapping[str, str]) -> bool:
    present = dict(_attr_pairs(attributes))
    return all(present.get(key) == value for key, value in selector.items())


def _span_row(span: Mapping) -> SpanRow:
    start = _nano_to_epoch(span.get("startTimeUnixNano"))
    end = _nano_to_epoch(span.get("endTimeUnixNano"))
    duration_ms = None if start is None or end is None else max(0.0, (end - start) * 1000.0)
    status = span.get("status") or {}
    # OTLP 는 UNSET(0) 일 때 code 를 아예 내보내지 않는다. 없음을 "오류 아님"으로
    # 읽는 쪽이 맞지만, 상태 문자열은 들고 온 것만 적는다.
    status_text = status.get("message") or (
        str(status.get("code")) if status.get("code") is not None else None
    )
    return SpanRow(
        name=str(span.get("name") or ""),
        span_id=str(span.get("spanId") or ""),
        trace_id=str(span["traceId"]) if span.get("traceId") else None,
        parent_span_id=str(span["parentSpanId"]) if span.get("parentSpanId") else None,
        duration_ms=duration_ms,
        status=status_text,
        started_at=start,
        attributes=_attr_pairs(span.get("attributes")),
    )


def _log_event(record: Mapping) -> ObservedEvent:
    attributes = _attr_pairs(record.get("attributes"))
    payload = dict(attributes)
    name = record.get("eventName") or payload.get("event.name") or _any_value(record.get("body"))
    at = _nano_to_epoch(record.get("timeUnixNano") or record.get("observedTimeUnixNano"))
    return ObservedEvent(
        name=str(name or ""),
        # severityText 가 비면 등급을 **지어내지 않는다** — 알 수 없음은 치명이 아니다.
        severity=str(record.get("severityText") or "").lower() or "unknown",
        at=at,
        payload=attributes,
        subject_id=payload.get("subject_id") or payload.get("mission_id"),
    )


def _nano_to_epoch(value) -> float | None:
    try:
        return float(value) / _NANOS
    except (TypeError, ValueError):
        return None


# ── 백엔드가 없는 노드 ───────────────────────────────────────────────────────


class LocalEventQueryProvider:
    """쓰는 provider 의 **로컬 사건 버퍼**를 읽는다.

    AI-O-02: "외부 수집기가 일시적으로 사용할 수 없어도 로컬 오류 기록은 남아야 한다."
    그 기록이 남아 있다면 수집기가 없는 노드에서도 실패 분석은 치명 사건만큼은 볼 수
    있다. 이 reader 가 그 길이고, 말단 경량 실행 경계(AI-B-10)에서 유일하게 가능한
    길이기도 하다 — 말단에는 질의 서버가 없다.

    `local_events()` 를 내놓는 것(`providers/otel.py`)과 `.events` 를 들고 있는 것
    (`providers/fakes.py`)을 모두 받는다. 두 자료형을 한쪽으로 통일하라고 요구하지
    않는다 — 둘 다 이미 배포된 계약이다.
    """

    def __init__(self, write_side_provider) -> None:
        self._provider = write_side_provider

    def is_reachable(self) -> bool:
        return self._records() is not None

    def metric_series(
        self, name: str, window: TimeWindow, selector: Mapping[str, str] | None = None
    ) -> MetricSeries:
        # 로컬 버퍼에는 계측 이력이 없다. 닿지 못한 것이 아니라 여기에 없는 것이다.
        return MetricSeries(
            name=name, state=DataState.NOT_SCRAPED, note="local event buffer has no metric history"
        )

    def span_view(self, window: TimeWindow, *, trace_id: str | None = None) -> SpanView:
        return SpanView(DataState.NOT_SCRAPED, note="local event buffer has no spans")

    def event_view(self, window: TimeWindow, *, subject_id: str | None = None) -> EventView:
        records = self._records()
        if records is None:
            return EventView(DataState.BACKEND_UNREACHABLE, note="no local event buffer")
        events = [_from_local_record(record) for record in records]
        events = [e for e in events if window.contains(e.at)]
        if subject_id is not None:
            events = [e for e in events if e.subject_id in (None, subject_id)]
        if not events:
            return EventView(DataState.NOT_SCRAPED, note="no local events in window")
        return EventView(DataState.PRESENT, tuple(events))

    def _records(self) -> list | None:
        getter = getattr(self._provider, "local_events", None)
        if callable(getter):
            try:
                return list(getter())
            except Exception:
                return None
        records = getattr(self._provider, "events", None)
        return list(records) if records is not None else None


def _from_local_record(record) -> ObservedEvent:
    payload = getattr(record, "payload", None) or {}
    pairs = tuple((str(k), str(v)) for k, v in payload.items())
    return ObservedEvent(
        name=str(getattr(record, "name", "")),
        severity=str(getattr(record, "severity", "unknown")).lower(),
        # 버퍼에 시각이 없는 구현도 있다. 지어내지 않고 None 으로 둔다 —
        # `TimeWindow.contains(None)` 이 그런 사건을 창 밖으로 버리지 않는다.
        at=getattr(record, "at", None),
        payload=pairs,
        subject_id=payload.get("subject_id") or payload.get("mission_id"),
    )


# ── 축별 조합 ────────────────────────────────────────────────────────────────


class CompositeQueryProvider:
    """축마다 다른 reader 를 붙인다. 한 축이 비어도 다른 축은 그대로 답한다.

    현재 배포가 정확히 이 모양이다 — 계측은 엣지 Prometheus 가, log·trace 는
    Collector 가 들고 있다(`integration/deployment_topology.py` §관측). 한 쪽이
    꺼졌을 때 나머지를 못 쓰게 만들지 않는 것이 AI-C-05 의 요구다.
    """

    def __init__(self, *, metrics=None, spans=None, events=None) -> None:
        self._metrics = metrics
        self._spans = spans
        self._events = events

    def is_reachable(self) -> bool:
        """하나라도 닿으면 닿는다. 전부 죽었을 때만 못 닿는다고 말한다."""
        for reader in (self._metrics, self._spans, self._events):
            if reader is None:
                continue
            try:
                if reader.is_reachable():
                    return True
            except Exception:
                continue
        return False

    def metric_series(
        self, name: str, window: TimeWindow, selector: Mapping[str, str] | None = None
    ) -> MetricSeries:
        if self._metrics is None:
            return MetricSeries(
                name=name, state=DataState.BACKEND_UNREACHABLE, note="no metric reader configured"
            )
        return self._metrics.metric_series(name, window, selector)

    def span_view(self, window: TimeWindow, *, trace_id: str | None = None) -> SpanView:
        if self._spans is None:
            return SpanView(DataState.BACKEND_UNREACHABLE, note="no span reader configured")
        return self._spans.span_view(window, trace_id=trace_id)

    def event_view(self, window: TimeWindow, *, subject_id: str | None = None) -> EventView:
        if self._events is None:
            return EventView(DataState.BACKEND_UNREACHABLE, note="no event reader configured")
        return self._events.event_view(window, subject_id=subject_id)
