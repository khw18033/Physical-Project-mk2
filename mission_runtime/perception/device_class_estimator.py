"""어떤 **기종**인가를 외형 하나로 정하지 않는다.

implements: AI-E-01 (공통 인지 인터페이스), AI-S-02 (여러 관측 근거의 연계),
            AI-S-03 (근거 충분도), AI-S-04 (확정 label 강제 금지)
관련: AI-C-13 (선택 방법은 교체 가능해야 한다), AI-L-09, AI-C-05, AI-C-19
tests: tests/test_device_class_estimator.py

## 문제

`perception/appearance_classifier.py` 는 사진 한 장을 기종으로 환산한다. 그 사전의
실측(`_meta.self_check`)이 말하는 것은 분명하다 — 절대점수로는 기종을 가를 수 없고
(같은 기종 최저 0.6236 vs 다른 기종 최고 0.8915), 가르는 것은 1·2 위의 **차이**이며,
그 차이는 배경과 조명이 닮으면 쉽게 뒤집힌다. 참조영상을 52 장에서 86 장으로 늘려도
확신 정답 비율은 80.8% → 81.4% 로 거의 그대로였다. 사진을 더 넣는 것으로는 여기서
더 못 간다.

그런데 "저것이 어떤 기종인가"를 말해 주는 근거는 사진만이 아니다. 그 장치는 자기가
무슨 action 을 할 수 있는지 **스스로 공지했고**(`registry/onboarding.py` 의
`declared_actions`), 어떤 자원 태그를 달고 조인했고, 지금 바닥을 가로질러 움직이고
있거나 볼트로 고정돼 있고, 거리와 박스 크기를 곱하면 대충 몇 미터짜리인지 나온다.
`takeoff` 를 공지한 장치는 책상에 고정된 매니퓰레이터가 아니다 — 그 한 줄이 사진
86 장보다 확실하다.

## 그래서 이 모듈이 지키는 것 (전부 시험으로 고정돼 있다)

1. **가리지 못하는 단서가 판정을 하지 못한다.** 단서는 두 격으로 나뉘어 타입에 남는다
   (`ClassCueSpec.decisive`). 공지한 action·자원 태그·운동·크기는 기종을 **배제**할 수
   있고, 외형과 선언된 구역은 지지만 한다. 전부 한 점수로 더하면 약한 단서 셋이 결정적
   단서 하나를 이긴다 — `perception/device_identity.py` 가 개체 식별에서 막은 것과 같은
   실패다. 여기서는 더 나아가, **점수가 판정을 하지 않는다**: 점수는 순위를 보이고
   동점을 깰 뿐이고, 고르는 일은 "어떤 단서가 스스로 갈랐는가"(`ClassCue.separated`)와
   "무엇이 배제됐는가"(`ClassCue.excludes`)의 구조가 한다.
2. **없는 단서는 아무것도 말하지 않는다.** 거리가 없고 운동이 없고 공지가 비어 있는 것은
   반대 근거가 아니라 침묵이다. 침묵한 종류는 `unobserved_kinds` 로 드러나며 점수에
   들어가지 않는다(AI-C-05 의 축소 운용이 정상 구성이라는 것과 같은 축).
3. **모순은 잡음이 아니라 결과다.** 외형이 insta360 이라 하고 공지가 `takeoff` 라 하면
   평균해서 뭉개지 않고 `CONFLICTED` 로 **양쪽을 이름으로** 낸다. 결정적 단서 쪽을
   `device_class` 에 적되 `classified` 는 거짓이다 — 모순을 통과시키면 그 통과가 다음
   판단의 전제가 된다.
4. **모호는 정답의 한 종류다.** 아무 단서도 혼자 가르지 못하면 고르지 않고, 무엇을 하면
   풀리는지(`resolution_requests`)를 함께 낸다(AI-S-05: 요청만 하고 실행은 다른 파트).
5. **설명이 산출물이다.** `explanation()` 은 단서별 기여, 외형 점수를 만든 참조영상
   파일 이름, 배제된 기종과 그 사유, 그리고 `leave_one_out()` — 각 단서를 빼면 판정이
   무엇이 되는가 — 를 한 묶음으로 낸다. 관제 웹이 사람에게 보여 주는 것이 이것이다.
6. **기종 이름으로 갈라지는 분기가 없다.** 어떤 기종이 어떤 action 을 공지하고 어떤
   태그를 다는지는 사전 파일의 `estimation_profile` 에 **데이터로** 적힌다. 새 기종은
   그 블록을 더해서 들어오고 이 모듈은 고치지 않는다(원칙 #1, #3).
7. **가중치와 임계값은 데이터다.** `_meta.estimation` 에서 읽고, 없으면 모듈 기본값을
   쓴다. 선택 방법은 동일 조건 비교로 교체할 수 있어야 한다(AI-C-13).

## 소유하지 않는 것

여기서 나오는 것은 **기종**이지 개체가 아니다. "이 track 이 go1-a 인가 go1-b 인가" 는
`perception/device_identity.py` 가 식별력 있는 단서로 따로 풀고, 장치의 최종 가용성과
권위 있는 결속은 백엔드의 몫이다(AI-C-19). 거리에서 미터 크기를 얻는 광학 환산은
보정의 영역이라(AI-E-02) 이 모듈은 이미 환산된 값을 **입력으로 받는다**.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from mission_runtime.contracts.data_dictionary import (
    CONFIDENCE,
    CONTRIBUTIONS,
    CONTRIBUTING_EVIDENCE_KINDS,
    LEAVE_ONE_OUT,
    SEMANTIC_CLASS,
    UNOBSERVED_EVIDENCE_KINDS,
)

# --- 등록된 단서 종류 --------------------------------------------------------
#: 참조영상 임베딩 유사도. 노이즈가 크고 **기종을 배제하지 못한다**.
KIND_APPEARANCE = "appearance_embedding"
#: 장치가 조인에서 스스로 공지한 action 어휘(registry/onboarding.py).
KIND_ANNOUNCED_ACTIONS = "announced_action_vocabulary"
#: 노드가 달고 온 자원 태그(config 의 nodes[].tags). 벤더 enum 이 아니라 자유 문자열.
KIND_RESOURCE_TAGS = "resource_tags"
#: 박스와 거리에서 환산한 실제 크기(m). 환산 자체는 보정의 몫이다(AI-E-02).
KIND_APPARENT_SIZE = "apparent_size"
#: 시간창에서의 변위. 움직였다는 것만 말하고 안 움직인 것은 아무것도 말하지 않는다.
KIND_MOTION = "motion"
#: 프로파일에 "있을 것"이라고 적힌 배치. 가장 약하고 배제하지 못한다.
KIND_DECLARED_ZONE = "declared_zone"

#: 모호할 때 낼 수 있는 해법 요청. 실행은 다른 파트가 한다(AI-C-19).
REQUEST_ANNOUNCE_ACTIONS = "request_action_announcement"
REQUEST_REGISTER_TAGS = "request_resource_tag_registration"
REQUEST_RANGE = "request_range_measurement"
REQUEST_MOTION_WINDOW = "request_motion_observation"
REQUEST_BETTER_VIEW = "request_closer_or_unoccluded_view"


@dataclass(frozen=True)
class ClassCueSpec:
    """한 단서 종류의 선언. `decisive` 가 이 모듈의 핵심 주장이다.

    `decisive=True` 는 "이 단서는 기종을 **배제**할 수 있다"는 뜻이지 "항상 맞다"는
    뜻이 아니다. 배제할 수 있다는 것만으로 격이 갈린다 — 외형은 아무리 점수가 높아도
    어떤 기종도 배제하지 못하고, 그래서 배제를 뒤집지도 못한다.
    """

    kind: str
    decisive: bool
    #: 순위 표시와 동점 처리에만 쓰는 무게다. **판정은 여기서 나오지 않는다**.
    weight: float
    #: 이 종류가 없을 때 낼 해법 요청. 비어 있으면 요청하지 않는다.
    request: str = ""
    note: str = ""


@dataclass
class ClassCueKindRegistry:
    """등록된 단서 종류. 등록되지 않은 종류의 단서는 조용히 쓰이지 않고 **사유로**
    남는다 — 종류 이름 오타가 판정을 바꾸지 않은 채 사라지는 것이 가장 찾기 어렵다."""

    _specs: dict[str, ClassCueSpec] = field(default_factory=dict)

    def register(self, spec: ClassCueSpec) -> ClassCueSpec:
        self._specs[spec.kind] = spec
        return spec

    def spec(self, kind: str) -> ClassCueSpec | None:
        return self._specs.get(kind)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def copy(self) -> "ClassCueKindRegistry":
        return ClassCueKindRegistry(dict(self._specs))


def default_cue_kind_registry() -> ClassCueKindRegistry:
    """현재 배포가 아는 여섯 종류. 새 종류는 `register()` 로 늘린다 — 이 함수를
    고치지 않고도 늘어나야 새 하드웨어가 핵심 코드를 건드리지 않는다(원칙 #7)."""
    registry = ClassCueKindRegistry()
    for spec in (
        ClassCueSpec(
            KIND_APPEARANCE, decisive=False, weight=0.35, request=REQUEST_BETTER_VIEW,
            note="사진 한 장. 배경·조명이 닮으면 뒤집히므로 어떤 기종도 배제하지 못한다."),
        ClassCueSpec(
            KIND_ANNOUNCED_ACTIONS, decisive=True, weight=0.85,
            request=REQUEST_ANNOUNCE_ACTIONS,
            note="장치가 스스로 공지한 것. takeoff 를 공지한 것은 고정 매니퓰레이터가 아니다."),
        ClassCueSpec(
            KIND_RESOURCE_TAGS, decisive=True, weight=0.75, request=REQUEST_REGISTER_TAGS,
            note="조인에 실린 자원 태그. 같은 역할이어도 다리와 바퀴는 여기서 갈린다."),
        ClassCueSpec(
            KIND_APPARENT_SIZE, decisive=True, weight=0.45, request=REQUEST_RANGE,
            note="거리를 알 때만 나온다. 보통 가르지는 못하고 **배제**한다."),
        ClassCueSpec(
            KIND_MOTION, decisive=True, weight=0.55, request=REQUEST_MOTION_WINDOW,
            note="움직였다는 것만 말한다. 안 움직인 것은 고정됐다는 뜻이 아니다 — 세워 둔 것일 수 있다."),
        ClassCueSpec(
            KIND_DECLARED_ZONE, decisive=False, weight=0.10,
            note="프로파일에 적힌 배치. 가장 약한 근거이고 단독으로는 아무것도 못 한다."),
    ):
        registry.register(spec)
    return registry


#: 모듈 기본 레지스트리. 배치별로 바꿔야 하면 `copy()` 해서 쓴다.
DEFAULT_CUE_KINDS = default_cue_kind_registry()

#: 한 단서가 "스스로 갈랐다"고 말하려면 1·2 위 지지가 이만큼은 벌어져야 한다.
#: 외형은 자기 사전의 마진을 쓰므로 이 값을 쓰지 않는다 — 각 단서의 분해능은
#: 그 단서가 가장 잘 안다(AI-B-01: 측정한 조합에서 나온 값만 쓴다).
DEFAULT_SEPARATION_MIN = 0.20
#: 배제 판정에서 크기가 범위를 벗어나도 봐 주는 비율. 거리 추정이 거칠기 때문이다.
DEFAULT_SIZE_TOLERANCE = 1.6
#: 이만큼 움직였으면 "바닥을 가로질렀다"로 본다. 떨림·추적 지터와 가르는 값이다.
DEFAULT_MOVED_MIN_M = 0.30


class ClassState(str, Enum):
    """판정 상태. `ESTIMATED` 만 기종을 말하고 나머지는 전부 말하지 않는다."""

    ESTIMATED = "ESTIMATED"
    #: 아무 단서도 혼자 가르지 못했다. 고르면 그것은 판단이 아니라 추측이다.
    AMBIGUOUS = "AMBIGUOUS"
    #: 단서들이 서로 다른 기종을 가리켰다. 양쪽이 이름으로 남는다.
    CONFLICTED = "CONFLICTED"
    #: 쓸 수 있는 단서가 하나도 없었다. 판정을 시도한 적이 없는 상태다.
    NO_CUE = "NO_CUE"


@dataclass(frozen=True)
class ClassCue:
    """한 관측자가 "저것은 이런 기종이다"라고 말한 근거 1 건.

    `support` 는 기종별 지지(0..1)이고 **순위만** 만든다. 판정을 만드는 것은 둘이다 —
    `separated`(이 단서가 혼자 가른 기종)와 `excludes`(이 단서가 배제한 기종과 사유).
    둘을 지지 점수와 분리해 두면, 점수가 아무리 커도 가르지 못한 단서는 고르지 못한다.
    """

    kind: str
    source: str
    observed_at: float
    support: Mapping[str, float] = field(default_factory=dict)
    #: 이 단서가 **혼자** 가른 기종. 가르지 못했으면 None 이고 그것이 보통이다.
    separated: str | None = None
    #: 이 단서가 배제한 기종 → 사유. 지지 단서(decisive=False)가 적어도 무시된다.
    excludes: Mapping[str, str] = field(default_factory=dict)
    #: 이 단서로는 서로 가를 수 없었던 기종들. 모호 사유를 사람 말로 적는 재료다.
    tied: tuple[str, ...] = ()
    detail: Mapping[str, object] = field(default_factory=dict)

    @property
    def silent(self) -> bool:
        """아무 말도 하지 않았는가. 침묵은 반대 근거가 아니다(규칙 2)."""
        return not self.support and not self.excludes and self.separated is None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "source": self.source,
            "observed_at": self.observed_at,
            "support": {k: round(v, 4) for k, v in sorted(self.support.items())},
            "separated": self.separated,
            "excludes": dict(sorted(self.excludes.items())),
            "tied": list(self.tied),
            "detail": dict(self.detail),
        }


