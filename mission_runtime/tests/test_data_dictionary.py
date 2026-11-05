"""implements: AI-C-01, AI-C-06
covers: common field names, producer payload checks, and data-plane mapping
"""

from pathlib import Path

import pytest

from mission_runtime.common.data_plane import DataPlane
from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.data_dictionary import UnknownFieldError


def test_core_payload_names_are_registered_in_the_dictionary():
    payload = {
        dd.DEVICE_ID: "device-1",
        dd.OBSERVED_AT: 1720000000.0,
        dd.OBSERVATION_NAME: "water_level",
        dd.OBSERVATION_VALUE: 2.4,
        dd.COORDINATE_FRAME: "GLOBAL",
    }

    assert dd.assert_known(payload) is payload
    assert dd.unknown_fields(payload) == ()


def test_ad_hoc_field_names_are_reported_during_development():
    payload = {
        dd.DEVICE_ID: "device-1",
        "deviceId": "device-1",
    }

    assert dd.unknown_fields(payload) == ("deviceId",)
    with pytest.raises(UnknownFieldError):
        dd.assert_known(payload)


def test_specs_keep_meaning_producer_consumer_and_plane_together():
    spec = dd.spec_for(dd.COMMAND_ID)

    assert spec.name == "command_id"
    assert "명령" in spec.meaning
    assert "백엔드" in spec.produced_by
    assert "말단" in spec.consumed_by
    assert spec.plane is DataPlane.TASK


def test_node_pose_is_kept_separate_from_its_confidence_and_source():
    # 2026-09 재설계: 위치 자체와 "어떤 방법으로 얻었는지"를 같은 이름에 섞지 않는다 —
    # 고정 카메라가 본 위치와 로봇 자체 추정 위치는 신뢰도가 다르므로 근거로 구분한다.
    pose_spec = dd.spec_for(dd.NODE_POSE)
    source_spec = dd.spec_for(dd.POSE_SOURCE)
    uncertainty_spec = dd.spec_for(dd.POSE_UNCERTAINTY)

    assert pose_spec.plane is DataPlane.TASK
    assert "확정값 아님" in pose_spec.meaning
    assert source_spec.name != pose_spec.name
    assert uncertainty_spec.name != pose_spec.name


def test_camera_extrinsic_is_distinct_from_dynamic_node_pose():
    # 고정 카메라 위치는 매 틱 갱신되는 node_pose가 아니라 보정 프로파일처럼
    # 버전 관리되는 별도 개념이다(AI-E-02).
    extrinsic_spec = dd.spec_for(dd.CAMERA_EXTRINSIC)

    assert "엣지 보정" in extrinsic_spec.produced_by
    assert extrinsic_spec.name != dd.NODE_POSE


def test_unknown_spec_lookup_fails_closed():
    with pytest.raises(UnknownFieldError):
        dd.spec_for("undocumented_name")


def test_plane_queries_keep_business_and_observability_names_separate():
    task_fields = dd.fields_on_plane(DataPlane.TASK)
    observability_fields = dd.fields_on_plane(DataPlane.OBSERVABILITY)

    assert dd.COMMAND_OUTCOME in task_fields
    assert dd.TRACE_ID in observability_fields
    assert dd.OVERLAY_STATE in observability_fields
    assert set(task_fields).isdisjoint(observability_fields)


def test_every_dictionary_entry_has_a_unique_name_and_nonempty_contract():
    names = [entry.name for entry in dd.DATA_DICTIONARY.values()]

    assert len(names) == len(set(names))
    for entry in dd.DATA_DICTIONARY.values():
        assert entry.meaning
        assert entry.value_kind
        assert entry.produced_by
        assert entry.consumed_by


# --- 회귀 방지: 경계를 넘는 payload 는 사전에 등록된 이름만 쓴다 --------------
# 여기 걸리는 것은 "새 이름을 쓰지 말라"는 뜻이 아니라 "쓰기 전에 사전에 등록하라"는
# 뜻이다(AI-C-01). 검사 대상은 실제로 파트·모듈 경계를 넘는 payload 로 한정한다.

