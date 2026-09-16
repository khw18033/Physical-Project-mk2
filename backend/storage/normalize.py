"""조회 시 채널 본문의 빠진 키를 규격대로 채워 돌려주는 **읽기 함수**.

**저장은 원본 그대로다**(원칙 4 — 계측의 원본은 TSDB). 저장 시점에 `null`을 채워 넣으면
저장된 것이 더는 원본이 아니게 되고, 나중에 "생산자가 안 보낸 것"과 "백엔드가 채운 것"을
구분할 수 없다. 그래서 채우는 일은 쓰기가 아니라 **읽기**에서 한다.

채우는 목적은 하나다 — **소비자(트윈·로봇 제어·화면)가 생산자 구성 변화에 흔들리지 않게
하는 것.** 항목을 생략하면 소비자가 매번 키 존재를 확인해야 하고, "아예 없는 항목"과
"지금 값이 없는 것"을 구분할 수 없다. 키 구조를 고정하면 생산자 하나를 빼고 다른 것을
붙여도 소비자 코드가 그대로다(`contracts/common/README.md` "값이 없을 때의 표현").

**항목 목록을 파이썬에 다시 적지 않는다.** `contracts/common/payload/*.schema.json`을 직접
읽어 얻는다 — `envelope.py`가 규격 파일을 그대로 로드해 검증하는 것과 같은 방식이다.
두 벌이 되면 조용히 어긋나고, 어긋난 뒤에는 어느 쪽이 맞는지 알 수 없다.

이 함수를 실제로 쓰는 것은 조회 층(Phase 5/6)이다. Phase 2는 함수와 pytest까지다.

implements: BE-C-01 (누락값 표현), BE-S-01 (계측 조회의 키 구조)
tests: tests/test_payload_contract.py::test_normalize_payload_fills_keys
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from backend import contracts

# 부재 사유를 구분해야 하는 항목이 빠졌을 때 채우는 값.
#
# `unavailable`(있을 수 있는데 지금 값이 없다)로 채우고 `unsupported`(이 배포 구성에 그
# 생산자가 없다)로 채우지 않는 이유: 배포 구성에 그 생산자가 있는지는 **레지스트리 선언
# 축이 아는 것**이고 이 함수는 모른다. 모르는 것을 단정하면 화면이 "해당 없음"으로 그려
# 실제 장애를 숨긴다. 생산자가 사유를 알면 스스로 `{value, state}` 형태로 보내면 되고,
# 그 값은 아래에서 덮어쓰지 않는다.
ABSENT_STATEFUL: Dict[str, Any] = {"value": None, "state": "unavailable"}


def _absent(spec: Mapping[str, Any]) -> Any:
    """규격이 그 항목을 어떻게 비워 표현하라고 했는지에 따라 채울 값을 고른다."""
    if spec.get("x-mk2-absence") == "stateful":
        return dict(ABSENT_STATEFUL)
    return None


def _fill_nested(spec: Mapping[str, Any], value: Any) -> Any:
    """항목이 **있는데** 그 안의 하위 키가 빠진 경우만 한 단계 더 채운다.

    항목 자체가 없는 것(`position`이 통째로 없다)과 항목은 있는데 하위 키가 없는 것
    (`buffer`는 있는데 `thinned`가 없다)은 다른 사건이라 다르게 다룬다. 전자는 `null`로
    남기고 후자만 채운다.

    `oneOf`로 여러 형태를 허용하는 항목(계측값·registration)은 어느 가지인지 단정할 수
    없으므로 손대지 않는다 — 추측해서 채우면 원본 해석이 틀어진다.
    """
    if value is None or "oneOf" in spec:
        return value
    sub = spec.get("properties")
    if not sub or not isinstance(value, dict):
        return value
    filled = dict(value)
    for name, sub_spec in sub.items():
        if name not in filled:
            filled[name] = _absent(sub_spec if isinstance(sub_spec, Mapping) else {})
    return filled


def normalize_payload(
    channel: str,
    entity_type: Optional[str],
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """규격의 항목 목록대로 빠진 키를 채운 **새 dict**를 돌려준다.

    - 원본을 바꾸지 않는다(입력은 그대로 두고 사본을 돌려준다).
    - 이미 있는 값은 절대 덮지 않는다 — 명시적 `null`도 "값이 없다"는 정보이므로 유지한다.
    - 규격이 없는 조합(모르는 개체 타입 등)은 **손대지 않고 사본만** 돌려준다. 모르는
      타입의 본문을 우리가 아는 모양으로 채우면 그 순간 사실이 아닌 것이 생긴다.
    """
    schema = contracts.load_payload_schema(channel, entity_type)
    normalized: Dict[str, Any] = dict(payload)
    if schema is None:
        return normalized

    for name, spec in schema.get("properties", {}).items():
        if not isinstance(spec, Mapping):
            continue
        if name in normalized:
            normalized[name] = _fill_nested(spec, normalized[name])
        else:
            normalized[name] = _absent(spec)
    return normalized
