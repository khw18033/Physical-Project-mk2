"""
anchor360_live.py — 360° 앵커 카메라 실시간 장애물 파이프라인 (상주형 데몬)

[무엇을 하나]
  pano_receiver 가 받아 놓은 equirect.jpg 를 감시하다가, 새 사진이 들어오면
    equirect → (메모리) perspective 슬라이스 → zeroshot 검출 → 필터 → NMS
    → 바닥평면 pos3d/size → JSON → UDP 송출 + 파일 저장
  까지를 한 프로세스 안에서 자동으로 수행한다.

[기존 스크립트와의 관계]
  detect_send_3b2.py 를 "상주 + 감시 루프" 형태로 재구성한 것.
  검출 필터 / NMS / pixel_to_ground 수식 / JSON 스키마는 detect_send_3b2.py 와
  동일하다. (검증된 수식이라 한 줄도 바꾸지 않음)
  detect_ground_3b1.py(시각 검증) / detect_send_3b2.py(수동 1회 송출) 는
  그대로 남겨 두고 병행해서 쓴다.

[핵심 3가지]
  1) 모델 상주   : YOLOWorld 로드(+워밍업)를 기동 시 1회만. 사진마다 8~9초씩 안 든다.
  2) 메모리 슬라이스 : e2p 결과를 검출에 바로 넘긴다. equirect 를 cv2.imread(BGR)로
                     읽으므로 슬라이스도 BGR → 채널 변환 불필요.
                     JPEG 재인코딩 손실이 없어 파일 경유보다 좌표가 정확하다.
                     ※ 백업이 필요하면 --save-slice 로 "검출에 쓴 그 배열"을
                       그대로 디스크에도 남긴다(검출 경로는 무손실 유지).
  3) 감시 루프   : watch_dir 아래 */equirect.jpg 중 mtime 최신을 집어 처리.
                  같은 파일은 두 번 처리하지 않는다.

[좌표 규약 — detect_send_3b2.py 와 동일]
  +x = 오른쪽, +y = 위(바닥 y=0), +z = 슬라이스가 보는 정면. 단위 m.
  원점 = 카메라를 바닥에 수직 투영한 점.
  ※ 슬라이스 1장만 보내므로 좌표는 "그 슬라이스 로컬"이다.
     Unity 쪽 yawOffsetDeg 로 맵 방향에 맞춘다.
     (여러 슬라이스를 합칠 때에만 u_deg 회전이 필요하며, 지금은 해당 없음)

[품질 필터 — 왜 필요한가]
  --drop-clipped : bbox 아랫변이 화면 밑변에 붙은 검출 제외.
                   접지점이 프레임 밖이라 바닥평면 거리가 원리적으로 안 맞는다.
                   (예: 화면 아래로 잘린 책상이 D=0.58m 로 나옴)
  --max-dist     : 지정 거리 초과 검출 제외.
                   지평선에 가까운 얕은 광선은 바닥과 거의 평행해서, 픽셀 1~2개
                   오차가 미터 단위로 증폭된다. 랩실 규모 밖 값은 신뢰할 수 없다.
                   (예: D=11.88m, D=6.88m 짜리 conf 0.12~0.13 검출)
  둘 다 임계값 경계의 불안정 검출을 걸러 Unity 에 유령 큐브가 뜨는 것을 막는다.
  ※ 이 불안정성은 메모리/파일 처리 방식과 무관하다. 파일 경유에서도 동일하게
    나타났으며(conf 0.12 box, D=6.88m), 원인은 클래스별 conf 임계값 경계다.

[Unity 쪽]
  Anchor360ObstacleReceiver.cs (UDP 5010, 스냅샷 방식) 무수정으로 동작.
  검출 0개일 때도 빈 패킷을 보내므로 사라진 장애물의 큐브가 자동으로 지워진다.

[CLIP 캐시 주의]
  YOLOWorld.set_classes() 는 CLIP(ViT-B-32, 약 338MB)을 쓰는데, 이 파일은
  현재 작업 디렉터리 아래 weights/clip/ 에 캐시된다. 다른 폴더에서 띄우면
  다시 받는다. 그래서 이 스크립트는 기동 시 자기 파일이 있는 디렉터리로
  chdir 한다(사용자가 넘긴 경로는 그 전에 절대경로로 변환하므로 안전).

[실행]
  # 실시간 감시 (권장 옵션 포함)
  python3 anchor360_live.py --drop-clipped --max-dist 8 --debug-img --save-slice

  # 카메라 없이 기존 사진 1장으로 테스트
  python3 anchor360_live.py --replay /경로/equirect.jpg \
      --drop-clipped --max-dist 8 --debug-img

  # 현재 폴더에 있는 최신 사진 1장만 처리하고 종료
  python3 anchor360_live.py --once --drop-clipped --max-dist 8

  # 필터 없이(원본 그대로) 보고 싶을 때
  python3 anchor360_live.py --once

[종료]
  Ctrl+C
"""

