"""실증 데이터 스트림의 **실제 결과 한 건**으로 번역을 고정한다.

아래 `RECORDED_*` 는 2026-11-04 에 `physical_demo`(data_stream 가지)를 실제로 돌려
받은 항목이다 — 파일 소스로 올린 프레임에 `vision/vision_infer.py` 의 YOLOE
prompt-free(`yoloe-11s-seg-pf.pt`, cuda:0)가 붙인 결과이고, 손으로 지어낸 값이
아니다(마스크 `polygon` 만 길이 때문에 뺐다).

시험이 고정하는 것 넷.

1. 번역 결과가 **우리 계약**(`schemas/ai/detection-result.schema.json`)을 만족한다.
   고치기 전에는 10 군데가 어긋났다 — `frame_ref` 모양, `emitted_at` 시간대,
   `producer` 네 칸, `bbox_format` 어휘.
2. 원본 관측 참조는 **장치가 붙인 것을 그대로** 옮긴다. 우리가 번호를 새로 만들면
   그 번호는 아무 원본도 가리키지 않는다(AI-C-03).
3. 그 참조가 없는 결과는 **버리고 센다.** 옛 장비(프레임 헤더 없는 MJPEG)에서 실제로
   일어나고, 조용히 버리면 "탐지가 없다" 와 구분되지 않는다(AI-C-05).
4. 같은 항목을 두 번 내보내지 않는다 — 화면의 탐지 수가 실제보다 많아진다.

implements: AI-C-01, AI-C-03, AI-C-05, AI-E-01
tests: recorded-stream translation, contract conformance, missing frame_ref drop,
       stream pointer separate from the frame reference, cursor
"""
from __future__ import annotations

import json

from integration.vz_redis_source import REASON_NO_FRAME_REF, RedisDetectionSource
from tests.test_integration_contract_schemas import body_validator

RECORDED_ENTRY_ID = b"1793759870296-0"

RECORDED_RESULT = {
    "schema_version": "2.0", "source_id": "ds-vision", "node_id": "DESKTOP-0IB285F",
    "zone_id": "zoneA", "timestamp": "2026-11-04T11:37:50.193+09:00",
    "frame_ref": {"camera_id": "go1-001_cam1", "sequence_id": 720,
                  "timestamp": "2026-11-04T11:37:50.193+09:00"},
    "emitted_at": "2026-11-04T11:37:50.293+09:00",
    "producer": {"tier": "server", "kind": "precise"},
    "n": 722, "frame_file": "frames/000000722.jpg", "stream": "robot1",
    "run": "20261104_112747", "width": 640, "height": 480, "live": True,
    "model": "yoloe", "infer_ms": 30.5, "model_file": "yoloe-11s-seg-pf.pt",
    "prompt": "free",
    "detections": [
        {"class_id": 2115, "label": "home interior", "confidence": 0.7773,
         "bbox": [1.0, 0.8, 638.0, 479.0]},
        {"class_id": 2320, "label": "kitchen floor", "confidence": 0.6875,
         "bbox": [2.0, 281.5, 640.0, 480.0]},
        {"class_id": 133, "label": "armoire", "confidence": 0.645,
         "bbox": [345.5, 0.0, 545.5, 283.0]},
    ],
    "overlay_file": "overlay/000000722.jpg",
}

RECORDED_HEADER = {
    "stream": "robot1", "model": "yoloe", "n": 722, "run": "20261104_112747",
    "frame_file": "robot1/20261104_112747/frames/000000722.jpg",
    "stream_entry_id": "1793759870197-0", "lag_ms": 96,
}


class FakeRedis:
    """`xrevrange` · `xread` · `exists` 만 흉내 낸다. 소켓도 서버도 없다."""

    def __init__(self, rows: list[tuple[bytes, dict]]):
        self.rows = rows

    def exists(self, key):                                    # noqa: D102
        return 1 if self.rows else 0

    def xrevrange(self, key, count=1):                        # noqa: D102
        return list(reversed(self.rows[-count:]))

    def xread(self, streams, count=4):                        # noqa: D102
        key, cursor = next(iter(streams.items()))
        after = [row for row in self.rows if row[0] > cursor]
        return [(key.encode(), after[:count])] if after else []


