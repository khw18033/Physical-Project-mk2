"""촬영본(정지 촬영 세션) 저장소 — HW #15 의 목적지. 작은 HTTP PUT 수신단 + MySQL 메타 한 행.

로봇이 주행 중 찍은 JPEG 낱장 묶음(세션 디렉터리 → `tar.gz`)은 **스트림이 아니라 임무 종료 시
일괄 업로드되는 파일**이다. 온디맨드 중계(`ws_echo.py` `/media`)도, 이벤트 캡처(BE-S-09 원문)도
아닌 **오프라인 데이터셋 적재**라 자리가 없었고, Phase 4 결정 9 가 이 갈래를 BE-S-09 저장 모드로
수용했다(`docs/be/02-media-path.md` §1-3-4). 새 저장 제품(S3 호환·MinIO)을 들이지 않는다 — HW
업로더(`pi/robot/capture_upload.py:118-125`)가 서명 없는 **단순 HTTP PUT 한 방**이기 때문이다.

## 규약 — PUT 두 번, 아카이브 안을 뒤지지 않는다

1. `PUT <base>/<세션>.manifest.json` (수 KB) → 2xx
2. `PUT <base>/<세션>.tar.gz` (수백 MB) → 2xx

`tarfile` 이 `sorted(listdir())` 순서로 담아 매니페스트가 수만 장의 JPEG **뒤**에 오고 gzip 은
seek 이 안 되므로, 아카이브 안에서 매니페스트를 꺼내려면 0.7GB 를 통째로 풀어야 한다. 그래서
매니페스트를 먼저 따로 받고, 아카이브는 **열지 않는다**(지시서 단계 10-2).

## 최종 위치는 URL 이 아니라 매니페스트가 정한다

HW 업로더는 `url = base + "/" + basename(path)` 라 URL 에 `entity_id` 가 한 번도 실리지 않는다
(`capture_upload.py:120`). 로봇 2대가 같은 분에 세션을 시작하면 파일명이 같아 서로 덮어쓴다.
그래서 ① 아카이브를 임시 파일로 받고 → ② 앞서 받아 둔 매니페스트의 `source_id`·`session_id` 로
최종 경로 `<루트>/<source_id>/<세션 마지막 칸>.tar.gz` 를 정해 → ③ DB `INSERT`(멱등) → ④ 원자적
rename 한다. **경로 순회 방어의 대상도 URL 이 아니라 매니페스트 값**이다(URL 파일명은 짝짓기 열쇠일
뿐 경로에 쓰이지 않는다 — 그래도 `..`·`\\`·NUL 은 URL 에서도 거부한다).

## 파일과 행의 순서 — 부분 적재가 남지 않는다

`INSERT` → rename → `COMMIT`. DB 가 실패하면 파일은 최종 위치에 놓이지 않고, rename 이 실패하면
행을 롤백한다. 같은 `session_id` 를 두 번 올리면 UNIQUE 충돌(1062)만 골라 잡아 **멱등**으로 2xx 를
돌려주고 두 번째 파일은 버린다(`backend/storage/mission.py` 선례 — `INSERT IGNORE` 는 값 잘림 같은
다른 오류까지 삼키므로 쓰지 않는다).

## 하지 않는 것

- `frame_ref_base` 를 채우지 않는다 — 오프라인 촬영본은 엣지를 거치지 않아 발급 주체가 없다(원칙 10).
  프레임 시각은 매니페스트의 `t0_unix + (n-1) × interval_s` 그대로다.
- 시간대를 추측하지 않는다 — `started_at` 이 오프셋 없는 naive 문자열이면 `NULL` 로 두고 원본은
  `manifest` JSON 에 보존한다. `frames.t0_unix`(epoch) 가 있으면 그것으로 채운다.
- 실제 삭제를 하지 않는다 — 보존 상한 초과분은 `--retention-dry-run` 으로 **선정만** 한다(Phase 4).
  행은 어떤 경우에도 지우지 않는다(`mk2_app` 에 DELETE 권한이 없다) — 아카이브만 지우고 `purged_at` 을
  남기는 갱신 경로는 있으나 이번 Phase 의 CLI 는 켜지 않는다.
- 새 의존성을 들이지 않는다 — `http.server.ThreadingHTTPServer` + `do_PUT`. 대용량 PUT 은 블로킹이라
  WS 게이트웨이(asyncio)와 **별도 프로세스**(systemd `mk2-capture`)로 둔다 — 업로드 쪽 예외·OOM 이
  미디어 중계를 같이 넘어뜨리지 않게.

implements: BE-S-09 (미디어 저장 모드 — 촬영본 갈래), BE-T-08 (토큰·바인딩 — 호스트 파이썬 포트라 ufw 가 통제)
tests: tests/test_capture_upload.py (DoD 10-1~10-3 · 음성 C1~C5) · 합성 업로더 tests/capture_uploader.py
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import re
import signal
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

from backend import observability as obs
from backend import settings
from backend.storage.registry import to_mysql_utc
from backend.storage.writer import parse_iso

LOG = logging.getLogger("mk2.capture")
COMPONENT = "capture"
INSTRUMENT = "be.gateway.capture"          # A층 — source_id 를 라벨에 넣지 않는다(장치 수만큼 곱해진다)

MANIFEST_SUFFIX = ".manifest.json"
ARCHIVE_SUFFIX = ".tar.gz"
PART_SUFFIX = ".part"
INCOMING_DIR = ".incoming"                  # 대기 매니페스트 · 수신 중 임시 파일 (루트와 같은 파일시스템 — rename 이 원자적)
MANIFEST_MAX_BYTES = 1 << 20                # 매니페스트는 수 KB. 1MB 넘으면 매니페스트가 아니다
CHUNK = 1 << 20                             # 아카이브 수신 청크 — 메모리에 통째로 올리지 않는다(0.7GB/h)
REQUIRED_MANIFEST = ("kind", "session_id", "source_id")
MYSQL_DUPLICATE_ENTRY = 1062

# source_id · 세션 마지막 칸 · URL 파일명 stem 에 허용하는 모양. 인덱스 칼럼(varchar 128)과 파일시스템 양쪽에
# 안전한 집합만 — 경로 구분자·NUL·선행 점(숨김/`..`)을 처음부터 배제한다.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_URL_BAD = ("..", "\\", "\x00", "%00", "%2e%2e", "%2E%2E")


class CaptureError(Exception):
    """수신 거부. `status` 가 HTTP 응답 코드, `reason` 이 본문의 `error` 값이다."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__("{} {}".format(status, reason))
        self.status = status
        self.reason = reason


