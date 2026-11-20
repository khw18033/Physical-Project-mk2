"""계약과 현재 레코드를 대조해 **무엇이 아직 없는가**를 낸다.

implements: AI-S-07, AI-S-03, AI-S-05, AI-C-05, AI-C-18

`MissionContract`(목적이 요구하는 것)와 `ObjectRecord`(지금 확보한 것)를 나란히 놓고
증거 종류별로 충족을 판정한다. 결손은 버리지 않고 `EvidenceNeed`로 바꿔 기존
`decision/info_request.py` 경로에 그대로 넘긴다 — 새 타입을 만들지 않는다.

**존재 여부 판정은 기존 `perception/purpose_requirements.evaluate_gap()`에 위임한다**
(2026-09-22). 그 모듈이 이미 AI-S-07의 required/preferred gap을 구현하고 있으므로,
"무엇이 빠졌나"의 정의를 두 곳에 두지 않는다. 이 모듈이 더하는 것은 **품질 판정**
(tolerance를 넘는가)과 **획득 가능성 판정**(만들 수 있는 provider가 있는가)이다.

**RoboKudo와 방향이 같고 대상이 다르다.** RoboKudo는 목표 annotation에서 annotator
dependency를 역구성한다. 여기서도 역방향이지만 대상이 파이프라인이 아니라 **현재
레코드의 결손**이다. 그래서 한 번 구성하고 끝나지 않고, 증거가 들어올 때마다 다시 센다
(internal/docs-dev/obsidian/ideas/evidence-driven-orchestration-plan.md §3 S2).

**`unobtainable`을 따로 두는 이유**: 등록된 provider로 만들 수 없는 증거를 `unmet`과
같이 취급하면 오케스트레이터가 영원히 돈다. 만들 수 없다는 것은 실패가 아니라 축소
경로이며(AI-C-05), 부족한 근거를 명시한 채 진행하는 것이 AI-S-05가 요구하는 동작이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from mission_runtime.contracts.evidence_contract import (
    MissionContract,
    SufficiencyItem,
    SufficiencyVerdict,
)
from mission_runtime.decision.info_request import EvidenceNeed
from mission_runtime.perception.object_record import UNKNOWN_CLASS, ObjectRecord
from mission_runtime.perception.purpose_requirements import evaluate_gap

#: 선언이 없을 때의 매핑. **비어 있는 것이 기본이다.**
#:
#: 2026-11-05 이전에는 여기에 11 개 후보가 코드 상수로 적혀 있었고, 그 이름들이 이
#: 저장소의 선언 어휘와 **하나도 맞지 않았다**(`detection` vs `perception.detect`).
#: 그러면 모든 증거 종류가 `unobtainable` 로 떨어지고, `gap()` 은 `unobtainable` 을
#: 요청으로 내보내지 않으므로 **아무것도 승격되지 않고 아무 요청도 나가지 않는데 그
#: 침묵이 통과하는 시험과 구분되지 않았다.**
#:
#: 그래서 표는 `config/evidence_kind_providers.example.json` 로 나갔고(AI-C-15), 여기
#: 남은 빈 사전은 "선언을 못 읽었다" 를 뜻한다. 그 상태에서 판정은
#: `provider_mapping_undeclared` 가 되어 **고칠 곳이 현장이 아니라 선언**임을 말한다 —
#: 그럴듯한 기본값을 두면 그 거짓이 다시 조용해진다.
DEFAULT_KIND_PROVIDERS: dict[str, tuple[str, ...]] = {}

#: 선언 파일의 자리. 배포가 다른 자리를 쓰면 `load_kind_providers(path)` 로 준다.
DEFAULT_KIND_PROVIDERS_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "evidence_kind_providers.example.json")


def load_kind_providers(
    source: Path | str | Mapping[str, Any] | None = None,
) -> dict[str, tuple[str, ...]]:
    """증거 종류 → capability kind 후보 선언을 읽는다.

    **파일이 없으면 빈 사전이고 추측하지 않는다.** 빈 사전으로 돌리면 모든 종류가
    `provider_mapping_undeclared` 가 되어 그 사실이 판정에 드러난다 — 그럴듯한
    기본값을 채우면 그 거짓이 조용해지고, 그것이 이 함수가 생긴 이유다.

    선언에 **없는 키는 없는 채로 둔다**. 빈 목록(`[]`)을 적은 키와 적지 않은 키는
    다른 사실이다 — 전자는 "찾아봤고 만들 수 있는 종류가 없다", 후자는 "아직 정하지
    않았다" 다(AI-S-08 과 같은 규칙).
    """
    if isinstance(source, Mapping):
        document: Mapping[str, Any] = source
    else:
        path = Path(source) if source is not None else DEFAULT_KIND_PROVIDERS_PATH
        if not path.is_file():
            return {}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 읽을 수 없는 선언을 빈 사전으로 두면 **선언이 없는 것과 같아진다.**
            # 그 둘을 가르는 것은 이 함수의 몫이 아니라 호출자의 몫이라 올려 보낸다.
            raise
    raw = document.get("evidence_kind_providers")
    if not isinstance(raw, Mapping):
        return {}
    return {str(kind): tuple(str(c) for c in candidates)
            for kind, candidates in raw.items() if isinstance(candidates, list)}


def _held(record: ObjectRecord) -> dict[str, float | None]:
    """레코드가 현재 들고 있는 증거 종류 → 그 품질 지표.

    값이 `None`이면 "있지만 품질을 잴 수 없음"이다. 없으면 키 자체가 빠진다.
    품질 지표의 의미는 종류마다 다르므로(신뢰도 / 지지 소스 수) 해석은 호출부에서 한다.
    """
    out: dict[str, float | None] = {}
    if record.geometry is not None:
        out["existence"] = record.confidence
        # geometry_kind가 표현 종류를 정한다. region은 2D, 그 외는 그대로 쓴다.
        out["region_2d" if record.geometry_kind == "region" else record.geometry_kind] = \
            record.confidence
    if record.semantic_class != UNKNOWN_CLASS:
        # **신뢰도가 아니라 지지 소스 수로 센다**(AI-S-03). 한 모델이 0.94로 틀리는
        # 경우가 실측됐고(2026-09-21), 그때 임계로는 거를 수 없었다.
        out["semantic_class"] = float(record.supporting_groups)
    if record.object_id:
        out["track_identity"] = float(record.supporting_groups)
    return out


def _quality(spec, value) -> tuple[str, str]:
    """이미 **있는** 증거가 쓸 만한가. (충족 상태, 사유)."""
    if spec.tolerance is None or value is None:
        return "met", "근거 있음(경계 미지정)"
    if spec.kind == "semantic_class":
        # 의미는 소스 **개수**로 재고, tolerance는 최소 지지 그룹 수로 읽는다.
        need = max(1, int(spec.tolerance))
        return ("met", f"지지 소스 {int(value)}개 ≥ {need}") if value >= need else \
               ("unmet", f"지지 소스 {int(value)}개 < {need}")
    return ("met", f"{value:.3f} ≥ {spec.tolerance}") if value >= spec.tolerance else \
           ("unmet", f"{value:.3f} < {spec.tolerance}")


def evaluate(contract: MissionContract, record: ObjectRecord,
             available_kinds: frozenset[str] | None = None,
             kind_providers: dict[str, tuple[str, ...]] | None = None
             ) -> SufficiencyVerdict:
    """계약 대비 충족 판정.

    `available_kinds=None`은 "무엇이 가능한지 모름"이며, 그때는 전부 얻을 수 있다고
    본다 — 모른다는 이유로 미리 포기하지 않는다(AI-S-05).
    """
    table = kind_providers if kind_providers is not None else load_kind_providers()
    held = _held(record)

    # 1) 존재 층 — 기존 AI-S-07 구현이 유일한 정의다.
    presence = evaluate_gap(contract.as_purpose_requirement(), set(held))
    absent = set(presence.missing_required) | set(presence.missing_preferred)

    # 2) 품질·획득 가능성 층 — 이 모듈이 더하는 부분.
    items = []
    for spec in contract.required:
        cands = table.get(spec.kind, ())
        obtainable = available_kinds is None or bool(set(cands) & available_kinds)
        if spec.kind in absent:
            if not cands:
                # **매핑이 없다.** "만들 수 없다" 가 아니라 "무엇이 만드는지 모른다" 다.
                # 이것을 `unobtainable` 로 적으면 `gap()` 이 요청으로 내보내지 않아
                # 전체가 조용히 멈춘다(위 표의 설명).
                state, why = ("provider_mapping_undeclared",
                              f"{spec.kind} 를 만드는 capability kind 가 선언되지 않았다")
            elif obtainable:
                state, why = ("unmet", "확보된 근거 없음")
            else:
                state, why = ("unobtainable",
                              "이 증거를 만들 수 있는 provider가 등록돼 있지 않다")
        else:
            state, why = _quality(spec, held[spec.kind])
        items.append(SufficiencyItem(spec.kind, state, spec.necessity, why))
    return SufficiencyVerdict(contract.mission_id, contract.revision, tuple(items))


def gap(contract: MissionContract, record: ObjectRecord,
        available_kinds: frozenset[str] | None = None,
        kind_providers: dict[str, tuple[str, ...]] | None = None
        ) -> tuple[EvidenceNeed, ...]:
    """다음에 채워야 할 결손. **필수가 앞, 선택이 뒤**로 정렬된다.

    `unobtainable`은 내보내지 않는다 — 요청해봐야 만들 사람이 없다. 그 사실은
    `evaluate()`의 판정에 남아 호출자가 "부족한 근거를 명시한 채" 진행할 수 있다.

    `provider_mapping_undeclared`도 내보내지 않지만 **이유가 다르다**: 무엇을 요청해야
    하는지 모르는 것이고, 고칠 곳은 현장이 아니라 **매핑 선언**이다. 호출자가 그 둘을
    구분할 수 있어야 "현장에 장비가 없다" 와 "우리 표가 비어 있다" 를 가린다 —
    `unanswerable_kinds()` 가 그 목록을 낸다.
    """
    table = kind_providers if kind_providers is not None else load_kind_providers()
    verdict = evaluate(contract, record, available_kinds, table)
    needs = []
    for item in verdict.items:
        if item.state not in ("unmet", "contested"):
            continue
        needs.append(EvidenceNeed(
            evidence_id=item.kind,
            candidate_capability_kinds=table.get(item.kind, ()),
            conflicting=item.state == "contested",
        ))
    order = {"required": 0, "preferred": 1}
    by_kind = {i.kind: i for i in verdict.items}
    needs.sort(key=lambda n: order.get(by_kind[n.evidence_id].necessity, 1))
    return tuple(needs)


def unanswerable_kinds(verdict: SufficiencyVerdict) -> tuple[str, ...]:
    """요청으로 나가지 못한 종류들 — **왜 못 나갔는지가 섞이지 않게** 따로 낸다.

    `gap()` 은 `unobtainable` 과 `provider_mapping_undeclared` 를 둘 다 내보내지
    않으므로, 그것만 보는 호출자에게는 둘이 똑같이 **빈 목록**으로 보인다. 그 상태가
    "현장에 장비가 없어 할 수 있는 것이 없다" 인지 "우리 매핑표가 비어 있어 무엇을
    요청해야 하는지 모른다" 인지는 고칠 곳이 다르다.
    """
    return tuple(item.kind for item in verdict.items
                 if item.state == "provider_mapping_undeclared")

