"""레이더 팀 quick-look(`cansar_quick.py`)을 패스마다 돌려 결과 PNG 를 화면에 준다 — 레이더 팀 README(2026-10-04) 그대로.

  Pi:  python -m sar_data … --cansar-quick /home/physical/cansar/cansar_quick.py \\
           --cansar-data /home/physical/flight --cansar-logs /home/physical/cansar_logs --cansar-side right

지키는 것(그쪽 README 「주의」):
  - 그쪽 명령 · 출력 이름(quick_N.png · quick_N.npz)만 쓴다. 코드는 그쪽이 계속 바꾼다.
  - 비행 제어와 같은 기기 → `nice -n 19`, `--fine` 은 안 쓴다.
  - CAP_ON 이 있으면(다음 패스 캡처 중) 미룬다.
  - 한 번에 하나씩, 패스마다 **따로 만든 작업 폴더**에서(flight_img.png 가 겹치지 않게).
  - 실패하면(0 이 아닌 종료) 로그를 남기고 화면에 사유를 보인다.

새 패스는 `<로그>/*/passes.csv` 에 새 줄(n)이 생기고 `iq_N.bin` · `meta_N.txt` 가 있으면 줄 세운다.
결과는 `<flights>/cansar_quick/<N>/` — quick.png · quick.npz · log.txt · result.json. 노트북 미러가 이것을 그대로 가져간다.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("sar_data.quick")

FILES = {"quick.png": "image/png", "quick.npz": "application/octet-stream", "log.txt": "text/plain; charset=utf-8",
         "result.json": "application/json"}

_VERDICT = re.compile(r"^\[판정\]\s*#(\d+)\s*(.*?)\s*→\s*(\S+)")
_PEAK = re.compile(r"영상 첨두\s*([-\d.]+)\s*dB\s*@\s*진행\s*([+-]?[\d.]+)\s*m,\s*옆\s*([+-]?[\d.]+)\s*m\s*\(배경 중앙값\s*([+-]?[\d.]+)\s*dB\)")
_TIME = re.compile(r"^\[시각\].*?pi_epoch 차\s*([\d.]+)\s*s")


def parse_stdout(text: str) -> dict:
    """그쪽 표준 출력에서 화면에 보일 줄을 뽑는다. 못 찾으면 그 칸은 None."""
    out: dict = {"verdict": None, "verdict_line": None, "peak": None, "peak_line": None, "time_match_s": None, "warnings": []}
    for line in text.splitlines():
        s = line.strip()
        m = _VERDICT.match(s)
        if m:
            out["verdict"], out["verdict_line"] = m.group(3), re.sub(r"^\[판정\]\s*", "", s)    # 화면이 「판정」 칸 이름을 따로 붙인다
        m = _PEAK.search(s)
        if m:
            out["peak"] = {"db": float(m.group(1)), "along_m": float(m.group(2)), "side_m": float(m.group(3)),
                           "background_db": float(m.group(4))}
            out["peak_line"] = s
        m = _TIME.match(s)
        if m:
            out["time_match_s"] = float(m.group(1))
        if "[!]" in s:
            out["warnings"].append(s)
    return out


def _write(path: Path, body: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class QuickLooks:
    """script 가 있으면 돌리는 쪽(Pi), 없으면 미러로 받은 결과만 보여 주는 쪽(노트북 · 서버)."""

    def __init__(self, root: Path, script: Path | None = None, data_dir: Path | None = None, logs_root: Path | None = None,
                 side: str = "right", cap_path: Path | None = None, python: str = sys.executable, nice: bool = True,
                 timeout_s: float = 900.0, interval_s: float = 5.0, settle_s: float = 3.0,
                 lever: list[float] | None = None) -> None:
        self.root = Path(root)
        # 절대 경로로 — 그쪽 스크립트는 패스마다 따로 만든 작업 폴더에서 돈다(상대 경로면 거기서 못 찾는다)
        self.script = Path(script).resolve() if script else None
        self.data_dir = Path(data_dir).resolve() if data_dir else None
        self.logs_root = Path(logs_root).resolve() if logs_root else None
        self.side = side
        self.cap_path = Path(cap_path) if cap_path else None
        self.python = python
        self.nice = nice and shutil.which("nice") is not None
        self.timeout_s = timeout_s
        self.interval_s = interval_s
        self.settle_s = settle_s
        self.q: queue.Queue[tuple[int, dict]] = queue.Queue()
        self._queued: set[int] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.last_error: str | None = None
        # 레이더 안테나 위치(FC 기준 앞 · 오른쪽 · 아래 m) — 그쪽 v2 의 --lever 로 넘긴다. 드론 쪽 radar.json 의 antenna_offset_m 과 같은 값
        self.lever = [float(x) for x in lever] if lever and any(abs(float(x)) > 0 for x in lever) else None

    @property
    def runner(self) -> bool:
        return self.script is not None

    def missing(self) -> list[str]:
        if not self.runner:
            return []
        miss = []
        if not self.script.is_file():  # type: ignore[union-attr]
            miss.append(f"cansar_quick.py 없음: {self.script}")
        if self.data_dir is None or not self.data_dir.is_dir():
            miss.append(f"원시 폴더 없음: {self.data_dir}")
        if self.logs_root is None or not self.logs_root.is_dir():
            miss.append(f"로그 폴더 없음: {self.logs_root}")
        return miss

    def state(self) -> dict:
        return {"runner": self.runner, "side": self.side if self.runner else None, "lever": self.lever, "queued": sorted(self._queued),
                "missing": self.missing(), "last_error": self.last_error}

    # ── 목록 · 파일 ─────────────────────────────────────────────────────────
    def items(self) -> list[dict]:
        out = []
        if self.root.is_dir():
            for d in self.root.iterdir():
                f = d / "result.json"
                if d.is_dir() and d.name.isdigit() and f.is_file():
                    try:
                        out.append(json.loads(f.read_text(encoding="utf-8")))
                    except (OSError, ValueError):
                        continue
        # N 은 시각(HHMMSS)이라 날이 바뀌면 거꾸로 간다 — 패스 시작 시각(t0)으로 줄 세운다
        return sorted(out, key=lambda r: r.get("t0") or r.get("queued_unix") or 0, reverse=True)

    def file(self, n: int, name: str) -> Path | None:
        if name not in FILES:
            return None
        p = self.root / str(int(n)) / name
        return p if p.is_file() else None

    # ── 돌리기 (Pi) ─────────────────────────────────────────────────────────
    def start(self) -> None:
        if self.runner:
            threading.Thread(target=self._loop, name="cansar-quick", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def passes(self) -> list[dict]:
        rows = []
        if self.logs_root is None or not self.logs_root.is_dir():
            return rows
        for pc in self.logs_root.glob("*/passes.csv"):
            try:
                with pc.open(encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        if (r.get("n") or "").isdigit():
                            rows.append({**r, "_logdir": pc.parent.name})
            except OSError:
                continue
        return rows

    def scan(self, now: float | None = None) -> list[int]:
        """새로 줄 세운 N 들."""
        now = time.time() if now is None else now
        got = []
        for r in self.passes():
            n = int(r["n"])
            if n in self._queued or self._finished(n):
                continue
            iq = self.data_dir / f"iq_{n}.bin" if self.data_dir else None
            meta = self.data_dir / f"meta_{n}.txt" if self.data_dir else None
            if iq is None or not iq.is_file() or not meta.is_file():          # type: ignore[union-attr]
                continue                                                      # 아직 복사 전
            if now - iq.stat().st_mtime < self.settle_s:
                continue                                                      # 복사 중
            self.request(n, row=r)
            got.append(n)
        return got

    def _finished(self, n: int) -> bool:
        """done · failed 면 끝난 것. queued · running 이 남아 있으면 지난번에 꺼진 것 — 다시 돈다."""
        try:
            return json.loads((self.root / str(n) / "result.json").read_text(encoding="utf-8")).get("state") in ("done", "failed")
        except (OSError, ValueError):
            return False

    def request(self, n: int, force: bool = False, row: dict | None = None) -> tuple[int, dict]:
        if not self.runner:
            return 501, {"error": "이 서버는 quick-look 을 돌리지 않는다(Pi 에서 돈다) — 결과만 보여 준다"}
        miss = self.missing()
        if miss:
            return 501, {"error": "quick-look 설정이 빠졌다", "missing": miss}
        with self._lock:
            if n in self._queued:
                return 200, {"state": "queued", "n": n}
            done = self.root / str(n) / "result.json"
            if self._finished(n) and not force:
                return 200, json.loads(done.read_text(encoding="utf-8"))
            if row is None:
                row = next((r for r in self.passes() if r["n"] == str(n)), {})
            self._queued.add(n)
        d = self.root / str(n)
        d.mkdir(parents=True, exist_ok=True)
        body = {"schema": "cansar-quick-0.1", "n": n, "state": "queued", "queued_unix": time.time(),
                "t0": float(row["t0"]) if row.get("t0") else None, "pass": {k: v for k, v in row.items() if not k.startswith("_")},
                "side": self.side, "label": "quick-look"}
        _write(d / "result.json", body)
        self.q.put((n, body))
        return 202, body

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("quick-look 확인 실패")
            try:
                n, body = self.q.get(timeout=self.interval_s)
            except queue.Empty:
                continue
            try:
                self.run_one(n, body)
            except Exception:  # noqa: BLE001
                log.exception("quick-look #%s 실패", n)
            finally:
                with self._lock:
                    self._queued.discard(n)

    def _wait_capture(self, body: dict, path: Path) -> None:
        """CAP_ON 이 있으면(다음 패스 캡처 중) 기다린다 — 비행 제어와 같은 기기다."""
        if self.cap_path is None:
            return
        waited = 0.0
        while self.cap_path.exists() and not self._stop.is_set() and waited < 3600:
            if waited == 0:
                body["state"] = "waiting_capture"
                _write(path, body)
            time.sleep(1.0)
            waited += 1.0

    def run_one(self, n: int, body: dict | None = None) -> dict:
        d = self.root / str(n)
        d.mkdir(parents=True, exist_ok=True)
        rpath = d / "result.json"
        body = body or {"schema": "cansar-quick-0.1", "n": n, "label": "quick-look", "side": self.side}
        self._wait_capture(body, rpath)
        work = d / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir()
        cmd = ([("nice"), "-n", "19"] if self.nice else []) + [
            self.python, str(self.script), "--nopull", "--data-dir", str(self.data_dir), "--logs-root", str(self.logs_root),
            "--n", str(n), "--side", self.side, "--noopen"] + (["--", "--lever", *[f"{x:g}" for x in self.lever]] if self.lever else [])
        body.update(state="running", started_unix=time.time(), command=cmd)
        _write(rpath, body)
        log.info("quick-look #%d 시작", n)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "MPLBACKEND": "Agg"}
        try:
            r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=self.timeout_s, env=env)
            code, stdout, stderr = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired as exc:
            code, stdout, stderr = -1, (exc.stdout or "") if isinstance(exc.stdout, str) else "", f"시간 초과 {self.timeout_s:.0f} s"
        (d / "log.txt").write_text(stdout + ("\n--- stderr ---\n" + stderr if stderr.strip() else ""), encoding="utf-8")
        png, npz = work / f"quick_{n}.png", work / f"quick_{n}.npz"
        if code == 0 and png.is_file():
            shutil.move(str(png), d / "quick.png")
            if npz.is_file():
                shutil.move(str(npz), d / "quick.npz")
        body.update(parse_stdout(stdout), returncode=code, finished_unix=time.time(),
                    state="done" if code == 0 and (d / "quick.png").is_file() else "failed",
                    error=None if code == 0 else (stderr.strip().splitlines() or stdout.strip().splitlines() or ["?"])[-1][:300])
        body["duration_s"] = round(body["finished_unix"] - body["started_unix"], 2)
        _write(rpath, body)
        shutil.rmtree(work, ignore_errors=True)
        log.info("quick-look #%d %s (%.1f s)", n, body["state"], body["duration_s"])
        return body


__all__ = ["FILES", "QuickLooks", "parse_stdout"]
