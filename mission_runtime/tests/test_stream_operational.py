"""실증 배치의 운영 데이터 스트림이 학습 후보로 들어오는 입구.

implements: AI-L-09
tests: stream_data 실행 폴더 읽기, vision_stream Redis 읽기, held 검출 배제,
       기기·모델별 묶음 분리, 미검증 결과의 자동 승격 금지, 수집 실패 격리
"""

from __future__ import annotations

import json

import pytest

from mission_runtime.continual.operational_stream import (
    EXTRA_MODEL,
    REASON_DUPLICATE_RESULT,
    REASON_FRAME_NOT_STORED,
    REASON_HELD_DETECTION,
    REASON_MALFORMED_RECORD,
    REASON_NO_CONFIDENCE,
    REASON_NO_DETECTIONS,
    REASON_NO_LABEL,
    REASON_UNKNOWN_FRAME,
    Detection,
    FrameRecord,
    IngestResult,
    VisionResult,
    discover_runs,
    models_in_run,
    read_run,
    read_stream_data,
    read_vision_stream,
    samples_from_result,
    vision_stream_key,
)
from mission_runtime.continual.stream_learning import (
    REASON_NO_CONFIRMED_SAMPLES,
    CandidateOrigin,
    CandidateStore,
    ContinualLearner,
    ParameterSet,
)
from mission_runtime.continual.stream_ingest import ThresholdLearningProvider

RUN = "20261001_123152"


# -- 실제 규약 모양의 자료를 만든다 -------------------------------------------


def _frame_header(stream: str, n: int, *, stored: bool = True) -> dict:
    """`frames.jsonl` 한 줄. 규약의 칸 이름 그대로다."""
    return {
        "stream": stream,
        "n": n,
        "frame_file": f"{stream}/{RUN}/frames/{n:09d}.jpg" if stored else None,
        "via": "pull:http://pi7:8090/stream/1",
        "received_by": "ds-note",
        "received_at": "2026-10-14T12:00:00.190+09:00",
        "sender": {"sequence_id": n},
    }


def _result(stream: str, n: int, model: str, detections, **over) -> dict:
    """`results.jsonl` 한 줄(v2 비전 결과)."""
    row = {
        "schema_version": "2.0",
        "source_id": "ds-vision",
        "node_id": "ds-note",
        "zone_id": "zoneA",
        "timestamp": "2026-10-14T12:00:00.100+09:00",
        "frame_ref": {"camera_id": f"{stream}-cam0", "sequence_id": n},
        "emitted_at": "2026-10-14T12:00:00.400+09:00",
        "producer": {"tier": "server", "kind": "precise"},
        "n": n,
        "frame_file": f"frames/{n:09d}.jpg",
        "stream": stream,
        "run": RUN,
        "model": model,
        "model_file": "weights/yoloe-11s-seg.pt",
        "width": 1920,
        "height": 1080,
        "infer_ms": 41.0,
        "prompt": "text",
        "detections": list(detections),
    }
    row.update(over)
    return row


def _det(label: str, confidence: float | None, **over) -> dict:
    row = {"class_id": 0, "label": label, "confidence": confidence,
           "bbox": [1.0, 2.0, 3.0, 4.0], "track_id": 7}
    row.update(over)
    return row


def _write_run(root, stream: str, *, frames, results_by_model) -> None:
    run_dir = root / stream / RUN
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "frames.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in frames),
        encoding="utf-8")
    for model, rows in results_by_model.items():
        model_dir = run_dir / "vision" / model
        model_dir.mkdir(parents=True)
        (model_dir / "results.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8")


# -- 디스크 경로 ---------------------------------------------------------------


def test_a_run_folder_becomes_candidates_with_a_traceable_frame_reference(tmp_path):
    _write_run(tmp_path, "robot1",
               frames=[_frame_header("robot1", 1)],
               results_by_model={"yoloe": [_result("robot1", 1, "yoloe",
                                                   [_det("door", 0.81)])]})
    outcome = read_run(tmp_path / "robot1" / RUN)

    assert len(outcome.samples) == 1
    sample = outcome.samples[0]
    assert sample.label == "door"
    assert sample.confidence == pytest.approx(0.81)
    # 임계 학습이 읽는 칸. 검출 신뢰도가 운영에서 임계와 견주는 그 수치다.
    assert sample.similarity == pytest.approx(0.81)
    # 원본 관측을 되짚을 수 있다(AI-C-03). 실행 폴더가 참조에 들어 있다.
    assert sample.frame_ref == f"robot1/{RUN}/frames/000000001.jpg"
    assert RUN in sample.sample_id and "yoloe" in sample.sample_id
    assert outcome.frames_read == 1 and outcome.results_read == 1