def test_wire_envelope_uses_only_dictionary_names():
    """봉투 필드는 파트 경계를 넘는다. 본문(payload) 내부 이름은 contracts/ai 스키마 소관."""
    from mission_runtime.integration.wire import MessageContext, build_message

    message = build_message(
        MessageContext(source_id="cam-1", node_id="edge-1", entity_id="e-1",
                       zone_id="zone-a", sequence_id=3),
        "detections", {"detections": []}, coordinate_frame="IMAGE",
    )

    assert dd.unknown_fields(message) == ()


def test_resource_sample_payload_uses_only_dictionary_names():
    from mission_runtime.collection.sampler import ResourceSample

    sample = ResourceSample(sampled_at=1.0, rss_mib=12.0, cpu_percent=3.0,
                            energy_uj=5, temperature_c=41.0)

    assert dd.unknown_fields(sample.as_payload()) == ()


def _session_entries():
    from mission_runtime.collection.session import CollectionSession
    from mission_runtime.observability.experiment import ExperimentRecorder, RunHeader

    class _Worker:
        worker_id = "w-1"
        source_group = "det_a"

        def is_available(self):
            return True

        def run(self, frame):
            return [{"kind": "region", "confidence": 0.8, "region": (0, 0, 1, 1),
                     "object_id": "obj-1"}]

    class _BadWorker(_Worker):
        worker_id = "w-2"

        def run(self, frame):
            raise RuntimeError("boom")

    class _Media:
        _frames = [object()]

        def is_available(self):
            return True

        def source_id(self):
            return "cam-1"

        def read_frame(self):
            return self._frames.pop() if self._frames else None

    session = CollectionSession(recorder=ExperimentRecorder(RunHeader("run-1", "d-1")),
                                workers=[_Worker(), _BadWorker()])
    session.set_available_groups({"det_a"}, reason="startup")
    session.run(_Media())
    return session.recorder.entries


def test_collection_session_capture_payloads_use_only_dictionary_names():
    """수집 세션이 run bundle 로 내보내는 이름 — 시나리오 러너가 이걸 읽는다."""
    checked = {"capability", "worker", "fault"}
    entries = [e for e in _session_entries() if e.channel in checked]

    assert entries, "세션이 아무것도 기록하지 않았다면 검사가 무의미하다"
    for entry in entries:
        assert dd.unknown_fields(entry.payload) == (), (entry.channel, entry.payload)


# -- STATE_CHANGE_REASON is a controlled vocabulary (2026-09-17, P2) ---------


def test_every_selector_reason_constant_is_in_the_dictionary_vocabulary():
    """The selector defines the strings; the dictionary owns the vocabulary.
    A new REASON_* constant that is not registered here fails this test —
    that is how the vocabulary stays closed instead of drifting back to
    free text."""
    from mission_runtime.selection import selector

    constants = {v for k, v in vars(selector).items() if k.startswith("REASON_") and isinstance(v, str)}
    assert constants  # guard against the prefix being renamed silently
    assert constants <= set(dd.STATE_CHANGE_REASONS)


def test_resolver_and_egress_gate_reasons_are_in_the_vocabulary():
    from mission_runtime.contracts.capability import CapabilityRequirement
    from mission_runtime.contracts.profile import DeploymentProfile, ResourceBudget
    from mission_runtime.registry.capability_registry import CapabilityRegistry
    from mission_runtime.runtime.application import CapabilitySpec, ZoneApplication

    app = ZoneApplication(
        DeploymentProfile(domain_id="t", active_capability_kinds=("a", "b")),
        CapabilityRegistry(),
        [
            CapabilitySpec("a", is_core=True, requirement=CapabilityRequirement(required=("x",))),
            CapabilitySpec("b"),
        ],
    )
    reasons = {r.reason for r in app.resolve(ResourceBudget(1, 1)).values()}

    assert reasons == {"missing_required:x", "core_capability_unplaced"}
    assert {dd.state_change_reason_token(r) for r in reasons} <= set(dd.STATE_CHANGE_REASONS)


