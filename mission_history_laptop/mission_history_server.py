#!/usr/bin/env python3
"""임무 이력 서버 — 가시화(VZ) 요청 「임무이력서버_요청_VZ_261119.md」 구현.  (v2 · 261119)

v2 에서 명세에 맞게 고친 것 (v1 은 이 셋이 명세와 달랐다):
  - 그림 표: 명세 §5 에 없는 byte_size 칸을 쓰지 않는다(표는 schema_v2.sql / schema_v1_to_v2.sql).
  - health 가 DB 오류로 503 을 줄 때 본문을 명세 §3 의 오류 꼴 {"error": "<사유>"} 로만 준다.
  - 표준 라이브러리가 직접 내는 오류 응답(모르는 메서드 501 · 잘못된 요청 줄 400 등)에도
    CORS 머리(명세 §6-1 「모든 응답(오류 포함)」)와 {"error": ...} 본문을 붙인다. 상태 코드는 그대로다.
v2 에서 사용자 결정(261119)으로 바꾼 것:
  - 목록 정렬(명세 §3 A2 「문자열 "{date}/{run}" 내림차순」)을 완료 기준 검사(check-history-server.mjs L7)와
    가짜 서버가 쓰는 JS localeCompare 순서에 맞춘다(바이트 순이 아니다). list_sort_key 참고.

가시화 웹의 임무 이력(판마다 mission.json · progress.json · 그림)을 서버에 저장하고 돌려준다.
어느 장치에서든 같은 판 목록과 다시보기를 열 수 있게 하는 것이 목적이다.

창구 (뿌리 /api/v1)
  GET  /api/v1/health                                       서버 확인
  GET  /api/v1/runs                                         판 목록 (mission.json 에서 view 만 뺀 것)
  PUT  /api/v1/runs/{date}/{run}/{mission|progress}.json    JSON 문서 덮어쓰기
  POST /api/v1/runs/{date}/{run}/images/{detect|robot}/{name}  그림 덮어쓰기
  GET  /api/v1/files/{date}/{run}/{mission.json | progress.json | images/<kind>/<name>}
  OPTIONS (아무 경로)                                       CORS 사전 요청 → 204
  DELETE · PATCH                                            405 (지우는 창구는 없다)

저장
  문서  PostgreSQL(mk2 DB) 표 mission_runs — mission_doc · progress_doc (JSONB)
  그림  디스크 MH_IMAGES_DIR/<date>/<run>/<kind>/<name>
        표 mission_run_images 에는 그 경로를 그림 폴더 기준 상대 경로로 넣는다(storage_path)

환경변수 (systemd 유닛이 넣는다)
  MH_HOST        바인딩 주소   기본 100.102.8.102 (서버 tailnet 주소)
  MH_PORT        포트          기본 8850
  MH_IMAGES_DIR  그림 폴더     기본 /home/dg/mission_history/images
  MK2_TSDB_HOST / MK2_TSDB_PORT / MK2_TSDB_DB / MK2_TSDB_USER   기본 127.0.0.1 / 7859 / mk2 / mk2_app
  MK2_TSDB_PASSWORD   필수 — 서버 /home/dg/capstone-db/.env 에 있다

로그는 표준 출력(systemd 면 journalctl -u mission-history)에 요청 한 줄씩 남긴다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import unquote

import psycopg

LOG = logging.getLogger("mission-history")

API = "/api/v1"
SERVICE = "mission-history"
API_VERSION = 1

MAX_JSON_BYTES = 32 * 1024 * 1024       # 명세 §3 A3 — 32MB 이상
MAX_IMAGE_BYTES = 15 * 1024 * 1024      # 명세 §3 A4 — 15MB 이상
READ_CHUNK = 1024 * 1024

# 명세 §3-0 이름 규칙. fullmatch + ASCII — 줄바꿈(%0A)이나 다른 문자권 숫자가 끼어들지 못하게 한다.
RE_DATE = re.compile(r"\d{6}", re.ASCII)
RE_RUN = re.compile(r"\d{6}_[A-Za-z0-9_.-]{1,80}", re.ASCII)
RE_FILE = re.compile(r"(mission|progress)\.json", re.ASCII)
RE_KIND = re.compile(r"(detect|robot)", re.ASCII)
RE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,120}\.(jpg|jpeg|png)", re.ASCII)

DOC_COLUMN = {"mission.json": "mission_doc", "progress.json": "progress_doc"}
IMAGE_TYPE = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}

# 명세 §6-1 — 모든 응답(오류 포함)에 붙인다.
CORS_HEADERS = (
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS"),
    ("Access-Control-Allow-Headers", "Content-Type, Authorization"),
    ("Access-Control-Allow-Private-Network", "true"),
    ("Access-Control-Max-Age", "600"),
)


class ApiError(Exception):
    """요청 거절. status 가 HTTP 응답 코드, message 가 본문 {"error": ...} 의 값이다."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status} {message}")
        self.status = status
        self.message = message


