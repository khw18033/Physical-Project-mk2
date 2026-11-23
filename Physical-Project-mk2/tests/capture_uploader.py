"""합성 촬영본 업로더 — HW `pi/robot/capture_upload.py` 의 모양을 흉내 낸 가짜 업로더(4b 검증용).

실물 로봇 촬영본이 없으므로, HW 매니페스트 모양(`build_manifest`)과 같은 dict 를 만들고 fixture JPEG 를
복사해 세션 디렉터리 → `tar.gz` 로 묶어 **PUT 두 번**(매니페스트 → 아카이브)을 보낸다. 표준 라이브러리만
쓴다(HW 업로더와 같다 — `urllib.request`, `tarfile`).

HW 와 같은 점: `session_id = "{entity_id}/{세션디렉터리명}"` · `frames.t0_unix/interval_s` · `frame_ref_base: None`
· `started_at` 은 **오프셋 없는 naive 문자열**(HW 촬영 도구가 그렇게 낸다 — 서버는 이를 NULL 로 두어야 한다)
· `Content-Type: application/gzip` · 2xx 면 성공.
HW 와 다른 점(v2 규약): 매니페스트를 아카이브 **앞에 별도 PUT** 으로 보낸다(`--no-manifest` 로 C2 음성 대조).

실행(컴퓨터·서버 어디서든):
  python tests/capture_uploader.py --base-url http://<서버 tailscale IP>:8767/capture?token=<토큰> --entity-id go1-001
  python tests/capture_uploader.py --kind scan_capture_session --frames 8        # 8방향 스캔 세션 모양
  python tests/capture_uploader.py --no-manifest                                 # C2: 아카이브만 → 거부돼야 한다

implements: BE-S-09 (검증 수단 — 가짜 업로더)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend import settings  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
JPEGS = sorted(FIXTURES.glob("synthetic_464x400_*.jpg"))
MANIFEST_VERSION = "1.0"


def build_session_dir(dst: Path, frames: int = 6, fps: float = 10.0, camera: int = 1,
                      started: Optional[float] = None, jpegs: Optional[List[Path]] = None) -> Path:
    """세션 디렉터리를 만든다 — `frame_%06d.jpg` + `session.json`(HW 촬영 도구 모양)."""
    jpegs = jpegs or JPEGS
    if not jpegs:
        raise RuntimeError("fixture JPEG 이 없다: {}".format(FIXTURES))
    dst.mkdir(parents=True, exist_ok=True)
    for n in range(1, frames + 1):
        shutil.copyfile(jpegs[(n - 1) % len(jpegs)], dst / "frame_{:06d}.jpg".format(n))
    started = time.time() if started is None else started
    meta = {
        "fps": fps, "camera": camera, "jpeg_quality": 2,
        "started_at": started,
        # HW go1_capture_teleop.py:250 · go1_scan_capture.py:268 — 오프셋·밀리초 없는 naive 로컬 시각
        "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
    }
    (dst / "session.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def build_manifest(session_dir: Path, entity_id: str, node_id: str = "pi7", zone_id: str = "zoneA",
                   kind: str = "capture_session", correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """HW `capture_upload.py::build_manifest` 와 같은 모양. `kind` 가 스캔이면 `shots[]` 를 넣는다."""
    name = session_dir.name
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    frames = sorted(p.name for p in session_dir.glob("frame_*.jpg"))
    total = sum((session_dir / f).stat().st_size for f in frames)
    fps = meta.get("fps")
    man: Dict[str, Any] = {
        "schema_version": MANIFEST_VERSION,
        "kind": kind,
        "session_id": "{}/{}".format(entity_id, name),
        "source_id": entity_id,
        "node_id": node_id,
        "zone_id": zone_id,
        "started_at": meta.get("started_at_iso"),
        "duration_s": round(len(frames) / fps, 1) if (fps and frames) else None,
        "sensor": {"type": "camera", "position": "front", "camera_id": meta.get("camera"),
                   "fps": fps, "format": "jpeg", "jpeg_quality": meta.get("jpeg_quality")},
        "frames": {"count": len(frames), "bytes": total, "naming": "frame_%06d.jpg",
                   "t0_unix": meta.get("started_at"),
                   "interval_s": round(1.0 / fps, 4) if fps else None, "uri": None},
        "motion": None, "pose_track": None,
        "frame_ref_base": None,          # 엣지를 거치지 않으므로 발급 주체가 없다 — 서버도 채우지 않는다
        "labels": None,
    }
    if kind != "capture_session":
        # 8방향 스캔 세션 — shots[] 의 방위 대응표가 곧 데이터다(서버가 kind 를 덮어쓰면 소실된다)
        man["shots"] = [{"file": f, "bytes": (session_dir / f).stat().st_size, "heading_deg": i * 45}
                        for i, f in enumerate(frames)]
        man.pop("frames")
    if correlation_id:
        man["correlation_id"] = correlation_id
    return man


def pack(session_dir: Path, out_dir: Path) -> Path:
    """HW `pack()` 그대로 — 세션 디렉터리를 `<name>.tar.gz` 로(arcname = 디렉터리명)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (session_dir.name + ".tar.gz")
    with tarfile.open(path, "w:gz") as tf:
        tf.add(str(session_dir), arcname=session_dir.name)
    return path


