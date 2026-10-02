"""비행 전 점검 — 날지 않고 확인한다.  `python -m sar_pass check --connect … --mqtt …`

  ✓ 통과   ! 주의(날 수는 있다)   ✗ 막힘(이대로는 시작이 거절되거나 데이터가 틀린다)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .mission import MAX_CLOCK_OFFSET_S


@dataclass
class Item:
    mark: str   # ✓ ! ✗
    what: str
    detail: str


def _run(cmd: list[str]) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def check_ack(path: Path | None) -> list[Item]:
    if path is None:
        return [Item("!", "레이더 확인", "CAP_ACK 경로를 안 줬다 — 실제 기록 시각을 모른 채 난다 (--cap-ack)")]
    if path.exists():
        return [Item("!", "레이더 확인", f"{path} 가 남아 있다 — 시작 때 지운다")]
    return [Item("✓", "레이더 확인", f"{path} (cansar 가 기록 시작 시 쓴다)")]


def check_cap(path: Path) -> list[Item]:
    out = []
    parent = path.parent
    if parent.is_dir() and os.access(parent, os.W_OK):
        out.append(Item("✓", "CAP_ON 자리", f"{parent} 쓰기 가능"))
    else:
        out.append(Item("✗", "CAP_ON 자리", f"{parent} 가 없거나 쓸 수 없다 — 만들거나 권한을 준다"))
    if path.exists():
        out.append(Item("!", "CAP_ON 남아 있음", f"{path} — 지금 레이더가 캡처 중일 수 있다. 시작 때 지운다"))
    return out


def check_clock() -> list[Item]:
    synced = _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    if synced == "yes":
        return [Item("✓", "시계 동기화", "NTP 동기화됨")]
    if synced == "no":
        return [Item("!", "시계 동기화", "NTP 동기화 안 됨 — 핫스팟에 인터넷이 없으면 아래 FC(GPS) 시각과의 차이로 판단한다")]
    return [Item("!", "시계 동기화", "timedatectl 없음 — FC(GPS) 시각과의 차이로 판단한다")]


def check_service(name: str) -> list[Item]:
    state = _run(["systemctl", "is-active", name])
    if state is None:
        return [Item("!", name, "systemctl 로 확인할 수 없다")]
    return [Item("✓" if state == "active" else "!", name, state)]


async def check_fc(address: str, wait_s: float = 8.0) -> list[Item]:
    from .mavsdk_vehicle import MavsdkVehicle

    v = MavsdkVehicle(address)
    try:
        await v.connect(timeout_s=15.0)
    except asyncio.TimeoutError:
        return [Item("✗", "FC 연결", f"{address} — 15초 안에 FC heartbeat 가 없다 (mavlink-router 끝점 · 배선 확인)")]
    except Exception as exc:  # noqa: BLE001
        return [Item("✗", "FC 연결", f"{address} — {type(exc).__name__}: {exc}")]
    out = [Item("✓", "FC 연결", address)]
    tel = await v.telemetry()
    for _ in range(int(wait_s * 10)):          # GPS 시각과 fix 가 들어올 시간을 준다
        tel = await v.telemetry()
        if tel.clock_offset_s is not None and tel.gps_fix != "NO_GPS":
            break
        await asyncio.sleep(0.1)
    fix_mark = "✓" if tel.gps_fix == "RTK_FIXED" else ("!" if tel.gps_fix == "RTK_FLOAT" else "✗")
    out.append(Item(fix_mark, "GPS fix", f"{tel.gps_fix} · 위성 {tel.satellites}개"
                    + ("" if fix_mark == "✓" else " — 기본 설정은 RTK Fixed 가 아니면 시작을 거절한다")))
    if tel.clock_offset_s is None:
        out.append(Item("!", "시계 오차", "FC 가 아직 GPS 시각을 안 줬다 — 패스 시각은 이 컴퓨터 시계 기준이 된다"))
    else:
        ok = abs(tel.clock_offset_s) <= MAX_CLOCK_OFFSET_S
        out.append(Item("✓" if ok else "✗", "시계 오차",
                        f"이 컴퓨터 − FC(GPS) = {tel.clock_offset_s:+.3f} s"
                        + ("" if ok else f" (허용 ±{MAX_CLOCK_OFFSET_S} s) — 시계를 맞춘다: sudo date -s @<GPS시각> 또는 chrony")))
    out.append(Item("✓", "비행 상태", f"mode {tel.flight_mode} · armed {tel.armed} · in_air {tel.in_air}"))
    hgt = await v.get_param_int("EKF2_HGT_REF")
    names = {0: "기압계", 1: "GNSS", 2: "거리센서", 3: "비전"}
    if hgt is None:
        out.append(Item("!", "높이 기준", "EKF2_HGT_REF 를 못 읽었다"))
    else:
        out.append(Item("✓" if hgt == 1 else "!", "높이 기준",
                        f"EKF2_HGT_REF={hgt} ({names.get(hgt, '?')})"
                        + ("" if hgt == 1 else " — RTK 를 쓰면 1(GNSS) 을 검토한다. 기압계는 몇 분 사이 0.5~1 m 흔들린다")))
    await v.close()
    return out


def check_mqtt(host: str, port: int) -> list[Item]:
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sar-pass-check")
    try:
        client.connect(host, port, keepalive=5)
        client.disconnect()
        return [Item("✓", "MQTT 브로커", f"{host}:{port}")]
    except Exception as exc:  # noqa: BLE001
        return [Item("✗", "MQTT 브로커", f"{host}:{port} — {exc}")]


async def run_checks(cap: Path, connect: str | None, mqtt_addr: str | None, service: str,
                     ack: Path | None = None) -> list[Item]:
    items = check_cap(cap) + check_ack(ack) + check_clock() + check_service(service)
    if mqtt_addr:
        host, _, port = mqtt_addr.partition(":")
        items += check_mqtt(host, int(port or 1883))
    if connect:
        items += await check_fc(connect)
    return items


def report(items: list[Item]) -> int:
    width = max(len(i.what) for i in items)
    for i in items:
        print(f" {i.mark}  {i.what.ljust(width)}  {i.detail}")
    blocked = sum(i.mark == "✗" for i in items)
    print(f"\n{'막힘 ' + str(blocked) + '건 — 해결 후 다시 점검' if blocked else '시작해도 된다 (주의 항목은 확인할 것)'}")
    return 1 if blocked else 0
