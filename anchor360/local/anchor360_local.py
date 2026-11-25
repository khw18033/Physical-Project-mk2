"""
anchor360_local.py — 360° 카메라 → 검출 → Unity 를 이 PC 한 대에서 끝내는 판

[무엇을 대체하나]
  기존 : [PC] stream_to_server → [서버] pano_receiver → anchor360_live
         → [PC] anchor360_bridge → [Unity]                       (터미널 4개, 서버 필요)
  이것 : [PC] RTMP 프레임 → 슬라이스 → YOLOWorld → UDP 127.0.0.1:5010 → [Unity]
                                                                  (터미널 1개, 서버 불필요)

[전방위]
  기본값 --slices 8 : 기준 슬라이스(--u)부터 45도 간격 8장을 한 번에 추론하고,
  기준 슬라이스 좌표계로 돌려 합친 뒤 겹쳐 잡힌 것을 하나로 줄여 보낸다.
  좌표계가 기준 슬라이스 것 그대로라 Unity 의 yawOffsetDeg 는 1장일 때와 같은 값을 쓴다.
  --slices 1 이면 예전처럼 기준 슬라이스 한 장만 본다.

  카메라 제어/프레임 수신은 stream_to_server.py, 슬라이스·검출·바닥투영·패킷은
  anchor360_live.py 의 함수를 그대로 불러 쓴다(수식·스키마 무변경).
  JPEG 인코딩·업로드·서버 폴링·브릿지 폴링 구간이 통째로 없어진다.

[전제]
  - Farsight 수신기가 이 PC 에 LAN 으로 연결돼 있고 카메라가 192.168.100.124 로 보일 것
  - D:\\capstone\\venv (ultralytics, torch+cuda, py360convert)
  - D:\\capstone\\unidepth_duel_yolo_config.yaml, yolov8s-world.pt, weights\\clip\\ViT-B-32.pt
  - Unity: Go1_Unity / lab 씬의 Anchor360 (Anchor360ObstacleReceiver, UDP 5010) — 무수정

[실행]
  D:\\capstone\\venv\\Scripts\\python.exe anchor360_local.py
  D:\\capstone\\venv\\Scripts\\python.exe anchor360_local.py --seconds 20     # 20초만 (시험용)
  D:\\capstone\\venv\\Scripts\\python.exe anchor360_local.py --u 50           # 오른쪽 복도 슬라이스

[종료]
  Ctrl+C  → _stopPreview 후 통계 출력
  ※ 카메라 제어 세션은 하나뿐이다. Insta360 앱 / stream_to_server / preview_probe 와 동시 실행 불가.
"""

import os
import sys
import json
import math
import time
import socket
import signal
import argparse
import threading
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cv2
import numpy as np
import yaml

import stream_to_server as sts      # 카메라 제어 + 최신 프레임 리더
import anchor360_live as live       # 슬라이스 · 검출 · 바닥투영 · 패킷
import anchor360_pose as apose      # 수평 · 방위 자동 맞춤

DEF_CFG = r"D:\capstone\unidepth_duel_yolo_config.yaml"
DEF_CLIP_CWD = r"D:\capstone"       # CLIP 캐시가 CWD/weights/clip 기준
DEF_OUT_DIR = os.path.join(HERE, "live_out")
DEF_CALIB = "D:/Go1_Unity/Assets/StreamingAssets/anchor360_calib.json"
DEF_POSE_REF = os.path.join(HERE, "anchor360_pose_ref.npz")   # 자세 기준(보정 때의 영상에서 만든 것)

_running = True
REFINED_KEYS = ("pos3d", "dist_m", "size", "oriented", "pos_src", "base_h", "elevated")
WIN = "anchor360 detections"


