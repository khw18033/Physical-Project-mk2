"""
go1_front_guard.py — Go1 정면 카메라 근접 경고 (로봇은 건드리지 않는다)

[역할 분담]
  360° 카메라 = 방 전체 장애물 지도(anchor360_local.py)
  Go1 정면   = 로봇 바로 앞에 무엇이 있는지만 본다. "정확히 어디"가 아니라 "앞에 뭔가 가깝다"를 알린다.
  두 카메라를 서로 맞추지 않는다 — 로봇 기준(앞 +, 오른쪽 +) 거리만 쓴다.

[흐름]
  pi7 카메라 뷰어(MJPEG, http://<pi7>:8090/stream/1) → 이 PC 에서 검출(360 과 같은 모델)
  → 검출 박스 아랫변 가운데를 바닥에 투영해 로봇 기준 거리·좌우 위치를 구한다
  → 진행 통로(좌우 ±corridor) 안에서 가장 가까운 물체로 단계 결정: clear / warn / stop
  → UDP JSON(Unity 5012) + 브라우저 화면(http://localhost:8091/)
  ※ 로봇에 정지 명령을 보내지 않는다. 화면 표시와 Unity 알림까지만 한다.

[거리의 정확도 — 낮다]
  카메라가 바닥에서 약 0.3 m 로 낮고 어안 렌즈 보정값이 없다(등거리 모델 r = f·θ, f 는 추정).
  2026-11-18 실측 한 점: 실제 0.57 m 인 물체를 0.48 m 로 봤다(약 15% 가깝게). 1.5 m 를 넘으면 믿기 어렵다.
  그래서 경고 기준으로만 쓰고 지도 배치에는 쓰지 않는다.

[실행]
  python go1_front_guard.py                 # 기본값
  python go1_front_guard.py --warn 1.2 --stop 0.7
"""
import os
import sys
import json
import math
import time
import socket
import argparse
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cv2
import numpy as np

import anchor360_local as L
import anchor360_live as live


class Fisheye:
    """등거리 어안(r = f·θ). 로봇 기준 좌표: x 오른쪽, y 위, z 앞. 카메라는 (0, h, 0) 에서 앞을 본다."""

    def __init__(self, f, cx, cy, h, pitch_deg=0.0):
        self.f, self.cx, self.cy, self.h = f, cx, cy, h
        p = math.radians(pitch_deg)
        self.fwd = np.array([0.0, math.sin(p), math.cos(p)])
        self.right = np.array([1.0, 0.0, 0.0])
        self.up = np.cross(self.fwd, self.right)

    def floor(self, u, v):
        """화면 픽셀 → 바닥 위 (오른쪽 m, 앞 m). 지평선 위면 None."""
        dx, dy = u - self.cx, -(v - self.cy)
        r = math.hypot(dx, dy)
        th = r / self.f
        if r < 1e-6:
            d = self.fwd
        else:
            d = self.fwd * math.cos(th) + (self.right * dx / r + self.up * dy / r) * math.sin(th)
        if d[1] > -0.03:
            return None
        t = self.h / -d[1]
        return float(d[0] * t), float(d[2] * t)


SOI, EOI = bytes([0xFF, 0xD8]), bytes([0xFF, 0xD9])     # JPEG 시작·끝 표식


