"""C층 — 업무 값의 관측 표현 파생 (00-architecture §8-3, 결정 5).

저장 소비자가 계측 1건을 저장한 **다음 줄**에서 부른다. 값을 받은 쪽이 파생하므로 말단은 업무 채널로
한 번만 보낸다(말단이 두 번 보내지 않는다). **원본은 여전히 TSDB·MySQL이고 이 신호는 사본이다** —
조회·감사·학습 재료를 관측 저장소에서 끌어오지 않는다(원칙 4, §8-3 제약 2).

## 조건 둘 (결정 5-a)

1. **파생 실패가 저장을 막지 않는다.** 예외는 여기서 전부 삼킨다(한 번만 로그).
2. **저장 성공 여부와 무관하게 파생한다.** `tsdb_writer._fail()`이 예외를 삼키고 소비는 계속되므로,
   TSDB가 죽어도 C층은 계속 나온다. ingest 에서 파생하면 produce 실패 시 원본과 어긋난다.

## 대상은 규격에서 읽는다 (원칙 9)

`contracts/common/payload/*.schema.json`의 `$comment` 힌트가 기준이다(`contracts.hints_of_schema`).
파이썬에 목록을 다시 적지 않는다. 이번 Phase 는 **gauge 9 + counter 3 = 12개**만 계측하고
**log/event 10개는 Phase 5 이월**이다(전부 상태 어휘라 "언제 바뀌었나"의 판정이 가용성의 일이고,
지금 그대로 내면 로봇 1대당 초당 60줄이 Loki 로 간다).

## 계기 이름 (지시서 7-2 표 그대로)

`be.telemetry.<항목 경로>` — 단 **`state.analysis` 규격의 항목**만 `be.telemetry.analysis.<항목>` 이다
(`value` 처럼 일반 명사라 접두사 없이는 무엇의 값인지 알 수 없다). 중첩은 점으로 잇는다
(`be.telemetry.buffer.pending`). ⚠ 접두사는 **규격**이 정하지 개체 타입이 정하지 않는다 — `status`는
타입 공통 규격이라 증강 분석이 보낸 `status`의 `uptime_s`도 `be.telemetry.uptime_s`다(타입은 라벨).
2026-09-16 서버 실측에서 타입만 보고 붙였다가 `be_telemetry_analysis_uptime_s` 등 5종이 잘못 생겨 고쳤다.

⚠ **counter 힌트 3개(`buffer.dropped`·`buffer.thinned`·`publish_failures`)는 gauge 계기로 낸다.**
말단이 보내는 것이 **절대 누적값**이라 델타를 만들려면 직전 값을 들고 있어야 하는데, 그것은 Phase 2가
세운 무상태 원칙과 충돌한다. 절대값을 그대로 기록하고 이름에 `_total`을 붙이지 않는다 — 조회에서
증가분이 필요하면 `increase()`가 아니라 `delta()`/`deriv()`를 쓴다.

## 값 꺼내기 (지시서 7-3)

1. `{value, state}` 형태는 벗긴다(`water_level_m`·`battery_pct`, `x-mk2-absence: stateful`). `value`가
   `null`이면 **기록하지 않는다** — 0을 넣으면 "값 없음"이 "0"이 된다(음성 대조 N4).
2. 명시적 `null`은 기록하지 않는다(`trend_m_per_min`·`eta_to_threshold_min`의 판단 보류).
3. `status.buffer`가 통째로 없을 수 있다(LWT). 없으면 그 셋을 건너뛴다.
4. `entity_type`이 `None`(헤더 없는 옛 메시지)이면 라벨을 `unknown`으로 채우고 기록은 계속한다 —
   어댑터 `check_labels()`가 그렇게 한다(7-3-a).

라벨: `source_id` · `zone_id` · `entity_type` · `channel` (결정 4-b — A층과 기준이 다르다).

implements: BE-S-02 (C층 — 업무 값의 관측 표현)
tests: tests/test_c_layer_extract.py — 힌트 파싱 검산 · 계기 이름 12종 · {value,state} 벗기기 · null 미기록(음성) · LWT buffer 부재 ·
       tests/test_observability_pipeline.py — be_telemetry_* 가 Prometheus 에 도달, null 발행 시 시계열 미생성(N4)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend import contracts
from backend import observability as obs
from backend.storage.writer import TelemetryRecord

LOG = logging.getLogger("mk2.storage.derive")

INSTRUMENT_PREFIX = "be.telemetry."
# 이 Phase 가 계측하는 힌트 종류. log/event 는 Phase 5 (상태 전이 판정과 함께).
METRIC_KINDS = ("gauge", "counter")
# 계기 이름에 타입 접두사를 붙이는 규격 — 항목 이름이 일반 명사(value)라 구분이 필요하다.
PREFIXED_ENTITY_TYPES = ("analysis",)

_failed_once: set = set()


def instrument_name(channel: str, entity_type: Optional[str], path: str) -> str:
    """(채널, 개체 타입, 항목 경로) → OTel 계기 이름. 지시서 7-2 표의 규칙이다.

    접두사는 **타입별 규격(`state.<etype>`)일 때만** 붙는다. `status`·`heartbeat`는 타입 공통 규격이라
    어느 타입이 보냈든 같은 이름이고 타입은 라벨(`entity_type`)로 갈린다.
    """
    if channel == "state" and entity_type in PREFIXED_ENTITY_TYPES:
        return f"{INSTRUMENT_PREFIX}{entity_type}.{path}"
    return f"{INSTRUMENT_PREFIX}{path}"


def metric_targets(channel: str, entity_type: Optional[str]) -> Tuple[Tuple[str, str, str], ...]:
    """(채널, 개체 타입)에서 이번 Phase 가 계측할 (항목 경로, 힌트 종류, 계기 이름) 목록.

    규격 파일에서 유도한다. 규격이 없으면(모르는 타입·헤더 없는 state) 빈 튜플.
    """
    return tuple(
        (hint.path, hint.kind, instrument_name(channel, entity_type, hint.path))
        for hint in contracts.hints_of_schema(channel, entity_type)
        if hint.kind in METRIC_KINDS
    )


def all_metric_instruments() -> Tuple[str, ...]:
    """이번 Phase 의 C층 계기 이름 전수(12종) — 규격에서 유도. 문서 표·테스트 검산용."""
    names: List[str] = []
    for entity_type in contracts.known_entity_types():
        names.extend(name for _, _, name in metric_targets("state", entity_type))
    for channel in contracts.CHANNEL_SCOPED:
        names.extend(name for _, _, name in metric_targets(channel, None))
    return tuple(sorted(set(names)))


def unwrap(value: Any) -> Any:
    """`{value, state}` 형태를 벗긴다. 그 밖의 값은 그대로."""
    if isinstance(value, dict) and "value" in value and "state" in value:
        return value.get("value")
    return value


def extract_value(message: Dict[str, Any], path: str) -> Optional[float]:
    """본문에서 항목 경로의 **수치**를 꺼낸다. 없거나 `null`이거나 수치가 아니면 `None`(= 기록하지 않는다).

    - 중첩 경로(`buffer.pending`)는 한 단계씩 내려간다. 중간이 없거나 `null`이면 `None`(LWT의 `buffer` 부재).
    - `{value, state}`는 벗긴 뒤 본다.
    - `bool`은 수치가 아니다(파이썬에서 `bool`이 `int`의 하위 타입이라 따로 막는다).
    """
    node: Any = message
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = unwrap(node.get(part))
        if node is None:
            return None
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return float(node)


def derive(record: TelemetryRecord, sink: Callable[..., None] = obs.gauge) -> int:
    """계측 1건에서 C층 신호를 뽑아 `sink(name, value, **labels)`로 낸다. 낸 개수를 돌려준다.

    `sink`는 기본이 어댑터의 `gauge()`다(counter 힌트도 절대값이라 gauge). 테스트가 바꿔 끼운다.
    **예외를 밖으로 내지 않는다** — 파생 실패가 저장·소비를 막지 않는다.
    """
    try:
        targets = metric_targets(record.channel, record.entity_type)
        if not targets:
            return 0
        message = record.message
        labels = {
            "source_id": message.get("source_id"),
            "zone_id": message.get("zone_id"),
            "entity_type": record.entity_type,     # None 이면 어댑터가 "unknown" 으로 채운다
            "channel": record.channel,
        }
        emitted = 0
        for path, _kind, name in targets:
            value = extract_value(message, path)
            if value is None:
                continue                            # null·부재는 시계열을 만들지 않는다 (N4)
            sink(name, value, **labels)
            emitted += 1
        return emitted
    except Exception as exc:  # noqa: BLE001 - 파생 실패가 저장을 막지 않는다
        key = type(exc).__name__
        if key not in _failed_once:
            _failed_once.add(key)
            LOG.error(
                "C층 파생 실패(이후 같은 종류는 조용히 지나간다): channel=%s etype=%s source_id=%s / %s: %s",
                record.channel, record.entity_type, record.message.get("source_id"), key, exc,
            )
        return 0