def test_residency_reason_constants_are_in_the_dictionary_vocabulary():
    """배치 축(`runtime/residency.py`)도 선택기와 같은 규약을 따른다: 모듈이
    문자열을 정하고 사전이 어휘를 소유한다. 이 어휘를 STATE_CHANGE_REASONS와
    합치지 않는 이유는 질문이 다르기 때문이다 — "지금 돌 수 있는가"와
    "이 장치 안에 있어야 하는가"가 같은 칸에 들어가면 '예산이 모자라서
    엣지로 갔다'와 '링크가 나빠서 말단으로 왔다'를 구분할 수 없다."""
    from mission_runtime.contracts.profile import OUTAGE_BEHAVIORS
    from mission_runtime.ondevice.link_handover import LinkPosture
    from mission_runtime.runtime import residency

    assert set(residency.LINK_POSTURE_REASONS) <= set(dd.LINK_POSTURE_REASONS)
    assert set(residency.RESIDENCY_REASONS) <= set(dd.RESIDENCY_DECISION_REASONS)
    assert set(residency.RESIDENCY_VIOLATIONS) <= set(dd.RESIDENCY_VIOLATIONS)
    assert set(OUTAGE_BEHAVIORS) == set(dd.OUTAGE_BEHAVIOR_VALUES)
    # 배치 시점과 운행 중 전환이 같은 자세 어휘를 쓴다(AI-N-03).
    assert set(dd.LINK_POSTURES) == {p.value for p in LinkPosture}
    assert set(dd.CAPABILITY_RESIDENCIES) == {r.value for r in residency.Residency}


def test_residency_field_specs_list_their_vocabulary_not_str():
    for name in (dd.CAPABILITY_RESIDENCY, dd.RESIDENCY_DECISION_REASON, dd.LINK_POSTURE,
                 dd.LINK_POSTURE_REASON, dd.OUTAGE_BEHAVIOR):
        assert dd.spec_for(name).value_kind != "str"


def test_reason_token_strips_only_the_data_suffix():
    assert dd.state_change_reason_token("missing_required:media.video_input,perception.detect") == "missing_required"
    assert dd.state_change_reason_token("required_hw_tag_missing:compute.gpu") == "required_hw_tag_missing"
    assert dd.state_change_reason_token("selected") == "selected"


def test_state_change_reason_spec_lists_the_vocabulary_not_str():
    spec = dd.spec_for(dd.STATE_CHANGE_REASON)
    assert spec.value_kind != "str"
    assert set(spec.value_kind.split("|")) == set(dd.STATE_CHANGE_REASONS)


def test_device_probe_reason_constants_are_in_their_own_vocabulary():
    """연결 검증 하네스(`tools/hw_smoke/smoke.py`)도 같은 규약을 따른다: 모듈이
    문자열을 정하고 사전이 어휘를 소유한다. STATE_CHANGE_REASONS와 별개인 이유는
    질문이 다르기 때문이다 — "이 capability가 돌 수 있는가"와 "이 장치에 닿는가"가
    같은 칸에 들어가면 'provider 미등록'과 'SSH 거부'를 구분할 수 없다."""
    import sys
    from pathlib import Path

    framework_dir = str(Path(__file__).resolve().parents[1])
    if framework_dir not in sys.path:
        sys.path.insert(0, framework_dir)
    from tools.hw_smoke import smoke

    constants = {v for k, v in vars(smoke).items()
                 if k.startswith("PROBE_") and not k.startswith("PROBE_KIND") and isinstance(v, str)}
    assert constants
    assert constants <= set(dd.DEVICE_PROBE_REASONS)
    assert set(dd.DEVICE_PROBE_REASONS).isdisjoint(dd.STATE_CHANGE_REASONS)
    spec = dd.spec_for(dd.DEVICE_PROBE_REASON)
    assert set(spec.value_kind.split("|")) == set(dd.DEVICE_PROBE_REASONS)
    assert spec.plane is DataPlane.OBSERVABILITY
    for name in (dd.DEVICE_PROBE_LEVEL, dd.PROBED_AT):
        assert dd.spec_for(name).plane is DataPlane.OBSERVABILITY
        assert "연결 검증" in dd.spec_for(name).produced_by


