"""implements: AI-B-09, AI-C-18
covers: four-step join contract, missing fields are not defaulted,
        adapter gaps surface, join is not an availability verdict
"""

import pytest

from mission_runtime.contracts.profile import ResourceBudget
from mission_runtime.providers.overlay import StaticOverlayProvider
from mission_runtime.registry.onboarding import (
    APPEARANCE_ASSET_TEMPLATE,
    JOIN_CONTRACT_VERSION,
    JoinRejection,
    JoinStep,
    NodeJoinManifest,
    NodeOnboarding,
    manifest_from_dict,
    node_config_entry,
)

GOOD = {
    "device_id": "spot-01",
    "role": "ugv",
    "label": "새 사족 로봇",
    "node_tags": ["compute.cpu", "tier.ugv", "locomotion.legged", "sensor.imu"],
    "budget": {"compute_units": 5.0, "memory_mb": 4096},
    "declared_actions": ["move_forward", "turn", "stop"],
}


def onboarding(**kwargs):
    kwargs.setdefault("overlay", StaticOverlayProvider(connected=True, peers={"new-dog": True}))
    return NodeOnboarding(**kwargs)


# --- 받아들이는 경로 --------------------------------------------------------


def test_a_complete_manifest_joins():
    outcome = onboarding().submit(manifest_from_dict(GOOD),
                                  announced_actions=["move_forward", "turn", "stop"])

    assert outcome.accepted is True
    assert outcome.rejections == ()


def test_joining_is_not_a_claim_that_the_device_is_available():
    """절대 준수 원칙 #15: 최종 가용성은 백엔드가 판정하고 여기서 재판정하지 않는다."""
    outcome = onboarding().submit(manifest_from_dict(GOOD), announced_actions=["stop"])

    assert not hasattr(outcome, "available")


def test_unknown_fields_pass_through_rather_than_being_rejected():
    manifest = manifest_from_dict({**GOOD, "vendor_note": "x", "future_field": 7})

    assert manifest.extra["vendor_note"] == "x"
    assert manifest.extra["future_field"] == 7


def test_the_appearance_path_is_the_contract_not_a_per_vendor_choice():
    manifest = manifest_from_dict(GOOD)

    assert manifest.appearance_dir(root="/srv/assets") == APPEARANCE_ASSET_TEMPLATE.format(
        root="/srv/assets", device_id="spot-01")


# --- 빠진 칸을 메우지 않는다 ------------------------------------------------


def test_a_half_filled_budget_stays_unmeasured_rather_than_becoming_zero():
    manifest = manifest_from_dict({**GOOD, "budget": {"compute_units": 4.0}})

    assert manifest.budget is None


def test_an_unmeasured_budget_leaves_profile_verification_as_work():
    manifest = manifest_from_dict({k: v for k, v in GOOD.items() if k != "budget"})

    outcome = onboarding().submit(manifest, announced_actions=["stop"])

    assert JoinStep.VERIFY_PROFILE in outcome.next_steps


def test_a_camera_without_a_calibration_version_leaves_calibration_as_work():
    outcome = onboarding().submit(manifest_from_dict({**GOOD, "has_camera": True}),
                                  announced_actions=["stop"])

    assert JoinStep.CALIBRATE_CAMERA in outcome.next_steps


def test_an_already_calibrated_camera_does_not_ask_for_calibration_again():
    outcome = onboarding().submit(
        manifest_from_dict({**GOOD, "has_camera": True,
                            "calibration_profile_version": "2026-10-19.1"}),
        announced_actions=["stop"])

    assert JoinStep.CALIBRATE_CAMERA not in outcome.next_steps


def test_without_appearance_images_classification_is_left_as_work():
    outcome = onboarding().submit(manifest_from_dict(GOOD), announced_actions=["stop"])

    assert JoinStep.LEARN_APPEARANCE in outcome.next_steps


def test_with_appearance_images_and_a_class_no_learning_is_queued():
    outcome = onboarding().submit(
        manifest_from_dict({**GOOD, "appearance_assets": ["a.jpg", "b.jpg"],
                            "appearance_class": "go1"}),
        announced_actions=["stop"])

    assert JoinStep.LEARN_APPEARANCE not in outcome.next_steps


# --- 거절하는 경로 ----------------------------------------------------------


def test_a_device_id_that_would_not_survive_a_topic_or_path_is_rejected():
    outcome = onboarding().submit(manifest_from_dict({**GOOD, "device_id": "Bad ID"}),
                                  announced_actions=["stop"])

    assert (JoinRejection.BAD_DEVICE_ID, "Bad ID") in outcome.rejections


