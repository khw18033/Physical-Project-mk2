"""4b 촬영본 저장소 — DoD 10-1~10-3 + 음성 대조 C1~C5.

서버(`backend/gateway/capture.py`)를 **이 프로세스 안에서** 임시 저장 루트 + 임의 포트로 띄우고, 합성 업로더
(`tests/capture_uploader.py` — HW `capture_upload.py` 모양)로 PUT 두 번을 보낸다. 메타 저장은 **MySQL 이 닿으면
실제 `media_capture`**(서버), 닿지 않으면 UNIQUE 만 흉내 낸 `FakeStore`(컴퓨터)다 — 파일 쪽 규칙(경로·원자성·
부분 적재 금지)은 어느 쪽에서도 같은 코드가 돈다. 실제 systemd 유닛(8767)에 대한 판정은 서버에서 업로더를
손으로 돌려 한다(DoD 10-1 실측).

테스트 세션은 `source_id` `test-cap-<hex>` · 세션 `s<hex>` 로 고유하다. MySQL 행은 남는다(`mk2_app` 에 DELETE 가
없다 — 그것이 설계다).

implements: BE-S-09 (미디어 저장 모드 — 촬영본 갈래)
tests: 10-1 저장·바이트 동일·행 1·매니페스트 원본 / 10-2 kind 보존 / 10-3 멱등 / C1 토큰 / C2 부분 적재 금지 /
       C3 경로 순회 / C4 끊김 / C5 보존 dry-run
"""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

import capture_uploader as up
from backend import settings
from backend.gateway import capture

TOKEN = "captest" + uuid.uuid4().hex[:12]     # 파일 이름이 아니라 값이다 — .gitignore 의 *token* 과 무관


# ── 메타 저장 — 실제 MySQL 또는 가짜 ────────────────────────────────────────


class FakeStore:
    """`CaptureStore` 의 대역. UNIQUE(session_id) 와 INSERT→then→commit 순서만 흉내 낸다."""

    fake = True

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    def insert_then(self, row: Dict[str, Any], then: Callable[[], None]) -> str:
        if row["session_id"] in self.rows:
            return "duplicate"
        then()                                  # rename 이 실패하면 예외가 올라오고 행은 남지 않는다
        self.rows[row["session_id"]] = dict(row, received_at=datetime.now(timezone.utc).replace(tzinfo=None),
                                           purged_at=None)
        return "stored"

    def list_for_retention(self) -> List[Tuple[str, datetime, int, str]]:
        rows = [(r["session_id"], r["received_at"], int(r["archive_bytes"] or 0), r["archive_path"])
                for r in self.rows.values() if r["purged_at"] is None and r["archive_path"] is not None]
        return sorted(rows, key=lambda r: (r[1], r[0]))

    def mark_purged(self, session_id: str) -> int:
        row = self.rows.get(session_id)
        if row is None or row["purged_at"] is not None:
            return 0
        row.update(archive_path=None, archive_bytes=None, purged_at=datetime.now(timezone.utc).replace(tzinfo=None))
        return 1

    def close(self) -> None:
        pass


def _real_store() -> Optional[capture.CaptureStore]:
    try:
        settings.mysql_password()
    except Exception:  # noqa: BLE001 - MissingSetting
        return None
    try:
        store = capture.CaptureStore()
        store.connection()
        return store
    except Exception:  # noqa: BLE001
        return None


@pytest.fixture(scope="module")
def capture_store():
    store = _real_store()
    if store is None:
        store = FakeStore()
    yield store
    store.close()


def row_of(store: Any, session_id: str) -> Optional[Dict[str, Any]]:
    if getattr(store, "fake", False):
        return store.rows.get(session_id)
    conn = store.connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session_id, source_id, node_id, zone_id, kind, started_at, duration_s, frames_count, frames_bytes, "
            "archive_path, archive_bytes, manifest, correlation_id, received_at, purged_at "
            "FROM media_capture WHERE session_id = %s", (session_id,))
        rows = cur.fetchall()
    conn.commit()
    if not rows:
        return None
    assert len(rows) == 1
    keys = ("session_id", "source_id", "node_id", "zone_id", "kind", "started_at", "duration_s", "frames_count",
            "frames_bytes", "archive_path", "archive_bytes", "manifest", "correlation_id", "received_at", "purged_at")
    return dict(zip(keys, rows[0]))


def count_rows(store: Any, session_id: str) -> int:
    if getattr(store, "fake", False):
        return 1 if session_id in store.rows else 0
    conn = store.connection()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM media_capture WHERE session_id = %s", (session_id,))
        n = cur.fetchone()[0]
    conn.commit()
    return int(n)