# ---------------------------------------------------------------------------
# 기종 프로파일 — 코드가 아니라 사전 파일에 적힌 데이터
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassProfile:
    """한 기종이 **무엇으로 드러나는가**의 선언. 전부 선택 항목이다.

    적지 않은 칸은 모름이고 기본값이 아니다 — `size_m` 이 None 이면 크기 단서는 이
    기종에 대해 아무 말도 하지 않는다. 0 이나 빈 범위를 꽂으면 "모르는 값"이 "아는
    값"을 배제하게 된다(AI-B-01: 미측정 항목은 구분해 남긴다).
    """

    class_name: str
    label: str = ""
    action_vocabulary: tuple[str, ...] = ()
    #: 위 어휘가 **전부**인가. 참일 때만 어휘 밖 action 이 이 기종을 배제한다.
    #: 모르는 채로 배제하면 공지를 적게 한 장치가 전부 탈락한다.
    action_vocabulary_complete: bool = False
    signature_tags: frozenset[str] = frozenset()
    size_m: tuple[float, float] | None = None
    #: 바닥을 가로질러 이동하는 기종인가. None 은 모름이고 거짓이 아니다.
    mobile: bool | None = None
    zones: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, class_name: str, label: str, raw: Mapping[str, Any]) -> "ClassProfile":
        size = raw.get("size_m")
        return cls(
            class_name=class_name,
            label=label,
            action_vocabulary=tuple(raw.get("action_vocabulary") or ()),
            action_vocabulary_complete=bool(raw.get("action_vocabulary_complete", False)),
            signature_tags=frozenset(raw.get("signature_tags") or ()),
            size_m=(float(size[0]), float(size[1])) if size else None,
            mobile=raw.get("mobile"),
            zones=tuple(raw.get("zones") or ()),
        )


