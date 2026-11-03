"""공통 데이터 사전 — 의미가 같은 항목의 변수명을 한 곳에서 통일한다.

implements: AI-C-01

AI-C-01 / 원칙 #8: "요구사항 단계에서는 구체 변수명을 확정하지 않고 필요한 정보의
의미만 정의하며, 하드웨어·백엔드·AI·가시화 요구사항이 확정된 뒤 데이터 사전에서 동일
의미 항목의 변수명을 통일해야 한다."

이제 그 조건이 충족됐다(§6-8: 전체 기능 구현 후). 이 모듈은 각 항목에 대해
**의미 · 값 종류 · 생산자 · 소비자 · 소속 평면**을 함께 기록하고, 코드가 쓰는 이름은
이 파일의 상수를 통해서만 결정되게 한다. 이름을 바꿔야 하면 여기 한 곳만 고친다.

여기서 정하는 것은 *이름*이지 전송 형식이 아니다. 같은 의미 항목이 MQTT·Kafka·OTLP·
미디어 경로 중 어디로 가더라도 이름은 동일하다(AI-C-01, AI-C-14).
"""

from __future__ import annotations

from dataclasses import dataclass

from mission_runtime.common.data_plane import DataPlane


@dataclass(frozen=True)
class FieldSpec:
    """One entry of the dictionary."""

    name: str
    meaning: str
    value_kind: str
    produced_by: tuple[str, ...]
    consumed_by: tuple[str, ...]
    plane: DataPlane


# --- 식별 -------------------------------------------------------------------
DEVICE_ID = "device_id"
ENTITY_ID = "entity_id"
NODE_ID = "node_id"
ZONE_ID = "zone_id"
SOURCE_ID = "source_id"
MESSAGE_ID = "message_id"
CHANNEL = "channel"
PAYLOAD = "payload"
CAPABILITY_KIND = "capability_kind"
PROVIDER_ID = "provider_id"
CLUSTER_ID = "cluster_id"
PEER_ID = "peer_id"


# --- 이종 근거 기반 객체 레코드 (AI-S-06) ------------------------------------
SOURCE_GROUP = "source_group"
SUPPORTING_SOURCE_COUNT = "supporting_source_count"
RECORD_REVISION = "record_revision"
LIFECYCLE_STATE = "lifecycle_state"
GEOMETRY_KIND = "geometry_kind"
EXPOSED_AT = "exposed_at"

# --- 임무 요구 증거 계약 (AI-S-07, 2026-09-22 증거 주도 오케스트레이션) ---------
#: 업무 목적이 요구하는 증거의 **종류**. provider가 무엇을 만드는지(AI-C-18)와 같은
#: 축이어야 대조가 성립한다 — 이름이 갈리면 격차 계산 자체가 불가능하다.
REQUIRED_EVIDENCE_KIND = "required_evidence_kind"
#: 그 증거가 "충족"으로 인정되는 경계. 없으면 충족 여부를 판정할 수 없다.
REQUIRED_EVIDENCE_TOLERANCE = "required_evidence_tolerance"
#: 요구 해상도. 같은 객체라도 목적에 따라 필요한 세밀도가 다르다(AI-S-07).
REQUIRED_EVIDENCE_GRANULARITY = "required_evidence_granularity"
#: 필수인가 선택인가. AI-S-07이 "반드시 필요한 정보와 있으면 품질을 높이는 선택
#: 정보"를 나누라고 한 축이며, AI-C-05의 축소 판정이 이 값을 본다.
REQUIRED_EVIDENCE_NECESSITY = "required_evidence_necessity"
#: 계약 개정 번호. 임무가 운용 중 바뀌면 올라간다.
CONTRACT_REVISION = "contract_revision"
#: 계약 대비 현재 레코드의 충족 상태.
SUFFICIENCY_STATE = "sufficiency_state"

#: REQUIRED_EVIDENCE_NECESSITY의 값 어휘.
REQUIRED_EVIDENCE_NECESSITIES: tuple[str, ...] = ("required", "preferred")

#: SUFFICIENCY_STATE의 값 어휘. **`met`은 신뢰도가 높다는 뜻이 아니라 계약이 요구한
#: 근거가 확보됐다는 뜻이다**(AI-S-03: 신뢰도와 근거 충분도는 다른 축).
SUFFICIENCY_STATES: tuple[str, ...] = (
    "met",           # 계약이 요구한 근거가 tolerance 안에서 확보됨
    "unmet",         # 아직 확보되지 않음
    "contested",     # 확보됐으나 근거끼리 어긋남 — 추가 검증 대상
    "unobtainable",  # 현재 등록된 provider로는 만들 수 없음(축소 경로, AI-C-05)
)


# --- 환경 구조 추정 (AI-S-08) ------------------------------------------------
MAP_ELEMENT_ID = "map_element_id"
STRUCTURE_UNCERTAINTY = "structure_uncertainty"
ANCHOR_ID = "anchor_id"

# --- 링크 품질 (AI-N-03) -----------------------------------------------------
LINK_QUALITY = "link_quality"
LINK_POSTURE = "link_posture"

# --- 이동체·센서 종류 (2026-09-17, LOTUSim-Energy 반영) -----------------------
# 이 두 이름은 값을 고정하는 enum이 아니라 **태그 어휘의 의미**를 등록하는 것이다
# (절대 준수 원칙 #1: 센서 제품·이동체 벤더를 핵심 코드에 하드코딩하지 않는다).
# 실제 값은 `CompatibilityProfile.required_hw_tags`/`preferred_hw_tags`에
# `platform.uav` / `sensor.sonar` 같은 자유 문자열로 들어가고, 노드가 실제로
# 무엇을 갖고 있는지는 `providers/compute.py::discover_node_tags()` 계열이
# 실측해 보고한다 -- 그래서 새 이동체·새 센서를 붙이는 것은 등록의 문제이지
# 이 파일을 고치는 문제가 아니다.
#
# 왜 이름만이라도 등록하는가: LOTUSim-Energy(docs/obsidian/papers/lotusim-energy.md)
# 의 태스크 표는 "작업 -> 이동체 종류 -> 자율 수준 -> 주 센서"를 한 줄로 묶는데,
# 우리 쪽에는 "작업에 필요한 정보"(AI-S-07 PurposeRequirement)는 있어도 "어떤
# 이동체가, 어떤 센서로"를 적을 공통 어휘가 없었다. 어휘를 정해두지 않으면
# 같은 뜻을 `uav`/`drone`/`platform.uav`처럼 제각각 쓰게 된다(AI-C-01 위반).
PLATFORM_KIND = "platform_kind"
SENSOR_KIND = "sensor_kind"

# --- 자율 수준 (2026-09-17, LOTUSim-Energy 반영) -------------------------------
# 같은 조치라도 "사람이 직접 조종", "사람 승인 후 자동 수행", "자동 수행"은
# 책임 소재가 다르다. AI는 이 등급을 **판단해서 표시**할 뿐이고, 실제 승인 절차와
# 물리 명령 발급은 백엔드·하드웨어 몫이다(AI-C-19) -- 그래서 이 값은 권고
# (RECOMMENDATION)에 동반되는 정보이지 명령 필드가 아니다.
AUTONOMY_LEVEL = "autonomy_level"

# --- 노드 위치·자세 (2026-09 온디바이스/엣지 재설계, AI-S-06/S-08 연계) ----------
# 이동형 에이전트의 위치는 확정값이 아니라 "어떤 방법으로 얼마나 최근에" 얻었는지가
# 함께 붙어야 하는 근거다(AI-S-03과 같은 이유로 confidence/근거출처/불확실도를
# 분리한다) — 그래서 세 필드로 나눈다: 위치 자체(NODE_POSE), 그 위치를 만든 방법
# (POSE_SOURCE: 예를 들어 "고정 카메라가 봤다" vs "로봇이 자체 추정했다"는 신뢰도가
# 전혀 다르다), 그리고 누적 불확실도(POSE_UNCERTAINTY). 고정 카메라 자신의 위치는
# 이동하지 않으므로 별도 이름(CAMERA_EXTRINSIC)으로 두고 보정 프로파일(AI-E-02)의
# 일부로 버전 관리한다 — 매 틱 갱신되는 NODE_POSE와 성격이 다르다.
NODE_POSE = "node_pose"
POSE_SOURCE = "pose_source"
POSE_UNCERTAINTY = "pose_uncertainty"
CAMERA_EXTRINSIC = "camera_extrinsic"

# --- 시간·순서·원본 참조 -----------------------------------------------------
FRAME_ID = "frame_id"
OBSERVED_AT = "observed_at"
LOCAL_SEQUENCE = "local_sequence"
TIME_SYNC_STATE = "time_sync_state"
TIMESTAMP = "timestamp"
SEQUENCE_ID = "sequence_id"

# --- 버전 -------------------------------------------------------------------
SCHEMA_VERSION = "schema_version"
MODEL_VERSION = "model_version"
CONFIG_VERSION = "config_version"
CALIBRATION_PROFILE_VERSION = "calibration_profile_version"

# --- 관측 결과 --------------------------------------------------------------
OBSERVATION_NAME = "observation_name"
OBSERVATION_VALUE = "observation_value"
COORDINATE_FRAME = "coordinate_frame"

# --- 실행 계획 (2026-09-28, runtime/execution_plan.py) -------------------------
# 요청 1건의 해석 결과와 배치 액션을 하나로 묶는 식별자. 어떤 요청의 산출물인지는
# CORRELATION_ID 로 잇고, 누가 요청했는지는 REQUESTER_ROLE 자리에 둔다 — 값 어휘와
# 권한 판정은 사용자(소유자)의 인증·권한 설계 몫이라 여기서 정하지 않는다.
PLAN_ID = "plan_id"
REQUESTER_ROLE = "requester_role"

# --- 기능 상태 --------------------------------------------------------------
CAPABILITY_STATE_BEFORE = "capability_state_before"
CAPABILITY_STATE_AFTER = "capability_state_after"
STATE_CHANGE_REASON = "state_change_reason"

#: Controlled vocabulary for STATE_CHANGE_REASON (2026-09-17). Every reason a
#: selector/resolver attaches to a capability or a candidate is one of these
#: tokens; a token marked "<...>" carries data after a ':' separator
#: (`missing_required:media.video_input,perception.detect`). Producers:
#: `selection/selector.py` (REASON_* constants), `runtime/application.py`,
#: `runtime/airgap.py::EgressGate.rejection_reason`. The list lives here, not
#: in the selector, because the dictionary is the layer consumers import —
#: `tests/test_data_dictionary.py` proves the producers stay inside it.
#: A display grade (READY/BLOCKED/MISSING/STALE …) is *derived* from
#: (CapabilityState, token) by the consumer; it is not a state of its own
#: (capability·상태 UI 연동 설계 노트(비공개) §3-2).
STATE_CHANGE_REASONS: tuple[str, ...] = (
    "selected",                                  # winner / capability placed
    "selected_degraded",                         # placed with optional deps missing
    "compatible",                                # candidate passed every filter, ranked below winner
    "no_provider_registered",                    # kind has no healthy provider at all
    "no_compatible_provider_within_budget",      # providers exist, none fit tags/budget
    "required_hw_tag_missing",                   # + ":<tags>"  (per candidate)
    "required_runtime_tag_missing",              # + ":<tags>"  (per candidate)
    "over_budget",                               # per candidate
    "missing_required",                          # + ":<kinds>" (capability's own required deps)
    "core_capability_unplaced",                  # optional kind withheld to keep headroom for core
    "deadline_exceeded",                         # TaskIntent deadline passed before selection
    "input_too_stale",                           # TaskIntent max_input_age violated
    "execution_profile_conditions_mismatch",     # measured evidence from other conditions not reused
    "runtime_instance_unhealthy_or_expired",     # instance TTL/health failed
    "no_capability_kinds_given",                 # select_with_degrade called with []
    "external_connection_required_in_closed_network",    # AI-C-16 egress gate, blocking
    "external_connection_unavailable_in_closed_network", # AI-C-16 egress gate, optional feature off
)

# --- 장치 연결 검증 (tools/hw_smoke, 2026-09-28) -------------------------------
# STATE_CHANGE_REASONS가 "이 capability가 지금 돌 수 있는가"(선택기·resolver의
# 판정)의 어휘라면, 아래는 "등록된 장치에 실제로 닿는가, 어디까지 되는가"(연결
# 검증 하네스의 L1 도달 / L2 신원·계층 / L3 기능)의 어휘다. 질문이 다르므로
# 합치지 않는다 — 합치면 'provider가 등록돼 있지 않다'와 'SSH가 거부됐다'가 같은
# 칸에 들어가고, 장치 도달 실패가 capability 판정 사유로 오독된다. 이 토큰은
# 장치의 최종 가용성 판정이 아니다(원칙 #15): 하네스는 관측만 남기고 판정은
# 백엔드가 한다. 생산자는 `tools/hw_smoke/smoke.py`이며
# `tests/test_data_dictionary.py`가 그 모듈의 상수가 여기를 벗어나지 않는지 본다.
DEVICE_PROBE_LEVEL = "device_probe_level"
DEVICE_PROBE_REASON = "device_probe_reason"
PROBED_AT = "probed_at"

#: Controlled vocabulary for DEVICE_PROBE_REASON. `reachable` is the only
#: success token (any level); the rest name *which* step of the probe stopped
#: and are never inferred from a missing measurement (AI-N-03: 측정값이 항상
#: 존재한다고 가정하지 않는다 — `not_implemented`는 "아직 재는 provider가 없다"
#: 이지 실패가 아니며, 성공으로 위장하지도 않는다).
DEVICE_PROBE_REASONS: tuple[str, ...] = (
    "reachable",           # this level passed
    "dns_unresolved",      # L1: the registered address does not resolve
    "host_unreachable",    # L1: resolved, ICMP sent, nothing came back
    "ssh_refused",         # L2: transport-level ssh failure (refused / timeout / no route)
    "auth_failed",         # L2: ssh reached the host, credential rejected
    "command_failed",      # L2/L3: logged in, the probe script itself failed
    "tag_mismatch",        # L2: registered observable tags not observed on the device
    "no_camera",           # L3: capture attempted, the device reports no camera
    "no_frame",            # L3: capture ran, no usable frame came back
    "no_heartbeat",        # L3: robot/UAV link up, no heartbeat within the window
    "not_implemented",     # L3: no probe exists yet for this device's tags
)


# --- 온디바이스/엣지 기능 배치 (AI-N-03, AI-C-15, AI-B-10) --------------------
# STATE_CHANGE_REASON이 "이 기능이 지금 돌 수 있는가"의 사유라면, 아래 두 항목은
# "이 기능이 이 장치 **안에** 있어야 하는가"의 사유다. 서로 다른 질문이라 어휘를
# 합치지 않는다 — 합치면 "예산이 모자라서 엣지로 갔다"와 "링크가 나빠서 장치로
# 왔다"가 같은 칸에 들어가 버린다. 생산자는 `runtime/residency.py`이고
# `tests/test_data_dictionary.py`가 그 모듈의 상수가 여기를 벗어나지 않는지 본다.
DEVICE_PURPOSE_ID = "device_purpose_id"
CAPABILITY_RESIDENCY = "capability_residency"
RESIDENCY_DECISION_REASON = "residency_decision_reason"
# LINK_POSTURE / LINK_QUALITY는 위 "링크 품질 (AI-N-03)" 절에 이미 등록돼 있다 —
# 배치 시점 판정이 운행 중 전환과 **같은 항목**을 쓴다는 것이 요점이라 여기서
# 새 이름을 만들지 않는다.
LINK_POSTURE_REASON = "link_posture_reason"
LINK_STABILITY = "link_stability"
OUTAGE_BEHAVIOR = "outage_behavior"
EDGE_SERVICE = "edge_service"

#: CAPABILITY_RESIDENCY의 값 어휘.
CAPABILITY_RESIDENCIES: tuple[str, ...] = ("ondevice", "edge")

#: LINK_POSTURE의 값 어휘 — `ondevice/link_handover.py::LinkPosture`와 같은 값이다.
#: 배치 시점 판정과 운행 중 전환이 같은 말을 써야 둘이 어긋났을 때 눈에 띈다.
LINK_POSTURES: tuple[str, ...] = ("remote_ok", "reducing", "local_only")

#: LINK_POSTURE_REASON의 통제 어휘. ':' 뒤에는 데이터(품질값·표본수)가 붙는다.
LINK_POSTURE_REASONS: tuple[str, ...] = (
    "link_posture_declared",                # + ":<posture>" 배포자가 못박은 자세
    "link_quality_unknown",                 # 측정도 선언도 없음 → 보수적으로 로컬
    "link_samples_insufficient",            # + ":<n>/<min>" 순간값 한 번은 근거가 아니다
    "link_quality_at_or_below_floor",       # + ":<q>"
    "link_quality_below_restore_margin",    # + ":<q>"
    "link_stability_below_threshold",       # + ":<s>" 평균은 좋은데 자주 끊김
    "link_quality_stable",                  # + ":<q>"
)

#: RESIDENCY_DECISION_REASON의 통제 어휘.
RESIDENCY_DECISION_REASONS: tuple[str, ...] = (
    "resident_by_purpose",                  # 목적이 상주로 선언
    "edge_served_by_purpose",               # 목적이 엣지로 선언
    "link_posture_requires_local",          # + ":<posture>" 링크를 못 믿어 끌어옴
    "link_posture_permits_remote",          # + ":<posture>" 링크가 좋아 엣지에 맡김
    "link_quality_below_kind_minimum",      # + ":<q><min>" 이 kind가 요구하는 품질 미달
    "link_quality_unverifiable_for_kind",   # 요구 수치를 확인할 측정값이 없음
)

#: 목적 프로파일 데이터 자체의 모순. 판정 실패가 아니라 배치 전 검증 대상이다(AI-B-09).
RESIDENCY_VIOLATIONS: tuple[str, ...] = (
    "outage_critical_not_resident",         # + ":<kind>"
    "safety_affecting_kind_not_core",       # + ":<kind>"
    "unknown_outage_behavior",              # + ":<kind>"
    "local_fallback_kind_missing",          # + ":<kind>"
)

#: OUTAGE_BEHAVIOR의 값 어휘 — `contracts/profile.py::OUTAGE_BEHAVIORS`와 같다.
OUTAGE_BEHAVIOR_VALUES: tuple[str, ...] = (
    "resident_unaffected",
    "queued_for_edge",
    "local_fallback",
    "unavailable_until_link_returns",
)

# --- 임무 캐시·구역 핸드오버 (AI-N-02, AI-N-03, AI-B-05, AI-C-19) --------------
# 말단이 링크 없이도 답할 수 있어야 하는 두 축이다. 하나는 "무슨 임무 중인가"
# (`ondevice/mission_cache.py`), 다른 하나는 "지금 어느 구역에 붙어 있고 넘어갈
# 것인가"(`ondevice/zone_handover.py`). 배치 사유(RESIDENCY_DECISION_REASONS)와
# 합치지 않는 이유는 질문이 다르기 때문이다 — "이 기능이 이 장치 안에 있어야
# 하는가"와 "이 항목을 링크 없이 이어서 해도 되는가"는 후속 조치가 다르다.
MISSION_CACHE_REASON = "mission_cache_reason"
ZONE_HANDOVER_REASON = "zone_handover_reason"
MISSION_AUTONOMY = "mission_autonomy"
MISSION_ITEM_STATE = "mission_item_state"

#: MISSION_AUTONOMY의 값 어휘 — **발급자가** 정하며 말단이 추론하지 않는다(AI-C-19).
MISSION_AUTONOMY_VALUES: tuple[str, ...] = (
    "AUTONOMOUS_WHEN_CACHED",     # 이미 승인·전달됐고 링크 없이 이어서 해도 된다
    "REQUIRES_FRESH_COMMAND",     # 새 물리 명령이 와야 움직인다(기본값)
)