# ── 서버 — 프로세스 안에서 임의 포트 ────────────────────────────────────────


@pytest.fixture(scope="module")
def capture_server(tmp_path_factory, capture_store):
    root = tmp_path_factory.mktemp("capture_root")
    storage = capture.CaptureStorage(root)
    service = capture.CaptureService(storage, capture_store)
    server = capture.build_server("127.0.0.1", 0, service, TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield {
        "base_url": "http://127.0.0.1:{}/capture?token={}".format(port, TOKEN),
        "base_url_bad_token": "http://127.0.0.1:{}/capture?token=wrong{}".format(port, uuid.uuid4().hex[:6]),
        "base_url_no_token": "http://127.0.0.1:{}/capture".format(port),
        "host": "127.0.0.1", "port": port, "root": root, "storage": storage, "store": capture_store,
    }
    server.shutdown()
    server.server_close()


def new_session(tmp_path: Path, kind: str = "capture_session", frames: int = 6,
                started: Optional[float] = None) -> Tuple[Path, Dict[str, Any], str]:
    entity = "test-cap-" + uuid.uuid4().hex[:8]
    name = "s" + uuid.uuid4().hex[:8]
    session_dir = up.build_session_dir(tmp_path / name, frames=frames, started=started)
    manifest = up.build_manifest(session_dir, entity, kind=kind)
    return session_dir, manifest, entity


def _final(root: Path, entity: str, name: str) -> Path:
    return root / entity / (name + ".tar.gz")


def _files_under(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _normalize(value: Any) -> Any:
    """MySQL JSON 칼럼은 **값**을 보존하지 키 순서·수의 표기까지 보존하지 않는다 — double 을 다시 찍을 때 마지막
    자리가 달라질 수 있다(서버 실측: `t0_unix` 17자리 float 가 한 자리 달라져 dict 비교가 깨졌다). 그래서 float 는
    밀리초까지만 맞춘다. 그 외(키 집합·문자열·None·중첩 구조)는 그대로 비교한다."""
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


# ── 순수 함수 단위 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("man, reason", [
    ({"session_id": "a/b", "source_id": "a"}, "manifest_missing_kind"),
    ({"kind": "capture_session", "source_id": "a"}, "manifest_missing_session_id"),
    ({"kind": "capture_session", "session_id": "a/b"}, "manifest_missing_source_id"),
    ({"kind": "capture_session", "session_id": "a/b", "source_id": "../evil"}, "source_id_unsafe"),
    ({"kind": "capture_session", "session_id": "../etc/passwd", "source_id": "a"}, "session_id_unsafe"),
    ({"kind": "capture_session", "session_id": "a/../b", "source_id": "a"}, "session_id_unsafe"),
    ({"kind": "capture_session", "session_id": "/abs/b", "source_id": "a"}, "session_id_unsafe"),
    ({"kind": "capture_session", "session_id": "a\\b", "source_id": "a"}, "session_id_unsafe"),
    ({"kind": "capture_session", "session_id": "a/b/c", "source_id": "a"}, "session_id_unsafe"),
    ({"kind": "capture_session", "session_id": "a/.hidden", "source_id": "a"}, "session_id_unsafe"),
    ("not an object", "manifest_not_object"),
])
def test_validate_manifest_rejects(man, reason) -> None:
    with pytest.raises(capture.CaptureError) as exc:
        capture.validate_manifest(man)
    assert exc.value.reason == reason
    assert exc.value.status == 400


def test_validate_manifest_keeps_kind_and_splits_session() -> None:
    v = capture.validate_manifest({"kind": "scan_capture_session", "session_id": "go1-001/20260910-134818",
                                   "source_id": "go1-001", "extra": 1})
    assert v == {"kind": "scan_capture_session", "session_id": "go1-001/20260910-134818",
                 "source_id": "go1-001", "session_name": "20260910-134818"}


def test_final_archive_path_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = capture.final_archive_path(root, "go1-001", "20260910-134818")
    assert target == (root / "go1-001" / "20260910-134818.tar.gz").resolve()
    assert root.resolve() in target.parents


@pytest.mark.parametrize("path", ["/capture/../../etc/passwd.tar.gz", "/capture/..%2F..%2Fetc.tar.gz",
                                  "/capture/a\\b.tar.gz", "/capture/x%00.tar.gz", "/capture/"])
def test_filename_of_url_path_rejects_traversal(path: str) -> None:
    with pytest.raises(capture.CaptureError) as exc:
        capture.filename_of_url_path(path)
    assert exc.value.status == 400