@dataclass(frozen=True)
class ClassProfiles:
    """이 배치가 아는 기종들과, 판정에 쓰는 데이터 값들.

    `exclusive_tag_families` 는 "같은 가족 안에서는 하나만 참"인 태그 묶음이다 —
    `locomotion.legged` 와 `platform.uav` 는 함께 설 수 없다. 이것을 태그 이름별
    if 문으로 적으면 새 하드웨어가 올 때마다 코드가 자란다(원칙 #1).
    """

    profiles: tuple[ClassProfile, ...] = ()
    exclusive_tag_families: Mapping[str, frozenset[str]] = field(default_factory=dict)
    weights: Mapping[str, float] = field(default_factory=dict)
    separation_min: float = DEFAULT_SEPARATION_MIN
    size_tolerance: float = DEFAULT_SIZE_TOLERANCE
    moved_min_m: float = DEFAULT_MOVED_MIN_M
    missing_reason: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(p.class_name for p in self.profiles))

    def get(self, class_name: str) -> ClassProfile | None:
        return next((p for p in self.profiles if p.class_name == class_name), None)

    @classmethod
    def load(cls, path: str | Path) -> "ClassProfiles":
        """사전 파일에서 프로파일 블록을 읽는다. **없으면 예외가 아니라 빈 묶음이다.**

        프로파일을 적지 않은 배치에서는 다중 단서 추정만 비활성이고 외형 분류는
        그대로 돈다 — 선택 기능 하나의 결손이 기동을 막지 않는다(AI-C-05).
        """
        path = Path(path)
        if not path.exists():
            return cls(missing_reason="no_dictionary_file")
        payload = json.loads(path.read_text(encoding="utf-8"))
        estimation = (payload.get("_meta") or {}).get("estimation") or {}
        profiles = [
            ClassProfile.from_json(name, entry.get("label", name), entry["estimation_profile"])
            for name, entry in payload.items()
            if not name.startswith("_") and entry.get("estimation_profile")
        ]
        return cls(
            profiles=tuple(sorted(profiles, key=lambda p: p.class_name)),
            exclusive_tag_families={
                family: frozenset(tags)
                for family, tags in (estimation.get("exclusive_tag_families") or {}).items()
            },
            weights={k: float(v) for k, v in (estimation.get("cue_weights") or {}).items()},
            separation_min=float(estimation.get("separation_min", DEFAULT_SEPARATION_MIN)),
            size_tolerance=float(estimation.get("size_tolerance", DEFAULT_SIZE_TOLERANCE)),
            moved_min_m=float(estimation.get("moved_min_m", DEFAULT_MOVED_MIN_M)),
            missing_reason="" if profiles else "no_class_declares_an_estimation_profile",
        )


