"""수레 시험 — 드론 없이 레이더 · RTK 를 수레(카트)에 싣고 사람이 밀며 선을 지난다. 비행 명령은 한 번도 안 보낸다.

    python -m sar_pass cart --start 37.5665,126.9780 --heading 45 --length 30 --passes 3 \\
        --connect udpin://0.0.0.0:14540 --mqtt 127.0.0.1:1883 --log-dir sar_logs

왜: 영상이 안 나왔을 때 원인이 레이더 · 시각 · 레버암 · 처리 중 어디인지 가르려면, 비행(추락 위험 · 배터리 · 허가)
없이 같은 파이프라인을 여러 번 돌려 봐야 한다. 리플렉터 옆 30~60 m 를 걸어서 민다.

FC(+GPS/RTK)는 수레에 실어 켜 둔다(시동 안 함). 위치 · 자세 · 시각은 비행 때와 같은 MAVSDK 연결로 받는다.

동작
  1) 선 시작점보다 뒤(진행 거리 < 0)에서 기다린다 — 「준비」
  2) 선 방향으로 움직여 시작점을 지나면(횡 ±cross_tol 안, 속도 ≥ 0.3 m/s) CAP_ON — 「캡처」
  3) 끝점을 지나거나 선에서 크게 벗어나면 CAP_ON 을 지운다. 다시 시작점 뒤로 돌아가면 다음 패스
  기록 · 판정 · 화면 · 데이터 서버 · 영상은 비행과 **같은 형식**이다(flight_<시각>/passNN_*.csv|json).
  판정은 걷는 속도에 맞게 느슨하다: 속도 ±1 m/s · 고도 ±1 m · 기수 ±15° · 진행 방향 ±20°.
"""

from __future__ import annotations

import collections
import logging

from .mission import CONTROL_HZ, SPEED_AVG_S, PassRecord, SarMission, SarPlan

log = logging.getLogger("sar_pass.cart")

CART_DEFAULTS = dict(speed_mps=1.2, alt_m=0.0, q_speed_mps=1.0, q_alt_m=1.0, q_heading_deg=15.0, q_course_deg=20.0,
                     q_cross_m=1.0, require_rtk=True, extra_passes=0)


def cart_plan(start_lat: float, start_lon: float, end_lat: float, end_lon: float, passes: int = 3, **over) -> SarPlan:
    kw = {**CART_DEFAULTS, **over}
    return SarPlan(start_lat=start_lat, start_lon=start_lon, end_lat=end_lat, end_lon=end_lon, passes=passes, **kw)


class CartSession(SarMission):
    """비행 임무와 같은 기록 · 판정 · 상태 보고를 쓰고, 움직임만 사람이 한다."""

    def __init__(self, *a, cross_tol_m: float = 3.0, min_speed_mps: float = 0.3, **kw) -> None:
        super().__init__(*a, **kw)
        self.cross_tol_m = cross_tol_m
        self.min_speed_mps = min_speed_mps

    async def run(self) -> str:
        outcome = "aborted"
        try:
            tel = await self._tel()
            self.clock_offset_s = tel.clock_offset_s
            if self.cap.ack_path is None:
                self.warnings.append("레이더 확인(CAP_ACK) 경로가 없다 — 실제 기록 시각은 모르고 요청 시각만 남는다")
            attempt = 0
            while attempt < self.plan.passes:
                attempt += 1
                await self._walk_pass(attempt)
            outcome = "done"
            self.message = f"수레 패스 {len(self.records)}회 · 유효 {self.valid_passes}"
        except Exception as exc:  # noqa: BLE001 — 중단(Ctrl-C) · 연결 끊김
            from .mission import MissionAborted
            if not isinstance(exc, MissionAborted):
                self.error = f"{type(exc).__name__}: {exc}"
                log.exception("수레 시험 예외")
                outcome = "failed"
        finally:
            self.cap.off(f"finally · {outcome}")
            self._close_open_record("중단으로 캡처 종료")
            self.state = outcome
            self._publish(force=True)
        return outcome

    async def _walk_pass(self, n: int) -> PassRecord:
        plan, line = self.plan, self.plan.line
        length = line.length_m
        record = PassRecord(pass_no=n)
        self.records.append(record)
        self.pass_no = n
        rows: list[dict] = []
        speeds: collections.deque = collections.deque()
        armed = False                     # 시작점 뒤로 한 번 가야 캡처를 걸 수 있다
        self._set_state("transit")
        log.info("수레 패스 %d: 시작점 뒤로 가서 선 방향으로 미세요", n)
        step = 1.0 / CONTROL_HZ
        while True:
            self._check_abort()
            tel = await self._tel()
            now = self.v.clock.now()
            along, cross = line.along_cross(tel.lat, tel.lon)
            gs = tel.ground_speed
            speeds.append((now, gs))
            while speeds and now - speeds[0][0] > SPEED_AVG_S:
                speeds.popleft()
            gs_avg = sum(x for _t, x in speeds) / len(speeds)
            ack = self.cap.read_ack()
            if self.state == "transit":
                if along < -0.5:
                    if not armed:
                        log.info("수레 패스 %d: 준비 — 시작점을 지나면 캡처", n)
                    armed = True
                elif armed and 0.0 <= along < length and abs(cross) <= self.cross_tol_m and gs_avg >= self.min_speed_mps:
                    self.cap.on(max_on_s=max(60.0, 4 * length / max(self.min_speed_mps, 0.1)))
                    record.captured, record.start_unix = True, now
                    record.fc_start_unix = self._fc_time(now)
                    record.along_at_start_m = round(along, 2)
                    self._log_pass_event(record, "start")
                    self._set_state("capture")
            elif self.state == "capture":
                record._speed_sum += gs
                record._speed_n += 1
                if ack is not None and record.ack_start_unix is None and ack >= (record.start_unix or 0) - 0.5:
                    record.ack_start_unix = ack
                    record.ack_on_latency_s = round(ack - (record.start_unix or ack), 3)
                    self._on_latencies.append(max(0.0, record.ack_on_latency_s))
                if along >= length or along < -1.0 or abs(cross) > 2 * self.cross_tol_m:
                    self.cap.off(f"수레 패스 {n} 끝")
                    record.end_unix = now
                    record.fc_end_unix = self._fc_time(now)
                    record.mean_speed_mps = round(record._speed_sum / max(1, record._speed_n), 3)
                    if along < length:
                        record.note = "끝점 전에 선을 벗어났다"
                    self._log_pass_event(record, "end")
                    self._set_state("decel")
                    end_at = now
            elif self.state == "decel":
                if record.ack_start_unix is not None and record.ack_end_unix is None and ack is None:
                    record.ack_end_unix = now
                    record.ack_off_latency_s = round(now - end_at, 3)
                    self._off_latencies.append(record.ack_off_latency_s)
                if self.cap.ack_path is None or record.ack_end_unix is not None or now - end_at > 3.0:
                    break
            row = self._row(tel, now, along, cross, gs, gs_avg, self.state, ack)
            row["ref_along_m"], row["ref_speed"] = None, None
            rows.append(row)
            self._last_tel = tel
            self._publish(tel=tel, along=along, cross=cross)
            await self.v.clock.sleep(step)
        # 판정 · 기록은 비행과 같은 함수 (느슨한 기준은 plan 에)
        self._judge(record, rows)
        self._write_traj(record, rows)
        self._publish(force=True)
        return record