import os
import glob
import math
import json
import time
import socket
import signal
import argparse
import datetime

import cv2
import numpy as np
import yaml
import py360convert
from ultralytics import YOLOWorld


# =========================================================
# 기본값
# =========================================================
DEF_WATCH_DIR = os.path.expanduser(
    "~/capstone-db/image_server/pano_captures/pro2_anchor")
DEF_CFG = os.path.expanduser(
    "~/capstone-db/image_server/unidepth_dual_yolo_config.yaml")
DEF_OUT_DIR = os.path.expanduser("~/capstone-db/docx2026/live_out")
DEF_SLICE_DIR = os.path.expanduser("~/capstone-db/docx2026/live_out/slices")

DEF_U_DEG = 50.0        # 왼쪽 복도 슬라이스
DEF_V_DEG = -35.0       # 하향각. pitch 와 같은 값이어야 한다.
DEF_CAM_H = 1.85        # 렌즈중심 높이(m)
DEF_UNITY_IP = "192.168.50.246"
DEF_PORT = 5010
DEF_IMGSZ = 640
DEF_POLL = 1.0          # 감시 주기(초)

KEEP_GROUPS = {"HARD_OBSTACLE", "AGENT"}

_running = True


def _on_sigint(signum, frame):
    global _running
    _running = False
    print("\n[live] 종료 요청 — 현재 작업 마치고 정리합니다.")


# =========================================================
# 설정 로드
# =========================================================
class Config:
    """unidepth_dual_yolo_config.yaml 에서 검출에 필요한 항목만 뽑아 든다."""

    def __init__(self, cfg_path, weight_override=None):
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        self.path = cfg_path
        self.weight = weight_override or cfg["models"]["zeroshot_detector"]["weight"]
        self.classes = cfg["classes"]["zeroshot"]
        self.conf = float(cfg["models"]["zeroshot_detector"]["conf"])
        self.group = cfg["group_mapping"]
        self.class_conf = cfg.get("class_conf", {}).get("zeroshot", {})
        self.iou = float(cfg.get("fusion", {}).get("iou", 0.45))

    def min_conf(self, name):
        return float(self.class_conf.get(name, self.class_conf.get("default", 0.0)))


# =========================================================
# 기하 — detect_send_3b2.py 와 동일한 수식
# =========================================================
class GroundProjector:
    """
    슬라이스(합성 핀홀) 픽셀 → 바닥평면(y=0) 교차점.

    슬라이스는 e2p fov=(90,90), out_hw=(720,720) 이므로
      fx = fy = W / (2*tan(45deg)) = W/2 = 360
      cx = cy = W/2 = 360
    카메라는 높이 cam_h, 하향 pitch(음수), roll 0 으로 고정.
    """

    def __init__(self, width, height, cam_h, pitch_deg):
        self.W, self.H = width, height
        self.fx = self.fy = width / (2.0 * math.tan(math.radians(90) / 2.0))
        self.cx, self.cy = width / 2.0, height / 2.0
        self.cam_h = cam_h
        th = math.radians(pitch_deg)
        self.cos_t, self.sin_t = math.cos(th), math.sin(th)

    def pixel_to_ground(self, px, py):
        """반환: ((X, Z) 또는 None, wy).  wy 는 광선의 하향 성분(음수라야 바닥과 만남)"""
        dx = (px - self.cx) / self.fx
        dy = -(py - self.cy) / self.fy
        dz = 1.0
        wy = self.cos_t * dy + self.sin_t * dz
        wz = -self.sin_t * dy + self.cos_t * dz
        wx = dx
        if wy >= -1e-6:                 # 지평선 위 → 바닥과 안 만남
            return None, wy
        t = -self.cam_h / wy
        return (wx * t, wz * t), wy     # (X, Z) 바닥좌표(m)


