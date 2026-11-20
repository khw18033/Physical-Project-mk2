"""실증 배치의 데이터 스트림에서 탐지를 받아 온다.

현장 지형은 이렇다(`physical_demo` 의 `data_stream` 가지).

    로봇2 · 드론 · 360 카메라 → server_stream_multi_source.py → Redis :6380 + 디스크
                                                                  ↓
                                              vision/vision_infer.py (YOLOE · UniDepth · MoGe2)

그래서 **우리가 카메라를 직접 열지 않는다.** 촬영과 추론은 그쪽이 이미 하고 있고,
우리 몫은 그 결과를 뷰어 계약으로 옮기는 일이다 — 같은 프레임에 추론기를 두 번
돌리면 GPU 를 두 배로 쓰고 두 화면이 서로 다른 탐지를 말한다(AI-C-19 · 같은 사실에
주인이 둘이 되지 않게).

## 읽는 자리

    camera_stream:<소스>              원본 프레임 (우리는 **읽지 않는다** — 픽셀은
                                      미디어 경로의 몫이다, AI-C-08)
    vision_stream:<소스>:<모델>        탐지 결과. 필드 `result`(JSON) · `header`(JSON)

소스는 `cam360` · `drone` · `robot1` · `robot2` 이고, 이 배치에서 robot1 은 pi7(go1),
robot2 는 pi1(ep) 이 중계한다.

## 칸 이름이 이미 맞는다

그쪽 `result.detections[]` 는 `{class_id, label, confidence, bbox, …}` 이고 우리
`schemas/ai/detection-result.schema.json` 의 `detections[]` 필수 칸은
`label · confidence · bbox · camera_id` 다. **탐지 한 줄에서 옮길 것은 `camera_id`
하나뿐**이라 번역다운 번역이 없다 — 이름을 서로 맞춰 둔 결과다(AI-C-01).

## 머리 칸은 받아 적지, 새로 만들지 않는다

2026-11-04 실제 스트림으로 검증기를 돌려 보니 **머리 쪽 네 칸이 우리 계약과
어긋나 있었다**(`frame_ref` 모양 · `emitted_at` 시간대 · `producer` 네 칸 ·
`bbox_format` 어휘 — 모두 10 군데). 그쪽 `v2_record()` 가 이미 계약과 같은 모양의
`frame_ref`(camera_id · sequence_id · timestamp)와 `emitted_at`(+09:00),
`producer.tier/kind` 를 적어 두므로 **그 값을 그대로 옮긴다.** 우리가 번호와 시각을
새로 지으면 같은 사실에 주인이 둘이 되고, 그 번호는 아무 원본도 가리키지 않는다
(AI-C-03). 참조가 없는 결과는 보내지 않고 사유별로 센다.

데모 쪽 포인터(Redis 항목 id · 저장 파일 경로)는 `last_pointer` 에만 남고 와이어로는
나가지 않는다 — 공통 데이터 사전에 등록된 이름이 아니다(AI-C-01).

## 없으면 없다고 말한다

`redis` 미설치 · 서버 꺼짐 · 스트림 없음은 **전부 다른 사유**이고, 어느 경우에도
빈 탐지를 지어내지 않는다(AI-C-05).

implements: AI-C-01, AI-C-03, AI-C-04, AI-C-05, AI-C-08, AI-E-01, AI-S-02
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

#: 실증 배치의 소스 이름 → 우리가 아는 장치. **데이터다** — 새 소스는 한 줄이다.
DEFAULT_SOURCE_MAP: dict[str, str] = {
    "robot1": "go1-001",
    "robot2": "ep-001",
    "drone": "x500-001",
    "cam360": "cam360-001",
}

#: 현장 시각대. 계약의 `emitted_at` 은 `+09:00` 이다.
_KST = timezone(timedelta(hours=9))

REASON_NO_PACKAGE = "redis_package_missing"
REASON_NO_SERVER = "redis_unreachable"
REASON_NO_STREAM = "no_vision_stream"
#: 장치가 원본 관측 참조를 붙이지 않은 결과. **버리고 센다.**
#:
#: 한때 스트림 항목 id 로 대신 채우려 했고, 그것이 틀린 이유를 남겨 둔다.
#: `frame_ref` 는 우리 쪽에서 **"한 번 봤다"의 단위**다 — `perception/uncertainty.py`
#: 가 `(source_group, frame_ref)` 로 근거를 접어, 같은 장을 탐지기와 분류기가
#: 각각 읽은 것을 한 번으로 센다. 그 단위를 스트림 항목으로 바꾸면 같은 장의
#: 결과 둘이 서로 다른 항목에 들어가 **두 번 본 것으로 세어지고**, 근거 충분도가
#: 실제보다 커져 확정이 모자란 근거에서 나온다. 번호를 지어내지 않는 것은 예의가
#: 아니라 그 셈의 전제다(AI-C-03 · AI-S-03).
#:
#: 그래서 이 수가 0 이 아니면 **장비 쪽 프레임 헤더를 고쳐야 한다**. 우리가
#: 메울 구멍이 아니다 — `docs/integration-handover.md` 의 하드웨어 항목이다.
REASON_NO_FRAME_REF = "no_device_frame_ref"

#: 우리 계약이 요구하는 세 칸(`schemas/ai/frame-reference.schema.json`).
_FRAME_REF_KEYS = ("camera_id", "sequence_id", "timestamp")


@dataclass
class RedisDetectionSource:
    """`vision_stream:<소스>:<모델>` 하나를 뒤에서부터 따라 읽는다.

    마지막으로 본 항목 id 를 들고 있다가 그 뒤만 가져온다 — 같은 결과를 두 번
    내보내면 화면의 탐지 수가 실제보다 많아진다.
    """

    url: str = "redis://127.0.0.1:6380/0"
    model: str = "yoloe"
    sources: tuple[str, ...] = ("robot1", "robot2", "drone", "cam360")
    source_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SOURCE_MAP))
    client: object | None = None
    reason: str | None = None
    _cursor: dict[str, bytes] = field(default_factory=dict)
    seen: int = 0
    #: 사유별로 **버린 결과의 수**. 조용히 버리면 "탐지가 안 나온다" 와
    #: "탐지는 나왔는데 참조가 없어 못 보낸다" 가 화면에서 같아 보인다.
    dropped: dict[str, int] = field(default_factory=dict)
    #: 마지막으로 읽은 데모 쪽 포인터(스트림 항목 id · 저장 파일). **와이어로 내보내지
    #: 않는다** — 공통 데이터 사전에 등록된 이름이 아니다(AI-C-01). 로그·재현용이다.
    last_pointer: dict[str, dict] = field(default_factory=dict)

    def connect(self) -> bool:
        """붙어 본다. 실패를 예외로 올리지 않고 **사유로** 남긴다."""
        try:
            import redis  # noqa: PLC0415
        except ImportError:
            self.reason = REASON_NO_PACKAGE
            return False
        try:
            client = redis.Redis.from_url(self.url, socket_connect_timeout=2,
                                          socket_timeout=3)
            client.ping()
        except Exception as exc:                              # noqa: BLE001
            self.reason = f"{REASON_NO_SERVER}:{type(exc).__name__}"
            return False
        self.client = client
        self.reason = None
        return True

    def stream_key(self, source: str) -> str:
        return f"vision_stream:{source}:{self.model}"

    def available_sources(self) -> list[str]:
        """실제로 결과가 쌓이고 있는 소스만. 선언이 아니라 **관측**이다."""
        if self.client is None:
            return []
        live = []
        for source in self.sources:
            try:
                if self.client.exists(self.stream_key(source)):   # type: ignore[attr-defined]
                    live.append(source)
            except Exception:                                  # noqa: BLE001
                continue
        return live

    def poll(self, *, count: int = 4) -> list[tuple[str, dict]]:
        """새로 들어온 결과만. `(장치 id, payload)` 목록이고 없으면 빈 목록이다."""
        if self.client is None:
            return []
        out: list[tuple[str, dict]] = []
        for source in self.sources:
            key = self.stream_key(source)
            try:
                cursor = self._cursor.get(source)
                if cursor is None:
                    # 처음에는 **가장 최근 한 건**만 본다. 과거를 통째로 재생하면
                    # 화면이 지나간 탐지로 가득 찬다.
                    rows = self.client.xrevrange(key, count=1)     # type: ignore[attr-defined]
                    rows = list(reversed(rows))
                else:
                    rows = self.client.xread({key: cursor}, count=count)  # type: ignore[attr-defined]
                    rows = rows[0][1] if rows else []
            except Exception:                                  # noqa: BLE001
                continue
            for entry_id, fields in rows:
                self._cursor[source] = entry_id
                payload = self._to_payload(source, entry_id, fields)
                if payload is not None:
                    self.seen += 1
                    out.append((self.source_map.get(source, source), payload))
        return out

    def _to_payload(self, source: str, entry_id: bytes, fields: dict) -> dict | None:
        raw = fields.get(b"result") or fields.get("result")
        header_raw = fields.get(b"header") or fields.get("header")
        if raw is None:
            return None
        try:
            result = json.loads(raw if isinstance(raw, (str, bytes)) else str(raw))
            header = json.loads(header_raw) if header_raw else {}
        except (ValueError, TypeError):
            return None

        camera_id = self.source_map.get(source, source)
        # 원본 관측 참조는 **그 장을 처음 손에 넣은 기기**가 붙인다. 우리가 번호와
        # 시각을 새로 만들면 두 번째 주인이 생긴다(AI-C-03 · frame-reference).
        #
        # 없으면 보내지 않고 센다 — 지어낸 참조는 아무 원본도 가리키지 못하고,
        # 그보다 나쁘게 **근거 셈을 틀리게 한다**(위 REASON_NO_FRAME_REF 주석).
        frame_ref = _frame_ref(result)
        if frame_ref is None:
            self.dropped[REASON_NO_FRAME_REF] = self.dropped.get(REASON_NO_FRAME_REF, 0) + 1
            return None
        stream_ref = _stream_ref(self.stream_key(source), entry_id, header)
        self.last_pointer[source] = {
            "stream_key": self.stream_key(source),
            "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id),
            "stream_entry_id": header.get("stream_entry_id"),
            "frame_file": header.get("frame_file"),
            "n": header.get("n"),
        }

        detections = []
        for det in result.get("detections") or ():
            bbox = det.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            row = {
                "label": str(det.get("label", "")),
                "confidence": round(float(det.get("confidence", 0.0)), 4),
                "bbox": [float(v) for v in bbox[:4]],
                "camera_id": camera_id,
            }
            # 깊이는 **있을 때만** 실린다 — 없는 칸을 0 으로 채우지 않는다.
            if det.get("depth_m") is not None:
                row["depth_m"] = float(det["depth_m"])
            detections.append(row)

        width, height = _image_size(result)
        upstream = result.get("producer") if isinstance(result.get("producer"), dict) else {}
        body: dict = {
            # 그쪽이 적어 둔 발행 시각을 **그대로** 쓴다. 다시 찍으면 추론이 끝난
            # 시각이 아니라 우리가 읽은 시각이 되어 지연이 실제보다 작아 보인다.
            "emitted_at": _emitted_at(result),
            "model": f"{header.get('model') or self.model}",
            "infer_ms": result.get("infer_ms"),
            # tier·kind 는 **그쪽 선언**이고, optional·label 은 우리가 아는 사실이다.
            # 이 경로는 선택 기능이다 — 데모 스택이 없으면 그냥 꺼진다(AI-C-05).
            "producer": {
                "tier": upstream.get("tier") if upstream.get("tier") in ("device", "edge", "server") else "edge",
                "kind": upstream.get("kind") if upstream.get("kind") in
                        ("safety_minimal", "precise", "derived") else "precise",
                "optional": True,
                "label": f"physical_demo/vision_infer:{source} → mission_runtime/vz_gateway",
            },
            "width": width,
            "height": height,
            "bbox_format": "absolute",
            # 이 경로에는 다중 관측 연계가 없다. 없을 때 연계 신뢰도를 띄우면
            # 없는 근거를 만드는 것이다(AI-S-02).
            "association": "unavailable",
            "detections": detections,
        }
        body["frame_ref"] = frame_ref
        if stream_ref is not None:
            # 되찾을 자리를 함께 싣는다. `frame_ref` 는 **무엇을 봤는가**이고
            # 이것은 **어디서 다시 꺼낼 수 있는가**다 — 다른 질문이라 다른 칸이고,
            # 오류 재현(AI-O-03)이 이 칸을 쓴다. 근거를 접는 쪽은 보지 않는다.
            body["stream_ref"] = stream_ref
        return body

    def note(self) -> str:
        if self.reason is not None:
            return f"detections 발행하지 않음 — {self.reason}"
        live = self.available_sources()
        dropped = ("".join(f" · 버림 {k} {n}" for k, n in sorted(self.dropped.items()))
                   if self.dropped else "")
        if not live:
            return f"detections 발행하지 않음 — {REASON_NO_STREAM} (모델 {self.model}){dropped}"
        return (f"detections 발행 중 — Redis {self.url} · 모델 {self.model} · "
                f"소스 {', '.join(live)} · 누적 {self.seen}{dropped}")


def _frame_ref(result: dict) -> dict | None:
    """그쪽 결과가 들고 온 원본 관측 참조. 세 칸이 다 있을 때만 쓴다.

    `vision_infer.py` 의 `v2_record()` 가 **보내는 쪽 프레임 헤더(§3-5)** 에
    `camera_id` · `sequence_id` 가 둘 다 있을 때만 이 칸을 만든다. 옛 장비(헤더 없는
    MJPEG 등)는 이 칸이 없고, 그때 우리가 번호를 붙이면 그 번호는 아무 원본도
    가리키지 않는다.
    """
    ref = result.get("frame_ref")
    if not isinstance(ref, dict) or any(ref.get(k) in (None, "") for k in _FRAME_REF_KEYS):
        return None
    if not isinstance(ref.get("sequence_id"), int) or isinstance(ref.get("sequence_id"), bool):
        return None
    return {k: ref[k] for k in _FRAME_REF_KEYS}


def _stream_ref(stream_key: str, entry_id, header: dict) -> dict | None:
    """되찾을 수 있는 자리. **프레임 참조의 대체물이 아니다.**

    스트림 항목 id 는 스트림 서버가 쓰므로 장치 메타가 없어도 늘 있다.
    `header.stream_entry_id` 는 `camera_stream:<소스>` 의 원본 장을 가리키고,
    `entry_id` 는 우리가 읽은 `vision_stream:…` 결과 항목을 가리킨다 — 둘은 다른
    스트림의 다른 항목이라 한 칸에 담지 않는다.

    `sequence_id` 를 여기서 만들지 않는다. 항목 id 의 `<ms>-<n>` 을 번호로 바꿔
    적으면 그것은 **장치의 프레임 순번이 아니라 우리가 만든 수**이고, 소비자가
    카메라의 프레임 순번으로 읽는 순간 끊긴 장을 못 보게 된다. 그래서 이 칸은
    `frame_ref` 가 있을 때만 함께 나가고, 없을 때 그 자리를 메우지 않는다.
    """
    result_entry = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id or "")
    source_entry = header.get("stream_entry_id")
    if not result_entry and not source_entry:
        return None
    ref: dict = {"result_stream": stream_key}
    if result_entry:
        ref["result_entry_id"] = result_entry
    if source_entry:
        ref["source_entry_id"] = str(source_entry)
    if header.get("frame_file"):
        ref["frame_file"] = str(header["frame_file"])
    return ref


def _emitted_at(result: dict) -> str:
    """그쪽이 적은 발행 시각. 없을 때만 우리가 **현장 시간대로** 찍는다.

    계약의 시각은 `+09:00` 이다(`detection-result.schema.json`). UTC 로 찍으면
    같은 순간이라도 검증기가 거부한다.
    """
    value = result.get("emitted_at")
    if isinstance(value, str) and value.endswith("+09:00"):
        return value
    return datetime.now(_KST).isoformat(timespec="milliseconds")


def _image_size(result: dict) -> tuple[int, int]:
    size = result.get("image_wh") or result.get("image_size")
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        return int(size[0]), int(size[1])
    return int(result.get("width") or 0), int(result.get("height") or 0)
