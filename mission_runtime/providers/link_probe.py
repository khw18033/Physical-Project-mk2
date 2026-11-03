"""등록된 장치의 링크를 실제로 재서 `LinkProfile`로 환산하는 provider.

implements: AI-N-03, AI-O-01, AI-C-04, AI-B-04

AI-N-03은 "링크 품질 지표의 종류와 측정 방식은 고정하지 않고 공통 인터페이스로
조회하며 특정 무선 규격이나 측정값이 항상 존재한다고 가정해서는 안 된다"고
요구한다. 그래서 이 모듈의 계약은 두 겹이다.

1. `LinkMeasurement` — **잰 것 그대로**. 보낸 수, 받은 수, 평균 RTT, RTT 편차.
   해석이 하나도 섞여 있지 않고, 재지 못했으면 필드가 `None`으로 남는다.
2. `LinkQualityMapping` — 그 원시값을 `LinkProfile`의 정규화 quality/stability로
   옮기는 **환산표**. 계수가 코드가 아니라 데이터라서 현장별로 갈아끼울 수 있고,
   환산 후에도 원시값은 `LinkMeasurement`로 남아 있어 "0.89라는 숫자가 어디서
   나왔는가"를 되짚을 수 있다.

환산식을 굳이 분리한 이유는 2026-09-18 pi2 실측이다. 같은 장치를 다른 시각에
재면 (125ms / 33% 손실) → (11ms / 0% 손실)로 바뀌는데, **평균만 보면 좋은
링크**가 된다. 실제로는 mdev가 14.9ms(평균 11.2ms보다 크다)라 순간적으로는
75ms까지 튄다. 그래서 손실·평균은 `quality`로, 흔들림은 `stability`로 서로 다른
축에 넣는다 — `LinkProfile` docstring이 말하는 "평균은 좋은데 자주 떨어지는
링크"가 바로 이 경우다.

이 환산식은 검증된 지표가 아니라 **잠정 매핑**이다. 확정하려면 동일 조건에서
실제 원격 기능의 성공률과 비교해야 하고(AI-B-01의 재측정 규칙), 그때까지는
`source` 문자열에 방법 이름을 남겨 "이 값이 무엇으로 만들어졌는지"를 드러낸다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from mission_runtime.contracts.profile import LinkProfile

#: `LinkProfile.source`에 들어가는 방법 이름. 자유 문자열이며 enum이 아니다.
METHOD_ICMP = "icmp_ping"
METHOD_COMMAND_ROUNDTRIP = "command_roundtrip"

REASON_PROBE_UNAVAILABLE = "probe_tool_unavailable"
REASON_PROBE_FAILED = "probe_failed"
REASON_PROBE_TIMEOUT = "probe_timeout"

_RTT_LINE = re.compile(
    r"=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)(?:/([0-9.]+))?\s*ms"
)
_LOSS_LINE = re.compile(r"(\d+)\s+packets transmitted,\s*(\d+)\s*(?:packets\s+)?received")
_SAMPLE_LINE = re.compile(r"time[=<]([0-9.]+)\s*ms")


@dataclass(frozen=True)
class LinkMeasurement:
    """한 번의 링크 관측. 해석 없이 잰 값만 담는다.

    `received == 0`과 `rtt_avg_ms is None`은 다른 상태다. 전자는 "재봤고 전부
    실패했다", 후자는 "재지 못했다"이며 후자를 0으로 접으면 AI-N-03이 금지하는
    "측정값이 항상 존재한다는 가정"이 조용히 들어온다.
    """

    address: str
    method: str
    sent: int = 0
    received: int = 0
    rtt_min_ms: float | None = None
    rtt_avg_ms: float | None = None
    rtt_max_ms: float | None = None
    rtt_mdev_ms: float | None = None
    #: 표본별 RTT. `stability`가 "floor 위에 머문 비율"을 세려면 평균이 아니라
    #: 표본이 필요하다 — 평균만으로는 잠깐 튄 구간이 보이지 않는다.
    rtt_samples_ms: tuple[float, ...] = ()
    reason: str | None = None

    @property
    def measured(self) -> bool:
        return self.sent > 0 and self.reason is None

    @property
    def loss_fraction(self) -> float | None:
        if self.sent <= 0:
            return None
        return (self.sent - self.received) / self.sent

    def as_dict(self) -> dict:
        return {
            "address": self.address,
            "method": self.method,
            "sent": self.sent,
            "received": self.received,
            "loss_fraction": self.loss_fraction,
            "rtt_min_ms": self.rtt_min_ms,
            "rtt_avg_ms": self.rtt_avg_ms,
            "rtt_max_ms": self.rtt_max_ms,
            "rtt_mdev_ms": self.rtt_mdev_ms,
            "rtt_samples_ms": list(self.rtt_samples_ms),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LinkQualityMapping:
    """원시 측정 → 정규화 quality/stability. 계수는 전부 데이터다.

    * `quality   = (1 - 손실률) x min(1, 기준RTT / 평균RTT)`
      기준 RTT까지는 감점이 없고 그보다 느려지면 반비례로 떨어진다. 손실은
      곱으로 들어가 100% 손실이면 무조건 0이다. 기준 RTT 50ms의 근거는
      "링크가 언제부터 병목이 되는가"다 — 현재 말단 목표 주기 5Hz(200ms)에서
      왕복 50ms는 한 주기의 1/4이고, 그보다 빠른 링크는 더 빨라져도 처리
      주기를 바꾸지 못하므로 감점할 이유가 없다. 이 값을 10ms로 잡아 보니
      같은 LAN을 연속으로 재도 평균이 7ms와 27ms 사이를 오가며 quality가
      1.00과 0.37을 왕복했다 — 실제로 달라진 것이 없는데 배치가 흔들리는
      전형적인 과민 설정이다(AI-N-03: 순간 변동으로 실행 전환이 반복되지
      않아야 한다).
    * `stability = (개별 표본 품질이 floor를 넘은 횟수) / (보낸 횟수)`
      `LinkProfile.stability`가 문서에 적어둔 의미("floor 위에 머문 시간 비율")를
      그대로 계산한다. 유실된 패킷은 floor 아래로 센다. 표본별 RTT를 읽지
      못했으면 `None` — 흔들림을 재지 못한 것을 "흔들리지 않았다"로 바꾸지
      않는다.

    두 값이 서로 다른 축이라는 것이 요점이다. 하나로 합치면 "평균 11ms / 0%
    손실인데 순간 75ms까지 튀는" 링크를 좋은 링크로 읽게 된다 — 실제로 pi2가
    그랬고, 평균만 보면 통과하지만 표본별로 보면 floor 아래로 내려간 구간이
    남는다.
    """

    reference_rtt_ms: float = 50.0
    #: `LinkPostureThresholds.floor`와 같은 숫자여야 한다 — 한쪽만 바꾸면
    #: "표본은 floor 위였다는데 판정은 floor 아래"가 된다.
    floor: float = 0.25

    def quality(self, m: LinkMeasurement) -> float | None:
        loss = m.loss_fraction
        if loss is None:
            return None
        if m.received == 0:
            return 0.0
        if m.rtt_avg_ms is None:
            # 도달은 했지만 RTT를 못 읽었다 — 손실만으로 환산하고, 없는 항목을
            # 있는 것처럼 채우지 않는다.
            return _clamp(1.0 - loss)
        latency_term = min(1.0, self.reference_rtt_ms / max(m.rtt_avg_ms, 1e-6))
        return _clamp((1.0 - loss) * latency_term)

    def sample_quality(self, rtt_ms: float) -> float:
        """표본 하나의 품질. 전체 품질과 같은 환산을 한 표본에 적용한다."""
        return _clamp(min(1.0, self.reference_rtt_ms / max(rtt_ms, 1e-6)))

    def stability(self, m: LinkMeasurement) -> float | None:
        if m.received == 0 and m.sent > 0:
            return 0.0
        if not m.rtt_samples_ms or m.sent <= 0:
            return None
        above = sum(1 for rtt in m.rtt_samples_ms if self.sample_quality(rtt) > self.floor)
        return _clamp(above / m.sent)


DEFAULT_MAPPING = LinkQualityMapping()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def probe_icmp(
    address: str,
    *,
    count: int = 20,
    interval_s: float = 0.2,
    timeout_s: float = 30.0,
    ping: str = "ping",
) -> LinkMeasurement:
    """ICMP로 한 번 잰다. 도구가 없거나 실패해도 예외를 던지지 않는다.

    측정 실패는 정상 경로다(AI-C-05) — 호출자는 `reason`을 보고 "링크가
    나쁘다"가 아니라 "모른다"로 처리해야 하며, 모르는 링크는
    `runtime/residency.py`가 보수적으로 LOCAL_ONLY로 다룬다.
    """
    if shutil.which(ping) is None:
        return LinkMeasurement(address, METHOD_ICMP, reason=REASON_PROBE_UNAVAILABLE)
    argv = [ping, "-c", str(count), "-i", str(interval_s), "-W", "2", address]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return LinkMeasurement(address, METHOD_ICMP, sent=count, reason=REASON_PROBE_TIMEOUT)
    except OSError:
        return LinkMeasurement(address, METHOD_ICMP, reason=REASON_PROBE_UNAVAILABLE)
    return parse_ping_output(address, proc.stdout or "", returncode=proc.returncode)


def parse_ping_output(address: str, output: str, *, returncode: int = 0) -> LinkMeasurement:
    """`ping` 요약 두 줄만 읽는다. 하드웨어 없이도 시험할 수 있게 분리했다."""
    loss = _LOSS_LINE.search(output)
    sent = int(loss.group(1)) if loss else 0
    received = int(loss.group(2)) if loss else 0
    rtt = _RTT_LINE.search(output)
    values = [float(g) for g in rtt.groups() if g is not None] if rtt else []
    samples = tuple(float(v) for v in _SAMPLE_LINE.findall(output))
    reason = None
    if sent == 0:
        reason = REASON_PROBE_FAILED if returncode != 0 else REASON_PROBE_FAILED
    return LinkMeasurement(
        address=address,
        method=METHOD_ICMP,
        sent=sent,
        received=received,
        rtt_min_ms=values[0] if len(values) > 0 else None,
        rtt_avg_ms=values[1] if len(values) > 1 else None,
        rtt_max_ms=values[2] if len(values) > 2 else None,
        rtt_mdev_ms=values[3] if len(values) > 3 else None,
        rtt_samples_ms=samples,
        reason=reason,
    )


def probe_command_roundtrip(
    runner,
    *,
    count: int = 5,
    command: str = "true",
) -> LinkMeasurement:
    """ICMP가 막힌 곳을 위한 대체 측정 — 제어 경로 자체의 왕복 시간.

    `runner`는 `SshRunner`처럼 `run(command)`를 가진 무엇이든 된다. 여기서
    ssh를 이름으로 부르지 않는 이유는 AI-C-04다: 측정은 "제어 경로 1왕복"이라는
    의미만 알면 되고 그 경로가 무엇인지는 provider의 몫이다.
    """
    import time

    samples: list[float] = []
    received = 0
    for _ in range(max(1, count)):
        start = time.perf_counter()
        try:
            proc = runner.run(command)
        except Exception:
            continue
        if getattr(proc, "returncode", 1) == 0:
            received += 1
            samples.append((time.perf_counter() - start) * 1000.0)
    if not samples:
        return LinkMeasurement(
            getattr(getattr(runner, "device", None), "address", "?"),
            METHOD_COMMAND_ROUNDTRIP, sent=count, received=0,
        )
    avg = sum(samples) / len(samples)
    mdev = sum(abs(s - avg) for s in samples) / len(samples)
    return LinkMeasurement(
        address=getattr(getattr(runner, "device", None), "address", "?"),
        method=METHOD_COMMAND_ROUNDTRIP,
        sent=count,
        received=received,
        rtt_min_ms=min(samples),
        rtt_avg_ms=avg,
        rtt_max_ms=max(samples),
        rtt_mdev_ms=mdev,
        rtt_samples_ms=tuple(samples),
    )


def link_profile_from(
    measurement: LinkMeasurement,
    mapping: LinkQualityMapping = DEFAULT_MAPPING,
) -> LinkProfile | None:
    """측정 → `LinkProfile`. 재지 못했으면 `None`을 돌려준다.

    `None`은 "링크가 나쁘다"가 아니라 "모른다"이며, 호출자는 이 경우 기존 링크
    선언을 그대로 두어야 한다. 없는 측정을 0으로 채워 넣으면 `assess_link`가
    측정 실패와 실제 단절을 구분할 수 없게 된다.
    """
    if not measurement.measured:
        return None
    return LinkProfile(
        source=f"measured:{measurement.method}",
        quality=mapping.quality(measurement),
        stability=mapping.stability(measurement),
        samples=measurement.sent,
    )