# ---------------------------------------------------------------------------
# 단서를 만드는 쪽 — 각 관측이 어떤 단서로 환산되는지 한곳에 모은다
# ---------------------------------------------------------------------------


def _separate(support: Mapping[str, float], *, minimum: float) -> tuple[str | None, tuple[str, ...]]:
    """지지에서 "혼자 갈랐는가"를 판정한다. 1 위가 2 위를 `minimum` 넘게 앞서야 한다.

    앞서지 못하면 고른 것이 아니라 못 고른 것이고, 그 동점자들이 모호 사유가 된다.
    """
    ranked = sorted(support.items(), key=lambda kv: (-kv[1], kv[0]))
    ranked = [(name, value) for name, value in ranked if value > 0.0]
    if not ranked:
        return None, ()
    if len(ranked) == 1:
        return ranked[0][0], ()
    if ranked[0][1] - ranked[1][1] >= minimum:
        return ranked[0][0], ()
    top = ranked[0][1]
    return None, tuple(sorted(name for name, value in ranked if top - value < minimum))


def appearance_cue(verdict: Any, *, observed_at: float,
                   source: str = "appearance_classifier") -> ClassCue:
    """외형 판정을 단서로 바꾼다. **가른 것은 사전의 마진이 정한다.**

    여기서 1 위를 다시 고르지 않는다 — 1·2 위를 가를 수 있는 마진은 그 사전의
    leave-one-out 이 측정한 값이고(`_meta.self_check`), 그 측정을 한 쪽이
    `AppearanceClassifier` 다. 바깥에서 다른 임계값으로 다시 판정하면 측정과 판정이
    갈라진다.
    """
    support = {score.class_name: max(0.0, float(score.score)) for score in verdict.ranked}
    ranked = [score.class_name for score in verdict.ranked]
    return ClassCue(
        kind=KIND_APPEARANCE,
        source=source,
        observed_at=observed_at,
        support=support,
        separated=verdict.appearance_class,
        tied=tuple(sorted(ranked[:2])) if verdict.appearance_class is None and len(ranked) > 1 else (),
        detail={
            "state": verdict.state.value,
            "reason": verdict.reason,
            "margin": None if verdict.margin is None else round(verdict.margin, 4),
            # 어떤 사진이 점수를 만들었는지. 화면이 그려야 하는 것이 이것이다.
            "driving_references": {
                score.class_name: [m.file for m in score.driving_references]
                for score in verdict.ranked
            },
        },
    )


def announced_action_cue(actions: Iterable[str], profiles: ClassProfiles, *,
                         observed_at: float, source: str = "node_join_manifest") -> ClassCue:
    """장치가 공지한 action 어휘를 단서로 바꾼다.

    배제는 **완전하다고 선언된** 어휘에서만 나온다. 어휘를 다 적지 않은 기종까지
    배제하면, 공지를 적게 한 장치가 아무 기종도 아니게 된다 — 모르는 것을 반대
    근거로 쓰는 것이 규칙 2 가 금지한 바로 그것이다.
    """
    announced = frozenset(a for a in actions if a)
    if not announced:
        return ClassCue(KIND_ANNOUNCED_ACTIONS, source, observed_at,
                        detail={"announced": [], "reason": "nothing_announced"})

    support: dict[str, float] = {}
    excludes: dict[str, str] = {}
    for profile in profiles.profiles:
        vocabulary = frozenset(profile.action_vocabulary)
        if not vocabulary:
            continue  # 이 기종이 무엇을 공지하는지 모른다 — 침묵한다.
        overlap = announced & vocabulary
        support[profile.class_name] = len(overlap) / len(announced)
        unknown = announced - vocabulary
        if unknown and profile.action_vocabulary_complete:
            excludes[profile.class_name] = (
                f"announced_action_outside_complete_vocabulary:{','.join(sorted(unknown))}")
    for name in excludes:
        support.pop(name, None)
    separated, tied = _separate(support, minimum=profiles.separation_min)
    return ClassCue(KIND_ANNOUNCED_ACTIONS, source, observed_at,
                    support=support, separated=separated, excludes=excludes, tied=tied,
                    detail={"announced": sorted(announced)})


def resource_tag_cue(tags: Iterable[str], profiles: ClassProfiles, *,
                     observed_at: float, source: str = "node_registration") -> ClassCue:
    """조인에 실린 자원 태그를 단서로 바꾼다.

    배제는 **배타 가족** 안에서만 나온다 — 노드가 `locomotion.wheeled` 를 달고 왔는데
    어떤 기종이 같은 가족의 `locomotion.legged` 를 선언했다면 그 기종은 아니다.
    가족 선언이 없는 태그는 지지만 만든다. 이렇게 두면 새 태그가 추가돼도 코드가
    아니라 `_meta.estimation.exclusive_tag_families` 가 자란다.
    """
    observed = frozenset(t for t in tags if t)
    if not observed:
        return ClassCue(KIND_RESOURCE_TAGS, source, observed_at,
                        detail={"tags": [], "reason": "no_tag_registered"})

    support: dict[str, float] = {}
    excludes: dict[str, str] = {}
    for profile in profiles.profiles:
        signature = profile.signature_tags
        if not signature:
            continue
        support[profile.class_name] = len(observed & signature) / len(signature)
        for family, members in profiles.exclusive_tag_families.items():
            mine = signature & members
            theirs = observed & members
            if mine and theirs and not (mine & theirs):
                excludes[profile.class_name] = (
                    f"exclusive_tag_family_conflict:{family}:"
                    f"{','.join(sorted(theirs))}!={','.join(sorted(mine))}")
                break
    for name in excludes:
        support.pop(name, None)
    separated, tied = _separate(support, minimum=profiles.separation_min)
    return ClassCue(KIND_RESOURCE_TAGS, source, observed_at,
                    support=support, separated=separated, excludes=excludes, tied=tied,
                    detail={"tags": sorted(observed)})