class LocalConfig:
    """live.Config 와 같은 속성. yaml 을 UTF-8 로 읽는 것만 다르다(윈도우 기본 cp949 회피)."""

    def __init__(self, cfg_path, weight_override=None):
        with open(cfg_path, encoding="utf-8") as f:
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
# 전방위(360°) — 여러 슬라이스를 한 좌표계로 합친다
# =========================================================
class MultiSlicer:
    """
    py360convert.e2p 와 같은 샘플러(같은 맵)를 쓰되, 패딩을 프레임당 1회만 한다.
    e2p 는 호출마다 3840x1920 을 채널별로 패딩해서 슬라이스 8장이면 그것만 0.5초다.
    결과 픽셀은 live.slice_equirect 와 동일하다(--selftest 로 확인).
    """

    def __init__(self, u_list, v_deg, size):
        self.u_list, self.v_deg, self.size = list(u_list), v_deg, size
        self._samplers = None
        self._hw = None
        self.R = None          # 보정 좌표계 회전(b_보정 = R b_원본). None 이면 원본 그대로
        self._maps = None

    def set_rotation(self, R):
        """수평·방위 맞춤 회전을 건다. 이후 슬라이스는 보정 좌표계에서 뽑힌다."""
        maps = None
        if self._hw is not None:
            maps = apose.slice_maps(self.u_list, self.v_deg, 90.0, self.size, R, self._hw[1], self._hw[0])
        self._maps, self.R = maps, R

    def _build(self, h, w):
        from py360convert.utils import EquirecSampler, mode_to_order
        fov = float(np.deg2rad(90.0))
        order = mode_to_order("bilinear")
        self._samplers = [
            EquirecSampler.from_perspective(fov, fov, -float(np.deg2rad(u)),
                                            float(np.deg2rad(self.v_deg)), 0.0,
                                            h, w, self.size, self.size, order)
            for u in self.u_list]
        self._hw = (h, w)

    def __call__(self, equ):
        h, w = equ.shape[:2]
        if self.R is not None:
            maps = self._maps
            if maps is None or self._hw != (h, w):
                maps = apose.slice_maps(self.u_list, self.v_deg, 90.0, self.size, self.R, w, h)
                self._maps, self._hw = maps, (h, w)
            return [np.ascontiguousarray(cv2.remap(equ, m1, m2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP))
                    for m1, m2 in maps]
        if self._hw != (h, w):
            self._build(h, w)
        # EquirecSampler._pad 와 같은 1픽셀 패딩을 3채널 한 번에 (극점 행은 반바퀴 굴리고, 좌우는 이어붙임)
        padded = np.empty((h + 2, w + 2, equ.shape[2]), dtype=equ.dtype)
        padded[1:-1, 1:-1] = equ
        padded[0, 1:-1] = np.roll(equ[0], w // 2, axis=0)
        padded[-1, 1:-1] = np.roll(equ[-1], w // 2, axis=0)
        padded[:, 0] = padded[:, -2]
        padded[:, -1] = padded[:, 1]
        return [np.ascontiguousarray(
                    cv2.remap(padded, s._coor_x, s._coor_y, interpolation=s._order))
                for s in self._samplers]


def detect_batch(det, images):
    """live.Detector.detect 와 같은 필터를 슬라이스 여러 장에 한 번의 추론으로 적용."""
    cfg = det.cfg
    results = det.model.predict(images, conf=cfg.conf, imgsz=det.imgsz, verbose=False)
    out = []
    for res in results:
        raw = []
        if res.boxes is not None:
            for b in res.boxes:
                cid = int(b.cls[0])
                name = cfg.classes[cid] if cid < len(cfg.classes) else "cls%d" % cid
                conf = float(b.conf[0])
                if conf < cfg.min_conf(name):
                    continue
                grp = cfg.group.get(name, "UNKNOWN_OBSTACLE")
                if grp not in live.KEEP_GROUPS:
                    continue
                raw.append({"name": name, "group": grp, "conf": conf,
                            "bbox": [float(v) for v in b.xyxy[0]]})
        out.append(live.Detector._nms(raw, cfg.iou))
    return out


_FAMILIES = [
    {"box", "cardboard box", "carton", "package", "parcel", "shipping box", "open box", "storage box"},
    {"person", "pedestrian", "child"},
    {"robot", "quadruped robot", "robot dog"},
    {"table", "bench"},
]


def _family(name):
    """같은 물체가 슬라이스마다 다른 이름으로 잡히는 묶음(box ↔ storage box 등)."""
    for i, fam in enumerate(_FAMILIES):
        if name in fam:
            return i
    return name


def merge_slices(per_slice, u_list, u_ref, size):
    """
    슬라이스별 검출(슬라이스 로컬 좌표)을 기준 슬라이스(u_ref) 좌표계로 돌려 합친다.

    u 가 커질수록 오른쪽(위에서 보면 시계방향)을 본다. 기준보다 Δ 만큼 오른쪽을 보는
    슬라이스의 로컬 (x, z) 는 기준 좌표계에서
        X =  x·cosΔ + z·sinΔ
        Z = -x·sinΔ + z·cosΔ
    (Unity 의 Quaternion.Euler(0, Δ, 0) 과 같은 회전). 기준 슬라이스 좌표계를 그대로
    쓰므로 Unity 의 yawOffsetDeg 는 슬라이스 1장 때와 같은 값이면 된다.

    같은 물체가 겹치는 슬라이스에서 두 번 잡히므로 방위·거리가 가까운 것은 하나만 남긴다.
    좌우가 슬라이스 경계에 잘린 검출은 접지점이 밀리므로, 안 잘린 검출이 근처에 있으면 버린다.
    """
    cands = []
    for dets, u in zip(per_slice, u_list):
        d_rad = math.radians(u - u_ref)
        c, s = math.cos(d_rad), math.sin(d_rad)
        for d in dets:
            x, z = d["pos3d"]["x"], d["pos3d"]["z"]
            X, Z = x * c + z * s, -x * s + z * c
            x1, _, x2, _ = d["bbox_xyxy"]
            d = dict(d)
            d["pos3d"] = {"x": round(X, 3), "y": 0.0, "z": round(Z, 3)}
            if d.get("oriented"):
                d["yaw_deg"] = round((d["yaw_deg"] + (u - u_ref) + 180.0) % 360.0 - 180.0, 1)
            d["slice_u"] = round(u % 360.0, 1)
            d["edge_cut"] = bool(x1 <= 2 or x2 >= size - 2)
            d["_bearing"] = math.degrees(math.atan2(X, Z))
            cands.append(d)

    cands.sort(key=lambda d: (d["edge_cut"], -d["conf"]))   # 안 잘린 것 · conf 높은 것 먼저
    kept = []
    for d in cands:
        dup = False
        for k in kept:
            if d["slice_u"] == k["slice_u"]:
                continue                # 같은 슬라이스 안은 이미 NMS 를 거쳤다
            gap = math.hypot(d["pos3d"]["x"] - k["pos3d"]["x"], d["pos3d"]["z"] - k["pos3d"]["z"])
            if _family(d["name"]) == _family(k["name"]):
                # 슬라이스마다 원근 왜곡이 달라 접지점이 물체 폭의 절반쯤 어긋난다
                tol = min(1.0, max(0.5, 0.5 * max(d["size"]["w"], k["size"]["w"])))
            else:
                tol = 0.25
            if d["edge_cut"]:
                tol = max(tol, min(1.5, k["size"]["w"]))
            if gap < tol:
                dup = True
                break
        if not dup:
            kept.append(d)

    kept.sort(key=lambda d: d["_bearing"])
    for i, d in enumerate(kept, 1):
        d["id"] = i
        del d["_bearing"]
    return kept, len(cands) - len(kept)


def draw_overview(slices, per_slice, u_list, out_path=None, cell=360):
    """슬라이스 전부를 한 장에 타일로 붙인다(검출 박스 포함). out_path 를 주면 저장도 한다."""
    tiles = []
    for sl, dets, u in zip(slices, per_slice, u_list):
        img = sl.copy()
        for d in dets:
            x1, y1, x2, y2 = d["bbox_xyxy"]
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.circle(img, ((x1 + x2) // 2, y2), 5, (0, 0, 255), -1)
            cv2.putText(img, "%s %.2f D=%.2f" % (d["name"], d["conf"], d["dist_m"]),
                        (x1, max(y1 - 5, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(img, "u=%g" % (u % 360), (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        tiles.append(cv2.resize(img, (cell, cell)))
    cols = 4 if len(tiles) > 4 else len(tiles)
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    view = np.vstack(rows)
    if out_path:
        cv2.imwrite(out_path, view)
    return view


# =========================================================
# 깊이 모델로 위치·크기 다듬기
# =========================================================
class DepthRefiner:
    """
    바닥 투영만으로는 "검출 박스 아랫변 가운데 = 물체가 바닥에 닿는 가장 가까운 점" 하나만 알 수 있다.
    그래서 큐브가 물체 중심이 아니라 카메라 쪽 모서리에 놓이고, 크기도 정사각형 추정이며,
    책상 위 물건은 엉뚱하게 먼 바닥에 찍힌다.

    UniDepth(단안 미터 깊이)로 슬라이스의 픽셀마다 3D 점을 얻어, 박스 안 물체 점들의
    바닥면 분포에서 중심·가로·세로·방향·높이를 직접 구한다.
      - 깊이의 절대 배율은 슬라이스마다 ±10% 흔들리므로, 바닥으로 보이는 픽셀에서
        "바닥 기하 깊이 / 모델 깊이" 중앙값으로 슬라이스별 배율을 맞춘다(기존 보정과 같은 기준).
      - 물체 바닥 높이가 base_max 보다 높으면(가구 위 물건) elevated 로 표시한다.
    """

    def __init__(self, model_dir, repo_dir, size, cam_h, pitch_deg, level=0):
        sys.path.insert(0, repo_dir)
        import torch
        from unidepth.models import UniDepthV2
        self.torch = torch
        t0 = time.perf_counter()
        self.model = UniDepthV2.from_pretrained(model_dir).to("cuda").eval()
        self.model.resolution_level = level
        self.model.interpolation_mode = "bilinear"
        f = c = size / 2.0
        self.K = torch.tensor([[f, 0, c], [0, f, c], [0, 0, 1]], dtype=torch.float32)
        self.size, self.cam_h, self.f = size, cam_h, f

        th = math.radians(pitch_deg)
        ct, st = math.cos(th), math.sin(th)
        px, py = np.meshgrid(np.arange(size, dtype=np.float32), np.arange(size, dtype=np.float32))
        dx, dyu = (px - c) / f, -(py - c) / f
        self.DX = dx                               # 오른쪽 = z·DX
        self.UP = ct * dyu + st                    # 위     = z·UP   (카메라 기준, 아래가 음수)
        self.FW = -st * dyu + ct                   # 정면   = z·FW
        with np.errstate(divide="ignore"):
            self.ZFLOOR = np.where(self.UP < -0.05, -cam_h / self.UP, np.inf)
        self.infer(np.zeros((size, size, 3), np.uint8))      # 워밍업
        self.load_s = time.perf_counter() - t0

    def infer(self, bgr):
        """슬라이스 1장 → z 깊이(H,W), 바닥 기준으로 배율을 맞춘 것. (배율도 함께 반환)"""
        torch = self.torch
        t = torch.from_numpy(np.ascontiguousarray(bgr[..., ::-1])).permute(2, 0, 1).to("cuda")
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
            out = self.model.infer(t, camera=self.K)
        z = out["points"][0, 2].float().cpu().numpy()

        h = self.cam_h + z * self.UP
        floor = (np.abs(h) < 0.25) & (self.UP < -0.2) & (z > 0.3)
        k = 1.0
        if floor.sum() > 3000:
            k = float(np.median(self.ZFLOOR[floor] / z[floor]))
            k = min(1.25, max(0.8, k))
        return z * k, k

    def refine(self, det, z, mask=None, room_yaw_deg=0.0, base_max=0.3):
        """
        det(슬라이스 로컬, build_packet 형식)를 깊이로 다듬는다. 성공하면 det 를 고쳐 쓰고 True.

        mask        : 이 물체의 분할 마스크(H,W bool). 있으면 박스 대신 마스크 안 픽셀만 쓴다.
                      박스에는 뒤 배경·옆 물체가 섞여 크기가 부풀기 때문.
        room_yaw_deg: 슬라이스 로컬 → 방(Unity) 축으로 가는 회전각. 크기를 방의 가로·세로 축에
                      맞춰 재서, Unity 에서 회전 없는 상자로 놓을 수 있게 한다.
        """
        x1, y1, x2, y2 = det["bbox_xyxy"]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(self.size, x2), min(self.size, y2)
        if x2 - x1 < 6 or y2 - y1 < 6:
            return False
        zb = z[y1:y2, x1:x2]
        hb = self.cam_h + zb * self.UP[y1:y2, x1:x2]
        obj = (hb > 0.06) & (hb < 2.3) & (zb > 0.2)

        # 마스크가 박스의 30%도 못 채우면 물체 일부만 딴 것(위에 물건이 쌓인 탁자 등) → 박스 기준으로
        if mask is not None and mask[y1:y2, x1:x2].sum() < 0.3 * (x2 - x1) * (y2 - y1):
            mask = None

        if mask is not None:
            mb = mask[y1:y2, x1:x2].astype(np.uint8)
            # 윤곽 픽셀은 앞·뒤 깊이가 섞여 튄다 → 마스크를 조금 깎아 쓴다
            er = cv2.erode(mb, np.ones((5, 5), np.uint8))
            if er.sum() >= 60:
                mb = er
            obj &= mb.astype(bool)
            if obj.sum() < 40:
                return False
            z_med = float(np.median(zb[obj]))
        else:
            if obj.sum() < 40:
                return False
            # 박스 안쪽(가장자리 20% 제외)의 물체 픽셀 깊이 중앙값
            iy, ix = max(1, (y2 - y1) // 5), max(1, (x2 - x1) // 5)
            zi = zb[iy:-iy, ix:-ix][obj[iy:-iy, ix:-ix]]
            if zi.size < 20:
                return False
            z_med = float(np.median(zi))

        # 깊이 중앙값 ± 띠 = 이 물체. 뒤 배경·앞 가림을 뺀다
        sel = obj & (np.abs(zb - z_med) <= max(0.35, 0.25 * z_med))
        if sel.sum() < 40:
            return False

        # ── 접지선으로 거리 고정 ──
        # 물체 윤곽의 맨 아래 픽셀이 바닥에 닿은 곳이면, 그 지점의 거리는 깊이 모델이 아니라
        # 바닥 기하(카메라 높이·각도)로 정확히 알 수 있다. 그 비율로 이 물체의 깊이 전체를 맞춘다.
        k_obj = self._contact_scale(mask, zb, hb, x1, y1, x2, y2)
        if k_obj is not None:
            zb = zb * k_obj
            hb = self.cam_h + zb * self.UP[y1:y2, x1:x2]

        X = (zb * self.DX[y1:y2, x1:x2])[sel]
        Z = (zb * self.FW[y1:y2, x1:x2])[sel]
        H = hb[sel]

        # 방 축으로 돌려서 가로(X)·세로(Z) 범위를 잰다. 양끝 5%는 튄 점으로 보고 버린다
        a = math.radians(room_yaw_deg)
        c, s = math.cos(a), math.sin(a)
        RX, RZ = X * c + Z * s, -X * s + Z * c
        lo_x, hi_x = np.percentile(RX, [5, 95])
        lo_z, hi_z = np.percentile(RZ, [5, 95])
        cx_r, cz_r = (lo_x + hi_x) / 2.0, (lo_z + hi_z) / 2.0
        cx, cz = cx_r * c - cz_r * s, cx_r * s + cz_r * c          # 슬라이스 로컬로 되돌림

        base, top = float(np.percentile(H, 4)), float(np.percentile(H, 96))
        det["pos3d"] = {"x": round(float(cx), 3), "y": 0.0, "z": round(float(cz), 3)}
        det["dist_m"] = round(math.hypot(cx, cz), 3)
        det["size"] = {"w": round(max(float(hi_x - lo_x), 0.1), 3), "h": round(max(top, 0.1), 3),
                       "d": round(max(float(hi_z - lo_z), 0.1), 3)}
        det["oriented"] = False                    # 크기가 방 축 기준이므로 회전 없이 놓는다
        det["pos_src"] = ("depth+contact" if k_obj is not None
                          else "depth+mask" if mask is not None else "depth")
        det["base_h"] = round(base, 2)
        det["elevated"] = bool(base > base_max)
        return True


    def _contact_scale(self, mask, zb, hb, x1, y1, x2, y2):
        """
        접지 픽셀에서 (바닥 기하 깊이 / 모델 깊이) 의 중앙값. 접지를 못 믿으면 None.

        열마다 윤곽 맨 아래 픽셀을 접지 후보로 본다(마스크가 없으면 박스 아랫변 가운데 절반).
        그 바로 위(4픽셀) 물체 픽셀의 높이가 0.2m 보다 높으면 접지가 아니라
        공중에 뜬 모서리(탁자 상판 앞변 등)나 가려진 아랫부분이므로 뺀다.
        """
        hh, ww = zb.shape
        if hh < 12 or ww < 6:
            return None
        cols = np.arange(ww)
        if mask is not None:
            full = mask[y1:y2, x1:x2]
            ok = full.sum(axis=0) >= 6
            yb = hh - 1 - np.argmax(full[::-1], axis=0)
        else:
            ok = (cols >= ww // 4) & (cols < ww - ww // 4)
            yb = np.full(ww, hh - 1)
        ya = yb - 4
        gy = y1 + yb + 1                                     # 윤곽 바로 아래 = 바닥
        ok &= (ya >= 0) & (gy < self.size - 2)               # 슬라이스 밑변에 잘린 것은 접지를 모른다
        if ok.sum() < 4:
            return None
        c = cols[ok]
        zm = zb[ya[ok], c]
        hm = hb[ya[ok], c]
        zf = self.ZFLOOR[gy[ok], x1 + c]
        good = (hm < 0.2) & (zm > 0.2) & np.isfinite(zf)
        if good.sum() < max(4, 0.2 * ok.sum()):
            return None
        k = float(np.median(zf[good] / zm[good]))
        return min(1.25, max(0.8, k))


class Segmenter:
    """검출 박스를 실마리로 물체 윤곽(마스크)을 딴다 — MobileSAM."""

    def __init__(self, weight, size, imgsz=512):
        from ultralytics import SAM
        t0 = time.perf_counter()
        self.model = SAM(weight)
        self.size, self.imgsz = size, imgsz
        self(np.zeros((size, size, 3), np.uint8), [[100, 100, 300, 300]])
        self.load_s = time.perf_counter() - t0

    def __call__(self, bgr, boxes):
        """boxes 와 같은 순서의 마스크 배열 (N,H,W) bool. 실패하면 None."""
        try:
            r = self.model.predict(bgr, bboxes=boxes, imgsz=self.imgsz, verbose=False)[0]
            if r.masks is None:
                return None
            m = r.masks.data
            if m.shape[0] != len(boxes):
                return None
            m = m.cpu().numpy().astype(bool)
            if m.shape[1:] != (self.size, self.size):
                m = np.stack([cv2.resize(x.astype(np.uint8), (self.size, self.size),
                                         interpolation=cv2.INTER_NEAREST).astype(bool) for x in m])
            return m
        except Exception:
            return None


# =========================================================
# 브라우저로 보는 실시간 화면 (MJPEG)
# =========================================================
class MjpegServer:
    """
    http://<이 PC>:<port>/ 를 열면 검출 화면이 계속 갱신된다. 별도 프로그램 불필요.
    보는 사람이 없으면 JPEG 인코딩도 하지 않는다(has_viewers).
    """

    PAGE = (b"<!doctype html><html><head><meta charset='utf-8'>"
            b"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            b"<title>anchor360</title><style>html,body{margin:0;background:#111}"
            b"img{display:block;width:100%;height:auto}</style></head>"
            b"<body><img src='/stream.mjpg'></body></html>")

    def __init__(self, host, port):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.cond = threading.Condition()
        self.jpeg = None
        self.seq = 0
        self.viewers = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(outer.PAGE)))
                    self.end_headers()
                    self.wfile.write(outer.PAGE)
                elif path == "/snapshot.jpg":
                    with outer.cond:
                        outer.viewers += 1
                        try:
                            if outer.jpeg is None:
                                outer.cond.wait(timeout=5)
                            data = outer.jpeg
                        finally:
                            outer.viewers -= 1
                    if data is None:
                        self.send_error(503)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                elif path == "/stream.mjpg":
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    with outer.cond:
                        outer.viewers += 1
                    last = -1
                    try:
                        while True:
                            with outer.cond:
                                while outer.seq == last:
                                    if not outer.cond.wait(timeout=10):
                                        return
                                last, data = outer.seq, outer.jpeg
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                             + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                    except (BrokenPipeError, ConnectionError, OSError):
                        pass
                    finally:
                        with outer.cond:
                            outer.viewers -= 1
                else:
                    self.send_error(404)

        self.httpd = ThreadingHTTPServer((host, port), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def has_viewers(self):
        return self.viewers > 0

    def publish(self, bgr, quality=70):
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return
        with self.cond:
            self.jpeg = buf.tobytes()
            self.seq += 1
            self.cond.notify_all()

    def close(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass


def blend_fields(old, new, n, max_jump=0.5):
    """
    전에 잰 값(old)과 방금 잰 값(new)의 이동 평균. new 의 비중은 1/n.
    위치가 max_jump(m) 넘게 달라졌으면 None(평균하지 않음).
    """
    jump = math.hypot(new["pos3d"]["x"] - old["pos3d"]["x"], new["pos3d"]["z"] - old["pos3d"]["z"])
    if jump > max_jump:
        return None
    w = 1.0 / n
    mix = lambda a, b: round(a + (b - a) * w, 3)
    out = dict(new)
    out["pos3d"] = {"x": mix(old["pos3d"]["x"], new["pos3d"]["x"]), "y": 0.0,
                    "z": mix(old["pos3d"]["z"], new["pos3d"]["z"])}
    out["size"] = {k: mix(old["size"][k], new["size"][k]) for k in ("w", "h", "d")}
    out["dist_m"] = round(math.hypot(out["pos3d"]["x"], out["pos3d"]["z"]), 3)
    out["base_h"] = round(old["base_h"] + (new["base_h"] - old["base_h"]) * w, 2)
    out["elevated"] = bool(out["base_h"] > 0.3)
    # 접지로 맞춘 적이 있으면 그 표시를 유지한다
    if "contact" in str(old.get("pos_src", "")):
        out["pos_src"] = old["pos_src"]
    return out


def write_atomic(path, text):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main():
    global _running

    ap = argparse.ArgumentParser(description="Pro2 실시간 스트림 → 로컬 검출 → Unity UDP")
    ap.add_argument("--ip", default=sts.DEF_IP, help="카메라 IP")
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--bitrate", type=int, default=10240)
    ap.add_argument("--url", default=None, help="스트림 주소 직접 지정")

    ap.add_argument("--cfg", default=DEF_CFG)
    ap.add_argument("--weight", default=None)
    ap.add_argument("--imgsz", type=int, default=live.DEF_IMGSZ)

    # 영상(인카메라 스티칭) 경로 확정값 — 260921 총정리 v2 §4.2, §4.3
    ap.add_argument("--u", type=float, default=230.0,
                    help="기준 슬라이스 방위각(좌표계의 +z 방향). 왼쪽 230 / 중앙 330 / 오른쪽 50")
    ap.add_argument("--slices", type=int, default=8,
                    help="전방위를 몇 장으로 나눠 볼지. 8=45도 간격(권장), 1=기준 슬라이스 한 장만")
    ap.add_argument("--v", type=float, default=-36.35, help="슬라이스 고저각")
    ap.add_argument("--pitch", type=float, default=None,
                    help="바닥평면 계산용 하향각. 기본: 자세 맞춤을 쓰면 --v 와 같은 값, 안 쓰면 -35")
    ap.add_argument("--cam-h", type=float, default=None,
                    help="카메라 렌즈 높이(m). 기본: 보정 파일의 camH, 없으면 %.2f" % live.DEF_CAM_H)
    ap.add_argument("--stab", action="store_true",
                    help="카메라 손떨림 보정을 켠다. 켜면 접속할 때마다 기준 방위가 바뀐다(기본: 끔)")
    ap.add_argument("--no-level", action="store_true", help="수평·방위 자동 맞춤을 쓰지 않는다")
    ap.add_argument("--groups", default="HARD_OBSTACLE,AGENT,SOFT_PUSHABLE,LOW_OBSTACLE,THIN_OBSTACLE,GROUND_HAZARD,VEHICLE",
                    help="보낼 물체 그룹(쉼표 구분). 예전 동작은 HARD_OBSTACLE,AGENT")
    ap.add_argument("--pose-ref", default=DEF_POSE_REF, help="자세 기준 파일(.npz)")
    ap.add_argument("--pose-every", type=float, default=600.0, help="자세를 다시 확인하는 간격(초). 0=시작할 때만")
    ap.add_argument("--slice-size", type=int, default=720)
    ap.add_argument("--max-dist", type=float, default=8.0, help="이 거리 초과 검출 제외. 0=제한없음")
    ap.add_argument("--keep-clipped", action="store_true", help="접지점이 잘린 검출도 보낸다")

    ap.add_argument("--no-depth", action="store_true",
                    help="깊이 모델을 끄고 예전처럼 바닥 투영만 쓴다(빠르지만 위치가 물체 앞모서리 기준)")
    ap.add_argument("--depth-model", default=r"D:\capstone\unidepth-v2-vitb14")
    ap.add_argument("--depth-repo", default=r"D:\capstone\UniDepth")
    ap.add_argument("--depth-level", type=int, default=0,
                    help="UniDepth 입력 해상도 단계 0(빠름)~9(정밀)")
    ap.add_argument("--no-mask", action="store_true",
                    help="분할 모델을 끄고 검출 박스 안 전체로 크기를 잰다(빠르지만 크기가 부푼다)")
    ap.add_argument("--sam-weight", default="mobile_sam.pt")
    ap.add_argument("--calib", default=DEF_CALIB,
                    help="Unity 보정 파일. yawOffsetDeg 를 읽어 크기를 방 축에 맞춰 잰다")
    ap.add_argument("--room-yaw", type=float, default=None,
                    help="기준 슬라이스 → 방 축 회전각(도). 주면 보정 파일 대신 이 값을 쓴다")
    ap.add_argument("--cache-iou", type=float, default=0.8,
                    help="검출 박스가 직전 것과 이만큼 겹치면 같은 물체로 보고 위치·크기를 재사용")
    ap.add_argument("--cache-refresh", type=float, default=30.0,
                    help="재사용한 결과도 이 시간(초)마다 다시 계산. 0=재사용 끔(매 프레임 전부 계산)")
    ap.add_argument("--cache-keep", type=float, default=60.0,
                    help="안 보이게 된 물체의 결과를 이 시간(초) 동안 기억(깜빡이는 검출 대비)")
    ap.add_argument("--avg-n", type=int, default=6,
                    help="정지 물체의 위치·크기를 최근 N번 잰 값으로 평균. 1=평균 안 함")
    ap.add_argument("--keep-elevated", action="store_true",
                    help="가구 위에 놓인 물체(바닥에서 0.3m 이상 떠 있음)도 보낸다")

    ap.add_argument("--unity-ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=live.DEF_PORT)
    ap.add_argument("--fps", type=float, default=3.0,
                    help="Unity 송출 목표 fps. 수신기가 스냅샷 방식이라 4 이상이면 큐브가 깜빡인다")

    ap.add_argument("--out-dir", default=DEF_OUT_DIR)
    ap.add_argument("--debug-every", type=int, default=5,
                    help="N프레임마다 검출 그린 슬라이스를 out-dir 에 덮어쓴다. 0=끔")
    ap.add_argument("--seconds", type=float, default=0, help="N초 돌리고 종료 (0=무한)")
    ap.add_argument("--quiet", action="store_true", help="프레임별 검출 목록을 찍지 않는다")
    ap.add_argument("--show", action="store_true",
                    help="검출 박스를 그린 8방향 화면을 창으로 실시간 표시 (창에서 q = 종료)")
    ap.add_argument("--show-cell", type=int, default=420, help="화면 타일 한 변 픽셀")
    ap.add_argument("--http-port", type=int, default=8090,
                    help="브라우저로 검출 화면을 보는 포트. 0=끔")
    ap.add_argument("--http-host", default="0.0.0.0",
                    help="화면 서버가 받을 주소. 이 PC 에서만 보려면 127.0.0.1")
    ap.add_argument("--selftest", action="store_true",
                    help="첫 프레임에서 빠른 슬라이서를 e2p 와 픽셀 단위로 대조하고 equirect 한 장 저장")
    args = ap.parse_args()

    max_dist = args.max_dist if args.max_dist > 0 else None
    calib_j = {}
    try:
        with open(args.calib, encoding="utf-8") as f:
            calib_j = json.load(f)
    except Exception:
        pass
    level_on = (not args.no_level) and os.path.exists(args.pose_ref)
    if args.pitch is None:
        args.pitch = args.v if level_on else -35.0      # 수평을 맞추면 슬라이스 고저각이 곧 물리 하향각이다
    if args.cam_h is None:
        args.cam_h = float(calib_j.get("camH", live.DEF_CAM_H)) if level_on else live.DEF_CAM_H
    args.stabilization = bool(args.stab)
    live.KEEP_GROUPS = {g.strip() for g in args.groups.split(",") if g.strip()}
    os.makedirs(args.out_dir, exist_ok=True)
    os.chdir(DEF_CLIP_CWD)

    print("=" * 70)
    print("anchor360_local — 카메라 %s → 로컬 검출 → UDP %s:%d" % (args.ip, args.unity_ip, args.port))
    n_sl = max(1, args.slices)
    u_list = [args.u + 360.0 * k / n_sl for k in range(n_sl)]
    slicer = MultiSlicer(u_list, args.v, args.slice_size)
    print("  슬라이스 : 기준 u=%+.1f 부터 %d장(%g도 간격) v=%+.2f %dx%d | 카메라 높이 %.2fm 하향 %.1f"
          % (args.u, n_sl, 360.0 / n_sl, args.v, args.slice_size, args.slice_size,
             args.cam_h, args.pitch))
    print("  필터     : 접지잘림제외=%s 최대거리=%s | 목표 %.1f fps"
          % ("off" if args.keep_clipped else "ON", ("%gm" % max_dist) if max_dist else "제한없음", args.fps))
    print("=" * 70)

    # ── 모델 (카메라 세션을 쥐기 전에 올린다: 로드가 느려도 세션이 안 죽게) ──
    cfg = LocalConfig(args.cfg, args.weight)
    det = live.Detector(cfg, args.imgsz)
    warm = det.warmup(args.slice_size)
    print("[모델] %s  classes %d개  로드 %.1fs + 워밍업 %.1fs"
          % (os.path.basename(cfg.weight), len(cfg.classes), det.load_s, warm))
    proj = live.GroundProjector(args.slice_size, args.slice_size, args.cam_h, args.pitch)

    refiner = None
    if not args.no_depth:
        try:
            refiner = DepthRefiner(args.depth_model, args.depth_repo, args.slice_size,
                                   args.cam_h, args.pitch, args.depth_level)
            print("[깊이] UniDepthV2 로드 %.1fs — 위치·크기를 깊이로 다듬습니다 (끄려면 --no-depth)"
                  % refiner.load_s)
        except Exception as e:
            print("[깊이] 로드 실패(%s) — 바닥 투영만으로 계속합니다." % e)

    segmenter = None
    if refiner is not None and not args.no_mask:
        try:
            segmenter = Segmenter(args.sam_weight, args.slice_size)
            print("[분할] %s 로드 %.1fs — 물체 윤곽 안의 점만으로 크기를 잽니다 (끄려면 --no-mask)"
                  % (args.sam_weight, segmenter.load_s))
        except Exception as e:
            print("[분할] 로드 실패(%s) — 박스 기준으로 계속합니다." % e)

    if args.room_yaw is None:
        args.room_yaw = 0.0
        try:
            with open(args.calib, encoding="utf-8") as f:
                args.room_yaw = float(json.load(f).get("yawOffsetDeg", 0.0))
            print("[보정] 방 축 회전 %.1f도 ← %s" % (args.room_yaw, args.calib))
        except Exception as e:
            print("[보정] 보정 파일을 못 읽어 방 축 회전 0도로 둡니다 (%s)" % e)

    # ── 카메라 ──
    sts.CMD_URL = "http://%s:20000/osc/commands/execute" % args.ip
    sts.STATE_URL = "http://%s:20000/osc/state" % args.ip
    if not sts.connect():
        sys.exit(1)
    sts.hb_stop.clear()
    threading.Thread(target=sts.heartbeat, daemon=True).start()
    time.sleep(0.5)

    url = args.url or sts.start_preview(args)
    if not url:
        sts.hb_stop.set()
        sys.exit(2)

    t_open = time.time()
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print("[스트림] 열기 실패: %s" % url)
        sts.send("camera._stopPreview", {})
        sts.hb_stop.set()
        sys.exit(3)
    print("[스트림] 열림 %.2fs" % (time.time() - t_open))

    latest = sts.Latest()
    stop = threading.Event()
    rstat = {"read_ok": 0, "read_fail": 0}
    th = threading.Thread(target=sts.reader, args=(cap, latest, stop, rstat), daemon=True)
    th.start()

    # ── 자세 맞춤: 수직선으로 수평을, 기준 영상과 겹쳐 방위를 맞춘다 ──
    ref_band = None
    pose_state = {"busy": False, "t": time.time()}

    def pose_update(fr, first=False):
        try:
            R, info = apose.solve_pose(fr, ref_band)
            old = slicer.R
            diff = 999.0 if old is None else math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R @ old.T) - 1) / 2))))
            if first or diff > 0.15:
                slicer.set_rotation(R)
                print("[자세] 기울기 %.2f도  기준 대비 방위 %+.2f도 (겹침 %.2f, 수직선 %d개)%s"
                      % (info["tilt_deg"], info["heading_deg"], info["corr"] or 0, info["lines"][0],
                         "" if first else "  ← %.2f도 달라져 다시 맞춤" % diff))
                if (info["corr"] or 0) < 0.35:
                    print("[자세] ⚠ 기준 영상과 잘 겹치지 않습니다. 카메라 위치를 옮겼다면 보정을 다시 해야 합니다.")
        except Exception as e:
            print("[자세] 맞춤 실패(%s) — 이전 값 유지" % e)
        finally:
            pose_state["busy"] = False
            pose_state["t"] = time.time()

    if level_on:
        ref_band = np.load(args.pose_ref)["band"]
        f0, t_w = None, time.time()
        while f0 is None and time.time() - t_w < 15:
            f0 = latest.frame
            time.sleep(0.05)
        if f0 is None:
            print("[자세] 첫 프레임을 못 받아 맞춤을 건너뜁니다.")
        else:
            pose_update(f0, first=True)
    else:
        print("[자세] 자동 맞춤 안 씀 (기준 파일 없음 또는 --no-level)")

    def bye(sig, frm):
        global _running
        _running = False
    signal.signal(signal.SIGINT, bye)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, bye)

    web = None
    if args.http_port > 0:
        try:
            web = MjpegServer(args.http_host, args.http_port)
            print("[화면] 브라우저에서 http://<이 PC 주소>:%d/  (이 PC 에서는 http://localhost:%d/)"
                  % (args.http_port, args.http_port))
        except OSError as e:
            print("[화면] 포트 %d 열기 실패(%s) — 브라우저 화면 없이 계속합니다." % (args.http_port, e))

    if args.show:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WIN, args.show_cell * min(4, n_sl), args.show_cell * ((n_sl + 3) // 4))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    json_path = os.path.join(args.out_dir, "anchor360_latest.json")
    img_path = os.path.join(args.out_dir, "anchor360_latest.jpg")

    ages, slices, infers, totals = [], [], [], []
    cache = [[] for _ in u_list]        # 슬라이스별 {name, bbox, fields, made, seen}
    n = 0
    n_det_total = 0
    t_start = time.time()
    period = 1.0 / args.fps
    next_t = time.time()
    t_last_frame = time.time()

    while _running and (args.seconds <= 0 or time.time() - t_start < args.seconds):
        now = time.time()
        if now < next_t:
            time.sleep(min(0.005, next_t - now))
            continue
        next_t += period
        if next_t < now:
            next_t = now + period

        frame, t_frame, seq = latest.take()
        if frame is None:
            if now - t_last_frame > 10:
                print("[스트림] 10초간 프레임 없음 — 종료합니다.")
                break
            continue
        t_last_frame = now

        if (level_on and args.pose_every > 0 and not pose_state["busy"]
                and now - pose_state["t"] > args.pose_every):
            pose_state["busy"] = True
            threading.Thread(target=pose_update, args=(frame.copy(),), daemon=True).start()

        t0 = time.perf_counter()
        sls = slicer(frame)
        t1 = time.perf_counter()

        if args.selftest and n == 0:
            # 빠른 슬라이서가 검증된 e2p 경로와 같은 픽셀을 내는지 확인
            worst = 0
            for sl_fast, u in zip(sls, u_list):
                ref = live.slice_equirect(frame, u, args.v, args.slice_size)
                worst = max(worst, int(np.abs(sl_fast.astype(np.int16) - ref.astype(np.int16)).max()))
            print("[selftest] 슬라이스 %d장, e2p 대비 최대 픽셀 차이 = %d (0 이어야 함)" % (n_sl, worst))
            cv2.imwrite(os.path.join(args.out_dir, "equirect_sample.jpg"), frame)
        kept_per = detect_batch(det, sls)
        t2 = time.perf_counter()

        per_slice, dropped = [], []
        n_depth = n_elev = n_reuse = n_run = 0
        now_c = time.time()
        for si, (kept, u, sl) in enumerate(zip(kept_per, u_list, sls)):
            pkt, drp = live.build_packet(kept, proj, u, args.v,
                                         not args.keep_clipped, max_dist)
            dets_s = pkt["detections"]
            if refiner is not None and dets_s:
                # ── 직전 결과 재사용: 카메라가 고정이라 박스가 그대로면 위치·크기도 그대로다 ──
                # 슬라이스마다 수명을 조금씩 달리해 전체가 한 프레임에 몰려 갱신되지 않게 한다
                life = args.cache_refresh * (1.0 + 0.15 * si)
                ents = [e for e in cache[si] if now_c - e["seen"] < args.cache_keep]
                matches, prevs = [], []
                for d in dets_s:
                    best, best_iou = None, 0.0
                    for e in ents:
                        if _family(e["name"]) != _family(d["name"]):
                            continue
                        iou = live.Detector._iou(d["bbox_xyxy"], e["bbox"])
                        if iou > best_iou:
                            best, best_iou = e, iou
                    same = best is not None and best_iou >= args.cache_iou
                    # 처음 본 물체는 1.5초·3초·6초… 간격으로 다시 재서 평균을 빨리 모으고,
                    # 충분히 모이면 --cache-refresh 주기로만 다시 잰다
                    # (슬라이스마다 시차를 둬서 8방향 재측정이 한 프레임에 몰리지 않게 한다)
                    life_e = (min(life, (1.5 + 0.4 * si) * 2 ** (best["obs"] - 1))
                              if same else 0.0)
                    ok = args.cache_refresh > 0 and same and now_c - best["made"] < life_e
                    matches.append(best if ok else None)
                    prevs.append(best if same else None)

                todo = [i for i, m in enumerate(matches) if m is None]
                if todo:
                    # 새로 나타났거나 움직인 물체가 있는 슬라이스만 깊이·분할을 돌린다
                    n_run += 1
                    z, _k = refiner.infer(sl)
                    masks = (segmenter(sl, [dets_s[i]["bbox_xyxy"] for i in todo])
                             if segmenter else None)
                    room_yaw = (u - args.u) + args.room_yaw
                    for j, i in enumerate(todo):
                        d = dets_s[i]
                        bbox = list(d["bbox_xyxy"])
                        fields, obs = None, 1
                        if refiner.refine(d, z, masks[j] if masks is not None else None, room_yaw):
                            n_depth += 1
                            fields = {k: d[k] for k in REFINED_KEYS}
                            # 같은 물체를 전에 잰 값이 있으면 평균한다(한 번 잰 값의 잡음을 줄임).
                            # 0.5m 넘게 달라졌으면 물체가 옮겨진 것이므로 새 값으로 다시 시작한다
                            pv = prevs[i]
                            if args.avg_n > 1 and pv is not None and pv["fields"]:
                                merged_f = blend_fields(pv["fields"], fields,
                                                        min(pv["obs"] + 1, args.avg_n))
                                if merged_f is not None:
                                    fields, obs = merged_f, pv["obs"] + 1
                                    d.update(fields)
                        # 같은 자리의 옛 항목은 새 것으로 바꾼다
                        ents = [e for e in ents
                                if live.Detector._iou(bbox, e["bbox"]) < args.cache_iou
                                or _family(e["name"]) != _family(d["name"])]
                        ents.append({"name": d["name"], "bbox": bbox, "fields": fields,
                                     "made": now_c, "seen": now_c, "obs": obs})
                for d, e in zip(dets_s, matches):
                    if e is not None:
                        n_reuse += 1
                        e["seen"] = now_c
                        if e["fields"]:
                            d.update(e["fields"])
                cache[si] = ents

                out_s = []
                for d in dets_s:
                    if str(d.get("pos_src", "")).startswith("depth"):
                        # 사람은 앉아 있으면 다리가 가려져 '바닥에서 뜬 것'으로 보인다 → 가구위 제외를 적용하지 않는다
                        if d["elevated"] and not args.keep_elevated and d.get("group") != "AGENT":
                            n_elev += 1
                            dropped.append((d, "가구위", d["dist_m"]))
                            continue
                        if max_dist is not None and d["dist_m"] > max_dist:
                            dropped.append((d, ">%gm" % max_dist, d["dist_m"]))
                            continue
                    out_s.append(d)
                dets_s = out_s
            per_slice.append(dets_s)
            dropped += drp
        t2 = time.perf_counter()
        merged, n_dup = merge_slices(per_slice, u_list, args.u, args.slice_size)
        packet = {
            "timestamp": "%.3f" % time.time(),
            "camera_id": "anchor360",
            "frame": "anchor360",
            "anchor_dir": {"u_deg": args.u, "v_deg": args.v, "roll_deg": 0, "slices": n_sl},
            "detections": merged,
        }
        payload = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        sock.sendto(payload.encode("utf-8"), (args.unity_ip, args.port))

        n += 1
        age = now - t_frame
        tot = age + (time.perf_counter() - t0)
        ages.append(age); slices.append(t1 - t0); infers.append(t2 - t1); totals.append(tot)
        dets = packet["detections"]
        n_det_total += len(dets)

        if args.debug_every > 0 and n % args.debug_every == 1:
            write_atomic(json_path, json.dumps(packet, ensure_ascii=False, indent=2))
            draw_overview(sls, per_slice, u_list, img_path)

        web_on = web is not None and web.has_viewers()
        if args.show or web_on:
            view = draw_overview(sls, per_slice, u_list, cell=args.show_cell)
            cv2.putText(view, "%s  sent %d" % (time.strftime("%H:%M:%S"), len(dets)),
                        (10, view.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            if web_on:
                web.publish(view)
            if args.show:
                cv2.imshow(WIN, view)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    _running = False

        print("  #%-4d 나이 %4.0fms  slice %3.0fms  infer %3.0fms  | 지연 %4.0fms  전송 %d개"
              "  (중복 %d, 필터 %d)  깊이 %d장/재사용 %d개"
              % (n, age * 1000, (t1 - t0) * 1000, (t2 - t1) * 1000, tot * 1000, len(dets),
                 n_dup, len(dropped), n_run, n_reuse))
        if not args.quiet:
            for d in dets:
                print("        %-18s pos=(%+.2f, %+.2f) D=%.2f  %.2fx%.2fx%.2f  conf=%.2f  u=%g  %s%s"
                      % (d["name"], d["pos3d"]["x"], d["pos3d"]["z"], d["dist_m"],
                         d["size"]["w"], d["size"]["d"], d["size"]["h"], d["conf"],
                         d["slice_u"], d.get("pos_src", "floor"),
                         " [경계잘림]" if d["edge_cut"] else ""))

    # ── 정리 (stream_to_server 와 같은 순서) ──
    stop.set()
    sts.send("camera._stopPreview", {})
    th.join(timeout=3.0)
    sts.hb_stop.set()
    sock.close()
    if web is not None:
        web.close()
    if args.show:
        cv2.destroyAllWindows()

    el = time.time() - t_start
    print("\n" + "=" * 70)
    print("종료 — %.1f초 동안 %d회 송출 (%.2f Hz), 검출 누적 %d개"
          % (el, n, n / el if el else 0, n_det_total))
    print("  리더 수신 %d프레임 (%.1f fps), read 실패 %d"
          % (rstat["read_ok"], rstat["read_ok"] / el if el else 0, rstat["read_fail"]))
    if totals:
        for name, v in [("프레임 나이", ages), ("슬라이스", slices), ("검출", infers), ("PC 구간 합계", totals)]:
            s = sorted(v)
            print("  %-12s 중앙 %5.0fms   p90 %5.0fms   최대 %5.0fms"
                  % (name, statistics.median(s) * 1000, s[int(len(s) * 0.9)] * 1000, s[-1] * 1000))
    print("=" * 70)


if __name__ == "__main__":
    main()
