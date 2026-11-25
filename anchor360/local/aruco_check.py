# -*- coding: utf-8 -*-
"""
360 카메라에서 영상을 몇 장 받아 ArUco 마커가 잡히는지 확인한다 (한 번 실행하고 끝).
anchor360_local.py 와 같은 방식으로 카메라에 붙고(프리뷰 시작 → 프레임 → 프리뷰 정지), 결과 그림을 저장한다.

  python aruco_check.py [--out 폴더] [--marker-h 0.40]
"""
import argparse
import math
import os
import sys
import threading
import time

import cv2
import numpy as np

import anchor360_aruco as aru
import anchor360_pose as apose
import stream_to_server as sts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=sts.DEF_IP)
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--bitrate", type=int, default=10240)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_out", "aruco_check"))
    ap.add_argument("--u", type=float, default=230.0)
    ap.add_argument("--v", type=float, default=-36.35)
    ap.add_argument("--cam-h", type=float, default=2.0)
    ap.add_argument("--marker-h", type=float, default=0.40)
    ap.add_argument("--frames", type=int, default=5)
    ap.add_argument("--image", default=None, help="카메라 대신 이 등장방형 그림으로 확인")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    frames = []
    if args.image:
        frames = [cv2.imread(args.image)]
    else:
        sts.CMD_URL = "http://%s:20000/osc/commands/execute" % args.ip
        sts.STATE_URL = "http://%s:20000/osc/state" % args.ip
        if not sts.connect():
            print("카메라 연결 실패"); sys.exit(1)
        sts.hb_stop.clear()
        threading.Thread(target=sts.heartbeat, daemon=True).start()
        time.sleep(0.5)
        url = sts.start_preview(args)
        if not url:
            sts.hb_stop.set(); print("프리뷰 시작 실패"); sys.exit(2)
        try:
            cap = cv2.VideoCapture(url)
            if not cap.isOpened():
                print("스트림 열기 실패"); sys.exit(3)
            t0 = time.time()
            n = 0
            while time.time() - t0 < 25 and len(frames) < args.frames:
                ok, fr = cap.read()
                if not ok:
                    continue
                n += 1
                if n > 30 and n % 15 == 0:      # 처음 1초는 버리고 0.5초 간격으로
                    frames.append(fr.copy())
            cap.release()
        finally:
            sts.send("camera._stopPreview", {})
            sts.hb_stop.set()
    if not frames:
        print("프레임을 받지 못함"); sys.exit(4)

    equ = frames[-1]
    h, w = equ.shape[:2]
    cv2.imwrite(os.path.join(args.out, "equirect.jpg"), equ, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print("프레임 %d장, 크기 %dx%d" % (len(frames), w, h))

    det = aru.make_detector()
    u_list = [args.u + 45.0 * k for k in range(8)]
    found_any = False
    for size in (720, 960, 1200):
        hits = {}
        for fi, fr in enumerate(frames):
            slices = [apose.persp(fr, u, args.v, 90.0, size) for u in u_list]
            ms = aru.detect(slices, u_list, args.u, args.cam_h, args.v, args.marker_h, det)
            for m in ms:
                hits.setdefault(m["id"], []).append(m)
            if fi == len(frames) - 1:
                last_slices = slices
        print("슬라이스 %4d px: " % size + (", ".join(
            "ID %d → %d/%d장, 한 변 %.0f px, 위치 (x=%.2f, z=%.2f) m, 거리 %.2f m, 방향 %.0f도, 흔들림 %.1f cm"
            % (i, len(v), len(frames), np.mean([m["side_px"] for m in v]),
               np.mean([m["x"] for m in v]), np.mean([m["z"] for m in v]),
               math.hypot(np.mean([m["x"] for m in v]), np.mean([m["z"] for m in v])),
               v[-1]["yaw_deg"],
               100 * float(np.hypot(np.std([m["x"] for m in v]), np.std([m["z"] for m in v]))))
            for i, v in sorted(hits.items())) or "마커 없음"))
        if hits:
            found_any = True
            # 마커가 보인 슬라이스에 표시해서 저장
            for i, v in hits.items():
                k = int(round(((v[-1]["slice_u"] - args.u) % 360.0) / 45.0)) % 8
                img = last_slices[k].copy()
                corners, ids, _ = det.detectMarkers(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
                if ids is not None:
                    cv2.aruco.drawDetectedMarkers(img, corners, ids)
                cv2.imwrite(os.path.join(args.out, "found_id%d_slice%d_%dpx.jpg" % (i, k, size)), img)

    # 못 찾았을 때 눈으로 볼 수 있게 8방향 슬라이스를 한 장으로 저장
    tiles = [cv2.resize(apose.persp(equ, u, args.v, 90.0, 720), (480, 480)) for u in u_list]
    for t, u in zip(tiles, u_list):
        cv2.putText(t, "u=%d" % (u % 360), (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.imwrite(os.path.join(args.out, "slices_overview.jpg"), np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]))
    print("결과 폴더:", args.out)
    print("결론:", "마커 인식됨" if found_any else "마커 인식 안 됨")


if __name__ == "__main__":
    main()