def test_a_node_with_no_tags_is_rejected_rather_than_joining_with_no_capability():
    outcome = onboarding().submit(manifest_from_dict({**GOOD, "node_tags": []}),
                                  announced_actions=["stop"])

    assert any(code is JoinRejection.MISSING_FIELD and detail == "node_tags"
               for code, detail in outcome.rejections)


def test_a_node_with_no_action_vocabulary_at_all_is_rejected():
    outcome = onboarding().submit(
        manifest_from_dict({**GOOD, "declared_actions": []}), announced_actions=[])

    assert any(code is JoinRejection.NO_ACTION_VOCABULARY for code, _ in outcome.rejections)


def test_a_duplicate_device_id_is_not_silently_replaced():
    board = onboarding(known_device_ids={"spot-01"})

    outcome = board.submit(manifest_from_dict(GOOD), announced_actions=["stop"])

    assert any(code is JoinRejection.DUPLICATE_DEVICE_ID for code, _ in outcome.rejections)
    assert board.submit(manifest_from_dict(GOOD), announced_actions=["stop"],
                        replace=True).accepted is True


def test_a_peer_the_overlay_cannot_reach_is_rejected():
    outcome = onboarding().submit(
        manifest_from_dict({**GOOD, "overlay_peer": "not-joined"}), announced_actions=["stop"])

    assert any(code is JoinRejection.NOT_ON_OVERLAY for code, _ in outcome.rejections)


def test_without_an_overlay_provider_the_check_is_recorded_as_skipped():
    outcome = NodeOnboarding().submit(manifest_from_dict(GOOD), announced_actions=["stop"])

    assert "overlay_not_checked" in outcome.notes


# --- 어댑터 구현 누락이 드러난다 --------------------------------------------


def test_declared_but_never_announced_actions_are_surfaced():
    """어댑터가 그 action 을 아직 구현하지 않은 전형적인 모습이다."""
    outcome = onboarding().submit(manifest_from_dict(GOOD),
                                  announced_actions=["move_forward"])

    assert outcome.unannounced_declarations == ("stop", "turn")


def test_announced_but_undeclared_actions_are_surfaced_too():
    outcome = onboarding().submit(
        manifest_from_dict(GOOD),
        announced_actions=["move_forward", "turn", "stop", "sit"])

    assert outcome.undeclared_announcements == ("sit",)


def test_a_different_contract_version_is_recorded_not_refused():
    outcome = onboarding().submit(manifest_from_dict({**GOOD, "contract_version": "99"}),
                                  announced_actions=["stop"])

    assert outcome.accepted is True
    assert outcome.contract_version_mismatch == "99"
    assert JOIN_CONTRACT_VERSION != "99"


# --- 할 일 목록 -------------------------------------------------------------


def test_pending_lists_only_accepted_devices_that_still_owe_that_step():
    board = onboarding()
    board.submit(manifest_from_dict({**GOOD, "has_camera": True}), announced_actions=["stop"])
    board.submit(manifest_from_dict({**GOOD, "device_id": "Bad ID", "has_camera": True}),
                 announced_actions=["stop"])

    assert board.pending(JoinStep.CALIBRATE_CAMERA) == ("spot-01",)


def test_resolving_a_step_removes_it_and_leaves_a_note():
    board = onboarding()
    board.submit(manifest_from_dict({**GOOD, "has_camera": True}), announced_actions=["stop"])

    updated = board.resolve_step("spot-01", JoinStep.CALIBRATE_CAMERA)

    assert JoinStep.CALIBRATE_CAMERA not in updated.next_steps
    assert "resolved:calibrate_camera" in updated.notes
    assert board.pending(JoinStep.CALIBRATE_CAMERA) == ()


# --- 선언이 그대로 배치 계산의 입력이 된다 ----------------------------------


def test_a_manifest_becomes_a_node_config_row_without_hand_editing():
    entry = node_config_entry(manifest_from_dict(GOOD))

    assert entry["node_id"] == "spot-01"
    assert entry["role"] == "ugv"
    assert entry["tags"] == sorted(GOOD["node_tags"])
    assert entry["budget"] == {"compute_units": 5.0, "memory_mb": 4096.0}
    assert entry["verified"] is False, "현장 실측 전이라는 표시가 기본이다"


def test_an_unmeasured_budget_is_absent_from_the_config_row():
    entry = node_config_entry(
        manifest_from_dict({k: v for k, v in GOOD.items() if k != "budget"}))

    assert "budget" not in entry


def test_a_manifest_can_be_built_directly_without_the_wire_form():
    manifest = NodeJoinManifest(device_id="d1", role="ugv",
                                node_tags=frozenset({"compute.cpu"}),
                                budget=ResourceBudget(compute_units=1.0, memory_mb=512.0))

    assert manifest.contract_version == JOIN_CONTRACT_VERSION
