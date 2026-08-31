"""
피지컬팀 mk2 — Unitree Go1 제어기 링크 (HW-R-01)
==================================================
`ControllerLink` 의 Go1 구현. **읽기 전용이다** — 로봇에 명령을 보내지 않는다.

## 왜 SDK(UDP)를 쓰지 않는가

Go1 의 고수준 SDK 경로(`192.168.123.161:8082`)는 **요청/응답 구조**라 가만히 듣기만
해서는 아무것도 오지 않는다. 상태를 받으려면 `HighCmd` 를 보내야 하는데, 그 순간
sport mode 에서 **제어권을 가져온다.** 서 있는 로봇이 힘이 빠져 주저앉을 수 있다.

대신 Go1 은 자체 MQTT 브로커(`192.168.123.161:1883`)로 텔레메트리를 **이미 발행하고
있다.** 구독만 하면 되고, 구독은 로봇을 움직일 수 없다. 그래서 이 경로를 쓴다.

| 토픽 | 내용 | 주기 |
|---|---|---|
| `robot/state` | 84바이트 — 몸통 자세·12관절·높이·속도 | 12.5 Hz |
| `bms/state` | 34바이트 — SDK `BmsState` 구조체 그대로 | 0.5 Hz |
| `usys/version/*` | 각 노드 버전 (retained) | — |

## 페이로드 레이아웃 (pi7 에서 역공학, 2026-08-31)

`bms/state` 는 SDK `comm.h` 의 `BmsState` 와 정확히 일치했다 — 값이 전부 물리적으로
말이 됐다(SOC 43%, 방전 4.93A, 124사이클, BQ 32/31°C).

`robot/state` 는 공개 규격이 없어 **관측으로 추정**했다. 확신도를 구분해 둔다.

| 오프셋 | 형식 | 해석 | 확신도 |
|---|---|---|---|
| 0~5 | int16 ×3 | 몸통 roll·pitch·yaw (도) | **높음** — 서 있을 때 (0,0,-25), 물리적으로 타당 |
| 6~29 | int16 ×12 | 12관절 각도 (도), 4다리 × (hip,thigh,calf) | **높음** — 서 있을 때 (0,46,-92)×4, Go1 기립 자세와 일치 |
| 30~51 | int16 ×11 | 미상 (발 접지력 추정) | 낮음 |
| 52~59 | float32 ×2 | 위치 x·y (오도메트리 추정) | **낮음** — 정지 중이라 구분 불가 |
| 60~67 | float32 ×2 | 몸통 높이 (m) | **높음** — 0.295, Go1 기본 0.28과 일치 |
| 68~75 | float32 ×2 | 속도 x·y (m/s) | 중간 — 정지 중 ±0.001 |
| 76~83 | float32 ×2 | 미상 / 각속도 | 중간 |

**낮음·중간 항목은 로봇이 실제로 움직여야 확정된다.** 앱이나 리모컨으로 주행시키면서
이 스트림을 관찰하면 명령을 보내지 않고도 확정할 수 있다(`bench/go1_probe.py`).

## 명령(HW-R-06)은 아직 없다

`send_command()` 는 의도적으로 거부한다. 명령 경로는 로봇이 **엎드린 상태 또는 거치대에서**,
사람이 지켜보는 가운데 별도로 붙인다.
"""
import struct
import threading
import time

import paho.mqtt.client as mqtt

from common import config
from robot.controller_link import ControllerLink, RobotState

# --- robot/state 레이아웃 상수 (위 표 참조) ---
# ⚠ 전부 **바이트 오프셋**이다. int16 인덱스와 헷갈리면 값이 조용히 깨진다
# (실제로 JOINTS 를 인덱스 3 으로 뒀다가 관절이 쓰레기값으로 나왔다).
BODY_RPY = 0            # int16 ×3, 도   — 바이트 0,2,4
JOINTS = 6              # int16 ×12, 도  — 바이트 6~29
F_POS = 52              # float32 ×2 (추정)
F_HEIGHT = 60           # float32, m
F_VEL = 68              # float32 ×2, m/s
F_TAIL = 76             # float32 ×2
STATE_LEN = 84
BMS_LEN = 34