def http_put(url: str, data: bytes, content_type: str, timeout: float = 120) -> Tuple[int, Dict[str, Any]]:
    """단순 PUT. 2xx 가 아니면 `HTTPError` 를 잡아 (status, body) 로 돌려준다(HW 는 예외로 본다)."""
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, _json_or_empty(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _json_or_empty(exc.read())


def _json_or_empty(raw: bytes) -> Dict[str, Any]:
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        return {"raw": raw[:200].decode("utf-8", "replace")}


def join_url(base_url: str, filename: str) -> str:
    """HW `http_put` 과 같은 규칙(`base.rstrip("/") + "/" + basename`) — 단 쿼리(`?token=`)는 뒤로 보낸다."""
    base, _, query = base_url.partition("?")
    url = base.rstrip("/") + "/" + filename
    return url + ("?" + query if query else "")


def upload_session(base_url: str, session_dir: Path, manifest: Dict[str, Any], out_dir: Path,
                   send_manifest: bool = True) -> Dict[str, Any]:
    """매니페스트 PUT → 2xx → 아카이브 PUT. 결과 dict 에 두 응답과 아카이브 경로·크기를 담는다."""
    archive = pack(session_dir, out_dir)
    result: Dict[str, Any] = {"archive": str(archive), "archive_bytes": archive.stat().st_size,
                              "manifest_status": None, "manifest_body": None}
    if send_manifest:
        raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        status, body = http_put(join_url(base_url, session_dir.name + ".manifest.json"), raw, "application/json")
        result["manifest_status"], result["manifest_body"] = status, body
        if not 200 <= status < 300:
            result["archive_status"], result["archive_body"] = None, None
            return result
    with open(archive, "rb") as fh:
        status, body = http_put(join_url(base_url, session_dir.name + ".tar.gz"), fh.read(), "application/gzip")
    result["archive_status"], result["archive_body"] = status, body
    return result


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="합성 촬영본 업로더(HW capture_upload.py 모양)")
    p.add_argument("--base-url", default=None, help="기본 MK2_CAPTURE_URL(설정)")
    p.add_argument("--entity-id", default="go1-001")
    p.add_argument("--session-name", default=None, help="세션 디렉터리명(기본 시각 기반 — HW 와 같은 모양)")
    p.add_argument("--kind", default="capture_session")
    p.add_argument("--frames", type=int, default=6)
    p.add_argument("--fps", type=float, default=10.0)
    p.add_argument("--correlation-id", default=None)
    p.add_argument("--no-manifest", action="store_true", help="아카이브만 보낸다(C2 음성 대조 — 거부돼야 한다)")
    p.add_argument("--out", default=None, help="세션·아카이브를 만들 디렉터리(기본 임시)")
    a = p.parse_args(argv)
    base_url = a.base_url or settings.capture_url()
    out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="mk2_capture_"))
    name = a.session_name or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    session_dir = build_session_dir(out / name, frames=a.frames, fps=a.fps)
    manifest = build_manifest(session_dir, a.entity_id, kind=a.kind, correlation_id=a.correlation_id)
    result = upload_session(base_url, session_dir, manifest, out / "staged", send_manifest=not a.no_manifest)
    print(json.dumps({"session_id": manifest["session_id"], "kind": a.kind, **result}, ensure_ascii=False, indent=2))
    ok = result.get("archive_status") is not None and 200 <= result["archive_status"] < 300
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
