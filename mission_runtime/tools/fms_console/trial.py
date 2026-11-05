"""관제 웹의 "돌려 보고 고르기" 책상 — 운영자 입력을 시도 계약으로 옮긴다.

implements: AI-B-09 (운영 후보가 되기 전 검증), AI-L-06 (관리자 판단 정보)
관련: AI-B-01, AI-C-08, AI-C-13, AI-C-19, AI-C-05
tests: tests/test_console_trial.py

**판정을 새로 만들지 않는다.** 시도의 의미 계약은 `runtime/model_trial.py` 가,
적격 판정은 `runtime/model_assignment.py` 가, 구성 신원과 재측정 의무는
`contracts/profile.py` 가 소유한다. 이 모듈은 폼 입력을 그 자료형으로 옮기고
결과를 화면이 읽는 한 덩어리로 낸다(CLAUDE.md §0: 콘솔은 판정을 하지 않는다).

오버레이를 서버가 합성하지 않는다
---------------------------------
운영자는 그림 위에 상자가 겹친 것을 보고 고른다. 그런데 그 합성을 서버가 하면
**색·선 굵기·글꼴을 서버가 정하게 되고**, 그것은 응답에 표현 결정을 넣지 않는다는
규칙에 걸린다(`tests/test_view_contract.py` 가 그 규칙을 지킨다). 그래서 둘을 따로
낸다 — 프레임 픽셀은 `/api/media`(AI-C-08), 상자는 상태 계약. 겹치는 것은 화면의
일이고, 그래서 같은 두 입력으로 우리 콘솔도 Unity 뷰어도 각자 그릴 수 있다.

어휘를 바꾸는 것은 **다른 실행 구성이다**
----------------------------------------
제로샷 모델에서 클래스 프롬프트는 동작을 가장 크게 바꾸는 입력이다. 그래서
`contracts/profile.py::AXIS_PROMPT` 가 구성 축이고, 어휘를 바꾸면 지문이 달라져
옛 측정값이 그 구성에 붙지 않는다. 이 책상이 그 축을 채우므로 **웹에서 프롬프트를
바꾸는 순간 재측정 의무가 생긴다** — 그것이 의도다.

임계값을 바꾸는 것도 같다
-------------------------
점수 하한은 `AXIS_POSTPROCESS`(`postprocess_ref`)에 들어간다. 그래서 하한을 0.05
에서 0.4 로 바꾼 것은 **다른 구성**이고 지문이 달라진다 — 옛 측정값이 조용히 따라
오지 않는다(AI-B-01). 이 책상은 그 값을 코드 상수에서 읽지 않고
`config/detection_thresholds.example.json` 의 선언과 운영자 장부에서 받아 오며,
**각 값이 어디서 왔는지**(`param_basis`)를 값과 다른 칸으로 함께 낸다.

하한 상태는 세 가지이고, 시도는 **아무것도 거르지 않는다**
---------------------------------------------------------
라벨마다 `above_floor` · `below_floor` · `no_floor_declared` 를 세어 낸다. 세는 것이
전부다 — 하한에 못 미친 상자도, 하한을 말할 근거가 없는 상자도 응답에서 빼지
않는다. 빼면 이름 없는 관측이 운영자 화면에서 사라지고, 그것이 AI-S-04 가 막는
동작이다. 어느 어휘로 판정할지는 **탐지기 선언이 정한다**(`taxonomy_vocabulary`) —
`"zeroshot"` 을 여기 적어 넣으면 프롬프트를 받지 않는 모델의 라벨이 운영자 어휘의
기본 하한을 빌려 선언된 하한처럼 보인다(그것이 실제 결함이었다).

상자 좌표는 **여기서** 나간다
-----------------------------
개수와 점수 폭만 내던 동안 화면은 오버레이를 그릴 수 없었다 — 운영자가 "이 모델이
무엇을 어디서 봤는가" 를 보려면 상자의 자리가 필요하다. 좌표는 표현이 아니라
**상태**이므로 상태 계약에 실린다. 픽셀은 여전히 여기로 나가지 않고 `/api/media`
가 낸다(AI-C-08).

`RunSummary`(`runtime/model_trial.py`)가 아니라 **이 책상의 응답**에 붙인 이유:
상자마다 붙는 하한 상태는 `floor_lookup` 이 답하고 그 주인은
`perception/obstacle_taxonomy.py` 와 `perception/detection_thresholds.py` 다.
`runtime/model_trial.py` 는 시도의 **의미 계약**이고 선언 파일을 모른다 — 거기에
상자+하한을 넣으려면 `floor_lookup` 을 계약 계층까지 내려 보내야 하고, 그러면
판정이 계약 안으로 들어온다. 그래서 상자는 하한을 물을 수 있는 자리에서 조립되고,
`runs[]` 와는 **구성 지문**으로 이어진다. 응답 크기의 상한은 그대로
`MAX_TRIAL_FRAMES` 다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from mission_runtime.contracts.profile import ExecutionConfiguration, prompt_ref_for
from mission_runtime.runtime.model_trial import (
    TrialDetection,
    TrialFrame,
    TrialRun,
    compare,
)

#: 거절 사유 토큰.
REASON_NO_FRAMES = "no_frames_selected"
REASON_UNKNOWN_FRAME = "unknown_frame"
REASON_NO_CANDIDATE = "no_candidate_selected"
REASON_DETECTOR_UNAVAILABLE = "detector_unavailable"
REASON_NO_FRAME_ASSETS = "no_frame_assets"
#: 그 후보를 세우면 **나가는 연결이 생긴다**. 운영자 클릭 하나가 수백 MB 를 끌어오는
#: 일은 폐쇄망에서 AI-C-16 위반이고 열린 망에서도 예상 못 한 일이다. 그래서 세우지
#: 않고 사유를 낸다 — 다운로드는 배포가 하는 일이고 조회·시도가 하는 일이 아니다.
REASON_WOULD_REACH_NETWORK = "would_reach_outbound_network"

#: 한 번의 시도에 받는 그림 수 상한. 운영자가 실수로 전체 폴더를 고르면 추론이
#: 분 단위로 돈다 — 상한을 두고 **자른 사실을 함께 낸다**(숨기지 않는다).
MAX_TRIAL_FRAMES = 8

#: 이번 시도에만 쓰려고 폼에 적어 넣은 값. 선언도 아니고 적용도 아니다 —
#: **돌려 보는 것과 적용하는 것은 다른 행위**이고 적용은 `POST /api/threshold` 다.
BASIS_TRIAL_REQUEST = "trial_request"


@dataclass(frozen=True)
class TrialCandidate:
    """운영자가 고른 한 후보. 구성 축을 채우는 재료다."""

    implementation_ref: str
    #: 그 구현을 실제로 세우는 것. `(vocabulary, params) -> provider | None`.
    vocabulary: tuple[str, ...] = ()
    #: 프롬프트를 받지 않는 모델인가. 어휘가 빈 것과 **다른 상태다**.
    prompt_free: bool = False
    #: 후처리 파라미터(점수 하한 등). 구성의 `postprocess_ref` 축이 된다 — 임계값을
    #: 바꾼 것은 다른 구성이고, 구현을 바꾼 것과 섞어 적으면 어느 쪽이 달라졌는지
    #: 운영 화면에서 읽을 수 없다.
    params: dict[str, Any] = None  # type: ignore[assignment]
    #: 각 파라미터 값이 **어디서 왔는가**(`declared` · `operator_edit` ·
    #: `trial_request`). 값과 같은 칸에 담지 않는다 — 담으면 선언된 0.05 와 운영자가
    #: 폼에 적어 넣은 0.05 가 화면에서 같은 수가 된다(AI-S-08·AI-L-03).
    param_basis: dict[str, str] = None  # type: ignore[assignment]
    #: 이 탐지기의 라벨을 **어느 어휘로 판정하는가**. 탐지기 선언의
    #: `taxonomy_vocabulary` 를 그대로 받는다. `None` 은 "선언된 어떤 어휘에도
    #: 속하지 않는다" 이고 "모른다" 가 아니다 — 그래서 어휘 하한을 빌리지 않는다.
    taxonomy_vocabulary: str | None = None
    #: 라벨이 어느 이름 공간에서 왔는가(선언의 `label_namespace`).
    label_namespace: str = ""

    def __post_init__(self) -> None:
        if self.params is None:
            object.__setattr__(self, "params", {})
        if self.param_basis is None:
            object.__setattr__(self, "param_basis", {})

    @property
    def postprocess_ref(self) -> str:
        """후처리 축의 값. 같은 파라미터는 같은 문자열이어야 한다."""
        if not self.params:
            return ""
        return ",".join(f"{k}={self.params[k]}" for k in sorted(self.params))

    def configuration(self, *, capability_kind: str, runtime_ref: str,
                      input_profile: str) -> ExecutionConfiguration:
        return ExecutionConfiguration(
            capability_kind=capability_kind,
            implementation_ref=self.implementation_ref,
            runtime_ref=runtime_ref,
            input_profile=input_profile,
            postprocess_ref=self.postprocess_ref,
            prompt_ref=prompt_ref_for(self.vocabulary, prompt_free=self.prompt_free),
        )


@dataclass
class TrialDesk:
    """후보들을 같은 그림에 돌려 보고 결과를 한 덩어리로 낸다."""

    #: `(implementation_ref, vocabulary, params) -> provider | None`.
    #: None 은 "그 구현을 이 노드에서 세울 수 없다" 이고 장애가 아니다(AI-C-05).
    resolver: Callable[..., Any]
    #: `(frame_ref) -> (bgr 배열, (w, h)) | None`. 픽셀을 **읽기만** 한다.
    frame_loader: Callable[[str], Any]
    #: 그 그림을 화면이 꺼낼 미디어 위치를 만드는 것.
    media_ref: Callable[[str], dict] | None = None
    capability_kind: str = "perception.detect_ovd"
    runtime_ref: str = ""
    #: `(label, score, vocabulary, label_namespace) -> 하한 행`. 판정의 주인은
    #: `perception/obstacle_taxonomy.py::score_floor` 와
    #: `perception/detection_thresholds.py` 이고 이 책상은 **그 답을 세기만** 한다.
    #: 없으면 하한 칸을 내지 않는다 — 없는 선언을 추측해 채우지 않는다.
    floor_lookup: Callable[[str, float, str | None, str], Mapping[str, Any]] | None = None

    def run(self, *, candidates: Sequence[TrialCandidate], frame_refs: Sequence[str],
            actor: str, ground_truth: dict | None = None) -> dict:
        """고른 후보들을 **같은 그림들에** 돌린다.

        거절도 결과다 — 사유와 함께 같은 모양으로 낸다. 빈 응답을 내면 화면이
        "아무것도 안 찾았다" 와 "돌리지 못했다" 를 구분할 수 없다.
        """
        picked = list(frame_refs)[:MAX_TRIAL_FRAMES]
        truncated = max(0, len(list(frame_refs)) - len(picked))
        if not picked:
            return self._refusal(REASON_NO_FRAMES)
        if not candidates:
            return self._refusal(REASON_NO_CANDIDATE)

        loaded: list[tuple[str, Any, tuple[int, int]]] = []
        for ref in picked:
            frame = self.frame_loader(ref)
            if frame is None:
                return self._refusal(f"{REASON_UNKNOWN_FRAME}:{ref}")
            image, size = frame
            loaded.append((ref, image, size))

        input_profile = "x".join(str(v) for v in loaded[0][2])
        runs: list[TrialRun] = []
        ran: list[TrialCandidate] = []
        unavailable: list[dict] = []
        for candidate in candidates:
            resolved = self.resolver(candidate.implementation_ref,
                                     list(candidate.vocabulary), dict(candidate.params))
            # 해소하는 쪽이 **사유를 돌려줄 수** 있다. 문자열이면 그것이 사유다 —
            # 전부 `detector_unavailable` 로 뭉개면 "가중치가 없다" 와 "세우면
            # 네트워크로 나간다" 가 운영 화면에서 같은 말이 된다.
            provider = None if isinstance(resolved, str) else resolved
            if provider is None or not getattr(provider, "is_available", lambda: True)():
                unavailable.append({
                    "implementation_ref": candidate.implementation_ref,
                    "reason": (resolved if isinstance(resolved, str)
                               else REASON_DETECTOR_UNAVAILABLE)})
                continue
            runs.append(self._run_one(candidate, provider, loaded,
                                      input_profile=input_profile, actor=actor))
            ran.append(candidate)

        verdict = compare(runs, ground_truth=ground_truth)
        payload = verdict.as_payload()
        if truncated:
            payload["caveats"] = [
                *payload["caveats"],
                f"고른 그림 중 {truncated}장은 한 번의 시도 상한({MAX_TRIAL_FRAMES})을 "
                "넘어 빠졌다",
            ]
        # 하한 상태를 **한 번만** 묻는다. 셈(`thresholds_used`)과 상자
        # (`detections`)가 각자 다시 물으면 같은 상자가 두 곳에서 다른 상태로
        # 적힐 여지가 생긴다 — 같은 답을 두 번 유도하지 않는다.
        floors = [self._floor_rows(candidate, run)
                  for candidate, run in zip(ran, runs)]
        return {
            **payload,
            "capability_kind": self.capability_kind,
            # 후보마다 **왜 이 구성인가**를 함께 낸다. 지문만 내면 운영자가 두 줄이
            # 왜 다른 구성인지 알 수 없다.
            "unavailable": unavailable,
            "frames": [self._frame_payload(ref, size) for ref, _, size in loaded],
            # 쓴 임계값과 **그 값의 출처**. `runs[]` 의 지문으로 이어진다.
            "thresholds_used": [self._threshold_payload(candidate, run, rows)
                                for candidate, run, rows in zip(ran, runs, floors)],
            # 상자의 자리. 화면이 겹쳐 그릴 재료이고 **픽셀이 아니다**(AI-C-08).
            "detections": [self._detection_payload(candidate, run, rows)
                           for candidate, run, rows in zip(ran, runs, floors)],
            # 시도가 측정이 아니라는 사실을 응답이 직접 말한다.
            "not_a_measurement": (runs[0].why_not_a_measurement() if runs else None),
        }

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _run_one(self, candidate: TrialCandidate, provider, loaded, *,
                 input_profile: str, actor: str) -> TrialRun:
        configuration = candidate.configuration(
            capability_kind=self.capability_kind,
            runtime_ref=self.runtime_ref or type(provider).__name__,
            input_profile=input_profile)
        frames, detections, latency = [], [], []
        for ref, image, _ in loaded:
            frames.append(TrialFrame(frame_ref=ref, media_ref=self._media_path(ref)))
            started = time.perf_counter()
            results = provider.detect(image)
            latency.append((time.perf_counter() - started) * 1000.0)
            for result in results:
                detections.append(TrialDetection(
                    label=str(getattr(result, "label", "")),
                    score=float(getattr(result, "confidence", 0.0)),
                    box_xyxy=tuple(float(v) for v in getattr(result, "box", (0, 0, 0, 0))),
                    frame_ref=ref,
                    # 프롬프트를 받지 않는 모델의 라벨은 어휘 일치가 아니다.
                    from_vocabulary=not candidate.prompt_free))
        return TrialRun(configuration=configuration, frames=tuple(frames),
                        detections=tuple(detections), latency_ms=tuple(latency),
                        actor=actor, ran_at=time.time())

    def _floor_rows(self, candidate: TrialCandidate,
                    run: TrialRun) -> list[dict] | None:
        """상자마다 그 하한 판정 한 줄. **순서가 `run.detections` 와 같다.**

        `floor_lookup` 이 없으면 `None` 이다 — 그것은 "하한이 없다" 가 아니라
        **물을 주인이 이 배치에 없다**는 뜻이고, 둘을 한 값으로 적으면 선언이 빈
        것과 판정자가 없는 것이 화면에서 같은 말이 된다.
        """
        if self.floor_lookup is None:
            return None
        return [dict(self.floor_lookup(det.label, det.score,
                                       candidate.taxonomy_vocabulary,
                                       candidate.label_namespace))
                for det in run.detections]

    def _detection_payload(self, candidate: TrialCandidate, run: TrialRun,
                           floors: list[dict] | None) -> dict:
        """이 구성이 **무엇을 어디서 봤는가**. 프레임별 상자 목록이다.

        하한에 못 미친 상자도, 하한을 말할 근거가 없는 상자도 **여기 들어 있다**
        (AI-S-04). 거르는 것은 이 응답의 일이 아니고, 걸러 내면 운영자가 하한을
        고치려고 보는 바로 그 상자들이 화면에서 사라진다. 상태를 상자마다 들고
        다니므로 화면이 셋을 다르게 그릴 수 있다.
        """
        by_frame: dict[str, list[dict]] = {f.frame_ref: [] for f in run.frames}
        for index, det in enumerate(run.detections):
            floor = (floors[index] if floors is not None else None)
            by_frame.setdefault(det.frame_ref, []).append({
                "label": det.label,
                "score": round(det.score, 4),
                # 탐지기가 낸 그대로의 픽셀 xyxy. 정규화하지 않는다 — 프레임 크기는
                # `frames[]` 가 따로 내고, 둘을 곱해 두면 원래 좌표가 사라진다.
                "box_xyxy": [round(float(v), 2) for v in det.box_xyxy],
                "from_vocabulary": det.from_vocabulary,
                # 셋째 상태(`no_floor_declared`)를 0 이나 `below_floor` 로 바꾸지
                # 않는다. `None` 은 또 다른 상태 — 물을 주인이 없었다는 뜻이다.
                "floor_state": (None if floor is None
                                else (floor.get("state") or None)),
                "floor_value": (None if floor is None else floor.get("value")),
                "floor_basis": (None if floor is None else floor.get("basis")),
                "threshold_id": (None if floor is None else floor.get("threshold_id")),
            })
        return {
            "configuration_fingerprint": run.configuration.fingerprint,
            "implementation_ref": candidate.implementation_ref,
            "postprocess_ref": candidate.postprocess_ref,
            "frames": [{"frame_ref": frame.frame_ref,
                        "boxes": by_frame.get(frame.frame_ref, [])}
                       for frame in run.frames],
        }

    def _threshold_payload(self, candidate: TrialCandidate, run: TrialRun,
                           floors: list[dict] | None = None) -> dict:
        """이 시도가 **어떤 값으로 돌았고 그 값이 어디서 왔는가**, 그리고 라벨별
        하한 상태의 수.

        하한 상태를 **세기만** 한다. 못 미친 상자를 응답에서 빼지 않는 이유는
        AI-S-04 다 — 이름을 모르는 관측을 화면에서 지우면 운영자가 그것을 확인하거나
        학습 후보로 올릴 길이 사라진다.
        """
        body: dict[str, Any] = {
            "configuration_fingerprint": run.configuration.fingerprint,
            "implementation_ref": candidate.implementation_ref,
            "postprocess_ref": candidate.postprocess_ref,
            "params": dict(candidate.params),
            # 값과 출처를 **다른 칸으로** 낸다.
            "param_basis": dict(candidate.param_basis),
            "taxonomy_vocabulary": candidate.taxonomy_vocabulary,
            "label_namespace": candidate.label_namespace,
        }
        if floors is None:
            floors = self._floor_rows(candidate, run)
        if floors is None:
            return body
        counts: dict[str, int] = {}
        per_label: dict[str, dict] = {}
        for det, row_floor in zip(run.detections, floors):
            floor = dict(row_floor)
            state = str(floor.get("state") or "")
            counts[state] = counts.get(state, 0) + 1
            row = per_label.setdefault(det.label, {**floor, "count": 0,
                                                   "state_counts": {}})
            row["count"] += 1
            # 같은 라벨 안에서도 점수에 따라 상태가 갈린다. 라벨당 한 상태만 적으면
            # 마지막 상자가 앞의 것들을 덮는다.
            row["state_counts"][state] = row["state_counts"].get(state, 0) + 1
            row.pop("state", None)
        body["floor_states"] = dict(sorted(counts.items()))
        body["label_floors"] = [
            dict(row, label=label, state_counts=dict(sorted(row["state_counts"].items())))
            for label, row in sorted(per_label.items())]
        return body

    def _frame_payload(self, ref: str, size=None) -> dict:
        # 상자는 픽셀 좌표라 그 좌표계의 크기가 함께 나가야 화면이 그릴 수 있다.
        # **프레임마다** 낸다 — 구성의 `input_profile` 은 첫 그림의 크기 하나뿐이고,
        # 크기가 다른 그림이 섞이면 그 하나로 나머지를 그리면 상자가 어긋난다.
        width, height = (size if size is not None else (None, None))
        body: dict[str, Any] = {"frame_ref": ref,
                                "width": (None if width is None else int(width)),
                                "height": (None if height is None else int(height))}
        if self.media_ref is not None:
            # 픽셀이 아니라 **꺼낼 자리**다(AI-C-08).
            body["media"] = self.media_ref(ref)
        return body

    def _media_path(self, ref: str) -> str:
        if self.media_ref is None:
            return ""
        located = self.media_ref(ref)
        return str(located.get("path", "")) if isinstance(located, dict) else str(located)

    def _refusal(self, reason: str) -> dict:
        return {"kind": "descriptive_no_ground_truth", "runs": [], "frame_refs": [],
                "agreement": [], "scored": {}, "reason": reason, "caveats": [],
                "capability_kind": self.capability_kind, "unavailable": [],
                "frames": [], "thresholds_used": [], "detections": [],
                "not_a_measurement": None}


def candidates_from_body(rows, *, declared: Callable[[str], Mapping[str, Any]] | None = None
                         ) -> tuple[TrialCandidate, ...]:
    """운영자 폼 → 후보들. 모르는 칸은 **무시하지 않고 기본값으로 남긴다.**

    `declared` 를 주면 그 탐지기의 **선언된 임계값**(+ 운영자 장부의 현재 값)과
    어휘·이름 공간을 가져와 폼이 적지 않은 칸을 채운다. 그래서 운영자가 아무 수도
    적지 않아도 시도가 코드 상수가 아니라 **선언된 값**으로 돈다. 폼에 적어 넣은
    수는 선언을 이기지만 그 사실이 `param_basis` 에 `trial_request` 로 남는다 —
    돌려 보는 것은 적용이 아니다(적용은 `POST /api/threshold`).
    """
    out = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        implementation = str(row.get("implementation_ref") or "").strip()
        if not implementation:
            continue
        vocabulary = tuple(str(v).strip() for v in (row.get("vocabulary") or ())
                           if str(v).strip())
        asked = {k: v for k, v in (row.get("params") or {}).items()
                 if isinstance(k, str)}
        defaults = dict(declared(implementation) or {}) if declared is not None else {}
        params = dict(defaults.get("params") or {})
        basis = dict(defaults.get("param_basis") or {})
        for name, value in asked.items():
            params[name] = value
            basis[name] = BASIS_TRIAL_REQUEST
        out.append(TrialCandidate(
            implementation_ref=implementation,
            vocabulary=vocabulary,
            # 폼이 적지 않았으면 **선언이 말하는 값**을 쓴다. 어휘를 받지 않는
            # 모델을 "어휘가 빈 모델" 로 적으면 구성 축이 섞인다(prompt_ref_for).
            prompt_free=bool(row["prompt_free"]) if "prompt_free" in row
            else bool(defaults.get("prompt_free", False)),
            params=params,
            param_basis=basis,
            taxonomy_vocabulary=defaults.get("taxonomy_vocabulary"),
            label_namespace=str(defaults.get("label_namespace") or "")))
    return tuple(out)