#: MISSION_ITEM_STATE의 값 어휘. 진행 상태이며 결과(MissionItemOutcome)와 다른 축이다.
#: INTERRUPTED는 "프로세스가 죽어 실행 주체를 잃었다"이고 FAILED가 아니다(AI-B-05).
MISSION_ITEM_STATES: tuple[str, ...] = (
    "PENDING", "IN_PROGRESS", "DONE", "INTERRUPTED",
)

#: MISSION_CACHE_REASON의 통제 어휘. ':' 뒤에는 데이터(버전·항목 id)가 붙는다.
MISSION_CACHE_REASONS: tuple[str, ...] = (
    "mission_accepted",
    "mission_unchanged",
    "mission_rejected_no_origin_command",
    "mission_rejected_no_baseline_for_delta",
    "mission_rejected_version_not_newer",
    "mission_rejected_mission_id_mismatch",
    "mission_rejected_validation_failed",
    "mission_rejected_malformed",
    "mission_restored",
    "mission_restored_last_known_good",
    "mission_restore_failed",
    "mission_progress_kept",
    "mission_progress_reset_content_changed",
    "mission_progress_dropped_item_removed",
    "mission_item_interrupted_by_restart",
    "mission_blocked_safety_suspended",
    "mission_blocked_deadline_passed",
    "mission_blocked_needs_fresh_command",
)

#: ZONE_HANDOVER_REASON의 통제 어휘. 전환 "요청"과 실제 "진입"이 다른 토큰이다.
ZONE_HANDOVER_REASONS: tuple[str, ...] = (
    "zone_unknown",
    "zone_entry_requested",
    "zone_stable",
    "zone_no_other_candidate",
    "zone_candidate_below_margin",
    "zone_holding_samples",
    "zone_holding_dwell",
    "zone_switch_requested",
    "zone_switch_forced_by_floor",
    "zone_entered",
    "zone_return_penalised",
    "link_quality_unmeasured",
    "link_unmeasured_forced_local",
)

# --- 말단 로봇 어댑터 (AI-C-20, AI-C-19) --------------------------------------
# 말단에서 물리 명령 계약을 그 로봇의 명령으로 옮기는 자리의 사유 어휘
# (`execution/robot_adapter.py`). 임무 캐시 사유(MISSION_CACHE_REASONS)와 합치지
# 않는 이유는 질문이 다르기 때문이다 — "이 명령을 수락하는가"와 "이 항목을 링크
# 없이 이어서 해도 되는가"는 판정 주체도 후속 조치도 다르다.
ROBOT_ADAPTER_REASON = "robot_adapter_reason"

#: ROBOT_ADAPTER_REASON의 통제 어휘. ':' 뒤에는 데이터(action·사유·항목 id)가 붙는다.
#: 거부(robot_rejected_*)는 실행 상태가 아니다 — AI-C-20이 수락 결과와 실행
#: lifecycle을 분리하도록 정한 그대로다.
ROBOT_ADAPTER_REASONS: tuple[str, ...] = (
    "robot_command_accepted",
    "robot_command_redelivered",
    "robot_rejected_action_not_declared",
    "robot_rejected_deadline_passed",
    "robot_rejected_backend_not_ready",
    "robot_rejected_emergency_stop_latched",
    "robot_rejected_backend_validation",
    "robot_cancel_forwarded",
    "robot_cancel_refused_by_backend",
    "robot_emergency_stop_engaged",
    "robot_emergency_stop_backend_unreachable",
    "robot_emergency_stop_cleared",
    "robot_resume_no_mission_cache",
    "robot_resume_blocked_emergency_stop",
    "robot_resume_blocked_pending_command",
    "robot_resume_executed",
    "robot_resume_failed",
    "robot_resume_action_not_declared",
    "robot_zone_entered",
)


def state_change_reason_token(reason: str) -> str:
    """The vocabulary token of a reason string — everything before the first
    ':'. `"missing_required:a,b"` → `"missing_required"`."""
    return reason.split(":", 1)[0]

# --- 제어 -------------------------------------------------------------------
COMMAND_ID = "command_id"
COMMAND = "command"
COMMAND_OUTCOME = "command_outcome"
REJECTION_REASON = "rejection_reason"
CORRELATION_ID = "correlation_id"

# --- 위험 판단 --------------------------------------------------------------
RISK_STATE = "risk_state"
RISK_LEVEL = "risk_level"
EVIDENCE_SUFFICIENCY = "evidence_sufficiency"
EVIDENCE_USED = "evidence_used"
RECOMMENDATION = "recommendation"

# --- 재현 참조 --------------------------------------------------------------
BUSINESS_CORRELATION_ID = "business_correlation_id"
SHORT_TERM_REPLAY_REF = "short_term_replay_ref"
ARCHIVE_REF = "archive_ref"
TRACE_ID = "trace_id"

# --- 가용성·연결 ------------------------------------------------------------
TASK_TRANSPORT_ALIVE = "task_transport_alive"
OBSERVABILITY_ALIVE = "observability_alive"
OVERLAY_STATE = "overlay_state"


# --- 관측 커버리지·사각 (AI-S-03) -------------------------------------------
REGION_ID = "region_id"
OBSERVATION_ID = "observation_id"
OBSERVED_FRACTION = "observed_fraction"
COVERAGE_GAIN = "coverage_gain"
BLIND_SPOT_CAUSE = "blind_spot_cause"

# --- 근거·객체 레코드 참조 (AI-S-06, AI-C-03) --------------------------------
EVIDENCE_ID = "evidence_id"
FRAME_REF = "frame_ref"
AVAILABLE_AT = "available_at"
OBJECT_ID = "object_id"
SEMANTIC_CLASS = "semantic_class"
CONFIDENCE = "confidence"
#: 백엔드 contracts/common/object-reference.schema.json과 이름을 맞춘 필드
#: (2026-09-16 door/pedestal 랜드마크 통합 설계 조사에서 확인). OBJECT_ID는
#: 백엔드가 부여하는 구역-횡단 전역 식별자이고, 이건 AI가 구역 내에서만
#: 부여하는 로컬 추적 식별자다 — 둘을 하나로 합치면 AI 쪽 추적 결과를 원래
#: 값으로 되짚을 수 없어 별도 필드로 유지한다.
ZONE_LOCAL_TRACK_ID = "zone_local_track_id"

# --- 랜드마크 기반 회전각/거리 산출 (2026-09 door/pedestal 통합 설계) ------------
# 8방향 회전 스캔 중 특정 프레임에서 탐지된 물체의, 그 프레임 자체를 기준으로 한
# 회전각(랜드마크의 지도상 절대 위치와는 별개 — ROTATION_DEG는 "몇 번째 스캔
# 각도에서 찍혔나"이고 ABSOLUTE_BEARING_DEG는 그걸 지도 기준 절대 방위각으로
# 환산한 값이다. 이 구분을 지키지 않으면 회전 지시각이 45도 배수로만 나오는
# 구조적 결함이 재발한다 — edge/self_localization.py 참고).
ROTATION_DEG = "rotation_deg"
ABSOLUTE_BEARING_DEG = "absolute_bearing_deg"
#: 현재 방향에서 목표를 향하도록 얼마나 돌아야 하는지(부호: 오른쪽(시계)=+).
TURN_DEG = "turn_deg"
FORWARD_DISTANCE_M = "forward_distance_m"
STANDOFF_CM = "standoff_cm"
#: CLIP 텍스트 특징 문구별 유사도 원본값(어떤 특징이 근거였는지 사람이 읽을 수
#: 있게 남긴다 — 최종 점수 하나로 뭉개면 "왜 이 판정인가"를 재현할 수 없다).
FEATURE_SIMILARITIES = "feature_similarities"
#: 참조영상 유사도의 **가중 평균**(상위 k 장). 생산자 perception/appearance_classifier.py,
#: 소비자 tools/fms_console (근거 표)·학습 후보 선별. 데이터 평면: 업무.
#: `CONFIDENCE` 와 **다른 칸**이다 — 이것은 "무엇과 얼마나 닮았나" 이고, 근거가
#: 충분한가(AI-S-03)는 별도 축이다. 한 칸에 담으면 닮은 사진이 여러 장이라는 사실이
#: "확신이 높다" 로 읽히고, 외형은 애초에 개체를 가리지 못한다.
WEIGHTED_REFERENCE_SIMILARITY = "weighted_reference_similarity"

#: 클래스 판정에 반드시 통과해야 하는 게이트들의 이름→통과여부·실측값 묶음
#: (색상/모양/기준영상 유사도/채도 등). 게이트 자체의 구체 종류는 클래스별
#: 설정 파일이 정하므로 여기서는 자유 형식 dict로만 의미를 고정한다.
MANDATORY_GATES = "mandatory_gates"

# --- 미확인 객체 근거 충분도 (AI-S-03, AI-S-04) -------------------------------
UNKNOWN_LIKELIHOOD = "unknown_likelihood"
UNKNOWNNESS_POLICY_ID = "unknownness_policy_id"

# --- 임무·서브태스크 실행 (AI-B-05, AI-C-05) ---------------------------------
GOAL_ID = "goal_id"
GOAL_KIND = "goal_kind"
SUBTASK_ID = "subtask_id"
ORDER_INDEX = "order_index"
EXECUTOR_ID = "executor_id"
MISSING_REQUIRED_CAPABILITIES = "missing_required_capabilities"
MISSING_OPTIONAL_CAPABILITIES = "missing_optional_capabilities"
ITEM_ID = "item_id"
MISSION_STATUS = "mission_status"
OPTIONAL_QUALITY = "optional_quality"
DETECTION_COUNT = "detection_count"
#: 한 프레임에서 나온 인지 결과의 목록 자체. 개수(DETECTION_COUNT)와 구분한다.
DETECTIONS = "detections"

# --- 실행 자원 표본 (AI-O-01) ------------------------------------------------
WORKER_ID = "worker_id"
LATENCY_MS = "latency_ms"
RSS_MIB = "rss_mib"
CPU_PERCENT = "cpu_percent"
ENERGY_UJ = "energy_uj"
TEMPERATURE_C = "temperature_c"
SAMPLED_AT = "sampled_at"
ITEM_COUNT = "item_count"
ERROR_CODE = "error_code"
ERROR_DETAIL = "error_detail"
AVAILABLE_GROUPS_BEFORE = "available_groups_before"
AVAILABLE_GROUPS_AFTER = "available_groups_after"

# --- 실행 회차 식별 (AI-O-03) ------------------------------------------------
DOMAIN_ID = "domain_id"
STEP_INDEX = "step_index"

# --- 작업 그래프·운영 상태 뷰 (AI-B-12, AI-B-13, AI-O-05, AI-O-06) ----------
# 요구사항 출처는 종합상황정보 Dashboard 기능정의서(2026-09-28)이고 2026-10-27 에
# 위 네 ID 로 요구사항 시트에 등재했다(CLAUDE.md §5). 이름은 **물리 실행 노드(`node_id`)와 작업 그래프
# 노드를 반드시 구분**하기 위해 `task_node_id` 로 둔다 — 같은 이름에 두 뜻을 담으면
# 화면에서 계층이 섞인다(기능정의서 §1.2).
SESSION_ID = "session_id"
EMITTED_AT = "emitted_at"
INFER_MS = "infer_ms"
PRODUCER = "producer"
CAMERA_ID = "camera_id"
MODEL = "model"
BBOX = "bbox"
TASK_NODE_ID = "task_node_id"
TASK_NODE_STATE = "task_node_state"
TASK_ATTEMPT = "task_attempt"
ORIGIN_TASK_NODE_ID = "origin_task_node_id"
PARALLEL_GROUP = "parallel_group"
SERVICE_ID = "service_id"
ACCELERATOR_INSTANCE_ID = "accelerator_instance_id"
ACCELERATOR_ATTACHMENT = "accelerator_attachment"
EXTERNAL_REQUEST_ID = "external_request_id"
EXTERNAL_REQUEST_STAGE = "external_request_stage"
EXTERNAL_REQUEST_REASON = "external_request_reason"
EXTERNAL_REQUEST_VERDICT = "external_request_verdict"
DEPLOYMENT_VERSION = "deployment_version"
PROGRESS_RATIO = "progress_ratio"
TARGET_MEET_STATE = "target_meet_state"
FOCUS_REASON = "focus_reason"
REGION_REASON = "region_reason"
# --- 상태 스냅샷 한 장이 실어 보내는 이름 (2026-11-02, AI-O-06) -------------
# 채널 `status_snapshot` 의 본문 이름이다. 구조(중첩 모양)는
# `schemas/ai/status-snapshot.schema.json` 이 소유하고, 여기에는 **파트 경계를
# 넘는 의미 단위**만 등재한다 — 그 경계는 위 PAYLOAD 항목이 이미 정한 규칙이다.
# 스냅샷의 구역 묶음 이름. 구역(B~I)과 1:1 로 대응하므로 화면이 어느 묶음을 어느
# 구역에 그리는지 이 이름으로 정해진다.
MISSION = "mission"
FOCUS = "focus"
TASK_NODES = "task_nodes"
REFERENCE_EDGES = "reference_edges"
ACCELERATORS = "accelerators"
SERVICES = "services"
BOARD = "board"
VERDICTS = "verdicts"
EVENTS = "events"
EXTERNAL_REQUESTS = "external_requests"
MODEL_ASSIGNMENTS = "model_assignments"
SOURCES = "sources"
REGIONS = "regions"
MISSION_ID = "mission_id"
UTTERANCE_TEXT = "utterance_text"
ACCEPTED_AT = "accepted_at"
FOCUS_PINNED = "focus_pinned"
NODE_TITLE = "node_title"
NODE_KIND = "node_kind"
TARGET_DEVICE_ID = "target_device_id"
STARTED_AT = "started_at"
STATE_CHANGED_AT = "state_changed_at"
ESTIMATED_COMPLETION_AT = "estimated_completion_at"
INPUT_COMMAND = "input_command"
REFERENCE_EDGE_KIND = "reference_edge_kind"
REFERENCE_EDGE_WHEN = "reference_edge_when"
ACCELERATOR_KIND = "accelerator_kind"
ACCELERATOR_VENDOR_LABEL = "accelerator_vendor_label"
SERVICE_ROLE = "service_role"
MEASUREMENT = "measurement"
# 측정값을 담는 칸들. **이름에 단위를 넣지 않는다** — 단위는 measurement 안에 있다.
# 위쪽 AI-O-01 표본의 `temperature_c` 는 단위를 이름에 담은 평평한 float 이고,
# 이쪽은 값·단위·시각을 함께 들고 다니는 묶음이다. 둘을 한 이름으로 합치면 한쪽의
# 단위 정보가 사라진다.
UTILIZATION = "utilization"
TEMPERATURE = "temperature"
MEMORY_UTILIZATION = "memory_utilization"
POWER = "power"
POWER_TREND = "power_trend"
MEASURED_AT = "measured_at"
REQUESTED_AT = "requested_at"
SOURCE_STATUS = "source_status"
INDICATOR_NAME = "indicator_name"
CONDITION_ITEM_ID = "condition_item_id"
CONDITION_SATISFIED = "condition_satisfied"
CONDITION_REASON = "condition_reason"
ESCALATED_REQUEST_ID = "escalated_request_id"
EVENT_SEVERITY = "event_severity"
EVENT_KIND = "event_kind"
EVENT_MESSAGE = "event_message"
OCCURRED_AT = "occurred_at"
SERVER_WORK_IS_OPAQUE = "server_work_is_opaque"
DEPLOYMENT_RECEIVED = "deployment_received"
RE_EXECUTION_COUNT = "re_execution_count"
STAGE_ENTERED_AT = "stage_entered_at"
ASSIGNMENT_REASON = "assignment_reason"
MODEL_REFERENCE = "model_reference"
SOURCE_LAYER = "source_layer"
LAST_RECEIVED_AT = "last_received_at"
SOURCE_STALE = "source_stale"
REGION_AVAILABLE = "region_available"

#: 작업 그래프 노드의 런타임 상태 6종(기능정의서 §4.2). 가용성
#: (ACTIVE/DEGRADED/DISABLED)·결과(SUCCEEDED/FAILED/UNAVAILABLE)와 **다른 축**이다.
TASK_NODE_STATES: tuple[str, ...] = (
    "PENDING", "BLOCKED", "EXECUTING", "SUCCEEDED", "FAILED", "EXTERNAL_REQUESTED",
)

#: 외부 기능 요청 6단계(기능정의서 §4.9). SERVER_WORKING 구간은 내부가 보이지 않는다.
EXTERNAL_REQUEST_STAGES: tuple[str, ...] = (
    "JUDGED", "SENT", "SERVER_WORKING", "DEPLOYED", "RE_EXECUTING", "SETTLED",
)

EXTERNAL_REQUEST_REASONS: tuple[str, ...] = (
    "UNSUPPORTED_CAPABILITY", "SIM_REAL_MISMATCH",
)

EXTERNAL_REQUEST_VERDICTS: tuple[str, ...] = ("PENDING", "SUCCEEDED", "FAILED")

#: 목표 기준선 충족 여부. 미측정을 미달과 섞지 않기 위해 3값이다(기능정의서 §4.5).
TARGET_MEET_STATES: tuple[str, ...] = ("MET", "UNMET", "NOT_MEASURED")

#: 자동 추종이 기준 노드를 고른 사유(기능정의서 §2).
FOCUS_REASONS: tuple[str, ...] = (
    "focus_pinned_by_operator", "focus_attention_first",
    "focus_latest_executing", "focus_no_candidate",
)

#: 구역이 비어 있는 사유. 소스 미수신과 데이터 없음을 구분한다(기능정의서 §3).
REGION_REASONS: tuple[str, ...] = ("source_not_received", "no_data_yet")


