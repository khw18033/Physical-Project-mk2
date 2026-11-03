"""지속 객체 레코드 — 이종 모델 근거를 하나의 객체 상태로 점진 구성한다.

implements: AI-S-06, AI-S-03, AI-S-04, AI-S-01, AI-C-03

근거: `docs/obsidian/ideas/progressive-object-record.pdf`
(Progressive Digital Twin Object Record Construction Method Using Heterogeneous
Models in an On-Device Environment). 이 저장소의 선행 연구이며, 여기서는 그 §3의
상태 해소(Resolving the Object State)와 점진 구성(Constructing the Object Record
Progressively) 규칙을 그대로 구현한다.

**왜 이 규칙이 필요했나**(2026-09-21 실측): 장면이 정지해 있는데 판정이 계속 흔들렸다.
앞서 시도한 방법들은 모두 "이번 프레임에 무엇이 보였나"를 다시 계산했기 때문에, 검출의
미세한 변동이 곧바로 노출 상태의 변동이 됐다. 논문은 그 문제를 세 규칙으로 막는다.

1. **의미 상태는 source group 지지로 정한다.** 클래스 c를 지지하는 서로 다른 소스
   그룹 수 |S(c)|가 가장 큰 것을 고르고, 동수면 대표 confidence 합으로, 그래도
   동수면 결정적 순서로 가른다(논문 식 7~8).
2. **한 번 정해진 클래스는 "엄격히 더 많은" 그룹 지지가 있을 때만 바뀐다.** 동수면
   기존 클래스를 유지한다. 이것이 이름이 프레임마다 뒤집히는 것을 막는 핵심이다.
3. **노출 상태 V는 lifecycle·클래스·양자화된 기하뿐이다.** confidence만 달라진 것은
   갱신으로 치지 않는다(논문 식 13). 논문은 월드 좌표를 0.02 m로 양자화하는데,
   여기서는 아직 전역 좌표가 없으므로(AI-C-02: 전역 변환은 백엔드 몫) 영상 좌표를
   `geometry_quantum_px`로 양자화한다.

기하는 마스크가 없을 때 **가용 박스의 confidence 가중 평균**이다(논문 §3.1). 지금
구성에는 segmentation 소스가 없으므로 이 경로만 쓴다.

lifecycle은 **연속 미관측 횟수**로 정한다 — 벽시계 시간이 아니다(논문 식 9):
provisional → confirmed(검출 소스 그룹 2개 이상이 지지) → stale(연속 3회 미관측)
→ expired(연속 5회 미관측, 이후 매칭 제외). stale은 다시 관측되면 되살아난다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 논문 §3의 임계. 이름을 그대로 남겨 두어 논문과 대조할 수 있게 한다.
ASSOC_IOU = 0.30          # 관측 내 근거 클러스터링
TRACK_IOU = 0.20          # 관측 간 지속 객체 매칭
INIT_CONF = 0.30          # 새 객체 초기화 최소 confidence
STALE_MISSES = 3
EXPIRE_MISSES = 5
CONFIRM_GROUPS = 2


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    ua = ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / ua if ua > 0 else 0.0


@dataclass
class Evidence:
    """근거 사건 e = (id, o, s, t, k, c, p) — 논문 식 1."""

    obs: int                 # 관측 식별자 o
    source: str              # 소스 그룹 s
    at: float                # 완료 시각 t
    kind: str                # 근거 종류 k ("box")
    conf: float              # confidence c
    box: tuple               # 페이로드 p
    label: str = ""
    concept: str = ""


@dataclass
class ObjectRecord:
    """지속 객체 레코드 R_j — 논문 식 12."""

    obj_id: int
    box: tuple
    first_obs: int
    last_obs: int
    misses: int = 0
    lifecycle: str = "provisional"
    concept: str = ""            # 확립된 의미 클래스(개념 키)
    label: str = ""              # 그 클래스의 대표 라벨
    conf: float = 0.0
    class_groups: int = 0        # 현재 클래스를 지지하는 소스 그룹 수 |S(c)|
    groups_seen: set = field(default_factory=set)
    alt: dict | None = None      # 상대 소스가 말한 것(관리자 판단용)
    revision: int = 0            # 노출 갱신 번호 r
    # **노출 기하.** 해소된 박스(`box`)와 따로 둔다 — V가 바뀌지 않으면 노출은
    # 그대로여야 하기 때문이다. 이것을 분리하지 않으면 갱신 번호만 안 올라가고
    # 화면의 박스는 매 프레임 떨린다(양자화가 무의미해진다).
    exposed_box: tuple = (0.0, 0.0, 0.0, 0.0)

    def visible_semantic(self) -> tuple:
        """노출 상태 V(R)의 비기하 부분 — 논문 식 13. confidence는 **들어가지 않는다.**"""
        return (self.lifecycle, self.concept)

    def geometry_moved(self, resolved, quantum: float) -> bool:
        """노출 기하를 갱신할 만큼 움직였는가 — **불감대**로 판정한다.

        논문은 월드 좌표를 0.02 m로 양자화해 V를 만든다. 그 방식을 영상 좌표에
        그대로 쓰면 값이 **양자 경계에 걸쳤을 때** 1~2 px 흔들림에도 매 프레임
        반올림이 뒤집힌다(2026-09-21 실측: 1 px 지터에 갱신 3회). 경계는 고정된
        격자가 아니라 **현재 노출값**을 기준으로 잡아야 한다. 노출값에서 quantum
        이상 벗어날 때만 갱신하면 경계 문제가 원천적으로 없어진다.
        """
        return max(abs(resolved[i] - self.exposed_box[i]) for i in range(4)) > quantum

    def confirmed_ready(self) -> bool:
        """화면에 확정으로 올릴 수 있는가 — lifecycle과 **클래스 지지**를 모두 본다.

        논문의 lifecycle confirmed는 '객체가 두 소스 그룹의 지지를 받았다'이고
        클래스 일치까지 요구하지는 않는다. 이 배치의 요구는 "두 모델이 합의할 때만
        확정"이므로(사용자 2026-09-21) 클래스 지지 조건을 덧붙인다.
        """
        return self.lifecycle == "confirmed" and self.class_groups >= CONFIRM_GROUPS

    def to_dict(self) -> dict:
        return {"obj_id": self.obj_id, "box": [round(v, 1) for v in self.exposed_box],
                "label": self.label, "conf": round(self.conf, 3),
                "concept": self.concept, "alt": self.alt,
                "lifecycle": self.lifecycle,
                "confirmed": self.confirmed_ready(),
                "groups": self.class_groups, "revision": self.revision,
                "seen_obs": self.last_obs - self.first_obs + 1}


class ObjectTracks:
    """카메라 하나의 지속 객체 레코드 집합."""

    def __init__(self, cfg: dict):
        c = cfg.get("object_tracks", {})
        self.assoc_iou = float(c.get("assoc_iou", ASSOC_IOU))
        self.track_iou = float(c.get("track_iou", TRACK_IOU))
        self.init_conf = float(c.get("init_conf", INIT_CONF))
        self.stale_misses = int(c.get("stale_misses", STALE_MISSES))
        self.expire_misses = int(c.get("expire_misses", EXPIRE_MISSES))
        self.quantum = float(c.get("geometry_quantum_px", 8.0))
        # 해소된 기하를 레코드에 반영할 때의 평활 계수. 1이면 평활 없음.
        # **왜 필요한가**: 기하는 가용 박스의 confidence 가중 평균이라, 한 모델이
        # 한 관측에서 빠지면 '두 박스의 중간'에서 '한 박스'로 확 옮겨간다. 그러면
        # 관측 간 매칭(IoU 0.20)이 끊겨 새 객체가 생기고 누적 지지가 리셋된다 —
        # 실측에서 확정 객체 수가 중앙 0으로 떨어진 원인이 이것이었다.
        self.geom_alpha = float(c.get("geometry_alpha", 0.5))
        self.objects: dict[int, ObjectRecord] = {}
        self.last_stats: dict = {}
        self._next = 1
        self._obs = 0

    # -- 관측 내 근거 클러스터링 -------------------------------------------
    def _cluster(self, evs: list[Evidence]) -> list[list[Evidence]]:
        """같은 물리 객체를 가리키는 근거를 모은다(논문 §3, 임계 0.30).

        confidence가 높은 근거부터 클러스터의 **씨앗**이 되고, 이후 근거는 씨앗과
        직접 겹칠 때만 그 클러스터에 들어간다.

        **멤버 아무거나와 비교하면 안 된다**(single-link). 그러면 A-B가 겹치고
        B-C가 겹칠 때 A와 C가 전혀 겹치지 않아도 한 덩어리가 된다. 2026-09-21
        실측에서 사무실 장면의 검출 56개가 이 연쇄로 **객체 3개**가 됐고, 기하는
        전부의 평균이라 화면을 덮는 박스가 나왔으며 소스 그룹 지지도 뭉개졌다.
        씨앗 기준으로 묶으면 각 클러스터가 하나의 물체 주변에 머문다.
        """
        clusters: list[list[Evidence]] = []
        for e in sorted(evs, key=lambda x: -x.conf):
            for cl in clusters:
                if _iou(e.box, cl[0].box) >= self.assoc_iou:
                    cl.append(e)
                    break
            else:
                clusters.append([e])
        return clusters

    # -- 상태 해소 ---------------------------------------------------------
    @staticmethod
    def _representatives(cl: list[Evidence]) -> dict[str, Evidence]:
        """소스 그룹별 대표 가설 h_{j,g} — 그룹 내 최고 confidence(논문 §3.1)."""
        rep: dict[str, Evidence] = {}
        for e in cl:
            if e.source not in rep or e.conf > rep[e.source].conf:
                rep[e.source] = e
        return rep

    def _resolve_semantics(self, rec: ObjectRecord, rep: dict[str, Evidence]) -> None:
        """의미 상태를 해소한다 — 논문 식 7~8 + 클래스 교체 이력 규칙.

        **핵심**: 이미 클래스가 확립돼 있으면 새 클래스는 **엄격히 더 많은** 소스
        그룹의 지지를 받을 때만 대체한다. 동수면 기존 클래스를 유지한다. 이 한 줄이
        "장면이 그대로인데 이름이 프레임마다 뒤집히는" 현상을 막는다.
        """
        support: dict[str, list[Evidence]] = {}
        for e in rep.values():
            if e.concept:
                support.setdefault(e.concept, []).append(e)
        if not support:
            return                      # 이름 붙은 근거가 없으면 unknown 유지

        def rank(item):
            c, evs = item
            return (len(evs), sum(x.conf for x in evs), c)   # 그룹 수 → conf 합 → 결정적 순서

        best_c, best_evs = max(support.items(), key=rank)
        n_best = len(best_evs)

        if rec.concept and best_c != rec.concept:
            # 비교 대상은 **현재 관측의 지지**가 아니라 그 클래스가 **확립된 지지
            # 수준**이다. 이번 프레임에 기존 클래스를 아무도 말하지 않았다고 해서
            # 단일 소스 주장에 자리를 내주면 이력이 성립하지 않는다 — 실측에서
            # 2그룹으로 확립된 `chair`가 한 모델의 `person` 한 번에 뒤집혔다.
            cur = max(len(support.get(rec.concept, [])), rec.class_groups)
            if n_best <= cur:
                keep = support.get(rec.concept)
                if keep:
                    best_c, best_evs, n_best = rec.concept, keep, len(keep)
                else:
                    return          # 기존 클래스를 그대로 둔다(이번 관측에 근거 없음)

        top = max(best_evs, key=lambda x: x.conf)
        rec.concept, rec.label, rec.conf = best_c, top.label, top.conf
        rec.class_groups = n_best
        others = [e for e in rep.values() if e is not top and e.concept == best_c]
        rec.alt = ({"label": others[0].label, "conf": round(others[0].conf, 3)}
                   if others else None)

    @staticmethod
    def _resolve_geometry(cl: list[Evidence]) -> tuple:
        """기하 — 마스크가 없으므로 **가용 박스의 confidence 가중 평균**(논문 §3.1).

        최고 점수 박스 하나만 쓰면 어느 모델이 이겼는지에 따라 박스가 튄다.
        가중 평균은 두 모델이 같은 것을 볼 때 그 사이에 자리잡아 훨씬 덜 움직인다.
        """
        w = sum(max(1e-6, e.conf) for e in cl)
        return tuple(sum(max(1e-6, e.conf) * e.box[i] for e in cl) / w
                     for i in range(4))

    # -- 점진 구성 ---------------------------------------------------------
    def update(self, dets: list[dict], now: float) -> list[ObjectRecord]:
        """한 관측의 검출들을 받아 레코드를 갱신한다(논문 §3.2)."""
        self._obs += 1
        obs = self._obs

        evs = [Evidence(obs=obs, source=("text_prompt"
                                         if "text_prompt" in (d.get("sources") or [])
                                         and "prompt_free" not in (d.get("sources") or [])
                                         else "prompt_free"),
                        at=now, kind="box", conf=float(d["conf"]),
                        box=tuple(d["box"]), label=d.get("label", ""),
                        concept=d.get("concept", ""))
               for d in dets]
        # 합의로 묶인 검출은 두 소스가 같은 자리에서 말한 것이다 — 두 근거로 편다.
        for d in dets:
            if len(d.get("sources") or []) == 2 and d.get("alt"):
                evs.append(Evidence(obs=obs, source="text_prompt", at=now, kind="box",
                                    conf=float(d["alt"].get("conf", 0.0)),
                                    box=tuple(d["box"]),
                                    label=d["alt"].get("label", ""),
                                    concept=d.get("concept", "")))

        clusters = self._cluster(evs)

        # 관측 간 매칭 — 기존 레코드에 붙이거나 새로 만든다.
        alive = [r for r in self.objects.values() if r.lifecycle != "expired"]
        used = set()
        matched: list[tuple[ObjectRecord, list[Evidence]]] = []
        # 매칭 기준은 **노출 기하**다 — 해소된 기하는 근거 구성에 따라 튀므로
        # 그것으로 매칭하면 흔들리는 값끼리 비교하게 된다.
        pairs = sorted(((_iou(r.exposed_box, self._resolve_geometry(cl)), ri, ci)
                        for ri, r in enumerate(alive)
                        for ci, cl in enumerate(clusters)),
                       key=lambda p: -p[0])
        taken_r, taken_c = set(), set()
        for v, ri, ci in pairs:
            if v < self.track_iou or ri in taken_r or ci in taken_c:
                continue
            taken_r.add(ri)
            taken_c.add(ci)
            matched.append((alive[ri], clusters[ci]))
            used.add(ci)

        for ci, cl in enumerate(clusters):
            if ci in used:
                continue
            if max(e.conf for e in cl) < self.init_conf:
                continue                    # 논문: conf > 0.30에서만 새 객체 생성
            g = self._resolve_geometry(cl)
            rec = ObjectRecord(obj_id=self._next, box=g, exposed_box=g,
                               first_obs=obs, last_obs=obs)
            self._next += 1
            self.objects[rec.obj_id] = rec
            matched.append((rec, cl))

        for rec, cl in matched:
            rep = self._representatives(cl)
            before = rec.visible_semantic()
            resolved = self._resolve_geometry(cl)
            a = self.geom_alpha
            rec.box = tuple(rec.box[i] * (1 - a) + resolved[i] * a for i in range(4))
            self._resolve_semantics(rec, rep)
            rec.groups_seen |= set(rep)
            rec.last_obs = obs
            rec.misses = 0
            if rec.lifecycle in ("provisional", "stale"):
                rec.lifecycle = ("confirmed" if len(rec.groups_seen) >= CONFIRM_GROUPS
                                 else "provisional")
            moved = rec.geometry_moved(rec.box, self.quantum)
            if rec.visible_semantic() != before or moved:
                # 노출 갱신은 V가 바뀔 때만이고, 그때만 노출 기하도 새 값이 된다.
                # confidence만 달라진 것은 갱신이 아니다(논문 식 13).
                rec.revision += 1
                if moved:
                    rec.exposed_box = rec.box

        seen_ids = {r.obj_id for r, _ in matched}
        for rec in list(self.objects.values()):
            if rec.obj_id in seen_ids or rec.lifecycle == "expired":
                continue
            rec.misses += 1
            if rec.misses >= self.expire_misses:
                rec.lifecycle = "expired"
                self.objects.pop(rec.obj_id, None)
            elif rec.misses >= self.stale_misses:
                rec.lifecycle = "stale"

        self.last_stats = {"evidence": len(evs), "clusters": len(clusters),
                           "matched": len(taken_c),
                           "new": len(matched) - len(taken_c),
                           "below_init_conf": sum(
                               1 for ci, cl in enumerate(clusters)
                               if ci not in used
                               and max(e.conf for e in cl) < self.init_conf),
                           "objects": len(self.objects)}
        return [r for r in self.objects.values() if r.lifecycle != "expired"]