def test_everything_from_the_vision_stream_is_auto_inference_and_cannot_train(tmp_path):
    """AI-L-02: 검증되지 않은 추론 결과는 학습 정답이 되지 않는다.

    이 입구만으로는 임계 학습이 **아무것도 내지 않는다**. 그것이 고장이 아니라
    설계이고, 그 사실을 시험이 고정한다 — 누군가 origin 을 바꿀 수 있게 만들면
    이 시험이 깨진다.
    """
    _write_run(tmp_path, "drone",
               frames=[_frame_header("drone", n) for n in (1, 2, 3, 4, 5, 6)],
               results_by_model={"yoloe": [
                   _result("drone", n, "yoloe", [_det("trash", 0.5 + n / 100)])
                   for n in (1, 2, 3, 4, 5, 6)]})
    outcome = read_run(tmp_path / "drone" / RUN)
    assert len(outcome.samples) == 6
    assert {s.origin for s in outcome.samples} == {CandidateOrigin.AUTO_INFERENCE}
    assert not any(s.confirmed for s in outcome.samples)

    learner = ContinualLearner(provider=ThresholdLearningProvider(min_samples=3))
    learner.ingest_many(outcome.samples)
    conditions = outcome.samples[0].conditions
    learner.bases[conditions.group_key] = ParameterSet(
        parameters={"trash": {"prompts": ["a photo of trash"], "threshold": 0.3,
                              "gates": {}}},
        conditions=conditions)
    result = learner.train_group(conditions)
    assert not result.produced
    assert result.reason == REASON_NO_CONFIRMED_SAMPLES

    # 이 모듈에 자동 추론을 확인 상태로 올리는 길이 없다.
    import mission_runtime.continual.operational_stream as module

    assert "HUMAN_CONFIRMED" not in module.__dict__
    assert all("confirm" not in name for name in dir(module))


def test_a_held_detection_is_not_a_candidate(tmp_path):
    """`held` 는 이 장에서 못 잡은 검출을 직전 박스로 유지한 표시다.

    후보로 세면 같은 관측 하나가 여러 프레임에서 센 것이 되어 임계가 끌려간다.
    """
    _write_run(tmp_path, "robot1",
               frames=[_frame_header("robot1", 1), _frame_header("robot1", 2)],
               results_by_model={"yoloe": [
                   _result("robot1", 1, "yoloe", [_det("door", 0.80)]),
                   _result("robot1", 2, "yoloe", [_det("door", 0.80, held=True)]),
               ]})
    outcome = read_run(tmp_path / "robot1" / RUN)
    assert len(outcome.samples) == 1
    assert outcome.reasons() == {REASON_HELD_DETECTION: 1}


def test_a_frame_that_was_never_stored_yields_no_candidate(tmp_path):
    """되짚을 원본이 없는 후보는 만들지 않는다(AI-C-03)."""
    _write_run(tmp_path, "cam360",
               frames=[_frame_header("cam360", 1, stored=False)],
               results_by_model={"yoloe": [_result("cam360", 1, "yoloe",
                                                   [_det("buoy", 0.6)])]})
    outcome = read_run(tmp_path / "cam360" / RUN)
    assert outcome.samples == ()
    assert outcome.reasons() == {REASON_FRAME_NOT_STORED: 1}


def test_a_detection_without_a_label_or_confidence_is_refused_not_zero_filled(tmp_path):
    """미측정은 0이 아니다 — 신뢰도 없는 검출은 사유와 함께 빠진다."""
    _write_run(tmp_path, "robot2",
               frames=[_frame_header("robot2", 1)],
               results_by_model={"yoloe": [_result("robot2", 1, "yoloe", [
                   _det("", 0.9), _det("door", None), _det("door", 0.7)])]})
    outcome = read_run(tmp_path / "robot2" / RUN)
    assert [s.label for s in outcome.samples] == ["door"]
    assert outcome.reasons() == {REASON_NO_LABEL: 1, REASON_NO_CONFIDENCE: 1}


def test_the_same_frame_number_twice_is_counted_once(tmp_path):
    """`--overwrite` 재작성·동시 append 가 같은 번호를 두 번 남길 수 있다."""
    _write_run(tmp_path, "robot1",
               frames=[_frame_header("robot1", 1)],
               results_by_model={"yoloe": [
                   _result("robot1", 1, "yoloe", [_det("door", 0.8)]),
                   _result("robot1", 1, "yoloe", [_det("door", 0.8)]),
               ]})
    outcome = read_run(tmp_path / "robot1" / RUN)
    assert len(outcome.samples) == 1
    assert outcome.reasons() == {REASON_DUPLICATE_RESULT: 1}


