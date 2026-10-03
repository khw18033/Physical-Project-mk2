"""비행이 끝나면 FC 의 `.ulg` 를 받아 그 비행 폴더에 둔다 — 「비행 후 QGC 에서 .ulg 받기」를 사람이 잊지 않게.

    # Pi 에 상주 (systemd). 착륙 · 시동 꺼짐을 보고 그 비행의 로그를 받는다
    python -m sar_pass ulog --watch --connect tcp://127.0.0.1:5760 --log-dir /home/physical/sar_logs

    # 지금 가장 최근 로그 하나만
    python -m sar_pass ulog --connect tcp://127.0.0.1:5760 --log-dir sar_logs

연결: 패스 비행(MAVSDK 14540)과 겹치지 않게 mavlink-router 의 TCP 5760(QGC 와 같이 쓴다)이나 따로 둔 UDP 끝점을
쓴다. MAVSDK 서버도 다른 포트(50052)로 띄운다 — 같은 Pi 에서 에이전트의 서버(50051)와 부딪치지 않게.

어느 비행 폴더에 두나: 시동이 꺼진 순간보다 앞서 시작한 `flight_<시각>` 중 가장 최근 것(그 비행 동안 생긴 것).
없으면 `ulog/` 아래에 둔다. 받은 뒤 `ulog.json` 에 FC 의 로그 번호 · 날짜 · 크기 · 받은 시각을 적는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger("sar_pass.ulog")

FLIGHT_RE = re.compile(r"^flight_(\d+)$")


def flight_dir_for(log_dir: Path, when: float, max_age_s: float = 3 * 3600) -> Path:
    """`when` 직전에 시작한 비행 폴더. 너무 오래됐거나 없으면 `ulog/`."""
    best: tuple[int, Path] | None = None
    if log_dir.is_dir():
        for d in log_dir.iterdir():
            m = FLIGHT_RE.match(d.name)
            if d.is_dir() and m:
                t = int(m.group(1))
                if t <= when + 5 and when - t <= max_age_s and (best is None or t > best[0]):
                    best = (t, d)
    return best[1] if best else log_dir / "ulog"


def newest(entries):  # noqa: ANN001, ANN201
    """FC 로그 목록에서 가장 최근 것 — 날짜 문자열(ISO)이 같으면 번호가 큰 것."""
    return max(entries, key=lambda e: (e.date or "", e.id)) if entries else None


class UlogFetcher:
    def __init__(self, address: str, log_dir: Path, grpc_port: int = 50052, timeout_s: float = 30.0) -> None:
        self.address = address
        self.log_dir = log_dir
        self.grpc_port = grpc_port
        self.timeout_s = timeout_s
        self.system = None

    async def connect(self) -> None:
        import mavsdk_grpc as mavsdk

        self.system = mavsdk.System(port=self.grpc_port)

        async def go() -> None:
            await self.system.connect(system_address=self.address)
            async for st in self.system.core.connection_state():
                if st.is_connected:
                    return

        try:
            await asyncio.wait_for(go(), self.timeout_s)
        except BaseException:
            self.close()
            raise
        log.info("FC 연결됨 %s (로그 받기용)", self.address)

    def close(self) -> None:
        if self.system is not None:
            try:
                self.system._stop_mavsdk_server()
            except Exception:  # noqa: BLE001
                pass

    async def fetch_latest(self, when: float | None = None) -> Path | None:
        when = time.time() if when is None else when
        entries = await self.system.log_files.get_entries()
        e = newest(entries)
        if e is None:
            log.warning("FC 에 로그가 없다")
            return None
        target_dir = flight_dir_for(self.log_dir, when)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = re.sub(r"[^0-9T]", "", e.date or "")[:15] or str(e.id)
        out = target_dir / f"fc_{stamp}_{e.id}.ulg"
        if out.exists() and out.stat().st_size == e.size_bytes:
            log.info("이미 받았다 %s", out)
            return out
        part = out.with_suffix(".ulg.part")
        log.info("받는 중 로그 %d (%s, %.1f MB) → %s", e.id, e.date, e.size_bytes / 1e6, out)
        t0 = time.time()
        last = -1
        async for prog in self.system.log_files.download_log_file(e, str(part)):
            pct = int(prog.progress * 100)
            if pct // 20 != last // 20:
                log.info("  %d%%", pct)
            last = pct
        part.replace(out)
        meta_path = target_dir / "ulog.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {"logs": []}
        meta["logs"] = [x for x in meta.get("logs", []) if x.get("file") != out.name] + [{
            "file": out.name, "fc_log_id": e.id, "fc_date_utc": e.date, "size_bytes": out.stat().st_size,
            "fetched_unix": time.time(), "download_s": round(time.time() - t0, 1), "disarmed_unix": when}]
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("받았다 %s (%.1f s)", out, time.time() - t0)
        return out

    async def watch(self, settle_s: float = 5.0) -> None:
        """시동이 꺼질 때마다 그 비행의 로그를 받는다. PX4 는 꺼지면서 로그를 닫는다 — 조금 기다린다."""
        armed_before = None
        async for armed in self.system.telemetry.armed():
            if armed_before and not armed:
                when = time.time()
                log.info("시동 꺼짐 — %.0f s 뒤 로그를 받는다", settle_s)
                await asyncio.sleep(settle_s)
                for attempt in range(3):
                    try:
                        await self.fetch_latest(when)
                        break
                    except Exception as exc:  # noqa: BLE001 — 링크가 잠깐 끊겨도 다시
                        log.warning("로그 받기 실패 (%d/3): %s", attempt + 1, exc)
                        await asyncio.sleep(5)
            armed_before = armed


async def run(address: str, log_dir: Path, watch: bool, grpc_port: int = 50052) -> int:
    f = UlogFetcher(address, log_dir, grpc_port)
    await f.connect()
    try:
        if watch:
            await f.watch()
            return 0
        return 0 if await f.fetch_latest() else 1
    finally:
        f.close()