# --- 구역 공간 근거 융합 (2026-11-02, AI-S-06/S-08, AI-C-02) ------------------
# 같은 구역의 같은 값을 여러 출처가 서로 다른 정확도로 말한다. 평균 하나로 뭉개면
# **사람이 실측한 값과 깊이맵 추측이 구분되지 않으므로**, 융합 결과와 함께 누가
# 무엇을 말했는지를 같은 이름으로 싣는다. 좌표 이름은 위 COORDINATE_FRAME 을 쓰고
# 전역 좌표 항목은 여기에 없다 — 전역 변환은 백엔드 소유다(AI-C-02).
#: 구역 공간 상태에서 융합 대상이 되는 값 하나의 이름(예: 어떤 기기의 자리, 어떤 벽의 길이).
QUANTITY_ID = "quantity_id"
#: 그 관측이 어느 종류의 공간 근거인가. 벤더·제품 이름이 아니라 **등록된 종류**다.
SPATIAL_EVIDENCE_KIND = "spatial_evidence_kind"
#: 근거의 격(사람 실측 / 선언 / 센서 추정). 정확도와 **다른 축**이다 — 정확도가 좋은
#: 추정이 사람 실측과 같은 격이 되지는 않는다.
EVIDENCE_TIER = "evidence_tier"
#: 그 관측이 **스스로 선언한** 1σ 정확도(m). null 은 모른다는 뜻이고 모름으로 남는다 —
#: 기본값을 넣는 순간 모르는 값이 아는 값처럼 가중된다.
ACCURACY_M = "accuracy_m"
#: 융합된 값. 성분 수는 quantity 가 정한다(길이는 1, 평면 자리는 2).
FUSED_VALUE = "fused_value"
#: 그 값을 정한 규칙. 사람 실측 덮어쓰기와 역분산 융합을 구분한다.
DECIDED_BY = "decided_by"
#: 값을 움직인 근거 종류들.
CONTRIBUTING_EVIDENCE_KINDS = "contributing_evidence_kinds"
#: 그 값을 확정으로 써도 되는가. **값이 있다는 것과 다른 축이다** — 선언(사전정보)만
#: 으로 나온 값은 자리를 말해 주지만 확정이 아니다(AI-S-08).
VALUE_CONFIRMED = "value_confirmed"
#: 확정이 아니라면 그 사유. 확정이면 null 이다.
UNCONFIRMED_REASON = "unconfirmed_reason"
#: 서로 **독립인** 지지의 수. 같은 frame_ref·같은 점군에서 나온 둘은 하나로 센다
#: (AI-S-06). 객체 레코드의 supporting_source_count 는 소스 그룹 수이고 이것은
#: 원본 관측 수라 서로 다른 값이다.
INDEPENDENT_SUPPORT_COUNT = "independent_support_count"
#: 각 근거가 값에 어떻게 들어갔는지의 내역. 융합 뒤에도 출처가 남아야 틀린 지도를
#: 디버깅할 수 있다.
CONTRIBUTIONS = "contributions"
#: 융합에 넣지 못한 관측과 그 사유. 조용히 버리면 왜 값이 안 바뀌는지 알 수 없다.
#: 사유 자체의 이름은 위 REJECTION_REASON 을 그대로 쓴다 — 같은 뜻을 두 이름으로
#: 적으면 사전이 사전 구실을 못 한다.
REJECTED_OBSERVATIONS = "rejected_observations"
#: 한 근거가 값에서 맡은 역할(독립 가중 / 같은 관측에 종속 / 정확도 미선언 보류 등).
CONTRIBUTION_ROLE = "contribution_role"
#: 역분산 가중치. 정확도를 선언하지 않은 근거는 0 이며 0 을 "값이 작다"로 읽지 않는다.
CONTRIBUTION_WEIGHT = "contribution_weight"
#: 사람 입력을 빼면 센서·선언만으로 무엇이었는가. 덮어썼다고 센서가 말한 것이 바뀌지는 않는다.
WITHOUT_HUMAN_VALUE = "without_human_value"
#: 사람 입력 값을 넣은 사람과 시각. 서명 없는 사람 입력은 받지 않는다(AI-L-03).
ENTERED_BY = "entered_by"
ENTERED_AT = "entered_at"
#: GPS 같은 절대 측위를 현장 로컬 좌표로 환산한 기준. 없으면 그 관측은 쓰지 않는다 —
#: 환산 기준 없는 절대 좌표를 로컬 값으로 섞으면 그 자리는 전역 좌표가 된다(AI-C-02).
LOCAL_REDUCTION_REF = "local_reduction_ref"
#: 등록됐지만 이번에 관측이 하나도 없는 근거 종류. **없음은 반대 근거가 아니다**.
UNOBSERVED_EVIDENCE_KINDS = "unobserved_evidence_kinds"
#: 한 출처를 빼면 값이 무엇이 되는가. 지도가 틀렸을 때 누가 틀렸는지 묻는 자리다.
LEAVE_ONE_OUT = "leave_one_out"
#: 그 출처를 뺐을 때 값이 움직인 거리(m). 0 이면 그 출처는 값을 정하지 않았다.
INFLUENCE_M = "influence_m"

#: EVIDENCE_TIER 의 값 어휘. 서열이 있다 — 사람 실측 > 선언 > 센서 추정.
SPATIAL_EVIDENCE_TIERS: tuple[str, ...] = ("measured", "declared", "estimated")

#: CONTRIBUTION_ROLE 의 값 어휘.
CONTRIBUTION_ROLES: tuple[str, ...] = (
    "independent",        # 자기 원본 관측을 대표하며 가중됐다
    "dependent",          # 같은 원본 관측의 다른 값 — 두 번 세지 않는다
    "accuracy_unknown",   # 정확도 미선언 — 선언한 근거가 있는 동안 보류한다
    "unweighted_mean",    # 아무도 정확도를 선언하지 않아 가중 없이 평균했다
    "override",           # 사람 실측이 값을 정했다
    "superseded",         # 더 나중 사람 실측이 대체했다
)

#: DECIDED_BY 의 값 어휘.
SPATIAL_DECISION_RULES: tuple[str, ...] = (
    "human_survey_override", "inverse_variance_fusion", "unweighted_mean", "no_evidence",
)

#: UNCONFIRMED_REASON 의 값 어휘. 확정을 **보류한** 사유이고 오류 코드가 아니다.
UNCONFIRMED_REASONS: tuple[str, ...] = (
    "no_evidence",           # 값을 움직인 근거가 없다
    "declared_prior_only",   # 선언(사전정보)뿐 — 실제 관측이 없다(AI-S-08)
)

#: REJECTION_REASON 의 값 어휘. 전부 "값이 왜 안 움직였는지"의 답이다.
SPATIAL_REJECTION_REASONS: tuple[str, ...] = (
    "unregistered_kind", "source_unavailable", "not_reduced_to_local_frame",
    "missing_author", "frame_mismatch", "arity_mismatch", "duplicate_evidence_id",
)


# --- 이종 근거의 공통 계약·충분도 (2026-11-03, AI-S-03/S-05/S-06) -------------
# 추론 근거는 사진 유사도 하나가 아니다. 외형·무선거리·운동상관·마커·공지 action·자원
# 태그·GPS·깊이·점군·열린어휘·선언 인프라·사람 실측·환경 사전정보가 모두 근거이고, 각
# 모듈이 자기 모양으로 들고 있었다. 그 모양들을 한 이름으로 모으는 자리가 여기다
# (`perception/evidence_kinds.py`). 공간 융합 전용 이름(SPATIAL_EVIDENCE_KIND 등)은
# 위 절에 그대로 두고 **갈래를 합치지 않는다** — 공간 값은 claim 이 수치이고 여기는
# 결론이 이름이라 같은 칸에 담으면 둘 다 설명이 안 된다.
#: 그 근거가 어느 **등록된 종류**인가. 벤더·제품 이름이 아니다(AI-C-18 과 같은 축).
EVIDENCE_KIND = "evidence_kind"
#: 그 근거가 가리키는 결론. 개체 id·기종 이름·구역 값 이름 등 질문에 따라 다르다.
CLAIM = "claim"
#: 그 근거들이 **무엇에 대해** 말하고 있는가(개체 식별·기종·구역 값). 질문을 적지 않으면
#: 같은 근거 묶음이 서로 다른 질문의 답으로 읽힌다.
CLAIM_SUBJECT = "claim_subject"
#: 그 근거를 낸 쪽이 말한 세기(0..1). **confidence 와 다른 축이다** — 모델 신뢰도가
#: 아니라 "이 근거가 자기 결론을 얼마나 세게 지지하는가" 다(AI-S-03).
EVIDENCE_STRENGTH = "evidence_strength"
#: 그 종류가 결론을 **가릴** 수 있는가. 비식별 근거가 아무리 쌓여도 식별 근거 하나를
#: 뒤집지 못한다는 규칙(perception/device_identity.py)의 이름이다.
DISCRIMINATING = "discriminating"
#: 지지가 아니라 **반박**인가. 식별력 있는 반박만 후보를 배제한다.
REFUTES = "refutes"
#: 같은 원본 관측에서 나온 선행 근거. 이 칸이 "두 번 봤다" 와 "한 번 본 것을 두 번
#: 읽었다" 를 가른다(AI-S-06).
DEPENDS_ON = "depends_on"
#: 이번에 실제로 근거를 낸 종류.
OBSERVED_EVIDENCE_KINDS = "observed_evidence_kinds"
#: 제공자가 없어 **미측정**인 종류 → 사유. 오류가 아니라 비활성이다(AI-C-05). 위
#: UNOBSERVED_EVIDENCE_KINDS("말할 수 있었는데 안 했다")와 **같은 칸에 담지 않는다** —
#: 합치면 "볼 능력이 없다" 와 "보이지 않았다" 가 같은 모양이 된다.
UNAVAILABLE_EVIDENCE_KINDS = "unavailable_evidence_kinds"
#: 무엇을 더 하면 풀리는지. AI-S-05 의 입구이고 실제 실행은 다른 파트다(AI-C-19).
RESOLUTION_REQUESTS = "resolution_requests"
#: 충분도 판정의 사유. 위 SUFFICIENCY_STATE 가 "무엇인가" 이고 이것이 "왜" 다.
SUFFICIENCY_REASON = "sufficiency_reason"

#: SUFFICIENCY_REASON 의 값 어휘. 토큰 뒤에 `:데이터` 가 붙을 수 있고 그때는
#: `state_change_reason_token` 과 같은 방식으로 앞부분만 본다.
EVIDENCE_SUFFICIENCY_REASONS: tuple[str, ...] = (
    "no_evidence_arrived",                          # 근거가 하나도 오지 않았다
    "no_discriminating_kind_is_available",           # 가릴 수 있는 종류의 제공자가 없다
    "discriminating_evidence_supports",              # 식별 근거가 결론을 받쳤다
    "discriminating_evidence_too_close",             # 식별 근거가 둘을 거의 같게 가리켰다
    "only_non_discriminating_evidence",              # 외형·선언만 — 가리지 못한다
    "sole_candidate_without_discriminating_evidence",  # 달리 없을 뿐 확정이 아니다
    "only_declared_prior_information",               # 사전정보만 — 확정하지 않는다(AI-S-08)
    "independent_support_below_minimum",             # 독립 출처가 모자라다
    "independent_support_met",                       # 독립 출처가 요구를 채웠다
    "every_claim_refuted_by_discriminating_evidence",  # 모든 후보가 배제됐다
    "claims_tied_without_discriminating_evidence",   # 비식별 근거로는 동점이다
)


# --- 가상환경 대역 자산 (2026-11-03, AI-S-06 · AI-C-08 · AI-C-15) -------------
# 디지털 트윈은 관측된 객체를 저장해 둔 **비슷한** 물체로 그린다
# (`perception/object_appearance.py`). 그 선택의 이름을 여기 모으는 이유는 두 가지다.
# 첫째, 대역은 **종류의 대역**이고 개체 주장이 아니다 — 그래서 이 절에 DEVICE_ID 와
# 같은 뜻의 칸이 하나도 없고, 그 부재가 설계다(perception/device_identity.py: 외형은
# 종류만 말한다). 둘째, 자산의 **픽셀은 여기로 나가지 않는다**(AI-C-08) — 나가는 것은
# 자산 참조 하나이고 뷰어가 그것으로 미디어 경로에서 받는다. 색·크기·카메라 각도 같은
# 표현 결정은 서버 응답에 들어오지 않는다(docs/view-contract.md).
#: 관측된 객체를 대신 그릴 저장 자산의 식별자. null 은 "대신할 것이 없다" 이고
#: 그것은 정상 상태다 — 자리는 그대로 나간다(AI-C-05).
PROXY_ID = "proxy_id"
#: 그 자산이 무엇을 묘사하는가(다국어 라벨). 표현 결정이 아니라 카탈로그의 자료다.
DEPICTS = "depicts"
#: 그 자산이 대신하는 **종류** 태그들. 개체 id 가 아니고 될 수도 없다.
STANDS_IN_FOR = "stands_in_for"
#: 자산의 표현 종류(저장 이미지 / 3D 모델). 벤더 열거형이 아니라 카탈로그가 스스로
#: 선언하는 어휘다 — 새 표현 방식을 더하는 일이 코드 변경이 되지 않게 한다.
ASSET_KIND = "asset_kind"
#: 자산 뿌리($MISSION_RUNTIME_ASSETS) 기준 상대 참조. 파일은 공개 트리 밖에 산다.
ASSET_REF = "asset_ref"
#: 그 자산이 어디서 왔는가. 제작·촬영·외부 조달을 구분해 적는다.
ASSET_ORIGIN = "asset_origin"
#: 그 자산의 라이선스 선언. **모름은 "unknown" 으로 적는다** — 빈 칸은 "확인했고
#: 제약이 없다" 와 구분되지 않는다(config/label_sources.example.json 과 같은 규약).
ASSET_LICENSE = "asset_license"
#: 자산 파일이 실제로 자산 뿌리에 있는가. **null 은 뿌리가 없어 확인하지 못한
#: 것**이고 '없다' 가 아니다.
ASSET_PRESENT = "asset_present"
#: 그 대역 자산이 묘사하는 실물의 가장 긴 변(m). null 은 미측정이고 0 이 아니다.
PROXY_EXTENT_M = "proxy_extent_m"
#: 관측이 **실측한** 그 객체의 가장 긴 변(m). null 은 미측정이다.
MEASURED_EXTENT_M = "measured_extent_m"
#: 선언 크기와 실측 크기의 비교 상태. 자산을 조용히 늘리지 않고 어긋남을 낸다.
SIZE_FIT_STATE = "size_fit_state"
#: 실측/선언 배율. 설명용 수치이고 **적용 지시가 아니다**. null 은 한쪽이 미측정이다.
SIZE_RATIO = "size_ratio"
#: 그 비교에 적용한 허용 배율. 데이터이고 현장 비교로 바꾼다(AI-C-13).
SIZE_TOLERANCE = "size_tolerance"
#: 크기 비교에서 **어느 쪽이** 미측정인가. 어느 쪽인지 적지 않으면 "카탈로그에 크기를
#: 안 적었다" 와 "관측이 크기를 못 쟀다" 가 같은 빈칸이 된다.
UNMEASURED_SIDE = "unmeasured_side"
#: 대역 선택의 상태. RESOLVED 만 모양을 말한다.
PROXY_STATE = "proxy_state"
#: 그 상태의 사유 토큰. "모양이 없다" 의 네 가지 이유를 한 빈칸으로 만들지 않는다.
PROXY_REASON = "proxy_reason"
#: 종류 추정이 그 상태인 사유(추정기 어휘). 위 PROXY_REASON 과 다른 축이다 —
#: 종류를 못 가린 것과 대역이 없는 것은 다른 사실이다.
KIND_CLAIM_REASON = "kind_claim_reason"
#: 그 대역 선택의 회차. 근거가 바뀌면 올라가고 **이전 선택을 덮지 않는다**(AI-S-06).
PROXY_REVISION = "proxy_revision"
#: 같은 종류를 대신할 수 있었던 다른 자산들(결정적 순서).
PROXY_ALTERNATIVES = "proxy_alternatives"
#: 그 종류의 대역이지만 지금 쓸 수 없었던 자산 → 사유. 조용히 빼지 않는다.
UNFIT_PROXIES = "unfit_proxies"
#: 이번 선택이 대체한 자산. 이력은 체인으로 남고 덮어쓰지 않는다.
SUPERSEDED_PROXY_ID = "superseded_proxy_id"
#: 왜 대체됐는가. 종류가 바뀐 것과 같은 종류의 다른 자산으로 바뀐 것을 구분한다.
SUPERSEDE_REASON = "supersede_reason"
#: 대역을 세울 자리. **현장 로컬 미터**이고 전역 값은 이 칸에 담기지 않는다
#: (AI-C-02: 로컬 값과 전역 값은 같은 칸에 담지 않는다). null 은 자리를 모르는 것이고
#: 0 좌표가 아니다 — 사유는 아래 PLACEMENT_REFUSAL_REASON 이 든다.
PROXY_POSITION = "proxy_position"
#: 그 자리를 내지 못한 사유. 전역 프레임으로 들어와 거절한 것과 아직 관측하지 못한
#: 것을 구분한다 — 합치면 "모른다" 와 "여기서 낼 수 없다" 가 한 빈칸이 된다.
PLACEMENT_REFUSAL_REASON = "placement_refusal_reason"
#: 그 자리의 방향(도). null 은 미측정이고 0 도가 아니다 — 저장 이미지 대역은 애초에
#: 자세를 말하지 못한다.
HEADING_DEG = "heading_deg"

#: PROXY_STATE 의 값 어휘.
PROXY_STATES: tuple[str, ...] = ("RESOLVED", "ABSENT")

#: PROXY_REASON 의 값 어휘. 전부 "왜 이 모양인가 / 왜 모양이 없는가" 의 답이다.
PROXY_REASONS: tuple[str, ...] = (
    "catalogued_stand_in_for_kind",     # 그 종류의 대역이 카탈로그에 있었다
    "kind_not_established",             # 종류가 아직 가려지지 않았다(AI-S-04)
    "no_catalogued_stand_in_for_kind",  # 종류는 아는데 대역이 없다
    "no_proxy_catalog",                 # 이 배치에 카탈로그가 없다(정상 축소)
    "every_stand_in_unfit",             # 대역은 있는데 자산 파일이 없다
)

#: SIZE_FIT_STATE 의 값 어휘. **unmeasured 는 mismatch 가 아니고 0 도 아니다.**
SIZE_FIT_STATES: tuple[str, ...] = ("match", "mismatch", "unmeasured")

#: PLACEMENT_REFUSAL_REASON 의 값 어휘.
PLACEMENT_REFUSAL_REASONS: tuple[str, ...] = (
    "unregistered_frame",            # 프레임 이름이 없다
    "global_value_not_owned_here",   # 전역 값은 datum 계층이 낸다(AI-C-02)
    "position_not_observed",         # 자리를 아직 관측하지 못했다
)

#: SUPERSEDE_REASON 의 값 어휘.
PROXY_SUPERSEDE_REASONS: tuple[str, ...] = (
    "estimated_kind_changed",            # 종류 추정이 바뀌어 대역도 바뀌었다
    "same_kind_different_stand_in",      # 같은 종류인데 다른 자산이 선택됐다
    "stand_in_no_longer_available",      # 쓰던 대역을 더 이상 쓸 수 없다
    "stand_in_became_available",         # 없던 대역이 생겼다
)


# --- 탐지로 지은 점유 지도 (2026-11-03, AI-S-06 · AI-S-08 · AI-C-02) ----------
# `perception/twin_map.py` 는 **희소한 탐지**로 지도를 짓는다. 촘촘한 깊이 스트림도
# 광선도 없으므로 한 칸을 숫자 하나로 적으면 "아무도 안 봤다" · "반쯤 점유로 합의했다" ·
# "서로 다르게 봤다" 가 모두 같은 값이 된다. 그래서 이 절의 이름은 **질량 넷을 서로
# 다른 칸에** 두고, 모름(`mass_unknown`)과 불일치(`mass_conflict`)를 끝까지 가른다 —
# 합치면 제공자의 침묵이 "비었다" 의 근거로 환산되고 그것이 이 프레임워크가 금지한
# 환산이다(AI-C-05, 원칙 #4).
#
# 지지 수를 `independent_support_count`(위 공간 융합 절) 하나로 세지 않고 관측 격과
# 사전정보 격으로 **쪼개 세는** 이유는 AI-S-08 이다: 도면이 벽이라고 적었다는 사실만
# 으로 칸이 점유로 확정되면 as-built 가 어긋난 현장에서 탐지가 영원히 틀린 쪽이 된다.
#
# 전역 좌표는 2026-11-03 개정으로 AI 소유이지만(AI-C-02) **필수가 아닌 계층**이다.
# 그래서 로컬 값과 전역 값에 각자의 칸을 주고(`local_position` · `global_position`)
# 둘을 같은 칸에 담지 않는다 — 한 칸에 합치면 전역 추정이 어느 측정에서 나왔는지
# 되짚을 수 없고, 어림 datum 을 통과한 값이 측량값과 같은 품질로 읽힌다.