def apparent_size_m(bbox: Sequence[float], *, range_m: float, focal_px: float) -> float | None:
    """박스와 거리에서 실제 크기(m)를 뽑는다. 거리가 없으면 **None 이고 끝이다**.

    없는 거리를 지어내 확정 판단에 쓰지 않는다 — `tools/fms_console/twin.py` 의
    `DeviceDetection.range_m` 가 None 일 때와 같은 규칙이다(AI-R-02 와 같은 이유).
    """
    if range_m is None or range_m <= 0 or focal_px <= 0:
        return None
    x1, y1, x2, y2 = bbox
    longest_px = max(abs(x2 - x1), abs(y2 - y1))
    if longest_px <= 0:
        return None
    return float(range_m * longest_px / focal_px)


def apparent_size_cue(size_m: float | None, profiles: ClassProfiles, *,
                      observed_at: float, source: str = "detection") -> ClassCue:
    """환산된 크기를 단서로 바꾼다. 보통 가르지 못하고 **배제**한다.

    4 축 탁상 팔과 사족 로봇은 크기가 겹치지 않지만, 사족 로봇과 쿼드콥터는 겹친다.
    그래서 이 단서의 쓸모는 "저것이 무엇인가"가 아니라 "저것은 무엇이 아닌가"다.
    """
    if size_m is None or size_m <= 0:
        return ClassCue(KIND_APPARENT_SIZE, source, observed_at,
                        detail={"size_m": None, "reason": "no_range_measurement"})

    support: dict[str, float] = {}
    excludes: dict[str, str] = {}
    tolerance = profiles.size_tolerance
    for profile in profiles.profiles:
        if profile.size_m is None:
            continue
        low, high = profile.size_m
        if low <= size_m <= high:
            support[profile.class_name] = 1.0
            continue
        # 범위 밖이면 얼마나 밖인지를 **비율**로 잰다. 미터 차이로 재면 큰 기종이
        # 항상 너그러워진다.
        ratio = size_m / high if size_m > high else low / size_m
        if ratio > tolerance:
            excludes[profile.class_name] = (
                f"apparent_size_outside_declared_range:{size_m:.2f}m"
                f"_vs_{low:.2f}-{high:.2f}m")
        else:
            support[profile.class_name] = max(0.0, 1.0 - (ratio - 1.0) / (tolerance - 1.0))
    separated, tied = _separate(support, minimum=profiles.separation_min)
    return ClassCue(KIND_APPARENT_SIZE, source, observed_at,
                    support=support, separated=separated, excludes=excludes, tied=tied,
                    detail={"size_m": round(size_m, 3), "tolerance": tolerance})


def motion_cue(displacement_m: float | None, profiles: ClassProfiles, *,
               observed_at: float, source: str = "track_motion") -> ClassCue:
    """시간창의 변위를 단서로 바꾼다. **움직인 것만 말한다.**

    가만히 있는 것은 고정 장비라는 뜻이 아니다 — 대기 중인 로봇도 가만히 있다.
    그래서 변위가 작으면 지지도 배제도 내지 않고 침묵한다(규칙 2).
    """
    if displacement_m is None:
        return ClassCue(KIND_MOTION, source, observed_at,
                        detail={"displacement_m": None, "reason": "no_motion_observation"})
    if displacement_m < profiles.moved_min_m:
        return ClassCue(KIND_MOTION, source, observed_at,
                        detail={"displacement_m": round(displacement_m, 3),
                                "moved_min_m": profiles.moved_min_m,
                                "reason": "standing_still_is_not_evidence_of_being_fixed"})

    support: dict[str, float] = {}
    excludes: dict[str, str] = {}
    for profile in profiles.profiles:
        if profile.mobile is None:
            continue
        if profile.mobile:
            support[profile.class_name] = 1.0
        else:
            excludes[profile.class_name] = (
                f"translated_but_class_is_declared_fixed:{displacement_m:.2f}m")
    separated, tied = _separate(support, minimum=profiles.separation_min)
    return ClassCue(KIND_MOTION, source, observed_at,
                    support=support, separated=separated, excludes=excludes, tied=tied,
                    detail={"displacement_m": round(displacement_m, 3),
                            "moved_min_m": profiles.moved_min_m})


def declared_zone_cue(zone_id: str, profiles: ClassProfiles, *,
                      observed_at: float, source: str = "zone_profile") -> ClassCue:
    """선언된 배치. 가장 약한 근거이고 **단독으로는 아무것도 확정하지 못한다**.

    `device_identity.declared_placement_cue` 와 같은 격이다 — "있을 것"이라고 적힌
    것이지 본 것이 아니다.
    """
    if not zone_id:
        return ClassCue(KIND_DECLARED_ZONE, source, observed_at,
                        detail={"zone_id": "", "reason": "no_zone_declared"})
    support = {p.class_name: 1.0 for p in profiles.profiles if zone_id in p.zones}
    return ClassCue(KIND_DECLARED_ZONE, source, observed_at, support=support,
                    tied=tuple(sorted(support)) if len(support) > 1 else (),
                    detail={"zone_id": zone_id})


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CueContribution:
    """한 기종에 대한 한 단서의 기여. 점수와 그 점수의 격이 함께 남는다."""

    kind: str
    source: str
    decisive: bool
    support: float
    weight: float

    @property
    def weighted(self) -> float:
        return self.support * self.weight

    def as_dict(self) -> dict:
        return {"kind": self.kind, "source": self.source, "decisive": self.decisive,
                "support": round(self.support, 4), "weight": self.weight,
                "weighted": round(self.weighted, 4)}


