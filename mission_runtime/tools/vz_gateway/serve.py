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
_CONSOLE = _PACKAGE / "tools" / "view_service"
if str(_CONSOLE) not in sys.path:
    sys.path.insert(0, str(_CONSOLE))

from integration.vz_detection_feed import DetectionFeed  # noqa: E402
from integration.broker_endpoints import (  # noqa: E402
    PROBE_MQTT_ACCEPTED,
    VANTAGE_GATEWAY,
    BrokerEndpointDirectory,
    EndpointObservation,
    load_broker_endpoints,
)
from integration.broker_link import BrokerLink  # noqa: E402
from integration.fms_write_api import (  # noqa: E402
    WRITE_ROUTES,
    WriteApiUnavailable,
    build_write_api,
)
from integration.fms_view_api import (  # noqa: E402
    VIEW_ROUTES,
    ViewApiUnavailable,
    build_view_api,
)
from integration.device_telemetry_source import DeviceTelemetrySource  # noqa: E402
#: presence 어휘의 주인은 함대 모델이다 — 문자열을 박아 두면 그쪽이 바뀔 때
#: 이 파일이 조용히 틀린다(AI-C-01).
from tools.view_service.fleet import PRESENCE_UNEXPECTED  # noqa: E402
from integration.vz_redis_source import RedisDetectionSource  # noqa: E402
from integration.vz_wire import (  # noqa: E402
    SubscriptionTable, _now_iso, error_frame, hello_frame, to_envelope,
)
from observability.host_resources import HostResourceReader  # noqa: E402
from providers.overlay import (  # noqa: E402
    TailscaleOverlayProvider,
    advertised_host,
)
from providers.ws_server import WsClient, WsHttpServer  # noqa: E402

#: 뷰어가 "오래됐다" 로 넘기는 경계. 우리 신선도 판정과 같은 값을 쓴다.
DEBUG = __import__("os").environ.get("VZ_GATEWAY_DEBUG") == "1"
#: 장치가 자기 보고 주기를 **말하지 않을 때만** 쓰는 대체값. 선언이 있으면 그쪽이
#: 이긴다(`_stale_ms_for`).
STALE_MS = 60_000
#: 선언된 주기의 몇 배를 넘기면 stale 로 보는가. **재지 않은 값이다** — "보고 세 번을
#: 놓치면 이상하다" 는 통념이고 실측이 아니다. 현장에서 재면 이 한 줄을 바꾼다
#: (AI-B-01: 바뀐 임계는 다른 실행 구성이다).
STALE_INTERVAL_FACTOR = 3.0
#: 아무리 짧은 주기라도 이보다 빨리 stale 로 내리지 않는다. 한 번의 지터로 화면이
#: 깜빡이는 것을 막는 바닥이다.
STALE_FLOOR_MS = 5_000
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
    from tools.view_service import service as console  # noqa: PLC0415

    service = console.build_service(
        ui_config=_PACKAGE / "config" / "status_ui.json",
        zone_profile=_PACKAGE / "profiles" / "domains.json",
        goal_kinds=_PACKAGE / "profiles" / "goal_kinds.example.json",
        with_fleet=False)
    return service.fleet


