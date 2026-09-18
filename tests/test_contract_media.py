"""미디어 헤더·탐지 초안 규격 — 인프라 없이 도는 규격 단위 확인(Phase 4 단계 1).

**규격이 코드보다 먼저다.** 여기서 못 박는 것:

- `media-header.schema.json` 양성 2 · 음성 4 — 필수 누락·타입 오류·`frame_ref.capture_timestamp` `+0900`은
  거부되고, **모르는 `encoding`(`av1`)은 통과한다**(enum 이 아님을 못 박는 반대 축 — 음성 대조 M5의 규격판).
- `frame_ref` 안쪽 추가 필드는 거부된다 — 참조 규격의 `additionalProperties: false` 예외(README).
- `detections.schema.json` 초안 — `alignment` 없는 메시지도 통과(선택 + 기본 의미 unaligned), `origin.tier` 에
  `server` 가 `$comment` 에 있고, 어휘 필드에 `enum` 이 없다(제약 10).
- `frame-reference.schema.json` **구조 무개정** — 필드 5·필수 3·`additionalProperties:false` 그대로, description 만 바뀜.
- 파일 간 `$ref` 가 **레지스트리로** 해석되고(결정 12), 레지스트리에 없으면 네트워크로 가지 않고 실패한다.
  `object-reference.schema.json` 도 같은 경로로 해석된다 — Phase 7 이 그대로 쓴다.
- `contracts.observation_hints()` 27 → 22 검산이 그대로다(새 규격 둘은 `payload/` 밖이라 C층 대상이 아니다).

implements: BE-C-03 (frame_ref 규격 확정·$ref 레지스트리), BE-T-07 (미디어 헤더 규격)
tests: 미디어 헤더 양성/음성 · 모르는 encoding 통과 · frame_ref 닫힘 · 탐지 초안 · 구조 무개정 · 레지스트리 해석
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import contracts, settings
from backend.ingest import envelope

EXAMPLES = settings.contracts_dir() / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _errors(validator, message) -> list:
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in validator.iter_errors(message)]


@pytest.fixture(scope="module")
def media_validator():
    return envelope.contract_validator("media-header.schema.json")


@pytest.fixture(scope="module")
def detections_validator():
    return envelope.contract_validator("detections.schema.json")


# ── 미디어 헤더: 양성 ────────────────────────────────────────────────────────


def test_media_header_valid(media_validator) -> None:
    assert _errors(media_validator, _load("media-header-valid.json")) == []


def test_media_header_unknown_encoding_passes(media_validator) -> None:
    """M5(규격판): `encoding: "av1"` 이 통과한다 — 값 어휘를 보지 않는다. 헤더 바깥의 추가 필드도 통과한다."""
    message = _load("media-header-valid-unknown-encoding.json")
    assert message["encoding"] == "av1" and "producer_extra" in message
    assert _errors(media_validator, message) == []


# ── 미디어 헤더: 음성 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fixture, expect_in_error",
    [
        ("media-header-invalid-missing-encoding.json", "'encoding' is a required property"),
        ("media-header-invalid-keyframe-type.json", "keyframe: 'true' is not of type 'boolean'"),
        ("media-header-invalid-timestamp-offset.json", "frame_ref/capture_timestamp: '2026-09-18T12:00:00+0900' is not a 'date-time'"),
        ("media-header-invalid-frame-ref-extra.json", "frame_ref: Additional properties are not allowed ('rotation_deg' was unexpected)"),
    ],
)
def test_media_header_invalid_rejected(media_validator, fixture: str, expect_in_error: str) -> None:
    """필수 누락 · 타입 오류 · `+0900` · frame_ref 안쪽 추가 필드 — 넷 다 실제로 거부되고 사유가 정확하다.

    `+0900` 거부는 `$ref` 로 끌어온 `frame-reference.schema.json` 의 `format: date-time` 이 포맷 검사기·
    레지스트리와 함께 실제로 동작한다는 뜻이다 — 이것이 무력하면 공통 헤더 검증도 무력한 것이다.
    """
    errors = _errors(media_validator, _load(fixture))
    assert errors, f"{fixture} 가 거부되지 않았다"
    assert any(expect_in_error in e for e in errors), errors


def test_media_header_required_set_and_no_enum() -> None:
    """필수 5(`frame_ref`·`encoding`·`keyframe`·`width`·`height`) · `frame_ref` 는 `$ref`(평면 아님) · 어휘 필드에 enum 없음."""
    schema = json.loads((settings.contracts_dir() / "media-header.schema.json").read_text(encoding="utf-8"))
    assert set(schema["required"]) == {"frame_ref", "encoding", "keyframe", "width", "height"}
    assert schema["properties"]["frame_ref"]["$ref"] == "frame-reference.schema.json"
    for field in ("encoding", "codec"):
        assert "enum" not in schema["properties"][field], field
        assert "$comment" in schema["properties"][field], field
    assert schema.get("additionalProperties") is not False
    assert "페이로드는 열지 않는다" in schema["$comment"]


# ── 탐지 초안 ────────────────────────────────────────────────────────────────


def test_detections_draft_valid(detections_validator) -> None:
    assert _errors(detections_validator, _load("detections-draft-valid.json")) == []


def test_detections_draft_without_alignment_passes(detections_validator) -> None:
    """`alignment` 는 선택이다 — 없으면 뷰어가 unaligned 로 취급한다(결정 3 fail-safe). 거부가 아니다."""
    message = _load("detections-draft-valid-no-alignment.json")
    assert "alignment" not in message and "frame_ref" not in message
    assert _errors(detections_validator, message) == []


def test_detections_draft_shape_and_vocab_not_enum() -> None:
    """메시지 단위 `alignment`·`origin{tier,kind}`·`coord` 가 있고, `tier` 에 `server` 가 적혀 있으며, 어휘는 enum 이 아니다."""
    schema = json.loads((settings.contracts_dir() / "detections.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    assert "alignment" in props and "alignment" not in schema["required"]
    assert set(props["origin"]["required"]) == {"tier", "kind"}
    assert "server" in props["origin"]["properties"]["tier"]["$comment"]
    assert "origin_kind" in props["origin"]["properties"]["kind"]["$comment"], "공통 헤더 origin_kind 와 다른 축임을 적어야 한다"
    assert set(props["coord"]["required"]) == {"normalized", "origin", "ref_width", "ref_height"}
    assert "top-left" in props["coord"]["properties"]["origin"]["$comment"]
    for spec in (props["alignment"], props["origin"]["properties"]["tier"], props["origin"]["properties"]["kind"],
                 props["coord"]["properties"]["origin"]):
        assert "enum" not in spec
    box = props["boxes"]["items"]
    assert "source" not in box["properties"], "박스 단위 source 는 버렸다 — 출처는 메시지 단위 origin"
    assert "초안" in schema["$comment"]


def test_detections_draft_rejects_bad_box(detections_validator) -> None:
    """초안이라도 검증기는 돈다 — 박스에 `label` 이 없거나 `coord` 가 없으면 거부."""
    message = _load("detections-draft-valid.json")
    del message["boxes"][0]["label"]
    assert any("label" in e for e in _errors(detections_validator, message))
    message = _load("detections-draft-valid.json")
    del message["coord"]
    assert any("'coord' is a required property" in e for e in _errors(detections_validator, message))


# ── frame-reference: 구조 무개정 ─────────────────────────────────────────────


def test_frame_reference_structure_unchanged_description_updated() -> None:
    """결정 2 — 구조(필드·필수·additionalProperties)는 그대로, description 만 `capture_timestamp` 뜻으로 바뀌었다."""
    schema = json.loads((settings.contracts_dir() / "frame-reference.schema.json").read_text(encoding="utf-8"))
    assert set(schema["properties"]) == {"source_id", "capture_timestamp", "sequence_id", "frame_id", "time_sync_state"}
    assert schema["required"] == ["source_id", "capture_timestamp", "sequence_id"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["capture_timestamp"]["type"] == "string"
    assert schema["properties"]["capture_timestamp"]["format"] == "date-time"
    assert "촬영 시각이 아니다" in schema["properties"]["capture_timestamp"]["description"]
    assert "액세스 유닛 재조립" in schema["description"]
    assert "디코드 시점에 단 한 번" not in schema["description"]


# ── $ref 레지스트리 ──────────────────────────────────────────────────────────


def test_registry_resolves_object_reference_like_media_header() -> None:
    """`object-reference.schema.json` 도 같은 레지스트리로 `frame_ref` 를 해석한다 — Phase 7 이 이 경로를 그대로 쓴다."""
    validator = envelope.contract_validator("object-reference.schema.json")
    good = {
        "object_id": "obj-1", "zone_local_track_id": "zoneA-track-1", "zone_id": "zoneA",
        "first_seen": "2026-09-18T12:00:00+09:00", "last_seen": "2026-09-18T12:00:01+09:00",
        "frame_ref": {"source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00.123+09:00", "sequence_id": 1},
    }
    assert _errors(validator, good) == []
    bad = dict(good, frame_ref={"source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00+0900", "sequence_id": 1})
    assert any("frame_ref/capture_timestamp" in e for e in _errors(validator, bad))


def test_registry_has_every_schema_by_id() -> None:
    registry = envelope.schema_registry()
    for path in settings.contracts_dir().rglob("*.schema.json"):
        schema_id = json.loads(path.read_text(encoding="utf-8"))["$id"]
        assert registry.get(schema_id) is not None, f"{path.name} 이 레지스트리에 없다"


def test_unregistered_ref_fails_without_network(tmp_path: Path, monkeypatch) -> None:
    """레지스트리에 `frame-reference` 가 없으면 `$id` URL 로 가져오려 하지 않고 검증 시점에 실패한다(결정 12)."""
    contracts_dir = tmp_path / "common"
    contracts_dir.mkdir()
    src = settings.contracts_dir() / "media-header.schema.json"
    (contracts_dir / "media-header.schema.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("MK2_CONTRACTS_DIR", str(contracts_dir))
    envelope.reset_validators_for_tests()
    contracts.reset_cache()
    try:
        validator = envelope.contract_validator("media-header.schema.json")
        with pytest.raises(Exception) as excinfo:
            validator.is_valid(_load("media-header-valid.json"))
        assert "Unresolvable" in type(excinfo.value).__name__ or "Referencing" in type(excinfo.value).__name__, type(excinfo.value)
    finally:
        monkeypatch.delenv("MK2_CONTRACTS_DIR", raising=False)
        envelope.reset_validators_for_tests()
        contracts.reset_cache()


def test_contract_validator_is_cached() -> None:
    """프레임마다 검증기를 새로 만들지 않는다 — 같은 이름은 같은 객체."""
    a = envelope.contract_validator("media-header.schema.json")
    b = envelope.contract_validator("media-header.schema.json")
    assert a is b


def test_new_schemas_do_not_disturb_c_layer_hints() -> None:
    """DoD 1-1b — 새 규격 둘은 `payload/` 밖이라 타입 판별·힌트 검산(22)에 영향이 없다."""
    assert "media-header" not in contracts.known_entity_types()
    grouped = contracts.hint_items_by_kind()
    assert sum(len(v) for v in grouped.values()) == 22
    assert len(contracts.observation_hints()) == 27