def test_manifest_row_started_at_rules() -> None:
    validated = {"kind": "capture_session", "session_id": "e/s", "source_id": "e", "session_name": "s"}
    t0 = 1789000000.5
    row = capture.manifest_row({"frames": {"t0_unix": t0, "count": 3, "bytes": 30}, "started_at": "2026-09-10T13:48:18"},
                               validated, Path("/x/e/s.tar.gz"), 123)
    assert row["started_at"] == datetime.fromtimestamp(t0, tz=timezone.utc).replace(tzinfo=None)
    assert row["frames_count"] == 3 and row["frames_bytes"] == 30 and row["archive_bytes"] == 123
    # t0_unix 가 없고 started_at 이 naive(오프셋 없음) → NULL. 서버가 시간대를 추측하지 않는다.
    row = capture.manifest_row({"started_at": "2026-09-10T13:48:18"}, validated, Path("/x"), 1)
    assert row["started_at"] is None
    # 오프셋이 있으면 UTC 로 바꿔 담는다.
    row = capture.manifest_row({"started_at": "2026-09-10T13:48:18.500+09:00"}, validated, Path("/x"), 1)
    assert row["started_at"] == datetime(2026, 9, 10, 4, 48, 18, 500000)
    # 스캔 세션 — shots[] 에서 센다. correlation_id 는 문자열일 때만.
    row = capture.manifest_row({"shots": [{"bytes": 10}, {"bytes": 5}], "correlation_id": "cmd-1"}, validated, Path("/x"), 1)
    assert row["frames_count"] == 2 and row["frames_bytes"] == 15 and row["correlation_id"] == "cmd-1"
    assert json.loads(row["manifest"])["shots"][1]["bytes"] == 5


