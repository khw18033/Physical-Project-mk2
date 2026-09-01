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

# --- 환경 구조 추정 (AI-E-05) ------------------------------------------------
MAP_ELEMENT_ID = "map_element_id"
STRUCTURE_UNCERTAINTY = "structure_uncertainty"
ANCHOR_ID = "anchor_id"

# --- 링크 품질 (AI-N-03) -----------------------------------------------------
LINK_QUALITY = "link_quality"
LINK_POSTURE = "link_posture"

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


# --- 관측 커버리지·사각 (AI-E-05, AI-S-03) -----------------------------------
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
    FieldSpec(COORDINATE_FRAME, "공간 값의 기준 좌표계", "IMAGE|CAMERA_LOCAL|GLOBAL",
              ("인지",), ("디지털트윈", "가시화"), DataPlane.TASK),

    FieldSpec(CAPABILITY_STATE_BEFORE, "상태 변화 이전의 기능 상태", "ACTIVE|DEGRADED|DISABLED",
              ("실행관리",), ("관측", "백엔드"), DataPlane.OBSERVABILITY),
    FieldSpec(CAPABILITY_STATE_AFTER, "상태 변화 이후의 기능 상태", "ACTIVE|DEGRADED|DISABLED",
              ("실행관리",), ("관측", "백엔드"), DataPlane.OBSERVABILITY),
    FieldSpec(STATE_CHANGE_REASON, "기능 상태가 바뀐 사유", "str",
              ("실행관리",), ("관측", "운영자"), DataPlane.OBSERVABILITY),

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