@dataclass(frozen=True)
class ClassSupport:
    """한 기종의 집계. 결정적 지지와 보조 지지를 **끝까지 따로** 들고 있다."""

    class_name: str
    label: str
    decisive_score: float
    supporting_score: float
    contributions: tuple[CueContribution, ...] = ()
    excluded_by: tuple[str, str] | None = None

    @property
    def excluded(self) -> bool:
        return self.excluded_by is not None

    def as_dict(self) -> dict:
        return {
            SEMANTIC_CLASS: self.class_name,
            "label": self.label,
            "decisive_score": round(self.decisive_score, 4),
            "supporting_score": round(self.supporting_score, 4),
            CONFIDENCE: round(self.decisive_score + (1.0 - self.decisive_score)
                              * self.supporting_score, 4),
            "excluded": self.excluded,
            "excluded_by": (None if self.excluded_by is None
                            else {"kind": self.excluded_by[0], "reason": self.excluded_by[1]}),
            CONTRIBUTIONS: [row.as_dict() for row in self.contributions],
        }


@dataclass(frozen=True)
class ClassConflict:
    """두 단서가 서로 다른 기종을 가리킨 사건. **양쪽이 이름으로 남는다**."""

    kind: str
    claims: str
    against_kind: str
    against_claims: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "claims": self.claims,
                "against_kind": self.against_kind, "against_claims": self.against_claims,
                "detail": self.detail}


@dataclass(frozen=True)
class LeaveOneOutRow:
    """한 단서 종류를 빼면 판정이 무엇이 되는가. 틀린 판정을 디버깅하는 자리다."""

    removed: str
    state: str
    device_class: str | None
    reason: str
    changed: bool

    def as_dict(self) -> dict:
        return {"removed": self.removed, "state": self.state,
                SEMANTIC_CLASS: self.device_class, "reason": self.reason,
                "changed": self.changed}


@dataclass(frozen=True)
class ClassEstimate:
    """한 관측 대상에 대한 기종 추정. **가설이고 확정이 아니다**(AI-S-04)."""

    state: ClassState
    device_class: str | None
    reason: str
    ranked: tuple[ClassSupport, ...] = ()
    conflicts: tuple[ClassConflict, ...] = ()
    resolution_requests: tuple[str, ...] = ()
    #: 이번 판정에 들어간 단서들. leave-one-out 이 이걸 다시 돌린다.
    cues: tuple[ClassCue, ...] = ()
    #: 등록돼 있지만 이번에 아무 말도 하지 않은 종류. **없음은 반대 근거가 아니다**.
    unobserved_kinds: tuple[str, ...] = ()
    #: 이 결과를 만든 추정기. 같은 설정으로 다시 돌려야 leave-one-out 이 비교가 된다.
    estimator: "DeviceClassEstimator | None" = field(default=None, repr=False, compare=False)

    @property
    def classified(self) -> bool:
        """이 값을 그대로 써도 되는가. `ESTIMATED` 만 참이다 — 모순을 통과시키지 않는다."""
        return self.state is ClassState.ESTIMATED

    @property
    def excluded_classes(self) -> dict[str, str]:
        return {row.class_name: row.excluded_by[1] for row in self.ranked if row.excluded_by}

    def leave_one_out(self) -> tuple[LeaveOneOutRow, ...]:
        """단서 종류를 하나씩 빼고 다시 판정한다.

        "이 판정은 무엇 때문인가"에 답할 수 있는 유일한 방법이다. 기여도 숫자만 보여
        주면 결정적 단서 하나가 전부를 정한 경우와 여럿이 합쳐 정한 경우가 같아 보인다.
        """
        if self.estimator is None:
            return ()
        rows = []
        for kind in sorted({cue.kind for cue in self.cues if not cue.silent}):
            reduced = self.estimator.estimate(
                cue for cue in self.cues if cue.kind != kind)
            rows.append(LeaveOneOutRow(
                removed=kind, state=reduced.state.value, device_class=reduced.device_class,
                reason=reduced.reason,
                changed=(reduced.state is not self.state
                         or reduced.device_class != self.device_class)))
        return tuple(rows)

    def explanation(self) -> dict:
        """화면이 "왜 이 판정인가"를 그리는 데 필요한 것 전부.

        고른 이유와 **고르지 못한 이유**(배제된 기종, 모순, 아무도 가르지 못함)를 같은
        묶음에 넣는다 — 나누면 화면은 확정만 그리게 되고 모호는 빈칸으로 보인다.
        """
        return {
            "state": self.state.value,
            SEMANTIC_CLASS: self.device_class,
            "reason": self.reason,
            "ranked": [row.as_dict() for row in self.ranked],
            "excluded_classes": self.excluded_classes,
            "conflicts": [row.as_dict() for row in self.conflicts],
            "resolution_requests": list(self.resolution_requests),
            CONTRIBUTING_EVIDENCE_KINDS: sorted({c.kind for c in self.cues if not c.silent}),
            UNOBSERVED_EVIDENCE_KINDS: list(self.unobserved_kinds),
            "cues": [cue.as_dict() for cue in self.cues],
            LEAVE_ONE_OUT: [row.as_dict() for row in self.leave_one_out()],
        }

    def as_dict(self) -> dict:
        return self.explanation()


