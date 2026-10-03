"""파이 시계를 FC 의 GPS 시각(MAVLink SYSTEM_TIME)에 맞춘다 — 핫스팟에 인터넷이 없어 NTP 가 안 될 때.

  python -m sar_pass timesync                 # 차이만 잰다
  sudo python -m sar_pass timesync --apply    # 맞춘다 (date -s)

MAVLink 가 몇~수십 ms 걸려 오므로 정밀도는 그 정도다. 레이더 샘플과 ms 이하로 맞추려면 GPS PPS 가 필요하다.
NTP 가 켜져 있으면 나중에 다시 덮어쓸 수 있다 — 인터넷이 없는 현장이면 `sudo timedatectl set-ntp false`.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import subprocess
import time

from .mavsdk_vehicle import MavsdkVehicle


async def measure(connect: str, samples: int = 10) -> float | None:
    v = MavsdkVehicle(connect)
    await v.connect(timeout_s=20)
    offsets: list[float] = []
    for _ in range(samples * 10):
        tel = await v.telemetry()
        if tel.clock_offset_s is not None:
            offsets.append(tel.clock_offset_s)
            if len(offsets) >= samples:
                break
        await asyncio.sleep(0.2)
    await v.close()
    return statistics.median(offsets) if offsets else None


async def timesync(connect: str, apply: bool) -> int:
    off = await measure(connect)
    if off is None:
        print("FC 가 GPS 시각을 아직 안 준다 (GPS fix 대기) — 맞출 수 없다")
        return 1
    print(f"이 컴퓨터 − FC(GPS) = {off:+.3f} s")
    if not apply:
        print("맞추려면 --apply (root 필요)")
        return 0
    if os.geteuid() != 0:
        print("root 가 아니다 — sudo 로 다시 실행한다")
        return 1
    target = time.time() - off
    subprocess.run(["date", "-s", f"@{target:.3f}"], check=True)
    print(f"맞췄다 → {time.strftime('%Y-%m-%d %H:%M:%S')}")
    return 0