# ── 순수 함수 — 검증 · 경로 · 행 ──────────────────────────────────────────────


def check_segment(value: Any, what: str) -> str:
    """경로 한 칸(`source_id`·세션 마지막 칸)이 안전한 이름인지. 아니면 400."""
    if not isinstance(value, str) or not value:
        raise CaptureError(400, "{}_missing".format(what))
    if "\x00" in value or "/" in value or "\\" in value or value in (".", "..") or ".." in value:
        raise CaptureError(400, "{}_unsafe".format(what))
    if not _SEGMENT_RE.match(value):
        raise CaptureError(400, "{}_unsafe".format(what))
    return value


def validate_manifest(man: Any) -> Dict[str, Any]:
    """매니페스트의 필수·안전성만 본다. `kind` 는 **보존**한다 — `capture_session` 이 아닌 값(8방향 스캔)도
    거부하거나 덮어쓰지 않는다(HW `capture_upload.py:144-155` 의 규율과 같은 방향).

    돌려주는 것: `kind`·`session_id`·`source_id`·`session_name`(세션 마지막 칸 = 최종 파일명·URL stem).
    `session_id` 는 HW 모양 `"{entity_id}/{세션디렉터리명}"` — 슬래시는 **하나만** 허용한다.
    """
    if not isinstance(man, dict):
        raise CaptureError(400, "manifest_not_object")
    for key in REQUIRED_MANIFEST:
        if not isinstance(man.get(key), str) or not man[key].strip():
            raise CaptureError(400, "manifest_missing_{}".format(key))
    session_id = man["session_id"]
    if "\x00" in session_id or "\\" in session_id or session_id.startswith("/"):
        raise CaptureError(400, "session_id_unsafe")
    parts = session_id.split("/")
    if len(parts) > 2:
        raise CaptureError(400, "session_id_unsafe")
    for part in parts:
        check_segment(part, "session_id")
    if len(session_id) > 128:
        raise CaptureError(400, "session_id_too_long")
    source_id = check_segment(man["source_id"], "source_id")
    if len(source_id) > 64:
        raise CaptureError(400, "source_id_too_long")
    return {
        "kind": man["kind"],
        "session_id": session_id,
        "source_id": source_id,
        "session_name": parts[-1],
    }