class Grabber(threading.Thread):
    """MJPEG 를 계속 읽어 최신 한 장만 들고 있는다. 끊기면 다시 붙는다."""

    def __init__(self, url):
        super().__init__(daemon=True)
        self.url, self.frame, self.t, self.lock, self.stop = url, None, 0.0, threading.Lock(), False

    def run(self):
        import urllib.request
        while not self.stop:
            try:
                r = urllib.request.urlopen(self.url, timeout=6)
                buf = b""
                while not self.stop:
                    chunk = r.read(8192)
                    if not chunk:
                        break
                    buf += chunk
                    last = None
                    while True:                      # 버퍼에 쌓인 것 중 마지막 완성 프레임만 쓴다
                        i = buf.find(SOI)
                        j = buf.find(EOI, i + 2) if i >= 0 else -1
                        if i < 0 or j < 0:
                            break
                        last, buf = buf[i:j + 2], buf[j + 2:]
                    if last is not None:
                        f = cv2.imdecode(np.frombuffer(last, np.uint8), cv2.IMREAD_COLOR)
                        if f is not None:
                            with self.lock:
                                self.frame, self.t = f, time.time()
                    if len(buf) > 2000000:
                        buf = b""
            except Exception:
                pass
            time.sleep(1.0)

    def take(self):
        with self.lock:
            return self.frame, self.t