def env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name, "").strip()
    return value or default


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def short(error: BaseException) -> str:
    text = str(error).strip().splitlines()
    return text[0] if text else type(error).__name__


# ── 설정 ──────────────────────────────────────────────────────────────────────


class Config:
    def __init__(self) -> None:
        self.host = env("MH_HOST", "100.102.8.102")
        self.port = int(env("MH_PORT", "8850"))
        self.images_dir = Path(env("MH_IMAGES_DIR", "/home/dg/mission_history/images"))
        password = env("MK2_TSDB_PASSWORD")
        if not password:
            raise SystemExit("MK2_TSDB_PASSWORD 가 없다 — 유닛의 EnvironmentFile(/home/dg/capstone-db/.env)을 확인한다")
        self.db = {
            "host": env("MK2_TSDB_HOST", "127.0.0.1"),
            "port": int(env("MK2_TSDB_PORT", "7859")),
            "dbname": env("MK2_TSDB_DB", "mk2"),
            "user": env("MK2_TSDB_USER", "mk2_app"),
            "password": password,
        }


# ── DB ────────────────────────────────────────────────────────────────────────

SQL_RUN_COUNT = "SELECT count(*) FROM mission_runs WHERE mission_doc IS NOT NULL"

# view 를 뺀 요약. mission_doc 이 객체가 아니면(배열·값 하나) 읽을 수 없는 판으로 보고 NULL — 목록 전체는 살린다.
# 정렬은 DB 가 아니라 list_sort_key 로 한다(localeCompare 순서 — 아래).
SQL_LIST = """
SELECT date, run,
       CASE WHEN jsonb_typeof(mission_doc) = 'object' THEN (mission_doc - 'view')::text END
FROM mission_runs
WHERE mission_doc IS NOT NULL
"""

# 목록 정렬 — JS localeCompare(ICU 기본 정렬)와 같은 순서 (사용자 결정 261119).
#   1단계: 글자 종류의 순서 _ < - < . < / < 0~9 < a~z (대 · 소문자를 같은 글자로 본다)
#   2단계: 1단계가 모두 같으면 앞 글자부터 소문자가 대문자보다 앞
# 날짜 · 판 이름은 쓸 때 이름 규칙(§3-0)으로 이 글자만 들어온다. 그 밖의 글자(창구를 거치지 않고 DB 에 넣은 줄)는
# 알려진 글자 뒤에 문자 코드 순으로 둔다 — 목록 전체가 실패하지 않게.
_COLLATE_ORDER = {c: i for i, c in enumerate("_-./0123456789abcdefghijklmnopqrstuvwxyz")}


def list_sort_key(date: str, run: str) -> tuple:
    key = "{}/{}".format(date, run)
    primary = tuple(_COLLATE_ORDER.get(c.lower(), 1000 + ord(c)) for c in key)
    case = tuple(1 if c.isupper() else 0 for c in key)
    return primary, case

SQL_UPSERT_DOC = """
INSERT INTO mission_runs (date, run, {col}) VALUES (%s, %s, %s::jsonb)
ON CONFLICT (date, run) DO UPDATE SET {col} = EXCLUDED.{col}, updated_at = now()
"""

SQL_GET_DOC = "SELECT {col}::text FROM mission_runs WHERE date = %s AND run = %s"

