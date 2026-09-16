"""채널 본문 규격 파일의 위치와 로드 — ingest(검증)와 storage(정규화)의 공통 진입점.

파트 경계의 기준은 `contracts/common/`의 JSON Schema이지 파이썬 타입이 아니다(원칙 9).
그래서 **항목 목록을 파이썬에 다시 적지 않는다** — 규격 파일을 직접 읽어 얻는다. 두 벌이
되면 조용히 어긋나고, 어긋난 쪽이 어느 쪽인지 나중에는 알 수 없다.

이 모듈이 따로 있는 이유는 소비자가 둘이기 때문이다:

- `backend/ingest/envelope.py` — 수신 시 본문을 검증한다(2단 검증의 2단).
- `backend/storage/normalize.py` — 조회 시 없는 키를 규격대로 채운다.

둘 중 한쪽에 두면 storage가 ingest를 import하거나 그 반대가 되어 방향이 뒤집힌 의존이
생긴다. 규격 로드는 어느 쪽의 관심사도 아니므로 밖으로 뺀다.

**타입 판별의 근거는 파이썬 목록이 아니라 파일 목록이다.** `state.{etype}.schema.json`이
있는 etype만 타입별 본문 검증 대상이고, 새 타입은 스키마 파일을 추가하는 것으로 는다.

세 번째 소비자(Phase 3): `backend/storage/derive.py` — C층(업무 값의 관측 표현)의 **대상 목록을
규격 파일의 `$comment` 힌트에서 읽는다**(`observation_hints()`). 파이썬에 목록을 다시 적지 않는다.

implements: BE-C-01 (채널 본문 규격), BE-S-02 (C층 대상 = 규격의 관측 신호 힌트)
tests: tests/test_payload_contract.py — 규격 로드·타입 판별 ·
       tests/test_c_layer_extract.py — 힌트 파싱이 27곳 → gauge 9 · counter 3 · log/event 10 을 뽑는다(중첩 포함)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend import settings

PAYLOAD_DIR_NAME = "payload"

# ── 관측 신호 힌트 (C층 대상의 기준) ────────────────────────────────────────
# 규격 항목의 `$comment` 가 "관측 신호 힌트: <종류>" 로 시작하면 그 항목이 C층 대상이다.
# 종류 어휘는 00-architecture §8-3 의 매핑 그대로 — gauge · counter · log/event (· histogram · trace).
HINT_MARKER = "관측 신호 힌트:"
HINT_KINDS = ("gauge", "counter", "log/event", "histogram", "trace")


@dataclass(frozen=True)
class ObservationHint:
    """규격 항목 하나에 달린 관측 신호 힌트.

    키는 **(채널, 개체 타입, 항목 경로)** 다 — `state`는 타입별 규격 4종이라 같은 항목 이름
    (`reason`·`device_status`)이 여러 규격에 나오고, `status`·`heartbeat`는 타입 공통(`entity_type=None`).
    `path`는 중첩을 점으로 잇는다(`buffer.pending`).
    """

    channel: str
    entity_type: Optional[str]
    path: str
    kind: str

    @property
    def item(self) -> str:
        """중복을 접을 때 쓰는 항목 이름(경로). 전수 검산의 단위다."""
        return self.path

# 본문 규격이 채널별로 하나뿐인 채널(타입에 무관하게 같은 본문을 쓴다).
# `state`만 타입별로 갈린다 — 센서·로봇·액추에이터·증강 분석의 본문이 서로 완전히 다르다.
CHANNEL_SCOPED = ("status", "heartbeat")

_schema_cache: Dict[Path, Dict[str, Any]] = {}


def payload_dir() -> Path:
    """채널 본문 규격 디렉터리."""
    return settings.contracts_dir() / PAYLOAD_DIR_NAME


def payload_schema_path(channel: str, entity_type: Optional[str]) -> Optional[Path]:
    """(채널, 개체 타입) → 본문 규격 파일. 대상이 없으면 `None`.

    `None`이 돌아오는 것은 오류가 아니라 **"이 조합은 본문 검증을 건너뛴다"**는 뜻이다.
    모르는 etype이 첫 메시지부터 격리되면 안 되기 때문이다 — 새 노드 타입이 붙는 순간
    파이프라인이 막히는 것이 규격 위반보다 나쁘다. 호출부가 기록만 남기고 통과시킨다.
    """
    directory = payload_dir()
    if channel in CHANNEL_SCOPED:
        path = directory / f"{channel}.schema.json"
        return path if path.is_file() else None
    if channel == "state":
        if not entity_type:
            return None
        # 경로 조작 방지: etype은 토픽에서 온 외부 입력이다.
        if "/" in entity_type or "\\" in entity_type or entity_type.startswith("."):
            return None
        path = directory / f"state.{entity_type}.schema.json"
        return path if path.is_file() else None
    return None


def load_payload_schema(channel: str, entity_type: Optional[str]) -> Optional[Dict[str, Any]]:
    """본문 규격을 읽어 돌려준다(파일당 1회 로드 후 캐시). 대상이 없으면 `None`."""
    path = payload_schema_path(channel, entity_type)
    if path is None:
        return None
    cached = _schema_cache.get(path)
    if cached is None:
        cached = json.loads(path.read_text(encoding="utf-8"))
        _schema_cache[path] = cached
    return cached


def known_entity_types() -> Tuple[str, ...]:
    """`state` 본문 규격이 존재하는 개체 타입 목록.

    파이썬에 어휘를 적지 않고 파일에서 유도한다 — 새 타입은 스키마 파일을 추가하는 것으로
    늘고, 목록이 코드와 어긋날 여지가 없다.
    """
    directory = payload_dir()
    if not directory.is_dir():
        return ()
    names = sorted(p.name[len("state."):-len(".schema.json")] for p in directory.glob("state.*.schema.json"))
    return tuple(names)


def stateful_absence_fields(schema: Dict[str, Any]) -> Tuple[str, ...]:
    """부재 사유를 구분해야 하는 항목 이름들(`x-mk2-absence: stateful`).

    이 표시도 규격 파일 안에 있다 — 어느 항목이 어느 형태인지는 규격이 정하는 것이지
    파이썬이 정하는 것이 아니다. JSON Schema는 모르는 키워드를 무시하므로 검증에는
    영향이 없고 주석 겸 기계 판독 표시로만 쓰인다.
    """
    props = schema.get("properties", {})
    return tuple(name for name, spec in props.items()
                 if isinstance(spec, dict) and spec.get("x-mk2-absence") == "stateful")


def parse_hint(comment: Any) -> Optional[str]:
    """`$comment` 문자열에서 신호 종류 힌트를 꺼낸다. 마커가 없으면 `None`(= C층 대상이 아니다).

    파싱 규약(지시서 7-1): 마커 `관측 신호 힌트:` **뒤의 첫 낱말**이 종류다. 그 뒤에 붙은 설명
    (`. 범위를 강제하지 않는다 …`)은 무시한다. 낱말 끝의 마침표는 떼어 낸다.
    """
    if not isinstance(comment, str) or HINT_MARKER not in comment:
        return None
    tail = comment.split(HINT_MARKER, 1)[1].strip()
    if not tail:
        return None
    word = tail.split()[0].rstrip(".,;")
    return word if word in HINT_KINDS else None


def _walk_hints(properties: Dict[str, Any], channel: str, entity_type: Optional[str], prefix: str,
                out: List[ObservationHint]) -> None:
    """`properties`를 **재귀로** 훑는다 — `status.buffer`의 `pending`·`dropped`·`thinned` 셋이 중첩에 있다.

    항목이 `oneOf`로 형태를 여럿 허용해도(`{value, state}` 등) 힌트는 항목 자체의 `$comment`에 있으므로
    `oneOf` 안까지 내려가지 않는다. 중첩 객체의 `properties`만 따라간다.
    """
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        path = f"{prefix}{name}"
        kind = parse_hint(spec.get("$comment"))
        if kind is not None:
            out.append(ObservationHint(channel=channel, entity_type=entity_type, path=path, kind=kind))
        nested = spec.get("properties")
        if isinstance(nested, dict):
            _walk_hints(nested, channel, entity_type, path + ".", out)


def hints_of_schema(channel: str, entity_type: Optional[str]) -> Tuple[ObservationHint, ...]:
    """(채널, 개체 타입) 규격 하나의 힌트 목록. 규격이 없으면 빈 튜플."""
    schema = load_payload_schema(channel, entity_type)
    if schema is None:
        return ()
    found: List[ObservationHint] = []
    _walk_hints(schema.get("properties", {}), channel, entity_type, "", found)
    return tuple(found)


def observation_hints() -> Tuple[ObservationHint, ...]:
    """규격 6종 전체의 관측 신호 힌트 — **C층 대상의 기준.** 파이썬에 목록을 적지 않고 파일에서 유도한다.

    전수 검산(2026-09-10 규격 기준): **27곳**에 힌트가 붙어 있고, 항목 경로로 중복을 접으면
    **gauge 9 · counter 3 · log/event 10 = 22개**다(`reason`·`device_status`가 여러 규격에 나온다).
    이 숫자가 안 나오면 파싱이 틀린 것이다 — `tests/test_c_layer_extract.py`가 못 박는다.
    """
    found: List[ObservationHint] = []
    for entity_type in known_entity_types():
        found.extend(hints_of_schema("state", entity_type))
    for channel in CHANNEL_SCOPED:
        found.extend(hints_of_schema(channel, None))
    return tuple(found)


def hint_items_by_kind(hints: Optional[Tuple[ObservationHint, ...]] = None) -> Dict[str, Tuple[str, ...]]:
    """종류별로 **항목 경로를 접은** 목록. 검산과 문서 표 갱신의 재료다.

    같은 항목이 규격마다 다른 종류로 달려 있으면 그것은 규격 오류이므로 `ValueError`.
    """
    hints = observation_hints() if hints is None else hints
    kind_of: Dict[str, str] = {}
    for hint in hints:
        previous = kind_of.get(hint.item)
        if previous is not None and previous != hint.kind:
            raise ValueError(f"항목 {hint.item!r} 의 힌트가 규격마다 다르다: {previous} vs {hint.kind}")
        kind_of[hint.item] = hint.kind
    grouped: Dict[str, List[str]] = {}
    for item, kind in kind_of.items():
        grouped.setdefault(kind, []).append(item)
    return {kind: tuple(sorted(items)) for kind, items in grouped.items()}


def reset_cache() -> None:
    """테스트에서 규격 파일을 바꿔 끼울 때 쓴다."""
    _schema_cache.clear()
