"""실제 무선 신호 세기(RSSI)를 읽어 정규화 링크 품질로 옮기는 provider.

implements: AI-N-03, AI-C-04, AI-C-05, AI-B-10
tests: tests/test_rssi_link_quality.py

RSSI라는 이름이 나와도 되는 유일한 자리
---------------------------------------
AI-N-03: "링크 품질 지표의 종류와 측정 방식은 고정하지 않고 공통 인터페이스로
조회하며 특정 무선 규격이나 측정값이 항상 존재한다고 가정해서는 안 된다."
그래서 `ondevice/link_handover.py`와 `ondevice/zone_handover.py`에는 RSSI도
dBm도 없다. 그 이름들은 여기, provider 구현 안에서만 산다. 상위 판단은
`LinkSample.quality`(1.0 최상, 0.0 사용 불가)만 보고, 그 숫자가 RSSI에서
왔는지 손실률에서 왔는지는 `source` 문자열로만 남는다.

같은 이유로 이 모듈은 `providers/link_probe.py`와 **경쟁하지 않는다**. 저쪽은
왕복 시간·손실률로, 이쪽은 신호 세기로 같은 정규화 축을 만든다. 둘 다 있으면
서로 다른 축을 재는 것이고(신호는 강한데 혼잡해서 느린 링크가 실제로 있다),
둘 중 없는 쪽은 그냥 없는 것이지 0이 아니다.

무엇을 실제로 읽는가 (2026-09-18 실측 기준)
--------------------------------------------
대상 하드웨어(Raspberry Pi 5, pi6·pi2)에는 `iw`도 `iwconfig`도 `wpa_cli`도
설치돼 있지 않고 sudo도 없다. 실제로 있는 것은 두 가지였다.

1. `/proc/net/wireless` — 커널이 직접 내놓는 인터페이스별 link/level/noise.
   추가 설치가 필요 없고 권한도 필요 없다. `level`이 dBm이다.
2. `nmcli -t -f IN-USE,SSID,BSSID,SIGNAL,FREQ dev wifi list` — 붙어 있는
   AP의 BSSID와 0~100 신호 백분율. BSSID가 있어야 "어느 AP인가"를 피어로
   식별할 수 있으므로 구역 매핑의 입력이 된다.

그래서 파서를 두 개 두고 각각 `source` 이름을 다르게 남긴다. 어느 쪽도 없는
장비에서는 `sample()`이 `None`을 돌려준다 — "링크가 나쁘다"가 아니라 "모른다"이며,
호출자는 `ZoneHandoverPolicy.observe_unknown()`으로 그것을 그대로 센다(AI-C-05).

환산식은 잠정이다
-----------------
`RssiQualityMapping`의 두 기준점(`excellent_dbm`, `floor_dbm`)은 코드가 아니라
데이터다. 현재 기본값은 일반적인 2.4/5GHz 실내 경험치이고 **검증된 값이 아니다**.
확정하려면 같은 조건에서 실제 원격 기능의 성공률과 맞춰봐야 하며(AI-B-01의
재측정 규칙), 그때까지 이 값이 어디서 왔는지는 `source` 문자열이 드러낸다.
dBm→품질이 선형이라는 것도 근사다. RSSI는 로그 척도라 거리에 대해서는 이미
압축돼 있고, 실제 처리율은 계단형으로 떨어진다 — 그래서 이 환산은 "얼마나
빠른가"가 아니라 "원격에 기대도 되는가"의 순서 관계만 보존하면 된다.

거리 환산도 여기에 있다 (dBm 이 사는 자리)
-----------------------------------------
`LogDistancePathLoss` 는 배포 프로파일(`profiles/domains.json` 의 `rf.<kind>`)이
선언한 계수로 **dBm ↔ m** 를 환산한다. 계수는 코드에 없고 전부 데이터이며,
모르는 모델 이름은 조용히 기본값으로 떨어지지 않고 거부된다.

이 환산이 상위 모듈이 아니라 provider 쪽에 있는 이유는 위와 같다 — dBm 과 경로
손실 지수는 무선 기술의 어휘이고, 그 이름이 나와도 되는 자리는 여기다(AI-N-03).
`perception/rssi_localization.py` 는 이 모델을 **받아 쓰기만** 하고 dBm 을 직접
파싱하지 않는다. 같은 식의 복사본이 `tools/fms_console/handover.py::RfModel` 에도
있고(그쪽이 구역 핸드오버 입력을 만든다) 두 구현이 갈라지지 않도록 시험이
프로파일이 적어 둔 `radius_m` 과 양쪽을 함께 고정한다.

그림자 손실(shadowing)은 계수가 아니라 **분산**이다
--------------------------------------------------
log-distance 식은 평균만 말한다. 실제 RSSI 는 다중경로·차폐로 같은 자리에서도
수 dB 씩 흔들리고, 그 흔들림은 거리로 환산될 때 **곱셈 오차**가 된다
(`distance_bounds_for`). 그래서 σ 없이 거리 하나만 내면 그 숫자는 측량값처럼
읽히지만 실제로는 ±수십 %다. σ 도 프로파일 데이터이며, 선언돼 있지 않으면
기본값을 쓰되 `shadowing_basis` 가 **그것이 실측이 아니라는 사실**을 들고 다닌다.

구역 매핑도 데이터다 (절대 준수 원칙 #3)
-----------------------------------------
BSSID→`zone_id`는 배포 데이터(`peer_zones`)로 주입된다. 이 파일에는 구역 이름도
도메인 분기도 없고, 모르는 BSSID의 구역은 `None`으로 남는다 — 모르는 구역으로는
넘어가지 않는다는 규칙이 `zone_handover.py`에 있기 때문에 조용한 추측을 하지
않는 편이 안전하다.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from mission_runtime.ondevice.link_handover import LinkSample
from mission_runtime.ondevice.zone_handover import PeerObservation

#: `LinkProfile.source` / `LinkSample` 출처에 남는 방법 이름. 자유 문자열이다.
SOURCE_PROC_NET_WIRELESS = "rssi_proc_net_wireless"
SOURCE_NM_SCAN = "rssi_network_manager_scan"
SOURCE_TRACE_REPLAY = "rssi_trace_replay"

REASON_SOURCE_UNAVAILABLE = "rssi_source_unavailable"
REASON_INTERFACE_NOT_FOUND = "rssi_interface_not_found"
REASON_LEVEL_MISSING = "rssi_level_missing"
REASON_UNPARSEABLE = "rssi_output_unparseable"

RSSI_PROVIDER_REASONS: tuple[str, ...] = (
    REASON_SOURCE_UNAVAILABLE,
    REASON_INTERFACE_NOT_FOUND,
    REASON_LEVEL_MISSING,
    REASON_UNPARSEABLE,
)

#: 프로파일이 선언할 수 있는 RF 모델 이름. 모르는 모델은 **추측하지 않고 거부한다** —
#: 조용히 log-distance 로 떨어지면 다른 모델을 선언한 현장이 틀린 거리를 받는다.
LOG_DISTANCE = "log_distance"

#: 경로손실 기준거리(m). 이보다 가까운 거리는 모델의 적용 범위 밖이라 눌러 쓴다.
REFERENCE_DISTANCE_M = 1.0

#: 그림자 손실 1σ(dB)의 **미실측 기본값**. 실내 log-normal shadowing 의 통상 범위
#: (4~8dB) 가운데 값이고 **이 현장에서 잰 값이 아니다**. 그래서 이 값을 쓴 추정은
#: `shadowing_basis` 로 그 사실을 들고 다닌다 — 미측정을 실측처럼 쓰지 않는다.
DEFAULT_SHADOWING_SIGMA_DB = 6.0

#: `shadowing_basis` 값 어휘. 자유 문자열이고 벤더 enum 이 아니다.
SIGMA_BASIS_DECLARED = "declared_in_profile"
SIGMA_BASIS_UNMEASURED = "unmeasured_default"

#: 프로파일 `rf.<kind>` 가 σ 를 적을 때 쓰는 키. 지금 `profiles/domains.json` 에는
#: **없다** — 그래서 현재 모든 추정이 `unmeasured_default` 로 나온다.
SHADOWING_SIGMA_KEY = "shadowing_sigma_db"


class RadioModelError(ValueError):
    """RF 선언을 그대로 쓸 수 없다. 조용히 기본 계수를 끼워 넣지 않는다."""


@dataclass(frozen=True)
class LogDistancePathLoss:
    """한 RF 종류의 경로손실 모델. **계수는 전부 프로파일 데이터다**.

        level_dbm(d) = tx_eirp_dbm - reference_loss_db_at_1m
                       - 10 * path_loss_exponent * log10(d)      (d >= 1m)

    `declared_radius_m` 은 프로파일이 적어 둔 **유도값**이라 계산에 쓰지 않는다 —
    비교용으로만 들고 있고, 시험이 "역산한 값 == 적어 둔 반경" 을 고정한다. 반경을
    상수로 베껴 쓰면 계수를 고치는 날 둘이 갈라진다.
    """

    kind: str
    tx_eirp_dbm: float
    reference_loss_db_at_1m: float
    path_loss_exponent: float
    shadowing_sigma_db: float = DEFAULT_SHADOWING_SIGMA_DB
    shadowing_basis: str = SIGMA_BASIS_UNMEASURED
    #: 주파수대. 표시 라벨이고 분기 조건이 아니다(자유 문자열).
    band: str = ""
    declared_radius_m: Mapping[str, float] = field(default_factory=dict)
    thresholds_dbm: Mapping[str, float] = field(default_factory=dict)
    model: str = LOG_DISTANCE

    def __post_init__(self) -> None:
        if self.path_loss_exponent <= 0:
            raise RadioModelError(
                f"rf {self.kind!r} needs a positive path loss exponent, "
                f"got {self.path_loss_exponent}")
        if self.shadowing_sigma_db <= 0:
            raise RadioModelError(
                f"rf {self.kind!r} needs a positive shadowing sigma, "
                f"got {self.shadowing_sigma_db}")

    @classmethod
    def from_profile(cls, kind: str, raw: Mapping) -> "LogDistancePathLoss":
        """`profiles/domains.json` 의 `rf.<kind>` 한 덩이를 모델로 옮긴다."""
        model = raw.get("model")
        if model != LOG_DISTANCE:
            raise RadioModelError(f"unsupported rf model for {kind!r}: {model!r}")
        for key in ("tx_eirp_dbm", "reference_loss_db_at_1m", "path_loss_exponent"):
            if key not in raw:
                raise RadioModelError(f"rf model {kind!r} missing {key!r}")
        declared_sigma = raw.get(SHADOWING_SIGMA_KEY)
        return cls(
            kind=kind,
            tx_eirp_dbm=float(raw["tx_eirp_dbm"]),
            reference_loss_db_at_1m=float(raw["reference_loss_db_at_1m"]),
            path_loss_exponent=float(raw["path_loss_exponent"]),
            shadowing_sigma_db=(DEFAULT_SHADOWING_SIGMA_DB if declared_sigma is None
                                else float(declared_sigma)),
            shadowing_basis=(SIGMA_BASIS_UNMEASURED if declared_sigma is None
                             else SIGMA_BASIS_DECLARED),
            band=str(raw.get("band", "")),
            declared_radius_m={k: float(v) for k, v in (raw.get("radius_m") or {}).items()},
            thresholds_dbm={k: float(v)
                            for k, v in (raw.get("thresholds_dbm") or {}).items()},
            model=model,
        )

    # --- 정방향 ------------------------------------------------------------

    def level_dbm(self, distance_m: float) -> float:
        """거리 → 평균 신호 세기. 흔들림(σ)은 **이 값에 들어 있지 않다**."""
        distance = max(float(distance_m), REFERENCE_DISTANCE_M)
        loss = (self.reference_loss_db_at_1m
                + 10.0 * self.path_loss_exponent * math.log10(distance))
        return self.tx_eirp_dbm - loss

    # --- 역방향 ------------------------------------------------------------

    def distance_m_for(self, level_dbm: float) -> float:
        """신호 세기 → 거리. **점 추정이고 그것만 쓰면 안 된다**.

        아래 `distance_bounds_for` 가 같은 측정의 구간이며, 그 폭이 이 점 하나를
        얼마나 믿을 수 없는지 말해 준다.
        """
        budget = self.tx_eirp_dbm - self.reference_loss_db_at_1m - float(level_dbm)
        return 10.0 ** (budget / (10.0 * self.path_loss_exponent))

    def distance_bounds_for(
        self, level_dbm: float, *, k_sigma: float = 1.0
    ) -> tuple[float, float]:
        """σ 를 거리 구간으로 옮긴다. dB 의 덧셈 오차는 거리의 **곱셈 오차**다.

            d_true = d_hat * 10 ** (X / (10 n)),   X ~ N(0, σ²)

        그래서 구간은 `d_hat` 을 중심으로 대칭이 아니라 비율로 벌어진다. n=3.5,
        σ=6dB, k=1 이면 ±48% 다 — 20m 추정이 13.5~29.7m 라는 뜻이고, 이것이
        "점 하나로 내면 안 된다" 의 수치적 근거다.
        """
        if k_sigma < 0:
            raise ValueError("k_sigma must not be negative")
        centre = self.distance_m_for(level_dbm)
        spread = 10.0 ** (k_sigma * self.shadowing_sigma_db
                          / (10.0 * self.path_loss_exponent))
        return centre / spread, centre * spread

    def radius_for_threshold(self, name: str) -> float | None:
        """선언된 문턱 이름(`excellent`·`handover`·`floor`)의 반경. 없으면 `None`."""
        level = self.thresholds_dbm.get(name)
        if level is None:
            return None
        return self.distance_m_for(level)


#: `/proc/net/wireless` 한 줄: "wlan0: 0000   65.  -45.  -256  0 0 0 1 0  0"
_PROC_LINE = re.compile(
    r"^\s*(?P<iface>[\w.-]+):\s*(?P<status>[0-9a-fA-F]+)\s+"
    r"(?P<link>-?[\d.]+)\.?\s+(?P<level>-?[\d.]+)\.?\s+(?P<noise>-?[\d.]+)\.?"
)


@dataclass(frozen=True)
class RssiReading:
    """신호 세기 관측 1건. 해석 없이 잰 값만 담는다.

    `level_dbm`이 `None`인 것과 값이 아주 낮은 것은 다른 상태다. 전자는
    "재지 못했다"이고 후자는 "재봤더니 나쁘다"이며, 전자를 후자로 접으면
    AI-N-03이 금지하는 "측정값이 항상 존재한다는 가정"이 조용히 들어온다.
    """

    peer_id: str | None
    source: str
    at: float
    level_dbm: float | None = None
    #: `/proc/net/wireless`의 link 칼럼(드라이버마다 척도가 다르다). 해석하지
    #: 않고 원본을 남긴다 — 환산은 dBm으로만 한다.
    link_quality_raw: float | None = None
    noise_dbm: float | None = None
    #: NetworkManager가 주는 0~100 백분율(있을 때만).
    signal_percent: float | None = None
    interface: str | None = None
    ssid: str | None = None
    zone_id: str | None = None
    reason: str | None = None

    @property
    def measured(self) -> bool:
        return self.reason is None and (
            self.level_dbm is not None or self.signal_percent is not None
        )

    def as_dict(self) -> dict:
        return {
            "peer_id": self.peer_id,
            "source": self.source,
            "at": self.at,
            "level_dbm": self.level_dbm,
            "link_quality_raw": self.link_quality_raw,
            "noise_dbm": self.noise_dbm,
            "signal_percent": self.signal_percent,
            "interface": self.interface,
            "ssid": self.ssid,
            "zone_id": self.zone_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RssiQualityMapping:
    """dBm(또는 0~100 백분율) → 정규화 품질. 계수는 전부 데이터다.

    `excellent_dbm` 이상이면 1.0, `floor_dbm` 이하면 0.0, 사이는 선형이다.
    기본값은 실내 경험치이며 검증된 수치가 아니다(모듈 docstring 참고).

    `link_handover.LinkTransitionPolicy.floor`(기본 0.25)와의 관계가 실제로
    중요한 부분이다: 기본값 조합에서 품질 0.25는 대략 -75dBm에 해당하고,
    그 아래에서 원격 의존을 내린다는 뜻이 된다. 한쪽 숫자만 바꾸면 "표본은
    괜찮다는데 판정은 바닥"이 되므로 둘은 같이 움직여야 한다.
    """

    excellent_dbm: float = -45.0
    floor_dbm: float = -85.0

    def __post_init__(self) -> None:
        if self.excellent_dbm <= self.floor_dbm:
            raise ValueError("excellent_dbm must be greater than floor_dbm")

    def quality(self, reading: RssiReading) -> float | None:
        if reading.reason is not None:
            return None
        if reading.level_dbm is not None:
            span = self.excellent_dbm - self.floor_dbm
            return _clamp((reading.level_dbm - self.floor_dbm) / span)
        if reading.signal_percent is not None:
            # 백분율은 이미 드라이버가 환산한 값이다. 다시 dBm으로 되돌리려
            # 하면 드라이버마다 다른 역함수를 가정하게 되므로 그대로 쓴다.
            return _clamp(reading.signal_percent / 100.0)
        return None

    def quality_of_dbm(self, level_dbm: float) -> float:
        span = self.excellent_dbm - self.floor_dbm
        return _clamp((level_dbm - self.floor_dbm) / span)


DEFAULT_MAPPING = RssiQualityMapping()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# --- 파서 --------------------------------------------------------------------


def parse_proc_net_wireless(
    text: str, *, at: float | None = None, source: str = SOURCE_PROC_NET_WIRELESS
) -> tuple[RssiReading, ...]:
    """`/proc/net/wireless` 전체 → 인터페이스별 관측.

    하드웨어 없이 시험할 수 있도록 읽기와 파싱을 분리해 둔다(=실제 장비에서
    받은 문자열을 그대로 고정 입력으로 쓸 수 있다).
    """
    at = at if at is not None else time.time()
    readings: list[RssiReading] = []
    for line in text.splitlines():
        match = _PROC_LINE.match(line)
        if not match:
            continue
        readings.append(
            RssiReading(
                peer_id=None,
                source=source,
                at=at,
                level_dbm=float(match.group("level")),
                link_quality_raw=float(match.group("link")),
                noise_dbm=float(match.group("noise")),
                interface=match.group("iface"),
            )
        )
    return tuple(readings)


def _unescape_bssid(raw: str) -> str:
    return raw.replace("\\:", ":")


def parse_nm_scan(
    text: str, *, at: float | None = None, peer_zones: Mapping[str, str] | None = None
) -> tuple[RssiReading, ...]:
    """`nmcli -t -f IN-USE,SSID,BSSID,SIGNAL,FREQ dev wifi list` → AP별 관측.

    `-t`(terse) 출력은 ':' 구분이고 BSSID 안의 ':'는 '\\:'로 이스케이프된다.
    필드 수가 다른 줄은 조용히 버리지 않고 건너뛴 사실이 개수 차이로 드러난다.
    """
    at = at if at is not None else time.time()
    peer_zones = peer_zones or {}
    readings: list[RssiReading] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = re.split(r"(?<!\\):", line)
        if len(fields) < 4:
            continue
        in_use, ssid, bssid_raw, signal = fields[0], fields[1], fields[2], fields[3]
        bssid = _unescape_bssid(bssid_raw)
        try:
            percent = float(signal)
        except ValueError:
            continue
        readings.append(
            RssiReading(
                peer_id=bssid,
                source=SOURCE_NM_SCAN,
                at=at,
                signal_percent=percent,
                ssid=ssid or None,
                zone_id=peer_zones.get(bssid),
                # 연결 중인 AP 표시는 `IN-USE`의 '*'다. 값 자체를 해석하지 않고
                # 호출자가 쓸 수 있게 남긴다.
                interface="*" if in_use.strip() == "*" else None,
            )
        )
    return tuple(readings)


# --- 읽기 경로 ----------------------------------------------------------------


def local_text_reader(path: str | Path) -> Callable[[], str | None]:
    """같은 장치 안에서 파일을 읽는다. 없으면 `None`(=모른다)."""

    def read() -> str | None:
        try:
            return Path(path).read_text()
        except OSError:
            return None

    return read


def runner_text_reader(runner, command: str) -> Callable[[], str | None]:
    """제어 경로 1왕복으로 원격 장치의 출력을 읽는다.

    `runner`는 `run(command)`를 가진 무엇이든 된다(`providers/ondevice_ssh.py`의
    SSH runner, 지역 셸 runner, 시험용 더블). 여기서 ssh를 이름으로 부르지 않는
    이유는 AI-C-04다 — 이 모듈이 알아야 하는 것은 "명령 하나를 실행해 표준출력을
    돌려주는 무언가"까지다.
    """

    def read() -> str | None:
        try:
            proc = runner.run(command)
        except Exception:
            return None
        if getattr(proc, "returncode", 1) != 0:
            return None
        return getattr(proc, "stdout", None)

    return read


# --- provider ----------------------------------------------------------------


class RssiLinkQualityProvider:
    """`LinkQualityProvider`(ondevice/link_handover.py)의 RSSI 구현.

    `sample()`은 측정에 실패하면 `None`을 돌려준다. 계약이 그렇게 돼 있는
    이유는 AI-C-05다: 못 잰 것을 0.0으로 채우면 추세·복귀 판정이 오염되고
    "측정 불가"와 "링크 단절"을 영원히 구분할 수 없게 된다.
    """

    def __init__(
        self,
        *,
        wireless_reader: Callable[[], str | None] | None = None,
        scan_reader: Callable[[], str | None] | None = None,
        interface: str = "wlan0",
        peer_zones: Mapping[str, str] | None = None,
        mapping: RssiQualityMapping = DEFAULT_MAPPING,
        clock: Callable[[], float] = time.time,
        #: 붙어 있는 AP를 스캔으로 식별할 수 없을 때 쓸 이름(선택).
        fallback_peer_id: str | None = None,
    ) -> None:
        self._wireless_reader = wireless_reader
        self._scan_reader = scan_reader
        self._interface = interface
        self._peer_zones = dict(peer_zones or {})
        self._mapping = mapping
        self._clock = clock
        self._fallback_peer_id = fallback_peer_id
        self._last_reading: RssiReading | None = None
        self._last_reason: str | None = None
        self._last_scan: tuple[RssiReading, ...] = ()

    # --- 조회 ---------------------------------------------------------------

    @property
    def last_reading(self) -> RssiReading | None:
        return self._last_reading

    @property
    def last_reason(self) -> str | None:
        """마지막 측정이 실패한 사유. 성공했으면 `None`."""
        return self._last_reason

    @property
    def mapping(self) -> RssiQualityMapping:
        return self._mapping

    # --- 측정 ---------------------------------------------------------------

    def read(self) -> RssiReading | None:
        """원시 관측 1건. 실패하면 사유가 붙은 `RssiReading`을 돌려준다."""
        at = self._clock()
        connected = self._connected_ap()
        if self._wireless_reader is not None:
            text = self._wireless_reader()
            if text is None:
                self._last_reason = REASON_SOURCE_UNAVAILABLE
            else:
                readings = parse_proc_net_wireless(text, at=at)
                match = next(
                    (r for r in readings if r.interface == self._interface), None
                )
                if match is None:
                    self._last_reason = (
                        REASON_INTERFACE_NOT_FOUND if readings else REASON_UNPARSEABLE
                    )
                elif match.level_dbm is None:
                    self._last_reason = REASON_LEVEL_MISSING
                else:
                    peer_id = (
                        connected.peer_id if connected else self._fallback_peer_id
                    )
                    reading = RssiReading(
                        peer_id=peer_id,
                        source=SOURCE_PROC_NET_WIRELESS,
                        at=at,
                        level_dbm=match.level_dbm,
                        link_quality_raw=match.link_quality_raw,
                        noise_dbm=match.noise_dbm,
                        signal_percent=connected.signal_percent if connected else None,
                        interface=match.interface,
                        ssid=connected.ssid if connected else None,
                        zone_id=self._peer_zones.get(peer_id) if peer_id else None,
                    )
                    self._last_reading = reading
                    self._last_reason = None
                    return reading
        if connected is not None:
            # dBm을 못 읽었어도 스캔 백분율이 있으면 그것으로라도 답한다.
            self._last_reading = connected
            self._last_reason = None
            return connected
        reason = self._last_reason or REASON_SOURCE_UNAVAILABLE
        self._last_reason = reason
        return RssiReading(
            peer_id=self._fallback_peer_id, source=SOURCE_PROC_NET_WIRELESS,
            at=at, reason=reason,
        )

    def sample(self) -> LinkSample | None:
        """정규화 표본. 재지 못했으면 `None`(="모른다", ≠"나쁘다")."""
        reading = self.read()
        if reading is None or not reading.measured:
            return None
        quality = self._mapping.quality(reading)
        if quality is None:
            return None
        return LinkSample(
            at=reading.at, quality=quality, peer_id=reading.peer_id,
            zone_id=reading.zone_id,
        )

    def candidates(self) -> list[tuple[str, float]]:
        """`LinkQualityProvider` 계약의 후보 목록 — (peer_id, 정규화 품질)."""
        return [(p.peer_id, p.quality) for p in self.peer_observations()]

    def peer_observations(self) -> tuple[PeerObservation, ...]:
        """구역 정보를 붙인 후보. `ZoneHandoverPolicy.observe()`의 입력이다.

        구역을 모르는 AP는 `zone_id=None`으로 남는다 — 상위 정책은 모르는
        구역으로 넘어가지 않으므로, 여기서 추측해 채우면 그 보호가 사라진다.
        """
        scan = self._scan()
        observations: list[PeerObservation] = []
        for reading in scan:
            if reading.peer_id is None:
                continue
            quality = self._mapping.quality(reading)
            if quality is None:
                continue
            observations.append(
                PeerObservation(
                    peer_id=reading.peer_id,
                    quality=quality,
                    zone_id=self._peer_zones.get(reading.peer_id),
                )
            )
        return tuple(observations)

    # --- 보조 ---------------------------------------------------------------

    def _scan(self) -> tuple[RssiReading, ...]:
        if self._scan_reader is None:
            return ()
        text = self._scan_reader()
        if text is None:
            self._last_scan = ()
            return ()
        self._last_scan = parse_nm_scan(
            text, at=self._clock(), peer_zones=self._peer_zones
        )
        return self._last_scan

    def _connected_ap(self) -> RssiReading | None:
        for reading in self._scan():
            if reading.interface == "*":
                return reading
        return None


# --- 오프라인 검증용 재생 ------------------------------------------------------


@dataclass(frozen=True)
class TraceStep:
    """재생 1스텝: 현재 붙어 있는 링크의 표본 + 그 시점에 보이던 후보들."""

    sample: LinkSample
    peers: tuple[PeerObservation, ...]


class RssiTraceReplay:
    """기록된 RSSI 시계열을 그대로 재생한다(하드웨어 없이 검증용).

    `datasets/link_quality/robot_rssi_zenodo_1219249`(zenodo:1219249)는 실제
    이동 로봇이 주행하면서 동시에 잰 세 개의 링크 RSSI(`rssi_dbm_link0..2`)와
    주행거리를 담고 있다.

    **정직하게 적어 둘 것**: 이 데이터셋에는 "구역 전환" 레이블이 없다. 세
    링크를 서로 다른 후보 피어로 두고(원하면 서로 다른 구역에 배정해) 재생하는
    것은 실제 신호 변동 위에서 선택·이력 로직을 돌려 보기 위한 **모델링**이지,
    데이터셋이 구역 핸드오버를 담고 있다는 주장이 아니다. 여기서 얻는 것은
    "히스테리시스가 실제 신호 흔들림에서 전환 횟수를 얼마나 줄이는가"라는
    비교값이고, 그 비교는 같은 입력에 대해 공정하다.
    """

    def __init__(
        self,
        rows: Sequence[Mapping[str, str]],
        *,
        link_columns: Sequence[str] = ("rssi_dbm_link0", "rssi_dbm_link1", "rssi_dbm_link2"),
        peer_ids: Sequence[str] | None = None,
        peer_zones: Mapping[str, str] | None = None,
        mapping: RssiQualityMapping = DEFAULT_MAPPING,
        time_column: str = "t_rel_s",
    ) -> None:
        self._rows = list(rows)
        self._link_columns = tuple(link_columns)
        self._peer_ids = tuple(peer_ids or link_columns)
        self._peer_zones = dict(peer_zones or {})
        self._mapping = mapping
        self._time_column = time_column

    @classmethod
    def from_csv(cls, path: str | Path, **kwargs) -> "RssiTraceReplay":
        import csv

        with open(path, newline="") as handle:
            rows = list(csv.DictReader(handle))
        return cls(rows, **kwargs)

    def __len__(self) -> int:
        return len(self._rows)

    def steps(self, attached_to: str | None = None):
        """`attached_to`(피어 id)에 붙어 있다고 보고 재생한다.

        `None`이면 첫 스텝에서 가장 좋은 피어에 붙은 상태로 시작한다. 붙어 있는
        피어를 바꾸는 것은 호출자의 몫이다 — 이 재생기는 정책을 흉내 내지 않는다.
        """
        current = attached_to
        for row in self._rows:
            try:
                at = float(row[self._time_column])
            except (KeyError, ValueError):
                continue
            peers: list[PeerObservation] = []
            for column, peer_id in zip(self._link_columns, self._peer_ids):
                raw = row.get(column)
                if raw in (None, ""):
                    continue
                try:
                    level = float(raw)
                except ValueError:
                    continue
                peers.append(
                    PeerObservation(
                        peer_id=peer_id,
                        quality=self._mapping.quality_of_dbm(level),
                        zone_id=self._peer_zones.get(peer_id),
                    )
                )
            if not peers:
                continue
            if current is None:
                current = max(peers, key=lambda p: p.quality).peer_id
            attached = next((p for p in peers if p.peer_id == current), None)
            if attached is None:
                attached = max(peers, key=lambda p: p.quality)
                current = attached.peer_id
            yield TraceStep(
                sample=LinkSample(
                    at=at, quality=attached.quality, peer_id=attached.peer_id,
                    zone_id=attached.zone_id,
                ),
                peers=tuple(peers),
            )

    def follow(self, policy, *, attached_to: str | None = None):
        """정책을 재생에 물려 돌린다. 전환 요청을 그대로 수락하는 소비자 역할.

        실제 배포에서 전환을 수행하는 것은 네트워크 provider이고(AI-C-19), 여기서는
        검증을 위해 "요청하면 항상 성공한다"는 가장 단순한 provider를 흉내 낸다.
        그보다 나쁜 provider(전환 실패)는 별도 시험의 몫이다.
        """
        current = attached_to
        decisions = []
        for step in self.steps(attached_to=current):
            sample = step.sample
            if current is not None and sample.peer_id != current:
                sample = LinkSample(sample.at, sample.quality, current, sample.zone_id)
                match = next((p for p in step.peers if p.peer_id == current), None)
                if match is not None:
                    sample = LinkSample(sample.at, match.quality, current, match.zone_id)
            decision = policy.observe(sample, list(step.peers))
            decisions.append(decision)
            if decision.switch_to_zone is not None:
                policy.confirm_zone(decision.switch_to_zone, at=sample.at)
                current = decision.switch_to_zone_peer or current
            elif decision.switch_to_peer is not None:
                current = decision.switch_to_peer
        return decisions