class Go1Link(ControllerLink):
    """Go1 내부 MQTT 를 구독해 상태만 읽는다. 명령은 보내지 않는다."""

    def __init__(self, host=None, port=1883):
        self.host = host or config.GO1_MQTT_HOST
        self.port = port
        self._lock = threading.Lock()
        self._state = None          # 최신 robot/state 원본
        self._bms = None            # 최신 bms/state 원본
        self._last_state_at = 0.0
        self._last_bms_at = 0.0
        self._versions = {}
        self._connected = False

        kw = {"callback_api_version": mqtt.CallbackAPIVersion.VERSION2,
              "client_id": f"hw-go1-{int(time.time())}"}
        self._c = mqtt.Client(**kw)
        self._c.on_connect = self._on_connect
        self._c.on_disconnect = self._on_disconnect
        self._c.on_message = self._on_message
        self._c.reconnect_delay_set(min_delay=1, max_delay=config.RECONNECT_MAX_DELAY)
        self._c.connect_async(self.host, self.port, keepalive=20)
        self._c.loop_start()

    # ---------- MQTT ----------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[Go1] 접속 실패 {reason_code}")
            return
        self._connected = True
        print(f"[Go1] 내부 MQTT 접속 — {self.host}:{self.port}")
        # 구독만 한다. 발행하지 않는다 — 로봇을 움직일 수 있는 경로를 열지 않는다.
        for t in ("robot/state", "bms/state", "usys/version/#"):
            client.subscribe(t, qos=0)

    def _on_disconnect(self, client, userdata, flags=None, reason_code=None, properties=None):
        self._connected = False
        print(f"[Go1] 내부 MQTT 단절 (rc={getattr(reason_code, 'value', reason_code)})")

    def _on_message(self, client, userdata, msg):
        now = time.time()
        with self._lock:
            if msg.topic == "robot/state" and len(msg.payload) >= STATE_LEN:
                self._state, self._last_state_at = msg.payload, now
            elif msg.topic == "bms/state" and len(msg.payload) >= BMS_LEN:
                self._bms, self._last_bms_at = msg.payload, now
            elif msg.topic.startswith("usys/version/"):
                self._versions[msg.topic.rsplit("/", 1)[-1]] = \
                    msg.payload.decode("utf-8", "replace")[:200]

    # ---------- ControllerLink 구현 ----------
    def read_state(self) -> RobotState:
        with self._lock:
            st, bms = self._state, self._bms
            st_age = time.time() - self._last_state_at if self._state else None

        if st is None:
            # 아직 한 건도 못 받았다. 값을 지어내지 않는다 — 모르는 것은 모른다고 낸다.
            raise RuntimeError("go1_state_unavailable")

        rpy = struct.unpack_from("<3h", st, BODY_RPY)          # 도
        height = struct.unpack_from("<f", st, F_HEIGHT)[0]     # m
        pos = struct.unpack_from("<2f", st, F_POS)             # 추정
        vel = struct.unpack_from("<2f", st, F_VEL)             # m/s

        battery = self._bms_soc(bms)
        speed = (vel[0] ** 2 + vel[1] ** 2) ** 0.5

        # mode: Go1 의 동작 모드를 이 스트림에서 확정하지 못했다. 관측 가능한 것으로
        # 대신한다 — 스트림이 최근에 왔고 높이가 기립 범위면 서 있는 것으로 본다.
        mode = self._infer_mode(st_age, height, speed)

        return RobotState(
            battery_pct=battery if battery is not None else 0.0,
            x=round(pos[0], 3), y=round(pos[1], 3),
            heading_deg=float(rpy[2]),
            speed_mps=round(speed, 3),
            mode=mode,
        )

    @staticmethod
    def _bms_soc(bms):
        """SDK BmsState 의 SOC(0~100%). 레이아웃은 comm.h 와 일치함을 실측 확인했다."""
        if bms is None or len(bms) < 4:
            return None
        return float(bms[3])

    @staticmethod
    def _infer_mode(age, height, speed):
        """관측으로 추정하는 동작 모드. **Go1 의 실제 mode 필드가 아니다.**
        확정하려면 `controller/current_action` 해독이나 SDK HighState 가 필요하다."""
        if age is None or age > config.GO1_STALE_S:
            return "unknown"
        if height < 0.15:
            return "idle"            # 엎드림
        return "mission" if speed > 0.05 else "idle"

    def send_command(self, action, params):
        """HW-R-06. **의도적으로 막아 둔다.**

        Go1 에 명령을 보내려면 SDK 의 UDP 경로로 HighCmd 를 실어야 하는데, 그 순간
        sport mode 에서 제어권을 가져와 서 있던 로봇이 주저앉을 수 있다. 명령 경로는
        로봇이 엎드린 상태에서 사람이 지켜보는 가운데 따로 붙인다."""
        raise NotImplementedError(
            "go1_command_not_enabled — 명령 경로는 안전 조건 확립 후 별도로 활성화한다")

    def link_health(self):
        with self._lock:
            age = time.time() - self._last_state_at if self._state else None
            bms_age = time.time() - self._last_bms_at if self._bms else None
        if not self._connected or age is None:
            return "fault"
        if age > config.GO1_STALE_S:
            return "fault"           # 붙어는 있는데 값이 안 온다
        if bms_age is None or bms_age > config.GO1_BMS_STALE_S:
            return "degraded"        # 자세는 오는데 배터리가 안 온다
        return "ok"

    # ---------- 진단 ----------
    def diagnostics(self):
        with self._lock:
            st, bms = self._state, self._bms
            age = time.time() - self._last_state_at if self._state else None
            versions = dict(self._versions)
        d = {"connected": self._connected, "host": self.host,
             "state_age_s": round(age, 2) if age is not None else None,
             "sport_mode_version": None}
        raspi = versions.get("raspi", "")
        for part in raspi.split(";"):
            if part.startswith("sportMode:"):
                d["sport_mode_version"] = part.split(":", 1)[1]
        if st:
            d["joints_deg"] = list(struct.unpack_from("<12h", st, JOINTS))
            d["body_height_m"] = round(struct.unpack_from("<f", st, F_HEIGHT)[0], 3)
        if bms:
            cur = struct.unpack_from("<i", bms, 4)[0]
            d["battery"] = {"soc_pct": bms[3], "current_ma": cur,
                            "cycles": struct.unpack_from("<H", bms, 8)[0]}
        return d
