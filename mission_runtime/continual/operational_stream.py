"""Reads the **실증 배치의 운영 데이터 스트림** as it actually lands — the
`stream_data/<소스>/<실행>/` run folders and the `vision_stream:<소스>:<모델>`
Redis stream — and turns it into learning candidates.

implements: AI-L-09 (운영 데이터 스트림 기반 지속학습 실행)
관련: AI-L-01 (후보 선별), AI-L-02 (격리·미검증 승격 금지), AI-L-03 (사용자 확인),
      AI-C-06 (전송 경계), AI-C-08 (픽셀은 업무 경로로 나가지 않는다),
      AI-C-03 (원본 관측 참조), AI-O-05 (미측정 ≠ 0)
tests: tests/test_stream_operational.py

왜 `stream_ingest.py` 로 되지 않는가
-------------------------------------
`continual/stream_ingest.py` 는 **회전 스캔 규약**(`scan_id` · `rotation_deg` ·
`duplicate_of_prev` — 한 자리에서 8방향을 찍는 판)을 받는다. 실증 배치에서 실제로
쌓이는 것은 그 모양이 아니다. 로봇 2대·드론·360 카메라가 **연속 스트림**을 올리고
저장은 실행(run) 폴더 단위이며, 라벨 후보는 프레임이 아니라 **비전 모델의 검출**에서
나온다. 판 경계가 없으므로 `ScanAssembler` 의 판정(판을 통째로 버린다)을 적용할
자리가 없다. 그래서 같은 목적지(`StreamSample`)로 가는 **두 번째 입구**를 만들고,
그 뒤의 보관·학습·검증 경로는 기존 것을 그대로 쓴다. 이 파일에 학습기도 저장소도
없는 것이 그 경계다.

실제 자료 모양(데모 저장소 `data_stream` 가지의 규약을 그대로 받아 적었다)
-------------------------------------------------------------------------
    stream_data/<소스>/<실행 YYYYMMDD_HHMMSS>/
        frames.jsonl              {stream, n, frame_file, via, received_by,
                                   received_at, sender, edge}
        states.jsonl              {stream, n, topic, payload, enc, ...}
        vision/<모델>/results.jsonl
                                  {schema_version, node_id, zone_id, timestamp,
                                   frame_ref{camera_id, sequence_id, timestamp},
                                   n, frame_file, stream, run, model, model_file,
                                   width, height, infer_ms, prompt,
                                   detections[{label, confidence, bbox, track_id,
                                               held, label_raw, depth_m, ...}]}

Redis 쪽은 같은 `results.jsonl` 한 줄이 `vision_stream:<소스>:<모델>` 항목의
`result` 칸에 그대로 들어 있고, `header` 칸의 `stream_entry_id` 가 그 결과를 만든
원본 프레임(`camera_stream:<소스>` 항목)을 가리킨다. 그래서 디스크 경로와 Redis
경로가 **같은 자료형**으로 모이고, 이 모듈은 둘을 한 함수로 받는다.

양보하지 않는 네 가지
---------------------
1. **검증되지 않은 추론 결과를 정답으로 승격하지 않는다**(AI-L-02). 비전 결과에서
   나온 후보는 **예외 없이** `AUTO_INFERENCE` 다. 이 모듈에는 그것을 확인 상태로
   바꾸는 함수가 없다 — 확인은 운영자 수정(`tools/fms_console/twin.py`) 또는 외부
   라벨 출처의 일이고, 여기서 바꿀 수 있게 두면 "자동 추론을 학습 정답으로 쓰지
   않는다"가 한 줄로 무너진다. 그래서 이 입구만으로는 `ThresholdLearningProvider`
   가 **아무것도 학습하지 않는다**(확인 표본이 0이므로 `no_confirmed_samples`).
   그것이 고장이 아니라 설계다.
2. **`held` 검출은 후보가 아니다.** 데모의 안정화(`config stabilize`)는 그 장에서
   **못 잡은** 검출을 마지막 박스로 유지하며 `held: true` 를 붙인다. 그것은 이
   프레임의 관측이 아니라 직전 관측의 잔상이다. 후보로 넣으면 같은 관측 하나가
   여러 프레임에서 센 것이 되어 임계가 그 쪽으로 끌려간다. 회전 스캔의
   `duplicate_of_prev` 와 같은 종류의 함정이고 같은 이유로 막는다.
3. **기기·입력 조건별로 갈린다**(AI-L-09). 같은 라벨이라도 소스·카메라·해상도·
   **모델**·프롬프트 모드가 다르면 다른 묶음이다. 특히 모델을 묶음 키에 넣는
   이유: 검출 신뢰도의 분포는 모델마다 다르고, 섞으면 한 모델의 임계가 다른
   모델의 표본으로 움직인다. 반면 `run`·`zone_id`·`node_id` 는 입력 조건이
   **아니므로** 묶음 키에 넣지 않는다 — 넣으면 실행을 새로 띄울 때마다 묶음이
   갈려 표본이 모이지 않는다. 대신 둘 다 `frame_ref` 로 되짚을 수 있게 남긴다.
4. **미측정은 0이 아니다.** 해상도가 적혀 있지 않으면 `None` 이고 가속기는 이
   규약에 아예 없으므로 언제나 `None` 이다 — 지어내지 않는다. 읽지 못한 줄은
   조용히 사라지지 않고 사유와 함께 센다.

픽셀은 담지 않는다
------------------
프레임 바이트·오버레이·depth 배열은 미디어 경로의 것이다(AI-C-08). 후보에는
`frame_ref` 와 신뢰도만 남고, 원본이 필요하면 그 참조로 되짚는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Protocol, Sequence

from mission_runtime.continual.stream_learning import (
    CandidateOrigin,
    InputConditions,
    StreamSample,
)

#: 후보가 되지 못한 사유 토큰. `':'` 앞이 토큰, 뒤가 자료다(기존 규약).
REASON_FRAME_NOT_STORED = "frame_not_stored"
REASON_HELD_DETECTION = "detection_held_from_previous_frame"
REASON_NO_LABEL = "detection_without_label"
REASON_NO_CONFIDENCE = "detection_without_confidence"
REASON_DUPLICATE_RESULT = "duplicate_result_for_frame"
REASON_MALFORMED_RECORD = "malformed_record"
REASON_NO_DETECTIONS = "result_without_detections"
REASON_UNKNOWN_FRAME = "result_without_frame_record"

INGEST_REASONS: tuple[str, ...] = (
    REASON_FRAME_NOT_STORED,
    REASON_HELD_DETECTION,
    REASON_NO_LABEL,
    REASON_NO_CONFIDENCE,
    REASON_DUPLICATE_RESULT,
    REASON_MALFORMED_RECORD,
    REASON_NO_DETECTIONS,
    REASON_UNKNOWN_FRAME,
)

#: 옛 결과 파일의 검출 칸 이름 → 지금 이름. 데모의 `DET_RENAME` 과 같은 사전이다.
#: 옛 기록도 읽히게 해 두는 이유는 조용히 빈 결과가 나오는 것이 가장 나쁘기
#: 때문이다 — 읽을 수 없으면 사유가 나와야 한다.
_DETECTION_ALIASES: Mapping[str, str] = {
    "xyxy": "bbox",
    "name": "label",
    "cls": "class_id",
    "conf": "confidence",
    "name_raw": "label_raw",
}

#: 묶음 키에 싣는 추가 조건의 칸 이름. `InputConditions.extra` 는 자유 문자열이고
#: 이 세 이름은 이 모듈이 정한 것이다.
EXTRA_MODEL = "model"
EXTRA_PROMPT = "prompt"
EXTRA_PRODUCER_TIER = "producer_tier"


# -- 사유를 가진 결손 ---------------------------------------------------------


@dataclass(frozen=True)
class Rejection:
    """후보가 되지 못한 자료 1건과 그 사유."""

    locator: str
    reason: str


@dataclass(frozen=True)
class IngestResult:
    """한 번 읽어 들인 결과. **읽은 양과 버린 양을 함께 낸다.**

    버린 것을 세지 않으면 "후보가 적다"가 자료가 적은 것인지 전부 걸러진 것인지
    구분되지 않는다. 그 구분이 없으면 임계 학습이 왜 안 도는지 알 수 없다.
    """

    samples: tuple[StreamSample, ...] = ()
    rejected: tuple[Rejection, ...] = ()
    #: 읽어 본 줄 수(프레임 메타 / 비전 결과). 파일이 없으면 0이고 그것은 사실이다.
    frames_read: int = 0
    results_read: int = 0

    def reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rejection in self.rejected:
            token = rejection.reason.split(":", 1)[0]
            counts[token] = counts.get(token, 0) + 1
        return counts

    def merge(self, other: "IngestResult") -> "IngestResult":
        return IngestResult(
            samples=self.samples + other.samples,
            rejected=self.rejected + other.rejected,
            frames_read=self.frames_read + other.frames_read,
            results_read=self.results_read + other.results_read,
        )


# -- 자료형 -------------------------------------------------------------------


@dataclass(frozen=True)
class FrameRecord:
    """`frames.jsonl` 한 줄. 그림 바이트는 담지 않는다.

    `frame_file` 이 `None` 인 줄은 **디스크에 쓰지 못한 프레임**이다(규약이 그렇게
    적는다). 그 프레임은 되짚을 원본이 없으므로 후보의 재료가 되지 못한다 —
    학습 후보의 조건은 원본 관측을 다시 찾을 수 있는 것이다(AI-C-03).
    """

    stream: str
    n: int
    frame_file: str | None = None
    received_at: str | None = None
    via: str | None = None
    received_by: str | None = None
    #: 보낸 쪽이 준 정보 그대로. 해석하지 않는다.
    sender: Mapping[str, Any] = field(default_factory=dict)

    @property
    def stored(self) -> bool:
        return bool(self.frame_file)

    @classmethod
    def from_header(cls, raw: Mapping[str, Any]) -> "FrameRecord":
        stream = _text(raw.get("stream"))
        number = _integer(raw.get("n"))
        if not stream or number is None:
            raise ValueError("frame header needs 'stream' and 'n'")
        sender = raw.get("sender")
        return cls(
            stream=stream,
            n=number,
            frame_file=_text(raw.get("frame_file")) or None,
            received_at=_text(raw.get("received_at")) or None,
            via=_text(raw.get("via")) or None,
            received_by=_text(raw.get("received_by")) or None,
            sender=dict(sender) if isinstance(sender, Mapping) else {},
        )


@dataclass(frozen=True)
class Detection:
    """비전 결과의 검출 1건 — 후보 하나의 재료다.

    `held` 는 **이 장에서 실제로 잡은 것이 아니라** 직전 박스를 유지한 표시다.
    `confidence` 가 없으면 `None` 이고 0이 아니다.
    """

    index: int
    label: str | None = None
    confidence: float | None = None
    held: bool = False
    track_id: str | None = None
    label_raw: str | None = None

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], index: int) -> "Detection":
        row = {_DETECTION_ALIASES.get(str(k), str(k)): v for k, v in raw.items()}
        track = row.get("track_id")
        return cls(
            index=index,
            label=_text(row.get("label")) or None,
            confidence=_number(row.get("confidence")),
            held=bool(row.get("held")),
            track_id=None if track is None else str(track),
            label_raw=_text(row.get("label_raw")) or None,
        )


@dataclass(frozen=True)
class VisionResult:
    """`results.jsonl` 한 줄 / Redis `vision_stream` 항목의 `result` 칸 하나.

    `run` 과 `node_id`·`zone_id` 는 되짚기용으로 들고 다니지만 **묶음 키에는
    들어가지 않는다**(모듈 docstring 3번).
    """

    stream: str
    model: str
    n: int
    run: str | None = None
    frame_file: str | None = None
    width: int | None = None
    height: int | None = None
    prompt: str | None = None
    producer_tier: str | None = None
    camera_id: str | None = None
    timestamp: str | None = None
    node_id: str | None = None
    zone_id: str | None = None
    #: 원본 프레임을 가리키는 Redis 항목 ID. 디스크 경로에서는 `None` 이다.
    stream_entry_id: str | None = None
    detections: tuple[Detection, ...] = ()

    @classmethod
    def from_result(
        cls, raw: Mapping[str, Any], *, stream_entry_id: str | None = None
    ) -> "VisionResult":
        """결과 한 줄을 받아들인다. 필수 세 칸이 없으면 거절한다.

        `stream`·`model`·`n` 이 없으면 어느 기기의 어느 모델이 어느 프레임을 본
        것인지 말할 수 없고, 그 셋이 없는 후보는 되짚을 수 없다.
        """
        stream = _text(raw.get("stream")) or _text(raw.get("source"))
        model = _text(raw.get("model"))
        # 옛 결과 파일은 프레임 번호를 `frame` 에 적는다.
        number = _integer(raw.get("n"))
        if number is None:
            number = _integer(raw.get("frame"))
        if not stream or not model or number is None:
            raise ValueError("vision result needs 'stream', 'model' and 'n'")

        width, height = _number(raw.get("width")), _number(raw.get("height"))
        if width is None or height is None:
            width, height = _image_wh(raw.get("image_wh"))

        frame_ref = raw.get("frame_ref")
        camera_id = None
        if isinstance(frame_ref, Mapping):
            camera_id = _text(frame_ref.get("camera_id")) or None

        producer = raw.get("producer")
        tier = None
        if isinstance(producer, Mapping):
            tier = _text(producer.get("tier")) or None

        raw_detections = raw.get("detections")
        detections = tuple(
            Detection.from_raw(row, index)
            for index, row in enumerate(raw_detections or ())
            if isinstance(row, Mapping)
        )

        return cls(
            stream=stream,
            model=model,
            n=number,
            run=_text(raw.get("run")) or None,
            frame_file=_text(raw.get("frame_file")) or None,
            width=None if width is None else int(width),
            height=None if height is None else int(height),
            prompt=_text(raw.get("prompt")) or None,
            producer_tier=tier,
            camera_id=camera_id,
            timestamp=_text(raw.get("timestamp")) or None,
            node_id=_text(raw.get("node_id")) or None,
            zone_id=_text(raw.get("zone_id")) or None,
            stream_entry_id=stream_entry_id,
            detections=detections,
        )

    # -- 묶음 키와 되짚기 참조 ------------------------------------------------

    @property
    def conditions(self) -> InputConditions:
        """이 결과가 속한 조건 묶음(AI-L-09).

        `accelerator_id` 는 이 규약이 보고하지 않으므로 **언제나 `None`** 이다 —
        모르는 것을 채우면 "어느 가속기에서 나빠졌는가"를 되짚을 수 없다.
        """
        extra: list[tuple[str, str]] = [(EXTRA_MODEL, self.model)]
        if self.prompt:
            extra.append((EXTRA_PROMPT, self.prompt))
        if self.producer_tier:
            extra.append((EXTRA_PRODUCER_TIER, self.producer_tier))
        resolution = (
            (self.width, self.height)
            if self.width is not None and self.height is not None
            else None
        )
        return InputConditions(
            device_id=self.stream,
            camera_id=self.camera_id or self.stream,
            resolution=resolution,
            accelerator_id=None,
            extra=tuple(sorted(extra)),
        )

    @property
    def frame_ref(self) -> str:
        """원본 관측을 되짚는 참조(AI-C-03).

        실행 폴더와 Redis 항목 ID 를 함께 싣는다 — 디스크에 남은 그림과 Redis 의
        그 프레임이 같은 것이고, 둘 중 어느 쪽이 남아 있어도 되짚을 수 있어야 한다.
        """
        tail = self.frame_file or f"n={self.n}"
        base = "/".join(part for part in (self.stream, self.run, tail) if part)
        return base if self.stream_entry_id is None else f"{base}@{self.stream_entry_id}"

    @property
    def observed_at(self) -> float | None:
        return _epoch(self.timestamp)


# -- 결과 → 후보 --------------------------------------------------------------


def samples_from_result(
    result: VisionResult,
    *,
    frame: FrameRecord | None = None,
    require_stored_frame: bool = True,
) -> IngestResult:
    """비전 결과 하나의 검출들을 **자동 추론 후보**로 바꾼다.

    `origin` 을 인자로 받지 않는다. 받게 두면 호출자가 자동 추론을 확인 상태로
    올릴 수 있고, 그것이 AI-L-02 가 금지하는 바로 그 동작이다.

    `feature` 와 `similarity`
    -------------------------
    이 파이프라인은 특징 벡터를 결과에 싣지 않는다 — 검출기가 내는 수치는
    **신뢰도** 하나다. 그래서 벡터를 지어내지 않고 `(confidence,)` 한 칸으로 두고
    같은 값을 `similarity` 에도 싣는다. `similarity` 에 싣는 것이 뜻 있는 이유:
    `ThresholdLearningProvider` 가 조정하는 값이 **검출 임계**이고, 운영에서 그
    임계와 견주는 수치가 바로 이 신뢰도다. 프로토타입 학습
    (`PrototypeLearningProvider`)은 이 입구의 후보로는 뜻 있는 결과를 내지 못한다
    — 1차원 "벡터" 의 평균은 프로토타입이 아니다. 그 사실을 숨기지 않는다.
    """
    # 어느 이유로 빠지든 **결과 한 줄은 읽은 것이다** — `results_read` 를 세지
    # 않으면 "읽은 양" 과 "버린 양" 이 어긋나고, 그 둘을 견주는 것이 이 자료형의
    # 유일한 쓸모다.
    if require_stored_frame:
        unstored = (not frame.stored) if frame is not None else (not result.frame_file)
        if unstored:
            return IngestResult(
                rejected=(Rejection(result.frame_ref, REASON_FRAME_NOT_STORED),),
                results_read=1,
            )

    if not result.detections:
        return IngestResult(
            rejected=(Rejection(result.frame_ref, REASON_NO_DETECTIONS),),
            results_read=1,
        )

    conditions = result.conditions
    frame_ref = result.frame_ref
    observed_at = result.observed_at
    if observed_at is None and frame is not None:
        observed_at = _epoch(frame.received_at)

    samples: list[StreamSample] = []
    rejected: list[Rejection] = []
    for detection in result.detections:
        locator = f"{frame_ref}#{result.model}:{detection.index}"
        if detection.held:
            # 이 장의 관측이 아니다 — 직전 박스의 잔상이다(모듈 docstring 2번).
            rejected.append(Rejection(locator, REASON_HELD_DETECTION))
            continue
        if not detection.label:
            rejected.append(Rejection(locator, REASON_NO_LABEL))
            continue
        if detection.confidence is None:
            # 신뢰도 없는 검출은 임계 학습의 재료가 아니다. 0으로 채우지 않는다.
            rejected.append(Rejection(locator, REASON_NO_CONFIDENCE))
            continue
        confidence = float(detection.confidence)
        samples.append(
            StreamSample(
                sample_id=locator,
                conditions=conditions,
                label=detection.label,
                feature=(confidence,),
                origin=CandidateOrigin.AUTO_INFERENCE,
                frame_ref=frame_ref,
                confidence=confidence,
                similarity=confidence,
                observed_at=observed_at,
            )
        )
    return IngestResult(samples=tuple(samples), rejected=tuple(rejected), results_read=1)


# -- 디스크: 실행 폴더 --------------------------------------------------------

FRAMES_FILE = "frames.jsonl"
STATES_FILE = "states.jsonl"
VISION_DIR = "vision"
RESULTS_FILE = "results.jsonl"


def read_jsonl(path: Path) -> Iterator[tuple[int, Mapping[str, Any] | None]]:
    """줄 단위 JSON 을 읽는다. **못 읽은 줄도 자리를 남긴다.**

    깨진 줄에서 예외를 올리지 않는 이유: 이 파일들은 돌고 있는 운영 프로세스가
    append 중이고 마지막 줄이 반쪽일 수 있다. 한 줄 때문에 수집이 멈추면 학습
    장애가 아니라 수집 장애가 되고, 그것도 운영을 흔들 이유가 없다.
    """
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except ValueError:
                yield number, None
                continue
            yield number, row if isinstance(row, Mapping) else None


def read_frames(run_dir: Path) -> tuple[dict[int, FrameRecord], IngestResult]:
    """`frames.jsonl` 을 프레임 번호별로 읽는다."""
    frames: dict[int, FrameRecord] = {}
    rejected: list[Rejection] = []
    read = 0
    path = Path(run_dir) / FRAMES_FILE
    for number, row in read_jsonl(path):
        read += 1
        if row is None:
            rejected.append(Rejection(f"{path.name}:{number}", REASON_MALFORMED_RECORD))
            continue
        try:
            record = FrameRecord.from_header(row)
        except ValueError:
            rejected.append(Rejection(f"{path.name}:{number}", REASON_MALFORMED_RECORD))
            continue
        frames[record.n] = record
    return frames, IngestResult(rejected=tuple(rejected), frames_read=read)


def models_in_run(run_dir: Path) -> tuple[str, ...]:
    """이 실행 폴더에 결과가 있는 모델 이름. 목록은 **발견**이고 선언이 아니다."""
    vision = Path(run_dir) / VISION_DIR
    if not vision.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in vision.iterdir()
            if child.is_dir() and (child / RESULTS_FILE).is_file()
        )
    )


def read_run(
    run_dir: Path,
    *,
    models: Sequence[str] | None = None,
    require_stored_frame: bool = True,
) -> IngestResult:
    """실행 폴더 하나에서 후보를 읽는다.

    `models=None` 이면 그 폴더에 **있는** 모델 전부다. 모델 이름을 코드가 알지
    않는다 — 새 모델이 생기면 폴더가 하나 늘고 이 함수는 그대로다.

    프레임 메타와 결과는 프레임 번호(`n`)로 짝짓는다. 짝이 없는 결과는 버리지 않고
    `REASON_UNKNOWN_FRAME` 으로 남긴다 — `frames.jsonl` 이 아직 flush 되지 않아
    생기는 정상적인 어긋남이고, 그 사실을 세어 둬야 "결과만 있고 프레임이 없다"를
    자료 결손과 구분할 수 있다.
    """
    run_dir = Path(run_dir)
    frames, outcome = read_frames(run_dir)
    chosen = tuple(models) if models is not None else models_in_run(run_dir)

    for model in chosen:
        path = run_dir / VISION_DIR / model / RESULTS_FILE
        seen: set[tuple[str, int]] = set()
        for number, row in read_jsonl(path):
            if row is None:
                outcome = outcome.merge(
                    IngestResult(
                        rejected=(
                            Rejection(f"{model}/{RESULTS_FILE}:{number}",
                                      REASON_MALFORMED_RECORD),
                        ),
                        results_read=1,
                    )
                )
                continue
            try:
                result = VisionResult.from_result(row)
            except ValueError:
                outcome = outcome.merge(
                    IngestResult(
                        rejected=(
                            Rejection(f"{model}/{RESULTS_FILE}:{number}",
                                      REASON_MALFORMED_RECORD),
                        ),
                        results_read=1,
                    )
                )
                continue
            if result.run is None:
                result = _with_run(result, run_dir.name)
            key = (result.model, result.n)
            if key in seen:
                # `--overwrite` 로 다시 쓴 파일이나 동시 append 가 같은 번호를 두
                # 번 남길 수 있다. 같은 관측을 두 번 세면 임계가 그만큼 끌려간다.
                outcome = outcome.merge(
                    IngestResult(
                        rejected=(Rejection(result.frame_ref, REASON_DUPLICATE_RESULT),),
                        results_read=1,
                    )
                )
                continue
            seen.add(key)
            frame = frames.get(result.n)
            if frame is None and require_stored_frame and not result.frame_file:
                outcome = outcome.merge(
                    IngestResult(
                        rejected=(Rejection(result.frame_ref, REASON_UNKNOWN_FRAME),),
                        results_read=1,
                    )
                )
                continue
            outcome = outcome.merge(
                samples_from_result(
                    result, frame=frame, require_stored_frame=require_stored_frame
                )
            )
    return outcome


@dataclass(frozen=True)
class RunPath:
    """저장 뿌리 아래의 실행 폴더 하나. `source` 는 폴더 이름이 그대로다."""

    source: str
    run: str
    path: Path


def discover_runs(root: Path, *, sources: Iterable[str] | None = None) -> tuple[RunPath, ...]:
    """`stream_data/` 아래의 실행 폴더를 찾는다.

    소스 이름(`robot1`·`drone`·`cam360` …)을 코드가 알지 않는다 — 폴더가 목록이고
    새 기기는 폴더 하나다(AI-L-09 의 "장치별로 구분 가능").
    """
    root = Path(root)
    if not root.is_dir():
        return ()
    wanted = None if sources is None else {str(s) for s in sources}
    found: list[RunPath] = []
    for source_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if wanted is not None and source_dir.name not in wanted:
            continue
        for run_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            found.append(RunPath(source_dir.name, run_dir.name, run_dir))
    return tuple(found)


def read_stream_data(
    root: Path,
    *,
    sources: Iterable[str] | None = None,
    models: Sequence[str] | None = None,
    require_stored_frame: bool = True,
) -> IngestResult:
    """저장 뿌리 전체에서 후보를 읽는다. 실행마다의 결과를 하나로 합친다.

    실행이 갈려도 **묶음은 갈리지 않는다** — `run` 은 입력 조건이 아니므로 같은
    기기·카메라·해상도·모델의 표본이 여러 실행에 걸쳐 한 묶음에 쌓인다.
    """
    outcome = IngestResult()
    for run in discover_runs(root, sources=sources):
        outcome = outcome.merge(
            read_run(run.path, models=models, require_stored_frame=require_stored_frame)
        )
    return outcome


# -- Redis: live 스트림 -------------------------------------------------------


class StreamEntryReader(Protocol):
    """Redis 스트림에서 최근 항목을 읽는 경계.

    `redis` 를 import 하지 않는다. 이 프로토콜을 만족하는 무엇이든 받으므로
    전송·저장 기술이 provider 경계 밖으로 새지 않고(AI-C-04), 시험은 가짜 하나로
    같은 경로를 돈다.
    """

    def xrevrange(
        self, name: str, max: str = "+", min: str = "-", count: int | None = None
    ) -> list[tuple[Any, Mapping[Any, Any]]]: ...


def vision_stream_key(device_id: str, model: str) -> str:
    """`vision_stream:<소스>:<모델>` — 규약이 정한 이름이다."""
    return f"vision_stream:{device_id}:{model}"


def read_vision_stream(
    client: StreamEntryReader,
    device_id: str,
    model: str,
    *,
    count: int = 100,
    require_stored_frame: bool = False,
) -> IngestResult:
    """`vision_stream:<소스>:<모델>` 의 최근 항목을 후보로 읽는다.

    `require_stored_frame` 의 기본값이 디스크 경로와 **다르다**(False). live 항목은
    `header.stream_entry_id` 로 Redis 의 원본 프레임을 가리키므로, 디스크에 그림이
    없어도 되짚을 참조가 있다. 그 참조를 `frame_ref` 에 함께 싣는 것이 그 근거다.

    Redis 가 꺼져 있거나 키가 없는 것은 장애가 아니라 **빈 결과**다(규약: "Redis 가
    꺼져 있어도 스트림은 멈추지 않는다"). 예외를 사유로 바꿔 돌려주므로 수집 실패가
    호출자의 운영 경로를 멈추지 않는다(AI-L-09).
    """
    key = vision_stream_key(device_id, model)
    try:
        entries = client.xrevrange(key, count=count) or []
    except Exception as error:      # 수집 실패가 운영을 멈추지 않는다
        return IngestResult(
            rejected=(Rejection(key, f"{REASON_MALFORMED_RECORD}:{type(error).__name__}"),)
        )

    outcome = IngestResult()
    seen: set[tuple[str, int]] = set()
    for entry_id, fields in entries:
        locator = f"{key}@{_decode(entry_id)}"
        payload = _entry_json(fields, "result")
        if payload is None:
            outcome = outcome.merge(
                IngestResult(
                    rejected=(Rejection(locator, REASON_MALFORMED_RECORD),), results_read=1
                )
            )
            continue
        header = _entry_json(fields, "header") or {}
        source_entry = _text(header.get("stream_entry_id")) or _decode(entry_id)
        try:
            result = VisionResult.from_result(payload, stream_entry_id=source_entry)
        except ValueError:
            outcome = outcome.merge(
                IngestResult(
                    rejected=(Rejection(locator, REASON_MALFORMED_RECORD),), results_read=1
                )
            )
            continue
        key_seen = (result.model, result.n)
        if key_seen in seen:
            outcome = outcome.merge(
                IngestResult(
                    rejected=(Rejection(result.frame_ref, REASON_DUPLICATE_RESULT),),
                    results_read=1,
                )
            )
            continue
        seen.add(key_seen)
        outcome = outcome.merge(
            samples_from_result(result, require_stored_frame=require_stored_frame)
        )
    return outcome


# -- 작은 도구 ----------------------------------------------------------------


def _with_run(result: VisionResult, run: str) -> VisionResult:
    from dataclasses import replace

    return replace(result, run=run)


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)


def _entry_json(fields: Mapping[Any, Any], name: str) -> Mapping[str, Any] | None:
    """Redis 항목의 한 칸을 JSON 으로. 칸 이름이 bytes 인 경우도 받는다."""
    for key, value in fields.items():
        if _decode(key) != name:
            continue
        try:
            row = json.loads(_decode(value))
        except ValueError:
            return None
        return row if isinstance(row, Mapping) else None
    return None


def _text(value: Any) -> str:
    if value is None or isinstance(value, (Mapping, list, tuple, bool)):
        return ""
    return str(value).strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _image_wh(value: Any) -> tuple[float | None, float | None]:
    """옛 결과 파일의 `image_wh: [w, h]`."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return _number(value[0]), _number(value[1])
    return None, None


def _epoch(text: str | None) -> float | None:
    """ISO 8601 → epoch 초. 못 읽으면 `None` 이고 0이 아니다."""
    if not text:
        return None
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        pass
    # 옛 기록의 epoch 글자(360 폼 timestamp)도 같은 뜻이다.
    number = _number(text)
    return None if number is None else float(number)