def test_execution_plan_names_are_registered():
    """PLAN_ID / REQUESTER_ROLE (runtime/execution_plan.py, 2026-09-28) are dictionary names,
    and the plan's own as_dict() uses them."""
    from mission_runtime.runtime.execution_plan import build_plan

    assert dd.spec_for(dd.PLAN_ID).plane is DataPlane.OBSERVABILITY
    assert dd.spec_for(dd.REQUESTER_ROLE).plane is DataPlane.TASK
    d = build_plan("f", {}).as_dict()
    assert dd.PLAN_ID in d and dd.CORRELATION_ID in d


def test_a_vocabulary_reference_actually_resolves():
    """사전이 값을 베끼지 않고 **어휘가 사는 자리를 가리킨다.** 그 포인터가
    썩으면 사전은 찾아갈 수 없는 곳을 가리키고, 그러면 베낀 것보다 나쁘다.

    가리키는 이유는 둘이다 — 값을 베끼면 한쪽만 바뀌는 날이 오고, import 하면
    이름 등록부가 기능 모듈(그리고 그 모듈의 opencv·numpy)에 의존해 계층이
    거꾸로 선다. 이 시험이 그 셋째 길의 유일한 약점을 막는다.

    implements: AI-C-01
    """
    import importlib
    import re

    pattern = re.compile(r"어휘 정본: ([\w/]+)\.py::([A-Z_]+)")
    referenced = [(name, m.group(1), m.group(2))
                  for name, spec in dd.DATA_DICTIONARY.items()
                  for m in [pattern.search(spec.value_kind)] if m]

    assert referenced, "가리키는 항목이 하나는 있어야 이 시험이 뜻을 가진다"

    for field_name, module_path, constant in referenced:
        module = importlib.import_module(
            "mission_runtime." + module_path.replace("/", "."))
        vocabulary = getattr(module, constant, None)
        assert vocabulary is not None, (
            f"{field_name} 가 가리키는 {module_path}.py::{constant} 가 없다")
        assert isinstance(vocabulary, tuple) and vocabulary, (
            f"{module_path}.py::{constant} 은 비어 있지 않은 어휘 묶음이어야 한다")


