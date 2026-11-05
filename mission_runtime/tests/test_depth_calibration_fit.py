"""보정 계수는 **잴 수밖에 없다** — 그래서 도구는 맞추거나 거절한다.

이 묶음이 지키는 것 넷.

1. 기준 거리가 없거나 모자라면 **계수를 만들어 내지 않는다.** 거절도 프로파일
   모양으로 나와 선언에 그대로 들어가고, 거리는 미측정으로 흐른다.
2. 거절 사유가 서로 다르다 — 표본이 적은 것과 거리가 안 퍼진 것은 다음에 할
   일이 다르다.
3. **기준의 출처가 지위를 정한다.** 로봇 실측과 다른 경로를 기준으로 맞춘 것은
   같은 확신이 아니고, 도구가 지위를 올려 주지 않는다.
4. 맞춘 구간 밖으로 유효 범위를 넓히지 않는다.

implements: AI-E-02, AI-B-01, AI-S-08, AI-L-06
tests: refusal reasons, coefficient recovery, status from reference source,
       valid range bounded by the samples, fitted profile loads back
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from fit_depth_calibration import (  # noqa: E402
    MIN_SAMPLES,
    REASON_NO_SPREAD,
    REASON_TOO_FEW,
    REASON_UNKNOWN_SPACE,
    fit,
)

from edge.depth_contract import STATUS_MEASURED, DepthField, measure_distance  # noqa: E402
from perception.obstacle_evidence import load_calibration_profiles  # noqa: E402

PROVIDER = "zipdepth_base_384x384.onnx.cpu"
SPACE = "affine_invariant_inverse"


def _document(samples, **over) -> dict:
    body = {"provider_key": PROVIDER, "depth_space": SPACE,
            "reference_source": "tape_measure", "samples": samples}
    body.update(over)
    return body


def _true_curve(p: float, q: float, rels) -> list[dict]:
    """`1/cm = p*z + q` 를 정확히 따르는 표본 — 계수 복원을 볼 수 있다."""
    return [{"rel_depth": z, "reference_cm": 1.0 / (p * z + q)} for z in rels]


# ── 거절 ────────────────────────────────────────────────────────────────────

def test_too_few_reference_samples_is_refused_not_guessed():
    """2 점이면 항상 완벽히 맞고 그 완벽함은 적합도가 아니라 자유도 0 이다."""
    profile = fit(_document(_true_curve(2.0, 0.001, (0.02, 0.08))))

    assert profile["refusal_reason"] == REASON_TOO_FEW
    assert profile["coefficients"] == []
    assert profile["status"] == "unfitted"


def test_reference_distances_that_do_not_spread_are_refused():
    """같은 거리에서만 잰 표본으로는 곡선이 안 맞는다 — 맞춘 것처럼 보이는 계수가
    나오고 그 계수는 다른 거리에서 전부 틀린다."""
    flat = [{"rel_depth": 0.05 + i * 0.01, "reference_cm": 100.0 + i} for i in range(6)]

    assert fit(_document(flat))["refusal_reason"] == REASON_NO_SPREAD


def test_samples_that_follow_the_model_but_sit_close_together_are_still_refused():
    """**모델을 정확히 따라도** 거리가 안 퍼지면 맞추지 않는다.

    rel 0.02~0.09 는 5.5~24.4cm 로 19cm 범위다. 식이 맞는지와 그 식을 넓게
    쓸 수 있는지는 다른 질문이고, 뒤쪽을 표본이 답해 주지 못한다.
    """
    narrow = fit(_document(_true_curve(2.0, 0.001, (0.02, 0.04, 0.06, 0.09))))

    assert narrow["refusal_reason"] == REASON_NO_SPREAD


def test_an_unknown_depth_space_is_refused_rather_than_assumed():
    """공간을 모르면 식의 모양도 모른다. 하나를 골라 맞추면 그 선택이 숨는다."""
    profile = fit(_document(_true_curve(2.0, 0.001, (0.01, 0.03, 0.06, 0.1)),
                            depth_space="어디서온공간"))

    assert profile["refusal_reason"] == REASON_UNKNOWN_SPACE


def test_a_refusal_is_shaped_like_a_profile_so_the_fact_survives():
    """빈 파일이나 예외로 끝내면 "맞추지 못했다" 가 어디에도 남지 않는다."""
    profile = fit(_document([]))

    assert set(profile) >= {"applies_to", "coefficients", "status", "source",
                            "refusal_reason", "quality"}
    assert profile["applies_to"]["provider_key"] == PROVIDER
    assert REASON_TOO_FEW in profile["source"]
    assert profile["quality"]["sample_count"] == 0


# ── 맞춤 ────────────────────────────────────────────────────────────────────

def test_the_coefficients_are_recovered_from_a_curve_that_follows_the_model():
    profile = fit(_document(_true_curve(2.0, 0.001, (0.01, 0.03, 0.05, 0.08, 0.10))))

    assert profile.get("refusal_reason") is None
    p, q = profile["coefficients"]
    assert p == pytest.approx(2.0, abs=1e-6)
    assert q == pytest.approx(0.001, abs=1e-6)
    assert profile["quality"]["fit_residual_cm_rms"] == pytest.approx(0.0, abs=1e-6)


def test_the_valid_range_is_bounded_by_the_samples_that_were_taken():
    """맞춘 구간 밖에서 그 식을 쓰면 외삽이고, 외삽은 측정이 아니다."""
    # rel 0.005~0.09 → 90.9cm~5.5cm. 퍼짐이 좁으면 거절이 먼저 걸린다(아래 시험).
    profile = fit(_document(_true_curve(2.0, 0.001, (0.005, 0.02, 0.05, 0.09))))

    assert profile.get("refusal_reason") is None
    assert profile["valid_rel_range"] == [0.005, 0.09]


def test_the_sample_count_and_span_are_recorded_as_measured_quality():
    profile = fit(_document(_true_curve(2.0, 0.001, (0.01, 0.04, 0.07, 0.10))))

    assert profile["quality"]["sample_count"] == 4
    assert profile["quality"]["fitted_rel_span"] == pytest.approx(0.09)
    assert "accuracy_cm" not in profile["quality"], "재지 않은 항목은 키가 없다"


def test_the_reference_source_decides_the_status_and_the_tool_does_not_promote_it():
    """로봇 실측과 다른 경로를 기준으로 맞춘 것은 **같은 확신이 아니다**(AI-L-06)."""
    samples = _true_curve(2.0, 0.001, (0.01, 0.04, 0.07, 0.10))

    assert fit(_document(samples, reference_source="tape_measure"))["status"] == "deployed"
    assert fit(_document(samples, reference_source="surveyed_landmark"))["status"] \
        == "provisional"
    assert fit(_document(samples, reference_source="metric_depth_model"))["status"] \
        == "provisional"
    # 출처를 안 적으면 올려 주지 않는다.
    assert fit(_document(samples, reference_source=""))["status"] == "provisional"


def test_the_inverse_space_gets_the_near_side_percentile():
    """역깊이는 근거리가 큰 값이라 p60 이 depth 의 p40 과 같은 의도다."""
    inverse = fit(_document(_true_curve(2.0, 0.001, (0.01, 0.04, 0.07, 0.10))))

    assert inverse["roi_percentile"] == 60.0


def test_minimum_samples_is_at_least_four_so_a_residual_exists():
    """3 점으로 3차를 맞추면 잔차가 0 이 되고 품질을 말할 수 없다."""
    assert MIN_SAMPLES >= 4


# ── 맞춘 프로파일이 실제로 거리를 낸다 ──────────────────────────────────────

def test_a_fitted_profile_loads_back_and_produces_a_distance(tmp_path):
    """도구의 산출이 선언 파일에 그대로 들어가 **거리를 내기까지** 간다.

    여기서 끊기면 계수를 맞춰도 운영에는 닿지 않는다.
    """
    numpy = pytest.importorskip("numpy")

    profile = fit(_document(_true_curve(2.0, 0.001, (0.01, 0.04, 0.07, 0.10))))
    declaration = tmp_path / "depth_calibration.json"
    declaration.write_text(json.dumps({"profiles": [profile]}, ensure_ascii=False),
                           encoding="utf-8")

    loaded = load_calibration_profiles(declaration)
    assert PROVIDER in loaded

    # 맞춘 구간 안의 상대값 하나를 넣는다. 1/(2*0.05 + 0.001) = 9.90cm
    field_ = DepthField(values=numpy.full((40, 46), 0.05), depth_space=SPACE,
                        provider_key=PROVIDER, source_wh=(46, 40), infer_wh=(46, 40))
    measured = measure_distance(loaded[PROVIDER], field_, (5.0, 5.0, 40.0, 35.0))

    assert measured.status == STATUS_MEASURED
    assert measured.distance_cm == pytest.approx(1.0 / (2.0 * 0.05 + 0.001), rel=1e-6)
    assert measured.profile_id == profile["profile_id"]


def test_a_refused_profile_loads_back_but_produces_no_distance(tmp_path):
    """거절은 선언에 들어가도 **거리를 내지 않는다** — 그것이 거절의 뜻이다."""
    numpy = pytest.importorskip("numpy")

    refused = fit(_document([]))
    declaration = tmp_path / "depth_calibration.json"
    declaration.write_text(json.dumps({"profiles": [refused]}, ensure_ascii=False),
                           encoding="utf-8")

    loaded = load_calibration_profiles(declaration)
    field_ = DepthField(values=numpy.full((40, 46), 0.05), depth_space=SPACE,
                        provider_key=PROVIDER, source_wh=(46, 40), infer_wh=(46, 40))
    measured = measure_distance(loaded[PROVIDER], field_, (5.0, 5.0, 40.0, 35.0))

    assert measured.distance_cm is None
    assert measured.status != STATUS_MEASURED