#: 사유 어휘. 문자열을 호출부에 흩뿌리면 화면이 사유별로 분기할 수 없다.
REASON_NO_CUE = "no_cue_said_anything"
REASON_NO_PROFILE = "no_class_declares_an_estimation_profile"
REASON_ALL_EXCLUDED = "every_known_class_was_excluded"
REASON_NOBODY_SEPARATED = "no_cue_separated_a_single_class"
REASON_DECISIVE_DISAGREE = "decisive_cues_name_different_classes"


@dataclass
class DeviceClassEstimator:
    """단서들을 받아 기종 가설을 낸다. 상태를 바꾸지 않는다.

    판정 규칙은 세 줄로 끝난다:

    1. 결정적 단서가 배제한 기종은 후보에서 빠진다. 외형이 아무리 지지해도 돌아오지
       않는다.
    2. 남은 후보 중 **스스로 가른 단서가 있는** 기종이 답이다. 결정적 단서가 가른
       쪽과 보조 단서가 가른 쪽이 다르면 그것은 모순이고, 결정적 쪽을 적되 상태는
       `CONFLICTED` 로 남긴다.
    3. 아무도 가르지 못했으면 고르지 않는다.

    점수(`decisive_score`/`supporting_score`)는 이 세 줄에 들어가지 않는다 — 순위를
    보이고 동점을 깨는 데만 쓴다. 그래서 보조 단서 셋이 결정적 단서 하나를 이기는
    일이 **구조적으로** 일어나지 않는다.
    """

    profiles: ClassProfiles
    kinds: ClassCueKindRegistry = field(default_factory=lambda: DEFAULT_CUE_KINDS)
    #: 종류별 무게. 사전의 `_meta.estimation.cue_weights` 가 덮어쓴다(AI-C-13).
    weights: Mapping[str, float] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        """지금 추정을 할 수 있는가. 거짓이어도 정상 축소 상태다(AI-C-05)."""
        return bool(self.profiles.profiles)

    def weight_of(self, kind: str) -> float:
        if kind in self.weights:
            return float(self.weights[kind])
        if kind in self.profiles.weights:
            return float(self.profiles.weights[kind])
        spec = self.kinds.spec(kind)
        return spec.weight if spec else 0.0

    def estimate(self, cues: Iterable[ClassCue]) -> ClassEstimate:
        cues = tuple(cues)
        if not self.available:
            return ClassEstimate(ClassState.NO_CUE, None, REASON_NO_PROFILE,
                                 cues=cues, estimator=self)

        # 등록되지 않은 종류는 쓰지 않되 사유로 남긴다. 조용히 버리면 종류 이름
        # 오타가 판정을 바꾸지 않은 채 사라진다.
        known = tuple(cue for cue in cues if self.kinds.spec(cue.kind) is not None)
        speaking = tuple(cue for cue in known if not cue.silent)
        unobserved = tuple(sorted(set(self.kinds.kinds()) - {c.kind for c in speaking}))
        if not speaking:
            return ClassEstimate(ClassState.NO_CUE, None, REASON_NO_CUE, cues=cues,
                                 unobserved_kinds=unobserved,
                                 resolution_requests=self._requests(speaking),
                                 estimator=self)

        excluded = self._exclusions(speaking)
        ranked = self._rank(speaking, excluded)
        eligible = tuple(row for row in ranked if not row.excluded)
        if not eligible:
            return ClassEstimate(
                ClassState.CONFLICTED, None, REASON_ALL_EXCLUDED, ranked=ranked,
                cues=cues, unobserved_kinds=unobserved,
                resolution_requests=self._requests(speaking), estimator=self)

        alive = {row.class_name for row in eligible}
        decisive_claims = self._claims(speaking, alive, decisive=True)
        supporting_claims = self._claims(speaking, alive, decisive=False)
        conflicts = self._conflicts(speaking, decisive_claims, supporting_claims, excluded)

        decided = sorted({claim for _, claim in decisive_claims})
        if len(decided) > 1:
            # 결정적 단서 둘이 서로 다른 기종을 가리켰다. 그중 하나를 고르지 않는다 —
            # 고르면 그 선택을 한 근거가 어디에도 없다.
            return ClassEstimate(
                ClassState.CONFLICTED, None, REASON_DECISIVE_DISAGREE, ranked=ranked,
                conflicts=conflicts, cues=cues, unobserved_kinds=unobserved,
                resolution_requests=self._requests(speaking), estimator=self)

        if decided:
            winner = decided[0]
            state = ClassState.CONFLICTED if conflicts else ClassState.ESTIMATED
            kinds = ",".join(sorted(k for k, claim in decisive_claims if claim == winner))
            return ClassEstimate(
                state, winner, f"decisive_cue_separated:{kinds}", ranked=ranked,
                conflicts=conflicts, cues=cues, unobserved_kinds=unobserved,
                resolution_requests=self._requests(speaking) if conflicts else (),
                estimator=self)

        supported = sorted({claim for _, claim in supporting_claims})
        if len(supported) == 1:
            kinds = ",".join(sorted(k for k, claim in supporting_claims))
            return ClassEstimate(
                ClassState.ESTIMATED, supported[0], f"supporting_cue_separated:{kinds}",
                ranked=ranked, conflicts=conflicts, cues=cues, unobserved_kinds=unobserved,
                estimator=self)
        if len(supported) > 1:
            return ClassEstimate(
                ClassState.CONFLICTED, None, REASON_DECISIVE_DISAGREE, ranked=ranked,
                conflicts=conflicts, cues=cues, unobserved_kinds=unobserved,
                resolution_requests=self._requests(speaking), estimator=self)

        if len(eligible) == 1:
            # 남은 후보가 하나뿐이다. 가른 단서가 있어서가 아니라 나머지가 배제된
            # 것이고, 그 둘은 다른 일이다 — 사유에 그대로 적는다.
            return ClassEstimate(
                ClassState.ESTIMATED, eligible[0].class_name,
                f"only_class_left_after_exclusions:{len(ranked) - 1}_excluded",
                ranked=ranked, conflicts=conflicts, cues=cues,
                unobserved_kinds=unobserved, estimator=self)

        tied = sorted({name for cue in speaking for name in cue.tied if name in alive})
        return ClassEstimate(
            ClassState.AMBIGUOUS, None,
            f"{REASON_NOBODY_SEPARATED}:{','.join(tied) if tied else len(eligible)}",
            ranked=ranked, conflicts=conflicts, cues=cues, unobserved_kinds=unobserved,
            resolution_requests=self._requests(speaking), estimator=self)

    # -- 내부 ------------------------------------------------------------

    def _exclusions(self, cues: Sequence[ClassCue]) -> dict[str, tuple[str, str]]:
        """배제는 **결정적 단서에서만** 나온다.

        보조 단서가 배제를 적어 보내도 받지 않는다. 받으면 외형 한 장이 기종을 지울
        수 있게 되고, 그것이 이 모듈이 막으려는 바로 그 일이다.
        """
        out: dict[str, tuple[str, str]] = {}
        for cue in cues:
            spec = self.kinds.spec(cue.kind)
            if spec is None or not spec.decisive:
                continue
            for class_name, why in cue.excludes.items():
                out.setdefault(class_name, (cue.kind, why))
        return out

    def _rank(self, cues: Sequence[ClassCue],
              excluded: Mapping[str, tuple[str, str]]) -> tuple[ClassSupport, ...]:
        rows: list[ClassSupport] = []
        for profile in self.profiles.profiles:
            contributions: list[CueContribution] = []
            decisive_best: dict[str, float] = {}
            supporting_best: dict[str, float] = {}
            for cue in cues:
                spec = self.kinds.spec(cue.kind)
                if spec is None:
                    continue
                support = float(cue.support.get(profile.class_name, 0.0))
                if support <= 0.0:
                    continue
                weight = self.weight_of(cue.kind)
                contributions.append(CueContribution(
                    cue.kind, cue.source, spec.decisive, support, weight))
                # 같은 종류의 단서가 여러 번 와도 **합쳐서 커지지 않게** 둔다. 같은
                # 카메라가 같은 프레임을 두 번 보낸 것이 두 배의 근거가 되면 중복
                # 관측이 확신을 만들어 낸다(AI-S-06).
                bucket = decisive_best if spec.decisive else supporting_best
                bucket[cue.kind] = max(bucket.get(cue.kind, 0.0), support * weight)
            rows.append(ClassSupport(
                class_name=profile.class_name,
                label=profile.label or profile.class_name,
                decisive_score=_saturate(decisive_best.values()),
                supporting_score=_saturate(supporting_best.values()),
                contributions=tuple(sorted(contributions,
                                           key=lambda c: (-c.weighted, c.kind))),
                excluded_by=excluded.get(profile.class_name),
            ))
        # 동점은 기종 이름 순으로 깬다 — 같은 입력이 실행마다 다른 순위를 내면
        # 그 순위를 근거로 한 어떤 설명도 재현되지 않는다.
        return tuple(sorted(
            rows, key=lambda r: (r.excluded, -r.decisive_score, -r.supporting_score,
                                 r.class_name)))

    def _claims(self, cues: Sequence[ClassCue], alive: set[str], *,
                decisive: bool) -> tuple[tuple[str, str], ...]:
        """(단서 종류, 그 단서가 가른 기종) 목록. 배제된 기종을 가리킨 주장은 버린다."""
        out = []
        for cue in cues:
            spec = self.kinds.spec(cue.kind)
            if spec is None or spec.decisive is not decisive or cue.separated is None:
                continue
            if cue.separated in alive:
                out.append((cue.kind, cue.separated))
        return tuple(out)

    def _conflicts(self, cues: Sequence[ClassCue],
                   decisive_claims: Sequence[tuple[str, str]],
                   supporting_claims: Sequence[tuple[str, str]],
                   excluded: Mapping[str, tuple[str, str]]) -> tuple[ClassConflict, ...]:
        """모순을 사건으로 만든다. 평균해 없애지 않는다(규칙 3)."""
        conflicts: list[ClassConflict] = []
        decided = {claim for _, claim in decisive_claims}
        for kind, claim in supporting_claims:
            if decided and claim not in decided:
                for against_kind, against in decisive_claims:
                    conflicts.append(ClassConflict(
                        kind, claim, against_kind, against,
                        "supporting_cue_points_elsewhere"))
        # 보조 단서가 가른 기종이 **배제된** 경우도 모순이다. 조용히 빼면 화면에는
        # 그냥 다른 답이 뜨고, 외형이 왜 무시됐는지는 어디에도 남지 않는다.
        for cue in cues:
            spec = self.kinds.spec(cue.kind)
            if spec is None or spec.decisive or cue.separated is None:
                continue
            if cue.separated in excluded:
                kind, why = excluded[cue.separated]
                conflicts.append(ClassConflict(
                    cue.kind, cue.separated, kind,
                    next((c for _, c in decisive_claims), "none"),
                    f"excluded:{why}"))
        return tuple(conflicts)

    def _requests(self, cues: Sequence[ClassCue]) -> tuple[str, ...]:
        """무엇을 더 하면 풀리는지. 이미 말한 종류는 다시 요청하지 않는다."""
        have = {cue.kind for cue in cues}
        requests = []
        for kind in self.kinds.kinds():
            spec = self.kinds.spec(kind)
            if spec and spec.request and kind not in have:
                requests.append(spec.request)
        return tuple(requests)


def _saturate(values: Iterable[float]) -> float:
    """독립적인 종류의 지지를 더하되 1.0 에서 포화시킨다.

    `device_identity.DeviceIdentityResolver._score` 와 같은 식을 쓴다 — 같은 뜻의
    집계가 모듈마다 다른 모양이면 두 화면이 같은 근거를 다르게 그린다.
    """
    total = 0.0
    for value in values:
        total += value * (1.0 - total)
    return total
