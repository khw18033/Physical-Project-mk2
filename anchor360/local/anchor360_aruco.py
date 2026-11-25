# -*- coding: utf-8 -*-
"""
360 카메라 슬라이스에서 ArUco 마커를 찾아 로봇의 위치와 방향을 구한다.

로봇 등 위에 마커를 수평으로 붙였다고 가정한다(높이 marker_h). 마커 네 꼭짓점의 픽셀을
"높이 marker_h 인 수평면"에 내려 찍어 중심(x, z)과 방향(yaw)을 얻는다. 좌표계와 각도 규약은
anchor360_local.py 의 검출(pos3d, yaw_deg)과 같다: 기준 슬라이스(u_ref) 기준, x=오른쪽, z=앞,
yaw 는 위에서 보아 시계방향 +, 0 = 기준 슬라이스가 보는 방향.

마커의 "위쪽 변"이 로봇 앞을 향하게 붙인다.

단독 실행하면 합성 영상으로 자체 시험을 한다:  python anchor360_aruco.py --selftest
"""
import json
import math
import time

import cv2
import numpy as np

DEF_DICT = "DICT_4X4_50"


def make_detector(dict_name=DEF_DICT):
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 33
    params.adaptiveThreshWinSizeStep = 6
    params.minMarkerPerimeterRate = 0.02      # 720 px 슬라이스에서 한 변 약 14 px 까지
    params.polygonalApproxAccuracyRate = 0.05
    return cv2.aruco.ArucoDetector(dictionary, params)


class PlaneProjector:
    """슬라이스(시야 90도 핀홀, 아래로 pitch) 픽셀 → 높이 plane_h 수평면 위의 점. live.GroundProjector 와 같은 식."""

    def __init__(self, size, cam_h, pitch_deg, plane_h):
        self.f = size / 2.0
        self.c = size / 2.0
        self.h = cam_h - plane_h
        th = math.radians(pitch_deg)
        self.cos_t, self.sin_t = math.cos(th), math.sin(th)

    def __call__(self, px, py):
        dx = (px - self.c) / self.f
        dy = -(py - self.c) / self.f
        wy = self.cos_t * dy + self.sin_t
        wz = -self.sin_t * dy + self.cos_t
        if wy >= -1e-6:
            return None
        t = -self.h / wy
        return dx * t, wz * t

    def to_pixel(self, x, z):
        """수평면 위의 점 → 픽셀 (자체 시험용 역변환)."""
        wy = -self.h
        # 카메라 좌표: dz(앞) = sin_t*wy + cos_t*wz, dy(위) = cos_t*wy - sin_t*wz
        dz = self.sin_t * wy + self.cos_t * z
        dy = self.cos_t * wy - self.sin_t * z
        if dz <= 1e-6:
            return None
        return self.c + self.f * x / dz, self.c - self.f * dy / dz


def detect(slices, u_list, u_ref, cam_h, pitch_deg, marker_h, detector=None):
    """
    slices: 슬라이스 영상 목록(BGR), u_list: 각 슬라이스의 방위(도).
    반환: [{id, x, z, yaw_deg, side_px, slice_u}] — 같은 id 가 여러 슬라이스에 보이면 가장 크게 보인 것 하나.
    """
    detector = detector or make_detector()
    best = {}
    for img, u in zip(slices, u_list):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        corners, ids, _ = detector.detectMarkers(gray)
        if ids is None:
            continue
        proj = PlaneProjector(gray.shape[1], cam_h, pitch_deg, marker_h)
        d = math.radians(u - u_ref)
        c, s = math.cos(d), math.sin(d)
        for quad, mid in zip(corners, ids.flatten()):
            q = quad.reshape(4, 2)                       # 순서: 좌상, 우상, 우하, 좌하 (마커 기준)
            pts = [proj(float(px), float(py)) for px, py in q]
            if any(p is None for p in pts):
                continue
            pts = np.array(pts)
            cx, cz = pts.mean(axis=0)
            fwd = (pts[0] + pts[1]) / 2.0 - (pts[3] + pts[2]) / 2.0     # 마커 위쪽 변 방향 = 로봇 앞
            # 슬라이스 로컬 → 기준 슬라이스 좌표계 (merge_slices 와 같은 회전)
            X, Z = cx * c + cz * s, -cx * s + cz * c
            fx, fz = fwd[0] * c + fwd[1] * s, -fwd[0] * s + fwd[1] * c
            side_px = float(np.mean([np.linalg.norm(q[i] - q[(i + 1) % 4]) for i in range(4)]))
            side_m = float(np.mean([np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)]))   # 가정한 높이에서 계산한 한 변(m)
            m = {"id": int(mid), "x": round(float(X), 3), "z": round(float(Z), 3), "side_m": round(side_m, 4),
                 "yaw_deg": round(math.degrees(math.atan2(fx, fz)), 1),
                 "side_px": round(side_px, 1), "slice_u": round(u % 360.0, 1)}
            if int(mid) not in best or side_px > best[int(mid)]["side_px"]:
                best[int(mid)] = m
    return list(best.values())


