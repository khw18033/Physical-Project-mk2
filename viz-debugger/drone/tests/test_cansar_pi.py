"""레이더 브리지(cansar_pi.py, 레이더 팀) — 가짜 SDR(tests/fake_sdr/sshpass)로 보드 없이 돌린다.

원본: CAP_ON 으로 켜고 끄면 events.csv start · stop, passes.csv 한 줄, ~/flight 로 복사.
드론 쪽 제안(radar_team/cansar_pi.py): + CAP_ACK · 1 초 시계 행 · 응답 시각 · passes.csv 에 pass · flight.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ORIG = HERE / "data" / "cansar" / "cansar_pi_orig.py"
PROPOSAL = HERE.parent / "radar_team" / "cansar_pi.py"


def _wait(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def _run(script: Path, tmp: Path, extra: list[str]):
    env = {**os.environ, "PATH": f"{HERE / 'fake_sdr'}:{os.environ['PATH']}", "HOME": str(tmp),
           "FAKE_SDR": str(tmp / "sdr"), "FAKE_SDR_BOOT": str(time.time() - 5000.0), "PYTHONUNBUFFERED": "1"}
    (tmp / "flight").mkdir(exist_ok=True)
    return subprocess.Popen([sys.executable, str(script), "--conn", "none", "--file", str(tmp / "CAP_ON"),
                             "--flight", str(tmp / "flight"), "--status", "1000", *extra],
                            env=env, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _rows(tmp: Path, name: str) -> list[dict]:
    files = sorted((tmp / "cansar_logs").glob(f"*/{name}"))
    if not files:
        return []
    with files[-1].open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("which", ["orig", "proposal"])
def test_bridge_with_fake_sdr(tmp_path, which):
    script = ORIG if which == "orig" else PROPOSAL
    extra = [] if which == "orig" else ["--ack", str(tmp_path / "CAP_ACK"), "--clock", "0.5"]
    p = _run(script, tmp_path, extra)
    try:
        assert _wait(lambda: _rows(tmp_path, "events.csv") == [] and any((tmp_path / "cansar_logs").glob("*/events.csv")))
        (tmp_path / "CAP_ON").write_text(json.dumps({"pass": 2, "flight": "flight_1791000000", "time": time.time()}))
        assert _wait(lambda: any(r["event"] == "start" for r in _rows(tmp_path, "events.csv")))
        if which == "proposal":
            assert _wait(lambda: (tmp_path / "CAP_ACK").exists())
            assert abs(float((tmp_path / "CAP_ACK").read_text()) - time.time()) < 5
        time.sleep(2.2)
        (tmp_path / "CAP_ON").unlink()
        assert _wait(lambda: any(r["event"] == "stop" for r in _rows(tmp_path, "events.csv")))
        assert _wait(lambda: len(_rows(tmp_path, "passes.csv")) == 1)
        assert _wait(lambda: any((tmp_path / "flight").glob("iq_*.bin")) and any((tmp_path / "flight").glob("meta_*.txt")))
        ev = _rows(tmp_path, "events.csv")
        start = next(r for r in ev if r["event"] == "start")
        float(start["sdr_uptime"])                                            # SDR 시각이 숫자로 들어왔다
        if which == "proposal":
            assert not (tmp_path / "CAP_ACK").exists()                        # 끄면 지운다
            clocks = [r for r in ev if r["event"] == "clock"]
            assert len(clocks) >= 2 and all("rtt=" in r["note"] for r in clocks)
            assert "req=" in start["note"]
            row = _rows(tmp_path, "passes.csv")[0]
            assert row["pass"] == "2" and row["flight"] == "flight_1791000000"
    finally:
        p.terminate()
        try:
            out, _ = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
    assert "Traceback" not in out, out[-1500:]
