"""Turns a detector's class name into a group, a role and a confidence floor.

implements: AI-S-04 (미확인 객체를 기존 클래스에 강제 매핑하지 않는다),
            AI-S-08 (선언값은 출처·측정 여부를 들고 다니고 관측과 구분된다)
관련: AI-S-06 (근거 누적), AI-S-03 (근거 충분도), AI-C-15 (도메인 차이는 설정),
      AI-L-02 (미검증 추론을 확정 정답으로 승격하지 않는다), AI-R-02
tests: tests/test_obstacle_grounding.py, tests/test_detection_thresholds.py

탐지기는 **클래스 이름 문자열**을 낸다. 상위 판단은 그 문자열로 분기할 수 없고
(원칙 #3) 의미 단위가 필요하다. 이 모듈이 그 변환 한 겹이다.

세 축을 **따로** 낸다 — 합치면 각자의 뜻이 사라진다.

group
    위험 우선순위를 매기는 축(`AGENT` … `UNKNOWN_OBSTACLE`). 사람이 상자보다
    먼저다. `risk/hazard_field.py` 가 쓴다.
role
    디지털 트윈에서 **무엇으로 다룰 것인가**. 벽·기둥은 `background` 라 지도의
    몸체이고, 의자·상자는 `object` 라 자리가 바뀌면 따라 움직여야 하며,
    사람·로봇은 `agent`, 턱·계단·물웅덩이는 객체가 아니라 `ground` — 바닥의
    성질이다. **같은 `HARD_OBSTACLE` 안에서 벽과 의자가 갈리므로** 이 축은
    group 에서 유도할 수 없고 따로 선언한다.
vocabulary
    그 이름이 **어느 어휘에서 왔는가**. 미세조정 어휘의 `chair` 와 제로샷
    어휘의 `chair` 는 같은 글자지만 같은 근거가 아니다.

제로샷을 고려한다는 것
----------------------
open-vocabulary 탐지기는 **아무 문자열이나** 낸다. 그래서 둘을 지킨다.

1. 어휘에 없는 이름은 `UNKNOWN_OBSTACLE` 이고 사유가 남는다. 가장 비슷한
   기존 클래스로 끌어다 붙이지 않는다 — 그것이 AI-S-04 가 막는 바로 그 동작이다.
2. 제로샷 라벨은 `label_status="hypothesis"` 로만 나온다. 미세조정 어휘만
   `classified` 가 된다. 점수가 높아도 승격되지 않는다(AI-L-02) — 승격은
   사용자 확인이나 검증을 거친다(AI-L-03).

임계값도 어휘별이다. 제로샷 `box` 는 0.12, 미세조정 `box` 는 0.28 이다. 한
임계값을 둘에 같이 쓰면 한쪽은 전부 버리고 다른 쪽은 전부 통과한다.

하한은 **세 상태다** — 있다 · 기본값을 쓴다 · 근거가 없다
----------------------------------------------------------
`미측정 ≠ 0 ≠ 미달`. 그래서 `score_floor()` 는 수 하나가 아니라 수와 **근거**를
함께 낸다(`ScoreFloor.basis`).

``declared_for_class``
    그 어휘가 그 클래스에 대해 직접 적은 값이다.
``vocabulary_default``
    클래스별 값은 없고 그 어휘가 선언한 `default` 를 쓴다. 운영자가 그 어휘의
    점수 분포를 보고 정한 수이므로 **그 어휘의 라벨에 대해서는** 근거가 있다.
``no_declared_floor``
    근거가 없다. 모르는 어휘, 혹은 그 어휘가 `default` 조차 선언하지 않은 경우다.
    값은 `NaN` 이고 0 이 아니다.

옛 구현은 세 번째 상태가 없어 `table.get("default", 0.25)` 로 **코드에 박힌 0.25**
를 돌려줬다. 선언 파일이 아무 말도 하지 않았는데 선언된 하한처럼 보이는 수가
나오는 자리였다. 그 상수를 지웠다 — 어휘가 아무 말도 하지 않으면 우리도 하지 않는다.

**하한이 없다는 것은 그 탐지를 버리라는 뜻이 아니다.** `floor_state()` 가 세 토큰을
돌려주고, 그중 `no_floor_declared` 를 거름 조건으로 쓰면 이름을 모르는 관측이
파이프라인에서 사라져 AI-S-04 가 막는 바로 그 동작이 된다(미확인 객체는 미확인
상태로 유지된다). 그래서 이 모듈의 소비자는 하한을 **근거로 실어 보내고 거르지
않는다** — `perception/obstacle_evidence.py` 가 그렇게 한다.

프롬프트프리 라벨
-----------------
어휘를 받지 않는 탐지기(`edge/yoloe_provider.py`)의 라벨은 내장 4585 범주에서 와서
`promptfree:` 접두사가 붙는다. 그 라벨의 하한은 어떤 어휘에도 속하지 않으므로
`config/detection_thresholds.example.json` 의 `label_namespace` 선언이 주인이고
(지금은 `value: null` — 아무도 재지 않았다), 이 모듈은 그 이름 공간을 알면
`no_declared_floor` 를 돌려준다. 어휘의 `default` 를 빌려 주지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: 어휘에 없는 이름이 가는 자리. "모른다"는 상태이고 "없다"가 아니다(AI-S-04).
UNKNOWN_GROUP = "UNKNOWN_OBSTACLE"
#: 역할도 모를 수 있다. 배경인지 객체인지 모르는 것을 객체로 적지 않는다.
UNKNOWN_ROLE = "unknown"

#: 분류 사유 토큰.
REASON_MAPPED = "mapped"
REASON_UNMAPPED = "unmapped_label"
REASON_NO_VOCABULARY = "unknown_vocabulary"

#: 라벨의 지위. 제로샷은 끝까지 가설이다.
STATUS_CLASSIFIED = "classified"
STATUS_HYPOTHESIS = "hypothesis"

#: 점수 하한의 **근거**. 값과 같은 칸에 담지 않는다 — 담으면 "선언된 0.25" 와
#: "아무도 선언하지 않아 기본값이 된 0.25" 가 화면에서 같은 수가 된다.
FLOOR_BASIS_CLASS = "declared_for_class"
FLOOR_BASIS_VOCABULARY_DEFAULT = "vocabulary_default"
FLOOR_BASIS_NONE = "no_declared_floor"

#: 점수가 하한에 대해 **어떤 상태인가**. 셋이고 둘이 아니다(미측정 ≠ 0 ≠ 미달).
FLOOR_ABOVE = "above_floor"
FLOOR_BELOW = "below_floor"
#: 하한을 말할 근거가 없다. **버리라는 뜻이 아니다**(AI-S-04).
FLOOR_NO_BASIS = "no_floor_declared"

#: 어휘가 어느 이름 공간의 라벨을 받는가. 선언에 없으면 이 값으로 본다 —
#: `config/detector_characteristics.example.json` 의 `label_namespace` 와 같은 어휘다.
DEFAULT_LABEL_NAMESPACE = "operator_vocabulary"

#: 위 토큰들의 **어휘 묶음**. 사전(`contracts/data_dictionary.py`)이 값을 베끼지
#: 않고 이 이름을 가리킨다 — 베끼면 토큰을 하나 더할 때 한쪽만 바뀌고, 그때
#: 어긋난 쪽이 "선언된 어휘" 로 읽힌다.
FLOOR_BASES: tuple[str, ...] = (
    FLOOR_BASIS_CLASS, FLOOR_BASIS_VOCABULARY_DEFAULT, FLOOR_BASIS_NONE)
FLOOR_STATES: tuple[str, ...] = (FLOOR_ABOVE, FLOOR_BELOW, FLOOR_NO_BASIS)

_DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "obstacle_taxonomy.example.json"


@dataclass(frozen=True)
class ClassVerdict:
    """한 클래스 이름에 대한 판정. 이름을 몰라도 **거절하지 않고** 모름을 적는다."""

    class_name: str
    group: str
    group_priority: int
    role: str
    vocabulary: str
    label_status: str
    #: 이 어휘·이 클래스에 선언된 점수 하한. 근거가 없으면 `NaN` 이고 0 이 아니다.
    confidence_floor: float
    reason: str
    #: 그 하한이 **어디서 왔는가**(`declared_for_class` · `vocabulary_default` ·
    #: `no_declared_floor`). 값만 보면 "선언된 0.25" 와 "근거 없는 0.25" 가 같아 보인다.
    confidence_floor_basis: str = FLOOR_BASIS_NONE

    @property
    def is_known(self) -> bool:
        return self.reason == REASON_MAPPED

    @property
    def can_be_confirmed(self) -> bool:
        """확정 클래스로 승격할 수 있는 근거인가. 제로샷이면 아니다(AI-L-02)."""
        return self.label_status == STATUS_CLASSIFIED and self.is_known


@dataclass(frozen=True)
class Threshold:
    """값과 **그 값이 어디서 왔는지**. 근거 없이 나온 수를 운영자가 신뢰하면 안 된다."""

    value_m: float
    basis: str
    #: 그 수가 어디서 왔는가(선언 파일의 `provenance.source`). 빈 문자열은 미선언이다.
    source: str = ""
    #: 재서 나온 값인가. 손으로 맞춘 값과 실측값을 같은 칸에 담지 않는다(AI-S-08).
    measured: bool = False


@dataclass(frozen=True)
class ScoreFloor:
    """한 라벨의 점수 하한과 **그 하한의 근거**.

    `value` 가 `NaN` 인 것은 0 이 아니라 "말할 근거가 없다" 다. 그 상태를 거름
    조건으로 쓰면 이름을 모르는 관측이 사라지므로, 소비자는 `state()` 의 세 토큰을
    보고 **거르지 않고 근거로 실어 보낸다**(AI-S-04).
    """

    value: float
    basis: str
    vocabulary: str
    class_name: str
    label_namespace: str = DEFAULT_LABEL_NAMESPACE
    #: 그 수가 어디서 왔는가. 선언 파일의 `class_conf_provenance` 를 그대로 옮긴다.
    source: str = ""
    measured: bool = False

    @property
    def declared(self) -> bool:
        return self.basis != FLOOR_BASIS_NONE

    def state(self, score: float) -> str:
        """`above_floor` · `below_floor` · `no_floor_declared` 중 하나."""
        if not self.declared or self.value != self.value:   # NaN
            return FLOOR_NO_BASIS
        return FLOOR_ABOVE if float(score) >= self.value else FLOOR_BELOW

    def as_dict(self) -> dict:
        """화면이 읽는 모양. 근거 없는 하한은 **값 칸이 None** 이고 0 이 아니다."""
        return {
            "class_name": self.class_name,
            "vocabulary": self.vocabulary,
            "label_namespace": self.label_namespace,
            "value": None if self.value != self.value else self.value,
            "basis": self.basis,
            "source": self.source,
            "measured": self.measured,
        }


class ObstacleTaxonomy:
    """선언된 어휘 그대로 판정한다. 여기서 추론하지 않는다."""

    def __init__(self, declaration: dict) -> None:
        self._groups: dict[str, int] = dict(declaration.get("groups") or {})
        self._roles: dict[str, str] = dict(declaration.get("roles") or {})
        self._role_overrides: dict[str, str] = {
            str(k).strip().lower(): v for k, v in (declaration.get("role_overrides") or {}).items()}
        # 클래스 이름은 소문자로 접어 둔다 — 탐지기마다 대소문자가 다르다.
        self._mapping: dict[str, str] = {
            str(k).strip().lower(): v for k, v in (declaration.get("group_mapping") or {}).items()}
        self._vocabularies: dict[str, dict] = dict(declaration.get("vocabularies") or {})
        risk = declaration.get("risk") or {}
        self._near_m = float(risk.get("near_threshold", 2.0))
        self._mid_m = float(risk.get("mid_threshold", self._near_m * 1.2))
        self._dynamic = dict(risk.get("dynamic_threshold") or {})
        self._fusion_iou = float((declaration.get("fusion") or {}).get("iou", 0.45))

    # ── 읽기 ────────────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "ObstacleTaxonomy":
        with open(Path(path or _DEFAULT_CONFIG), encoding="utf-8") as fh:
            return cls(json.load(fh))

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(self._groups)

    @property
    def vocabularies(self) -> tuple[str, ...]:
        return tuple(self._vocabularies)

    def vocabulary_classes(self, vocabulary: str) -> tuple[str, ...]:
        """그 어휘가 **선언한 클래스 목록**. 모르는 어휘는 빈 묶음이다.

        탐지기에 넣을 어휘를 호출자가 따로 적지 않게 하려고 있다 — 두 곳에 적으면
        탐지기가 내는 이름과 우리가 아는 이름이 조용히 갈린다.
        """
        vocab = self._vocabularies.get(vocabulary) or {}
        return tuple(vocab.get("classes") or ())

    def label_namespace_of(self, vocabulary: str) -> str | None:
        """그 어휘가 **어느 이름 공간의 라벨을 받는가**. 모르는 어휘는 None 이다.

        탐지기 선언의 `label_namespace` 와 맞춰 보는 쪽이 쓴다 — 어긋나면 그 어휘의
        하한을 쓰지 않는 것이 맞고, 그 판정을 두 곳에서 따로 하면 갈린다.
        """
        vocab = self._vocabularies.get(vocabulary)
        if vocab is None:
            return None
        return str(vocab.get("label_namespace", DEFAULT_LABEL_NAMESPACE))

    @property
    def near_threshold_m(self) -> float:
        return self._near_m

    @property
    def mid_threshold_m(self) -> float:
        return self._mid_m

    @property
    def fusion_iou(self) -> float:
        return self._fusion_iou

    # ── 판정 ────────────────────────────────────────────────────────────────

    def classify(self, class_name: str, *, vocabulary: str = "zeroshot",
                 label_namespace: str | None = None) -> ClassVerdict:
        """클래스 이름 하나를 세 축으로 가른다.

        **모르는 이름을 비슷한 것으로 끌어오지 않는다.** 그래서 오타나 새 물체는
        `UNKNOWN_OBSTACLE` 로 남아 미확인 객체 경로(AI-S-04)와 학습 후보
        경로(AI-L-01)로 흐른다. 조용히 `chair` 가 되면 둘 다 일어나지 않는다.
        """
        name = (class_name or "").strip().lower()
        vocab = self._vocabularies.get(vocabulary)
        if vocab is None:
            # 모르는 어휘의 라벨은 가설로만 받는다. 어휘를 모르는데 임계값을
            # 아는 척할 수 없으므로 하한도 선언하지 않는다(0 으로 채우지 않는다).
            return ClassVerdict(
                class_name=name, group=UNKNOWN_GROUP,
                group_priority=self._groups.get(UNKNOWN_GROUP, 0),
                role=UNKNOWN_ROLE, vocabulary=str(vocabulary),
                label_status=STATUS_HYPOTHESIS, confidence_floor=float("nan"),
                reason=REASON_NO_VOCABULARY,
                confidence_floor_basis=FLOOR_BASIS_NONE)

        group = self._mapping.get(name)
        mapped = group is not None
        group = group or UNKNOWN_GROUP
        role = self._role_overrides.get(name) or (
            self._roles.get(group, UNKNOWN_ROLE) if mapped else UNKNOWN_ROLE)

        declared_status = str(vocab.get("label_status", STATUS_HYPOTHESIS))
        # 어휘가 확정 가능하다고 선언해도 **그 어휘에 없는 이름**은 가설이다.
        status = declared_status if mapped else STATUS_HYPOTHESIS

        floor = self.score_floor(name, vocabulary=vocabulary,
                                 label_namespace=label_namespace)
        return ClassVerdict(
            class_name=name, group=group,
            group_priority=self._groups.get(group, 0),
            role=role, vocabulary=vocabulary, label_status=status,
            confidence_floor=floor.value,
            reason=REASON_MAPPED if mapped else REASON_UNMAPPED,
            confidence_floor_basis=floor.basis)

    def score_floor(self, class_name: str, *, vocabulary: str = "zeroshot",
                    label_namespace: str | None = None) -> ScoreFloor:
        """그 라벨의 점수 하한과 **근거**. 근거가 없으면 수를 지어내지 않는다.

        `label_namespace` 를 주면 그 라벨이 **어느 이름 공간에서 왔는가**를 함께
        본다. 어휘가 받는 이름 공간과 다르면 그 어휘의 하한을 빌려 주지 않는다 —
        프롬프트프리 라벨이 `zeroshot` 의 `default`(0.25)를 빌려 선언된 하한처럼
        보이던 자리가 거기였다. 접두사를 여기서 들여다보지 않는 이유: 접두사는
        provider 의 것이고 이 모듈이 그것을 알면 새 탐지기가 코드 변경이 된다.
        선언이 말하는 이름 공간만 본다(원칙 #1·#7).
        """
        name = (class_name or "").strip().lower()
        vocab = self._vocabularies.get(vocabulary)
        if vocab is None:
            # 어휘를 모르면 하한도 모른다. 아무 기본값을 내면 그 값이 선언된
            # 하한처럼 보이고, 그 어휘의 점수 분포와는 아무 관계가 없다.
            return ScoreFloor(float("nan"), FLOOR_BASIS_NONE, str(vocabulary), name,
                              label_namespace or DEFAULT_LABEL_NAMESPACE)

        declared_namespace = str(vocab.get("label_namespace", DEFAULT_LABEL_NAMESPACE))
        provenance = vocab.get("class_conf_provenance") or {}
        source = str(provenance.get("source") or "")
        measured = bool(provenance.get("measured", False))
        if label_namespace is not None and label_namespace != declared_namespace:
            return ScoreFloor(float("nan"), FLOOR_BASIS_NONE, str(vocabulary), name,
                              str(label_namespace), source="", measured=False)

        table = vocab.get("class_conf") or {}
        if name in table:
            return ScoreFloor(float(table[name]), FLOOR_BASIS_CLASS, str(vocabulary),
                              name, declared_namespace, source, measured)
        if "default" in table:
            return ScoreFloor(float(table["default"]), FLOOR_BASIS_VOCABULARY_DEFAULT,
                              str(vocabulary), name, declared_namespace, source, measured)
        # 어휘가 기본 하한조차 선언하지 않았다. 옛 구현은 여기서 코드에 박힌 0.25 를
        # 돌려줘 선언되지 않은 수를 선언처럼 보이게 했다. 이제 말하지 않는다.
        return ScoreFloor(float("nan"), FLOOR_BASIS_NONE, str(vocabulary), name,
                          declared_namespace, source="", measured=False)

    def confidence_floor(self, class_name: str, *, vocabulary: str = "zeroshot",
                         label_namespace: str | None = None) -> float:
        """그 어휘·그 클래스의 점수 하한. 제로샷이 더 낮은 것은 **의도**다.

        수만 필요한 호출자를 위한 얇은 겉면이다 — 근거가 필요하면 `score_floor()`.
        """
        return self.score_floor(class_name, vocabulary=vocabulary,
                                label_namespace=label_namespace).value

    def floor_state(self, class_name: str, score: float, *,
                    vocabulary: str = "zeroshot",
                    label_namespace: str | None = None) -> str:
        """`above_floor` · `below_floor` · `no_floor_declared`.

        **세 번째를 거름 조건으로 쓰지 않는다.** 하한을 말할 근거가 없는 것은 그
        탐지가 틀렸다는 뜻이 아니고, 거르면 이름을 모르는 관측이 파이프라인에서
        사라져 AI-S-04 가 막는 바로 그 동작이 된다.
        """
        return self.score_floor(class_name, vocabulary=vocabulary,
                                label_namespace=label_namespace).state(score)

    def passes_floor(self, class_name: str, score: float, *, vocabulary: str = "zeroshot",
                     label_namespace: str | None = None) -> bool:
        """하한을 **넘었다고 말할 수 있는가**.

        거짓이 두 가지를 덮는다 — 미달과 근거 없음. 그 둘을 가르려면
        `floor_state()` 를 쓴다. 이 겉면을 남겨 둔 이유는 이미 참·거짓만 묻는
        호출자가 있기 때문이고, 그 호출자에게 "모른다" 를 참으로 주면 미검증 라벨이
        확정처럼 통과한다(AI-L-02).
        """
        return self.score_floor(class_name, vocabulary=vocabulary,
                                label_namespace=label_namespace).state(score) == FLOOR_ABOVE

    def priority_of(self, group: str) -> int:
        return self._groups.get(group, self._groups.get(UNKNOWN_GROUP, 0))

    def priority_norm(self, group: str) -> float:
        """0..1 로 눕힌 우선순위. 가중합에 들어가는 쪽이 쓴다."""
        if not self._groups:
            return 0.0
        top = max(self._groups.values())
        return (self.priority_of(group) / top) if top else 0.0

    # ── 근접 임계값 ──────────────────────────────────────────────────────────

    def near_threshold_for_speed(self, speed_mps: float | None) -> Threshold:
        """속도를 알면 제동거리로, 모르면 선언값으로 — **어느 쪽인지 적는다**.

        속도 스트림이 없을 때 정지 상태(0 m/s)로 가정하면 임계값이 최소로 내려가
        "가까운 것이 없다"가 된다. 그래서 모를 때는 계산하지 않고 선언된 고정값을
        쓰고, 그 사실을 `basis` 에 남긴다(AI-S-03).
        """
        provenance = self._dynamic.get("provenance") or {}
        source = str(provenance.get("source") or "")
        measured = bool(provenance.get("measured", False))
        if not self._dynamic.get("enabled") or speed_mps is None:
            basis = ("static_declared(dynamic_disabled)"
                     if not self._dynamic.get("enabled")
                     else "static_declared(no_velocity_stream)")
            return Threshold(self._near_m, basis, source, measured)

        v = max(0.0, float(speed_mps))
        reaction = float(self._dynamic.get("reaction_time", 0.0))
        brake = float(self._dynamic.get("brake_factor", 0.0))
        margin = float(self._dynamic.get("safety_margin", 0.0))
        lo = float(self._dynamic.get("min_threshold", 0.0))
        hi = float(self._dynamic.get("max_threshold", self._near_m))
        # **선형식 그대로 옮긴다.** 교과서 제동거리는 v²/2a 이고 이 식은 v 에
        # 선형이라 물리적으로는 그 모델이 아니다. 그래도 바꾸지 않는다 — 이
        # 계수들은 실제 로봇으로 재서 굳힌 값이고, 여기서 식을 고치면 같은
        # 장면에서 데모 스택과 **다른 거리**가 나와 둘을 비교할 수 없게 된다.
        # 식을 고칠 일이 생기면 재측정과 함께 AI-B-01 프로파일을 새로 낸다.
        raw = v * reaction + v * brake + margin
        return Threshold(min(hi, max(lo, raw)), f"dynamic(v={v:.2f}m/s)",
                         source, measured)