def stem_of_filename(filename: str) -> Tuple[str, str]:
    """URL 파일명 → (stem, 종류). 종류는 `manifest` 또는 `archive`. 그 외는 400."""
    if filename.endswith(MANIFEST_SUFFIX):
        stem, kind = filename[: -len(MANIFEST_SUFFIX)], "manifest"
    elif filename.endswith(ARCHIVE_SUFFIX):
        stem, kind = filename[: -len(ARCHIVE_SUFFIX)], "archive"
    else:
        raise CaptureError(400, "filename_not_manifest_or_archive")
    check_segment(stem, "filename")
    return stem, kind


def filename_of_url_path(url_path: str) -> str:
    """URL 경로에서 파일명만 꺼낸다. `..`·역슬래시·NUL 이 어디에 있든 거부한다(C3).

    이 파일명은 **짝짓기 열쇠**로만 쓰이고 최종 저장 경로에는 쓰이지 않는다 — 그래도 여기서 막아
    "URL 로 경로를 넘기면 어떻게 되나" 를 400 으로 답하게 한다.
    """
    lowered = url_path.lower()
    if any(bad in lowered for bad in (b.lower() for b in _URL_BAD)):
        raise CaptureError(400, "path_unsafe")
    filename = url_path.rsplit("/", 1)[-1]
    if not filename:
        raise CaptureError(400, "filename_missing")
    return filename


def final_archive_path(root: Path, source_id: str, session_name: str) -> Path:
    """`<루트>/<source_id>/<세션>.tar.gz`. 해석한 경로가 루트 밖이면 400(방어의 마지막 줄)."""
    root_resolved = root.resolve()
    target = (root_resolved / source_id / (session_name + ARCHIVE_SUFFIX)).resolve()
    if root_resolved not in target.parents:
        raise CaptureError(400, "path_outside_root")
    return target


def _epoch_to_naive_utc(value: Any) -> Optional[datetime]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def manifest_row(man: Dict[str, Any], validated: Dict[str, Any],
                 archive_path: Path, archive_bytes: int) -> Dict[str, Any]:
    """매니페스트 → `media_capture` 한 행. **채울 수 없는 칸은 NULL** — 없는 정보를 만들지 않는다.

    - `started_at`: `frames.t0_unix`(epoch, 모호하지 않다) 우선. 없으면 `started_at` 문자열을 읽되
      **오프셋이 없으면 `None`** (`parse_iso` 가 그렇게 한다 — 서버가 시간대를 추측하지 않는다).
    - `frames_count`·`frames_bytes`: `capture_session` 은 `frames.count/bytes`, 스캔 세션은 `shots[]` 에서.
    - `duration_s`: 매니페스트 값 그대로(없으면 NULL — HW 가 fps·frames 둘 다 있을 때만 채운다).
    - `correlation_id`: HW 에 추가 요청한 선택 칸. 없으면 NULL.
    """
    frames = man.get("frames") if isinstance(man.get("frames"), dict) else {}
    started_at = _epoch_to_naive_utc(frames.get("t0_unix"))
    if started_at is None:
        started_at = to_mysql_utc(parse_iso(man.get("started_at")))
    if isinstance(frames.get("count"), int) and not isinstance(frames.get("count"), bool):
        frames_count: Optional[int] = frames["count"]
        frames_bytes: Optional[int] = frames.get("bytes") if isinstance(frames.get("bytes"), int) else None
    else:
        shots = man.get("shots") if isinstance(man.get("shots"), list) else None
        frames_count = len(shots) if shots is not None else None
        frames_bytes = sum(int(s.get("bytes") or 0) for s in shots if isinstance(s, dict)) if shots else None
    duration = man.get("duration_s")
    correlation_id = man.get("correlation_id")
    return {
        "session_id": validated["session_id"],
        "source_id": validated["source_id"],
        "node_id": man.get("node_id") if isinstance(man.get("node_id"), str) else None,
        "zone_id": man.get("zone_id") if isinstance(man.get("zone_id"), str) else None,
        "kind": validated["kind"],
        "started_at": started_at,
        "duration_s": float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
        "frames_count": frames_count,
        "frames_bytes": frames_bytes,
        "archive_path": str(archive_path),
        "archive_bytes": archive_bytes,
        "manifest": json.dumps(man, ensure_ascii=False, separators=(",", ":")),
        "correlation_id": correlation_id if isinstance(correlation_id, str) and correlation_id else None,
    }