class Gateway:
    def __init__(self, fleet, feed: DetectionFeed | None = None,
                 redis_source: RedisDetectionSource | None = None,
                 link: BrokerLink | None = None,
                 brokers: BrokerEndpointDirectory | None = None) -> None:
        self.fleet = fleet
        # 구독 상태의 주인은 `BrokerLink` 다 — 여기서 다시 정하지 않는다.
        self.link = link
        # 주소는 **선언**이고 닿는가는 자리별 관측이다(`broker_endpoints.py`).
        self.brokers = brokers or BrokerEndpointDirectory()
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
                # 그 장치를 받는 브로커 주소들, **고를 순서대로**. 브라우저가 쓸
                # 수 없는 전송은 섞이지 않는다 — 고를 수 없는 것을 목록에 넣으면
                # 사람이 고르고 나서 실패한다.
                # 선언의 `viewer` 는 **지금 붙어 있는 가시화의 주소**로 풀린다 —
                # 로봇 SDK 를 들고 있는 기계가 그 노트북이고, 주소를 선언에 박으면
                # 노트북을 바꿀 때마다 선언을 고쳐야 한다. 못 풀면 그 줄은 사유와
                # 함께 남는다(빠지면 선언한 적 없는 것과 같아 보인다).
                "broker_candidates": list(
                    self.brokers.candidate_declarations(node_id)),
            })
            nodes.add(node_id)
            if zone:
                zones.add(zone)
        return {
            "registry_version": "mission-runtime/1",
            "generated_by": "mission_runtime/tools/vz_gateway",
            # **지금 듣고 있는가**를 화면이 아무 때나 물을 수 있어야 한다. 시작
            # 로그에만 있으면 운영 중에 브로커가 끊긴 것을 알 길이 없다 — 실제로
            # 로봇 배터리를 내리자 브로커가 함께 꺼졌다(2026-11-05 실측). 그래서
            # 이 응답은 **요청마다** 만든다(`http_get` 참조) — 기동 시점에 한 번
            # 굳히면 이 칸은 영원히 그때의 값이고 위 문장이 거짓이 된다.
            "telemetry": (self.link.snapshot() if self.link is not None else
                          BrokerLink(target=None).snapshot()),
            "note": ("선언된 장치만 들어 있다. "
                     + (self.redis.note() if self.redis is not None
                        else self.feed.status.as_note() if self.feed is not None
                        else "detections 발행하지 않음 — none_configured")
                     + " risk_state 는 risk.event_input 제공자가 없어 발행하지 않는다 — "
                       "빈 채로 두는 것이 그럴듯한 숫자를 채우는 것보다 낫다."),
            # 화면이 **고를 주소**가 선언에서 나온다 — 가시화 코드에 박히면
            # 로봇 한 대 늘 때마다 그 코드를 고쳐야 한다(AI-C-15, 원칙 #7).
            "brokers": self.brokers.snapshot(),
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
            actions = row.get("announced_actions") or ()
            # **축 셋을 섞지 않는다**(2026-11-05 실기기에서 드러난 결함).
            #
            # 전에는 `presence == "discovered"` 하나로 세 칸을 다 정했다. 그런데
            # `presence` 는 그 자체가 두 사실의 합이다 — 공지가 왔는가와 **그 구역
            # 선언에 있는가**(`fleet.py` 머리말: discovered / declared / unexpected).
            # 그래서 pi7 처럼 **들렸지만 구역 선언에 없는** 노드가 "아직 공지 없음"
            # 으로 나왔다. 들었는데 못 들었다고 적는 것이다.
            #
            #   들었는가      ← `last_seen` 하나로 정한다
            #   공지했는가    ← `announced_actions`
            #   선언에 있는가 ← `presence`
            heard = age is not None
            # **임계를 장치마다 따로 잡는다**(2026-11-05 실기기에서 드러난 결함).
            #
            # 고정 60 초는 두 장치를 정반대로 틀리게 한다 — 5 초마다 보고하는 로봇은
            # 죽고도 1 분 동안 online 이고(보고 12 회 놓침), 60 초마다 보고하는 수위계는
            # 멀쩡한데 늘 stale 경계에 선다. 장치가 자기 주기를 말하므로 그것을 쓴다.
            stale_ms, threshold_basis = self._stale_ms_for(node_id)
            fresh = heard and age * 1000.0 <= stale_ms
            if not heard:
                reason = "아직 아무것도 듣지 못했다"
            elif not actions:
                # 중계 노드가 이 자리다 — 소리는 그것을 지나왔지만 자기 action 을
                # 공지하지는 않았다. 그 기능은 선언이 말한다.
                reason = "들었다 — 다만 capability 공지는 없다(중계·선언 기능)"
            elif presence == PRESENCE_UNEXPECTED:
                reason = "공지는 왔는데 그 구역 선언에 없다"
            else:
                reason = None
            payload = {
                "device_status": "ok" if fresh else None,
                "availability": "online" if fresh else "stale" if heard else "offline",
                # 배치 여부는 **선언 축**이다. 들렸다고 배치된 것이 아니다.
                "deployment": "deployed" if presence == "discovered" else "not_deployed",
                "last_seen": None if age is None else round(age, 2),
                "stale_threshold_ms": round(stale_ms),
                # **그 임계가 어디서 왔는지 함께 낸다.** 선언에서 온 것과 대체값을
                # 쓴 것은 다른 사실이고, 섞으면 "왜 이 장치만 빨리 stale 인가" 에
                # 답할 수 없다.
                "stale_threshold_basis": threshold_basis,
                # 어휘를 눌러 담지 않는다 — 화면이 셋을 구분해야 한다.
                "presence": presence,
                "announced_action_count": len(actions),
                "reason": reason,
            }
            self.publish(to_envelope(
                entity=node_id, node=node_id, zone=row.get("zone_id"),
                channel="state", payload=payload, seq=self._next_seq(),
                last_seen_s=age, stale_after_s=stale_ms / 1000.0,
                coordinate_frame="zone-local"))

    def _stale_ms_for(self, device_id: str) -> tuple[float, str]:
        """그 장치의 stale 임계와 **그 값의 출처**.

        선언이 없으면 대체값을 쓰되 그 사실을 함께 낸다 — 미선언을 선언처럼 보이게
        하면 "왜 이 장치만 다르게 구는가" 에 답할 수 없다.
        """
        interval = None
        source = self.link.source if self.link is not None else None
        if source is not None:
            interval = source.declared_interval_s(device_id)
        if interval is None:
            return float(STALE_MS), "default_no_declared_interval"
        return (max(interval * 1000.0 * STALE_INTERVAL_FACTOR, float(STALE_FLOOR_MS)),
                "declared_by_device")

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
        # **가시화가 어디서 붙었는지는 소켓이 안다.** 그 주소를 적어 두면 선언이
        # `viewer` 라고만 적고도 로봇 주소가 풀린다 — 노트북이 바뀌면 주소도 따라
        # 바뀌고 선언은 그대로다. 오버레이 밖에서 온 연결은 **쓰지 않는다**(원칙 #10).
        if self.brokers is not None:
            host = client.addr[0] if isinstance(client.addr, tuple) else None
            reason = self.brokers.note_viewer(host)
            if DEBUG and reason:
                print(f"    가시화 주소를 쓰지 않는다 — {reason}", flush=True)
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


def build_parser() -> "argparse.ArgumentParser":
    """깃발 선언만 낸다 — **서버를 띄우지 않는다.**

    꺼낸 이유: `docker-compose.yml` 이 존재하지 않는 깃발
    (`--ui-config`·`--zone-profile`)을 넘기고 있었고 세 서비스 모두 argparse 에서
    `exit 2` 였다. 이미지를 돌리지 않고 그것을 잡으려면 파서가 밖에서 보여야
    한다(`tests/test_packaging.py`).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1",
                        help="듣는 주소. `overlay` 를 주면 **이 기계의 오버레이 "
                             "주소**로 묶는다 — 기계를 옮기면 그 기계의 주소가 "
                             "되고 선언은 그대로다. 오버레이를 쓸 수 없으면 "
                             "주소를 지어내지 않고 **세우지 않는다**")
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
    parser.add_argument("--no-view-api", action="store_true",
                        help="FMS 조회 계약(/api/*)을 열지 않는다. 기본은 **연다** — "
                             "트윈 맵·추천 임무·서브태스크·지표를 별도 웹으로 두지 "
                             "않고 가시화 앱이 같은 자리에서 읽게 한다(AI-O-06)")
    parser.add_argument("--no-write-api", action="store_true",
                        help="FMS 쓰기 계약을 열지 않는다(조회만 내는 포트가 된다). "
                             "기본은 **연다** — 콘솔을 지웠으므로 장치 들이기·보정·"
                             "학습·모델 교체·라벨 검수가 닿을 유일한 자리다. "
                             "조회와는 **다른 계약**이고 경로 이름이 겹치지 "
                             "않는다(AI-O-06)")
    # 설정 세 자리. FMS 콘솔의 `main()` 이 들고 있던 깃발이고, 그 웹을 지우면서
    # 이리로 왔다 — 예시 현장(걷기 길)을 물릴 길이 사라지면 안 된다.
    parser.add_argument("--config", default=None, metavar="PATH",
                        help=f"장치·자원 선언 (기본 config/status_ui.json)")
    parser.add_argument("--domains", "--zones", dest="domains", default=None,
                        metavar="PATH",
                        help="도메인·구역 프로파일 (기본 profiles/domains.json)")
    parser.add_argument("--goal-kinds", default=None, metavar="PATH",
                        help="기능 선언 (기본 profiles/goal_kinds.example.json)")
    parser.add_argument("--overlay", default=None, metavar="PATH",
                        help="운영자 수정 장부. **장부 파일이나 그것이 든 "
                             "디렉터리** 둘 다 받는다(기본은 "
                             "~/.local/state/mission_runtime/fms_overlay/"
                             "operator_edits.json). FMS 콘솔을 지우면서 이리로 "
                             "왔다 — 선언을 덮지 않고 쌓는 append-only 장부다"
                             "(AI-L-03)")
    parser.add_argument("--stack-units", default=None, metavar="PATH",
                        help="가시화 명령으로 띄울 **선언된 실행 단위** 파일 "
                             "(config/stack_units.example.json 모양). 주지 않으면 "
                             "`POST /api/stack` 은 거절하고 `/api/services` 가 "
                             "사유를 낸다 — 명령줄은 이 파일에만 있고 망에서 오지 "
                             "않는다")
    parser.add_argument("--accounts", default=None, metavar="PATH",
                        help="계정 파일의 자리. 계정이 없으면 조회만 열린다 — "
                             "첫 계정은 `python -m tools.view_service.accounts "
                             "add <id> --role admin`")
    parser.add_argument("--fleet", action="store_true",
                        help="선언된 로봇을 **이 프로세스에서** 세운다. 기본은 "
                             "세우지 않는다 — 장치 러너가 이미 돌고 있는데 여기서 "
                             "또 세우면 같은 device_id 로 둘이 서서 같은 "
                             "downlink 에 둘이 답한다")
    parser.add_argument("--viewer-bridge", default=None, metavar="WS_URL",
                        help="보는 사람의 기계에 세운 다리 주소 "
                             "(예: ws://127.0.0.1:9001/mqtt). **개발 편의다** — "
                             "선언에 담지 않고 런타임에만 붙으며, 후보 목록의 "
                             "맨 뒤에 그 사실과 함께 나간다. 제대로 된 해결은 "
                             "브라우저가 도는 기계에 오버레이를 설치하는 것이다")
    parser.add_argument("--broker", default=None, metavar="HOST[:PORT]",
                        help="말단 브로커. 주면 capability 공지와 신선도를 **구독해** "
                             "탐지/신선도를 채운다(발행하지 않는다). 없으면 화면의 "
                             "장치는 선언뿐이고 availability 가 offline 으로 남는다")
    parser.add_argument("--redis-sources", default="robot1,robot2,drone,cam360",
                        help="읽을 소스(쉼표). robot1=pi7(go1) · robot2=pi1(ep)")
    return parser


def main() -> int:
    args = build_parser().parse_args()

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

    fleet = _fleet()

    # 말단이 **실제로 올리는 것**을 듣는다. 이것이 없으면 `Discovery` 가 비어 있고
    # `state_tick` 의 presence 가 영원히 `discovered` 가 아니다 — 로봇이 말하고
    # 있는데도 화면은 offline 으로 남는다(2026-11-05 실기기에서 확인한 공백).
    # 선언된 주소들. 없으면 빈 묶음이고 **그것도 정상 배치다** — 주소를
    # 선언하지 않은 현장에서 프레임워크가 주소를 지어내지 않는다.
    with open(_PACKAGE / "config" / "status_ui.json", encoding="utf-8") as handle:
        brokers = BrokerEndpointDirectory(
            endpoints=load_broker_endpoints(json.load(handle)))
    if args.viewer_bridge:
        brokers.add_viewer_bridge(args.viewer_bridge)

    target = None
    if args.broker:
        host, _, port = args.broker.partition(":")
        target = f"{host}:{port or 1883}"

        def _open() -> tuple[object, DeviceTelemetrySource] | None:
            """붙어서 구독을 건다. 못 붙으면 `None` — **예외를 삼키지 않는다.**

            `ImportError` 는 그대로 올린다. `BrokerLink` 가 그것만
            `dependency_missing` 으로 받고 재시도를 멈춘다(AI-C-05).
            """
            from providers.mqtt import MqttTransportProvider  # noqa: PLC0415
            from providers.physical_command_protobuf import (  # noqa: PLC0415
                PhysicalCommandProtobufSerializerProvider,
            )

            transport = MqttTransportProvider(host=host, port=int(port or 1883),
                                              client_id="mission-runtime-vz-gateway")
            if not transport.connect(timeout_s=8.0):
                transport.close()   # 루프 스레드를 남기지 않는다
                return None
            source = DeviceTelemetrySource(
                transport=transport,
                serializer=PhysicalCommandProtobufSerializerProvider(),
                # **`Discovery` 가 그 사실의 주인이다.** 여기서 presence 를
                # 정하지 않는다(원칙 #15) — 공지와 시각만 넘긴다.
                sink=fleet.discovery)
            source.start()
            return transport, source
    else:
        _open = None

    # 한 번 실패하고 영구히 귀를 닫지 않는다 — 충전하러 내려간 로봇이 돌아오는
    # 것은 예외가 아니라 정상 운용이다(2026-11-05 실측, AI-C-05).
    link = BrokerLink(target=target, connect=_open)
    link.start()

    # **우리 자리의 관측만** 적는다. 브라우저가 닿는지는 여기서 말하지 않는다 —
    # 그 자리는 브라우저가 재야 하고, 합치면 이번 버그가 그대로 돌아온다.
    if link.source is not None and args.broker:
        _host, _, _port = args.broker.partition(":")
        for endpoint in brokers.matching(_host, int(_port or 1883)):
            brokers.observe(endpoint.url, EndpointObservation(
                vantage=VANTAGE_GATEWAY, probe=PROBE_MQTT_ACCEPTED,
                reason="게이트웨이가 붙어 구독 중", at=link.connected_since))

    gateway = Gateway(fleet, feed=feed, redis_source=redis_source, link=link,
                      brokers=brokers)

    # **FMS 조회 계약을 같은 포트에서 낸다.** 콘솔과 같은 `build_service()` 를 쓰므로
    # 판정이 한 곳에 남는다 — 두 곳이 각자 조립하면 두 화면이 다른 답을 말한다
    # (view-contract §3.6). 세우지 못하면 **그 조각만** 꺼지고 나머지는 그대로 돈다.
    view_api = None
    view_api_reason = "열지 않았다(--no-view-api)"
    if not args.no_view_api:
        try:
            view_api = build_view_api(
                ui_config=(args.config
                           or _PACKAGE / "config" / "status_ui.json"),
                zone_profile=(args.domains
                              or _PACKAGE / "profiles" / "domains.json"),
                goal_kinds=(args.goal_kinds
                            or _PACKAGE / "profiles" / "goal_kinds.example.json"),
                # 장치는 **기본으로** 세우지 않는다 — 게이트웨이는 듣는 쪽이고,
                # 두 프로세스가 같은 device_id 로 서면 같은 downlink 에 둘이
                # 답한다. 그래도 길은 둔다(`--fleet`): 콘솔을 지웠으므로 선언된
                # 로봇을 세울 자리가 여기 말고는 장치 러너뿐이다.
                with_fleet=args.fleet,
                overlay_path=args.overlay, accounts_path=args.accounts,
                # 백엔드 기계 앞에서 사람이 하는 일을 **화면으로** 옮기는 자리.
                # 자리를 주지 않으면 그 조각만 비활성이고 응답이 사유를 적는다.
                stack_units_path=args.stack_units)
            view_api_reason = f"조회 경로 {len(VIEW_ROUTES)}개"
        except ViewApiUnavailable as error:
            view_api_reason = f"세우지 못했다 — {error}"
        except Exception as error:                              # noqa: BLE001
            view_api_reason = f"세우지 못했다 — {type(error).__name__}: {error}"

    # **쓰기 계약도 같은 포트에서 받는다.** 조회와 같은 서비스 객체를 쓴다 — 두
    # 번째를 만들면 운영자가 고친 값이 한쪽에만 보이고 같은 사실에 주인이 둘이
    # 된다. 경로 이름은 조회와 겹치지 않고(`WRITE_ROUTES` ∩ `VIEW_ROUTES` = ∅)
    # 세션은 쿠키가 아니라 Bearer 다 — 교차 출처 쿠키는 CSRF 를 연다.
    write_api = None
    write_api_reason = "열지 않았다(--no-write-api)"
    if not args.no_write_api:
        if view_api is None:
            write_api_reason = "조회 계약이 서지 않아 함께 꺼졌다"
        else:
            try:
                write_api = build_write_api(view_api.service, view_api.module)
                write_api_reason = f"쓰기 경로 {len(WRITE_ROUTES)}개 · Bearer 세션"
            except WriteApiUnavailable as error:
                write_api_reason = f"세우지 못했다 — {error}"
            except Exception as error:                          # noqa: BLE001
                write_api_reason = f"세우지 못했다 — {type(error).__name__}: {error}"

    def http_get(path: str, headers: dict | None = None):
        if view_api is not None and view_api.handles(path):
            from urllib.parse import parse_qs, urlparse  # noqa: PLC0415

            parsed = urlparse(path)
            status, body = view_api.answer(parsed.path, parse_qs(parsed.query),
                                           headers)
            return status, "application/json; charset=utf-8", body
        if path.split("?")[0] == "/registry":
            # **요청마다 만든다.** 굳혀 두면 구독 상태·들은 장치가 기동 시점에
            # 멈추고, 화면은 그 사실을 알 수 없다.
            body = json.dumps(gateway.registry(), ensure_ascii=False).encode("utf-8")
            return 200, "application/json; charset=utf-8", body
        if view_api is not None:
            # 없는 경로의 **어휘는 조회 계약이 소유한다** — 전송 provider 의
            # `not_found` 로 답하면 같은 사실에 두 이름이 생긴다.
            status, body = view_api.unknown_path()
            return status, "application/json; charset=utf-8", body
        return None

    def http_post(path: str, body: bytes, headers: dict):
        """바꾸는 요청. 판정은 서비스가 하고 이 자리는 옮기기만 한다."""
        if write_api is None:
            return None
        status, payload = write_api.answer(path, body, headers)
        return status, "application/json; charset=utf-8", payload

    # `--host overlay`: 듣는 주소를 **이 기계의 오버레이 주소**로 푼다. 기계를
    # 옮기면 그 기계의 주소가 되므로 선언에 주소를 박을 일이 없다. 풀지 못하면
    # 0.0.0.0 으로 넓히지 않는다 — 오버레이 밖으로 열려 버리기 때문이다(원칙 #10).
    if args.host == "overlay":
        resolved, origin = advertised_host("0.0.0.0", TailscaleOverlayProvider())
        if origin != "overlay":
            print("vz_gateway: --host overlay 인데 오버레이 주소를 알 수 없다 — "
                  "세우지 않는다. `tailscale status` 를 먼저 본다.")
            return 2
        args.host = resolved

    server = WsHttpServer(args.host, args.port,
                          on_message=gateway.on_message, on_open=gateway.on_open,
                          on_close=gateway.on_close,
                          http_get=http_get,
                          # 훅을 걸지 않으면 POST 는 405 다. 가시화 웹이 유일한
                          # 웹이므로 **여기서는 건다**.
                          http_post=(None if write_api is None else http_post),
                          # 계약의 판을 응답에 싣는다 — 문서에만 있으면 뷰어가
                          # 자기 기대와 맞출 길이 없다.
                          server_name=(None if view_api is None
                                       else view_api.server_name()))
    gateway.server = server
    port = server.start()
    counts = gateway.registry()
    # **듣는 주소와 붙는 주소는 다르다.** `--host 0.0.0.0` 으로 열어 두고 안내문에도
    # `0.0.0.0` 을 적으면 다른 노트북이 그 주소로 붙을 수 없다(2026-11-20 실측).
    # 와일드카드일 때 안내하는 주소는 **오버레이가 말하는 것**이고(원칙 #10:
    # 공개 인터넷을 경유하지 않는다) 알 수 없으면 지어내지 않는다.
    shown, origin = advertised_host(args.host, TailscaleOverlayProvider())
    print(f"vz_gateway: ws://{shown}:{port}  ·  http://{shown}:{port}/registry")
    if shown != args.host:
        print(f"vz_gateway: 듣는 주소는 {args.host}:{port} 이고 위 주소는 "
              + ("오버레이에서 본 이 기계다" if origin == "overlay"
                 else "**모른다** — 오버레이를 물어볼 수 없어 자리표를 넣었다"))
    print(f"vz_gateway: 선언 장치 {len(counts['entities'])} · 구역 {len(counts['zones'])}")
    detect_note = (redis_source.note() if redis_source is not None
                   else feed.status.as_note())
    detect_on = "발행하지 않음" not in detect_note
    channels = ["state", "metrics"] + (["detections"] if detect_on else [])
    print(f"vz_gateway: 내보내는 채널 = {' · '.join(channels)}")
    print(f"vz_gateway: {detect_note}")
    print(f"vz_gateway: FMS 조회 계약 — {view_api_reason}")
    print(f"vz_gateway: FMS 쓰기 계약 — {write_api_reason}")
    print(f"vz_gateway: {link.note()}")
    ws_candidates = [e for e in brokers.endpoints if e.transport == "mqtt-ws"]
    print(f"vz_gateway: 선언된 브라우저용 브로커 주소 {len(ws_candidates)}건"
          + (" (다리 포함 — **개발 편의다**)" if args.viewer_bridge else ""))
    for endpoint in sorted(ws_candidates, key=lambda e: e.scope != "overlay"):
        print(f"vz_gateway:   [{endpoint.scope}] {endpoint.url}")
    if link.source is not None:
        print(f"vz_gateway: {link.source.note_for_screen()}")
    if not detect_on and redis_source is None:
        print("vz_gateway:   → --camera 와 --weights 를 주면 탐지가 켜진다. "
              "지금은 **빈 배열조차 보내지 않는다** — 보지 않은 것과 보았는데 "
              "없는 것은 다른 사실이다.")
    print(f"vz_gateway: 뷰어를 이렇게 띄운다 — "
          f"VITE_GATEWAY_WS=ws://{shown}:{port} "
          f"VITE_GATEWAY_HTTP=http://{shown}:{port} npm run dev")

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
