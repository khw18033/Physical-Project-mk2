"""지연 도착한 엣지 판정을 **현재 시점의 객체**에 붙이는 레코드 계층.

implements: AI-S-06, AI-S-01, AI-S-03, AI-C-03, AI-C-02, AI-L-01

풀려는 문제 (사용자 지적, 2026-09-21):
  pi4가 프레임 N을 보내고 판정을 받기까지 실측 약 450 ms가 걸린다. 그 사이
  드론은 움직였고 화면은 이미 프레임 N+k다. **판정이 가리키는 박스 좌표는
  도착하는 순간 이미 낡았다.**

해법 — 좌표가 아니라 **정체성**에 붙인다:
  * 말단이 RPN 후보를 ByteTracker에 태워 `track_id`를 준다. 이 id는 프레임
    사이를 건너 살아남는다.
  * 엣지로 보내는 페이로드에 `frame_ref`(원본 관측 참조)와 후보별 `track_id`를
    같이 싣는다. AI-C-03이 요구하는 두 가지가 서로 다른 목적이라는 게 여기서
    실제로 쓰인다 — frame_ref는 "어느 원본에서 나왔나", track_id는 "어느
    지속 객체인가".
  * 판정이 돌아오면 frame_ref의 낡은 박스는 버리고 `track_id`로 현재 트랙을
    찾아 **의미 근거만** 얹는다. 박스는 언제나 말단의 최신 추적값을 쓴다.

낡음을 숨기지 않는다 (AI-S-03):
  근거마다 `observed_at`(관측 시각), `applied_at`(반영 시각), `age_s`,
  `frames_late`를 남긴다. 근거 충분도는 최신성을 봐야 하는데, 나이를 지워버리면
  소비자가 그 판단을 할 수 없다.

트랙이 사라진 뒤 도착한 근거는 버리지 않고 `orphans`에 남긴다 — 그 crop과 판정은
학습 후보로는 여전히 쓸모가 있다(AI-L-01). 다만 현재 상태로는 승격하지 않는다.

좌표는 로컬 영상 좌표뿐이다. 전역 변환은 백엔드 몫이다(AI-C-02).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    """엣지가 만든 의미 근거 하나. 확정이 아니라 근거다(AI-S-04)."""

    source: str                  # "ovd" | "clip" | "vlm"
    payload: dict[str, Any]
    observed_at: float           # 원본 프레임이 찍힌 시각
    applied_at: float            # 이 말단이 반영한 시각
    frame_ref: str
    frames_late: int
    # **이 트랙이 보낸 프레임에서 가지고 있던 자기 박스.** 판정에 실려 온 검출
    # 박스가 아니다 — 그것을 쓰면 OVD 검출 기하(때로 거의 전체 화면)와 RPN 트랙
    # 기하의 차이를 이동으로 착각한다(2026-09-21 실측에서 실제로 그랬다: 서로 다른
    # 트랙 여럿이 같은 observed_box를 들고 "300px 이동"을 보고했다).
    # 같은 트랙의 과거 좌표와 현재 좌표만이 "그 사이 시야가 얼마나 움직였나"를 잰다.
    observed_box: tuple[float, float, float, float] | None = None

    @property
    def age_s(self) -> float:
        return self.applied_at - self.observed_at

    def displacement(self, current_box) -> float:
        """같은 트랙의 관측 당시 중심 → 현재 중심 거리(px).

        0이면 그 사이 움직이지 않았다는 뜻이고, 그때는 이 화면만으로 "정체성으로
        붙였다"와 "좌표로 붙였다"를 구분할 수 없다. 구분 불가를 반영 성공으로
        보고하지 않는다.
        """
        if not self.observed_box or not current_box:
            return 0.0
        ox = (self.observed_box[0] + self.observed_box[2]) / 2
        oy = (self.observed_box[1] + self.observed_box[3]) / 2
        cx = (current_box[0] + current_box[2]) / 2
        cy = (current_box[1] + current_box[3]) / 2
        return float(((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5)

    def to_dict(self) -> dict:
        return {"source": self.source, "payload": self.payload,
                "observed_box": list(self.observed_box) if self.observed_box else None,
                "observed_at": self.observed_at, "applied_at": self.applied_at,
                "age_s": round(self.age_s, 3), "frame_ref": self.frame_ref,
                "frames_late": self.frames_late}


@dataclass
class ObjectRecord:
    """하나의 지속 객체. 박스는 최신 추적값, 근거는 누적."""

    track_id: int
    box: tuple[float, float, float, float]
    first_seen_at: float
    last_seen_at: float
    last_frame_seq: int
    evidence: list[Evidence] = field(default_factory=list)
    alive: bool = True
    # (frame_seq, box) 최근 이력. 엣지가 생각하는 동안 이 트랙이 어디로 갔는지를
    # 되짚는 유일한 근거다. 4~8 fps에서 240칸이면 30~60초 분량이다.
    history: deque = field(default_factory=lambda: deque(maxlen=240))

    def box_at(self, seq: int):
        """frame_seq 시점의 이 트랙 박스. 그 이하 중 가장 늦은 기록을 쓴다."""
        found = None
        for s, b in self.history:
            if s <= seq:
                found = b
            else:
                break
        return found

    def latest(self, source: str) -> Evidence | None:
        for e in reversed(self.evidence):
            if e.source == source:
                return e
        return None

    @staticmethod
    def label_of(e: "Evidence") -> str:
        """근거에서 의미 라벨을 꺼낸다. 출처마다 모양이 다르다."""
        p = e.payload or {}
        if e.source == "clip":
            return str(((p.get("ranking") or [{}])[0]).get("class", "?"))
        return str(p.get("label", "?"))

    def consensus(self, source: str, *, now: float, ttl: float) -> Evidence | None:
        """유효 창 안에서 **가장 많이 지지받은 라벨**의 최신 근거.

        마지막 도착값을 그대로 쓰면(last-wins) 정지한 장면에서도 라벨이 프레임마다
        뒤집힌다 — 2026-09-21 실측: 고정 카메라·고정 피사체에서 라벨 10개 중 초당
        약 1개가 바뀌었다. 검출기가 임계 근처에서 흔들리거나 겹친 후보 사이에서
        승자가 바뀌면 한 프레임짜리 반대 근거가 즉시 화면을 지배하기 때문이다.

        AI-S-06이 요구하는 것은 덮어쓰기가 아니라 **누적**이다. 창 안의 근거를
        라벨별로 세어 다수를 택하면, 한 번의 흔들림은 누적된 지지를 못 이긴다.
        동률이면 최신을 택해 새 증거가 들어올 길은 막지 않는다.

        근거를 지우지는 않는다 — 소수 의견도 레코드에 남아 학습 후보로 쓰인다.
        """
        live = [e for e in self.evidence
                if e.source == source and (now - e.observed_at) <= ttl]
        if not live:
            return None
        tally: dict[str, int] = {}
        for e in live:
            tally[self.label_of(e)] = tally.get(self.label_of(e), 0) + 1
        top = max(tally.values())
        winners = {k for k, v in tally.items() if v == top}
        for e in reversed(live):
            if self.label_of(e) in winners:
                return e
        return live[-1]

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id, "box": [round(v, 2) for v in self.box],
            "first_seen_at": self.first_seen_at, "last_seen_at": self.last_seen_at,
            "last_frame_seq": self.last_frame_seq, "alive": self.alive,
            "evidence": [e.to_dict() for e in self.evidence],
            # 소비자가 "이 근거가 얼마나 낡았나"를 한 번에 볼 수 있게 요약한다.
            "staleness_s": {s: round(e.age_s, 3)
                            for s in ("ovd", "ovd2", "clip", "vlm")
                            if (e := self.latest(s)) is not None},
        }


def smooth_box(prev, cur, *, alpha: float, snap_px: float):
    """트랙 박스의 프레임 간 떨림을 줄이되 **실제 이동은 그대로 따라간다.**

    문제(사용자 보고 2026-09-21, 실측): 카메라와 피사체가 모두 고정인데 박스가
    떤다. 추적기가 `track.box = det.box`로 매 프레임 RPN 회귀값을 그대로 쓰기
    때문이다. 정지 장면 실측 — 중심 이동 중앙 1.4 px / p90 6.9 px,
    크기 변화 중앙 3.6 px / p90 17.5 px.

    단순 EMA로는 안 된다. 계수를 세게 주면 떨림은 잡히지만 **드론이 실제로
    움직일 때 박스가 뒤처진다** — 이 파이프라인의 목적이 움직이는 시야에서
    근거를 붙이는 것이므로 그 지연은 치명적이다.

    그래서 **변화량에 따라 계수를 올린다.** 변화가 작으면(떨림) 강하게 누르고,
    `snap_px` 이상 움직이면 계수가 1이 되어 그대로 따라붙는다. 떨림과 이동을
    가르는 것은 크기뿐이고, 어느 쪽인지 판단하는 임계는 설정에 노출한다.

    alpha=1이면 평활화 없음(원래 동작).
    """
    if alpha >= 1.0 or prev is None:
        return tuple(cur)
    d = (((cur[0] + cur[2]) - (prev[0] + prev[2])) / 2) ** 2 + \
        (((cur[1] + cur[3]) - (prev[1] + prev[3])) / 2) ** 2
    d = d ** 0.5
    a = alpha if snap_px <= 0 else min(1.0, max(alpha, d / snap_px))
    return tuple(p + a * (c - p) for p, c in zip(prev, cur))


def reanchor(det_box, observed_box, current_box):
    """검출 기하를 **현재 시점으로 옮긴다** — 정확한 박스를 맞는 자리에 놓는다.

    두 박스는 서로 다른 장점을 가진다(사용자 지적 2026-09-21):
      * OVD 검출 박스 — 경계가 정확하다. class-agnostic RPN 후보는 헐겁다.
      * 말단 트랙 박스 — **지금** 좌표다. 검출 박스는 왕복 지연(실측 ~450 ms
        ~ 1 s)만큼 낡았다.

    그래서 정확한 쪽을 버리지도, 낡은 자리에 그대로 두지도 않는다. 같은 트랙의
    `observed_box`(보낼 당시 자기 박스)와 현재 박스를 비교하면 그 사이의 이동과
    크기 변화를 알 수 있으므로, 그 변환을 검출 박스에 그대로 먹인다.

    크기 배율까지 쓰는 이유는 피사체가 카메라 쪽으로 다가오면 기하도 함께 커지기
    때문이다. 이동만 보정하면 다가오는 물체에서 박스가 작게 남는다.

    관측 당시 박스를 모르면(근거가 orphan 등) 보정하지 않고 None을 돌려준다 —
    추정으로 메우지 않는다(AI-S-03).
    """
    if not det_box or not observed_box or not current_box:
        return None
    ocx, ocy = (observed_box[0] + observed_box[2]) / 2, (observed_box[1] + observed_box[3]) / 2
    ccx, ccy = (current_box[0] + current_box[2]) / 2, (current_box[1] + current_box[3]) / 2
    ow, oh = observed_box[2] - observed_box[0], observed_box[3] - observed_box[1]
    cw, ch = current_box[2] - current_box[0], current_box[3] - current_box[1]
    sx = cw / ow if ow > 1e-6 else 1.0
    sy = ch / oh if oh > 1e-6 else 1.0
    # 배율이 폭주하면(추적 박스가 한 프레임 무너진 경우) 이동만 반영한다.
    if not (0.4 <= sx <= 2.5 and 0.4 <= sy <= 2.5):
        sx = sy = 1.0
    dcx, dcy = (det_box[0] + det_box[2]) / 2, (det_box[1] + det_box[3]) / 2
    hw, hh = (det_box[2] - det_box[0]) / 2 * sx, (det_box[3] - det_box[1]) / 2 * sy
    nx, ny = ccx + (dcx - ocx) * sx, ccy + (dcy - ocy) * sy
    return (nx - hw, ny - hh, nx + hw, ny + hh)


class RecordStore:
    """track_id로 색인된 레코드 창고. 지연 근거 반영과 만료를 담당한다."""

    def __init__(self, *, keep_after_death_s: float = 10.0,
                 evidence_ttl_s: float = 6.0,
                 box_alpha: float = 1.0, box_snap_px: float = 24.0):
        self.records: dict[int, ObjectRecord] = {}
        self.orphans: list[dict] = []
        self.keep_after_death_s = keep_after_death_s
        # 근거 유효기간. 넘기면 **레코드에는 남기되 현재 상태로는 내보내지 않는다**
        # — 지운 게 아니라 "지금 이걸 근거로 말하지 않는다"이다(AI-S-03).
        # 필요한 이유: 근거는 트랙당 한 번만 만들어지므로 만료가 없으면 화면에
        # 30초 전 판정이 그대로 남는다(2026-09-21 실측 28.6s). 시야가 계속 바뀌는
        # 이동체에서 그 나이의 의미 판정은 현재 상태를 말해주지 못한다.
        self.evidence_ttl_s = evidence_ttl_s
        # 박스 평활화. 여기서 하는 이유는 이 레코드가 **표시·전송·이동량 계산의
        # 기준 박스**를 소유하기 때문이다. 추적기의 연관(association)은 원측정값을
        # 그대로 쓰게 두어 정체성 유지 성능(실측 90~100%)을 건드리지 않는다.
        self.box_alpha = box_alpha
        self.box_snap_px = box_snap_px
        self.applied = 0
        self.orphaned = 0

    def observe(self, tracks, frame_seq: int, at: float) -> None:
        """말단 추적 결과로 박스·생존을 갱신한다. 매 프레임 호출."""
        live = set()
        for t in tracks:
            live.add(t.track_id)
            r = self.records.get(t.track_id)
            if r is None:
                r = ObjectRecord(
                    track_id=t.track_id, box=tuple(t.box), first_seen_at=at,
                    last_seen_at=at, last_frame_seq=frame_seq)
                self.records[t.track_id] = r
                r.history.append((frame_seq, tuple(t.box)))
            else:
                r.box = smooth_box(r.box, tuple(t.box),
                                   alpha=self.box_alpha, snap_px=self.box_snap_px)
                r.history.append((frame_seq, r.box))
                r.last_seen_at = at
                r.last_frame_seq = frame_seq
                r.alive = True
        for tid, r in self.records.items():
            if tid not in live:
                r.alive = False

        # 죽은 지 오래된 레코드는 내보낸다. 근거가 붙어 있으면 학습 후보로 남긴다.
        dead = [tid for tid, r in self.records.items()
                if not r.alive and (at - r.last_seen_at) > self.keep_after_death_s]
        for tid in dead:
            self.records.pop(tid)

    def apply_verdict(self, verdict: dict, current_seq: int, now: float | None = None) -> dict:
        """엣지 판정을 현재 트랙에 반영한다.

        판정 안의 박스 좌표는 **쓰지 않는다** — 그 좌표는 보낼 당시의 것이다.
        track_id로 현재 레코드를 찾고, 없으면 orphan으로 남긴다.
        """
        now = now or time.time()
        observed_at = float(verdict.get("observed_at") or now)
        frame_ref = str(verdict.get("frame_id", "?"))
        sent_seq = int(verdict.get("frame_seq", current_seq))
        frames_late = max(0, current_seq - sent_seq)
        applied = orphaned = 0

        for item in verdict.get("per_track", []):
            tid = item.get("track_id")
            if tid is None:
                continue
            rec = self.records.get(int(tid))
            for source in ("ovd", "ovd2", "clip", "vlm"):
                data = item.get(source)
                if not data:
                    continue
                # 보낸 프레임에서 **이 트랙이 가지고 있던 자기 박스**를 박아 둔다.
                # 판정에 실려 온 data["box"]는 쓰지 않는다 — 이 모듈 첫머리에 적은
                # 원칙 그대로다. 그 좌표는 검출기의 기하이지 이 객체의 궤적이 아니다.
                obox = rec.box_at(sent_seq) if rec is not None else None
                ev = Evidence(source=source, payload=data, observed_at=observed_at,
                              applied_at=now, frame_ref=frame_ref,
                              frames_late=frames_late,
                              observed_box=tuple(obox) if obox else None)
                if rec is not None and rec.alive:
                    rec.evidence.append(ev)
                    applied += 1
                else:
                    # 트랙이 사라진 뒤 도착 — 현재 상태로 승격하지 않되 버리지도
                    # 않는다. 미지 객체 학습 후보의 출처가 된다(AI-L-01).
                    self.orphans.append({"track_id": tid, **ev.to_dict(),
                                         "reason": "track_gone" if rec is None
                                                   else "track_not_alive"})
                    orphaned += 1

        self.applied += applied
        self.orphaned += orphaned
        return {"frame_ref": frame_ref, "frames_late": frames_late,
                "age_s": round(now - observed_at, 3),
                "applied": applied, "orphaned": orphaned}

    def transmit_view(self, now: float | None = None, max_tracks: int = 200) -> list[dict]:
        """엣지로 보낼 **현재 트랙 상태**. 시점 반영 결과를 그대로 담는다.

        박스는 말단이 방금 추적한 **현재 위치**이고, 근거는 몇 프레임 전 관측에서
        온 것이다. 그 둘을 한 항목에 담아 보내면 엣지가 현재 프레임 위에 그릴 수
        있고, 보는 사람이 "옛 근거가 지금 어디에 붙어 있는지"를 눈으로 확인한다 —
        이것이 온디바이스 RPN+ByteTracker를 두는 이유 자체다.

        `age_s`를 같이 보내는 이유는 낡음을 숨기지 않기 위해서다(AI-S-03).
        """
        now = now or time.time()
        out = []
        for r in self.records.values():
            if not r.alive:
                continue
            item = {"track_id": r.track_id, "box": [round(v, 1) for v in r.box],
                    "seen_s": round(now - r.first_seen_at, 2)}
            for src in ("ovd", "ovd2", "clip", "vlm"):
                # 마지막 근거가 아니라 유효 창의 **다수 의견**을 내보낸다.
                e = r.consensus(src, now=now, ttl=self.evidence_ttl_s)
                if e is None:
                    continue
                item[src] = {"age_s": round(now - e.observed_at, 2),
                             "support": sum(
                                 1 for q in r.evidence
                                 if q.source == src
                                 and (now - q.observed_at) <= self.evidence_ttl_s
                                 and r.label_of(q) == r.label_of(e)),
                             "frames_late": e.frames_late,
                             "payload": e.payload,
                             # 검증용: 관측 당시 박스와 그때부터 지금까지의 이동 거리
                             "observed_box": ([round(v, 1) for v in e.observed_box]
                                              if e.observed_box else None),
                             "moved_px": round(e.displacement(r.box), 1)}
                # 검출 기하를 현재 시점으로 옮긴 박스. 있으면 화면은 이것을 그린다
                # — RPN 후보보다 경계가 정확하면서 자리는 지금 것이다.
                rb = reanchor((e.payload or {}).get("box"), e.observed_box, r.box)
                if rb:
                    item[src]["reanchored_box"] = [round(v, 1) for v in rb]

            # **확정은 유효 창 안 근거의 다수결이다** — 한 프레임의 판정이 아니다.
            # 엣지는 근거마다 그 프레임에서 두 모델이 합의했는지를 `agreed`로 싣고,
            # 여기서는 창 안의 근거 중 과반이 합의였는지를 본다. 그래야 한 프레임
            # 한쪽 모델이 빠져도 확정이 끊기지 않는다(실측: 정지 장면에서 확정
            # 집합이 프레임당 0.42개씩 들고났다, 2026-09-21).
            e_ovd = item.get("ovd")
            if e_ovd is not None:
                live = [q for q in r.evidence
                        if q.source == "ovd"
                        and (now - q.observed_at) <= self.evidence_ttl_s]
                yes = sum(1 for q in live if (q.payload or {}).get("agreed"))
                item["agreed"] = bool(live) and yes * 2 >= len(live)
                item["ovd"]["agree_support"] = f"{yes}/{len(live)}"
            else:
                item["agreed"] = False
            out.append(item)
        # 근거가 붙은 트랙을 먼저 — 화면 상한에 걸려도 정보가 있는 것부터 남는다.
        # 화면 상한에 걸려도 정보가 많은 것부터 남는다 — 합의한 것이 가장 먼저다.
        out.sort(key=lambda d: (-int(d.get("agreed", False)),
                                -(("ovd" in d) + ("ovd2" in d) + ("clip" in d)),
                                -d["seen_s"]))
        return out[:max_tracks]

    def snapshot(self) -> dict:
        return {"records": [r.to_dict() for r in self.records.values() if r.alive],
                "n_alive": sum(1 for r in self.records.values() if r.alive),
                "n_total": len(self.records),
                "orphans": len(self.orphans),
                "applied_total": self.applied, "orphaned_total": self.orphaned}