def test_the_dictionary_does_not_drag_opencv_into_every_importer():
    """이름 등록부는 거의 모든 모듈이 import 한다. 그 자리에 무거운 의존이 붙으면
    이름 하나 읽으려고 opencv 가 올라온다."""
    import subprocess
    import sys

    probe = ("import sys; import mission_runtime.contracts.data_dictionary; "
             "print('cv2' in sys.modules, 'numpy' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         text=True, cwd=str(Path(__file__).resolve().parents[2]))

    assert out.stdout.strip() == "False False", out.stdout + out.stderr


# --- 2026-11-04 등재분: 임계값 선언 · 학습 버전 계보 · 탐지기 선언/관측 -------
# 이 묶음이 지키는 것은 "세 상태를 둘로 접지 않는다" 와 "선언과 관측을 가른다" 다.
# 사전은 이름만 등록하므로, 그 이름이 **실제로 그 자리에서 나가는지**는 아래 시험이
# 본다 — 등록만 되고 아무도 쓰지 않는 이름은 사전을 믿을 수 없게 만든다.


def test_learning_state_vocabulary_matches_the_lineage_enum():
    """`learning_state` 의 정본은 `continual/lineage.py::LearningState` 다. Enum 은
    어휘 묶음이 아니라 value_kind 로 가리킬 수 없어 **베껴 적었고**, 베낀 값은
    갈라질 수 있으므로 이 시험이 그 유일한 약점을 막는다(LINK_POSTURES 와 같은 규약).

    implements: AI-C-01, AI-L-08
    """
    from mission_runtime.continual.lineage import LearningState

    assert set(dd.LEARNING_STATES) == {state.value for state in LearningState}
    spec = dd.spec_for(dd.LEARNING_STATE)
    assert set(spec.value_kind.split("|")) == set(dd.LEARNING_STATES)
    # 검증 통과와 사람의 승인과 실제 적용은 **같은 축의 다른 값**이어야 한다 —
    # 셋 중 둘이 빠지면 AI-L-06 의 관문이 상태 어휘에서 사라진다.
    assert {"validated", "approved", "deployed"} <= set(dd.LEARNING_STATES)


def test_the_score_floor_is_three_columns_and_the_state_is_three_valued():
    """하한은 값 하나가 아니라 값·근거·상태 셋이다. 근거를 값에 합치면 "선언된
    0.25" 와 "근거 없이 기본값이 된 0.25" 가 같은 수가 되고, 상태를 참·거짓으로
    접으면 **선언한 적 없는 하한을 통과/미달로 판정**하게 된다(AI-S-04).
    """
    value, basis, state = (dd.spec_for(dd.SCORE_FLOOR),
                           dd.spec_for(dd.SCORE_FLOOR_BASIS),
                           dd.spec_for(dd.SCORE_FLOOR_STATE))

    assert len({value.name, basis.name, state.name}) == 3
    # 값 칸은 **없음을 표현할 수 있어야** 한다 — 0 으로 접으면 모든 점수가 통과한다.
    assert "null" in value.value_kind
    for spec in (basis, state):
        assert spec.value_kind != "str"   # 어휘가 사는 자리를 가리킨다


def test_the_floor_vocabularies_keep_the_no_basis_token():
    """세 번째 상태가 어휘에서 사라지면 그 뒤의 모든 판정이 둘로 접힌다."""
    from mission_runtime.perception import obstacle_taxonomy as tax

    assert tax.FLOOR_BASIS_NONE in tax.FLOOR_BASES
    assert tax.FLOOR_NO_BASIS in tax.FLOOR_STATES
    assert len(tax.FLOOR_STATES) == 3


def test_threshold_resolution_sends_the_declared_and_operator_values_apart():
    """해소 결과의 이름이 사전에 있고, **선언값과 운영자 수정값이 다른 칸**이다 —
    합치면 "원래 이 값이었다" 를 더는 말할 수 없다(AI-L-03).
    """
    from mission_runtime.perception.detection_thresholds import (
        BASIS_NO_DECLARATION,
        DetectionThresholds,
    )

    resolved = DetectionThresholds.empty().resolve("score_floor").as_dict()

    # 선언이 없는 배치는 정상이고, 그때 값은 0 이 아니라 없음이다(세 번째 상태).
    assert resolved["value"] is None
    assert resolved["basis"] == BASIS_NO_DECLARATION
    for name in (dd.PARAMETER, dd.BASIS, dd.DECLARED_VALUE, dd.OPERATOR_VALUE,
                 dd.THRESHOLD_ID, dd.PROVENANCE):
        assert name in resolved, name
        assert name in dd.DATA_DICTIONARY, name
    assert dd.DECLARED_VALUE != dd.OPERATOR_VALUE


def test_basis_records_that_one_name_still_carries_two_axes():
    """`basis` 는 선언의 기준 묶음(AI-C-18)과 임계값의 근거 토큰 두 뜻으로 나간다.
    사전은 이름으로 색인하므로 갈라 적을 자리가 없고, **그 사실을 적어 두는 것이
    지금 할 수 있는 전부다** — 적어 두지 않으면 다음 사람이 한쪽만 보고 쓴다.
    혼동이 해로운 자리에는 좁은 이름이 따로 있어야 한다(AI-C-01).
    """
    spec = dd.spec_for(dd.BASIS)

    assert "개명" in spec.meaning        # 남은 일이 기록되어 있다
    assert "THRESHOLD_BASES" in spec.value_kind
    for narrow in (dd.SCORE_FLOOR_BASIS, dd.PARAM_BASIS, dd.ACCURACY_BASIS,
                   dd.NEAR_THRESHOLD_BASIS, dd.EVIDENCE_BASIS):
        assert narrow in dd.DATA_DICTIONARY and narrow != dd.BASIS


def test_version_reference_and_candidate_version_are_separate_columns():
    """배포하는 버전의 신원과 그 버전을 만든 학습 후보의 해시는 **이름 공간이
    다르다**. 한 칸에 담으면 손으로 적은 `model_id@version` 과 sha256 이 같은
    자리에서 비교되고 그 비교는 영원히 어긋난다 — 콘솔 적용 경로에서 실제로 그랬다.
    """
    reference, candidate = (dd.spec_for(dd.VERSION_REFERENCE),
                            dd.spec_for(dd.CANDIDATE_VERSION))

    assert reference.name != candidate.name
    assert "sha256" in candidate.meaning
    # 미검증 범위는 승인 정보의 일부다(AI-L-06). 빈 값이 "조건 무관" 으로 읽히는
    # 것을 막는 칸이므로 버전 신원과 같은 평면에 있어야 한다.
    assert dd.spec_for(dd.UNVERIFIED_SCOPE).plane is reference.plane


def test_detector_declaration_and_this_node_observation_sit_on_different_planes():
    """선언은 어디서 돌려도 참이고 관측은 기계마다 다르다. 둘을 한 평면에 두면
    선언 파일에 `present: true` 를 적어 두는 길이 열리고, 그 줄은 다른 기계에서
    거짓말이 된다(AI-C-18 · AI-C-16).
    """
    from mission_runtime.edge.detector_catalog import DetectorCatalog

    row = DetectorCatalog.from_file().all()[0].as_row("/nonexistent-asset-root")

    for name in (dd.WEIGHTS_PRESENT, dd.OUTBOUND_NETWORK_REQUIRED, dd.BUILDABLE_HERE):
        assert name in row, name
        assert dd.spec_for(name).plane is DataPlane.OBSERVABILITY, name
    for name in (dd.DETECTOR_ID, dd.ACCEPTED_PARAMS):
        assert name in row, name
        assert dd.spec_for(name).plane is DataPlane.TASK, name
    # 3값을 표현할 수 있어야 한다 — None 은 "물어볼 로컬 경로가 없다" 이고 거짓이 아니다.
    assert "null" in dd.spec_for(dd.WEIGHTS_PRESENT).value_kind


def test_an_output_the_contract_cannot_carry_is_not_the_same_as_an_absent_output():
    """`outputs_not_surfaced` 와 "모델에 없는 출력" 을 한 칸에 담으면 "계약만 넓히면
    된다" 는 사실이 사라진다. 사전이 그 둘을 다른 이름으로 들고 있어야 한다.
    """
    from mission_runtime.edge.detector_catalog import DetectorCatalog

    seg = next(d for d in DetectorCatalog.from_file().all()
               if d.outputs.not_surfaced)

    assert set(seg.outputs.not_surfaced).isdisjoint(seg.outputs.missing)
    assert dd.OUTPUTS_NOT_SURFACED in dd.DATA_DICTIONARY
    assert "계약" in dd.spec_for(dd.OUTPUTS_NOT_SURFACED).meaning