def test_a_broken_line_is_counted_not_raised(tmp_path):
    """운영 프로세스가 append 중인 파일의 마지막 줄은 반쪽일 수 있다.

    한 줄 때문에 수집이 멈추면 학습 장애가 아니라 수집 장애가 되고, 그것도 운영을
    흔들 이유가 없다(AI-L-09).
    """
    _write_run(tmp_path, "drone",
               frames=[_frame_header("drone", 1)],
               results_by_model={"yoloe": [_result("drone", 1, "yoloe",
                                                   [_det("trash", 0.7)])]})
    path = tmp_path / "drone" / RUN / "vision" / "yoloe" / "results.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"stream": "drone", "n": 2, "model": "yolo')  # 반쪽 줄
    outcome = read_run(tmp_path / "drone" / RUN)
    assert len(outcome.samples) == 1
    assert outcome.reasons() == {REASON_MALFORMED_RECORD: 1}


def test_a_result_without_a_matching_frame_record_is_reported(tmp_path):
    """`frames.jsonl` 이 아직 flush 되지 않아 생기는 정상적인 어긋남."""
    run = tmp_path / "robot1" / RUN
    (run / "frames").mkdir(parents=True)
    (run / "frames.jsonl").write_text("", encoding="utf-8")
    model_dir = run / "vision" / "yoloe"
    model_dir.mkdir(parents=True)
    (model_dir / "results.jsonl").write_text(
        json.dumps(_result("robot1", 9, "yoloe", [_det("door", 0.8)],
                           frame_file=None)) + "\n", encoding="utf-8")
    outcome = read_run(run)
    assert outcome.samples == ()
    assert outcome.reasons() == {REASON_UNKNOWN_FRAME: 1}


def test_a_result_with_no_detections_is_not_silently_dropped(tmp_path):
    _write_run(tmp_path, "robot1",
               frames=[_frame_header("robot1", 1)],
               results_by_model={"yoloe": [_result("robot1", 1, "yoloe", [])]})
    outcome = read_run(tmp_path / "robot1" / RUN)
    assert outcome.reasons() == {REASON_NO_DETECTIONS: 1}


# -- 기기·입력 조건별 분리 (AI-L-09) -----------------------------------------


def test_candidates_are_kept_apart_per_device_and_per_model(tmp_path):
    """같은 라벨이라도 기기·모델이 다르면 다른 묶음이다.

    모델을 묶음 키에 넣는 이유: 신뢰도 분포가 모델마다 다르고, 섞으면 한 모델의
    임계가 다른 모델의 표본으로 움직인다.
    """
    _write_run(tmp_path, "robot1",
               frames=[_frame_header("robot1", 1)],
               results_by_model={
                   "yoloe": [_result("robot1", 1, "yoloe", [_det("door", 0.8)])],
                   "moge2_aerial": [_result("robot1", 1, "moge2_aerial",
                                            [_det("door", 0.4)])]})
    _write_run(tmp_path, "drone",
               frames=[_frame_header("drone", 1)],
               results_by_model={"yoloe": [_result("drone", 1, "yoloe",
                                                   [_det("door", 0.6)])]})

    outcome = read_stream_data(tmp_path)
    store = CandidateStore()
    store.extend(outcome.samples)
    groups = store.groups()
    assert len(groups) == 3
    assert {g.device_id for g in groups} == {"robot1", "drone"}
    models = {dict(g.extra)[EXTRA_MODEL] for g in groups}
    assert models == {"yoloe", "moge2_aerial"}
    # 가속기는 이 규약이 보고하지 않으므로 지어내지 않는다.
    assert all(g.accelerator_id is None for g in groups)
    assert all(g.resolution == (1920, 1080) for g in groups)


