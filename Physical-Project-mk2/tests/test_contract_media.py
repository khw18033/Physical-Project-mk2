"""미디어 헤더·탐지 초안 규격 — 인프라 없이 도는 규격 단위 확인(Phase 4 단계 1).

**규격이 코드보다 먼저다.** 여기서 못 박는 것:

- `media-header.schema.json`(v2 프레임 헤더, 통합데이터규약 §3-5) 양성 3 · 음성 3 — 필수 누락·타입 오류·`timestamp`
  `+0900`은 거부되고, **모르는 `encoding`(`av1`)은 통과한다**(enum 이 아님을 못 박는 반대 축 — 음성 대조 M5의 규격판).
  H.264 면 `keyframe`·`codec` 필수(if/then), JPEG 는 둘 다 없어도 된다. 공통 머리 칸은 `message.schema.json` 을 칸마다 `$ref`.
- 과도기 v1 헤더(`media-header.v1.schema.json`)는 옛 모양 그대로 — `frame_ref` 안쪽 추가 필드는 거부된다
  (참조 규격의 `additionalProperties: false` 예외, README). 단계 5 에서 v1 파일 둘과 함께 지운다.
- `detections.schema.json` 초안(§3-6) — `alignment` 없는 메시지도 통과(선택 + 기본 의미 unaligned), `producer.tier` 에
  `server` 가 `$comment` 에 있고, 어휘 필드에 `enum` 이 없다(제약 10). 검출은 `bbox [x1,y1,x2,y2]` 픽셀 + `label`.
- `frame-reference.schema.json` v2 — 필드 3·필수 3(`camera_id`·`sequence_id`·`timestamp`)·`additionalProperties:false`.
- 파일 간 `$ref` 가 **레지스트리로** 해석되고(결정 12), 레지스트리에 없으면 네트워크로 가지 않고 실패한다.
  `object-reference.schema.json` 도 같은 경로로 해석된다 — Phase 7 이 그대로 쓴다.
- `contracts.observation_hints()` 27 → 22 검산이 그대로다(새 규격 둘은 `payload/` 밖이라 C층 대상이 아니다).

implements: BE-C-03 (frame_ref 규격 확정·$ref 레지스트리), BE-T-07 (미디어 헤더 규격)
tests: 미디어 헤더 양성/음성 · 모르는 encoding 통과 · v1 헤더(과도기) · frame_ref 닫힘 · 탐지 초안 · frame_ref v2 구조 · 레지스트리 해석
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
def media_validator_v1():
    return envelope.contract_validator("media-header.v1.schema.json")


@pytest.fixture(scope="module")
def detections_validator():
    return envelope.contract_validator("detections.schema.json")


# ── 미디어 헤더: 양성 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture", ["media-header-valid.json", "media-header-valid-jpeg.json"])
def test_media_header_valid(media_validator, fixture: str) -> None:
    assert _errors(media_validator, _load(fixture)) == []


def test_media_header_jpeg_without_keyframe_and_h264_requires_both(media_validator) -> None:
    """JPEG 는 keyframe·codec 이 없어도 통과, H.264 는 둘 다 필수(if/then)."""
    jpeg = _load("media-header-valid-jpeg.json")
    assert "keyframe" not in jpeg and "codec" not in jpeg
    h264 = _load("media-header-valid.json")
    for field in ("keyframe", "codec"):
        broken = {k: v for k, v in h264.items() if k != field}
        assert any(f"'{field}' is a required property" in e for e in _errors(media_validator, broken)), field
    as_jpeg = dict({k: v for k, v in h264.items() if k not in ("keyframe", "codec")}, encoding="jpeg")
    assert _errors(media_validator, as_jpeg) == []


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
        ("media-header-invalid-timestamp-offset.json", "timestamp: '2026-09-18T12:00:00+0900' is not a 'date-time'"),
    ],
)
def test_media_header_invalid_rejected(media_validator, fixture: str, expect_in_error: str) -> None:
    """필수 누락 · 타입 오류 · `+0900` — 셋 다 실제로 거부되고 사유가 정확하다.

    `+0900` 거부는 `$ref` 로 끌어온 `message.schema.json#/properties/timestamp` 의 `format: date-time` 이
    포맷 검사기·레지스트리와 함께 실제로 동작한다는 뜻이다 — 이것이 무력하면 공통 헤더 검증도 무력한 것이다.
    """
    errors = _errors(media_validator, _load(fixture))
    assert errors, f"{fixture} 가 거부되지 않았다"
    assert any(expect_in_error in e for e in errors), errors


def test_media_header_required_set_and_no_enum() -> None:
    """필수 = 공통 머리 7 + `camera_id`·`encoding`·`width`·`height` · `frame_ref` 없음 · 공통 머리는 칸마다 `$ref` · enum 없음."""
    schema = json.loads((settings.contracts_dir() / "media-header.schema.json").read_text(encoding="utf-8"))
    assert set(schema["required"]) == {"schema_version", "source_id", "node_id", "zone_id", "timestamp", "sequence_id",
                                       "session_id", "camera_id", "encoding", "width", "height"}
    assert "frame_ref" not in schema["properties"], "v2 프레임 헤더에는 frame_ref 가 없다(그 유무로 v1/v2 를 가른다)"
    for field in ("schema_version", "source_id", "node_id", "zone_id", "timestamp", "sequence_id", "session_id", "sent_at"):
        assert schema["properties"][field]["$ref"] == "message.schema.json#/properties/" + field, field
    assert schema["then"]["required"] == ["keyframe", "codec"]
    for field in ("encoding", "codec"):
        assert "enum" not in schema["properties"][field], field
        assert "$comment" in schema["properties"][field], field
    assert schema.get("additionalProperties") is not False
    assert "페이로드는 열지 않는다" in schema["$comment"]


# ── 미디어 헤더 v1 (과도기 — 단계 5 에서 지운다) ─────────────────────────────


def test_media_header_v1_valid_and_frame_ref_closed(media_validator_v1, media_validator) -> None:
    """옛 헤더는 v1 규격으로 통과하고, frame_ref 안쪽 추가 필드·`+0900` 은 그대로 거부된다. v2 규격으로는 통과하지 않는다."""
    v1 = _load("media-header-v1-valid.json")
    assert "frame_ref" in v1
    assert _errors(media_validator_v1, v1) == []
    assert _errors(media_validator, v1), "v1 헤더가 v2 규격을 통과하면 안 된다(camera_id 등 필수 칸이 없다)"
    errors = _errors(media_validator_v1, _load("media-header-v1-invalid-frame-ref-extra.json"))
    assert any("frame_ref: Additional properties are not allowed ('rotation_deg' was unexpected)" in e for e in errors), errors
    bad = json.loads(json.dumps(v1))
    bad["frame_ref"]["capture_timestamp"] = "2026-09-18T12:00:00+0900"
    assert any("frame_ref/capture_timestamp: '2026-09-18T12:00:00+0900' is not a 'date-time'" in e
               for e in _errors(media_validator_v1, bad))


def test_v1_schema_files_have_own_ids() -> None:
    """v1 사본 둘은 `$id` 끝이 `.v1.schema.json` — 레지스트리에서 v2 와 겹치지 않는다. v1 헤더는 v1 참조를 가리킨다."""
    base = settings.contracts_dir()
    mh1 = json.loads((base / "media-header.v1.schema.json").read_text(encoding="utf-8"))
    fr1 = json.loads((base / "frame-reference.v1.schema.json").read_text(encoding="utf-8"))
    assert mh1["$id"].endswith("/media-header.v1.schema.json") and fr1["$id"].endswith("/frame-reference.v1.schema.json")
    assert mh1["properties"]["frame_ref"]["$ref"] == "frame-reference.v1.schema.json"
    assert set(mh1["required"]) == {"frame_ref", "encoding", "keyframe", "width", "height"}
    assert fr1["required"] == ["source_id", "capture_timestamp", "sequence_id"] and fr1["additionalProperties"] is False


# ── 탐지 초안 ────────────────────────────────────────────────────────────────


def test_detections_draft_valid(detections_validator) -> None:
    assert _errors(detections_validator, _load("detections-draft-valid.json")) == []


def test_detections_draft_without_alignment_passes(detections_validator) -> None:
    """`alignment` 는 선택이다 — 없으면 뷰어가 unaligned 로 취급한다(결정 3 fail-safe). 거부가 아니다."""
    message = _load("detections-draft-valid-no-alignment.json")
    assert "alignment" not in message and "frame_ref" not in message
    assert _errors(detections_validator, message) == []


def test_detections_draft_shape_and_vocab_not_enum() -> None:
    """§3-6 결과 머리 — 필수(공통 머리 5 · `emitted_at` · `model` · `width` · `height` · `detections`), 메시지 단위
    `alignment`·`producer{tier,kind}`, `tier` 에 `server` 가 적혀 있고, 어휘는 enum 이 아니다.

    ⚠ 2026-10-13 통합데이터규약(BE-04)으로 `bbox_space{…}`+`boxes[{x,y,w,h}]` → 결과 `width`·`height` + 검출
    `bbox [x1,y1,x2,y2]` 픽셀, `origin` → `producer`(N5) 로 바꿨다. 옛 이름이 남으면 둘이 갈린다.
    """
    schema = json.loads((settings.contracts_dir() / "detections.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    assert set(schema["required"]) == {"schema_version", "source_id", "node_id", "zone_id", "timestamp",
                                       "emitted_at", "model", "width", "height", "detections"}
    assert "alignment" in props and "alignment" not in schema["required"]
    assert "frame_ref" not in schema["required"] and props["frame_ref"]["$ref"] == "frame-reference.schema.json"
    assert set(props["producer"]["required"]) == {"tier", "kind"}
    assert "server" in props["producer"]["properties"]["tier"]["$comment"]
    for gone in ("origin", "bbox_space", "boxes", "coord"):
        assert gone not in props, gone + " 은 v2 에서 없앤 이름이다"
    for spec in (props["alignment"], props["producer"]["properties"]["tier"], props["producer"]["properties"]["kind"]):
        assert "enum" not in spec
    item = props["detections"]["items"]
    assert set(item["required"]) == {"bbox", "label"}
    assert item["properties"]["bbox"]["minItems"] == 4 and item["properties"]["bbox"]["maxItems"] == 4
    assert "source" not in item["properties"], "검출 단위 source 는 버렸다 — 출처는 메시지 단위 producer"
    assert "초안" in schema["$comment"]


def test_detections_draft_rejects_bad_detection(detections_validator) -> None:
    """초안이라도 검증기는 돈다 — 검출에 `label` 이 없거나, `bbox` 가 넷이 아니거나, 결과에 `width` 가 없으면 거부.

    이름을 또 바꾸면 규격·예시·이 시험 **셋을 같이** 고쳐야 한다(2026-09-21 에 예시만 바뀌어 한 번 깨졌다).
    """
    message = _load("detections-draft-valid.json")
    del message["detections"][0]["label"]
    assert any("label" in e for e in _errors(detections_validator, message))
    message = _load("detections-draft-valid.json")
    message["detections"][0]["bbox"] = [1, 2, 3]
    assert any("detections/0/bbox" in e for e in _errors(detections_validator, message))
    message = _load("detections-draft-valid.json")
    del message["width"]
    assert any("'width' is a required property" in e for e in _errors(detections_validator, message))
    message = _load("detections-draft-valid.json")
    message["frame_ref"]["source_id"] = message["frame_ref"].pop("camera_id")       # 옛 frame_ref 모양
    assert any("frame_ref" in e for e in _errors(detections_validator, message))


# ── frame-reference: v2 구조 (통합데이터규약 §3-3 · BE-02) ────────────────────


def test_frame_reference_v2_structure() -> None:
    """세 칸(`camera_id`·`sequence_id`·`timestamp`)만, 셋 다 필수, `additionalProperties:false` — F==F 비교의 전제.

    `$id` 는 그대로다(규격을 $ref 하는 쪽이 바꿀 것이 없다). 옛 다섯 칸 모양은 `frame-reference.v1.schema.json`.
    """
    schema = json.loads((settings.contracts_dir() / "frame-reference.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"].endswith("/frame-reference.schema.json")
    assert set(schema["properties"]) == {"camera_id", "sequence_id", "timestamp"}
    assert schema["required"] == ["camera_id", "sequence_id", "timestamp"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["timestamp"]["type"] == "string"
    assert schema["properties"]["timestamp"]["format"] == "date-time"
    assert "처음 손에 넣은 기기" in schema["description"], "원칙 10 의 v2 문장(BE-10)"
    assert "엣지에서 한 번 부여" not in schema["description"]


# ── $ref 레지스트리 ──────────────────────────────────────────────────────────


def test_registry_resolves_object_reference_like_media_header() -> None:
    """`object-reference.schema.json` 도 같은 레지스트리로 `frame_ref` 를 해석한다 — Phase 7 이 이 경로를 그대로 쓴다.

    `frame_ref` 는 v2 모양(§3-3)이다 — object-reference 는 `$ref` 만 하므로 frame-reference 가 바뀌면 같이 바뀐다.
    """
    validator = envelope.contract_validator("object-reference.schema.json")
    good = {
        "object_id": "obj-1", "zone_local_track_id": "zoneA-track-1", "zone_id": "zoneA",
        "first_seen": "2026-09-18T12:00:00+09:00", "last_seen": "2026-09-18T12:00:01+09:00",
        "frame_ref": {"camera_id": "go1-001_front", "sequence_id": 1, "timestamp": "2026-09-18T12:00:00.123+09:00"},
    }
    assert _errors(validator, good) == []
    bad = dict(good, frame_ref={"camera_id": "go1-001_front", "sequence_id": 1, "timestamp": "2026-09-18T12:00:00+0900"})
    assert any("frame_ref/timestamp" in e for e in _errors(validator, bad))
    old = dict(good, frame_ref={"source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00.123+09:00",
                                "sequence_id": 1})
    assert _errors(validator, old), "옛 frame_ref 모양은 v2 참조 규격으로 통과하지 않는다"


def test_registry_has_every_schema_by_id() -> None:
    registry = envelope.schema_registry()
    for path in settings.contracts_dir().rglob("*.schema.json"):
        schema_id = json.loads(path.read_text(encoding="utf-8"))["$id"]
        assert registry.get(schema_id) is not None, f"{path.name} 이 레지스트리에 없다"


def test_unregistered_ref_fails_without_network(tmp_path: Path, monkeypatch) -> None:
    """레지스트리에 `$ref` 대상(v2 는 `message.schema.json`)이 없으면 `$id` URL 로 가져오려 하지 않고 검증 시점에 실패한다(결정 12)."""
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
    """DoD 1-1b — 새 규격 둘(과 v1 사본 둘)은 `payload/` 밖이라 타입 판별·힌트 검산(22)에 영향이 없다."""
    assert "media-header" not in contracts.known_entity_types()
    grouped = contracts.hint_items_by_kind()
    assert sum(len(v) for v in grouped.values()) == 22
    assert len(contracts.observation_hints()) == 27