# =========================================================
# 검출기 (모델 상주)
# =========================================================
class Detector:
    def __init__(self, cfg: Config, imgsz: int):
        self.cfg = cfg
        self.imgsz = imgsz
        t0 = time.perf_counter()
        self.model = YOLOWorld(cfg.weight)
        self.model.set_classes(cfg.classes)
        self.load_s = time.perf_counter() - t0

    def warmup(self, size=720):
        """더미 프레임 1회 추론. CUDA 초기화 비용을 기동 시점으로 당긴다."""
        dummy = np.zeros((size, size, 3), dtype=np.uint8)
        t0 = time.perf_counter()
        self.model.predict(dummy, conf=self.cfg.conf, imgsz=self.imgsz, verbose=False)
        return time.perf_counter() - t0

    def detect(self, bgr):
        """검출 → 클래스별 conf 하한 → 그룹 필터 → NMS. bbox 리스트 반환."""
        res = self.model.predict(bgr, conf=self.cfg.conf,
                                 imgsz=self.imgsz, verbose=False)
        raw = []
        if res and res[0].boxes is not None:
            for b in res[0].boxes:
                cid = int(b.cls[0])
                name = (self.cfg.classes[cid] if cid < len(self.cfg.classes)
                        else f"cls{cid}")
                conf = float(b.conf[0])
                if conf < self.cfg.min_conf(name):
                    continue
                grp = self.cfg.group.get(name, "UNKNOWN_OBSTACLE")
                if grp not in KEEP_GROUPS:
                    continue
                x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
                raw.append({"name": name, "group": grp, "conf": conf,
                            "bbox": [x1, y1, x2, y2]})
        return self._nms(raw, self.cfg.iou)

    @staticmethod
    def _iou(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
        return inter / ua if ua > 0 else 0.0

    @classmethod
    def _nms(cls, raw, iou_thr):
        raw.sort(key=lambda d: -d["conf"])
        kept = []
        for d in raw:
            if all(cls._iou(d["bbox"], k["bbox"]) < iou_thr for k in kept):
                kept.append(d)
        return kept


# =========================================================
# 슬라이스 (메모리)
# =========================================================
def slice_equirect(equirect_bgr, u_deg, v_deg, out_size=720):
    """
    equirect(BGR) → perspective 슬라이스(BGR).
    e2p 는 기하 리샘플링이라 채널 의미를 따지지 않으므로,
    BGR 로 넣으면 BGR 로 나온다 → 검출/저장에 그대로 쓸 수 있다.
    """
    persp = py360convert.e2p(equirect_bgr, fov_deg=(90, 90),
                             u_deg=u_deg, v_deg=v_deg,
                             out_hw=(out_size, out_size))
    if persp.dtype != np.uint8:
        persp = np.clip(persp, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(persp)


# =========================================================
# 패킷 조립 — detect_send_3b2.py 스키마와 동일
# =========================================================
def build_packet(kept, proj: GroundProjector, u_deg, v_deg,
                 drop_clipped=False, max_dist=None):
    """
    검출 리스트 → Unity 전송용 패킷.
    dropped 리스트도 함께 반환해 콘솔에 "왜 걸렀는지"를 남긴다.
    """
    accepted, dropped = [], []

    for d in kept:
        x1, y1, x2, y2 = d["bbox"]
        bcx, bcy = (x1 + x2) / 2.0, y2          # 하단 중앙 = 바닥 접지점
        g, wy = proj.pixel_to_ground(bcx, bcy)

        if g is None:
            dropped.append((d, "지평선위", None))
            continue

        X, Z = g
        D = math.hypot(X, Z)
        clipped = bool(y2 >= proj.H - 2)

        if drop_clipped and clipped:
            dropped.append((d, "접지잘림", D))
            continue
        if max_dist is not None and D > max_dist:
            dropped.append((d, f">{max_dist:g}m", D))
            continue

        # 대략 크기(m): bbox 픽셀폭/높이를 거리로 환산 (rough, Unity 에서 clamp)
        w_m = (x2 - x1) / proj.fx * D
        h_m = (y2 - y1) / proj.fy * D
        accepted.append({
            "name": d["name"], "group": d["group"],
            "pos3d": {"x": round(X, 3), "y": 0.0, "z": round(Z, 3)},
            "dist_m": round(D, 3),
            "size": {"w": round(w_m, 3), "h": round(h_m, 3), "d": round(w_m, 3)},
            "bbox_xyxy": [int(x1), int(y1), int(x2), int(y2)],
            "ground_clipped": clipped,
            "conf": round(d["conf"], 3),
            "wy": round(wy, 3),
        })

    # 필터 후에 id 를 매겨 번호에 구멍이 생기지 않게 한다
    for i, det in enumerate(accepted, 1):
        det["id"] = i

    packet = {
        "timestamp": f"{time.time():.3f}",
        "camera_id": "anchor360",
        "frame": "anchor360",
        "anchor_dir": {"u_deg": u_deg, "v_deg": v_deg, "roll_deg": 0},
        "detections": accepted,
    }
    return packet, dropped


def draw_debug(bgr, packet, out_path):
    """전송한 검출만 그린 시각화 이미지 저장 (detect_ground_3b1 형식)."""
    img = bgr.copy()
    for d in packet["detections"]:
        x1, y1, x2, y2 = d["bbox_xyxy"]
        bcx, bcy = (x1 + x2) // 2, y2
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.circle(img, (bcx, bcy), 5, (0, 0, 255), -1)
        label = f'{d["name"]} {d["conf"]:.2f} D={d["dist_m"]:.2f}m'
        cv2.putText(img, label, (x1, max(y1 - 5, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.imwrite(out_path, img)


# =========================================================
# 감시 — 최신 equirect 찾기
# =========================================================
def find_latest(watch_dir):
    """watch_dir/*/equirect.jpg 중 mtime 최신 (경로, mtime, size) 반환."""
    newest = None
    for p in glob.glob(os.path.join(watch_dir, "*", "equirect.jpg")):
        try:
            st = os.stat(p)
        except OSError:
            continue
        if newest is None or st.st_mtime > newest[1]:
            newest = (p, st.st_mtime, st.st_size)
    return newest


def wait_stable(path, tries=5, delay=0.3):
    """
    파일 크기가 연속 2회 같으면 쓰기 완료로 본다.
    pano_receiver 가 원자적 교체(.part → os.replace)를 쓰면 사실 불필요하지만,
    안전망으로 둔다.
    """
    last = -1
    for _ in range(tries):
        try:
            cur = os.path.getsize(path)
        except OSError:
            return False
        if cur > 0 and cur == last:
            return True
        last = cur
        time.sleep(delay)
    return last > 0


# =========================================================
# 1회 처리
# =========================================================
def process_one(path, det: Detector, sock, args, seq):
    t_all = time.perf_counter()

    equ = cv2.imread(path)                       # BGR
    if equ is None:
        print(f"[live] 읽기 실패, 건너뜀: {path}")
        return False
    t_read = time.perf_counter()

    sl = slice_equirect(equ, args.u, args.v, args.slice_size)
    t_slice = time.perf_counter()

    kept = det.detect(sl)
    t_infer = time.perf_counter()

    proj = GroundProjector(sl.shape[1], sl.shape[0], args.cam_h, args.pitch)
    packet, dropped = build_packet(kept, proj, args.u, args.v,
                                   args.drop_clipped, args.max_dist)
    payload = json.dumps(packet, ensure_ascii=False)

    # UDP 송출 — 검출 0개여도 보낸다(스냅샷: 사라진 큐브 정리)
    sent = True
    try:
        sock.sendto(payload.encode("utf-8"), (args.unity_ip, args.port))
    except Exception as e:
        sent = False
        print(f"[live] UDP 송출 실패: {e}")

    # JSON 저장 (원자적)
    os.makedirs(args.out_dir, exist_ok=True)
    json_path = os.path.join(args.out_dir, "anchor360_latest.json")
    tmp = json_path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(packet, f, ensure_ascii=False, indent=2)
    os.replace(tmp, json_path)

    cap = os.path.basename(os.path.dirname(path))

    # 슬라이스 원본 백업 — 검출에 쓴 그 배열을 그대로 저장(검출 경로는 무손실 유지)
    if args.save_slice:
        os.makedirs(args.slice_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{stamp}__{cap}__u{args.u:+.0f}_v{args.v:+.0f}.jpg"
        cv2.imwrite(os.path.join(args.slice_dir, fname), sl)

    if args.debug_img:
        draw_debug(sl, packet, os.path.join(args.out_dir, "anchor360_latest.jpg"))

    t_end = time.perf_counter()
    n_ok, n_drop = len(packet["detections"]), len(dropped)
    print(f"[live] #{seq} {cap}  전송 {n_ok}개"
          f"{f' (걸러냄 {n_drop}개)' if n_drop else ''}"
          f"  | read {t_read-t_all:.2f}s  slice {t_slice-t_read:.2f}s"
          f"  infer {t_infer-t_slice:.2f}s  총 {t_end-t_all:.2f}s"
          f"  | UDP {'OK' if sent else 'FAIL'} → {args.unity_ip}:{args.port}")
    for d in packet["detections"]:
        print(f'        {d["name"]:16}{d["group"]:14}'
              f' pos3d=({d["pos3d"]["x"]:+.2f}, 0, {d["pos3d"]["z"]:+.2f})'
              f' D={d["dist_m"]:5.2f}  conf={d["conf"]:.2f}  wy={d["wy"]:+.3f}')
    for d, why, D in dropped:
        ds = f"D={D:5.2f}" if D is not None else "D=  -  "
        print(f'        [제외:{why:>8}] {d["name"]:16}{ds}  conf={d["conf"]:.2f}')
    return True


# =========================================================
# main
# =========================================================
def main():
    ap = argparse.ArgumentParser(
        description="360° 앵커 카메라 실시간 장애물 → Unity UDP 파이프라인")
    ap.add_argument("--watch-dir", default=DEF_WATCH_DIR,
                    help="pano_receiver 저장 루트 (기본: pano_captures/pro2_anchor)")
    ap.add_argument("--no-wait-stable", action="store_true",
                    help="원자적 쓰기를 신뢰하고 크기 안정화 대기를 건너뛴다")
    ap.add_argument("--cfg", default=DEF_CFG, help="zeroshot config yaml")
    ap.add_argument("--weight", default=None,
                    help="YOLOWorld 가중치 경로. 지정하면 config 값을 덮어씀")
    ap.add_argument("--out-dir", default=DEF_OUT_DIR, help="JSON/디버그 이미지 저장 위치")

    ap.add_argument("--u", type=float, default=DEF_U_DEG, help="슬라이스 방위각(deg)")
    ap.add_argument("--v", type=float, default=DEF_V_DEG, help="슬라이스 고저각(deg)")
    ap.add_argument("--slice-size", type=int, default=720,
                    help="슬라이스 한 변 픽셀. 720 고정 권장(기하 전제)")
    ap.add_argument("--cam-h", type=float, default=DEF_CAM_H, help="카메라 높이(m)")
    ap.add_argument("--pitch", type=float, default=None,
                    help="바닥평면 계산용 하향각(deg). 기본은 --v 와 동일")

    ap.add_argument("--unity-ip", default=DEF_UNITY_IP)
    ap.add_argument("--port", type=int, default=DEF_PORT)
    ap.add_argument("--imgsz", type=int, default=DEF_IMGSZ)
    ap.add_argument("--poll", type=float, default=DEF_POLL, help="감시 주기(초)")

    # --- 품질 필터 ---
    ap.add_argument("--drop-clipped", action="store_true",
                    help="접지점이 프레임 밖으로 잘린 검출 제외(거리 신뢰 낮음)")
    ap.add_argument("--max-dist", type=float, default=None,
                    help="이 거리(m) 초과 검출 제외. 랩실 규모면 6~8 권장")

    # --- 출력 ---
    ap.add_argument("--debug-img", action="store_true",
                    help="전송한 검출을 그린 슬라이스를 out-dir 에 덮어쓰며 저장")
    ap.add_argument("--save-slice", action="store_true",
                    help="검출에 쓴 슬라이스 원본을 타임스탬프 이름으로 백업 저장")
    ap.add_argument("--slice-dir", default=DEF_SLICE_DIR,
                    help="--save-slice 저장 위치")

    # --- 모드 ---
    ap.add_argument("--once", action="store_true",
                    help="현재 최신 사진 1장만 처리하고 종료")
    ap.add_argument("--replay", default=None,
                    help="지정한 equirect.jpg 1장만 처리하고 종료 (카메라 없이 테스트)")
    args = ap.parse_args()

    if args.pitch is None:
        args.pitch = args.v

    # 경로를 먼저 절대경로로 고정한 뒤 chdir (CLIP 캐시가 CWD/weights/clip 이라)
    for k in ("watch_dir", "cfg", "out_dir", "slice_dir", "weight", "replay"):
        v = getattr(args, k)
        if v:
            setattr(args, k, os.path.abspath(os.path.expanduser(v)))
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    signal.signal(signal.SIGINT, _on_sigint)

    print("=" * 62)
    print("anchor360_live — 360° 실시간 장애물 파이프라인")
    print(f"  슬라이스   : u={args.u:+.1f}deg, v={args.v:+.1f}deg, "
          f"{args.slice_size}x{args.slice_size}")
    print(f"  카메라     : 높이 {args.cam_h}m, 하향 {args.pitch}deg")
    print(f"  Unity      : UDP {args.unity_ip}:{args.port}")
    print(f"  필터       : 접지잘림제외={'ON' if args.drop_clipped else 'off'}, "
          f"최대거리={f'{args.max_dist:g}m' if args.max_dist else '제한없음'}")
    print(f"  감시 대상  : {args.watch_dir}")
    print(f"  출력       : {args.out_dir}")
    if args.save_slice:
        print(f"  슬라이스백업: {args.slice_dir}")
    print(f"  작업 디렉터리: {script_dir}  (CLIP 캐시 기준)")
    print("=" * 62)

    cfg = Config(args.cfg, args.weight)
    print(f"[live] config : {cfg.path}")
    print(f"[live] weight : {cfg.weight}")
    print(f"[live] classes: {len(cfg.classes)}개, conf={cfg.conf}, iou={cfg.iou}")

    det = Detector(cfg, args.imgsz)
    warm_s = det.warmup(args.slice_size)
    print(f"[live] 모델 로드 {det.load_s:.2f}s + 워밍업 {warm_s:.2f}s — 상주 완료\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 0

    try:
        # --- 단발 모드 ---
        if args.replay:
            seq += 1
            process_one(args.replay, det, sock, args, seq)
            return
        if args.once:
            latest = find_latest(args.watch_dir)
            if latest is None:
                print(f"[live] {args.watch_dir} 에 equirect.jpg 가 없습니다.")
                return
            seq += 1
            process_one(latest[0], det, sock, args, seq)
            return

        # --- 감시 모드 ---
        last_key = None
        latest = find_latest(args.watch_dir)
        if latest:
            last_key = (latest[0], latest[1])
            print(f"[live] 기존 최신 사진은 건너뜁니다: "
                  f"{os.path.basename(os.path.dirname(latest[0]))}")
        print("[live] 새 사진 대기 중... (Ctrl+C 로 종료)\n")

        while _running:
            latest = find_latest(args.watch_dir)
            if latest is not None:
                key = (latest[0], latest[1])
                if key != last_key:
                    if args.no_wait_stable or wait_stable(latest[0]):
                        seq += 1
                        process_one(latest[0], det, sock, args, seq)
                        last_key = key
                    else:
                        print("[live] 파일이 아직 쓰이는 중, 다음 주기에 재시도")
            time.sleep(args.poll)
    finally:
        sock.close()
        print(f"\n[live] 종료. 처리한 사진 {seq}장.")


if __name__ == "__main__":
    main()
