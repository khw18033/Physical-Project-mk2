#!/usr/bin/env python3
"""가시화 게이트웨이 — 가시화 대시보드를 **우리 실제 데이터**에 붙인다.

가시화 쪽 대시보드(`khw_VZ/web-dashboard`)는 게이트웨이 주소를 환경변수로 받는다::

    VITE_GATEWAY_WS=ws://127.0.0.1:8899 VITE_GATEWAY_HTTP=http://127.0.0.1:8899 npm run dev

그래서 **화면 코드를 한 줄도 고치지 않고** 목 게이트웨이를 이 서버로 갈아 끼울 수
있다. 그쪽이 그렇게 설계해 두었다(`vite.config.ts` 의 주석 — "접속 주소를 환경변수로
바꿔 끼우는 것이 실제 게이트웨이 전환 방식이다").

## 무엇을 내보내는가 — **실재하는 것만**

| 채널 | 출처 | 실측인가 |
|---|---|---|
| `state` | `FleetModel` 의 선언·탐지·신선도 | 탐지/신선도는 실측, 선언은 선언 |
| `metrics` | `observability/host_resources` | **이 기계에서 실제로 잰 값** |
| `ai_failure` | 게이트웨이 자신의 오류 사건 | 실측 |

`risk_state` · `detections` 는 **내보내지 않는다.** 이 배치에는 위험 입력을 주는
provider 가 없고(`risk.event_input`), 탐지도 지금 도는 파이프라인이 없다. 없는 것을
그럴듯한 숫자로 채우면 이 저장소가 다른 파트에 요구한 것(「없는 근거를 만들지
말라」)을 우리가 먼저 어기는 것이다 — 빈 채로 두고 사유를 `/registry` 에 적는다.

## 좌표

`coordinate_frame` 에는 **구역 로컬 프레임 이름**이 들어간다. 전역을 적지 않는다 —
이 현장의 datum 은 미검증이고, 경계 재합의도 끝나지 않았다(AI-C-02).

    ../.venv/bin/python tools/vz_gateway/serve.py --port 8899

implements: AI-C-01, AI-C-02, AI-C-04, AI-C-06, AI-O-04, AI-O-05, AI-O-06
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parents[2]
if str(_PACKAGE) not in sys.path:
    sys.path.insert(0, str(_PACKAGE))
_CONSOLE = _PACKAGE / "tools" / "fms_console"
if str(_CONSOLE) not in sys.path:
    sys.path.insert(0, str(_CONSOLE))

from integration.vz_detection_feed import DetectionFeed  # noqa: E402
from integration.vz_redis_source import RedisDetectionSource  # noqa: E402
from integration.vz_wire import (  # noqa: E402
    SubscriptionTable, _now_iso, error_frame, hello_frame, to_envelope,
)
from observability.host_resources import HostResourceReader  # noqa: E402
from providers.ws_server import WsClient, WsHttpServer  # noqa: E402

#: 뷰어가 "오래됐다" 로 넘기는 경계. 우리 신선도 판정과 같은 값을 쓴다.
DEBUG = __import__("os").environ.get("VZ_GATEWAY_DEBUG") == "1"
STALE_MS = 60_000
STATE_PERIOD_S = 5.0
METRICS_PERIOD_S = 2.0
DETECT_PERIOD_S = 0.2        # 5 Hz — AI-N-01 의 초기 기준과 같은 값

#: 탐지 어휘. **데이터다** — 새 대상은 여기 한 줄이고 코드를 고치지 않는다.
DEFAULT_CLASSES = ("person", "door", "box", "chair", "robot")


def _media(spec: str | None):
    """카메라 하나. 사양은 **데이터**다 — RTSP·장치 번호·파일 모두 같은 자리로 들어온다.

    360 카메라의 스티칭 출력도 네트워크 스트림이면 그대로 붙는다(AI-C-08 — URL·
    codec·전송 방식은 어댑터 안에 숨는다).
    """
    if not spec:
        return None, "none_configured"
    from providers.network_stream_media import NetworkStreamMediaSource  # noqa: PLC0415

    def capture_factory(url: str):
        import cv2  # noqa: PLC0415
        # 숫자 하나면 로컬 장치 번호다(USB 카메라). 그 외는 URL·경로 그대로.
        return cv2.VideoCapture(int(url) if url.isdigit() else url)

    source = NetworkStreamMediaSource(spec, source_id=f"cam:{spec}",
                                      capture_factory=capture_factory)
    return source, (source.availability_reason() or None)


def _detector(weights: str | None, classes: tuple[str, ...], device: str | None):
    """탐지기 하나. 가중치가 없으면 **만들지 않는다** — 없는 것을 있는 척하지 않는다."""
    if not weights:
        return None, "no_weights_configured", "none"
    path = Path(weights)
    if not path.is_file():
        return None, f"weights_missing:{path.name}", path.name
    try:
        from edge.yolo_world_provider import YoloWorldPerceptionProvider  # noqa: PLC0415

        provider = YoloWorldPerceptionProvider(list(classes), path, device=device)
        if not provider.is_available():
            return None, "provider_unavailable", path.name
        return provider, None, path.name
    except Exception as exc:                                  # noqa: BLE001
        return None, f"provider_load_failed:{type(exc).__name__}", path.name


def _fleet():
    """실제 선언에서 함대를 읽는다 — 콘솔과 **같은 조립기**를 쓴다.

    여기서 FleetModel 을 따로 세우면 콘솔과 게이트웨이가 서로 다른 판정을 낼 수
    있다. 같은 사실에 주인이 둘이 되지 않도록 조립을 한 곳에 둔다.
    """
    from tools.fms_console import serve as console  # noqa: PLC0415

    service = console.build_service(
        ui_config=_PACKAGE / "config" / "status_ui.json",
        zone_profile=_PACKAGE / "profiles" / "domains.json",
        goal_kinds=_PACKAGE / "profiles" / "goal_kinds.example.json",
        with_fleet=False)
    return service.fleet


class Gateway:
    def __init__(self, fleet, feed: DetectionFeed | None = None,
                 redis_source: RedisDetectionSource | None = None) -> None:
        self.fleet = fleet
        self.feed = feed
        self.redis = redis_source
        self.table = SubscriptionTable()
        self.seq = 0
        self.server: WsHttpServer | None = None
        self.host = HostResourceReader()
        self._lock = threading.Lock()
        self.sent = 0

    # -- 레지스트리 ---------------------------------------------------------
    def registry(self) -> dict:
        """뷰어가 화면을 세우기 전에 읽는 목록. **선언된 것만** 나간다."""
        entities, nodes, zones = [], set(), set()
        for node_id, facts in sorted(self.fleet.facts.items()):
            zone = getattr(facts, "zone_id", None)
            try:
                row = self.fleet.robot(node_id)
            except Exception:                                   # noqa: BLE001
                row = {}
            zone = row.get("zone_id") or zone
            entities.append({
                "id": node_id,
                "node": node_id,
                "zone": zone,
                "entity_type": row.get("role") or "unknown",
                "display_name": row.get("label") or node_id,
                "display_name_en": row.get("label") or node_id,
                "aliases": [], "aliases_en": [],
                "channels": ["state", "metrics"],
            })
            nodes.add(node_id)
            if zone:
                zones.add(zone)
        return {
            "registry_version": "mission-runtime/1",
            "generated_by": "mission_runtime/tools/vz_gateway",
            "note": ("선언된 장치만 들어 있다. "
                     + (self.redis.note() if self.redis is not None
                        else self.feed.status.as_note() if self.feed is not None
                        else "detections 발행하지 않음 — none_configured")
                     + " risk_state 는 risk.event_input 제공자가 없어 발행하지 않는다 — "
                       "빈 채로 두는 것이 그럴듯한 숫자를 채우는 것보다 낫다."),
            "zones": sorted(zones),
            "nodes": sorted(nodes),
            "entities": entities,
        }

    # -- 발행 ---------------------------------------------------------------
    def _next_seq(self) -> int:
        with self._lock:
            self.seq += 1
            return self.seq

    def publish(self, envelope: dict) -> None:
        if self.server is None:
            return
        for frame in self.table.frames_for(envelope):
            for client in self.server.clients():
                if client.send_json(frame):
                    self.sent += 1

    def state_tick(self) -> None:
        """장치마다 상태 3층. **합치지 않는다** — 합치면 fault+online 이 정상으로 보인다."""
        for node_id in sorted(self.fleet.facts):
            try:
                row = self.fleet.robot(node_id)
            except Exception:                                   # noqa: BLE001
                continue
            age = row.get("last_seen_age_s")
            presence = row.get("presence")
            payload = {
                "device_status": "ok" if presence == "discovered" else None,
                "availability": ("online" if presence == "discovered"
                                 else "stale" if age is not None else "offline"),
                "deployment": "deployed" if presence == "discovered" else "not_deployed",
                "last_seen": None if age is None else round(age, 2),
                "stale_threshold_ms": STALE_MS,
                "reason": None if presence == "discovered" else "아직 공지 없음",
            }
            self.publish(to_envelope(
                entity=node_id, node=node_id, zone=row.get("zone_id"),
                channel="state", payload=payload, seq=self._next_seq(),
                last_seen_s=age, stale_after_s=STALE_MS / 1000.0,
                coordinate_frame="zone-local"))

    def metrics_tick(self) -> None:
        """이 기계에서 **실제로 잰** 값. 못 재는 칸은 사유와 함께 비운다."""
        readout = self.host.readout()
        for accelerator in readout.accelerators.values():
            payload = {
                "instance_id": accelerator.instance_id,
                "kind": accelerator.kind,
                "utilization": _measurement(accelerator.utilization),
                "temperature": _measurement(accelerator.temperature),
            }
            self.publish(to_envelope(
                entity=accelerator.instance_id, node="gateway-host", zone=None,
                channel="metrics", payload=payload, seq=self._next_seq(),
                last_seen_s=0.0, stale_after_s=STALE_MS / 1000.0))

    def detect_tick(self) -> None:
        """프레임 하나 → 탐지 봉투. 낼 것이 없으면 **아무것도 보내지 않는다**.

        빈 `detections` 를 보내면 화면이 "봤는데 없다" 로 읽는다 — "보지 않았다" 와
        다른 사실이다.
        """
        # 실증 데이터 스트림이 있으면 **그쪽이 우선**이다 — 촬영과 추론은 그 스택이
        # 이미 하고 있고 같은 프레임에 추론기를 두 번 돌릴 이유가 없다.
        if self.redis is not None and self.redis.client is not None:
            for entity, payload in self.redis.poll():
                self.publish(to_envelope(
                    entity=entity, node=entity, zone=self._zone_of(entity),
                    channel="detections", payload=payload, seq=self._next_seq(),
                    last_seen_s=0.0, stale_after_s=STALE_MS / 1000.0,
                    coordinate_frame="image"))
            return
        if self.feed is None:
            return
        payload = self.feed.tick()
        if payload is None:
            return
        self.publish(to_envelope(
            entity=self.feed.camera_id, node=self.feed.camera_id, zone=None,
            channel="detections", payload=payload, seq=self._next_seq(),
            last_seen_s=0.0, stale_after_s=STALE_MS / 1000.0,
            coordinate_frame="image"))

    def _zone_of(self, entity: str) -> str | None:
        """선언된 장치면 그 구역을, 아니면 None. 지어내지 않는다."""
        try:
            return self.fleet.robot(entity).get("zone_id")
        except Exception:                                      # noqa: BLE001
            return None

    # -- 뷰어 메시지 --------------------------------------------------------
    def on_open(self, client: WsClient) -> None:
        if DEBUG:
            print(f"  + 접속 {client.addr}", flush=True)
        client.send_json(hello_frame(stale_threshold_ms=STALE_MS))

    def on_close(self, client: WsClient) -> None:
        if DEBUG:
            print(f"  - 끊김 {client.addr}", flush=True)

    def on_message(self, client: WsClient, message: dict) -> None:
        kind = message.get("type")
        if DEBUG:
            print(f"  ← {json.dumps(message, ensure_ascii=False)[:160]}", flush=True)
        if kind == "subscribe":
            if self.table.add(message) is None:
                client.send_json(error_frame("subscribe_needs_id"))
            return
        if kind == "unsubscribe":
            self.table.remove(message)
            return
        if kind == "role":
            # 계정·권한은 콘솔이 소유한다. 여기서는 조회 전용임을 분명히 한다.
            #
            # `scope` 는 **객체**다 — 뷰어가 `scope.zones.includes(...)` 로 읽으므로
            # 문자열 "all" 을 주면 화면이 통째로 터진다(`data/permissions.ts`).
            # 범위를 넓게 주되 **쓰기는 아래에서 거절**하므로 권한이 늘지 않는다.
            client.send_json({
                "type": "role", "role": "viewer",
                "display_name": "조회 전용(mission_runtime 게이트웨이)",
                "scope": {"zones": ["*"]},
                "issued_at": _now_iso(),
                "source": "mission_runtime/tools/vz_gateway",
                "read_only": True})
            return
        if kind in ("command", "plan_decision", "video", "scenario"):
            # **쓰기는 이 경로로 받지 않는다.** 물리 명령 발급은 AI 가 소유하지
            # 않고(AI-C-19), 조회 계약과 제어 계약을 한 소켓에 섞지 않는다.
            client.send_json(error_frame(
                f"{kind}_not_served_here — 조회 전용 게이트웨이다(AI-C-19 · AI-O-06)"))
            return
        client.send_json(error_frame(f"unknown_type:{kind}"))


def _measurement(value) -> dict:
    """측정값 한 칸. **값이 없으면 `value` 키 자체가 없다** — 0 으로 채우지 않는다."""
    if value is None:
        return {"measurement_source": "unavailable"}
    body = {"unit": getattr(value, "unit", None),
            "measurement_source": getattr(value, "source", "declared")}
    raw = getattr(value, "value", None)
    if raw is not None:
        body["value"] = raw
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--camera", default=None,
                        help="RTSP/MJPEG URL · 로컬 장치 번호(0,1…) · 영상 파일 경로. "
                             "없으면 detections 를 발행하지 않는다")
    parser.add_argument("--camera-id", default="cam-01",
                        help="탐지 봉투에 실리는 카메라 식별자")
    parser.add_argument("--weights", default=None,
                        help="탐지 가중치 경로. 없으면 탐지기를 만들지 않는다")
    parser.add_argument("--classes", default=",".join(DEFAULT_CLASSES),
                        help="탐지 어휘(쉼표로 구분). 데이터이지 코드가 아니다")
    parser.add_argument("--device", default=None, help="cuda / cpu (기본: 자동)")
    parser.add_argument("--redis", default=None,
                        help="실증 데이터 스트림의 Redis. 예: redis://127.0.0.1:6380/0 "
                             "(physical_demo 의 server_stream_multi_source.py 가 흘린다). "
                             "주면 --camera 대신 이쪽에서 탐지를 받는다")
    parser.add_argument("--redis-model", default="yoloe", help="읽을 비전 모델 이름")
    parser.add_argument("--redis-sources", default="robot1,robot2,drone,cam360",
                        help="읽을 소스(쉼표). robot1=pi7(go1) · robot2=pi1(ep)")
    args = parser.parse_args()

    classes = tuple(c.strip() for c in args.classes.split(",") if c.strip())
    media, media_reason = _media(args.camera)
    detector, detector_reason, model_name = _detector(args.weights, classes, args.device)
    feed = DetectionFeed(
        media=media, detector=detector, model_name=model_name,
        producer={"kind": "mission_runtime/vz_gateway", "vocabulary": list(classes)},
        camera_id=args.camera_id,
        media_reason=media_reason, detector_reason=detector_reason)

    redis_source = None
    if args.redis:
        redis_source = RedisDetectionSource(
            url=args.redis, model=args.redis_model,
            sources=tuple(x.strip() for x in args.redis_sources.split(",") if x.strip()))
        redis_source.connect()

    gateway = Gateway(_fleet(), feed=feed, redis_source=redis_source)
    registry = json.dumps(gateway.registry(), ensure_ascii=False).encode("utf-8")

    def http_get(path: str):
        if path.split("?")[0] == "/registry":
            return 200, "application/json; charset=utf-8", registry
        return None

    server = WsHttpServer(args.host, args.port,
                          on_message=gateway.on_message, on_open=gateway.on_open,
                          on_close=gateway.on_close,
                          http_get=http_get)
    gateway.server = server
    port = server.start()
    counts = json.loads(registry.decode("utf-8"))
    print(f"vz_gateway: ws://{args.host}:{port}  ·  http://{args.host}:{port}/registry")
    print(f"vz_gateway: 선언 장치 {len(counts['entities'])} · 구역 {len(counts['zones'])}")
    detect_note = (redis_source.note() if redis_source is not None
                   else feed.status.as_note())
    detect_on = "발행하지 않음" not in detect_note
    channels = ["state", "metrics"] + (["detections"] if detect_on else [])
    print(f"vz_gateway: 내보내는 채널 = {' · '.join(channels)}")
    print(f"vz_gateway: {detect_note}")
    if not detect_on and redis_source is None:
        print("vz_gateway:   → --camera 와 --weights 를 주면 탐지가 켜진다. "
              "지금은 **빈 배열조차 보내지 않는다** — 보지 않은 것과 보았는데 "
              "없는 것은 다른 사실이다.")
    print(f"vz_gateway: 뷰어를 이렇게 띄운다 — "
          f"VITE_GATEWAY_WS=ws://{args.host}:{port} "
          f"VITE_GATEWAY_HTTP=http://{args.host}:{port} npm run dev")

    try:
        last_state = 0.0
        while True:
            now = time.monotonic()
            if now - last_state >= STATE_PERIOD_S:
                gateway.state_tick()
                last_state = now
            gateway.metrics_tick()
            # 탐지는 더 자주 돈다 — 한 번의 metrics 주기 안에서 여러 프레임을 본다.
            slices = max(1, int(METRICS_PERIOD_S / DETECT_PERIOD_S))
            for _ in range(slices):
                gateway.detect_tick()
                time.sleep(DETECT_PERIOD_S)
    except KeyboardInterrupt:
        print(f"\nvz_gateway: 보낸 프레임 {gateway.sent} · "
              f"어휘 밖이라 버린 채널 {gateway.table.dropped or '없음'}")
        print("vz_gateway: " + (redis_source.note() if redis_source is not None
                                 else feed.status.as_note()))
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