def entry(result: dict, header: dict, entry_id: bytes = RECORDED_ENTRY_ID):
    return (entry_id, {b"result": json.dumps(result, ensure_ascii=False).encode(),
                       b"header": json.dumps(header, ensure_ascii=False).encode(),
                       # 오버레이 JPEG 는 그쪽 항목에 늘 함께 들어 있다. 와이어로는 나가지 않는다.
                       b"overlay": b"\xff\xd8\xff\xe0 jpeg bytes"})


def source_over(rows) -> RedisDetectionSource:
    src = RedisDetectionSource(sources=("robot1",))
    src.client = FakeRedis(rows)
    return src


def test_a_recorded_result_translates_into_a_payload_our_own_contract_accepts():
    src = source_over([entry(RECORDED_RESULT, RECORDED_HEADER)])

    (device, payload), = src.poll()

    assert device == "go1-001"
    errors = list(body_validator("detections").iter_errors(payload))
    assert errors == [], [list(e.path) + [e.message] for e in errors]


def test_the_frame_reference_comes_from_the_device_not_from_us():
    """카메라·번호·시각은 그 장을 처음 손에 넣은 기기의 것이다."""
    src = source_over([entry(RECORDED_RESULT, RECORDED_HEADER)])

    (_, payload), = src.poll()

    assert payload["frame_ref"] == RECORDED_RESULT["frame_ref"]
    # 그쪽이 적은 발행 시각 그대로 — 우리가 읽은 시각으로 덮으면 지연이 작아 보인다.
    assert payload["emitted_at"] == RECORDED_RESULT["emitted_at"]
    # 데모 쪽 포인터는 로그에만 남고 와이어에는 없다(등록된 이름이 아니다).
    assert "stream_entry_id" not in json.dumps(payload)
    assert src.last_pointer["robot1"]["frame_file"].endswith("000000722.jpg")


def test_pixels_never_ride_the_state_contract():
    """오버레이 JPEG 는 봉투에 실리지 않는다(AI-C-08)."""
    src = source_over([entry(RECORDED_RESULT, RECORDED_HEADER)])

    (_, payload), = src.poll()

    assert "jpeg" not in json.dumps(payload)
    assert "\\ufffd" not in json.dumps(payload)


def test_a_result_without_a_device_frame_reference_is_dropped_and_counted():
    """옛 장비는 프레임 헤더를 붙이지 않는다 — 그때 그쪽 결과에 `frame_ref` 가 없다.

    한때 스트림 항목 id 로 그 자리를 메우려 했다. 틀린 이유는 규격이 아니라 **셈**
    이다 — `perception/uncertainty.py` 가 `(source_group, frame_ref)` 로 근거를
    접으므로, 같은 장의 결과 둘이 서로 다른 항목 id 를 받으면 **두 번 본 것으로
    세어지고** 근거 충분도가 실제보다 커진다. 그래서 버리고 센다. 이 수가 0 이
    아니면 고칠 곳은 우리가 아니라 장비의 프레임 헤더다.
    """
    legacy = {k: v for k, v in RECORDED_RESULT.items() if k != "frame_ref"}
    src = source_over([entry(legacy, RECORDED_HEADER)])

    assert src.poll() == []
    assert src.dropped == {REASON_NO_FRAME_REF: 1}
    assert REASON_NO_FRAME_REF in src.note()


def test_the_stream_pointer_rides_along_but_is_not_the_frame_reference():
    """`frame_ref` 는 **무엇을 봤는가**, `stream_ref` 는 **어디서 다시 꺼내는가**.

    오류 재현(AI-O-03)이 뒤쪽을 쓰고, 근거를 접는 쪽은 앞쪽만 본다.
    """
    (_, payload), = source_over([entry(RECORDED_RESULT, RECORDED_HEADER)]).poll()

    assert payload["frame_ref"] == RECORDED_RESULT["frame_ref"]
    assert payload["stream_ref"]["source_entry_id"] == str(
        RECORDED_HEADER["stream_entry_id"])
    assert "sequence_id" not in payload["stream_ref"], (
        "항목 id 를 프레임 순번으로 바꿔 적지 않는다")


def test_the_same_entry_is_not_emitted_twice():
    rows = [entry(RECORDED_RESULT, RECORDED_HEADER)]
    src = source_over(rows)

    assert len(src.poll()) == 1
    assert src.poll() == []

    later = dict(RECORDED_RESULT, frame_ref=dict(RECORDED_RESULT["frame_ref"], sequence_id=721))
    rows.append(entry(later, RECORDED_HEADER, b"1793759870900-0"))
    (_, payload), = src.poll()
    assert payload["frame_ref"]["sequence_id"] == 721