def select_for_purge(rows: Sequence[Tuple[str, datetime, int]], max_bytes: int) -> List[Tuple[str, datetime, int]]:
    """보존 상한을 넘는 만큼 **오래된 세션부터** 고른다(C5). 입력 (session_id, received_at, archive_bytes).

    합계가 상한 이하면 빈 목록. 상한을 넘으면 가장 오래된 것부터 하나씩 빼어 합계가 상한 이하가 될 때까지.
    """
    ordered = sorted(rows, key=lambda r: (r[1], r[0]))
    total = sum(int(r[2] or 0) for r in ordered)
    picked: List[Tuple[str, datetime, int]] = []
    for row in ordered:
        if total <= max_bytes:
            break
        picked.append(row)
        total -= int(row[2] or 0)
    return picked


def token_matches(expected: str, presented: Optional[str]) -> bool:
    """`ws_echo.token_matches` 와 같은 규칙 — 기대값이 비어 있으면(loopback 기동) 허용, 아니면 상수 시간 비교."""
    if not expected:
        return True
    if not presented:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), presented.encode("utf-8"))


# ── 파일시스템 ────────────────────────────────────────────────────────────────


class CaptureStorage:
    """저장 루트 아래의 파일 배치. `.incoming/` 에 대기 매니페스트와 수신 중 임시 파일을 둔다."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.incoming = self.root / INCOMING_DIR
        self.incoming.mkdir(parents=True, exist_ok=True)

    def pending_manifest_path(self, stem: str) -> Path:
        return self.incoming / (stem + MANIFEST_SUFFIX)

    def save_pending_manifest(self, stem: str, raw: bytes) -> None:
        """매니페스트를 대기 파일로 남긴다(원자적). 프로세스가 재기동돼도 짝짓기가 살아남는다."""
        target = self.pending_manifest_path(stem)
        tmp = target.with_suffix(target.suffix + PART_SUFFIX)
        with open(tmp, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)

    def load_pending_manifest(self, stem: str) -> Optional[Dict[str, Any]]:
        path = self.pending_manifest_path(stem)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def discard_pending(self, stem: str) -> None:
        try:
            self.pending_manifest_path(stem).unlink()
        except FileNotFoundError:
            pass

    def receive_archive(self, stem: str, reader: Any, length: int) -> Path:
        """본문을 `Content-Length` 만큼 청크로 임시 파일에 흘린다. 모자라면(끊김, C4) 임시 파일을 지우고 400."""
        tmp = self.incoming / (stem + ARCHIVE_SUFFIX + PART_SUFFIX)
        remaining = length
        try:
            with open(tmp, "wb") as fh:
                while remaining > 0:
                    chunk = reader.read(min(CHUNK, remaining))
                    if not chunk:
                        raise CaptureError(400, "incomplete_body")
                    fh.write(chunk)
                    remaining -= len(chunk)
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            self._unlink(tmp)
            raise
        return tmp

    def place(self, tmp: Path, final: Path) -> None:
        """임시 → 최종 위치 원자적 rename(같은 파일시스템). 디렉터리도 fsync 해 rename 을 확정한다."""
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, final)
        self._fsync_dir(final.parent)

    def final_path(self, source_id: str, session_name: str) -> Path:
        return final_archive_path(self.root, source_id, session_name)

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        if os.name != "posix":
            return
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


# ── MySQL 메타 ────────────────────────────────────────────────────────────────

INSERT_SESSION = """
INSERT INTO media_capture
    (session_id, source_id, node_id, zone_id, kind, started_at, duration_s,
     frames_count, frames_bytes, archive_path, archive_bytes, manifest, correlation_id)
VALUES (%(session_id)s, %(source_id)s, %(node_id)s, %(zone_id)s, %(kind)s, %(started_at)s, %(duration_s)s,
        %(frames_count)s, %(frames_bytes)s, %(archive_path)s, %(archive_bytes)s, %(manifest)s, %(correlation_id)s)
