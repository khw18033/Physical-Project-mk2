"""Serves today's core features as one read-only page: the status snapshot, the
capability-grounded subtask proposal and the situation-based mission recommendation.

implements: AI-O-06 (통합 운영 상태 뷰), AI-O-05, AI-B-12/13/14/15, AI-L-10
관련: AI-C-19 (조회 전용 · 표시는 가시화 책임)

이 서버는 **운영 UI 가 아니다.** 운영 화면은 가시화 파트가 만들고, 이 페이지는
"방금 만든 계약이 실제로 화면에 올라가는 모양인가"를 눈으로 확인하는 검토 도구다.
표준 라이브러리만 쓰고 CDN·폰트를 불러오지 않으므로 폐쇄망에서도 뜬다.

## 무엇이 실측이고 무엇이 예시인가

섞어서 보여 주면 데모가 실제보다 잘 도는 것처럼 보인다. 그래서 응답이 두 칸으로
나뉜다 — `message` 는 계약 그대로의 와이어 메시지이고, `live_sections` 는 그 안에서
**이 기계에서 실제로 읽은** 묶음의 이름이다. 화면은 그 이름에 배지를 붙인다.

    accelerators · board · events   이 기계의 실측(psutil · nvidia-smi · 임계 판정)
    그 밖(mission · task_nodes …)   커밋된 예시 장면(생산 코드가 만든 것)

작업 그래프를 실측으로 채울 수 없는 이유는 분명하다 — 그래프는 미션이 들어와야
생기고, 생성은 가시화 파트의 계약이다(우리는 소비한다).

## 조회 전용

GET 만 받는다. POST·PUT·DELETE 는 405 로 거절하고 사유 토큰을 돌려준다 — 상태 뷰
경로로 실행을 바꿀 수단을 주지 않는다는 요구(기능정의서 §1.1)의 서버 쪽 대응이다.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pathlib
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:  # 설치 없이 바로 실행할 수 있게
    sys.path.insert(0, str(PROJECT_ROOT))

from mission_runtime.observability.host_resources import HostResourceReader  # noqa: E402
from mission_runtime.observability.layered_metrics import (  # noqa: E402
    Direction,
    TargetBaseline,
)
from mission_runtime.observability.resource_watch import ResourceWatch, WatchTarget  # noqa: E402
from mission_runtime.planning.mission_recommendation import (  # noqa: E402
    TRIGGER_IDLE_ACCELERATOR,
    TRIGGER_STALE_CALIBRATION,
    TRIGGER_UNRESOLVED_UNKNOWN,
    MissionRecommender,
    MissionTemplate,
    SituationSnapshot,
)
from mission_runtime.planning.template_proposal import (  # noqa: E402
    CapabilityMenu,
    KeywordTemplateProposalProvider,
    ProposalPipeline,
    ProposalRequest,
    TemplateGrounder,
)

EXAMPLE_PATH = PROJECT_ROOT / "schemas" / "ai" / "examples" / "status-snapshot.json"
PAGE_PATH = Path(__file__).resolve().parent / "index.html"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770

REASON_READ_ONLY = "status_view_is_read_only"

#: 이 기계에서 실제로 읽어 덮어쓰는 묶음.
LIVE_SECTIONS = ("accelerators", "board", "events")

#: 임계 감시 대상. 배포가 주는 데이터이고 여기서는 데모용 기본값이다.
WATCH_TARGETS = (
    WatchTarget("cpu_util", "utilization",
                TargetBaseline(0.85, Direction.AT_MOST, "ratio"), "cpu"),
    WatchTarget("gpu_util", "utilization",
                TargetBaseline(0.85, Direction.AT_MOST, "ratio"), "gpu-0"),
    WatchTarget("gpu_temp", "temperature",
                TargetBaseline(80.0, Direction.AT_MOST, "celsius"), "gpu-0"),
    WatchTarget("board_memory", "memory_utilization",
                TargetBaseline(0.9, Direction.AT_MOST, "ratio")),
)


#: 역할별로 **무엇을 보는가**. 데이터이고 코드 분기가 아니다 — 새 역할은 이 표에
#: 한 줄이다. 이름과 범위 어휘는 가시화 파트의 `RoleInfo`/`RoleScope` 를 그대로 쓴다.
#:
#: **화면에서 가리는 것은 편의다. 강제는 백엔드가 한다**(BE-Q-04). 여기서 숨긴 칸이
#: 보안 경계라고 읽히면 안 되므로, 각 역할에 그 사실을 함께 싣는다.
ROLE_VIEWS: tuple[dict, ...] = (
    {
        "role": "viewer",
        "display_name": "관람 (시연)",
        "icon": "👀",
        "tabs": ["overview"],
        "detail_level": "summary",
        "note": "시연·외부 관람용. 식별자와 내부 사유 토큰을 가린다.",
    },
    {
        "role": "operator",
        "display_name": "운영자",
        "icon": "🎛️",
        "tabs": ["overview", "graph", "node", "requests"],
        "detail_level": "operational",
        "note": "지금 무엇이 돌고 무엇이 막혔는지. 자원 상세는 분석 역할이 본다.",
    },
    {
        "role": "analyst",
        "display_name": "분석",
        "icon": "📊",
        "tabs": ["overview", "graph", "node", "requests", "resources", "planning"],
        "detail_level": "full",
        "note": "자원·지표 추이와 산출·추천 근거까지.",
    },
    {
        "role": "maintainer",
        "display_name": "관리자",
        "icon": "🧰",
        "tabs": ["overview", "graph", "node", "requests", "resources", "planning", "raw"],
        "detail_level": "full",
        "note": "원본 메시지까지. 계약을 확인하는 역할이다.",
    },
)

#: 탭 선언. 구역 기호는 기능정의서 §2 의 것을 그대로 쓴다.
TABS: tuple[dict, ...] = (
    {"id": "overview", "icon": "🛰️", "label": "종합", "regions": ["B", "D"]},
    {"id": "graph", "icon": "🗺️", "label": "실행 그래프", "regions": ["C"]},
    {"id": "node", "icon": "🔎", "label": "노드 상세", "regions": ["F", "G", "H"]},
    {"id": "requests", "icon": "📮", "label": "외부 요청", "regions": ["I"]},
    {"id": "resources", "icon": "🖥️", "label": "자원·지표", "regions": ["E", "E′"]},
    {"id": "planning", "icon": "🧠", "label": "산출·추천", "regions": []},
    {"id": "raw", "icon": "🧾", "label": "원본 메시지", "regions": []},
)


#: 가시화 파트 콘솔(복사해 온 것)이 쓰는 개발 서버 포트. 그쪽 `vite.config.ts` 의 값이다.
CONSOLE_PORT = 5173
CONSOLE_DIR = PROJECT_ROOT / "third_party" / "vz-web-dashboard"


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, port)) == 0


class ConsoleProcess:
    """가시화 콘솔을 **같은 명령으로** 함께 띄운다.

    두 화면을 각각 띄우라고 하면 둘 중 하나는 안 띄운 상태로 보게 된다. 그래서 한
    명령으로 묶되, 콘솔이 없거나 Node 가 없으면 **우리 화면만** 뜬다 — 선택 구성요소
    결손은 축소이지 실패가 아니다(AI-C-05).

    이미 떠 있는 콘솔은 다시 띄우지 않고 그대로 쓴다(포트를 빼앗지 않는다).
    """

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.reason: str | None = None
        self.adopted = False

    def start(self, *, wait_s: float = 90.0) -> None:
        if port_open(CONSOLE_PORT):
            self.adopted = True
            return
        if not CONSOLE_DIR.is_dir():
            self.reason = "console_not_vendored"
            return
        if not (CONSOLE_DIR / "node_modules").is_dir():
            self.reason = "npm_install_needed"
            return
        npm = shutil.which("npm") or shutil.which(
            "npm", path=os.pathsep.join([
                str(pathlib.Path.home() / ".local" / "node" / "bin"),
                os.environ.get("PATH", ""),
            ])
        )
        if npm is None:
            self.reason = "node_not_installed"
            return
        self.process = subprocess.Popen(
            [npm, "run", "dev"], cwd=CONSOLE_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "PATH": os.path.dirname(npm) + os.pathsep + os.environ.get("PATH", "")},
        )
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if port_open(CONSOLE_PORT):
                return
            if self.process.poll() is not None:
                self.reason = "console_exited"
                return
            time.sleep(0.25)
        self.reason = "console_did_not_start"

    def state(self) -> dict:
        running = port_open(CONSOLE_PORT)
        body = {"running": running, "url": f"http://127.0.0.1:{CONSOLE_PORT}"}
        if not running and self.reason:
            body["reason"] = self.reason
        if running and self.adopted:
            body["adopted"] = True       # 우리가 띄운 것이 아니라 이미 떠 있던 것
        return body

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


class SnapshotService:
    """예시 장면 + 이 기계의 실측을 합쳐 한 장을 만든다. 상태를 바꾸지 않는다."""

    def __init__(self, example_path: Path = EXAMPLE_PATH) -> None:
        self._example = json.loads(example_path.read_text(encoding="utf-8"))
        self._reader = HostResourceReader(cpu_interval_s=None)
        self._watch = ResourceWatch.of(WATCH_TARGETS)
        self._reader.read()      # 전력은 차분이라 첫 읽기를 버린다

    # -- 상태 스냅샷 ----------------------------------------------------

    def snapshot(self) -> dict:
        from mission_runtime.integration.status_wire import (
            accelerator_to_wire,
            event_to_wire,
        )

        message = copy.deepcopy(self._example)
        view = self._reader.read()
        now = time.time()

        message["accelerators"] = [accelerator_to_wire(a) for a in view.accelerators]
        message["board"] = {
            "memory_utilization": _measurement(view.board.memory_utilization),
            "power": _measurement(view.board.power),
        }
        # 예시 장면의 서비스는 예시 가속기에 배치돼 있었다. 실측 가속기로 바꿨으니
        # 배치도 실측 쪽으로 옮긴다 — 아니면 화면이 "미배치"만 가득하게 된다.
        message["services"] = _rehome_services(message.get("services", []), view)
        message["events"] = [
            event_to_wire(e) for e in self._watch.events(view, at=now)
        ] + [e for e in message.get("events", []) if e.get("event_kind") != "RESOURCE"]
        # 자원 조건은 [E] 경고와 같은 판정에서 나온다 — 두 구역이 어긋날 수 없다.
        message["verdicts"] = _attach_resource_conditions(
            message.get("verdicts", []), self._watch, view
        )
        return {
            "message": message,
            "live_sections": list(LIVE_SECTIONS) + ["services", "verdicts[].resource"],
            "read_at": now,
        }

    def views(self) -> dict:
        """역할·탭·필터축. 화면이 무엇을 가릴지 **서버 선언**으로 정한다.

        화면 코드에 역할 이름을 박으면 역할이 늘 때마다 화면을 고쳐야 한다. 그리고
        가리는 것이 보안이 아니라는 사실도 한곳에 적어 둔다 — 강제는 백엔드다.
        """
        view = self._reader.read()
        message = self._example
        return {
            "roles": list(ROLE_VIEWS),
            "tabs": list(TABS),
            "enforcement": {
                "where": "backend",
                "note": "화면의 역할 필터는 보기 편하게 하려는 것이고 접근 통제가 아니다."
                        " 실제 차단은 백엔드가 역할·범위로 한다(BE-Q-04).",
            },
            "filters": {
                "zones": sorted({message.get("zone_id", "")} - {""}),
                "devices": [
                    {"id": a.instance_id, "kind": a.kind,
                     "label": a.vendor_label or a.instance_id}
                    for a in view.accelerators
                ],
                "capabilities": sorted({
                    kind
                    for service in message.get("services", [])
                    for kind in [service.get("service_id")] if kind
                }),
            },
        }

    # -- 서브태스크 산출(접지) ------------------------------------------

    def proposal(self, goal_text: str) -> dict:
        """예시 목표 하나를 지금 쓸 수 있는 어휘로 접지해 본다.

        어휘는 예시 장면의 서비스 이름이 아니라 **capability kind** 다. 데모에서는
        아래 목록을 쓰고, 실제 배치에서는 `CapabilityMenu.from_registry()` 가 만든다.
        """
        menu = CapabilityMenu((
            "media.video_input", "perception.detect", "perception.distance",
            "control.locomotion",
        ))
        provider = KeywordTemplateProposalProvider(vocabulary={
            "영상": ("open_stream", "media.video_input"),
            "탐지": ("detect_target", "perception.detect"),
            "거리": ("estimate_distance", "perception.distance"),
            "이동": ("move_forward", "control.locomotion"),
            "무게": ("estimate_weight", "analysis.weight"),   # 어휘 밖 — 거부된다
        })
        request = ProposalRequest("DEMO_GOAL", goal_text, menu)
        result = ProposalPipeline(TemplateGrounder(menu), provider).run(request)
        return {
            "goal_text": goal_text,
            "menu": list(menu.kinds),
            "reason": result.reason,
            "provider_id": result.provider_id,
            "steps": [
                {
                    "action": step.action,
                    "required": list(step.requirement.required),
                    "optional": list(step.requirement.optional),
                }
                for step in (result.template.steps if result.template else ())
            ],
            "template_version": result.template.version if result.template else None,
            "rejected": [
                {
                    "index": r.index, "reason": r.reason, "detail": r.detail,
                    "requested_capability": r.requested_capability,
                }
                for r in result.rejected
            ],
            "escalation_capabilities": list(result.escalation_capabilities),
        }

    # -- 임무 추천 ------------------------------------------------------

    def recommendation(self) -> dict:
        view = self._reader.read()
        placed = {s.accelerator_id for s in view.services if s.accelerator_id}
        idle = tuple(a.instance_id for a in view.accelerators if a.instance_id not in placed)

        recommender = MissionRecommender()
        recommender.register(MissionTemplate(
            "reobserve_unknown", "미확인 객체 재관측", "OBSERVE_REGION",
            frozenset({"media.video_input", "perception.detect"}),
            frozenset({TRIGGER_UNRESOLVED_UNKNOWN}), priority=10))
        recommender.register(MissionTemplate(
            "weigh_object", "대상 무게 추정", "MEASURE_OBJECT",
            frozenset({"analysis.weight"}),
            frozenset({TRIGGER_UNRESOLVED_UNKNOWN}), priority=20))
        recommender.register(MissionTemplate(
            "offload_analysis", "유휴 가속기로 추가 분석", "ANALYZE_BACKLOG",
            frozenset({"perception.detect"}),
            frozenset({TRIGGER_IDLE_ACCELERATOR}), priority=30))
        recommender.register(MissionTemplate(
            "recalibrate", "카메라 재보정", "CALIBRATE_CAMERA",
            frozenset({"media.video_input"}),
            frozenset({TRIGGER_STALE_CALIBRATION}), priority=40))

        situation = SituationSnapshot(
            available_capabilities=frozenset({"media.video_input", "perception.detect"}),
            idle_accelerators=idle,
            unresolved_unknown_object_ids=("obj-7", "obj-9"),
        )
        return {
            "situation": {
                "available_capabilities": sorted(situation.available_capabilities),
                "idle_accelerators": list(idle),
                "unresolved_unknown_object_ids": list(situation.unresolved_unknown_object_ids),
                "triggers": sorted(situation.triggers()),
            },
            "candidates": [
                {
                    "mission_kind": c.mission_kind, "title": c.title,
                    "goal_kind": c.goal_kind, "recommended": c.recommended,
                    "reason": c.reason, "matched_triggers": list(c.matched_triggers),
                    "missing_capabilities": list(c.missing_capabilities),
                    "subjects": list(c.subjects), "priority": c.priority,
                }
                for c in recommender.recommend(situation)
            ],
        }


def _measurement(measurement) -> dict:
    body = {"unit": measurement.unit}
    if measurement.value is not None:
        body["value"] = measurement.value
    return body


def _rehome_services(services: list[dict], view) -> list[dict]:
    """예시 서비스를 실측 가속기에 다시 얹는다. 남는 서비스는 미배치로 남긴다."""
    ids = [a.instance_id for a in view.accelerators]
    out = []
    for index, service in enumerate(services):
        moved = dict(service)
        if index < len(ids):
            moved["accelerator_instance_id"] = ids[index]
        else:
            moved.pop("accelerator_instance_id", None)
        for indicator in moved.get("indicators", []):
            if index < len(ids):
                indicator["accelerator_instance_id"] = ids[index]
            else:
                indicator.pop("accelerator_instance_id", None)
        out.append(moved)
    return out


def _attach_resource_conditions(verdicts: list[dict], watch: ResourceWatch, view) -> list[dict]:
    conditions = [
        {k: v for k, v in (
            ("condition_item_id", c.item_id),
            ("condition_satisfied", c.satisfied),
            ("condition_reason", c.reason_token),
        ) if v is not None}
        for c in watch.conditions(view)
    ]
    out = []
    for index, verdict in enumerate(verdicts):
        updated = dict(verdict)
        if index == 0:                     # 기준 노드 하나에만 붙인다
            updated["resource"] = conditions
        out.append(updated)
    return out


class SnapshotHandler(BaseHTTPRequestHandler):
    service: SnapshotService
    console: ConsoleProcess | None = None

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path in ("/", "/index.html"):
                self._send_bytes(PAGE_PATH.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/snapshot":
                self._send_json(self.service.snapshot())
            elif path == "/api/proposal":
                query = urlsplit(self.path).query
                goal = "영상 열고 대상 탐지해서 거리 재고 그 앞까지 이동해, 무게도 추정해"
                for part in query.split("&"):
                    if part.startswith("goal="):
                        from urllib.parse import unquote_plus

                        goal = unquote_plus(part[5:]) or goal
                self._send_json(self.service.proposal(goal))
            elif path == "/api/console":
                self._send_json(self.console.state() if self.console else {"running": False,
                                "reason": "console_not_started"})
            elif path == "/api/views":
                self._send_json(self.service.views())
            elif path == "/api/recommendation":
                self._send_json(self.service.recommendation())
            else:
                self._send_json({"error": "not_found", "path": path}, status=404)
        except Exception as error:          # 검토 도구가 조용히 죽지 않게
            self._send_json({"error": type(error).__name__, "detail": str(error)}, status=500)

    def _reject_write(self) -> None:
        self._send_json({"error": REASON_READ_ONLY}, status=405)

    do_POST = do_PUT = do_PATCH = do_DELETE = _reject_write  # type: ignore[assignment]

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:   # 조용히
        pass


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                example_path: Path = EXAMPLE_PATH,
                console: ConsoleProcess | None = None) -> ThreadingHTTPServer:
    handler = type("BoundSnapshotHandler", (SnapshotHandler,),
                   {"service": SnapshotService(example_path), "console": console})
    return ThreadingHTTPServer((host, port), handler)


def write_static(destination: Path, example_path: Path = EXAMPLE_PATH) -> Path:
    """데이터를 박아 넣은 한 장을 쓴다. 서버 없이 열리고 되읽기도 하지 않는다.

    검토를 다른 사람에게 보여 줄 때 서버를 띄우게 하는 대신 파일 하나를 보내기 위한
    것이다. 실측 값이 그 순간에 고정되므로 페이지가 "정적 사본"이라고 스스로 적는다.
    """
    service = SnapshotService(example_path)
    bundle = {
        "snapshot": service.snapshot(),
        "proposal": service.proposal(
            "영상 열고 대상 탐지해서 거리 재고 그 앞까지 이동해, 무게도 추정해"
        ),
        "recommendation": service.recommendation(),
        "views": service.views(),
    }
    page = PAGE_PATH.read_text(encoding="utf-8")
    baked = ("<script>window.__SNAPSHOT_BUNDLE__ = "
             + json.dumps(bundle, ensure_ascii=False) + ";</script>\n")
    # 페이지의 **마지막** <script> 앞에 끼운다. 특정 첫 줄에 기대면 페이지를 손볼
    # 때마다 여기서 깨진다.
    marker = "<script>"
    assert page.count(marker) >= 1, "페이지에 <script> 가 없다 — 주입 지점이 사라졌다"
    destination.parent.mkdir(parents=True, exist_ok=True)
    cut = page.rindex(marker)
    destination.write_text(page[:cut] + baked + page[cut:], encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="0 이면 빈 포트를 고른다")
    parser.add_argument("--example", type=Path, default=EXAMPLE_PATH,
                        help="기본 장면으로 쓸 status_snapshot 예시 메시지")
    parser.add_argument("--static", type=Path, default=None,
                        help="서버를 띄우지 않고 데이터가 박힌 한 장을 이 경로로 내보낸다")
    parser.add_argument("--with-console", action="store_true",
                        help="가시화 콘솔(third_party/vz-web-dashboard)을 같은 명령으로 함께 띄운다")
    args = parser.parse_args(argv)

    if args.static is not None:
        written = write_static(args.static, args.example)
        print(f"static page -> {written}")
        return 0

    console = ConsoleProcess()
    if args.with_console:
        print("가시화 콘솔 기동 중 … (처음이면 시간이 걸린다)")
        console.start()
        state = console.state()
        print("가시화 콘솔  " + (state["url"] + ("  (이미 떠 있던 것)" if state.get("adopted") else "")
                                 if state["running"] else f"없음 — {state.get('reason')}"))

    server = make_server(args.host, args.port, args.example, console)
    host, port = server.server_address[:2]
    print(f"운영 상태 화면  http://{host}:{port}   (조회 전용 · Ctrl+C 로 종료)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        console.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
