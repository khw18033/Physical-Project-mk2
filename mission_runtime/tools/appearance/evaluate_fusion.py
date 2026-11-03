#!/usr/bin/env python3
"""외형 하나로 판정할 때와 여러 단서를 합칠 때가 **얼마나** 다른지 잰다.

implements: AI-E-01, AI-S-03, AI-S-04
관련: AI-B-01 (측정하지 않은 값을 성능으로 적지 않는다), AI-C-13
tests: tests/test_device_class_estimator.py

사전의 참조영상마다 leave-one-out 으로 외형 판정을 만들고(자기 자신은 빼고 재므로
유사도 1.0 이 섞이지 않는다), 그 위에 그 기종의 장치가 실제로 공지·등록하는 다른
단서를 얹어 같은 판정을 다시 돌린다. 세는 것은 셋이다 —

    확신 정답   ESTIMATED 이고 기종이 맞다
    확신 오답   ESTIMATED 인데 기종이 틀리다  ← 가장 비싼 칸이다
    모호/모순   AMBIGUOUS · CONFLICTED · NO_CUE (고르지 않았다)

## 이 측정이 **증명하지 않는** 것

다른 단서(공지 어휘·자원 태그·운동·크기)는 그 장치의 선언에서 나오므로 이 실험에서는
언제나 맞다. 그래서 "다중 단서가 외형보다 정확하다"가 아니라 두 가지만 말할 수 있다 —

1. 외형이 **가르지 못한** 때(모호) 다른 단서가 대신 가르는가. 이것은 실제 이득이다.
2. 외형이 **틀리게 확신**할 때 다른 단서가 그 확신을 멈추는가. 이것이 `--flip` 이
   재는 것이고, 사전에 기록된 두 번의 1 위 뒤집힘이 바로 그 경우다.

선언이 틀린 경우(장치가 잘못된 태그를 달고 조인한 경우)는 여기서 재지 않는다. 그
경우의 동작은 시험이 고정한다(tests/test_device_class_estimator.py 의 모순 시험).

사용법:

    python3 tools/appearance/evaluate_fusion.py \\
        --dictionary config/device_appearance_classes.example.json
    python3 tools/appearance/evaluate_fusion.py ... --flip   # 1 위 뒤집힘 모사
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mission_runtime.perception.appearance_classifier import (  # noqa: E402
    AppearanceClassifier,
    AppearanceDictionary,
)
from mission_runtime.perception.device_class_estimator import (  # noqa: E402
    ClassProfiles,
    ClassState,
    DeviceClassEstimator,
    announced_action_cue,
    apparent_size_cue,
    appearance_cue,
    motion_cue,
    resource_tag_cue,
)

#: 재는 구성. 단서를 하나씩 켜 가며 **무엇이 이득을 만들었는지** 분리한다.
#: 전부 켠 것만 재면 "좋아졌다"는 말은 할 수 있어도 무엇 덕분인지는 말할 수 없다.
CONFIGURATIONS = (
    ("appearance only", ()),
    ("+ announced actions", ("actions",)),
    # 배치가 역할 수준의 태그 하나(tier.*)만 등록한 경우. 현실적인 최소 선언이고,
    # 같은 역할인 두 기종(go1·ep01)을 **가르지 못한다** — 다중 단서가 거저
    # 이기지 않는 구간을 일부러 하나 둔다.
    ("+ tier tag only", ("tier_tag",)),
    ("+ full resource tags", ("tags",)),
    ("+ size, motion", ("size", "motion")),
    ("all cues", ("actions", "tags", "size", "motion")),
)


def _leave_one_out_verdict(classifier, dictionary, truth: str, index: int):
    """참조영상 한 장을 사전에서 빼고 그 장을 판정한다.

    자기 자신을 참조로 두고 재면 유사도가 항상 1.0 이라 아무것도 검증하지 못한다.
    """
    import numpy as np

    entry = next(e for e in dictionary.fit_classes if e.class_name == truth)
    probe = entry.embeddings[index]
    reduced = []
    for other in dictionary.fit_classes:
        if other.class_name != truth:
            reduced.append(other)
            continue
        keep = [i for i in range(len(other.references)) if i != index]
        reduced.append(type(other)(
            class_name=other.class_name, label=other.label,
            references=tuple(other.references[i] for i in keep),
            embeddings=np.delete(other.embeddings, index, axis=0),
            top_k=other.top_k))
    trimmed = type(dictionary)(
        classes=tuple(reduced), model_version=dictionary.model_version,
        ambiguity_margin=dictionary.ambiguity_margin,
        similarity_floor=dictionary.similarity_floor, top_k=dictionary.top_k)
    return AppearanceClassifier(trimmed).classify_embedding(probe)


def _flip(verdict, profiles):
    """1 위와 2 위를 바꿔 "외형이 틀리게 확신한" 상태를 만든다.

    사전에 기록된 실패 두 건이 정확히 이 모양이었다 — 배경과 조명이 닮아 다른 기종이
    1 위로 올라섰다. 그때 다른 단서가 그 확신을 멈추는지가 이 모드의 질문이다.
    """
    from dataclasses import replace

    if len(verdict.ranked) < 2:
        return verdict
    swapped = (verdict.ranked[1], verdict.ranked[0]) + verdict.ranked[2:]
    return replace(verdict, ranked=swapped, appearance_class=swapped[0].class_name,
                   state=type(verdict.state).CLASSIFIED,
                   reason=f"forced_flip_for_measurement:{swapped[0].class_name}")


def run(dictionary_path: Path, *, flip: bool) -> dict:
    dictionary = AppearanceDictionary.load(dictionary_path)
    profiles = ClassProfiles.load(dictionary_path)
    estimator = DeviceClassEstimator(profiles)
    classifier = AppearanceClassifier(dictionary)

    rows: list[tuple[str, str, object]] = []
    for entry in dictionary.fit_classes:
        for index, reference in enumerate(entry.references):
            verdict = _leave_one_out_verdict(classifier, dictionary, entry.class_name, index)
            rows.append((entry.class_name, reference.file,
                         _flip(verdict, profiles) if flip else verdict))

    out: dict = {"probes": len(rows), "flip": flip, "configurations": {}}
    for label, enabled in CONFIGURATIONS:
        tally = {"confident_correct": 0, "confident_wrong": 0,
                 "ambiguous": 0, "conflicted": 0, "no_cue": 0,
                 # 모순으로 떨어졌지만 **결정적 단서가 적어 넣은 이름은 맞은** 경우.
                 # 이것을 세지 않으면 "모순 86 건"이 "아무것도 못 했다"로 읽힌다.
                 "conflicted_naming_truth": 0}
        per_class: dict[str, dict[str, int]] = {}
        wrong: list[dict] = []
        for truth, file_name, verdict in rows:
            profile = profiles.get(truth)
            cues = [appearance_cue(verdict, observed_at=0.0)]
            if "actions" in enabled:
                cues.append(announced_action_cue(profile.action_vocabulary, profiles,
                                                 observed_at=0.0))
            if "tier_tag" in enabled:
                # 가족 이름으로 고른다 — 태그 이름 접두사로 분기하면 새 태그마다
                # 이 도구를 고쳐야 한다.
                family = profiles.exclusive_tag_families.get("tier", frozenset())
                cues.append(resource_tag_cue(profile.signature_tags & family, profiles,
                                             observed_at=0.0))
            if "tags" in enabled:
                cues.append(resource_tag_cue(profile.signature_tags, profiles, observed_at=0.0))
            if "size" in enabled and profile.size_m:
                middle = sum(profile.size_m) / 2.0
                cues.append(apparent_size_cue(middle, profiles, observed_at=0.0))
            if "motion" in enabled and profile.mobile:
                cues.append(motion_cue(1.2, profiles, observed_at=0.0))
            estimate = estimator.estimate(cues)

            bucket = per_class.setdefault(truth, dict.fromkeys(tally, 0))
            if estimate.state is ClassState.ESTIMATED:
                key = ("confident_correct" if estimate.device_class == truth
                       else "confident_wrong")
            elif estimate.state is ClassState.CONFLICTED:
                key = "conflicted"
            elif estimate.state is ClassState.AMBIGUOUS:
                key = "ambiguous"
            else:
                key = "no_cue"
            tally[key] += 1
            bucket[key] += 1
            if key == "conflicted" and estimate.device_class == truth:
                tally["conflicted_naming_truth"] += 1
                bucket["conflicted_naming_truth"] += 1
            if key == "confident_wrong":
                wrong.append({"truth": truth, "file": file_name,
                              "picked": estimate.device_class, "reason": estimate.reason})
        out["configurations"][label] = {"total": tally, "per_class": per_class,
                                        "confident_wrong_cases": wrong}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dictionary", required=True, type=Path)
    parser.add_argument("--flip", action="store_true",
                        help="외형 1·2 위를 바꿔 '틀리게 확신한' 상태를 모사한다")
    parser.add_argument("--json", action="store_true", help="집계를 JSON 으로 낸다")
    args = parser.parse_args(argv)

    result = run(args.dictionary, flip=args.flip)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"probes={result['probes']}  flip={result['flip']}\n")
    print(f"{'configuration':<22}{'correct':>8}{'wrong':>7}{'ambig':>7}{'conflict':>9}"
          f"{'(names truth)':>14}")
    for label, block in result["configurations"].items():
        t = block["total"]
        print(f"{label:<22}{t['confident_correct']:>8}{t['confident_wrong']:>7}"
              f"{t['ambiguous']:>7}{t['conflicted']:>9}{t['conflicted_naming_truth']:>14}")
    print()
    for label, block in result["configurations"].items():
        print(f"-- {label}")
        for name in sorted(block["per_class"]):
            c = block["per_class"][name]
            print(f"   {name:<18} correct={c['confident_correct']:>3} "
                  f"wrong={c['confident_wrong']} ambiguous={c['ambiguous']:>2} "
                  f"conflicted={c['conflicted']:>2}")
        for case in block["confident_wrong_cases"]:
            print(f"   ! {case}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