"""

SELECT_FOR_RETENTION = """
SELECT session_id, received_at, archive_bytes, archive_path
FROM media_capture
WHERE purged_at IS NULL AND archive_path IS NOT NULL
ORDER BY received_at, session_id
"""

MARK_PURGED = """
UPDATE media_capture
SET archive_path = NULL, archive_bytes = NULL, purged_at = UTC_TIMESTAMP(6)
WHERE session_id = %s AND purged_at IS NULL
"""


class CaptureStore:
    """`media_capture` 쓰기. 접속·재접속 규율은 `MissionEventWriter` 와 같다(세션 타임존을 매 접속마다 못 박는다)."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, db: Optional[str] = None,
                 user: Optional[str] = None, password: Optional[str] = None) -> None:
        self._host = host or settings.mysql_host()
        self._port = port or settings.mysql_port()
        self._db = db or settings.mysql_db()
        self._user = user or settings.mysql_user()
        self._password = password if password is not None else settings.mysql_password()
        self._conn: Any = None

    def _connect(self) -> Any:
        import pymysql

        conn = pymysql.connect(host=self._host, port=self._port, database=self._db,
                               user=self._user, password=self._password, charset="utf8mb4", autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET time_zone = '+00:00'")
        conn.commit()
        return conn

    def connection(self) -> Any:
        if self._conn is None:
            self._conn = self._connect()
        else:
            try:
                self._conn.ping(reconnect=False)
            except Exception:  # noqa: BLE001 - 되살릴 수 없으면 새로 연다
                self.close()
                self._conn = self._connect()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._conn = None

    def insert_then(self, row: Dict[str, Any], then: Callable[[], None]) -> str:
        """`INSERT` → `then()`(rename) → `COMMIT`. `then` 이 실패하면 롤백(행이 남지 않는다).

        돌려주는 값: `"stored"` 또는 `"duplicate"`(같은 `session_id` 가 이미 있다 — `then` 을 부르지 않는다).
        중복 오류(1062)만 골라 잡는다.
        """
        import pymysql

        conn = self.connection()
        conn.begin()
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute(INSERT_SESSION, row)
                except pymysql.err.IntegrityError as exc:
                    if not exc.args or exc.args[0] != MYSQL_DUPLICATE_ENTRY:
                        raise
                    conn.rollback()
                    return "duplicate"
            then()
            conn.commit()
            return "stored"
        except Exception:
            conn.rollback()
            raise

    def list_for_retention(self) -> List[Tuple[str, datetime, int, str]]:
        conn = self.connection()
        with conn.cursor() as cur:
            cur.execute(SELECT_FOR_RETENTION)
            rows = cur.fetchall()
        conn.commit()
        return [(r[0], r[1], int(r[2] or 0), r[3]) for r in rows]

    def mark_purged(self, session_id: str) -> int:
        """아카이브를 지운 뒤 행에 남긴다 — 행은 지우지 않는다(`mk2_app` 에 DELETE 가 없다)."""
        conn = self.connection()
        conn.begin()
        try:
            with conn.cursor() as cur:
                cur.execute(MARK_PURGED, (session_id,))
                changed = cur.rowcount
            conn.commit()
            return changed
        except Exception:
            conn.rollback()
            raise


# ── 서비스 — 소켓 없는 오케스트레이션(테스트 대상) ─────────────────────────────


class CaptureService:
    """매니페스트 PUT 과 아카이브 PUT 을 짝지어 파일 + 행으로 놓는다. DB 는 한 번에 하나(락)."""

    def __init__(self, storage: CaptureStorage, store: CaptureStore) -> None:
        self.storage = storage
        self.store = store
        self._db_lock = threading.Lock()

    def put_manifest(self, stem: str, raw: bytes) -> Tuple[int, Dict[str, Any]]:
        try:
            man = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise CaptureError(400, "manifest_not_json")
        validated = validate_manifest(man)
        if validated["session_name"] != stem:
            # URL 파일명 stem 과 매니페스트의 세션 이름이 다르면 아카이브와 짝지을 수 없다.
            raise CaptureError(400, "stem_mismatch")
        self.storage.save_pending_manifest(stem, raw)
        obs.count(INSTRUMENT, component=COMPONENT, outcome="manifest")
        LOG.info("매니페스트 대기: session_id=%s kind=%s", validated["session_id"], validated["kind"])
        return 200, {"status": "manifest_accepted", "session_id": validated["session_id"]}

    def put_archive(self, stem: str, reader: Any, length: int) -> Tuple[int, Dict[str, Any]]:
        man = self.storage.load_pending_manifest(stem)
        if man is None:
            # 매니페스트 없이 아카이브만 왔다 — 부분 적재 금지(C2). 본문은 읽지 않고 거부한다.
            raise CaptureError(409, "manifest_required")
        validated = validate_manifest(man)
        final = self.storage.final_path(validated["source_id"], validated["session_name"])
        tmp = self.storage.receive_archive(stem, reader, length)
        try:
            archive_bytes = tmp.stat().st_size
            if final.exists():
                # 그 위치에 이미 파일이 있다 — UNIQUE 충돌과 같은 취급(멱등). 두 번째 파일은 버린다.
                outcome = "duplicate"
            else:
                row = manifest_row(man, validated, final, archive_bytes)
                with self._db_lock:
                    outcome = self.store.insert_then(row, then=lambda: self.storage.place(tmp, final))
        except BaseException:
            self.storage._unlink(tmp)
            obs.count(INSTRUMENT, component=COMPONENT, outcome="error")
            raise
        self.storage._unlink(tmp)          # stored 면 이미 옮겨져 없고, duplicate 면 여기서 버린다
        self.storage.discard_pending(stem)
        obs.count(INSTRUMENT, component=COMPONENT, outcome=outcome)
        if outcome == "duplicate":
            LOG.info("촬영본 재전송 무시(멱등): session_id=%s", validated["session_id"])
            return 200, {"status": "already_stored", "session_id": validated["session_id"]}
        LOG.info("촬영본 저장: session_id=%s kind=%s bytes=%s path=%s",
                 validated["session_id"], validated["kind"], archive_bytes, final)
        return 201, {"status": "stored", "session_id": validated["session_id"], "archive_bytes": archive_bytes}


def purge_sessions(storage: CaptureStorage, store: CaptureStore, max_bytes: int,
                   dry_run: bool = True) -> Dict[str, Any]:
    """보존 상한 초과분을 오래된 세션부터 고른다. `dry_run=True`(Phase 4 기본) 면 선정만 돌려준다.

    실제 삭제(`dry_run=False`)는 아카이브를 지우고 `purged_at` 을 남긴다 — 행은 남는다. Phase 4 의 CLI 는
    이 경로를 켜지 않는다(`--retention-dry-run` 만).
    """
    rows = store.list_for_retention()
    picked = select_for_purge([(r[0], r[1], r[2]) for r in rows], max_bytes)
    picked_ids = {p[0] for p in picked}
    total = sum(r[2] for r in rows)
    result = {
        "total_bytes": total, "max_bytes": max_bytes, "sessions": len(rows),
        "selected": [{"session_id": r[0], "received_at": r[1].isoformat() if isinstance(r[1], datetime) else str(r[1]),
                      "archive_bytes": r[2], "archive_path": r[3]} for r in rows if r[0] in picked_ids],
        "dry_run": dry_run,
    }
    if dry_run:
        return result
    for r in rows:
        if r[0] not in picked_ids:
            continue
        path = Path(r[3])
        if path.exists():
            path.unlink()
        store.mark_purged(r[0])
        LOG.info("촬영본 아카이브 삭제(행 유지): session_id=%s bytes=%s", r[0], r[2])
    return result


# ── HTTP ──────────────────────────────────────────────────────────────────────


class CaptureHandler(BaseHTTPRequestHandler):
    server_version = "mk2-capture/0.1"
    protocol_version = "HTTP/1.0"          # 응답 뒤 연결을 닫는다 — 거부한 대용량 PUT 의 본문을 읽지 않아도 된다

    def log_message(self, fmt: str, *args: Any) -> None:   # noqa: N802
        # 요청 줄에 쿼리 토큰이 있다 — 기본 stderr 로그를 끄고 DEBUG 에서만, 토큰을 가려서.
        LOG.debug("%s %s", self.address_string(), (fmt % args).replace(self._token_in_path(), "***"))

    def _token_in_path(self) -> str:
        token = parse_qs(urlsplit(self.path).query).get("token", [""])[0]
        return token or "\x00"

    def _reply(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _check_token(self) -> None:
        expected = self.server.token   # type: ignore[attr-defined]
        presented = parse_qs(urlsplit(self.path).query).get("token", [None])[0] or self.headers.get("X-MK2-Token")
        if not token_matches(expected, presented):
            raise CaptureError(401, "unauthorized")

    def do_GET(self) -> None:   # noqa: N802
        if urlsplit(self.path).path.rstrip("/").endswith("/health"):
            self._reply(200, {"status": "ok", "component": COMPONENT})
            return
        self._reply(404, {"error": "not_found"})

    def do_PUT(self) -> None:   # noqa: N802
        service: CaptureService = self.server.service   # type: ignore[attr-defined]
        try:
            self._check_token()
            filename = filename_of_url_path(urlsplit(self.path).path)
            stem, kind = stem_of_filename(filename)
            raw_len = self.headers.get("Content-Length")
            if raw_len is None or not raw_len.isdigit():
                raise CaptureError(411, "length_required")
            length = int(raw_len)
            if kind == "manifest":
                if length > MANIFEST_MAX_BYTES:
                    raise CaptureError(413, "manifest_too_large")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise CaptureError(400, "incomplete_body")
                status, payload = service.put_manifest(stem, body)
            else:
                if length <= 0:
                    raise CaptureError(400, "empty_body")
                status, payload = service.put_archive(stem, self.rfile, length)
            self._reply(status, payload)
        except CaptureError as exc:
            obs.count(INSTRUMENT, component=COMPONENT, outcome="rejected")
            LOG.warning("PUT 거부 %s %s: %s", exc.status, exc.reason, self._safe_path())
            self._reply(exc.status, {"error": exc.reason})
        except (BrokenPipeError, ConnectionResetError):
            LOG.warning("PUT 중 연결 끊김: %s", self._safe_path())
        except Exception:  # noqa: BLE001
            LOG.exception("PUT 처리 실패: %s", self._safe_path())
            try:
                self._reply(500, {"error": "internal"})
            except OSError:
                pass

    def _safe_path(self) -> str:
        return urlsplit(self.path).path


class CaptureServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], service: CaptureService, token: str) -> None:
        super().__init__(address, CaptureHandler)
        self.service = service
        self.token = token


