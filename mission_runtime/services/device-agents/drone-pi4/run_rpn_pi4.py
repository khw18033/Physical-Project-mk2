"""VisDrone 10장을 pi4(Raspberry Pi 5)에서 RPN으로 직접 돌려 지연 실측 + 오버레이.

implements: AI-B-01, AI-B-08, AI-B-10, AI-E-01, AI-O-01

`research/oln_training/p1_onnx/pi_ondevice_run_onnx.py`의 실행 규약(전처리 상수,
NMS_IOU, 좌표 역변환)을 그대로 따른다 — 같은 모델을 다른 규약으로 돌리면
기존 Pi 5 수치와 비교할 수 없다(AI-B-01).

이 스크립트가 남기는 것:
  * 이미지별 추론 지연(전처리·추론·NMS를 각각 따로) + 매 장 온도/쓰로틀
  * 후보 박스 수와 점수 분포 — VisDrone 객체가 작아서 class-agnostic
    objectness가 실제로 붙는지 눈으로 확인할 수 있어야 한다
  * 오버레이 JPG: 상위 TOP_N 후보를 원본 좌표계에 그린 것

주의: 지연은 **cool-start**다. 10장을 한 번 도는 것으로는 쓰로틀 정상상태에
도달하지 않는다(맨 Pi 5는 7~12초 만에 쓰로틀). 지속 부하 판정은
`research/drone_river_surveillance/tools/pi4_dual_stream_rpn_clip.py` 쪽 값을 쓴다.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "images"
OUT_DIR = ROOT / "out"
MODEL = ROOT / "mobilenet_rpn_p1_512.onnx"

# pi_ondevice_run_onnx.py와 동일한 상수 — 임의로 바꾸지 않는다.
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
NMS_IOU = 0.4
TOP_N = 100
THREADS = 4


def temp_c() -> float:
    try:
        raw = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return float(raw.split("=")[1].split("'")[0])
    except Exception:
        return float("nan")


def throttled_raw() -> str:
    try:
        return subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                              text=True, timeout=5).stdout.strip().split("=")[-1]
    except Exception:
        return ""


def fast_nms(boxes, scores, iou_thresh=NMS_IOU, score_thresh=0.0):
    """cv2.dnn.NMSBoxes 기반 — 순수 파이썬 NMS는 후보 수천 개에서 터진다."""
    if not boxes:
        return []
    xywh = [(x1, y1, x2 - x1, y2 - y1) for (x1, y1, x2, y2) in boxes]
    idx = cv2.dnn.NMSBoxes(xywh, scores, score_thresh, iou_thresh)
    if idx is None or len(idx) == 0:
        return []
    return [int(i) for i in (idx.flatten() if hasattr(idx, "flatten") else idx)]


def draw(bgr, boxes, scores):
    """후보 박스를 원본 좌표계에 그린다. 점수는 색으로만 — VisDrone은 객체가
    작아 박스마다 글자를 얹으면 그림이 글자로 덮인다."""
    out = bgr.copy()
    if not scores:
        return out
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0
    for (x1, y1, x2, y2), s in zip(boxes, scores):
        t = (s - lo) / span                       # 0(약) ~ 1(강)
        color = (int(255 * (1 - t)), int(90 + 120 * t), int(255 * t))  # 파랑→노랑
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), color, 1)
    cv2.putText(out, f"RPN candidates: {len(boxes)}  score {lo:.3f}~{hi:.3f}",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
    cv2.putText(out, f"RPN candidates: {len(boxes)}  score {lo:.3f}~{hi:.3f}",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1)
    return out


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = THREADS
    opts.inter_op_num_threads = 1
    t_load = time.perf_counter()
    sess = ort.InferenceSession(str(MODEL), opts, providers=["CPUExecutionProvider"])
    load_ms = (time.perf_counter() - t_load) * 1000.0
    inp_name = sess.get_inputs()[0].name
    size = int(sess.get_inputs()[0].shape[-1])

    images = sorted(IMG_DIR.glob("*.jpg"))
    rows = []

    # warmup 1회 — 첫 추론은 메모리 할당 때문에 항상 느리다. 측정에서 뺀다.
    warm = cv2.imread(str(images[0]))
    wr = cv2.resize(cv2.cvtColor(warm, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0,
                    (size, size))
    sess.run(None, {inp_name: np.ascontiguousarray(
        ((wr - MEAN) / STD).transpose(2, 0, 1)[None])})

    for p in images:
        bgr = cv2.imread(str(p))
        h0, w0 = bgr.shape[:2]

        t0 = time.perf_counter()
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        resized = cv2.resize(rgb, (size, size))
        inp = np.ascontiguousarray(((resized - MEAN) / STD).transpose(2, 0, 1)[None])
        pre_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        boxes, scores = sess.run(None, {inp_name: inp})
        infer_ms = (time.perf_counter() - t1) * 1000.0

        t2 = time.perf_counter()
        sx, sy = w0 / size, h0 / size
        order = np.argsort(-scores)
        b_all = [(float(boxes[i][0] * sx), float(boxes[i][1] * sy),
                  float(boxes[i][2] * sx), float(boxes[i][3] * sy)) for i in order]
        s_all = [float(scores[i]) for i in order]
        keep = fast_nms(b_all, s_all)[:TOP_N]
        nms_ms = (time.perf_counter() - t2) * 1000.0

        b_keep = [b_all[i] for i in keep]
        s_keep = [s_all[i] for i in keep]
        cv2.imwrite(str(OUT_DIR / f"{p.stem}_rpn.jpg"), draw(bgr, b_keep, s_keep),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])

        # 후보 박스 크기 분포 — 드론 시점 객체가 작다는 게 실제로 보이는지
        sides = [min(x2 - x1, y2 - y1) for (x1, y1, x2, y2) in b_keep]
        row = {
            "image": p.name, "orig_wh": [w0, h0], "input_size": size,
            "raw_candidates": int(len(s_all)), "after_nms": len(b_keep),
            "pre_ms": pre_ms, "infer_ms": infer_ms, "nms_ms": nms_ms,
            "total_ms": pre_ms + infer_ms + nms_ms,
            "score_max": max(s_all) if s_all else None,
            "score_min_kept": min(s_keep) if s_keep else None,
            "kept_short_side_px_median": float(np.median(sides)) if sides else None,
            "temp_c": temp_c(), "throttled": throttled_raw(),
        }
        rows.append(row)
        print(f"{p.name}  infer {infer_ms:7.1f}ms  nms {nms_ms:5.1f}ms  "
              f"cand {len(s_all)}→{len(b_keep)}  {row['temp_c']}C", flush=True)

    def stat(key):
        a = np.array([r[key] for r in rows], dtype=float)
        return {"mean": float(a.mean()), "p50": float(np.percentile(a, 50)),
                "min": float(a.min()), "max": float(a.max())}

    out = {
        "host": {"node": subprocess.run(["hostname"], capture_output=True,
                                        text=True).stdout.strip(),
                 "onnxruntime": ort.__version__,
                 "providers": ort.get_available_providers(),
                 "threads": THREADS},
        "model": MODEL.name, "input_size": size,
        "session_load_ms": load_ms,
        "n_images": len(rows),
        "note": "cool-start 값이다. 지속 부하 정상상태가 아니다.",
        "latency": {k: stat(k) for k in ("pre_ms", "infer_ms", "nms_ms", "total_ms")},
        "per_image": rows,
    }
    (ROOT / "rpn_visdrone_pi4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\n=== 요약 ===")
    for k, v in out["latency"].items():
        print(f"{k:10s} p50={v['p50']:8.2f}  mean={v['mean']:8.2f}  "
              f"min={v['min']:8.2f}  max={v['max']:8.2f}")


if __name__ == "__main__":
    main()
