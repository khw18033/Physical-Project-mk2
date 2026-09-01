"""Capability-gated cross-source track linking (AI-S-02).

implements: AI-S-02, AI-C-10, AI-C-11
tests: tests/test_multisource.py, scenarios/multisource (SURV-11, SURV-12)

`MultiObservationAssociator` (association.py) answers one question about
one pair of tracks. It is not, by itself, an integration path: something
has to decide *which* optional evidence this deployment may use at all,
walk the candidate pairs, and — crucially — keep per-source tracking
alive when none of that evidence is available.

That decision is what this module owns:

* 시간 동기화, 전역 좌표, 외형(ReID) 은 모두 **선택 capability** 다. 등록되어
  있지 않으면 그 근거는 트랙이 값을 들고 있더라도 사용하지 않는다
  (AI-C-11: 선택 조건이 없어지면 축소 모드로 전환한다).
* 근거가 하나도 없으면 연계만 비활성화되고, 소스별 추적 결과는 입력 그대로
  반환된다 (AI-S-02: "하나라도 없다고 전체 추적을 중단해서는 안 된다.
  필요한 근거가 부족하면 관측 소스별 추적을 독립적으로 유지해야 한다").
* 같은 소스끼리의 쌍은 오류가 아니라 그냥 건너뛴다. 단일 카메라 배치는
  정상 구성이며 예외를 던질 상황이 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

from perception_framework.perception.association import (
    AssociationResult, MultiObservationAssociator, ObservedTrack,
)

#: 근거 종류 -> 그 근거를 실제로 만들어 주는 선택 capability kind.
#: 이름은 배포마다 다를 수 있으므로 생성자에서 바꿀 수 있다.
DEFAULT_EVIDENCE_CAPABILITIES: Mapping[str, str] = {
    "time": "sync.time",
    "space": "coordinates.global",
    "appearance": "reid.embedding",
}


@dataclass(frozen=True)
class SourceLink:
    """두 관측 소스의 트랙이 동일 객체 후보로 연계된 결과."""

    left: tuple[str, int]          # (source_id, track_local_id)
    right: tuple[str, int]
    score: float
    basis: tuple[str, ...]


@dataclass(frozen=True)
class LinkingOutcome:
    links: tuple[SourceLink, ...]
    #: 이 실행에서 실제로 사용할 수 있었던 근거 종류.
    usable_evidence: tuple[str, ...]
    #: 소스별 트랙 식별자. 연계 성패와 무관하게 항상 입력 그대로 유지된다.
    per_source_tracks: Mapping[str, tuple[int, ...]]
    #: 같은 소스라서 비교하지 않은 쌍 (단일 카메라 배치에서 전부 여기로 간다).
    same_source_pairs: int
    #: 비교했으나 연계되지 않은 쌍.
    rejected_pairs: int

    @property
    def association_active(self) -> bool:
        return bool(self.usable_evidence)


class CrossSourceLinker:
    def __init__(
        self,
        associator: MultiObservationAssociator | None = None,
        *,
        evidence_capabilities: Mapping[str, str] = DEFAULT_EVIDENCE_CAPABILITIES,
    ) -> None:
        self._associator = associator or MultiObservationAssociator()
        self._evidence_capabilities = dict(evidence_capabilities)

    def usable_evidence(self, available_kinds: Iterable[str]) -> tuple[str, ...]:
        available = set(available_kinds)
        return tuple(name for name, kind in self._evidence_capabilities.items()
                     if kind in available)

    def _mask(self, track: ObservedTrack, usable: tuple[str, ...]) -> ObservedTrack:
        """등록되지 않은 근거는 트랙이 값을 들고 있어도 쓰지 않는다."""
        return replace(
            track,
            observed_at=track.observed_at if "time" in usable else None,
            global_position=track.global_position if "space" in usable else None,
            appearance_embedding=(track.appearance_embedding
                                  if "appearance" in usable else None),
        )

    def link(self, tracks: Sequence[ObservedTrack],
             available_kinds: Iterable[str]) -> LinkingOutcome:
        per_source: dict[str, list[int]] = {}
        for t in tracks:
            per_source.setdefault(t.source_id, []).append(t.track_local_id)

        usable = self.usable_evidence(available_kinds)
        links: list[SourceLink] = []
        same_source = 0
        rejected = 0

        # 근거가 하나도 없으면 비교 자체를 하지 않는다. 소스별 추적만 남는다.
        if usable:
            masked = [self._mask(t, usable) for t in tracks]
            for i in range(len(masked)):
                for j in range(i + 1, len(masked)):
                    a, b = masked[i], masked[j]
                    if a.source_id == b.source_id:
                        same_source += 1
                        continue
                    result: AssociationResult = self._associator.associate(a, b)
                    if result.linked:
                        links.append(SourceLink(
                            (a.source_id, a.track_local_id),
                            (b.source_id, b.track_local_id),
                            result.score, result.basis))
                    else:
                        rejected += 1
        else:
            for i in range(len(tracks)):
                for j in range(i + 1, len(tracks)):
                    if tracks[i].source_id == tracks[j].source_id:
                        same_source += 1

        return LinkingOutcome(
            links=tuple(links),
            usable_evidence=usable,
            per_source_tracks={s: tuple(v) for s, v in per_source.items()},
            same_source_pairs=same_source,
            rejected_pairs=rejected,
        )