def packet(markers, frame_age_s=0.0):
    return json.dumps({"type": "robot_markers", "timestamp": time.time(),
                       "frame_age_s": round(float(frame_age_s), 3), "markers": markers})


# ---------------------------------------------------------------------------------------------
# 자체 시험: 수평면 위에 마커를 그려 넣은 합성 슬라이스로 위치·방향 오차와 검출 한계를 본다
# ---------------------------------------------------------------------------------------------
def _render(size, cam_h, pitch, marker_h, side_m, x, z, yaw_deg, marker_id=7, blur=1.2, jpeg_q=45, seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((size, size), 150, np.uint8)
    img = cv2.add(img, rng.normal(0, 12, img.shape).astype(np.int16).clip(-60, 60).astype(np.int8), dtype=cv2.CV_8U)
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DEF_DICT))
    res = 240
    tile = cv2.aruco.generateImageMarker(dictionary, marker_id, res)
    quiet = res // 6                                      # 흰 여백(마커 한 칸 크기)
    tile = cv2.copyMakeBorder(tile, quiet, quiet, quiet, quiet, cv2.BORDER_CONSTANT, value=255)
    full = tile.shape[0]
    half = side_m * full / res / 2.0                      # 여백 포함 반 변(m)
    yaw = math.radians(yaw_deg)
    f = np.array([math.sin(yaw), math.cos(yaw)])          # 앞(위쪽 변 방향)
    r = np.array([math.cos(yaw), -math.sin(yaw)])         # 오른쪽
    ctr = np.array([x, z])
    world = [ctr + f * half - r * half, ctr + f * half + r * half,
             ctr - f * half + r * half, ctr - f * half - r * half]   # 좌상, 우상, 우하, 좌하
    proj = PlaneProjector(size, cam_h, pitch, marker_h)
    dst = [proj.to_pixel(*p) for p in world]
    if any(p is None for p in dst):
        return None
    src = np.float32([[0, 0], [full, 0], [full, full], [0, full]])
    H = cv2.getPerspectiveTransform(src, np.float32(dst))
    warped = cv2.warpPerspective(tile, H, (size, size), flags=cv2.INTER_AREA, borderValue=0)
    mask = cv2.warpPerspective(np.full_like(tile, 255), H, (size, size), flags=cv2.INTER_NEAREST)
    img = np.where(mask > 0, warped, img).astype(np.uint8)
    if blur > 0:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg_q])
    return cv2.cvtColor(cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE), cv2.COLOR_GRAY2BGR)


def selftest(size=720, cam_h=2.0, pitch=-36.35, marker_h=0.40):
    det = make_detector()
    print("슬라이스 %d px, 카메라 높이 %.2f m, 고저각 %.2f도, 마커 높이 %.2f m" % (size, cam_h, pitch, marker_h))
    print("거리 = 카메라 바로 아래에서 마커까지의 바닥 거리. 각 칸: 검출률 / 위치 오차 중앙값(cm) / 방향 오차 중앙값(도)")
    dists = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    print("마커 한 변   " + "".join("%14s" % ("%.1f m" % d) for d in dists))
    rows = {}
    for side in (0.10, 0.15, 0.20, 0.25):
        line = "%6.0f cm   " % (side * 100)
        for dist in dists:
            n, hit, pe, ye = 0, 0, [], []
            for k, yaw in enumerate(range(0, 360, 20)):
                for off in (-0.3, 0.0, 0.3):              # 슬라이스 가운데에서 좌우로 조금 벗어난 경우
                    x, z = dist * math.sin(off), dist * math.cos(off)
                    img = _render(size, cam_h, pitch, marker_h, side, x, z, yaw, seed=k)
                    if img is None:
                        continue
                    n += 1
                    out = detect([img], [0.0], 0.0, cam_h, pitch, marker_h, det)
                    out = [m for m in out if m["id"] == 7]
                    if not out:
                        continue
                    hit += 1
                    pe.append(math.hypot(out[0]["x"] - x, out[0]["z"] - z) * 100)
                    ye.append(abs((out[0]["yaw_deg"] - yaw + 180) % 360 - 180))
            rate = hit / n if n else 0.0
            rows[(side, dist)] = rate
            line += "%14s" % ("%3.0f%% %4.1f %4.1f" % (rate * 100, np.median(pe), np.median(ye)) if hit else "  0%    -    -")
        print(line)
    return rows


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        selftest()
    else:
        print(__doc__)