def test_two_runs_of_the_same_device_land_in_one_group(tmp_path):
    """`run` 은 입력 조건이 아니다 — 실행을 새로 띄워도 표본은 같은 묶음에 쌓인다."""
    _write_run(tmp_path, "robot1",
               frames=[_frame_header("robot1", 1)],
               results_by_model={"yoloe": [_result("robot1", 1, "yoloe",
                                                   [_det("door", 0.8)])]})
    second = tmp_path / "robot1" / "20261002_090000"
    (second / "frames").mkdir(parents=True)
    (second / "frames.jsonl").write_text(
        json.dumps({**_frame_header("robot1", 1),
                    "frame_file": "robot1/20261002_090000/frames/000000001.jpg"}) + "\n",
        encoding="utf-8")
    model_dir = second / "vision" / "yoloe"
    model_dir.mkdir(parents=True)
    (model_dir / "results.jsonl").write_text(
        json.dumps(_result("robot1", 1, "yoloe", [_det("door", 0.9)],
                           run="20261002_090000")) + "\n", encoding="utf-8")

    outcome = read_stream_data(tmp_path)
    store = CandidateStore()
    store.extend(outcome.samples)
    assert len(store.groups()) == 1
    assert store.total_count() == 2
    # 그러나 되짚기 참조는 서로 다르다 — 어느 실행의 그림인지 구분된다.
    assert len({s.frame_ref for s in outcome.samples}) == 2


def test_sources_and_models_are_discovered_not_declared(tmp_path):
    """소스·모델 이름을 코드가 알지 않는다. 새 기기·새 모델은 폴더 하나다."""
    _write_run(tmp_path, "nuevo-robot",
               frames=[_frame_header("nuevo-robot", 1)],
               results_by_model={"brand-new-model": [
                   _result("nuevo-robot", 1, "brand-new-model", [_det("x", 0.5)])]})
    runs = discover_runs(tmp_path)
    assert [(r.source, r.run) for r in runs] == [("nuevo-robot", RUN)]
    assert models_in_run(runs[0].path) == ("brand-new-model",)
    assert len(read_run(runs[0].path).samples) == 1


def test_an_absent_store_is_an_empty_result_not_a_failure(tmp_path):
    assert read_stream_data(tmp_path / "nothing-here") == IngestResult()
    assert discover_runs(tmp_path / "nothing-here") == ()
    assert models_in_run(tmp_path / "nothing-here") == ()


# -- 옛 결과 파일 -------------------------------------------------------------


def test_the_old_result_shape_is_read_rather_than_silently_empty():
    """옛 칸 이름(`frame`·`source`·`image_wh`·`cls/name/conf/xyxy`)도 읽는다."""
    result = VisionResult.from_result({
        "source": "robot1", "frame": 12, "model": "yoloe",
        "image_wh": [640, 480],
        "detections": [{"cls": 0, "name": "door", "conf": 0.66,
                        "xyxy": [1, 2, 3, 4]}],
        "frame_file": "frames/000000012.jpg",
    })
    assert result.stream == "robot1" and result.n == 12
    assert result.width == 640 and result.height == 480
    assert result.detections[0].label == "door"
    assert result.detections[0].confidence == pytest.approx(0.66)
    assert len(samples_from_result(result).samples) == 1


def test_a_result_missing_its_identity_is_refused():
    for row in ({"model": "yoloe", "n": 1}, {"stream": "a", "n": 1},
                {"stream": "a", "model": "yoloe"}):
        with pytest.raises(ValueError):
            VisionResult.from_result(row)


def test_a_frame_header_missing_its_identity_is_refused():
    with pytest.raises(ValueError):
        FrameRecord.from_header({"frame_file": "x.jpg"})


def test_unreadable_timestamps_stay_none_rather_than_zero():
    result = VisionResult.from_result(
        _result("robot1", 1, "yoloe", [_det("door", 0.5)], timestamp="not-a-time"))
    assert result.observed_at is None
    # epoch 글자(옛 360 폼)는 같은 뜻으로 읽는다.
    epoch = VisionResult.from_result(
        _result("robot1", 1, "yoloe", [_det("door", 0.5)], timestamp="1760000000.5"))
    assert epoch.observed_at == pytest.approx(1760000000.5)


def test_a_zulu_timestamp_is_read():
    result = VisionResult.from_result(
        _result("robot1", 1, "yoloe", [_det("door", 0.5)],
                timestamp="2026-10-14T03:00:00.100Z"))
    assert result.observed_at is not None


# -- Redis live 경로 ----------------------------------------------------------


class _FakeRedis:
    """`xrevrange` 하나만 가진 가짜. `redis` 를 설치하지 않고 같은 경로를 돈다."""

    def __init__(self, entries, *, fail: bool = False) -> None:
        self._entries = entries
        self._fail = fail
        self.asked: list[str] = []

    def xrevrange(self, name, max="+", min="-", count=None):
        self.asked.append(name)
        if self._fail:
            raise RuntimeError("connection refused")
        return list(self._entries)


