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

from ai_framework.common.data_plane import DataPlane


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
CAPABILITY_KIND = "capability_kind"
PROVIDER_ID = "provider_id"
CLUSTER_ID = "cluster_id"
PEER_ID = "peer_id"

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