SQL_UPSERT_IMAGE = """
INSERT INTO mission_run_images (date, run, kind, name, content_type, storage_path)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (date, run, kind, name) DO UPDATE
SET content_type = EXCLUDED.content_type, storage_path = EXCLUDED.storage_path, updated_at = now()
"""

SQL_GET_IMAGE = "SELECT storage_path FROM mission_run_images WHERE date = %s AND run = %s AND kind = %s AND name = %s"

SQL_CHECK = """
SELECT to_regclass('public.mission_runs') IS NOT NULL,
       to_regclass('public.mission_run_images') IS NOT NULL
"""

SQL_CHECK_PRIV = """
SELECT has_table_privilege('public.mission_runs', 'SELECT, INSERT, UPDATE'),
       has_table_privilege('public.mission_run_images', 'SELECT, INSERT, UPDATE')
"""


class Store:
    """요청마다 접속을 새로 연다 — 끊긴 접속을 되살리는 코드가 없어 원인 추적이 쉽다(요청 수가 적다)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(**self.cfg.db, connect_timeout=2, autocommit=True,
                               application_name="mission-history")

    def check(self) -> None:
        """기동 때 한 번 — 표가 없거나 권한이 모자라면 무엇이 문제인지 말하고 죽는다."""
        with self.connect() as conn:
            runs_ok, images_ok = conn.execute(SQL_CHECK).fetchone()
            if not (runs_ok and images_ok):
                raise SystemExit("표 mission_runs · mission_run_images 가 없다 — schema.sql 을 먼저 적용한다")
            runs_priv, images_priv = conn.execute(SQL_CHECK_PRIV).fetchone()
            if not (runs_priv and images_priv):
                raise SystemExit("{} 에게 두 표의 SELECT · INSERT · UPDATE 권한이 없다 — schema.sql 의 GRANT 를 확인한다"
                                 .format(self.cfg.db["user"]))

    def run_count(self) -> int:
        with self.connect() as conn:
            return int(conn.execute(SQL_RUN_COUNT).fetchone()[0])

    def list_runs(self) -> List[Tuple[str, str, Optional[str]]]:
        """명세 §3 A2 — 최근 것이 먼저(「{date}/{run}」 내림차순, list_sort_key 순서)."""
        with self.connect() as conn:
            rows = [(d.rstrip(), r, m) for d, r, m in conn.execute(SQL_LIST).fetchall()]
        rows.sort(key=lambda row: list_sort_key(row[0], row[1]), reverse=True)
        return rows

    def put_doc(self, date: str, run: str, file: str, text: str) -> None:
        col = DOC_COLUMN[file]
        with self.connect() as conn:
            conn.execute(SQL_UPSERT_DOC.format(col=col), (date, run, text))

    def get_doc(self, date: str, run: str, file: str) -> Optional[str]:
        col = DOC_COLUMN[file]
        with self.connect() as conn:
            row = conn.execute(SQL_GET_DOC.format(col=col), (date, run)).fetchone()
        return row[0] if row else None

    def put_image(self, date: str, run: str, kind: str, name: str, content_type: str,
                  storage_path: str) -> None:
        with self.connect() as conn:
            conn.execute(SQL_UPSERT_IMAGE, (date, run, kind, name, content_type, storage_path))

    def get_image_path(self, date: str, run: str, kind: str, name: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute(SQL_GET_IMAGE, (date, run, kind, name)).fetchone()
        return row[0] if row else None


# ── 디스크 ────────────────────────────────────────────────────────────────────


def write_atomic(path: Path, data: bytes) -> None:
    """임시 파일에 쓰고 바꿔 끼운다 — 읽는 쪽이 반쯤 쓴 그림을 보지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".{}.{}.{}.tmp".format(path.name, os.getpid(), threading.get_ident()))
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def inside(root: Path, target: Path) -> bool:
    root_r = root.resolve()
    target_r = target.resolve()
    return target_r == root_r or root_r in target_r.parents


# ── 이름 검사 ────────────────────────────────────────────────────────────────