def main():
    ap = argparse.ArgumentParser(description="Go1 정면 카메라 근접 경고")
    # 2026-11-25: pi7 Tailscale 주소로 바꿈. 랩 공유기로 받으려면 --url http://192.168.50.170:8090/stream/1
    ap.add_argument("--url", default="http://100.72.109.9:8090/stream/1", help="Go1 정면 MJPEG")
    ap.add_argument("--cfg", default=L.DEF_CFG)
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--scale", type=float, default=2.0, help="검출 전 확대 배율(원본 464x400 이 작아서)")
    ap.add_argument("--f", type=float, default=140.0, help="어안 초점(px/rad, 추정값)")
    ap.add_argument("--cx", type=float, default=232.0)
    ap.add_argument("--cy", type=float, default=200.0)
    ap.add_argument("--cam-h", type=float, default=0.30, help="서 있을 때 정면 카메라 높이(m, 추정값)")
    ap.add_argument("--pitch", type=float, default=0.0)
    ap.add_argument("--valid-r", type=float, default=175.0, help="이 반지름(px) 밖은 로봇 머리에 가린 곳으로 보고 무시")
    ap.add_argument("--corridor", type=float, default=0.35, help="진행 통로 반폭(m)")
    ap.add_argument("--warn", type=float, default=1.0, help="이 거리(m) 안이면 warn")
    ap.add_argument("--stop", type=float, default=0.6, help="이 거리(m) 안이면 stop")
    ap.add_argument("--hold", type=float, default=1.5, help="warn/stop 을 마지막 검출 뒤 이만큼(초) 유지 — 검출이 깜빡여도 단계가 흔들리지 않게")
    ap.add_argument("--unity-ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5012)
    ap.add_argument("--http-port", type=int, default=8091)
    ap.add_argument("--seconds", type=float, default=0)
    args = ap.parse_args()

    os.chdir(L.DEF_CLIP_CWD)
    live.KEEP_GROUPS = {"HARD_OBSTACLE", "AGENT", "SOFT_PUSHABLE", "LOW_OBSTACLE", "THIN_OBSTACLE",
                        "GROUND_HAZARD", "VEHICLE"}
    cfg = L.LocalConfig(args.cfg, None)
    det = live.Detector(cfg, 640)
    det.warmup(640)
    fish = Fisheye(args.f, args.cx, args.cy, args.cam_h, args.pitch)
    print("[guard] 모델 준비. 영상 %s → UDP %s:%d, 화면 http://localhost:%d/" % (args.url, args.unity_ip, args.port, args.http_port))

    grab = Grabber(args.url)
    grab.start()
    web = None
    try:
        web = L.MjpegServer("0.0.0.0", args.http_port)
    except OSError as e:
        print("[guard] 화면 포트 %d 열기 실패(%s)" % (args.http_port, e))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    COL = {"clear": (0, 200, 0), "warn": (0, 200, 255), "stop": (0, 0, 255), "no_video": (128, 128, 128)}
    t_start, period, last_level, n = time.time(), 1.0 / args.fps, None, 0
    RANK = {"clear": 0, "warn": 1, "stop": 2}
    held = {"level": "clear", "t": 0.0, "nearest": None}
    while args.seconds <= 0 or time.time() - t_start < args.seconds:
        t0 = time.time()
        frame, t_frame = grab.take()
        age = t0 - t_frame
        if frame is None or age > 2.0:
            level, items, nearest = "no_video", [], None
            view = np.zeros((400, 464, 3), np.uint8) if frame is None else frame.copy()
        else:
            S = args.scale
            big = cv2.resize(frame, None, fx=S, fy=S, interpolation=cv2.INTER_CUBIC)
            dets = L.detect_batch(det, [big])[0]
            items = []
            for d in dets:
                x1, y1, x2, y2 = [v / S for v in d["bbox"]]
                bu, bv = (x1 + x2) / 2.0, y2
                if math.hypot(bu - args.cx, bv - args.cy) > args.valid_r:
                    continue
                g = fish.floor(bu, bv)
                if g is None or g[1] <= 0:
                    continue                     # 바닥 위치를 못 구한 것(지평선 위)은 보내지 않는다 — null 을 싣지 않기 위해
                items.append({"name": d["name"], "conf": round(d["conf"], 2),
                              "bbox": [round(x1), round(y1), round(x2), round(y2)],
                              "right_m": round(g[0], 2), "forward_m": round(g[1], 2),
                              "dist_m": round(math.hypot(*g), 2), "in_path": bool(abs(g[0]) <= args.corridor)})
            inpath = [i for i in items if i["in_path"]]
            nearest = min(inpath, key=lambda i: i["forward_m"]) if inpath else None
            level = "clear"
            if nearest is not None:
                level = "stop" if nearest["forward_m"] <= args.stop else "warn" if nearest["forward_m"] <= args.warn else "clear"
            view = frame.copy()
            # 단계 유지: 더 심한 단계는 바로 올리고, 내려갈 때는 hold 초가 지나야 내린다
            if RANK[level] >= RANK[held["level"]] and level != "clear":
                held.update(level=level, t=t0, nearest=nearest)
            elif t0 - held["t"] <= args.hold and RANK[held["level"]] > RANK[level]:
                level, nearest = held["level"], held["nearest"]
            else:
                held.update(level=level, t=t0, nearest=nearest)

        pkt = {"type": "go1_front_guard", "timestamp": "%.3f" % time.time(), "level": level,
               "nearest_name": "" if nearest is None else nearest["name"],
               "nearest_forward_m": -1.0 if nearest is None else nearest["forward_m"],
               "video_age_s": -1.0 if frame is None else round(age, 2),
               "warn_m": args.warn, "stop_m": args.stop, "detections": items}
        sock.sendto(json.dumps(pkt, ensure_ascii=False).encode("utf-8"), (args.unity_ip, args.port))

        if level != last_level:
            print("[guard] %s → %s%s" % (last_level, level, "" if nearest is None else
                                         "  (%s 앞 %.2f m, 좌우 %+.2f m)" % (nearest["name"], nearest["forward_m"], nearest["right_m"])))
            last_level = level

        if web is not None:
            V = 2
            view = cv2.resize(view, None, fx=V, fy=V, interpolation=cv2.INTER_CUBIC)
            for it in items:
                x1, y1, x2, y2 = [int(v * V) for v in it["bbox"]]
                c = (0, 0, 255) if it["in_path"] and it["forward_m"] <= args.warn else (0, 255, 0)
                cv2.rectangle(view, (x1, y1), (x2, y2), c, 2)
                lab = "%s %.1fm" % (it["name"], it["dist_m"])
                cv2.putText(view, lab, (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 2)
            cv2.rectangle(view, (0, 0), (view.shape[1], 30), COL[level], -1)
            cv2.putText(view, "Go1 front: %s" % level.upper(), (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            web.publish(view)

        n += 1
        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)
    grab.stop = True
    if web is not None:
        web.close()


if __name__ == "__main__":
    main()