#: 격자 칸 하나의 식별자(층 로컬 격자 인덱스). 전역 좌표가 아니다.
MAP_CELL_ID = "map_cell_id"
#: 격자 한 칸의 한 변(m). 칸 중심 좌표의 양자화 오차 하한을 정하는 값이다.
CELL_SIZE_M = "cell_size_m"
#: 질의한 사각 영역의 식별자. 위 REGION_ID(운영 화면의 선언된 구역)와 **다른 축이다** —
#: 이쪽은 호출자가 이번에 물어본 범위이고 선언된 구역 목록이 아니다.
MAP_REGION_ID = "map_region_id"
#: 영역·지도 한 장이 싣는 칸들. 관측되지 않은 칸을 **생략하지 않는다** — 목록에서
#: 빠진 칸은 화면에서 비어 보이고 그것이 "모름"을 "비었음"으로 바꾸는 길이다.
MAP_CELLS = "cells"
#: 칸 하나를 읽은 결과.
CELL_STATE = "cell_state"
#: 이 지도가 어느 격의 값을 내고 있는가. 받는 쪽이 로컬 값을 전역으로 오인하지
#: 않도록 payload 에 적어 둔다(AI-C-02).
MAP_AUTHORITY = "map_authority"

#: Ω={자유, 점유} 위의 질량 넷. 앞의 셋은 합이 1 이고 `mass_conflict` 는 질량이 아니라
#: Dempster 결합이 정규화로 버린 몫의 **감사 기록**이다. 넷을 한 숫자(log-odds)로
#: 뭉개면 무지와 불일치가 같은 값이 된다.
MASS_OCCUPIED = "mass_occupied"
MASS_FREE = "mass_free"
#: **0 이 아니라 1 이 기본값이다.** 아무도 보지 않은 칸은 전부 여기에 있다.
MASS_UNKNOWN = "mass_unknown"
#: 봤고, 서로 다르게 봤다. 0 으로 적으면 "안 봤다" 와 구분되지 않는다.
MASS_CONFLICT = "mass_conflict"

#: 한 관측이 칸에 대해 한 말. 위 CLAIM(개체 id·기종 이름 등 열린 문자열)과 **같은
#: 칸에 담지 않는다** — 이쪽은 닫힌 두 값이고 그 닫힘이 규칙으로 쓰인다(광선 없는
#: 출처는 `free` 를 말할 수 없다).
TWIN_MAP_CLAIM = "twin_map_claim"
#: 사전정보가 이 칸에 대해 한 말. 읽기값(CELL_STATE)과 **분리해 싣는다** — 도면을
#: 정답으로 쓰면 as-built 가 어긋날 때 탐지가 범인이 된다(AI-S-08).
PRIOR_CLAIM = "prior_claim"

#: 관측 격(사람 실측·센서 추정)의 **독립** 지지 수. 같은 frame_ref 두 개는 하나다.
#: 위 INDEPENDENT_SUPPORT_COUNT 와 세는 방법은 같고 **세는 대상이 다르다** — 이쪽은
#: 격을 가려 센다. 0 이면 사전정보가 무엇을 말하든 칸은 UNKNOWN 이다.
OBSERVED_SUPPORT_COUNT = "observed_support_count"
#: 사전정보 격 기여 수. 혼자서는 어떤 칸도 주장하지 못한다(AI-S-08).
PRIOR_SUPPORT_COUNT = "prior_support_count"
#: 관측 격 근거가 이 칸에 **한 번도** 닿지 않았는가. 낡음(stale)과 다른 사실이다 —
#: 하나는 가서 본 적이 없다는 뜻이고 하나는 본 것이 낡았다는 뜻이며 대응이 다르다.
NEVER_OBSERVED = "never_observed"
#: 관측 격 근거가 이 칸에 마지막으로 닿은 시각. null 은 **미관측**이고 0 이 아니다.
#: 위 OBSERVED_AT(관측 1건의 측정 시각)의 집계값이라 같은 이름을 쓰지 않는다.
LAST_OBSERVED_AT = "last_observed_at"

#: 그 관측이 어느 **등록된 종류**인가(AI-C-18 과 같은 축). 위 SPATIAL_EVIDENCE_KIND 가
#: 수치 quantity 의 근거 종류이고 이쪽은 칸 주장의 근거 종류다 — 어휘가 다르므로
#: 갈래를 합치지 않는다.
OBSERVATION_KIND = "observation_kind"
#: 자세 품질·노후화 할인을 **다 적용한 뒤** 실제로 융합에 들어간 세기. 할인 전 값은
#: 위 EVIDENCE_STRENGTH 로 나란히 싣는다 — 둘을 한 칸에 합치면 깎였다는 사실이 사라진다.
APPLIED_STRENGTH = "applied_strength"
#: 그 관측이 통과한 카메라 자세의 **품질 등급**. 위 POSE_SOURCE(자세를 만든 방법)와
#: 다른 축이고, 깎인 질량은 전부 mass_unknown 으로 간다 — 나쁜 자세는 "비었다" 의
#: 근거가 아니다.
POSE_QUALITY = "pose_quality"

#: 거절 사유 토큰 뒤의 부연(어느 프레임이었는지 등). 사유 자체의 이름은 위
#: REJECTION_REASON 을 그대로 쓴다.
REJECTION_DETAIL = "rejection_detail"
#: 그 출처를 빼면 점유 질량이 움직인 양(부호 있음, 무차원). 위 INFLUENCE_M(거리 m)과
#: 단위가 달라 같은 이름을 쓰지 않는다. 0 이면 그 출처는 읽기값을 정하지 않았다.
OCCUPANCY_INFLUENCE = "occupancy_influence"

#: 영역 요약의 칸 수. `unknown` 과 `never_observed` 를 따로 세는 것이 이 요약의 요점
#: 이다 — 봤지만 주장이 서지 않은 칸과 아예 본 적 없는 칸은 다른 문제다.
TOTAL_CELL_COUNT = "total_cell_count"
UNKNOWN_CELL_COUNT = "unknown_cell_count"
FREE_CELL_COUNT = "free_cell_count"
OCCUPIED_CELL_COUNT = "occupied_cell_count"
DISPUTED_CELL_COUNT = "disputed_cell_count"
NEVER_OBSERVED_CELL_COUNT = "never_observed_cell_count"
STALE_CELL_COUNT = "stale_cell_count"

#: 현장 로컬↔전역 변환(site datum)의 식별자. datum 은 공리가 아니라 **출처와 선언된
#: 정확도를 가진 근거**다(AI-C-02). null 은 이 배치에 datum 이 없다는 뜻이고 그것은
#: 정상 상태다 — 전역 계층만 비활성이 된다.
DATUM_ID = "datum_id"
#: 그 datum 이 어디서 왔는가(측량 기준점 / 공개 지도 / 어림). 같은 변환이라도 출처가
#: 다르면 품질이 전혀 다르다.
DATUM_SOURCE = "datum_source"
#: **현장 로컬** 미터 자리. 전역 값은 이 칸에 담기지 않는다(AI-C-02: 로컬 값과 전역
#: 값은 교환 가능하지 않다). 전역 값을 낸 응답에서는 이 칸이 그 전역 값이 유도된
#: **재료**를 든다 — 그래서 전역 추정의 출처를 되짚을 수 있다.
LOCAL_POSITION = "local_position"
#: 선언된 datum 을 통과해 유도한 전역 자리. **검증되지 않거나 정확도를 모르는 datum
#: 으로는 이 칸이 채워지지 않는다** — 사유는 FRAME_REFUSAL_REASON 이 든다.
GLOBAL_POSITION = "global_position"
#: LOCAL_POSITION 이 어느 로컬 프레임의 값인가. 응답의 COORDINATE_FRAME 은 그 응답이
#: 답한 프레임이므로 재료 쪽 프레임은 별도 칸이 필요하다.
DERIVED_FROM_FRAME = "derived_from_frame"
#: 그 자리의 정확도를 지배한 축(로컬 측정 / datum / 미측정). 전역 값은 **datum 보다
#: 좋을 수 없다**.
ACCURACY_LIMITED_BY = "accuracy_limited_by"
#: 요구된 프레임으로 값을 내지 못한 사유. 지어낸 좌표를 내보내는 것보다 거절하는
#: 편이 낫다 — 틀린 전역 좌표는 조용히 전파되고 거절은 눈에 보인다.
FRAME_REFUSAL_REASON = "frame_refusal_reason"

#: 그 요소가 아직 거기 있다고 믿는 정도(persistence filter).
PERSISTENCE_BELIEF = "persistence_belief"
#: 관측을 하나도 세지 않은 **순수 생존 사전확률**. 믿음과 나란히 싣는 이유는 "관측이
#: 끌어내린 것" 과 "시간만 흐른 것" 을 가르기 위해서다.
SURVIVAL_PRIOR = "survival_prior"
#: 봤다(`y=1`)는 보고의 수.
SIGHTING_COUNT = "sighting_count"
#: **봤는데 없었다**(`y=0`)는 보고의 수. 보지 않은 것은 여기에도 저기에도 세지지
#: 않는다 — 침묵은 부재의 근거가 아니다(AI-C-05, 원칙 #4).
NEGATIVE_REPORT_COUNT = "negative_report_count"
#: 마지막으로 **본** 시각. 위 LAST_OBSERVED_AT 과 같은 칸에 담지 않는다 — 음성 보고도
#: 관측이므로, 둘을 합치면 "봤는데 없었다" 와 "안 봤다" 가 한 칸이 된다.
LAST_SIGHTING_AT = "last_sighting_at"
#: 종류를 가리지 않은 마지막 보고 시각(양성·음성 모두).
LAST_REPORT_AT = "last_report_at"
#: 그 믿음이 **무엇 때문에** 그런가. 믿음값만으로는 내려간 이유를 알 수 없다.
PERSISTENCE_EXPLAINED_BY = "persistence_explained_by"

#: CELL_STATE 의 값 어휘. **UNKNOWN 과 FREE 는 다른 상태이고 DISPUTED 는 둘 다 아니다.**
CELL_STATES: tuple[str, ...] = (
    "UNKNOWN",   # 아무도 보지 않았거나, 선 주장이 없거나, 사전정보만 있다
    "FREE",      # 비었다는 주장이 섰다 — 광선을 가진 출처나 선언만 낼 수 있다
    "OCCUPIED",  # 점유 주장이 섰다
    "DISPUTED",  # 봤고, 서로 다르게 봤다 — 모름은 가서 봐야 하고 이쪽은 범인을 찾아야 한다
)

#: MAP_AUTHORITY 의 값 어휘.
MAP_AUTHORITIES: tuple[str, ...] = (
    "site_local",  # 칸과 융합이 현장 로컬 미터다. 전역 승격은 datum 을 통과해야 한다
)

#: TWIN_MAP_CLAIM · PRIOR_CLAIM 의 값 어휘. **"모름" 이 없는 것이 설계다** — 모름은
#: 주장이 아니라 주장의 부재이므로, 어휘에 넣으면 아무도 보지 않은 칸과 누군가
#: "모르겠다" 고 보낸 칸이 같은 자리에 적힌다.
TWIN_MAP_CLAIMS: tuple[str, ...] = ("occupied", "free")

#: POSE_QUALITY 의 값 어휘. 서열이 있다(검증 > 자기추정 > 선언 > 모름). 새 등급은
#: 레지스트리 등록으로 늘리고 핵심 코드는 고치지 않는다(AI-C-18, 원칙 #7).
POSE_QUALITIES: tuple[str, ...] = ("validated", "estimated", "declared", "unknown")

#: 지도 관측의 REJECTION_REASON 값 어휘. 위 SPATIAL_REJECTION_REASONS 와 겹치는
#: 토큰이 있지만 어휘를 합치지 않는다 — `free_claim_not_permitted` 는 이 지도에만
#: 있는 규칙이고, 그 규칙이 이 모듈의 중심이다.
TWIN_MAP_REJECTION_REASONS: tuple[str, ...] = (
    "unregistered_kind",         # 종류 이름이 등록되지 않았다(오타가 조용히 사라지지 않게)
    "source_unavailable",        # 그 출처를 지금 쓸 수 없다 — 반대 근거가 아니라 무기여다
    "duplicate_observation_id",  # 같은 관측을 두 번 넣으면 질량이 두 배가 된다
    "frame_mismatch",            # 변환 없이 섞으면 그 값은 아무 프레임의 값도 아니다
    "free_claim_not_permitted",  # 광선 없는 출처가 "비었다" 를 말하려 했다
    "unregistered_claim",        # 주장 어휘 밖의 말
    "empty_footprint",           # 어떤 칸도 건드리지 않았다
)

#: FRAME_REFUSAL_REASON 의 값 어휘. 전부 "왜 그 프레임으로 답하지 않았는가" 의 답이고
#: 오류 코드가 아니다 — datum 없는 현장은 정상 배치다(AI-C-05). 위
#: PLACEMENT_REFUSAL_REASONS 와 **다른 축이다**: 그쪽은 전역 값을 낼 자격이 없다고
#: 말하고, 이쪽은 자격을 가진 계층이 재료가 모자라 거절한다고 말한다.
FRAME_REFUSAL_REASONS: tuple[str, ...] = (
    "no_site_datum",            # 이 현장에 datum 선언이 없다
    "datum_accuracy_unknown",   # datum 이 있지만 정확도를 선언하지 않았다
    "no_local_value",           # 올릴 로컬 값 자체가 없다
    "unregistered_frame",       # 요구된 프레임 이름을 모른다
)

#: ACCURACY_LIMITED_BY 의 값 어휘. **`accuracy_unknown` 은 0 도 아니고 "제한 없음"도
#: 아니다** — 재료 중 하나가 미측정이면 합성도 미측정이다.
ACCURACY_LIMITS: tuple[str, ...] = ("local", "datum", "accuracy_unknown")

#: PERSISTENCE_EXPLAINED_BY 의 값 어휘.
PERSISTENCE_EXPLANATIONS: tuple[str, ...] = (
    "sighting",          # 가장 최근 보고가 "봤다" 였다
    "negative_report",   # 가장 최근 보고가 "봤는데 없었다" 였다
    "prior_decay_only",  # 보고가 없다 — 믿음은 생존 사전확률로만 내려갔다
)



# --- 상황 변화 기반 재계획 (AI-B-12, AI-B-14, 2026-11-03) ----------------------
# 서브태스크 그래프는 한 번 내고 끝나는 산출이 아니다 — "기존에 이동하려던 길이
# 막혔으면 새로운 서브 태스크 노드를 만들어 그래프에 연결해야" 한다. 그 재계획이
# 쓰는 이름을 여기 등록한다. **값 어휘도 여기 있다**: 상황 변화 종류를 재계획
# 모듈이 따로 적으면 같은 사실에 이름이 둘이 되고(AI-C-01 위반), 새 변화 종류를
# 넣는 일이 코드 수정이 된다(절대 준수 원칙 #7).

#: 무엇이 달라졌는가. 도메인 이름이 아니라 **등록된 변화 종류**다.
CHANGE_KIND = "change_kind"
#: 그 변화가 가리키는 대상. 종류에 따라 장소 id·capability kind·subtask_id 다 —
#: 종류별로 칸을 늘리지 않고 "무엇에 대한 변화인가" 한 칸으로 둔다.
CHANGE_SUBJECT = "change_subject"
#: 그래프 개정 번호. 재계획은 앞 개정을 덮지 않고 번호를 올린 새 그래프를 낸다.
GRAPH_REVISION = "graph_revision"
#: 이 그래프가 어느 개정에서 갈라져 나왔는가. 최초 개정은 null.
PARENT_GRAPH_REVISION = "parent_graph_revision"
#: 한 노드가 이 개정에서 **새로 생긴 것인지, 그대로 남은 것인지, 밀려난 것인지**.
#: 밀려남(superseded)은 삭제가 아니다 — 원 노드는 그래프에 남는다(AI-B-12).
NODE_LINEAGE = "node_lineage"
#: 노드의 문법상 역할(작업·분기·시작·종료). BPMN 의 **모양만** 빌렸고 런타임은
#: 들여오지 않는다(§3 금지). 이 모듈은 값으로 분기하지 않는다.
NODE_ROLE = "node_role"
#: 그 노드를 끼워 넣게 만든 변화. "왜 이 단계가 생겼는가" 의 답이다.
INSERTED_BY = "inserted_by"
#: 그 단계가 가는 자리의 식별자(구역·통로 등). **좌표가 아니다** — 자리의 좌표와
#: 그리기는 가시화 몫이고 여기서는 순서와 사유만 낸다(AI-C-19).
VISIT_TARGET = "visit_target"
#: 그래프 순서를 따라 방문하게 되는 자리들의 **순서**. 그래프가 바뀌면 같이 바뀐다.
VISIT_ORDER = "visit_order"
#: 분기 하나의 이름(예: 열렸다/막혔다). 표시 문구는 화면이 만든다.
BRANCH_NAME = "branch_name"
#: 그 분기가 성립하는 조건. 선언된 사실 이름이며 판정은 호출자의 세계 모델이 한다.
BRANCH_CONDITION = "branch_condition"
#: 분기 노드가 묻는 질문. 분기 쌍을 코드에 박지 않기 위해 질문도 데이터다.
DECISION_QUESTION = "decision_question"
#: 재계획이 **왜 그렇게 끝났는가**. 바뀌지 않은 경우도 사유로 설명된다(AI-C-05).
REPLAN_REASON = "replan_reason"
#: 끼워 넣기를 거부한 사유. 거부는 오류가 아니라 결과다.
INSERTION_REFUSAL_REASON = "insertion_refusal_reason"
#: 거부된 단계가 요구한 capability 이름. 외부 개발 요청의 재료다(AI-B-13).
REQUESTED_CAPABILITY = "requested_capability"
#: 재실행 회차. 원 노드는 1이고 회차는 새 노드로 쌓인다(AI-B-12).
ATTEMPT_INDEX = "attempt_index"
#: 재실행 노드가 가리키는 원 노드. 원 노드는 null.
ORIGIN_SUBTASK_ID = "origin_subtask_id"

#: CHANGE_KIND 의 **기본 선언 어휘**. 배포가 `register()` 로 늘릴 수 있고, 늘리는
#: 일은 이 어휘에 한 줄과 규칙 하나를 더하는 일이지 핵심 코드 수정이 아니다.
SITUATION_CHANGE_KINDS: tuple[str, ...] = (
    "route_leg_blocked",   # 지나려던 자리에 못 간다(구역·통로 도달 불가)
    "capability_lost",     # 그 단계를 받치던 필수 capability 가 사라졌다
    "step_failed",         # 그 단계를 수행했으나 실패했다
)

#: NODE_LINEAGE 의 값 어휘. **`superseded` 는 삭제가 아니다** — 밀려난 노드도
#: 그래프에 남아야 "무엇이 왜 다시 계획됐는가"를 되짚을 수 있다.
NODE_LINEAGES: tuple[str, ...] = ("kept", "new", "superseded")

#: NODE_ROLE 의 값 어휘. 시작·종료는 노드를 새로 만들어 끼우지 않고 간선이 없는
#: 노드를 화면이 그렇게 그릴 수 있게 **이름만** 둔 것이다.
NODE_ROLES: tuple[str, ...] = ("task", "decision", "start_event", "end_event")

#: REPLAN_REASON 의 값 어휘. 앞의 넷은 그래프가 그대로인 경우이고 — 재계획이 없는
#: 배치도, 아무도 답할 수 없는 변화도 정상 상태다(AI-C-05).
REPLAN_REASONS: tuple[str, ...] = (
    "no_replanner_configured",   # 이 배치에 재계획이 없다
    "no_situation_change",       # 들어온 변화가 없다
    "unknown_change_kind",       # 등록되지 않은 변화 종류 — 조용히 무시하지 않는다
    "no_rule_for_change",        # 어휘에는 있으나 답할 규칙이 없다
    "no_anchor_node_for_change", # 규칙은 있으나 그래프에 붙일 자리가 없다
    "all_insertions_refused",    # 끼울 단계 전부가 capability 접지에서 떨어졌다
    "replanned",                 # 새 개정이 나왔다
)