def check_date_run(date: str, run: str) -> None:
    if not RE_DATE.fullmatch(date):
        raise ApiError(400, "날짜 형식이 아닙니다(YYMMDD 6자리): {!r}".format(date))
    if not RE_RUN.fullmatch(run):
        raise ApiError(400, "판 이름 형식이 아닙니다(HHMMSS_임무id): {!r}".format(run))


def check_kind_name(kind: str, name: str) -> None:
    if not RE_KIND.fullmatch(kind):
        raise ApiError(400, "그림 종류는 detect 또는 robot 입니다: {!r}".format(kind))
    if not RE_NAME.fullmatch(name):
        raise ApiError(400, "그림 이름 형식이 아닙니다: {!r}".format(name))


def parse_json_text(body: bytes) -> str:
    """UTF-8 JSON 인지 본다. NaN · Infinity 는 표준 JSON 이 아니라 거절한다(DB 도 받지 않는다)."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ApiError(400, "깨진 JSON 입니다(UTF-8 이 아닙니다)")

    def reject_constant(value: str) -> None:
        raise ValueError(value)

    try:
        json.loads(text, parse_constant=reject_constant)
    except ValueError:
        raise ApiError(400, "깨진 JSON 입니다")
    return text


# ── HTTP ──────────────────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    server_version = "mission-history/1"
    protocol_version = "HTTP/1.0"     # 응답마다 연결을 닫는다 — 연결 재사용에서 생기는 꼬임이 없다
    timeout = 60                      # 소켓 읽기·쓰기 한 번에 60초 넘게 멈추면 끊는다

    # 요청 한 줄 로그는 _handle 이 남긴다. 기본 로그(요청마다 stderr)는 끄고, 기본 오류 로그만 살린다.
    def log_request(self, code="-", size="-") -> None:   # noqa: D401
        pass

    def log_message(self, fmt: str, *args) -> None:
        LOG.warning("%s %s", self.client_address[0], fmt % args)

    def send_error(self, code: int, message: Optional[str] = None, explain: Optional[str] = None) -> None:
        """표준 라이브러리가 _handle 을 거치지 않고 직접 내는 오류(모르는 메서드 501 · 잘못된 요청 줄 400 ·
        너무 긴 요청 줄 414 등). 상태 코드는 그대로 두고 CORS 머리와 {"error": ...} 본문만 명세 꼴로 바꾼다."""
        try:
            reason = self.responses[code][0]
        except KeyError:
            reason = ""
        self.log_error("code %d, message %s", code, message)
        body = json.dumps({"error": message or reason or str(code)}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        for key, value in CORS_HEADERS:
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.close_connection = True
        if self.command != "HEAD" and code >= 200 and code not in (204, 205, 304):
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.end_headers()

    @property
    def store(self) -> Store:
        return self.server.store            # type: ignore[attr-defined]

    @property
    def cfg(self) -> Config:
        return self.server.cfg              # type: ignore[attr-defined]

    # ── 메서드 ──

    def do_OPTIONS(self) -> None:   # noqa: N802
        self._handle(lambda: self._send(204, b"", None))

    def do_GET(self) -> None:       # noqa: N802
        self._handle(self._get)

    def do_PUT(self) -> None:       # noqa: N802
        self._handle(self._put)

    def do_POST(self) -> None:      # noqa: N802
        self._handle(self._post)

    def do_DELETE(self) -> None:    # noqa: N802
        self._handle(self._not_allowed)

    def do_PATCH(self) -> None:     # noqa: N802
        self._handle(self._not_allowed)

    # ── 공통 처리 ──

    def _handle(self, fn) -> None:
        started = time.monotonic()
        self._status: Optional[int] = None
        self._sent = False
        self._body = b""
        try:
            self._body = self._read_body()
            fn()
        except ApiError as exc:
            self._json(exc.status, {"error": exc.message})
        except psycopg.OperationalError as exc:
            LOG.error("DB 에 닿지 않음: %s", exc)
            self._json(503, {"error": "DB 에 닿지 않습니다: {}".format(short(exc))})
        except psycopg.DataError as exc:
            self._json(400, {"error": "DB 가 이 값을 받지 않습니다: {}".format(short(exc))})
        except (BrokenPipeError, ConnectionResetError) as exc:
            LOG.warning("연결이 끊김: %s", exc)
            self._sent = True
        except Exception as exc:   # noqa: BLE001
            LOG.exception("처리 실패: %s %s", self.command, self.path)
            self._json(500, {"error": "서버 내부 오류: {}: {}".format(type(exc).__name__, short(exc))})
        finally:
            LOG.info("%s %s %s -> %s %dB %.0fms", self.client_address[0], self.command, self.path,
                     self._status, len(self._body), (time.monotonic() - started) * 1000)

    def _read_body(self) -> bytes:
        """본문을 먼저 다 읽는다. 읽지 않은 채 연결을 닫으면 상대가 응답 대신 「연결 끊김」을 받을 수 있다.

        상한(32MB)을 넘는 본문은 버리면서 끝까지 읽고 413 을 준다.
        """
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            self.close_connection = True
            raise ApiError(411, "Content-Length 가 필요합니다(chunked 는 받지 않습니다)")
        raw = self.headers.get("Content-Length")
        if raw is None or raw.strip() == "":
            return b""
        if not raw.strip().isdigit():
            self.close_connection = True
            raise ApiError(400, "Content-Length 가 숫자가 아닙니다")
        length = int(raw)
        if length > MAX_JSON_BYTES:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(READ_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            raise ApiError(413, "본문이 너무 큽니다(상한 {}MB)".format(MAX_JSON_BYTES // (1024 * 1024)))
        body = self.rfile.read(length) if length else b""
        if len(body) != length:
            raise ApiError(400, "본문이 Content-Length 보다 짧습니다(전송이 끊겼습니다)")
        return body

    def _send(self, status: int, body: bytes, content_type: Optional[str]) -> None:
        if self._sent:
            return
        self.send_response(status)
        for key, value in CORS_HEADERS:
            self.send_header(key, value)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)
        self._status = status
        self._sent = True

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _segments(self) -> List[str]:
        """/api/v1 뒤의 경로를 / 로 먼저 자르고 조각마다 디코딩한다 — %2F 가 경로 구분자로 풀리지 않는다."""
        raw = self.path.split("?", 1)[0].split("#", 1)[0]
        if raw == API:
            return []
        if not raw.startswith(API + "/"):
            raise ApiError(404, "없는 창구입니다")
        tail = raw[len(API) + 1:]
        parts = tail.split("/") if tail else []
        try:
            return [unquote(part, encoding="utf-8", errors="strict") for part in parts]
        except UnicodeDecodeError:
            raise ApiError(400, "경로가 UTF-8 이 아닙니다")

    # ── 창구 ──

    def _not_allowed(self) -> None:
        raise ApiError(405, "{} 는 받지 않습니다 — 지우는 창구는 없습니다".format(self.command))

    def _get(self) -> None:
        parts = self._segments()
        if parts == ["health"]:
            return self._health()
        if parts in (["runs"], ["runs", ""]):
            return self._list()
        if len(parts) >= 1 and parts[0] == "files":
            return self._file(parts[1:])
        raise ApiError(404, "없는 창구입니다")

    def _health(self) -> None:
        try:
            count = self.store.run_count()
        except psycopg.Error as exc:
            LOG.error("health — DB 오류: %s", exc)
            return self._json(503, {"error": "DB 오류: {}".format(short(exc))})
        self._json(200, {"ok": True, "service": SERVICE, "apiVersion": API_VERSION,
                         "serverTime": now_iso(), "runCount": count})

    def _list(self) -> None:
        rows = self.store.list_runs()
        # mission 은 DB 가 만든 JSON 문자열을 그대로 끼운다(숫자를 파이썬으로 다시 읽고 쓰지 않는다).
        items = ['{{"date":{},"run":{},"mission":{}}}'.format(
            json.dumps(date), json.dumps(run), mission if mission is not None else "null")
            for date, run, mission in rows]
        body = '{"dir":"","runs":[' + ",".join(items) + "]}"
        self._send(200, body.encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, parts: List[str]) -> None:
        if len(parts) < 3:
            raise ApiError(400, "파일 경로 형식이 아닙니다: /files/{날짜}/{판}/{경로}")
        date, run, rest = parts[0], parts[1], parts[2:]
        check_date_run(date, run)
        if len(rest) == 1 and RE_FILE.fullmatch(rest[0]):
            text = self.store.get_doc(date, run, rest[0])
            if text is None:
                raise ApiError(404, "기록에 없는 파일입니다: {}/{}/{}".format(date, run, rest[0]))
            return self._send(200, text.encode("utf-8"), "application/json; charset=utf-8")
        if len(rest) == 3 and rest[0] == "images":
            kind, name = rest[1], rest[2]
            check_kind_name(kind, name)
            rel = self.store.get_image_path(date, run, kind, name)
            path = self.cfg.images_dir / rel if rel else None
            if path is None or not inside(self.cfg.images_dir, path) or not path.is_file():
                raise ApiError(404, "기록에 없는 파일입니다: {}/{}/images/{}/{}".format(date, run, kind, name))
            data = path.read_bytes()
            ext = name.rsplit(".", 1)[-1].lower()
            return self._send(200, data, IMAGE_TYPE[ext])
        raise ApiError(400, "파일 경로 형식이 아닙니다(mission.json · progress.json · images/<종류>/<이름>)")

    def _put(self) -> None:
        parts = self._segments()
        if len(parts) >= 3 and parts[0] == "runs":
            check_date_run(parts[1], parts[2])
            if len(parts) == 4:
                date, run, file = parts[1], parts[2], parts[3]
                if not RE_FILE.fullmatch(file):
                    raise ApiError(400, "파일 이름은 mission.json 또는 progress.json 입니다: {!r}".format(file))
                text = parse_json_text(self._body)
                self.store.put_doc(date, run, file, text)
                return self._json(200, {"ok": True, "path": "{}/{}/{}".format(date, run, file)})
        raise ApiError(404, "없는 창구입니다")

    def _post(self) -> None:
        parts = self._segments()
        if len(parts) >= 3 and parts[0] == "runs":
            check_date_run(parts[1], parts[2])
            if len(parts) == 6 and parts[3] == "images":
                date, run, kind, name = parts[1], parts[2], parts[4], parts[5]
                check_kind_name(kind, name)
                data = self._body
                if len(data) == 0:
                    raise ApiError(400, "빈 그림입니다")
                if len(data) > MAX_IMAGE_BYTES:
                    raise ApiError(413, "그림이 너무 큽니다(상한 {}MB)".format(MAX_IMAGE_BYTES // (1024 * 1024)))
                rel = "{}/{}/{}/{}".format(date, run, kind, name)
                path = self.cfg.images_dir / rel
                if not inside(self.cfg.images_dir, path):
                    raise ApiError(400, "그림 경로가 그림 폴더 밖입니다")
                write_atomic(path, data)
                ext = name.rsplit(".", 1)[-1].lower()
                self.store.put_image(date, run, kind, name, IMAGE_TYPE[ext], rel)
                return self._json(200, {"ok": True, "path": "{}/{}/images/{}/{}".format(date, run, kind, name),
                                        "bytes": len(data)})
        raise ApiError(404, "없는 창구입니다")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def build_server(cfg: Config, store: Store) -> Server:
    server = Server((cfg.host, cfg.port), Handler)
    server.cfg = cfg       # type: ignore[attr-defined]
    server.store = store   # type: ignore[attr-defined]
    return server


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    cfg = Config()
    cfg.images_dir.mkdir(parents=True, exist_ok=True)
    store = Store(cfg)
    try:
        store.check()
    except psycopg.OperationalError as exc:
        # DB 가 아직 안 떴을 수 있다(재부팅 직후). 서버는 띄우고 health 가 503 을 준다.
        LOG.warning("기동 확인 — DB 에 닿지 않음(서버는 띄운다, health 는 503): %s", short(exc))
    server = build_server(cfg, store)
    LOG.info("READY — http://%s:%s%s  (DB %s@%s:%s/%s · 그림 %s)", cfg.host, cfg.port, API,
             cfg.db["user"], cfg.db["host"], cfg.db["port"], cfg.db["dbname"], cfg.images_dir)

    def stop(signum, _frame) -> None:
        LOG.info("종료 신호(%s) — 닫는다", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