def _entry(entry_id: str, result: dict, *, source_entry: str) -> tuple:
    """`vision_stream` 항목 하나. 칸 이름·값이 bytes 인 실제 모양을 쓴다."""
    return (
        entry_id.encode(),
        {
            b"result": json.dumps(result, ensure_ascii=False).encode(),
            b"header": json.dumps({"stream": result["stream"], "model": result["model"],
                                   "n": result["n"], "run": result["run"],
                                   "frame_file": result["frame_file"],
                                   "stream_entry_id": source_entry,
                                   "lag_ms": 70}).encode(),
            b"overlay": b"\xff\xd8not-a-real-jpeg",
        },
    )


def test_the_live_stream_carries_the_source_entry_id_into_the_frame_reference():
    """규약: `header.stream_entry_id` 로 원본 프레임을 찾는다. 그것이 참조에 남는다."""
    client = _FakeRedis([
        _entry("1760-1", _result("drone", 4, "yoloe", [_det("trash", 0.77)]),
               source_entry="1759-9"),
    ])
    outcome = read_vision_stream(client, "drone", "yoloe")

    assert client.asked == [vision_stream_key("drone", "yoloe")]
    assert client.asked == ["vision_stream:drone:yoloe"]
    assert len(outcome.samples) == 1
    sample = outcome.samples[0]
    assert sample.frame_ref.endswith("@1759-9")
    assert sample.origin is CandidateOrigin.AUTO_INFERENCE
    # 픽셀은 후보에 담지 않는다 — overlay 칸은 읽지도 않는다(AI-C-08).
    assert "overlay" not in sample.frame_ref


def test_a_dead_redis_is_an_empty_result_with_a_reason_not_an_exception():
    """규약: Redis 가 꺼져 있어도 스트림은 멈추지 않는다. 수집도 멈추지 않는다."""
    outcome = read_vision_stream(_FakeRedis([], fail=True), "drone", "yoloe")
    assert outcome.samples == ()
    assert list(outcome.reasons()) == [REASON_MALFORMED_RECORD]


def test_the_live_and_disk_paths_produce_the_same_group_key():
    """같은 기기·모델·해상도면 live 와 저장본이 **한 묶음**이다.

    갈리면 live 로 모은 표본과 나중에 저장본에서 모은 표본이 서로 다른 임계를
    학습하게 된다.
    """
    row = _result("drone", 4, "yoloe", [_det("trash", 0.77)])
    live = read_vision_stream(_FakeRedis([_entry("1760-1", row, source_entry="1759-9")]),
                              "drone", "yoloe")
    disk = samples_from_result(VisionResult.from_result(row))
    assert live.samples[0].conditions.group_key == disk.samples[0].conditions.group_key
    # 그러나 표본 신원은 다르다 — 같은 관측을 두 번 세지 않도록 호출자가 구분한다.
    assert live.samples[0].sample_id != disk.samples[0].sample_id


def test_a_malformed_live_entry_is_counted():
    client = _FakeRedis([(b"1-1", {b"result": b"{not json"})])
    outcome = read_vision_stream(client, "drone", "yoloe")
    assert outcome.samples == ()
    assert outcome.reasons() == {REASON_MALFORMED_RECORD: 1}


def test_a_live_entry_with_text_fields_is_read_too():
    """`decode_responses=True` 로 연결한 클라이언트는 칸이 글자다."""
    row = _result("drone", 4, "yoloe", [_det("trash", 0.5)])
    client = _FakeRedis([("1-1", {"result": json.dumps(row),
                                  "header": json.dumps({"stream_entry_id": "0-1"})})])
    outcome = read_vision_stream(client, "drone", "yoloe")
    assert len(outcome.samples) == 1
    assert outcome.samples[0].frame_ref.endswith("@0-1")


# -- 사유 집계 ----------------------------------------------------------------


def test_the_result_says_how_much_was_read_and_how_much_was_thrown_away(tmp_path):
    """"후보가 적다" 가 자료가 적은 것인지 전부 걸러진 것인지 구분되어야 한다."""
    _write_run(tmp_path, "robot1",
               frames=[_frame_header("robot1", n) for n in (1, 2)],
               results_by_model={"yoloe": [
                   _result("robot1", 1, "yoloe", [_det("door", 0.8, held=True)]),
                   _result("robot1", 2, "yoloe", [_det("door", 0.9)]),
               ]})
    outcome = read_run(tmp_path / "robot1" / RUN)
    assert outcome.frames_read == 2
    assert outcome.results_read == 2
    assert len(outcome.samples) == 1
    assert outcome.reasons() == {REASON_HELD_DETECTION: 1}


def test_detection_alias_table_does_not_invent_a_confidence():
    assert Detection.from_raw({"name": "door"}, 0).confidence is None
    assert Detection.from_raw({"conf": True, "name": "door"}, 0).confidence is None
