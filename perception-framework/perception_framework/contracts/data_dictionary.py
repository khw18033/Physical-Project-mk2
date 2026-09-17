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

from perception_framework.common.data_plane import DataPlane


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
#: (docs/ai/design/capability-ui-orchestration-plan.md §3-2).
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
    FieldSpec(LINK_POSTURE, "링크 품질에 따른 현재 실행 태세(전송·오버레이 상태와 별개)", "remote_ok|reducing|local_only",
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