def test_c5_select_for_purge_oldest_first() -> None:
    base = datetime(2026, 9, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    rows = [("s3", base + timedelta(days=3), 40), ("s1", base + timedelta(days=1), 100),
            ("s2", base + timedelta(days=2), 50), ("s4", base + timedelta(days=4), 10)]
    # 합계 200. 상한 120 → 오래된 순으로 s1(100) 을 빼면 100 ≤ 120. s2·s3·s4 는 남는다.
    picked = capture.select_for_purge(rows, 120)
    assert [p[0] for p in picked] == ["s1"]
    # 상한 55 → s1, s2 를 빼야 50 ≤ 55.
    assert [p[0] for p in capture.select_for_purge(rows, 55)] == ["s1", "s2"]
    # 상한이 합계 이상이면 아무것도 고르지 않는다. 최신 세션은 마지막까지 안 골라진다.
    assert capture.select_for_purge(rows, 200) == []
    assert [p[0] for p in capture.select_for_purge(rows, 0)] == ["s1", "s2", "s3", "s4"]


# ── 서버 관통 ────────────────────────────────────────────────────────────────


def test_10_1_manifest_then_archive_stored(capture_server, tmp_path: Path) -> None:
    session_dir, manifest, entity = new_session(tmp_path)
    result = up.upload_session(capture_server["base_url"], session_dir, manifest, tmp_path / "staged")
    assert result["manifest_status"] == 200, result
    assert result["archive_status"] == 201, result
    final = _final(capture_server["root"], entity, session_dir.name)
    assert final.exists()
    assert final.read_bytes() == Path(result["archive"]).read_bytes()            # 바이트 동일
    row = row_of(capture_server["store"], manifest["session_id"])
    assert row is not None and count_rows(capture_server["store"], manifest["session_id"]) == 1
    assert row["kind"] == "capture_session" and row["source_id"] == entity
    assert int(row["archive_bytes"]) == result["archive_bytes"]
    assert row["frames_count"] == 6
    stored_manifest = json.loads(row["manifest"])
    assert set(stored_manifest) == set(manifest)                                   # 매니페스트 원본 통째(키 전부)
    assert _normalize(stored_manifest) == _normalize(manifest)                     # 값 동일(float 는 ms 까지 — JSON 칼럼 정규화)
    assert stored_manifest["frame_ref_base"] is None                               # 서버가 채우지 않았다(원칙 10)
    assert row["started_at"] is not None                                           # t0_unix 로 채워진다
    assert row["purged_at"] is None
    assert not list(capture_server["storage"].incoming.iterdir())                  # 대기·임시 파일이 남지 않는다


def test_10_2_kind_preserved_for_scan_session(capture_server, tmp_path: Path) -> None:
    session_dir, manifest, entity = new_session(tmp_path, kind="scan_capture_session", frames=8)
    assert "shots" in manifest and "frames" not in manifest
    result = up.upload_session(capture_server["base_url"], session_dir, manifest, tmp_path / "staged")
    assert result["archive_status"] == 201, result
    row = row_of(capture_server["store"], manifest["session_id"])
    assert row["kind"] == "scan_capture_session"                                  # 덮어쓰지 않는다
    assert row["frames_count"] == 8                                               # shots[] 에서 센다
    assert json.loads(row["manifest"])["shots"][3]["heading_deg"] == 135          # 방위 대응표 보존
    assert _normalize(json.loads(row["manifest"])) == _normalize(manifest)
    assert row["started_at"] is None                                              # t0_unix 없음 + naive 문자열 → NULL


def test_10_3_duplicate_session_idempotent(capture_server, tmp_path: Path) -> None:
    session_dir, manifest, entity = new_session(tmp_path)
    first = up.upload_session(capture_server["base_url"], session_dir, manifest, tmp_path / "staged1")
    assert first["archive_status"] == 201
    final = _final(capture_server["root"], entity, session_dir.name)
    before = (final.stat().st_size, final.read_bytes())
    second = up.upload_session(capture_server["base_url"], session_dir, manifest, tmp_path / "staged2")
    assert second["manifest_status"] == 200 and second["archive_status"] == 200, second
    assert second["archive_body"]["status"] == "already_stored"
    assert count_rows(capture_server["store"], manifest["session_id"]) == 1
    assert (final.stat().st_size, final.read_bytes()) == before                    # 두 번째 파일은 버렸다
    assert not list(capture_server["storage"].incoming.iterdir())


def test_c1_token_mismatch_or_missing_nothing_written(capture_server, tmp_path: Path) -> None:
    before = _files_under(capture_server["root"])
    for base_url in (capture_server["base_url_bad_token"], capture_server["base_url_no_token"]):
        session_dir, manifest, entity = new_session(tmp_path / uuid.uuid4().hex[:6])
        result = up.upload_session(base_url, session_dir, manifest, tmp_path / "staged")
        assert result["manifest_status"] == 401 and result["archive_status"] is None, result
        # 매니페스트 없이 아카이브만 잘못된 토큰으로 — 역시 401
        result = up.upload_session(base_url, session_dir, manifest, tmp_path / "staged", send_manifest=False)
        assert result["archive_status"] == 401, result
        assert row_of(capture_server["store"], manifest["session_id"]) is None
        assert not _final(capture_server["root"], entity, session_dir.name).exists()
    assert _files_under(capture_server["root"]) == before                          # 파일도 행도 생기지 않는다


def test_c2_missing_field_and_archive_without_manifest(capture_server, tmp_path: Path) -> None:
    session_dir, manifest, entity = new_session(tmp_path)
    broken = dict(manifest)
    broken.pop("source_id")
    result = up.upload_session(capture_server["base_url"], session_dir, broken, tmp_path / "staged")
    assert result["manifest_status"] == 400 and result["manifest_body"]["error"] == "manifest_missing_source_id"
    assert result["archive_status"] is None
    # 매니페스트 PUT 없이 아카이브만 → 거부. 부분 적재가 남지 않는다.
    result = up.upload_session(capture_server["base_url"], session_dir, manifest, tmp_path / "staged", send_manifest=False)
    assert result["archive_status"] == 409 and result["archive_body"]["error"] == "manifest_required", result
    assert not _final(capture_server["root"], entity, session_dir.name).exists()
    assert row_of(capture_server["store"], manifest["session_id"]) is None
    assert not list(capture_server["storage"].incoming.glob("*.part"))
    # 이제 순서대로 보내면 된다(HW 는 2xx 가 아니면 원본을 지우지 않으므로 손실이 없다).
    result = up.upload_session(capture_server["base_url"], session_dir, manifest, tmp_path / "staged")
    assert result["archive_status"] == 201


def test_c3_path_traversal_in_url_and_manifest(capture_server, tmp_path: Path) -> None:
    root: Path = capture_server["root"]
    outside_before = sorted(p.name for p in root.parent.iterdir())
    files_before = _files_under(root)
    session_dir, manifest, entity = new_session(tmp_path)
    archive = up.pack(session_dir, tmp_path / "staged")
    # ① URL 파일명에 경로 순회 — 파일명 자체를 거부한다
    for evil in ("../../etc/passwd.tar.gz", "..%2F..%2Fetc%2Fpasswd.manifest.json", "x\\y.tar.gz"):
        status, body = up.http_put(up.join_url(capture_server["base_url"], evil), archive.read_bytes(), "application/gzip")
        assert status == 400, (evil, status, body)
    # ② 매니페스트 값에 경로 순회 — 최종 경로는 매니페스트가 정하므로 여기가 진짜 방어선이다
    for field, value in (("source_id", "../evil"), ("session_id", "../../etc/passwd"), ("session_id", "e/../x")):
        bad = dict(manifest, **{field: value})
        raw = json.dumps(bad).encode("utf-8")
        status, body = up.http_put(up.join_url(capture_server["base_url"], session_dir.name + ".manifest.json"), raw, "application/json")
        assert status == 400, (field, value, status, body)
    assert sorted(p.name for p in root.parent.iterdir()) == outside_before            # 루트 밖에 아무것도 없다
    assert _files_under(root) == files_before
    assert not list(capture_server["storage"].incoming.iterdir())


def test_c4_truncated_archive_leaves_nothing(capture_server, tmp_path: Path) -> None:
    session_dir, manifest, entity = new_session(tmp_path)
    raw = json.dumps(manifest).encode("utf-8")
    status, _ = up.http_put(up.join_url(capture_server["base_url"], session_dir.name + ".manifest.json"), raw, "application/json")
    assert status == 200
    archive = up.pack(session_dir, tmp_path / "staged")
    data = archive.read_bytes()
    # Content-Length 를 실제보다 크게 적고 중간에 끊는다 — 전송 중 끊김.
    sock = socket.create_connection((capture_server["host"], capture_server["port"]), timeout=10)
    try:
        head = ("PUT /capture/{}.tar.gz?token={} HTTP/1.1\r\nHost: x\r\nContent-Type: application/gzip\r\n"
                "Content-Length: {}\r\n\r\n").format(session_dir.name, TOKEN, len(data) + 4096)
        sock.sendall(head.encode("ascii") + data[: len(data) // 2])
    finally:
        sock.close()
    final = _final(capture_server["root"], entity, session_dir.name)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and list(capture_server["storage"].incoming.glob("*.part")):
        time.sleep(0.1)
    assert not list(capture_server["storage"].incoming.glob("*.part"))               # 불완전 파일이 남지 않는다
    assert not final.exists()
    assert row_of(capture_server["store"], manifest["session_id"]) is None
    assert capture_server["storage"].load_pending_manifest(session_dir.name) is not None   # 매니페스트는 대기 — 재전송 가능
    # 재전송하면 정상 저장된다.
    result = up.upload_session(capture_server["base_url"], session_dir, manifest, tmp_path / "staged2")
    assert result["archive_status"] == 201 and final.read_bytes() == data


def test_c5_retention_dry_run_over_store(capture_server, tmp_path: Path) -> None:
    store, storage = capture_server["store"], capture_server["storage"]
    # 이 테스트가 만든 두 세션 — 오래된 것과 최신 것(received_at 순서를 확실히 하려고 사이에 잠깐 쉰다).
    old_dir, old_man, old_entity = new_session(tmp_path / "old")
    assert up.upload_session(capture_server["base_url"], old_dir, old_man, tmp_path / "s1")["archive_status"] == 201
    time.sleep(0.05)
    new_dir, new_man, new_entity = new_session(tmp_path / "new")
    assert up.upload_session(capture_server["base_url"], new_dir, new_man, tmp_path / "s2")["archive_status"] == 201
    rows = store.list_for_retention()
    ids = [r[0] for r in rows]
    assert ids.index(old_man["session_id"]) < ids.index(new_man["session_id"])        # 오래된 순
    total = sum(r[2] for r in rows)
    newest_bytes = next(r[2] for r in rows if r[0] == new_man["session_id"])
    # 상한 = 최신 세션 크기 → 오래된 것부터 빼다가 최신 하나만 남으면 멈춘다. 최신은 안 골라지고 그 앞은 전부 골라진다.
    result = capture.purge_sessions(storage, store, newest_bytes, dry_run=True)
    selected = {s["session_id"] for s in result["selected"]}
    assert result["dry_run"] is True and result["total_bytes"] == total
    assert new_man["session_id"] not in selected
    assert old_man["session_id"] in selected
    assert selected == set(ids[:-1])                                                  # 최신 하나 빼고 전부, 오래된 순
    # dry-run — 파일도 행도 그대로다.
    assert _final(capture_server["root"], old_entity, old_dir.name).exists()
    assert row_of(store, old_man["session_id"])["purged_at"] is None
    # 상한이 합계 이상이면 아무것도 고르지 않는다.
    assert capture.purge_sessions(storage, store, total, dry_run=True)["selected"] == []
