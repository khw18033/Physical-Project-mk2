"""pi4(말단): RPN → 추적 → 비동기 전송/스풀 → 지연 판정 반영.

implements: AI-E-01, AI-S-01, AI-S-06, AI-B-10, AI-C-03, AI-C-05, AI-C-06, AI-N-03, AI-C-19

이 프로세스가 하는 일과 **하지 않는 일**:
  * 한다 — 로컬 영상에서 class-agnostic 후보를 만들고, ByteTracker로 지속
    정체성(track_id)을 주고, 업무 메타와 미디어 프레임을 나눠 엣지로 보내고,
    늦게 오는 판정을 **현재 트랙**에 반영한다.
  * 하지 않는다 — 물리 명령 발급, 장치 최종 가용성 판정, 전역 좌표 변환(AI-C-19).

세 가지 설계 결정과 근거:

1. **전송이 RPN을 막지 않는다.** 전송은 워커 스레드가 하고 실패는 스풀로 간다
   (`spool.py`). 인지 주기가 링크 품질에 끌려가면 AI-N-01/AI-C-05 위반이다.

2. **링크가 끊겨도 후보는 계속 생산된다.** 이것이 RPN을 말단에 두는 이유다 —
   프레임만 흘려보내는 설계였다면 단절 구간이 통째로 사라진다. 링크가 돌아오면
   스풀이 오래된 것부터 올라간다.

3. **늦게 온 판정은 좌표가 아니라 track_id로 붙인다**(`records.py`). 왕복 실측이
   약 450 ms라 판정이 도착할 때 박스는 이미 낡았다. 정체성은 낡지 않는다.

4. **먼저 나온 결과부터 반영한다.** 엣지가 단계형으로 답하므로 stage1(OVD)은
   전송 응답에 즉시 실려 오고, stage2(CLIP 확신분)는 `/api/verdicts?since=N`으로
   따로 회수한다. 느린 근거가 빠른 근거를 막지 않는다. 말단이 반영하는 것은
   **엣지가 확신한 근거뿐이다** — 미결(undecided)은 가시화 몫이고 여기 오지 않는다.

주의: 이 에이전트는 **안전 경로가 아니다.** 안전 판단은
`mission_runtime/reference/local_safety.py`와 기체 자체 failsafe가 맡는다
(AI-N-01, AI-C-20).
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
import requests

from camera import open_cameras
from common import edge_url, filter_candidates, load_config, resolve
from records import RecordStore
from spool import Spool
from tracking import ByteTracker, Detection

HERE = Path(__file__).resolve().parent
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def temp_c() -> float:
    try:
        raw = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return float(raw.split("=")[1].split("'")[0])
    except Exception:
        return float("nan")


def fast_nms(boxes, scores, iou_thresh):
    if not boxes:
        return []
    xywh = [(x1, y1, x2 - x1, y2 - y1) for (x1, y1, x2, y2) in boxes]
    idx = cv2.dnn.NMSBoxes(xywh, scores, 0.0, iou_thresh)
    if idx is None or len(idx) == 0:
        return []
    return [int(i) for i in (idx.flatten() if hasattr(idx, "flatten") else idx)]


def bucketed_nms(boxes, scores, frame_area, buckets):
    """**크기 구간별로 따로 NMS한다. 작은 박스는 큰 박스에 지워지지 않는다.**

    단일 IoU NMS의 문제(2026-09-21 실측):
      * 0.4로 조이면 겹친 작은 객체가 함께 지워진다 — 물 위 잔가지 사이의 페트병.
        하천 GT recall이 0.410 → 0.324로 떨어졌다.
      * 0.7로 풀면 작은 객체는 살지만 거대 중복 박스가 그대로 남는다.

    두 요구가 충돌하는 이유는 **한 임계를 크기가 다른 박스들에 같이 쓰기 때문**이다.
    구간을 나누면 각자 맞는 임계를 쓸 수 있고, 무엇보다 **구간이 다르면 서로
    억제하지 않는다** — 부유목 더미(큰 박스)가 그 위의 페트병(작은 박스)을 지우는
    일이 원천적으로 없어진다. 이건 부작용이 아니라 이 설계의 목적이다
    (사용자 2026-09-21: "부유목 안으로 다른 클래스가 흡수되지 않도록").

    buckets: [{"max_area_frac": 0.01, "iou": 0.7}, ...] — 작은 것부터. 마지막 구간이
    나머지를 받는다.
    """
    if not boxes:
        return []
    order = sorted(buckets, key=lambda b: float(b.get("max_area_frac", 1.0)))
    groups: list[list[int]] = [[] for _ in order]
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        frac = (max(0.0, x2 - x1) * max(0.0, y2 - y1)) / (frame_area or 1.0)
        for gi, spec in enumerate(order):
            if frac <= float(spec.get("max_area_frac", 1.0)) or gi == len(order) - 1:
                groups[gi].append(i)
                break
    keep: list[int] = []
    for gi, members in enumerate(groups):
        if not members:
            continue
        sub_b = [boxes[i] for i in members]
        sub_s = [scores[i] for i in members]
        for k in fast_nms(sub_b, sub_s, float(order[gi].get("iou", 0.5))):
            keep.append(members[k])
    keep.sort(key=lambda i: -scores[i])
    return keep


class Rpn:
    """class-agnostic 후보 제안기. 두 종류의 그래프를 같은 계약으로 감싼다.

    `kind`로 갈린다 — 상위 코드는 어느 쪽인지 모르고 (boxes, scores)만 받는다
    (AI-B-08: 상위 기능은 모델 형식에 직접 의존하지 않는다).

      p1_rpn   torchvision fasterrcnn_mobilenet_v3_large_fpn의 RPN까지만 내보낸 것.
               출력이 이미 (boxes, scores)이고 전처리는 ImageNet 정규화.
      yolov8   yolov8n을 **클래스를 무시하고** 후보 제안기로 쓴다. 출력 [1,84,N]에서
               앞 4개가 xywh, 뒤 80개가 클래스 점수이며 그 **최대값을 objectness로**
               쓴다. 전처리는 0~1 스케일만(ImageNet 정규화 없음) — 섞으면 점수가 깨진다.

    2026-09-21 교체 근거: 같은 GPU 평가에서 yolov8n class-agnostic이 P1보다
    빠르고(12.0 vs 20.4 ms) recall도 높았다(R@100 0.424 vs 0.310).
    Pi CPU에서도 같은 순서인지는 이 교체로 처음 확인한다 — GPU 비율은 옮기지 않는다(AI-B-01).
    """

    def __init__(self, cfg: dict):
        r = cfg["rpn"]
        self.kind = r.get("kind", "p1_rpn")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = int(r.get("threads", 4))
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(resolve(cfg, r["model"])), opts,
                                         providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name
        # **정사각을 가정하지 않는다.** 2026-09-21에 비정사각 export(1280x736)를
        # 올리자 shape[-1]만 읽어 1280x1280으로 리사이즈해 차원 오류가 났다.
        # H와 W를 따로 읽는다 — 종횡비 왜곡을 없애려고 비정사각을 쓰는 것이므로
        # 여기서 다시 정사각으로 만들면 목적 자체가 사라진다.
        shape = self.sess.get_inputs()[0].shape
        self.in_h, self.in_w = int(shape[2]), int(shape[3])
        self.cfg_rpn = r

    def propose(self, bgr):
        h0, w0 = bgr.shape[:2]
        t0 = time.perf_counter()
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        rs = cv2.resize(rgb, (self.in_w, self.in_h))
        # 전처리가 모델마다 다르다. p1은 export 시점에 ImageNet 정규화를 전제했고
        # yolov8은 0~1 스케일만 쓴다 — 바꿔 넣으면 점수가 조용히 망가진다.
        arr = ((rs - MEAN) / STD) if self.kind == "p1_rpn" else rs
        x = np.ascontiguousarray(arr.transpose(2, 0, 1)[None])
        pre_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        out = self.sess.run(None, {self.inp: x})
        infer_ms = (time.perf_counter() - t1) * 1000.0

        t2 = time.perf_counter()
        sx, sy = w0 / self.in_w, h0 / self.in_h
        if self.kind == "yolov8":
            # [1,84,N] → xywh(픽셀, 입력 해상도 기준) + 80 클래스 점수.
            # 클래스는 버리고 최대값만 objectness로 쓴다 = class-agnostic 후보.
            pred = np.asarray(out[0])[0]
            xywh, cls = pred[:4], pred[4:]
            scores_all = cls.max(axis=0)
            pre_conf = float(self.cfg_rpn.get("yolo_pre_conf", 0.01))
            sel = np.nonzero(scores_all >= pre_conf)[0]
            order = sel[np.argsort(-scores_all[sel])]
            cx, cy, ww, hh = xywh[0], xywh[1], xywh[2], xywh[3]
            b = [((cx[i] - ww[i] / 2) * sx, (cy[i] - hh[i] / 2) * sy,
                  (cx[i] + ww[i] / 2) * sx, (cy[i] + hh[i] / 2) * sy) for i in order]
            b = [tuple(float(v) for v in bb) for bb in b]
            s = [float(scores_all[i]) for i in order]
            n_raw = int(len(scores_all))
        else:
            boxes, scores = out
            order = np.argsort(-scores)
            b = [(float(boxes[i][0] * sx), float(boxes[i][1] * sy),
                  float(boxes[i][2] * sx), float(boxes[i][3] * sy)) for i in order]
            s = [float(scores[i]) for i in order]
            n_raw = int(len(scores))
        nb = self.cfg_rpn.get("nms_buckets")
        if nb:
            keep = bucketed_nms(b, s, float(w0 * h0), nb)
        else:
            keep = fast_nms(b, s, float(self.cfg_rpn.get("nms_iou", 0.4)))
        b, s = [b[i] for i in keep], [s[i] for i in keep]
        b, s = filter_candidates(b, s, self.cfg_rpn, w0, h0)
        nms_ms = (time.perf_counter() - t2) * 1000.0
        return b, s, {"pre_ms": round(pre_ms, 2), "infer_ms": round(infer_ms, 2),
                      "nms_ms": round(nms_ms, 2), "raw_candidates": n_raw}


def apply_input_crop(cfg: dict, bgr):
    """센서 유효 영역만 남긴다. 어안 비네팅 같은 무효 영역을 미리 자른다.

    **왜 말단에서 자르나**: 자르지 않으면 RPN이 검은 비네팅 경계에 후보를 대량으로
    내고, 화면 전체를 감싼 박스가 객체로 잡힌다(2026-09-21 실내 어안 실측: `person`
    박스가 실제 사람보다 훨씬 크게 잡혔다). 이건 인지 이후에 걸러낼 문제가 아니라
    **입력 조건**이므로 센서에 가장 가까운 곳에서 처리한다.

    crop 값은 source_size가 일치할 때만 적용한다 — 다른 해상도의 프레임에 남의
    좌표를 들이대면 조용히 엉뚱한 데를 자른다. `demo/test/class_finder_service.py`의
    BORDER_CROP_SOURCE_SIZE/BORDER_CROP_BOX가 같은 규약을 쓰며 값도 거기서 왔다.

    **crop은 실행 구성의 일부다**(AI-E-02/AI-B-01) — crop이 다르면 같은 모델이라도
    다른 구성이고, 성능 프로파일을 그대로 옮겨 쓸 수 없다.
    """
    c = cfg["pi4"].get("input_crop")
    if not c or not c.get("enabled", True):
        return bgr, None
    h, w = bgr.shape[:2]
    src = c.get("source_size")
    if src and [w, h] != list(src):
        return bgr, None                  # 해상도가 다르면 적용하지 않는다
    x1, y1, x2, y2 = c["box"]
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(w, int(x2)), min(h, int(y2))
    if x2 <= x1 or y2 <= y1:
        return bgr, None
    return bgr[y1:y2, x1:x2], [x1, y1, x2, y2]


def frames_from_cameras(cfg: dict):
    """두 카메라를 번갈아 돌며 **최신** 프레임을 낸다.

    번갈아 가는 이유: RPN이 4코어를 다 쓰므로 두 스트림은 시간을 나눠 갖는다.
    동시에 처리하면 서로 느려질 뿐 총 처리량은 같다(2026-09-21 2스트림 예산 분석).

    프레임이 아직 없는 카메라는 건너뛴다 — 한 대가 멈춰도 나머지로 계속한다(AI-C-05).
    """
    p = cfg["pi4"]
    cams = open_cameras(p.get("cameras", [{"index": 0}]))
    alive = [c for c in cams if c.available()]
    print("카메라 %d대 준비: %s" % (len(alive), [c.stats() for c in cams]), flush=True)
    if not alive:
        raise SystemExit("사용 가능한 카메라가 없다")
    try:
        i = 0
        while True:
            cam = cams[i % len(cams)]
            i += 1
            jpeg, seq = cam.take()
            if jpeg is None:
                time.sleep(0.01)
                continue
            bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                continue
            yield cam.index, f"cam{cam.index}_{seq:08d}", bgr
    finally:
        for c in cams:
            c.stop()


def frames_from_config(cfg: dict):
    """(frame_id, bgr) 를 흘린다. 이미지 디렉터리 또는 pi4 카메라."""
    p = cfg["pi4"]
    if p["source"] == "camera":
        while True:
            out = Path("/tmp/pi4_cap.jpg")
            subprocess.run(
                ["rpicam-still", "-n", "--camera", str(p.get("camera_index", 0)),
                 "--immediate", "-t", "300",
                 "--width", str(p.get("capture_width", 1280)),
                 "--height", str(p.get("capture_height", 720)),
                 "-o", str(out)],
                capture_output=True, timeout=20)
            img = cv2.imread(str(out))
            if img is not None:
                yield f"cam{p.get('camera_index',0)}_{time.time():.3f}", img
            if not p.get("loop", False):
                return
    else:
        d = resolve(cfg, p.get("images_dir", "images"))
        files = sorted(d.glob("*.jpg")) + sorted(d.glob("*.png"))
        if not files:
            raise SystemExit(f"이미지가 없다: {d}")
        while True:
            for f in files:
                img = cv2.imread(str(f))
                if img is not None:
                    yield f.stem, img
            if not p.get("loop", False):
                return


class EdgeLink:
    """엣지 전송 전담 워커. 실패는 정상 경로이며 RPN을 멈추지 않는다(AI-C-05).

    링크 상태를 `posture`로 내보낸다. 실제 축소 판단은
    `mission_runtime/ondevice/link_handover.py`의 몫이고, 여기서는 그 입력이
    될 연속 실패 수만 센다 — 판정 로직을 두 벌로 만들지 않는다(AI-N-03).
    """

    def __init__(self, cfg: dict, spool: Spool, verdicts: queue.Queue):
        self.cfg = cfg
        self.spool = spool
        self.verdicts = verdicts
        self.q: queue.Queue = queue.Queue(maxsize=8)
        self.cursor = 0
        self.consecutive_failures = 0
        self.sent = 0
        self.failed = 0
        self.resent = 0
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()
        self.q.put(None)
        self.thread.join(timeout=15)

    def submit(self, key: str, meta: dict, jpeg: bytes | None) -> None:
        try:
            self.q.put_nowait((key, meta, jpeg))
        except queue.Full:
            # 큐가 밀리면 즉시 스풀로 — 프레임을 버리지 않고, RPN도 막지 않는다.
            self.spool.put(key, meta, jpeg)

    def poll_verdicts(self) -> list[dict]:
        """엣지의 비동기 단계(stage2/3) 결과를 회수한다.

        커서만 기억하면 되므로 말단이 상태를 거의 들지 않는다. 실패는 조용히
        넘긴다 — 다음 프레임에 다시 시도하면 되고, 이것 때문에 RPN이 멈추면 안 된다.
        """
        try:
            r = requests.get(edge_url(self.cfg, f"/api/verdicts?since={self.cursor}"),
                             timeout=(self.cfg["edge"].get("connect_timeout_s", 3.0), 5.0))
            r.raise_for_status()
            data = r.json()
            self.cursor = int(data.get("cursor", self.cursor))
            return data.get("verdicts", [])
        except Exception:
            return []

    def _post(self, meta: dict, jpeg: bytes | None) -> dict:
        files = {"meta": ("meta.json", json.dumps(meta, ensure_ascii=False),
                          "application/json")}
        if jpeg:
            files["frame"] = ("frame.jpg", jpeg, "image/jpeg")
        e = self.cfg["edge"]
        r = requests.post(edge_url(self.cfg, "/api/observe"), files=files,
                          timeout=(e.get("connect_timeout_s", 3.0),
                                   e.get("read_timeout_s", 20.0)))
        r.raise_for_status()
        return r.json()

    def _drain_spool(self) -> None:
        """링크가 살아 있는 동안 밀린 것을 오래된 순서로 올린다."""
        for p in self.spool.pending()[:5]:      # 한 번에 조금씩 — 현재 프레임 우선
            try:
                meta, jpeg = self.spool.read(p)
                v = self._post(meta, jpeg)
                self.spool.done(p)
                self.resent += 1
                self.verdicts.put(v)
            except Exception:
                return                            # 아직 안 됨. 다음 기회에.

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self.q.get()
            if item is None:
                return
            key, meta, jpeg = item
            try:
                v = self._post(meta, jpeg)
                self.consecutive_failures = 0
                self.sent += 1
                self.verdicts.put(v)
                self._drain_spool()
            except Exception:
                self.consecutive_failures += 1
                self.failed += 1
                self.spool.put(key, meta, jpeg)

    @property
    def posture(self) -> str:
        return "local_only" if self.consecutive_failures >= 3 else "remote_ok"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default="pi4_agent_log.jsonl")
    args = ap.parse_args()

    cfg = load_config(args.config)
    rpn = Rpn(cfg)
    tcfg = cfg.get("tracking", {})

    def new_tracker():
        if not tcfg.get("enabled", True):
            return None
        return ByteTracker(
            high_thresh=float(tcfg.get("high_thresh", 0.6)),
            low_thresh=float(tcfg.get("low_thresh", 0.1)),
            iou_threshold=float(tcfg.get("iou_threshold", 0.3)),
            low_iou_threshold=float(tcfg.get("low_iou_threshold", 0.5)),
            max_missed_frames=int(tcfg.get("max_missed_frames", 5)),
            motion_prediction=bool(tcfg.get("motion_prediction", True)),
            velocity_alpha=float(tcfg.get("velocity_alpha", 0.5)),
        )

    # **카메라마다 따로 둔다.** 두 카메라는 서로 다른 시점이라 같은 track_id를 쓰면
    # 엉뚱한 객체에 근거가 붙는다. 다중 관측 연계는 별도 선택 기능이다(AI-S-02).
    trackers: dict[int, object] = {}
    stores: dict[int, RecordStore] = {}

    scfg = cfg.get("spool", {})
    spool = Spool(resolve(cfg, scfg.get("dir", "spool")),
                  max_items=int(scfg.get("max_items", 500)),
                  max_age_s=float(scfg.get("max_age_s", 1800)),
                  drop_frames_first=bool(scfg.get("drop_frames_first", True)))
    keep_dead = float(tcfg.get("keep_after_death_s", 10.0))
    ev_ttl = float(tcfg.get("evidence_ttl_s", 6.0))
    box_alpha = float(tcfg.get("box_alpha", 1.0))
    box_snap = float(tcfg.get("box_snap_px", 24.0))
    verdicts: queue.Queue = queue.Queue()
    link = EdgeLink(cfg, spool, verdicts)
    link.start()

    log = (HERE / args.out).open("a", encoding="utf-8")
    seq = 0

    max_frames = int(cfg["pi4"].get("max_frames", 0))
    use_cam = cfg["pi4"].get("source") == "camera"
    src = frames_from_cameras(cfg) if use_cam else frames_from_config(cfg)
    for item in src:
        cam_id, frame_id, bgr = item if use_cam else (0, item[0], item[1])
        tracker = trackers.get(cam_id)
        if tracker is None and tcfg.get("enabled", True):
            tracker = trackers[cam_id] = new_tracker()
        store = stores.get(cam_id)
        if store is None:
            store = stores[cam_id] = RecordStore(keep_after_death_s=keep_dead,
                                                evidence_ttl_s=ev_ttl,
                                                box_alpha=box_alpha,
                                                box_snap_px=box_snap)
        seq += 1
        if max_frames and seq > max_frames:
            break
        now = time.time()
        bgr, crop_box = apply_input_crop(cfg, bgr)
        h, w = bgr.shape[:2]
        boxes, scores, timing = rpn.propose(bgr)

        # 추적 — track_id가 늦게 오는 판정을 붙일 앵커다(AI-S-01 → AI-S-06).
        #
        # **점수를 프레임 내 순위로 정규화해서 넘긴다.** 검출기마다 objectness 척도가
        # 전혀 다르기 때문이다(2026-09-21 실측: p1_rpn은 max 0.996·p90 0.615인데
        # yolov8n은 드론 영상에서 max가 0.314라 절대 임계 0.6을 아무도 못 넘어
        # 트랙이 0개가 됐다). 절대값을 쓰면 추적기가 특정 검출기에 묶이는데,
        # AI-S-01은 추적이 인지 결과의 계약에만 의존하라고 요구한다.
        # 순위로 넘기면 high_thresh=0.6이 "이 프레임 상위 40%"라는 뜻이 되어
        # 검출기를 갈아끼워도 추적기 설정을 다시 잡을 필요가 없다.
        if tracker is not None:
            if scores and tcfg.get("rank_normalize", True):
                rank = np.empty(len(scores))
                rank[np.argsort(np.asarray(scores))] = np.arange(len(scores))
                tscores = ((rank + 1) / len(scores)).tolist()
            else:
                tscores = scores
            tracks = tracker.update([Detection(box=tuple(b), score=ts)
                                     for b, ts in zip(boxes, tscores)])
        else:
            # 추적 불가 시 프레임별 결과만 유지한다(AI-S-01 요구 fallback).
            tracks = []
        store.observe(tracks, seq, now)

        # 후보에 track_id를 붙인다. 추적기가 없으면 None — 엣지는 그대로 동작하고
        # 지연 반영만 못 한다(선택 기능 결손은 축소지 실패가 아니다, AI-C-05).
        by_box = {tuple(round(v, 1) for v in t.box): t.track_id for t in tracks}
        candidates = []
        for b, s in zip(boxes, scores):
            candidates.append({"box": [round(v, 2) for v in b],
                               "objectness": round(s, 5),
                               "track_id": by_box.get(tuple(round(v, 1) for v in b))})

        meta = {
            # AI-C-03: 원본 관측 참조와 지속 객체 식별은 서로 다른 목적이다.
            "frame_id": frame_id, "frame_seq": seq, "node_id": "pi4",
            "camera_id": cam_id,
            "captured_at": now, "observed_at": now,
            "frame_wh": [w, h],
            # crop을 적용했으면 좌표계가 원본과 다르다는 사실을 남긴다(AI-C-02).
            # 전역 좌표 변환은 백엔드 몫이지만, 어느 좌표계인지는 말단이 알려줘야 한다.
            "input_crop": crop_box,
            # **시점 반영 결과**. 박스는 지금 위치, 근거는 몇 프레임 전 것이다.
            # 엣지가 이걸 현재 프레임에 그려 스트리밍한다(records.transmit_view).
            "tracks": store.transmit_view(now),
            "rpn": {"model": Path(cfg["rpn"]["model"]).name, "timing_ms": timing},
            "candidates": candidates,
        }
        jpeg = None
        if cfg["pi4"].get("send_frame", True):
            ok, enc = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY,
                                                 int(cfg["pi4"].get("jpeg_quality", 85))])
            if ok:
                jpeg = enc.tobytes()
        link.submit(frame_id, meta, jpeg)

        # 늦게 도착한 판정을 **현재** 트랙에 반영한다(핵심: 좌표가 아니라 정체성).
        # 두 경로가 있고 둘 다 "먼저 온 것부터" 처리한다:
        #   (a) stage1 — 전송 응답에 즉시 실려 온 OVD 근거
        #   (b) stage2 — 엣지가 비동기로 끝낸 CLIP 확신분(커서로 회수)
        applied = []
        while True:
            try:
                applied.append(store.apply_verdict(verdicts.get_nowait(), seq))
            except queue.Empty:
                break
        for v in link.poll_verdicts():
            # 판정이 어느 카메라 것인지 보고 그 store에 반영한다.
            cam = int(v.get("camera_id", cam_id))
            st = stores.get(cam) or store
            applied.append(st.apply_verdict(v, seq))

        # **매 프레임 전체 직렬화하지 않는다.** snapshot()은 살아있는 레코드마다
        # 근거까지 dict로 펼치는데, 여기서 쓰는 값은 n_alive 하나뿐이다.
        n_alive = sum(1 for r in store.records.values() if r.alive)
        late = ""
        if applied:
            n_ev = sum(a["applied"] for a in applied)
            late = (f"  반영 {n_ev}근거/{len(applied)}건"
                    f"(평균 {sum(a['frames_late'] for a in applied)/len(applied):.1f}프레임 뒤,"
                    f" {sum(a['age_s'] for a in applied)/len(applied):.2f}s)")
        print(f"[{seq}] cam{cam_id} {frame_id[-8:]}  rpn {timing['infer_ms']:.0f}ms  후보 {len(boxes)}  "
              f"트랙 {n_alive}  링크 {link.posture}  스풀 {spool.stats()['pending']}"
              f"{late}", flush=True)

        log.write(json.dumps({"seq": seq, "frame_id": frame_id, "at": now,
                              "temp_c": temp_c(), "n_candidates": len(boxes),
                              **timing, "tracks_alive": n_alive,
                              "link": link.posture, "spool": spool.stats(),
                              "late_applied": applied}, ensure_ascii=False) + "\n")
        log.flush()
        if cfg["pi4"].get("interval_s", 0.0) > 0:
            time.sleep(cfg["pi4"]["interval_s"])

    # 마지막 응답들을 받아 반영한 뒤 정리한다.
    deadline = time.time() + float(cfg["edge"].get("read_timeout_s", 20.0))
    while time.time() < deadline and (link.q.qsize() or not verdicts.empty()):
        try:
            store.apply_verdict(verdicts.get(timeout=1.0), seq)
        except queue.Empty:
            pass
    link.stop()
    while not verdicts.empty():
        store.apply_verdict(verdicts.get_nowait(), seq)
    # 엣지의 비동기 단계가 아직 돌고 있을 수 있다. 잠시 더 회수한다.
    tail_deadline = time.time() + float(cfg["edge"].get("async_tail_s", 20.0))
    tail = 0
    while time.time() < tail_deadline:
        got = link.poll_verdicts()
        if not got:
            time.sleep(1.0)
            continue
        for v in got:
            store.apply_verdict(v, seq)
            tail += 1
    if tail:
        print(f"종료 후 비동기 판정 {tail}건 추가 회수")

    snap = {f"cam{k}": v.snapshot() for k, v in stores.items()}
    (HERE / "pi4_records.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    log.close()
    print(f"\n전송 {link.sent} / 재전송 {link.resent} / 실패 {link.failed}  "
          f"스풀 {spool.stats()}")
    for k, v in snap.items():
        print(f"{k}: 레코드 {v['n_total']}개(생존 {v['n_alive']}), "
              f"근거 반영 {v['applied_total']} / orphan {v['orphaned_total']}")


if __name__ == "__main__":
    main()