#: INSERTION_REFUSAL_REASON 의 값 어휘. `unknown_capability` 는
#: `planning/template_proposal.py` 와 같은 토큰을 쓴다 — 접지 거부는 생성이든
#: 재계획이든 같은 사실이고, 사유 이름이 갈리면 외부 요청 경로가 둘로 갈린다.
INSERTION_REFUSAL_REASONS: tuple[str, ...] = (
    "unknown_capability",   # 지금 provider 가 있는 어휘 밖이다(AI-B-14)
    "no_provider",          # 어휘에는 있으나 이 노드 태그·예산으로 해소되지 않았다
    "no_capability_named",  # 규칙이 필수 capability 를 적지 않았다
    "duplicate_action",     # 같은 action 이 이미 그래프에 있다
)


# --- 측정값의 출처와 계측 지점 (2026-11-03, AI-O-05 · AI-O-01) -----------------
#
# 같은 칸에 들어오는 숫자가 **이 기계에서 읽은 값**인지 **선언 데이터**인지 구분하는
# 축이다. 값의 유무(`measurement` 안의 `value` 칸)와 다른 질문이고, 둘을 한 축으로
# 합치면 선언된 예시가 계측으로 읽힌다 — 2026-11-03 감사가 적은 결손이 그것이었다.

#: 그 측정 1건이 어디서 왔는가. 값 칸의 유무와 **다른 축**이다.
MEASUREMENT_SOURCE = "measurement_source"
#: MEASUREMENT_SOURCE 의 값 어휘. 어휘의 정본은
#: `observability/layered_metrics.py` 의 `MEASUREMENT_SOURCES` 이고 여기서 이름만
#: 등재한다. 공간 근거의 `evidence_tier`(measured/declared/estimated)와 **다른
#: 항목**이다 — 저쪽은 근거의 격이고 이쪽은 관측 슬롯을 누가 채웠는가다.
MEASUREMENT_SOURCES: tuple[str, ...] = (
    "measured",     # 계측기가 이 호스트에서 실제로 읽었다
    "declared",     # 선언·등록 데이터다(숫자가 있어도 계측이 아니다)
    "unavailable",  # 재려 했으나 얻지 못했다 — 값 칸이 없고 0 이 아니다
)
#: 그 개체·보드를 재는 계측 지점의 id. 선언이 지목하며, 코드가 종류·벤더로
#: 추측하지 않는다(원칙 #1).
HOST_PROBE_ID = "host_probe_id"
#: 계측 지점별 상태 사유 토큰(`"<probe>.<slot>"` → 사유). 어휘의 정본은
#: `observability/host_resources.py` 의 `HOST_PROBE_REASONS` 다.
HOST_PROBE_STATUS = "host_probe_status"


