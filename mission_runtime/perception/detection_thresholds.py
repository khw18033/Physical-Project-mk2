"""Detection thresholds as declared data, each carrying where its number came from.

implements: AI-S-08 (사전정보는 출처·버전·유효범위를 갖고 관측과 구분된다)
관련: AI-B-01 (임계값을 바꾸면 다른 실행 구성이다), AI-C-15 (도메인 차이는 설정),
      AI-C-18 (선언 규약), AI-S-04 (하한이 없다고 객체를 버리지 않는다),
      AI-L-03 (운영자 수정은 선언을 덮지 않는다), 원칙 #1·#7·#8
tests: tests/test_detection_thresholds.py

왜 이 파일이 있는가
-------------------
탐지기의 점수 하한은 코드 상수였다 — `edge/yoloe_provider.py::DEFAULT_CONF = 0.05`,
`edge/grounding_dino_provider.py::DEFAULT_BOX_THRESHOLD = 0.15`. 그 수를 고치려면
저장소를 고치고 다시 배포해야 했고, **그 수가 어디서 나왔는지는 아무 데도 적혀 있지
않았다.** 운영자는 그림 한 장에 돌려 보고 "이 현장에서는 0.4 가 맞다" 를 알지만
그 판단을 적을 자리가 없었다.

그래서 임계값을 선언으로 옮긴다. 다만 **값만 옮기면 더 나빠진다** — 주석이 달린
상수가 출처 없는 설정값보다 낫다. 그래서 선언 하나는 넷을 함께 들고 다닌다.

값
    `value`. `None` 은 **아직 아무도 선언하지 않았다**이고 0 도 "미달" 도 아니다.
무엇에 적용되는가
    `applies_to` — 탐지기·어휘·클래스·라벨 이름공간 중 해당하는 축만. 축이 `None`
    인 것은 "그 축으로 한정하지 않는다" 이고 "모른다" 가 아니다.
어디서 왔는가
    `provenance.source`. 코드 상수에서 옮겨 적었으면 그 사실을 적는다.
재서 나온 값인가
    `provenance.measured`. 손으로 맞춘 값과 실측값을 **같은 칸에 담지 않는다**
    (AI-S-08). 재지 않았으면 정확도 칸이 **없다** — 0 을 적으면 이 값이 실측보다
    정확하다고 주장하게 된다(`config/depth_calibration.example.json` 의
    `accuracy_cm: null` 과 같은 규칙).

세 상태를 지킨다
----------------
`미측정 ≠ 0 ≠ 미달`. 선언이 없는 임계값은 `value=None` + `basis=no_declaration`
이고, 그것을 `0.0` 으로 접으면 모든 탐지가 통과하고, `inf` 로 접으면 전부 떨어진다.
둘 다 틀렸다 — **판정하지 않는 것이 맞다**. 하한이 없다는 사실이 운영 화면까지
올라가 운영자가 그때 하나 고르는 것이 이 모듈이 여는 길이다.

운영자 수정은 선언을 덮지 않는다
--------------------------------
`resolve()` 는 선언값과 운영자 수정값을 **서로 다른 칸으로** 돌려준다
(`declared_value` / `operator_value`). 어느 쪽이 지금 쓰이는지는 `basis` 가 말한다.
수정 자체는 `tools/fms_console/overlay.py` 의 append-only 장부에 쌓이고 이 파일은
읽기 전용이다 — 원래 선언과 사람이 고친 값이 끝까지 구분되어야 어긋남을 설명할 수
있다(AI-L-03).

여기서 하지 않는 것
-------------------
* **어휘별·클래스별 라벨 하한을 소유하지 않는다.** 그 주인은
  `config/obstacle_taxonomy.example.json` 의 `class_conf` 이고
  `perception/obstacle_taxonomy.py::score_floor` 가 읽는다. 같은 사실의 주인을 둘로
  만들면 두 화면이 다른 답을 말한다(AI-C-01).
* **provider 를 세우지 않는다.** 조립은 `edge/detector_catalog.py::provider_for` 가
  선언된 `construction.param_kwargs` 로 한다 — 이 모듈은 그 함수가 받는 운영자
  파라미터 사전을 만들어 줄 뿐이다. 그래서 새 탐지기도 설정 한 항목이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

#: 지금 쓰이는 값이 **어디서 왔는가**. 값과 같은 칸에 담지 않는다.
BASIS_DECLARED = "declared"
#: 운영자가 장부에서 고친 값이 쓰이고 있다. 선언은 그대로 남아 있다(AI-L-03).
BASIS_OPERATOR_EDIT = "operator_edit"
#: 아무도 선언하지 않았다. **0 이 아니고 미달도 아니다**(세 번째 상태).
BASIS_NO_DECLARATION = "no_declaration"
#: 같은 질문에 같은 좁기의 선언이 둘이다. 하나를 임의로 고르지 않는다.
BASIS_AMBIGUOUS = "ambiguous_declaration"

#: 위 토큰들의 어휘 묶음. 사전이 값을 베끼지 않고 이 이름을 가리킨다.
THRESHOLD_BASES: tuple[str, ...] = (
    BASIS_DECLARED, BASIS_OPERATOR_EDIT, BASIS_NO_DECLARATION, BASIS_AMBIGUOUS)

#: 선언 파일의 기본 자리. 다른 파일은 `from_file(path)` 로 준다.
DEFAULT_THRESHOLDS_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "detection_thresholds.example.json")

#: 범위를 선언하지 않은 축. `(None, None)` 과 구분하려고 상수로 둔다.
UNBOUNDED: tuple[None, None] = (None, None)


class ThresholdDeclarationError(ValueError):
    """선언 파일이 자기 규칙을 깼다. 값의 좋고 나쁨은 여기서 판정하지 않는다."""


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


@dataclass(frozen=True)
class Provenance:
    """그 수가 **어디서 왔고 재서 나왔는가**. 선언에서 가장 중요한 칸이다.

    `measured=False` 인데 정확도를 적는 것은 거짓이라 적재에서 거절한다 — 재지 않은
    값에 오차를 붙이면 그 오차가 실측처럼 읽힌다(AI-S-08).
    """

    source: str
    measured: bool
    method: str = ""
    measured_on: str | None = None
    measured_by: str | None = None
    created_at: str = ""
    #: 실측 표본 수. `None` 은 미측정이고 0 이 아니다.
    samples: int | None = None
    #: 실측 정확도(그 임계값의 단위). `None` 은 미측정이고 0 이 아니다.
    accuracy: float | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, threshold_id: str) -> "Provenance":
        if "measured" not in raw:
            # 재서 나온 값인지가 비어 있으면 그 선언은 읽는 쪽이 추측하게 된다.
            raise ThresholdDeclarationError(
                f"{threshold_id}: provenance.measured 를 적어야 한다(참/거짓)")
        measured = bool(raw["measured"])
        samples = None if raw.get("samples") is None else int(raw["samples"])
        accuracy = _opt_float(raw.get("accuracy"))
        if not measured and (samples is not None or accuracy is not None):
            raise ThresholdDeclarationError(
                f"{threshold_id}: measured=false 인데 samples/accuracy 가 적혀 있다 — "
                "재지 않은 값에 오차를 붙이면 실측처럼 읽힌다(AI-S-08)")
        source = str(raw.get("source") or "")
        if not source:
            raise ThresholdDeclarationError(
                f"{threshold_id}: provenance.source 가 비어 있다 — 출처 없는 선언은 "
                "출처가 적힌 코드 상수보다 나쁘다")
        return cls(
            source=source, measured=measured,
            method=str(raw.get("method") or ""),
            measured_on=_opt_str(raw.get("measured_on")),
            measured_by=_opt_str(raw.get("measured_by")),
            created_at=str(raw.get("created_at") or ""),
            samples=samples, accuracy=accuracy,
        )

    def as_dict(self) -> dict:
        """화면이 읽는 모양. **미측정 항목은 키가 없다**(0 으로 채우지 않는다)."""
        body: dict[str, Any] = {"source": self.source, "measured": self.measured}
        if self.method:
            body["method"] = self.method
        if self.measured_on is not None:
            body["measured_on"] = self.measured_on
        if self.measured_by is not None:
            body["measured_by"] = self.measured_by
        if self.created_at:
            body["created_at"] = self.created_at
        if self.samples is not None:
            body["samples"] = self.samples
        if self.accuracy is not None:
            body["accuracy"] = self.accuracy
        return body


#: `applies_to` 의 축 이름. 좁은 축이 넓은 축을 이긴다(아래 `specificity`).
SCOPE_AXES: tuple[str, ...] = (
    "class_name", "label_namespace", "vocabulary", "detector_id", "capability_kind")

#: 축의 좁기. 수를 직접 쓰지 않고 자리로 정한다 — 축을 더하면 여기 한 줄이다.
_SCOPE_WEIGHT: dict[str, int] = {name: len(SCOPE_AXES) - i
                                 for i, name in enumerate(SCOPE_AXES)}


@dataclass(frozen=True)
class ThresholdScope:
    """이 임계값이 **무엇에** 적용되는가. `None` 인 축은 한정하지 않는 축이다."""

    detector_id: str | None = None
    capability_kind: str | None = None
    vocabulary: str | None = None
    class_name: str | None = None
    label_namespace: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ThresholdScope":
        unknown = set(raw) - set(SCOPE_AXES) - {"$comment"}
        if unknown:
            # 모르는 축을 조용히 버리면 운영자가 적은 한정이 사라지고, 그 임계값은
            # 자기가 적지 않은 대상에까지 적용된다.
            raise ThresholdDeclarationError(
                f"applies_to: 모르는 축 {sorted(unknown)} — 아는 축은 {list(SCOPE_AXES)}")
        return cls(**{axis: _opt_str(raw.get(axis)) for axis in SCOPE_AXES})

    def as_dict(self) -> dict:
        """선언 그대로. **한정하지 않은 축도 `null` 로 내보낸다** — 키가 없으면
        화면이 "그 축은 모른다" 로 읽고, 여기서 `null` 은 "한정하지 않는다" 다."""
        return {axis: getattr(self, axis) for axis in SCOPE_AXES}

    @property
    def specificity(self) -> int:
        return sum(_SCOPE_WEIGHT[axis] for axis in SCOPE_AXES
                   if getattr(self, axis) is not None)

    def matches(self, query: Mapping[str, str | None]) -> bool:
        """이 선언이 그 질문에 적용되는가.

        축이 `None` 인 선언은 그 축을 한정하지 않으니 통과한다. 축에 값이 있으면
        **질문이 같은 값을 줘야** 한다 — 질문이 그 축을 주지 않았으면 적용된다고
        말할 수 없다. 그렇게 하지 않으면 어휘를 모른 채 어휘 전용 하한을 빌려 오고,
        그것이 이 파일이 생긴 원인(prompt-free 라벨이 zeroshot 기본값을 빌린 일)이다.
        """
        for axis in SCOPE_AXES:
            declared = getattr(self, axis)
            if declared is None:
                continue
            if query.get(axis) != declared:
                return False
        return True


@dataclass(frozen=True)
class ThresholdDeclaration:
    """임계값 하나의 선언. 값 · 적용 대상 · 출처 · 측정 여부를 함께 들고 다닌다."""

    threshold_id: str
    #: 운영자 파라미터 이름. `detector_characteristics` 의
    #: `construction.param_kwargs` 키와 **같은 어휘**다 — 두 곳에 다른 말을 적으면
    #: 선언한 값이 생성자에 도달하지 않는다.
    parameter: str
    applies_to: ThresholdScope
    #: `None` 은 **아직 아무도 선언하지 않았다**. 0 도 미달도 아니다.
    value: float | None
    unit: str
    bounds: tuple[float | None, float | None]
    provenance: Provenance
    #: 웹에서 그림에 돌려 볼 수 있는 값인가. 모델 구조 상수는 거짓이다.
    trialable: bool
    version: int
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ThresholdDeclaration":
        threshold_id = str(raw.get("threshold_id") or "")
        if not threshold_id:
            raise ThresholdDeclarationError("threshold entry without 'threshold_id'")
        parameter = str(raw.get("parameter") or "")
        if not parameter:
            raise ThresholdDeclarationError(f"{threshold_id}: 'parameter' 가 비어 있다")
        value = _opt_float(raw.get("value"))
        lo, hi = (raw.get("bounds") or UNBOUNDED)
        bounds = (_opt_float(lo), _opt_float(hi))
        if value is not None:
            if bounds[0] is not None and value < bounds[0]:
                raise ThresholdDeclarationError(
                    f"{threshold_id}: value {value} < bounds[0] {bounds[0]}")
            if bounds[1] is not None and value > bounds[1]:
                raise ThresholdDeclarationError(
                    f"{threshold_id}: value {value} > bounds[1] {bounds[1]}")
        provenance = Provenance.from_dict(raw.get("provenance") or {},
                                          threshold_id=threshold_id)
        if value is None and provenance.measured:
            # 재서 나온 값인데 값이 없다는 말은 성립하지 않는다.
            raise ThresholdDeclarationError(
                f"{threshold_id}: value 가 없는데 measured=true 다")
        return cls(
            threshold_id=threshold_id,
            parameter=parameter,
            applies_to=ThresholdScope.from_dict(raw.get("applies_to") or {}),
            value=value,
            unit=str(raw.get("unit") or ""),
            bounds=bounds,
            provenance=provenance,
            trialable=bool(raw.get("trialable", True)),
            version=int(raw.get("version", 1)),
            notes=str(raw.get("$comment") or ""),
        )

    @property
    def declared(self) -> bool:
        """값이 선언되어 있는가. 거짓이면 세 번째 상태다."""
        return self.value is not None

    def permits(self, value: float) -> bool:
        lo, hi = self.bounds
        return not ((lo is not None and value < lo) or (hi is not None and value > hi))

    def as_row(self) -> dict:
        """운영 화면이 읽는 한 행. 표현 결정은 들어가지 않는다."""
        return {
            "threshold_id": self.threshold_id,
            "parameter": self.parameter,
            "applies_to": self.applies_to.as_dict(),
            "declared_value": self.value,
            "declared": self.declared,
            "unit": self.unit,
            "bounds": [self.bounds[0], self.bounds[1]],
            "provenance": self.provenance.as_dict(),
            "trialable": self.trialable,
            "version": self.version,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class OperatorValue:
    """운영자가 장부에 쌓은 값 하나. **선언이 아니다.**"""

    value: float
    actor: str
    reason: str
    edited_at: float

    def as_dict(self) -> dict:
        return {"value": self.value, "actor": self.actor, "reason": self.reason,
                "edited_at": self.edited_at}


@dataclass(frozen=True)
class ResolvedThreshold:
    """지금 쓸 값과 **그것이 어디서 왔는지**. 선언값과 수정값이 다른 칸에 있다."""

    parameter: str
    #: 지금 쓸 값. `None` 이면 쓸 값이 없다 — 0 으로 접지 않는다.
    value: float | None
    basis: str
    declared_value: float | None = None
    operator_value: OperatorValue | None = None
    declaration: ThresholdDeclaration | None = None
    #: 같은 좁기의 선언이 둘일 때 그 둘의 id. 하나를 임의로 고르지 않은 사유다.
    conflicting: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return self.value is not None

    @property
    def changed_by_operator(self) -> bool:
        return self.basis == BASIS_OPERATOR_EDIT

    def as_dict(self) -> dict:
        body: dict[str, Any] = {
            "parameter": self.parameter,
            "value": self.value,
            "basis": self.basis,
            # 선언값과 운영자 값은 **같은 칸에 담지 않는다**(AI-S-08·AI-L-03).
            "declared_value": self.declared_value,
            "operator_value": (None if self.operator_value is None
                               else self.operator_value.as_dict()),
            "threshold_id": (None if self.declaration is None
                             else self.declaration.threshold_id),
            "provenance": (None if self.declaration is None
                           else self.declaration.provenance.as_dict()),
        }
        if self.conflicting:
            body["conflicting"] = list(self.conflicting)
        return body


class DetectionThresholds:
    """선언 파일 하나를 담는다. 아무 값도 화이트리스트로 검사하지 않는다."""

    def __init__(self, declaration: Mapping[str, Any]) -> None:
        entries = declaration.get("thresholds")
        if not isinstance(entries, list):
            raise ThresholdDeclarationError("'thresholds' must be a JSON array")
        rows: dict[str, ThresholdDeclaration] = {}
        seen: dict[tuple, str] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ThresholdDeclarationError("each threshold entry must be an object")
            item = ThresholdDeclaration.from_dict(entry)
            if item.threshold_id in rows:
                raise ThresholdDeclarationError(
                    f"duplicate threshold_id: {item.threshold_id}")
            # 같은 파라미터·같은 적용 대상을 둘이 선언하면 **같은 사실의 주인이
            # 둘**이다. 적재에서 막는 것이 운영 중 임의 선택보다 낫다.
            key = (item.parameter, item.applies_to)
            if key in seen:
                raise ThresholdDeclarationError(
                    f"{item.threshold_id}: {seen[key]} 와 같은 파라미터·같은 적용 "
                    "대상을 중복 선언했다")
            seen[key] = item.threshold_id
            rows[item.threshold_id] = item
        self._rows = rows

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "DetectionThresholds":
        raw = json.loads(Path(path or DEFAULT_THRESHOLDS_PATH).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ThresholdDeclarationError("top level must be a JSON object")
        return cls(raw)

    @classmethod
    def empty(cls) -> "DetectionThresholds":
        """선언이 없는 배치. 오류가 아니라 정상 상태다(AI-C-05)."""
        return cls({"thresholds": []})

    # ── 읽기 ────────────────────────────────────────────────────────────────

    @property
    def threshold_ids(self) -> tuple[str, ...]:
        return tuple(self._rows)

    def all(self) -> tuple[ThresholdDeclaration, ...]:
        return tuple(self._rows.values())

    def get(self, threshold_id: str) -> ThresholdDeclaration:
        try:
            return self._rows[threshold_id]
        except KeyError:
            raise ThresholdDeclarationError(
                f"unknown threshold_id: {threshold_id}") from None

    def parameters(self) -> tuple[str, ...]:
        return tuple(sorted({row.parameter for row in self._rows.values()}))

    def rows(self) -> list[dict]:
        """선언 전부를 화면이 읽는 행 목록으로. 선언 순서 그대로다."""
        return [row.as_row() for row in self._rows.values()]

    # ── 해소 ────────────────────────────────────────────────────────────────

    def resolve(self, parameter: str, *,
                detector_id: str | None = None,
                capability_kind: str | None = None,
                vocabulary: str | None = None,
                class_name: str | None = None,
                label_namespace: str | None = None,
                operator_values: Mapping[str, OperatorValue] | None = None,
                ) -> ResolvedThreshold:
        """그 파라미터의 지금 값. **없으면 없다고 말한다**(0 을 내지 않는다).

        좁은 선언이 넓은 선언을 이긴다. 같은 좁기가 둘이면 **고르지 않고** 사유를
        낸다 — 임의로 고르면 운영자가 고친 쪽과 쓰이는 쪽이 달라질 수 있다.
        """
        query = {"detector_id": detector_id, "capability_kind": capability_kind,
                 "vocabulary": vocabulary, "class_name": class_name,
                 "label_namespace": label_namespace}
        matched = [row for row in self._rows.values()
                   if row.parameter == parameter and row.applies_to.matches(query)]
        if not matched:
            return ResolvedThreshold(parameter=parameter, value=None,
                                     basis=BASIS_NO_DECLARATION)
        matched.sort(key=lambda r: (-r.applies_to.specificity, r.threshold_id))
        best = matched[0]
        tied = [r for r in matched
                if r.applies_to.specificity == best.applies_to.specificity]
        if len(tied) > 1:
            return ResolvedThreshold(
                parameter=parameter, value=None, basis=BASIS_AMBIGUOUS,
                conflicting=tuple(r.threshold_id for r in tied))

        edit = (operator_values or {}).get(best.threshold_id)
        if edit is not None and best.permits(edit.value):
            return ResolvedThreshold(
                parameter=parameter, value=edit.value, basis=BASIS_OPERATOR_EDIT,
                declared_value=best.value, operator_value=edit, declaration=best)
        if best.value is None:
            # 선언에 값이 없다. 운영자 수정도 없으면 **세 번째 상태**다.
            return ResolvedThreshold(
                parameter=parameter, value=None, basis=BASIS_NO_DECLARATION,
                declared_value=None, declaration=best)
        return ResolvedThreshold(
            parameter=parameter, value=best.value, basis=BASIS_DECLARED,
            declared_value=best.value, declaration=best)

    def params_for(self, detector_id: str, *,
                   capability_kind: str | None = None,
                   vocabulary: str | None = None,
                   label_namespace: str | None = None,
                   accepted: Mapping[str, Any] | tuple[str, ...] | None = None,
                   operator_values: Mapping[str, OperatorValue] | None = None,
                   ) -> tuple[dict[str, float], dict[str, ResolvedThreshold]]:
        """그 탐지기를 세울 때 넘길 운영자 파라미터 사전과 **각 값의 근거**.

        `accepted` 를 주면 그 탐지기가 실제로 받는 이름만 넣는다 — 받지 않는 이름을
        넣으면 `provider_for` 가 조용히 버리고, 운영자는 자기가 고친 값이 적용된
        줄 안다. 값이 없는(세 번째 상태) 파라미터는 **사전에 넣지 않는다**: 넣지
        않으면 provider 자신의 기본값이 쓰이고 그 사실이 근거에 남는다.
        """
        names = (tuple(accepted) if accepted is not None
                 else tuple(self.parameters()))
        params: dict[str, float] = {}
        basis: dict[str, ResolvedThreshold] = {}
        for name in names:
            resolved = self.resolve(
                name, detector_id=detector_id, capability_kind=capability_kind,
                vocabulary=vocabulary, label_namespace=label_namespace,
                operator_values=operator_values)
            basis[name] = resolved
            if resolved.known:
                params[name] = float(resolved.value)
        return params, basis


def operator_values_from_overlay(payloads: Mapping[str, Mapping[str, Any]]
                                 ) -> dict[str, OperatorValue]:
    """장부의 현재 유효 수정 → `{threshold_id: OperatorValue}`.

    `tools/fms_console/overlay.py::current_payloads(KIND_THRESHOLD)` 의 모양을 그대로
    받는다. 값이 수가 아닌 항목은 **버리지 않고 건너뛴다** — 장부는 append-only 라
    옛 형식의 항목이 남아 있을 수 있고, 그것 하나로 전체 해소가 멈추면 운영 화면이
    통째로 빈다(AI-C-05).
    """
    out: dict[str, OperatorValue] = {}
    for threshold_id, payload in (payloads or {}).items():
        try:
            value = float(payload["value"])
        except (KeyError, TypeError, ValueError):
            continue
        out[str(threshold_id)] = OperatorValue(
            value=value,
            actor=str(payload.get("actor") or ""),
            reason=str(payload.get("reason") or ""),
            edited_at=float(payload.get("edited_at") or 0.0))
    return out