def build_server(host: str, port: int, service: CaptureService, token: str) -> CaptureServer:
    return CaptureServer((host, port), service, token)


def serve() -> int:
    host, port = settings.capture_host(), settings.capture_port()
    if port == 0:
        LOG.info("촬영본 입구 닫힘 — MK2_CAPTURE_PORT=0")
        return 0
    token = settings.require_token("MK2_CAPTURE_TOKEN", settings.capture_token(), [host])
    root = settings.capture_dir()
    storage = CaptureStorage(root)
    service = CaptureService(storage, CaptureStore())
    server = build_server(host, port, service, token)
    LOG.info("READY — 촬영본 입구: http://%s:%s/capture (토큰 %s, dir=%s, max_bytes=%s) — PUT <세션>.manifest.json → <세션>.tar.gz",
             host, port, "있음" if token else "없음(loopback 전용 기동)", root.resolve(), settings.capture_max_bytes())

    def _stop(signum: int, _frame: Any) -> None:
        LOG.info("종료 신호(%s) — 촬영본 입구를 닫는다", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        service.store.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MK2 촬영본 저장소 — PUT 수신단 / 보존 dry-run")
    parser.add_argument("--retention-dry-run", action="store_true",
                        help="보존 상한 초과분을 오래된 세션부터 골라 보여 준다(삭제하지 않는다)")
    parser.add_argument("--max-bytes", type=int, default=None, help="dry-run 에서 쓸 상한(기본 MK2_CAPTURE_MAX_BYTES)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stdout)
    if args.retention_dry_run:
        max_bytes = args.max_bytes if args.max_bytes is not None else settings.capture_max_bytes()
        result = purge_sessions(CaptureStorage(settings.capture_dir()), CaptureStore(), max_bytes, dry_run=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    obs.setup("be-capture")
    handler = obs.log_handler()
    if handler is not None:
        logging.getLogger().addHandler(handler)
    try:
        return serve()
    except settings.MissingSetting as exc:
        LOG.error("기동 실패: %s", exc)
        return 2
    finally:
        obs.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