_ENTRIES: tuple[FieldSpec, ...] = (
    FieldSpec(DEVICE_ID, "관측·명령의 대상이 되는 개별 장치 식별자", "str",
              ("말단", "엣지"), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(ENTITY_ID, "업무·가시화가 추적하는 논리 개체 식별자", "str",
              ("백엔드 레지스트리",), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(NODE_ID, "개체의 기능이 실행되는 물리 노드 식별자", "str",
              ("하드웨어", "백엔드 레지스트리"), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(ZONE_ID, "구역(엣지 관할 범위) 식별자", "str",
              ("엣지",), ("백엔드",), DataPlane.TASK),
    FieldSpec(SOURCE_ID, "관측을 만든 입력 소스(카메라·센서) 식별자", "str",
              ("입력 어댑터",), ("인지", "가시화"), DataPlane.TASK),
    FieldSpec(MESSAGE_ID, "파트 경계를 통과하는 메시지 1건의 식별자", "str",
              ("메시지 생산자",), ("백엔드", "감사"), DataPlane.TASK),
    FieldSpec(CHANNEL, "payload 의미를 나타내는 논리 구독 채널", "str",
              ("메시지 생산자",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(PAYLOAD, "봉투가 감싸는 채널별 본문(내부 이름은 contracts/ai 스키마가 정한다)", "dict",
              ("메시지 생산자",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(CAPABILITY_KIND, "기능 종류 식별자(구현이 아니라 목적 수준)", "str",
              ("레지스트리", "실행관리"), ("선택기", "관측"), DataPlane.TASK),
    FieldSpec(PROVIDER_ID, "해당 기능을 제공하는 구현 식별자", "str",
              ("레지스트리",), ("선택기", "관측"), DataPlane.TASK),
    FieldSpec(CLUSTER_ID, "실행이 배치된 제어면(서버/엣지) 식별자", "str",
              ("실행관리",), ("백엔드", "관측"), DataPlane.OBSERVABILITY),
    FieldSpec(PEER_ID, "보안 오버레이 상의 상대 노드 식별자", "str",
              ("오버레이 provider",), ("실행관리", "선택기"), DataPlane.OBSERVABILITY),

    FieldSpec(FRAME_ID, "원본 관측을 다시 찾기 위한 프레임 참조", "str",
              ("입력 어댑터",), ("인지", "재현", "가시화"), DataPlane.TASK),
    FieldSpec(OBSERVED_AT, "측정 시각(공통 시간 기준)", "float(epoch seconds)",
              ("말단", "엣지"), ("융합", "재현", "가시화"), DataPlane.TASK),
    FieldSpec(LOCAL_SEQUENCE, "노드 로컬 처리 순서(시계와 무관하게 단조 증가)", "int",
              ("말단", "엣지"), ("동일 노드 처리"), DataPlane.TASK),
    FieldSpec(TIME_SYNC_STATE, "시간 동기화 상태(노드 간 정합 가능 여부)", "SYNCED|DEGRADED",
              ("말단", "엣지"), ("융합",), DataPlane.OBSERVABILITY),
    FieldSpec(TIMESTAMP, "메시지 봉투가 생성된 공통 시각", "str(ISO-8601 UTC)",
              ("메시지 생산자",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(SEQUENCE_ID, "동일 생산자의 메시지 순서 식별자", "int",
              ("메시지 생산자",), ("백엔드", "가시화"), DataPlane.TASK),

    FieldSpec(SCHEMA_VERSION, "메시지 구조 버전", "str", ("생산자 전체",), ("소비자 전체",), DataPlane.TASK),
    FieldSpec(MODEL_VERSION, "판단에 사용한 모델·규칙 버전", "str",
              ("인지", "위험"), ("백엔드", "재현"), DataPlane.TASK),
    FieldSpec(CONFIG_VERSION, "적용 중인 실행 구성 버전", "int|str",
              ("말단", "엣지"), ("실행관리",), DataPlane.TASK),
    FieldSpec(CALIBRATION_PROFILE_VERSION, "적용된 카메라 보정 프로파일 버전", "str",
              ("엣지 보정",), ("인지", "좌표 변환"), DataPlane.TASK),

    FieldSpec(OBSERVATION_NAME, "관측 항목의 의미 이름(수위·위치 등)", "str",
              ("말단",), ("엣지", "백엔드"), DataPlane.TASK),
    FieldSpec(OBSERVATION_VALUE, "관측 값", "number|list|str",
              ("말단",), ("엣지", "백엔드"), DataPlane.TASK),
    FieldSpec(COORDINATE_FRAME,
              "공간 값의 기준 좌표계. ZONE은 엣지가 여러 카메라를 융합해 낸 구역 공통"
              " 좌표(후보값)이고 GLOBAL은 서버가 여러 구역을 통합해 확정한 authoritative"
              " 값이다 — 엣지는 ZONE까지만 산출하고 GLOBAL 승격은 백엔드 소관이다(AI-C-02, AI-C-19)",
              "IMAGE|CAMERA_LOCAL|ZONE|GLOBAL",
              ("인지", "엣지 위치 융합"), ("디지털트윈", "가시화"), DataPlane.TASK),

    FieldSpec(PLAN_ID, "요청 1건의 해석·배치 결과(ExecutionPlan) 식별자", "str",
              ("실행관리",), ("관측", "가시화", "감사"), DataPlane.OBSERVABILITY),
    FieldSpec(REQUESTER_ROLE, "요청 주체의 역할(값 어휘·권한 판정은 소유자의 인증 설계)", "str",
              ("가시화", "백엔드", "엣지", "말단"), ("실행관리", "감사"), DataPlane.TASK),

    FieldSpec(CAPABILITY_STATE_BEFORE, "상태 변화 이전의 기능 상태", "ACTIVE|DEGRADED|DISABLED",
              ("실행관리",), ("관측", "백엔드"), DataPlane.OBSERVABILITY),
    FieldSpec(CAPABILITY_STATE_AFTER, "상태 변화 이후의 기능 상태", "ACTIVE|DEGRADED|DISABLED",
              ("실행관리",), ("관측", "백엔드"), DataPlane.OBSERVABILITY),
    FieldSpec(STATE_CHANGE_REASON,
              "기능 상태가 바뀐(또는 provider가 선택·탈락한) 사유. 자유 문자열이 아니라"
              " STATE_CHANGE_REASONS의 통제 어휘이며, ':' 뒤에는 데이터(빠진 kind·태그 목록)가"
              " 붙을 수 있다 — 소비자는 state_change_reason_token()으로 어휘만 떼어 본다",
              "|".join(STATE_CHANGE_REASONS),
              ("실행관리", "선택기"), ("관측", "운영자", "가시화"), DataPlane.OBSERVABILITY),

    FieldSpec(DEVICE_PROBE_LEVEL, "연결 검증이 도달한 단계 — 1 도달(이름 해석·ICMP), 2 신원·계층"
              "(SSH 로그인·실측 태그 대조), 3 기능(프레임·heartbeat 수신)", "1|2|3",
              ("연결 검증",), ("운영자", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(DEVICE_PROBE_REASON, "그 단계가 그렇게 끝난 사유. STATE_CHANGE_REASONS와 별개의"
              " 통제 어휘이며(장치 도달 vs capability 판정), 장치의 최종 가용성 판정이 아니다",
              "|".join(DEVICE_PROBE_REASONS),
              ("연결 검증",), ("운영자", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(PROBED_AT, "연결 검증 관측 시각(epoch 초). status UI의 '마지막 검증' freshness가"
              " RuntimeInstance.health_checked_at으로 읽는 값", "float",
              ("연결 검증",), ("운영자", "가시화"), DataPlane.OBSERVABILITY),

    FieldSpec(DEVICE_PURPOSE_ID, "등록된 장치가 무엇을 하러 있는가 — 온디바이스 기능 선정의 입력이 되는"
              " 목적 프로파일 식별자(도메인 이름이 아니다)", "str",
              ("배포 프로파일",), ("실행관리", "운영자", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(CAPABILITY_RESIDENCY, "이 capability kind가 말단에 상주하는가 엣지에서 제공되는가",
              "|".join(CAPABILITY_RESIDENCIES),
              ("실행관리",), ("실행관리", "운영자", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(RESIDENCY_DECISION_REASON, "그 배치가 그렇게 정해진 사유. 통제 어휘이며 ':' 뒤에 데이터가 붙는다",
              "|".join(RESIDENCY_DECISION_REASONS),
              ("실행관리",), ("운영자", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(LINK_POSTURE_REASON, "링크 자세가 그렇게 판정된 사유(측정값인지 기본값인지 구분 포함)",
              "|".join(LINK_POSTURE_REASONS),
              ("실행관리",), ("운영자", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(LINK_STABILITY, "링크가 floor 위에 머문 시간 비율 — 평균 품질과는 다른 축",
              "float|null", ("링크 품질 provider",), ("실행관리",), DataPlane.OBSERVABILITY),
    FieldSpec(OUTAGE_BEHAVIOR, "엣지에 닿지 못하는 동안 이 기능이 어떻게 되는가",
              "|".join(OUTAGE_BEHAVIOR_VALUES),
              ("배포 프로파일",), ("실행관리", "운영자", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(EDGE_SERVICE, "말단에 두지 않은 kind를 엣지에서 담당하는 서비스 식별자", "str|null",
              ("배포 프로파일",), ("실행관리", "운영자"), DataPlane.OBSERVABILITY),

    FieldSpec(COMMAND_ID, "명령 1건의 식별자(회신 상관 및 책임 추적용)", "str",
              ("백엔드",), ("엣지", "말단"), DataPlane.TASK),
    FieldSpec(COMMAND, "요청된 명령의 종류", "str", ("백엔드",), ("말단",), DataPlane.TASK),
    FieldSpec(COMMAND_OUTCOME, "명령의 업무 결과", "RECEIVED|SUCCESS|REJECTED|FAILED",
              ("말단",), ("백엔드", "감사"), DataPlane.TASK),
    FieldSpec(REJECTION_REASON, "거부·실패 사유(전송 실패와 구분되는 업무 사유)", "str",
              ("말단", "실행관리"), ("백엔드", "감사"), DataPlane.TASK),
    FieldSpec(CORRELATION_ID, "파트 간 요청·결과·감사를 연결하는 상관 식별자", "str|null",
              ("백엔드",), ("AI", "엣지", "말단", "가시화"), DataPlane.TASK),

    FieldSpec(DETECTIONS, "한 프레임의 인지 결과 목록(개수 요약인 detection_count와 구분)",
              "list[object]", ("인지",), ("추적", "위험 분석", "백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(RISK_STATE, "위험 분석 상태", "str", ("위험 분석",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(RISK_LEVEL, "위험 정도", "float", ("위험 분석",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(REQUIRED_EVIDENCE_KIND, "업무 목적이 요구하는 증거의 종류", "str",
              ("임무 분해", "업무 정의"), ("오케스트레이터", "선택기"), DataPlane.TASK),
    FieldSpec(REQUIRED_EVIDENCE_TOLERANCE, "그 증거가 충족으로 인정되는 경계", "float",
              ("임무 분해", "업무 정의"), ("충분도 판정",), DataPlane.TASK),
    FieldSpec(REQUIRED_EVIDENCE_GRANULARITY, "요구 해상도(목적별로 다르다)", "str",
              ("임무 분해",), ("오케스트레이터", "선택기"), DataPlane.TASK),
    FieldSpec(REQUIRED_EVIDENCE_NECESSITY, "필수 근거인가 선택 근거인가", "str",
              ("임무 분해", "업무 정의"), ("충분도 판정", "축소 판정"), DataPlane.TASK),
    FieldSpec(CONTRACT_REVISION, "임무 요구가 운용 중 바뀔 때 올라가는 개정 번호", "int",
              ("임무 분해",), ("오케스트레이터", "감사"), DataPlane.TASK),
    FieldSpec(SUFFICIENCY_STATE, "계약 대비 현재 레코드의 충족 상태", "str",
              ("충분도 판정",), ("오케스트레이터", "가시화", "감사"), DataPlane.TASK),
    FieldSpec(EVIDENCE_SUFFICIENCY, "판단 근거의 충분도(모델 신뢰도와 구분)", "float",
              ("인지", "위험 분석"), ("의사결정", "백엔드"), DataPlane.TASK),
    FieldSpec(EVIDENCE_USED, "판단에 사용한 근거 목록", "list[str]",
              ("위험 분석",), ("백엔드", "감사"), DataPlane.TASK),
    FieldSpec(RECOMMENDATION, "권고 조치(실제 제어 명령 생성은 백엔드 책임)", "str",
              ("위험 분석",), ("백엔드",), DataPlane.TASK),

    FieldSpec(BUSINESS_CORRELATION_ID, "업무 상관 식별자(장기 재현 진입점)", "str",
              ("AI 실행환경",), ("재현", "감사"), DataPlane.TASK),
    FieldSpec(SHORT_TERM_REPLAY_REF, "단기 전송로그 replay 참조(보존 기간 내)", "str",
              ("전송 provider",), ("재현",), DataPlane.OBSERVABILITY),
    FieldSpec(ARCHIVE_REF, "장기 저장·아카이브 참조", "str",
              ("업무 저장소",), ("재현",), DataPlane.TASK),
    FieldSpec(TRACE_ID, "기술 처리 경로·지연 추적 식별자", "str",
              ("관측 provider",), ("관측", "성능 분석"), DataPlane.OBSERVABILITY),

    FieldSpec(TASK_TRANSPORT_ALIVE, "업무 전송 세션 생존 신호", "bool",
              ("전송 provider",), ("백엔드 가용성 통합",), DataPlane.TASK),
    FieldSpec(OBSERVABILITY_ALIVE, "관측 경로 생존 신호", "bool",
              ("관측 provider",), ("백엔드 가용성 통합",), DataPlane.OBSERVABILITY),
    FieldSpec(OVERLAY_STATE, "보안 오버레이 연결 상태(위 두 신호와 별개)", "CONNECTED|DISCONNECTED|UNAVAILABLE",
              ("오버레이 provider",), ("실행관리", "백엔드"), DataPlane.OBSERVABILITY),

    FieldSpec(SOURCE_GROUP, "근거를 생산한 독립 생산자 그룹(같은 계열은 하나로 셈)", "str",
              ("인지 provider",), ("객체 레코드", "환경 구조 추정"), DataPlane.TASK),
    FieldSpec(SUPPORTING_SOURCE_COUNT, "현재 상태를 지지하는 독립 생산자 수(신뢰도와 구분)", "int",
              ("객체 레코드",), ("백엔드 디지털 트윈", "의사결정"), DataPlane.TASK),
    FieldSpec(RECORD_REVISION, "동일 객체 레코드의 갱신 회차", "int",
              ("객체 레코드",), ("백엔드 디지털 트윈", "가시화"), DataPlane.TASK),
    FieldSpec(LIFECYCLE_STATE, "객체 지속 상태", "provisional|confirmed|stale|expired",
              ("객체 레코드",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(GEOMETRY_KIND, "기하 표현의 종류(영역 근사 / 분할 결과)", "region|mask",
              ("객체 레코드",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(EXPOSED_AT, "해당 상태가 소비자에게 가용해진 시각(관측 시각과 구분)", "float",
              ("객체 레코드",), ("백엔드", "성능 분석"), DataPlane.TASK),

    FieldSpec(MAP_ELEMENT_ID, "환경 구조 요소 식별자", "str",
              ("환경 구조 추정",), ("계획 기능", "백엔드"), DataPlane.TASK),
    FieldSpec(STRUCTURE_UNCERTAINTY, "환경 구조 요소 추정의 불확실도(확정값 아님)", "float",
              ("환경 구조 추정",), ("계획 기능", "백엔드 디지털 트윈"), DataPlane.TASK),
    FieldSpec(ANCHOR_ID, "추정 위치가 기준으로 삼은 기준점(전역 좌표계 정의 아님)", "str",
              ("환경 구조 추정",), ("백엔드 디지털 트윈",), DataPlane.TASK),

    FieldSpec(LINK_QUALITY, "말단↔엣지 무선 링크 품질(정규화, 지표 종류 비노출)", "float",
              ("링크 품질 provider",), ("온디바이스 전환 판단", "관측"), DataPlane.OBSERVABILITY),
    FieldSpec(LINK_POSTURE, "링크 품질에 따른 현재 실행 태세(전송·오버레이 상태와 별개)."
              " 운행 중 전환(AI-N-03)과 배치 시점 기능 선정이 같은 항목을 쓴다", "|".join(LINK_POSTURES),
              ("온디바이스 전환 판단",), ("실행 재구성", "백엔드"), DataPlane.OBSERVABILITY),

    FieldSpec(PLATFORM_KIND, "관측·작업을 수행하는 이동체의 종류(제품명이 아니라 역할 수준 태그 어휘)",
              "str(예: platform.uav, platform.usv, platform.ground_robot, platform.fixed_camera)",
              ("배포 프로파일", "노드 자원 탐색"), ("기능 선택", "추가 정보 요청"), DataPlane.TASK),
    FieldSpec(SENSOR_KIND, "관측에 쓰이는 센서의 종류(제품명이 아니라 역할 수준 태그 어휘)",
              "str(예: sensor.rgb, sensor.lidar, sensor.sonar, sensor.sar, sensor.thermal)",
              ("배포 프로파일", "노드 자원 탐색"), ("기능 선택", "추가 정보 요청"), DataPlane.TASK),
    FieldSpec(AUTONOMY_LEVEL, "권고된 조치를 수행할 때 사람이 어디까지 개입해야 하는지의 등급"
              "(AI는 등급을 표시만 하고 승인 절차·명령 발급은 백엔드 소관, AI-C-19)",
              "teleoperated|shared|autonomous",
              ("의사결정",), ("백엔드", "가시화"), DataPlane.TASK),

    FieldSpec(NODE_POSE, "이동형 에이전트의 현재 위치·방향 추정치(확정값 아님, coordinate_frame과 함께 해석)",
              "dict(position+orientation)",
              ("말단(에이전트 자체 추정)", "인지(고정 카메라 기반 관측)"),
              ("위치 융합", "객체 레코드", "가시화"), DataPlane.TASK),
    FieldSpec(POSE_SOURCE, "node_pose를 산출한 방법 — 방법마다 신뢰도가 다르므로 근거로 함께 취급한다"
              "(예: fixed_camera_observation, onboard_odometry)",
              "str", ("말단", "인지"), ("위치 융합", "근거 충분도 평가"), DataPlane.TASK),
    FieldSpec(POSE_UNCERTAINTY, "node_pose의 누적 불확실도(시간 경과·근거 종류에 따라 커짐, 확정값 아님)",
              "float", ("말단", "인지"), ("위치 융합", "근거 충분도 평가", "백엔드"), DataPlane.TASK),
    FieldSpec(CAMERA_EXTRINSIC, "고정 카메라의 구역(zone) 내 위치·방향 — 보정 프로파일의 일부로"
              " calibration_profile_version과 함께 버전 관리되며 매 틱 갱신되는 node_pose와 다르다",
              "dict(position+orientation)", ("엣지 보정",), ("인지", "좌표 변환", "위치 융합"), DataPlane.TASK),

    FieldSpec(REGION_ID, "관측 커버리지를 누적하는 공간 구역 식별자(전역 좌표 아님)", "str",
              ("커버리지 추정",), ("계획 기능", "실험 기록", "백엔드"), DataPlane.TASK),
    FieldSpec(OBSERVATION_ID, "커버리지에 반영된 개별 관측 보고 1건의 식별자(중복 배달 제거용)", "str",
              ("인지 provider",), ("커버리지 추정",), DataPlane.TASK),
    FieldSpec(OBSERVED_FRACTION, "해당 구역에서 실제로 관측된 비율(확신도와 구분)", "float[0,1]",
              ("커버리지 추정",), ("계획 기능", "시나리오 실행", "백엔드"), DataPlane.TASK),
    FieldSpec(COVERAGE_GAIN, "1회 관측 실행이 더한 커버리지 증분(누적값과 구분)", "float[0,1]",
              ("관측 실행",), ("커버리지 추정", "실험 기록"), DataPlane.TASK),
    FieldSpec(BLIND_SPOT_CAUSE, "구역에 현재 쓸 수 있는 관측이 없는 사유(소스 없음/가림/소스 장애/노후/미완)",
              "NO_SOURCE|OCCLUDED|SOURCE_FAILURE|STALE|INCOMPLETE",
              ("커버리지 추정",), ("운영자", "실험 기록", "백엔드"), DataPlane.TASK),

    FieldSpec(EVIDENCE_ID, "객체 레코드에 반영된 근거 1건의 식별자", "str",
              ("인지 worker",), ("객체 레코드", "재현"), DataPlane.TASK),
    FieldSpec(FRAME_REF, "근거가 파생된 원본 관측 참조(전송 계약에서는 frame_id 로 실린다)", "str",
              ("입력 어댑터", "인지 worker"), ("객체 레코드", "재현", "가시화"), DataPlane.TASK),
    FieldSpec(AVAILABLE_AT, "근거가 소비 가능해진 시각(측정 시각 observed_at 과 구분)", "float",
              ("인지 worker",), ("객체 레코드", "성능 분석"), DataPlane.TASK),
    FieldSpec(OBJECT_ID, "여러 근거를 묶어 유지하는 객체 레코드 식별자", "str",
              ("객체 레코드",), ("백엔드 디지털 트윈", "가시화"), DataPlane.TASK),
    FieldSpec(SEMANTIC_CLASS, "객체의 확정 분류(미확인은 강제 매핑하지 않는다)", "str",
              ("객체 레코드",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(CONFIDENCE, "모델·소스가 스스로 보고한 신뢰도(근거 충분도와 구분)", "float[0,1]",
              ("인지", "위험 분석"), ("객체 레코드", "의사결정", "백엔드"), DataPlane.TASK),

    FieldSpec(ZONE_LOCAL_TRACK_ID, "AI가 구역 내에서 부여한 추적 식별자(백엔드가 부여하는 전역 object_id와 구분)",
              "str", ("객체 레코드",), ("백엔드 디지털 트윈(전역 object_id 매핑)", "가시화"), DataPlane.TASK),

    FieldSpec(ROTATION_DEG, "회전 스캔 중 해당 프레임을 찍은 시점의 상대 회전각(0/45/.../315 등, 시작 방향 기준)",
              "float(deg)", ("말단(회전 스캔)",), ("자기위치추정", "가시화"), DataPlane.TASK),
    FieldSpec(ABSOLUTE_BEARING_DEG, "rotation_deg를 지도 기준 절대 방위각으로 환산한 값(node_pose와 함께 해석)",
              "float(deg)", ("자기위치추정",), ("경로 계산", "가시화"), DataPlane.TASK),
    FieldSpec(TURN_DEG, "현재 방향에서 목표를 향하도록 회전해야 하는 양(오른쪽(시계)=+)",
              "float(deg)", ("경로 계산",), ("물리 명령(Command.parameters)", "가시화"), DataPlane.TASK),
    FieldSpec(FORWARD_DISTANCE_M, "회전 후 직진해야 하는 거리(standoff_cm이 이미 반영된 값)",
              "float(m)", ("경로 계산",), ("물리 명령(Command.parameters)", "가시화"), DataPlane.TASK),
    FieldSpec(STANDOFF_CM, "목표 앞 정지 거리(클래스별로 다를 수 있음, 예: door=80cm)",
              "float(cm)", ("경로 계산 설정",), ("경로 계산", "가시화"), DataPlane.TASK),
    FieldSpec(FEATURE_SIMILARITIES, "클래스 판정에 쓰인 CLIP 텍스트 특징 문구별 유사도 원본값",
              "dict[str, float]", ("CLIP dictionary provider",), ("근거 재현", "가시화"), DataPlane.TASK),
    FieldSpec(MANDATORY_GATES, "클래스 판정이 통과해야 하는 필수 게이트별 통과여부·실측값",
              "dict[str, object]", ("CLIP dictionary provider",), ("근거 재현", "가시화"), DataPlane.TASK),

    FieldSpec(UNKNOWN_LIKELIHOOD, "이 검출이 미확인(open-set) 객체일 가능성(known-class confidence와 구분)",
              "float", ("인지",), ("객체 레코드", "미확인 후보 등록"), DataPlane.TASK),
    FieldSpec(UNKNOWNNESS_POLICY_ID, "unknown_likelihood를 산출한 교체 가능한 정책 식별자(AI-C-13)",
              "str", ("인지",), ("객체 레코드", "실험 기록"), DataPlane.TASK),

    FieldSpec(GOAL_ID, "분해 대상이 된 목표(구역 임무) 식별자", "str",
              ("임무 배분",), ("서브태스크 분해", "실험 기록"), DataPlane.TASK),
    FieldSpec(GOAL_KIND, "목표의 종류(도메인 이름이 아니라 템플릿 선택 키)", "str",
              ("배포 프로파일",), ("서브태스크 분해",), DataPlane.TASK),
    FieldSpec(SUBTASK_ID, "생성된 서브태스크 1건의 식별자", "str",
              ("서브태스크 분해",), ("실행관리", "가시화"), DataPlane.TASK),
    FieldSpec(ORDER_INDEX, "서브태스크의 실행 순서", "int",
              ("서브태스크 분해",), ("실행관리", "가시화"), DataPlane.TASK),
    FieldSpec(EXECUTOR_ID, "서브태스크를 실제로 수행할 실행 주체 식별자", "str|null",
              ("서브태스크 분해",), ("실행관리",), DataPlane.TASK),
    FieldSpec(MISSING_REQUIRED_CAPABILITIES, "실행 불가 사유가 된 결손 필수 기능 목록", "list[str]",
              ("서브태스크 분해",), ("실행관리", "관측"), DataPlane.TASK),
    FieldSpec(MISSING_OPTIONAL_CAPABILITIES, "축소 실행의 사유가 된 결손 선택 기능 목록", "list[str]",
              ("서브태스크 분해",), ("실행관리", "관측"), DataPlane.TASK),
    FieldSpec(ITEM_ID, "임무 판정 단위(필수·선택 항목) 식별자", "str",
              ("임무 정의",), ("임무 판정", "실험 기록"), DataPlane.TASK),
    FieldSpec(MISSION_STATUS, "임무 전체의 달성 판정(선택 항목 포기와 구분)", "str",
              ("임무 판정",), ("백엔드", "실험 기록"), DataPlane.TASK),
    FieldSpec(OPTIONAL_QUALITY, "선택 항목까지 포함한 수행 품질 수준", "ACTIVE|DEGRADED|DISABLED",
              ("임무 판정",), ("백엔드", "실험 기록"), DataPlane.TASK),
    FieldSpec(DETECTION_COUNT, "1회 관측 실행이 산출한 인지 결과 개수(인지 결과 목록 자체가 아님)", "int",
              ("관측 실행",), ("실험 기록", "백엔드"), DataPlane.TASK),

    FieldSpec(WORKER_ID, "한 프레임을 처리한 인지 실행 단위 식별자", "str",
              ("수집 세션",), ("실험 기록", "성능 분석"), DataPlane.OBSERVABILITY),
    FieldSpec(LATENCY_MS, "해당 실행 단위의 처리 지연", "float(ms)",
              ("수집 세션", "관측 실행"), ("실험 기록", "성능 분석"), DataPlane.OBSERVABILITY),
    FieldSpec(RSS_MIB, "실행 프로세스의 상주 메모리", "float(MiB)",
              ("자원 표본 수집",), ("실험 기록", "실행 재구성"), DataPlane.OBSERVABILITY),
    FieldSpec(CPU_PERCENT, "실행 프로세스의 CPU 점유율", "float",
              ("자원 표본 수집",), ("실험 기록", "실행 재구성"), DataPlane.OBSERVABILITY),
    FieldSpec(ENERGY_UJ, "누적 에너지 카운터 값(구간 소비는 차분으로 구한다)", "int(uJ)",
              ("자원 표본 수집",), ("실험 기록",), DataPlane.OBSERVABILITY),
    FieldSpec(TEMPERATURE_C, "실행 노드 온도(과열 기반 축소 판단 입력)", "float(C)",
              ("자원 표본 수집",), ("실험 기록", "실행 재구성"), DataPlane.OBSERVABILITY),
    FieldSpec(SAMPLED_AT, "자원 표본을 읽은 시각(관측 대상의 측정 시각과 구분)", "float(epoch seconds)",
              ("자원 표본 수집",), ("실험 기록",), DataPlane.OBSERVABILITY),
    FieldSpec(ITEM_COUNT, "실행 단위 1회가 산출한 항목 수(항목 내용 자체가 아님)", "int",
              ("수집 세션",), ("실험 기록",), DataPlane.OBSERVABILITY),
    FieldSpec(ERROR_CODE, "오류·이상 사건의 분류 코드(사람이 읽는 설명과 구분)", "str",
              ("AI 실행 단위",), ("관측", "백엔드 알림"), DataPlane.OBSERVABILITY),
    FieldSpec(ERROR_DETAIL, "오류·이상 사건의 사람이 읽는 설명", "str",
              ("AI 실행 단위",), ("관측", "운영자"), DataPlane.OBSERVABILITY),

    FieldSpec(AVAILABLE_GROUPS_BEFORE, "가용 소스 그룹 변화 이전 목록(기능 상태와 구분)", "list[str]|null",
              ("수집 세션",), ("실험 기록", "재현"), DataPlane.OBSERVABILITY),
    FieldSpec(AVAILABLE_GROUPS_AFTER, "가용 소스 그룹 변화 이후 목록", "list[str]|null",
              ("수집 세션",), ("실험 기록", "재현"), DataPlane.OBSERVABILITY),

    FieldSpec(DOMAIN_ID, "실행 회차가 속한 배포 도메인 식별자(핵심 코드 분기 키가 아니다)", "str",
              ("배포 프로파일",), ("실험 기록", "재현"), DataPlane.OBSERVABILITY),
    FieldSpec(STEP_INDEX, "실행 회차 안에서의 단계 순번", "int",
              ("실행 회차 진행",), ("실험 기록", "재현"), DataPlane.OBSERVABILITY),

    FieldSpec(MISSION_AUTONOMY, "링크가 끊긴 동안 이 임무 항목을 이어서 수행해도 되는가 —"
              " 발급자가 전달 시점에 선언하며 말단이 추론하지 않는다(AI-C-19)",
              "|".join(MISSION_AUTONOMY_VALUES),
              ("백엔드 명령 발급",), ("말단 임무 캐시",), DataPlane.TASK),
    FieldSpec(MISSION_ITEM_STATE, "임무 항목의 진행 상태. 결과(mission_status)와 다른 축이며"
              " INTERRUPTED는 프로세스 재시작으로 실행 주체를 잃은 것이지 실패가 아니다",
              "|".join(MISSION_ITEM_STATES),
              ("말단 임무 캐시",), ("운영자", "백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(MISSION_CACHE_REASON, "임무 전달의 수락·거부·복원·차단 사유. 통제 어휘이며"
              " ':' 뒤에 데이터가 붙는다",
              "|".join(MISSION_CACHE_REASONS),
              ("말단 임무 캐시",), ("운영자", "관측"), DataPlane.OBSERVABILITY),
    FieldSpec(ZONE_HANDOVER_REASON, "구역 전환 판단의 사유. 전환 '요청'과 실제 '진입'이 서로"
              " 다른 토큰이라 실패한 전환이 성공으로 보이지 않는다",
              "|".join(ZONE_HANDOVER_REASONS),
              ("말단 구역 전환 판단",), ("운영자", "네트워크 provider"), DataPlane.OBSERVABILITY),
    FieldSpec(ROBOT_ADAPTER_REASON, "말단 로봇 어댑터의 수락·거부·취소·긴급정지·임무 재개"
              " 사유. 거부 토큰은 실행 상태가 아니라 수락 결과다(AI-C-20)",
              "|".join(ROBOT_ADAPTER_REASONS),
              ("말단 로봇 어댑터",), ("운영자", "관측", "백엔드"), DataPlane.OBSERVABILITY),
    # --- 백엔드 통합데이터규약 v2 정렬 (2026-10-27) ----------------------
    FieldSpec(SESSION_ID, "생산 프로세스의 1회 기동 식별자(12자리 hex). 재기동을"
              " 구분해 순번이 되돌아간 것을 알아볼 수 있게 한다", "str",
              ("AI", "말단", "엣지"), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(EMITTED_AT, "처리 결과가 나온 시각. 데이터 시각(timestamp)과 다른 축이다",
              "str(ISO-8601 +09:00)", ("AI",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(INFER_MS, "모델이 계산한 시간만. 프레임 수신부터 결과까지의 전체 지연이"
              " 아니다 — 전체 지연은 전송·대기가 섞여 생산자가 분리할 수 없다", "float(ms)",
              ("AI",), ("백엔드", "가시화", "운영자"), DataPlane.TASK),
    FieldSpec(PRODUCER, "결과를 만든 주체 묶음(계층·종류·선택 여부·라벨)", "object",
              ("AI",), ("가시화", "백엔드"), DataPlane.TASK),
    FieldSpec(CAMERA_ID, "카메라 식별자. 메시지를 만든 주체(source_id)와 뜻이 다르므로"
              " 같은 이름을 쓰지 않는다", "str",
              ("말단", "엣지"), ("AI", "백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(MODEL, "그 결과를 낸 모델 이름. 비전 결과의 필수 칸이다", "str",
              ("AI",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(BBOX, "경계 상자 [x1, y1, x2, y2] 픽셀. 기준 해상도는 결과의 width·height",
              "list[float]", ("AI",), ("백엔드", "가시화"), DataPlane.TASK),

    # --- 작업 그래프·대시보드 -------------------------------------------
    FieldSpec(TASK_NODE_ID, "작업 그래프의 실행 단위 식별자. 물리 실행 노드"
              "(node_id)와 다른 축이며 같은 칸에 담지 않는다", "str",
              ("오케스트레이션",), ("가시화", "백엔드"), DataPlane.TASK),
    FieldSpec(TASK_NODE_STATE, "작업 노드의 런타임 상태. 가용성·결과와 다른 축이다",
              "|".join(TASK_NODE_STATES),
              ("오케스트레이션",), ("가시화", "백엔드"), DataPlane.TASK),
    FieldSpec(TASK_ATTEMPT, "같은 논리 작업의 재실행 회차. 원 노드는 1이고 회차마다"
              " 새 노드가 생겨 이전 회차 이력이 덮이지 않는다", "int",
              ("오케스트레이션",), ("가시화",), DataPlane.TASK),
    FieldSpec(ORIGIN_TASK_NODE_ID, "재실행 노드가 가리키는 원 노드. 최초 실행은 없음",
              "str", ("오케스트레이션",), ("가시화",), DataPlane.TASK),
    FieldSpec(PARALLEL_GROUP, "동시 실행 묶음 식별자. 같은 값이면 한 그룹으로 그린다",
              "str", ("오케스트레이션",), ("가시화",), DataPlane.TASK),
    FieldSpec(SERVICE_ID, "작업을 처리하는 추론 모델 서비스(Layer 2) 식별자."
              " 실행 가속기와 별도 칸으로 유지한다", "str",
              ("실행관리",), ("가시화", "백엔드"), DataPlane.TASK),
    FieldSpec(ACCELERATOR_INSTANCE_ID, "연산 가속기 **개체** 식별자. 태그(무엇을 할 수"
              " 있는가)와 달리 같은 종류의 가속기 여러 개를 구분한다", "str",
              ("실행 노드",), ("가시화", "운영자"), DataPlane.OBSERVABILITY),
    FieldSpec(ACCELERATOR_ATTACHMENT, "가속기 부착 형태. 벤더 enum 이 아닌 자유 문자열",
              "str", ("실행 노드 등록",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(EXTERNAL_REQUEST_ID, "외부 기능 요청 식별자. 백엔드가 발급하고 AI 는"
              " 받아 싣는다(AI-C-19)", "str",
              ("백엔드",), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(EXTERNAL_REQUEST_STAGE, "요청 처리 6단계 중 현재 위치",
              "|".join(EXTERNAL_REQUEST_STAGES),
              ("백엔드", "오케스트레이션"), ("가시화",), DataPlane.TASK),
    FieldSpec(EXTERNAL_REQUEST_REASON, "요청 발생 사유 구분",
              "|".join(EXTERNAL_REQUEST_REASONS),
              ("오케스트레이션",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(EXTERNAL_REQUEST_VERDICT, "재실행 결과에 대한 최종 판정",
              "|".join(EXTERNAL_REQUEST_VERDICTS),
              ("오케스트레이션",), ("가시화",), DataPlane.TASK),
    FieldSpec(DEPLOYMENT_VERSION, "수신된 SW 패키지 버전. 미수신이면 없음이며 0 이나"
              " 빈 문자열로 채우지 않는다", "str",
              ("백엔드",), ("실행관리", "가시화"), DataPlane.TASK),
    FieldSpec(PROGRESS_RATIO, "작업 노드 내부 진행 비율(0~1). 측정 수단이 없으면 없음",
              "float", ("실행 기능",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(TARGET_MEET_STATE, "지표의 목표 기준선 충족 여부. 미측정은 미달이 아니다",
              "|".join(TARGET_MEET_STATES),
              ("관측",), ("가시화", "운영자"), DataPlane.OBSERVABILITY),
    FieldSpec(FOCUS_REASON, "기준 노드가 그렇게 선정된 사유 토큰",
              "|".join(FOCUS_REASONS),
              ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(REGION_REASON, "화면 구역이 비어 있는 사유. 소스 미수신과 데이터 없음을"
              " 구분한다", "|".join(REGION_REASONS),
              ("관측",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(MISSION, "[B] 현재 미션 요약 묶음",
              "dict" if MISSION in ("mission", "focus", "board") else "list",
              ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(FOCUS, "[F·G·H] 기준 노드와 선정 사유 묶음",
              "dict" if FOCUS in ("mission", "focus", "board") else "list",
              ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(TASK_NODES, "[C] 작업 그래프 노드 목록",
              "dict" if TASK_NODES in ("mission", "focus", "board") else "list",
              ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(REFERENCE_EDGES, "[C] 분기·되풀이 참조 간선 목록. DAG 에 넣지 않는다",
              "dict" if REFERENCE_EDGES in ("mission", "focus", "board") else "list",
              ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(ACCELERATORS, "[B·E] Layer 1 가속기 개체 목록. 유휴여도 생략하지 않는다",
              "dict" if ACCELERATORS in ("mission", "focus", "board") else "list",
              ("하드웨어", "관측"), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(SERVICES, "[B·E·E′·F] Layer 2 서비스 목록. 배치 가속기를 병기한다",
              "dict" if SERVICES in ("mission", "focus", "board") else "list",
              ("실행관리", "관측"), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(BOARD, "[E] 보드 단위 자원(메모리·전력) 묶음",
              "dict" if BOARD in ("mission", "focus", "board") else "list",
              ("하드웨어", "관측"), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(VERDICTS, "[G] 노드별 판정 근거 3축 목록",
              "dict" if VERDICTS in ("mission", "focus", "board") else "list",
              ("판단",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(EVENTS, "[D] 사건 스트림. 노드별 필터는 화면이 한다",
              "dict" if EVENTS in ("mission", "focus", "board") else "list",
              ("AI 실행 기능",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(EXTERNAL_REQUESTS, "[I] 외부 기능 요청 목록. 서버 내부는 담지 않는다",
              "dict" if EXTERNAL_REQUESTS in ("mission", "focus", "board") else "list",
              ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(MODEL_ASSIGNMENTS, "모델 배정 결과 목록(고른 것과 탈락 사유)",
              "dict" if MODEL_ASSIGNMENTS in ("mission", "focus", "board") else "list",
              ("AI 배정",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(SOURCES, "소스별 수신 상태 목록. 미수신과 오래됨을 구분한다",
              "dict" if SOURCES in ("mission", "focus", "board") else "list",
              ("관측",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(REGIONS, "구역별 표시 가능 여부 목록",
              "dict" if REGIONS in ("mission", "focus", "board") else "list",
              ("관측",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(MISSION_ID, "사용자 미션 1건의 식별자. 작업 그래프·외부 요청·배정이 이것으로 묶인다",
              "str", ("백엔드", "가시화"), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(UTTERANCE_TEXT, "사용자가 준 자연어 명령 **원문**. 요약·번역본으로 대체하지 않는다",
              "str", ("가시화",), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(ACCEPTED_AT, "미션 접수 시각. 경과 시간은 이 값에서 화면이 계산한다",
              "iso8601", ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(FOCUS_PINNED, "기준 노드가 운영자 수동 고정인가(참) 자동 추종인가(거짓)",
              "bool", ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(NODE_TITLE, "작업 그래프 노드의 작업명",
              "str", ("생성 주체",), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(NODE_KIND, "노드 종류 라벨(sense/decide/act/verify/report 등). 분기 근거로 쓰지 않는다",
              "str", ("생성 주체",), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(TARGET_DEVICE_ID, "그 노드를 수행하는 장비. 가속기가 아니다",
              "str", ("생성 주체",), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(STARTED_AT, "노드 실행이 시작된 시각",
              "iso8601", ("실행 기능",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(STATE_CHANGED_AT, "노드 상태가 전이한 시각",
              "iso8601", ("실행 기능",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(ESTIMATED_COMPLETION_AT, "예상 완료 시각. 근거가 없으면 없음(0 을 넣지 않는다)",
              "iso8601", ("실행 기능",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(INPUT_COMMAND, "그 노드에 전달된 명령·지시문 원문. 자연어가 어떤 실행 단위가 됐는지 추적한다",
              "str", ("생성 주체",), ("가시화",), DataPlane.TASK),
    FieldSpec(REFERENCE_EDGE_KIND, "DAG 밖 참조 간선의 종류(branch/repeat). 선행 관계가 아니다",
              "str", ("생성 주체",), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(REFERENCE_EDGE_WHEN, "그 참조 간선이 성립하는 판정 결과",
              "str", ("생성 주체",), ("AI", "가시화"), DataPlane.TASK),
    FieldSpec(ACCELERATOR_KIND, "가속기 종류. 벤더 열거형이 아니라 등록 데이터다",
              "str", ("하드웨어",), ("AI", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(ACCELERATOR_VENDOR_LABEL, "화면 표시용 벤더 이름. 선택이나 분기 근거로 쓰지 않는다",
              "str", ("하드웨어",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(SERVICE_ROLE, "그 서비스가 맡은 역할 설명",
              "str", ("실행관리",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(MEASUREMENT, "값·단위·측정 시각 한 묶음. 값 칸이 없으면 **측정 없음**이다",
              "dict", ("관측",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(UTILIZATION, "가속기 사용률 측정 묶음(0~1)",
              "dict" if UTILIZATION not in ("power_trend", "measured_at", "requested_at", "source_status") else ("list" if UTILIZATION == "power_trend" else ("iso8601" if UTILIZATION.endswith("_at") else "str")),
              ("하드웨어",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(TEMPERATURE, "가속기 온도 측정 묶음",
              "dict" if TEMPERATURE not in ("power_trend", "measured_at", "requested_at", "source_status") else ("list" if TEMPERATURE == "power_trend" else ("iso8601" if TEMPERATURE.endswith("_at") else "str")),
              ("하드웨어",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(MEMORY_UTILIZATION, "보드 전체 메모리 사용률 측정 묶음",
              "dict" if MEMORY_UTILIZATION not in ("power_trend", "measured_at", "requested_at", "source_status") else ("list" if MEMORY_UTILIZATION == "power_trend" else ("iso8601" if MEMORY_UTILIZATION.endswith("_at") else "str")),
              ("하드웨어",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(POWER, "현재 소비 전력 측정 묶음",
              "dict" if POWER not in ("power_trend", "measured_at", "requested_at", "source_status") else ("list" if POWER == "power_trend" else ("iso8601" if POWER.endswith("_at") else "str")),
              ("하드웨어",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(POWER_TREND, "최근 구간 소비 전력 표본 목록. 빈 구간을 0 으로 메우지 않는다",
              "dict" if POWER_TREND not in ("power_trend", "measured_at", "requested_at", "source_status") else ("list" if POWER_TREND == "power_trend" else ("iso8601" if POWER_TREND.endswith("_at") else "str")),
              ("하드웨어",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(MEASURED_AT, "그 측정이 이뤄진 시각",
              "dict" if MEASURED_AT not in ("power_trend", "measured_at", "requested_at", "source_status") else ("list" if MEASURED_AT == "power_trend" else ("iso8601" if MEASURED_AT.endswith("_at") else "str")),
              ("관측",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(REQUESTED_AT, "외부 기능 요청을 발신한 시각",
              "dict" if REQUESTED_AT not in ("power_trend", "measured_at", "requested_at", "source_status") else ("list" if REQUESTED_AT == "power_trend" else ("iso8601" if REQUESTED_AT.endswith("_at") else "str")),
              ("오케스트레이션",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(SOURCE_STATUS, "생성 주체가 쓴 원본 상태 문자열. 표시 어휘로 환산한 뒤에도 남긴다",
              "dict" if SOURCE_STATUS not in ("power_trend", "measured_at", "requested_at", "source_status") else ("list" if SOURCE_STATUS == "power_trend" else ("iso8601" if SOURCE_STATUS.endswith("_at") else "str")),
              ("생성 주체",), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(INDICATOR_NAME, "성능 지표 이름. 산출 서비스·가속기를 함께 싣는다",
              "str", ("관측",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(CONDITION_ITEM_ID, "판정 조건 1개의 식별자. 집계가 아니라 항목으로 다룬다",
              "str", ("판단",), ("가시화", "운영자"), DataPlane.OBSERVABILITY),
    FieldSpec(CONDITION_SATISFIED, "그 조건의 충족·발생·정상 여부. 칸이 없으면 판정할 근거가 없다",
              "bool", ("판단",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(CONDITION_REASON, "그 조건을 그렇게 판정한 사유 토큰. 표시 문구는 화면이 만든다",
              "str", ("판단",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(ESCALATED_REQUEST_ID, "그 판정이 외부 기능 요청으로 승격됐을 때의 요청 식별자",
              "str", ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(EVENT_SEVERITY, "사건 등급. 유형(SDI 등)과 다른 축이다",
              "INFO|WARN|ERROR", ("AI 실행 기능",), ("백엔드", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(EVENT_KIND, "사건 유형. 등급과 섞지 않는다",
              "EXECUTION|EXTERNAL_REQUEST|RESOURCE", ("AI 실행 기능",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(EVENT_MESSAGE, "사건 내용 요약",
              "str", ("AI 실행 기능",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(OCCURRED_AT, "사건 발생 시각",
              "iso8601", ("AI 실행 기능",), ("백엔드", "가시화"), DataPlane.OBSERVABILITY),
    FieldSpec(SERVER_WORK_IS_OPAQUE, "외부 요청이 서버 처리 구간에 있는가. 내부 진척은 수신하지 않는다",
              "bool", ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(DEPLOYMENT_RECEIVED, "그 요청의 배포를 받았는가. 미수신을 null 버전으로 적지 않는다",
              "bool", ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(RE_EXECUTION_COUNT, "배포 적용 후 재실행한 횟수",
              "int", ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(STAGE_ENTERED_AT, "요청이 그 단계에 들어간 시각",
              "iso8601", ("오케스트레이션",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(ASSIGNMENT_REASON, "모델을 그 장치·임무에 배정했거나 탈락시킨 사유 토큰",
              "str", ("AI 배정",), ("가시화", "운영자"), DataPlane.OBSERVABILITY),
    FieldSpec(MODEL_REFERENCE, "모델 버전 하나를 가리키는 참조(model@version)",
              "str", ("AI 배정",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(SOURCE_LAYER, "그 소스가 속한 계층(L1/L2/L3/external/stream)",
              "str", ("관측",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(LAST_RECEIVED_AT, "그 소스에서 마지막으로 받은 시각. 칸이 없으면 한 번도 받지 않았다",
              "iso8601", ("관측",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(SOURCE_STALE, "받은 적은 있으나 보존 기한을 넘겼는가. 미수신과 다른 상태다",
              "bool", ("관측",), ("가시화",), DataPlane.OBSERVABILITY),
    FieldSpec(REGION_AVAILABLE, "화면 구역을 지금 표시할 수 있는가",
              "bool", ("관측",), ("가시화",), DataPlane.OBSERVABILITY),

    # 구역 공간 근거 융합 (AI-S-06, AI-S-08, AI-C-02)
    FieldSpec(QUANTITY_ID, "구역 공간 상태에서 융합되는 값 하나의 이름",
              "str", ("AI 공간 융합",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(SPATIAL_EVIDENCE_KIND, "공간 근거의 등록된 종류. 제품 이름이 아니다",
              "str", ("관측 provider", "관제 웹"), ("AI 공간 융합",), DataPlane.TASK),
    FieldSpec(EVIDENCE_TIER, "근거의 격(measured/declared/estimated). 정확도와 다른 축이다",
              "str", ("AI 공간 융합",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(ACCURACY_M, "그 관측이 스스로 선언한 1σ 정확도(m). null 은 모름이고 모름으로 남는다",
              "float|null", ("관측 provider", "관제 웹"), ("AI 공간 융합",), DataPlane.TASK),
    FieldSpec(FUSED_VALUE, "융합된 현장 로컬 값. 전역 좌표가 아니다(AI-C-02)",
              "list[float]", ("AI 공간 융합",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(DECIDED_BY, "그 값을 정한 규칙(사람 실측 덮어쓰기/역분산 융합/비가중 평균)",
              "str", ("AI 공간 융합",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(CONTRIBUTING_EVIDENCE_KINDS, "값을 움직인 근거 종류들",
              "list[str]", ("AI 공간 융합",), ("가시화",), DataPlane.TASK),
    FieldSpec(VALUE_CONFIRMED,
              "그 값을 확정으로 써도 되는가. 선언만으로는 확정되지 않는다(AI-S-08)",
              "bool", ("AI 공간 융합",), ("백엔드", "가시화", "운영자"), DataPlane.TASK),
    FieldSpec(UNCONFIRMED_REASON, "확정을 보류한 사유. 확정이면 null 이다",
              "str|null", ("AI 공간 융합",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(INDEPENDENT_SUPPORT_COUNT, "서로 독립인 지지의 수. 같은 원본 관측에서 나온 둘은 하나로 센다",
              "int", ("AI 공간 융합",), ("백엔드", "가시화"), DataPlane.TASK),
    FieldSpec(CONTRIBUTIONS, "각 근거가 값에 어떻게 들어갔는지의 내역",
              "list[dict]", ("AI 공간 융합",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(REJECTED_OBSERVATIONS, "융합에 넣지 못한 관측과 그 사유",
              "list[dict]", ("AI 공간 융합",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(CONTRIBUTION_ROLE, "한 근거가 값에서 맡은 역할",
              "str", ("AI 공간 융합",), ("가시화",), DataPlane.TASK),
    FieldSpec(CONTRIBUTION_WEIGHT, "역분산 가중치. 정확도 미선언 근거는 0 이다",
              "float", ("AI 공간 융합",), ("가시화",), DataPlane.TASK),
    FieldSpec(WITHOUT_HUMAN_VALUE, "사람 입력을 빼면 센서·선언만으로 무엇이었는가",
              "list[float]|null", ("AI 공간 융합",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(ENTERED_BY, "사람 입력 값을 넣은 사람",
              "str|null", ("관제 웹",), ("AI 공간 융합", "백엔드"), DataPlane.TASK),
    FieldSpec(ENTERED_AT, "사람 입력 값을 넣은 시각",
              "float|null", ("관제 웹",), ("AI 공간 융합", "백엔드"), DataPlane.TASK),
    FieldSpec(LOCAL_REDUCTION_REF, "절대 측위를 현장 로컬 좌표로 환산한 기준",
              "str|null", ("관측 provider",), ("AI 공간 융합",), DataPlane.TASK),
    FieldSpec(UNOBSERVED_EVIDENCE_KINDS, "등록됐으나 이번에 관측이 없는 근거 종류. 없음은 반대 근거가 아니다",
              "list[str]", ("AI 공간 융합",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(LEAVE_ONE_OUT, "한 출처를 빼면 값이 무엇이 되는가",
              "list[dict]", ("AI 공간 융합",), ("운영자",), DataPlane.TASK),
    FieldSpec(INFLUENCE_M, "그 출처를 뺐을 때 값이 움직인 거리(m)",
              "float|null", ("AI 공간 융합",), ("운영자",), DataPlane.TASK),

    # --- 이종 근거의 공통 계약·충분도 (AI-S-03/S-05/S-06) ---------------------
    FieldSpec(EVIDENCE_KIND, "그 근거가 어느 등록된 종류인가. 벤더·제품 이름이 아니다",
              "str", ("AI 인지", "AI 근거 계약"), ("가시화", "운영자", "백엔드"),
              DataPlane.TASK),
    FieldSpec(CLAIM, "그 근거가 가리키는 결론(개체 id·기종 이름·구역 값 이름)",
              "str", ("AI 근거 계약",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(CLAIM_SUBJECT, "그 근거들이 무엇에 대해 말하고 있는가(판정의 질문)",
              "str", ("AI 근거 계약",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(EVIDENCE_STRENGTH,
              "그 근거가 자기 결론을 얼마나 세게 지지하는가. 모델 confidence 와 다른 축",
              "float", ("AI 인지", "AI 근거 계약"), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(DISCRIMINATING,
              "그 종류가 결론을 가릴 수 있는가. 비식별 근거는 쌓여도 식별 근거를 못 뒤집는다",
              "bool", ("AI 근거 계약",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(REFUTES, "지지가 아니라 반박인가. 식별력 있는 반박만 후보를 배제한다",
              "bool", ("AI 인지", "AI 근거 계약"), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(DEPENDS_ON, "같은 원본 관측에서 나온 선행 근거. 중복과 독립을 가른다",
              "str|null", ("AI 근거 계약",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(OBSERVED_EVIDENCE_KINDS, "이번에 실제로 근거를 낸 종류",
              "list[str]", ("AI 근거 계약",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(UNAVAILABLE_EVIDENCE_KINDS,
              "제공자가 없어 미측정인 종류 → 사유. 오류가 아니라 비활성이다",
              "dict[str,str]", ("AI 근거 계약",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(RESOLUTION_REQUESTS,
              "무엇을 더 하면 풀리는지. 실제 실행은 백엔드·하드웨어가 한다",
              "list[str]", ("AI 근거 계약",), ("백엔드", "가시화", "운영자"),
              DataPlane.TASK),
    FieldSpec(SUFFICIENCY_REASON, "충분도 판정의 사유",
              "|".join(EVIDENCE_SUFFICIENCY_REASONS), ("AI 근거 계약",),
              ("가시화", "운영자"), DataPlane.TASK),

    # --- 가상환경 대역 자산 (AI-S-06, AI-C-08, AI-C-15) ----------------------
    FieldSpec(PROXY_ID, "관측된 객체를 대신 그릴 저장 자산의 식별자. null 은 대역 없음이고 정상이다",
              "str|null", ("AI 대역 선택",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(DEPICTS, "그 자산이 무엇을 묘사하는가(다국어 라벨). 표현 결정이 아니다",
              "dict[str,str]", ("대역 카탈로그",), ("가시화",), DataPlane.TASK),
    FieldSpec(STANDS_IN_FOR, "그 자산이 대신하는 종류 태그들. 개체 id 가 아니다",
              "list[str]", ("대역 카탈로그",), ("AI 대역 선택", "가시화"), DataPlane.TASK),
    FieldSpec(ASSET_KIND, "자산의 표현 종류. 카탈로그가 스스로 선언하는 어휘이고 벤더 열거형이 아니다",
              "str(카탈로그 선언 어휘)", ("대역 카탈로그",), ("가시화",), DataPlane.TASK),
    FieldSpec(ASSET_REF, "자산 뿌리 기준 상대 참조. 픽셀은 이 경로로 미디어 경로가 낸다(AI-C-08)",
              "str", ("대역 카탈로그",), ("가시화", "미디어 경로"), DataPlane.TASK),
    FieldSpec(ASSET_ORIGIN, "그 자산이 어디서 왔는가",
              "str", ("대역 카탈로그",), ("운영자",), DataPlane.TASK),
    FieldSpec(ASSET_LICENSE, "그 자산의 라이선스 선언. 모름은 \"unknown\" 으로 적는다",
              "str", ("대역 카탈로그",), ("운영자",), DataPlane.TASK),
    FieldSpec(ASSET_PRESENT, "자산 파일이 실제로 있는가. null 은 확인하지 못한 것이고 '없다' 가 아니다",
              "bool|null", ("AI 대역 선택",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(PROXY_EXTENT_M, "대역 자산이 묘사하는 실물의 가장 긴 변(m). null 은 미측정",
              "float|null", ("대역 카탈로그",), ("AI 대역 선택", "가시화"), DataPlane.TASK),
    FieldSpec(MEASURED_EXTENT_M, "관측이 실측한 그 객체의 가장 긴 변(m). null 은 미측정",
              "float|null", ("AI 인지",), ("AI 대역 선택", "가시화"), DataPlane.TASK),
    FieldSpec(SIZE_FIT_STATE, "선언 크기와 실측 크기의 비교 상태. 늘리지 않고 어긋남을 낸다",
              "|".join(SIZE_FIT_STATES), ("AI 대역 선택",), ("가시화", "운영자"),
              DataPlane.TASK),
    FieldSpec(SIZE_RATIO, "실측/선언 배율. 설명용 수치이고 적용 지시가 아니다",
              "float|null", ("AI 대역 선택",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(SIZE_TOLERANCE, "그 비교에 적용한 허용 배율",
              "float", ("AI 대역 선택",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(UNMEASURED_SIDE, "크기 비교에서 어느 쪽이 미측정인가",
              "declared_extent|measured_extent|both|null", ("AI 대역 선택",),
              ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(PROXY_STATE, "대역 선택의 상태. RESOLVED 만 모양을 말한다",
              "|".join(PROXY_STATES), ("AI 대역 선택",), ("가시화",), DataPlane.TASK),
    FieldSpec(PROXY_REASON, "그 상태의 사유 토큰",
              "|".join(PROXY_REASONS), ("AI 대역 선택",), ("가시화", "운영자"),
              DataPlane.TASK),
    FieldSpec(KIND_CLAIM_REASON, "종류 추정이 그 상태인 사유(추정기 어휘). 대역 사유와 다른 축",
              "str(추정기 어휘)", ("AI 기종 추정",), ("AI 대역 선택", "가시화"),
              DataPlane.TASK),
    FieldSpec(PROXY_REVISION, "그 대역 선택의 회차. 이전 선택을 덮지 않는다",
              "int", ("AI 대역 선택",), ("가시화",), DataPlane.TASK),
    FieldSpec(PROXY_ALTERNATIVES, "같은 종류를 대신할 수 있었던 다른 자산들",
              "list[str]", ("AI 대역 선택",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(UNFIT_PROXIES, "그 종류의 대역이지만 지금 쓸 수 없었던 자산 → 사유",
              "dict[str,str]", ("AI 대역 선택",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(SUPERSEDED_PROXY_ID, "이번 선택이 대체한 자산. 이력은 체인으로 남는다",
              "str|null", ("AI 대역 선택",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(SUPERSEDE_REASON, "왜 대체됐는가",
              "|".join(PROXY_SUPERSEDE_REASONS), ("AI 대역 선택",),
              ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(HEADING_DEG, "그 자리의 방향(도). null 은 미측정이고 0 도가 아니다",
              "float|null", ("AI 인지",), ("AI 대역 선택", "가시화"), DataPlane.TASK),
    FieldSpec(PROXY_POSITION, "대역을 세울 현장 로컬 자리(m). 전역 값은 이 칸에 담지 않는다",
              "list[float]|null", ("AI 대역 선택",), ("가시화",), DataPlane.TASK),
    FieldSpec(PLACEMENT_REFUSAL_REASON, "그 자리를 내지 못한 사유. 미관측과 거절을 구분한다",
              "|".join(PLACEMENT_REFUSAL_REASONS), ("AI 대역 선택",),
              ("가시화", "운영자"), DataPlane.TASK),
    # --- 탐지로 지은 점유 지도 (AI-S-06, AI-S-08, AI-C-02) --------------------
    FieldSpec(MAP_CELL_ID, "격자 칸 하나의 식별자(층 로컬 격자 인덱스). 전역 좌표가 아니다",
              "str", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(CELL_SIZE_M, "격자 한 칸의 한 변(m). 칸 중심 좌표의 양자화 오차 하한을 정한다",
              "float", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(MAP_REGION_ID, "질의한 사각 영역의 식별자. 선언된 구역 목록(region_id)과 다른 축",
              "str", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(MAP_CELLS, "영역·지도 한 장이 싣는 칸들. 관측되지 않은 칸을 생략하지 않는다",
              "list[dict]", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(CELL_STATE, "칸 하나를 읽은 결과. UNKNOWN 과 FREE 는 다른 상태다",
              "|".join(CELL_STATES), ("AI 지도층",), ("가시화", "운영자", "백엔드"),
              DataPlane.TASK),
    FieldSpec(MAP_AUTHORITY, "이 지도가 어느 격의 값을 내고 있는가. 전역 승격은 datum 을 통과해야 한다",
              "|".join(MAP_AUTHORITIES), ("AI 지도층",), ("가시화", "백엔드"),
              DataPlane.TASK),
    FieldSpec(MASS_OCCUPIED, "점유 주장에 걸린 Dempster 질량",
              "float", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(MASS_FREE, "자유 주장에 걸린 Dempster 질량. 광선을 가진 출처나 선언만 올릴 수 있다",
              "float", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(MASS_UNKNOWN,
              "무지에 남은 질량 m(Ω). 아무도 보지 않은 칸은 1 이고 0 이 기본값이 아니다",
              "float", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(MASS_CONFLICT,
              "결합이 버린 몫의 누적(감사 기록). 0 으로 적으면 '안 봤다' 와 구분되지 않는다",
              "float", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(TWIN_MAP_CLAIM, "한 관측이 칸에 대해 한 말. 닫힌 두 값이고 그 닫힘이 규칙으로 쓰인다",
              "|".join(TWIN_MAP_CLAIMS), ("AI 인지", "AI 지도층"),
              ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(PRIOR_CLAIM, "사전정보가 이 칸에 대해 한 말. 읽기값과 분리해 싣는다(AI-S-08)",
              "occupied|free|null", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(OBSERVED_SUPPORT_COUNT,
              "관측 격의 독립 지지 수(frame_ref 단위). 0 이면 사전정보가 무엇을 말하든 UNKNOWN 이다",
              "int", ("AI 지도층",), ("가시화", "운영자", "백엔드"), DataPlane.TASK),
    FieldSpec(PRIOR_SUPPORT_COUNT, "사전정보 격 기여 수. 혼자서는 어떤 칸도 주장하지 못한다",
              "int", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(NEVER_OBSERVED,
              "관측 격 근거가 한 번도 닿지 않았는가. 낡음(stale)과 다른 사실이고 대응이 다르다",
              "bool", ("AI 지도층",), ("가시화", "운영자", "백엔드"), DataPlane.TASK),
    FieldSpec(LAST_OBSERVED_AT,
              "관측 격 근거가 마지막으로 닿은 시각(observed_at 의 집계). null 은 미관측이고 0 이 아니다",
              "float|null", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(OBSERVATION_KIND, "그 관측이 어느 등록된 종류인가. 벤더·제품 이름이 아니다",
              "str(등록 어휘)", ("AI 인지", "AI 지도층"), ("가시화", "운영자"),
              DataPlane.TASK),
    FieldSpec(APPLIED_STRENGTH,
              "자세·노후화 할인을 다 적용한 뒤 융합에 들어간 세기. 할인 전 값은 evidence_strength",
              "float", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(POSE_QUALITY,
              "그 관측이 통과한 카메라 자세의 품질 등급. pose_source(방법)와 다른 축",
              "|".join(POSE_QUALITIES), ("하드웨어 선언", "엣지 보정"),
              ("AI 지도층", "가시화"), DataPlane.TASK),
    FieldSpec(REJECTION_DETAIL, "거절 사유 토큰 뒤의 부연. 사유 자체는 rejection_reason 이다",
              "str", ("AI 지도층",), ("운영자",), DataPlane.TASK),
    FieldSpec(OCCUPANCY_INFLUENCE,
              "그 출처를 빼면 점유 질량이 움직인 양(부호 있음, 무차원). influence_m 과 단위가 다르다",
              "float", ("AI 지도층",), ("운영자",), DataPlane.TASK),
    FieldSpec(TOTAL_CELL_COUNT, "요약한 영역이 건드리는 칸의 수",
              "int", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(UNKNOWN_CELL_COUNT, "봤지만 주장이 서지 않은 칸의 수",
              "int", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(FREE_CELL_COUNT, "비었다는 주장이 선 칸의 수",
              "int", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(OCCUPIED_CELL_COUNT, "점유 주장이 선 칸의 수",
              "int", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(DISPUTED_CELL_COUNT, "봤고 서로 다르게 본 칸의 수",
              "int", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(NEVER_OBSERVED_CELL_COUNT,
              "관측이 한 번도 닿지 않은 칸의 수. unknown_cell_count 와 따로 센다",
              "int", ("AI 지도층",), ("가시화", "운영자", "백엔드"), DataPlane.TASK),
    FieldSpec(STALE_CELL_COUNT, "관측이 있었으나 지금을 받치기에 낡은 칸의 수",
              "int", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(DATUM_ID,
              "현장 로컬↔전역 변환(site datum)의 식별자. null 은 datum 없음이고 정상 상태다",
              "str|null", ("배포 선언", "운영자"), ("AI 지도층", "가시화", "백엔드"),
              DataPlane.TASK),
    FieldSpec(DATUM_SOURCE, "그 datum 이 어디서 왔는가. 출처가 다르면 품질이 전혀 다르다",
              "str", ("배포 선언", "운영자"), ("AI 지도층", "운영자"), DataPlane.TASK),
    FieldSpec(LOCAL_POSITION,
              "현장 로컬 미터 자리. 전역 값은 이 칸에 담지 않는다(AI-C-02). 전역 응답에서는"
              " 그 전역 값이 유도된 재료를 든다",
              "list[float]|null", ("AI 지도층", "AI 인지"), ("가시화", "백엔드"),
              DataPlane.TASK),
    FieldSpec(GLOBAL_POSITION,
              "선언된 datum 을 통과해 유도한 전역 자리. 미검증·정확도 미선언 datum 으로는"
              " 채워지지 않고 사유만 나간다",
              "list[float]|null", ("AI 지도층",), ("가시화", "백엔드"), DataPlane.TASK),
    FieldSpec(DERIVED_FROM_FRAME, "local_position 이 어느 로컬 프레임의 값인가",
              "str|null", ("AI 지도층",), ("가시화", "백엔드"), DataPlane.TASK),
    FieldSpec(ACCURACY_LIMITED_BY,
              "그 자리의 정확도를 지배한 축. 전역 값은 datum 보다 좋을 수 없다",
              "|".join(ACCURACY_LIMITS), ("AI 지도층",), ("가시화", "백엔드", "운영자"),
              DataPlane.TASK),
    FieldSpec(FRAME_REFUSAL_REASON,
              "요구된 프레임으로 값을 내지 못한 사유. 오류가 아니라 축소다(AI-C-05)",
              "|".join(FRAME_REFUSAL_REASONS) + "|null", ("AI 지도층",),
              ("가시화", "백엔드", "운영자"), DataPlane.TASK),
    FieldSpec(PERSISTENCE_BELIEF, "그 요소가 아직 거기 있다고 믿는 정도",
              "float", ("AI 지도층",), ("가시화", "운영자", "백엔드"), DataPlane.TASK),
    FieldSpec(SURVIVAL_PRIOR,
              "관측을 세지 않은 순수 생존 사전확률. 믿음과 나란히 싣어 '시간만 흘렀다' 를 가른다",
              "float", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(SIGHTING_COUNT, "봤다(y=1)는 보고의 수",
              "int", ("AI 인지",), ("AI 지도층", "가시화", "운영자"), DataPlane.TASK),
    FieldSpec(NEGATIVE_REPORT_COUNT,
              "봤는데 없었다(y=0)는 보고의 수. 보지 않은 것은 어느 쪽에도 세지 않는다",
              "int", ("AI 인지",), ("AI 지도층", "가시화", "운영자"), DataPlane.TASK),
    FieldSpec(LAST_SIGHTING_AT,
              "마지막으로 본 시각. last_observed_at 과 같은 칸에 담지 않는다 —"
              " 음성 보고도 관측이다",
              "float|null", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(LAST_REPORT_AT, "종류를 가리지 않은 마지막 보고 시각(양성·음성 모두)",
              "float|null", ("AI 지도층",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(PERSISTENCE_EXPLAINED_BY, "그 믿음이 무엇 때문에 그런가",
              "|".join(PERSISTENCE_EXPLANATIONS), ("AI 지도층",),
              ("가시화", "운영자"), DataPlane.TASK),
    # --- 상황 변화 기반 재계획 (AI-B-12, AI-B-14) ---------------------------
    FieldSpec(CHANGE_KIND,
              "무엇이 달라졌는가. 등록된 변화 종류이며 도메인 이름이 아니다",
              "|".join(SITUATION_CHANGE_KINDS) + "|(등록 확장)",
              ("백엔드", "AI 인지", "운영자"), ("AI 계획", "가시화"), DataPlane.TASK),
    FieldSpec(CHANGE_SUBJECT,
              "그 변화가 가리키는 대상(자리 id·capability kind·subtask_id). 종류별로"
              " 칸을 늘리지 않는다",
              "str", ("백엔드", "AI 인지", "운영자"), ("AI 계획", "가시화"), DataPlane.TASK),
    FieldSpec(GRAPH_REVISION,
              "그래프 개정 번호. 재계획은 앞 개정을 덮지 않고 번호를 올린다(AI-B-12)",
              "int", ("AI 계획",), ("가시화", "운영자", "백엔드"), DataPlane.TASK),
    FieldSpec(PARENT_GRAPH_REVISION, "이 그래프가 갈라져 나온 개정. 최초 개정은 null",
              "int|null", ("AI 계획",), ("가시화", "운영자", "백엔드"), DataPlane.TASK),
    FieldSpec(NODE_LINEAGE,
              "이 개정에서 그 노드가 새것인가 그대로인가 밀려났는가."
              " superseded 는 삭제가 아니다",
              "|".join(NODE_LINEAGES), ("AI 계획",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(NODE_ROLE, "노드의 문법상 역할. BPMN 의 모양만 빌렸고 런타임은 쓰지 않는다",
              "|".join(NODE_ROLES), ("AI 계획",), ("가시화",), DataPlane.TASK),
    FieldSpec(INSERTED_BY, "그 노드를 끼워 넣게 만든 변화. 선언 노드는 null",
              "str|null", ("AI 계획",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(VISIT_TARGET,
              "그 단계가 가는 자리의 식별자. 좌표가 아니다 — 자리의 좌표와 그리기는"
              " 가시화 몫이다(AI-C-19)",
              "str|null", ("배포 선언", "AI 계획"), ("가시화", "백엔드"), DataPlane.TASK),
    FieldSpec(VISIT_ORDER,
              "그래프 순서를 따라 방문하게 되는 자리들의 순서. 그래프가 바뀌면 같이 바뀐다",
              "list[dict]", ("AI 계획",), ("가시화", "백엔드", "운영자"), DataPlane.TASK),
    FieldSpec(BRANCH_NAME, "분기 하나의 이름. 표시 문구는 화면이 만든다",
              "str", ("AI 계획",), ("가시화",), DataPlane.TASK),
    FieldSpec(BRANCH_CONDITION,
              "그 분기가 성립하는 조건(선언된 사실 이름). 판정은 호출자의 세계 모델이 한다",
              "str", ("AI 계획",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(DECISION_QUESTION, "분기 노드가 묻는 질문. 분기 쌍을 코드에 박지 않는다",
              "str|null", ("배포 선언",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(REPLAN_REASON,
              "재계획이 왜 그렇게 끝났는가. 바뀌지 않은 경우도 사유로 설명된다(AI-C-05)",
              "|".join(REPLAN_REASONS), ("AI 계획",), ("가시화", "운영자", "백엔드"),
              DataPlane.TASK),
    FieldSpec(INSERTION_REFUSAL_REASON, "끼워 넣기를 거부한 사유. 거부는 오류가 아니라 결과다",
              "|".join(INSERTION_REFUSAL_REASONS), ("AI 계획",), ("가시화", "운영자"),
              DataPlane.TASK),
    FieldSpec(REQUESTED_CAPABILITY,
              "거부된 단계가 요구한 capability 이름. 외부 개발 요청의 재료다(AI-B-13)",
              "str", ("AI 계획",), ("백엔드", "가시화", "운영자"), DataPlane.TASK),
    FieldSpec(ATTEMPT_INDEX, "재실행 회차. 원 노드는 1이고 회차는 새 노드로 쌓인다",
              "int", ("AI 계획",), ("가시화", "운영자"), DataPlane.TASK),
    FieldSpec(ORIGIN_SUBTASK_ID, "재실행 노드가 가리키는 원 노드. 원 노드는 null",
              "str|null", ("AI 계획",), ("가시화", "운영자"), DataPlane.TASK),

    # 측정값의 출처와 계측 지점 (2026-11-03, AI-O-05)
    FieldSpec(MEASUREMENT_SOURCE,
              "그 측정 1건이 실측인지 선언인지, 또는 재려 했으나 못 얻었는지. "
              "값 칸의 유무와 다른 축이고 칸이 없으면 아무도 채우지 않은 자리다",
              "measured|declared|unavailable",
              ("관측",), ("가시화", "운영자", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(HOST_PROBE_ID,
              "그 가속기 개체·보드를 재는 계측 지점 id. 선언이 지목하며 칸이 없으면 아무도 재지 않는다",
              "str", ("하드웨어", "관측"), ("가시화", "AI"), DataPlane.OBSERVABILITY),
    FieldSpec(HOST_PROBE_STATUS,
              "계측 지점별 상태 사유 토큰('<probe>.<slot>' → 사유). 관측 실패를 "
              "응답 중단이 아니라 사유로 남긴다(AI-O-01)",
              "dict", ("관측",), ("가시화", "운영자"), DataPlane.OBSERVABILITY),
)

DATA_DICTIONARY: dict[str, FieldSpec] = {entry.name: entry for entry in _ENTRIES}


class UnknownFieldError(KeyError):
    """A payload used a name that the dictionary does not define."""


def spec_for(name: str) -> FieldSpec:
    try:
        return DATA_DICTIONARY[name]
    except KeyError as exc:
        raise UnknownFieldError(name) from exc


def unknown_fields(payload: dict) -> tuple[str, ...]:
    """Names in `payload` that are not in the dictionary.

    Producers call this in tests rather than at runtime: the point is to
    catch a new ad-hoc name at development time, not to reject data in
    the field (AI-C-01은 이름 통일 규약이지 런타임 검증기가 아니다).
    """
    return tuple(name for name in payload if name not in DATA_DICTIONARY)


def assert_known(payload: dict) -> dict:
    missing = unknown_fields(payload)
    if missing:
        raise UnknownFieldError(f"undocumented field names: {list(missing)}")
    return payload


def fields_on_plane(plane: DataPlane) -> tuple[str, ...]:
    return tuple(name for name, entry in DATA_DICTIONARY.items() if entry.plane is plane)
