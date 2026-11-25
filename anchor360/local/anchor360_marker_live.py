# -*- coding: utf-8 -*-
"""
360 카메라 영상에서 로봇 등의 ArUco 마커를 계속 찾아 Unity 로 보낸다 (UDP 127.0.0.1:5013).
Unity 쪽은 Robot360MarkerReceiver 가 받아 가상 로봇을 실제 위치·방향에 맞춘다.

  python anchor360_marker_live.py --marker-h 0.15            (Ctrl+C 로 종료)
  python anchor360_marker_live.py --marker-h 0.15 --seconds 30

--marker-h 는 바닥에서 마커까지의 높이(m)다. 틀리면 위치가 카메라 쪽/반대쪽으로 밀린다
(높이 5 cm 차이 → 2 m 거리에서 약 6 cm).

카메라 세션은 한 프로그램만 잡을 수 있다. anchor360_local.py 와 동시에 돌릴 수 없다.
좌표·각도 규약은 anchor360_local.py 의 검출과 같아서(기준 슬라이스 --u), Unity 의 보정값을 그대로 쓴다.
"""
import argparse
import os
import json
import math
import socket
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
    ap.add_argument("--u", type=float, default=230.0, help="기준 슬라이스 방위 (anchor360_local.py 와 같게)")
    ap.add_argument("--v", type=float, default=-36.35)
    ap.add_argument("--cam-h", type=float, default=2.0)
    ap.add_argument("--marker-h", type=float, default=0.40, help="바닥에서 마커까지 높이(m)")
    ap.add_argument("--id", type=int, default=7, help="이 번호의 마커만 보낸다")
    ap.add_argument("--slice-size", type=int, default=960)
    ap.add_argument("--min-side-px", type=float, default=22.0, help="이보다 작게 보이면 믿지 않는다")
    ap.add_argument("--max-dist", type=float, default=5.0, help="카메라에서 이 거리(m) 넘으면 오인식으로 본다")
    ap.add_argument("--unity-ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5013)
    ap.add_argument("--seconds", type=float, default=0.0, help="이 시간만 돌고 끝낸다. 0 = 계속")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--pose-out", default=None,
                    help="끝날 때 평균 자세를 맵 좌표로 바꿔 이 파일(JSON)에 쓴다. Unity 에디터가 읽어 가상 로봇을 옮긴다")
    ap.add_argument("--calib", default="D:/Go1_Unity/Assets/StreamingAssets/anchor360_calib.json")
    ap.add_argument("--robot-id", default="GO1_A")
    ap.add_argument("--pose-ref", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "anchor360_pose_ref.npz"),
                    help="자세 기준 파일. anchor360_local.py 와 같은 수평·방위 맞춤을 건다(보정값이 이 기준으로 구해졌다)")
    args = ap.parse_args()
    args.stabilization = False       # 보정은 손떨림 보정을 끈 상태에서 했다

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

    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        sts.send("camera._stopPreview", {}); sts.hb_stop.set()
        print("스트림 열기 실패"); sys.exit(3)
    latest = sts.Latest()
    stop = threading.Event()
    threading.Thread(target=sts.reader, args=(cap, latest, stop, {"read_ok": 0, "read_fail": 0}), daemon=True).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # 마커는 영상에서 한 변 40~50 픽셀로 작게 보여서, 슬라이스 가장자리에 걸리거나 조명이 바뀌면 놓치기 쉽다.
    # 그래서 (1) 찾을 때는 방위를 22.5도 간격으로 촘촘히 훑고 설정을 바꿔 가며 여러 번 시도하고,
    # (2) 한 번 찾으면 그 방위가 화면 가운데 오도록 슬라이스를 다시 잡아 따라간다.
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, aru.DEF_DICT))

    def variant(**kw):
        prm = cv2.aruco.DetectorParameters()
        prm.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        for k, v in kw.items():
            setattr(prm, k, v)
        return cv2.aruco.ArucoDetector(dictionary, prm)

    dets = [aru.make_detector(),
            variant(adaptiveThreshWinSizeMin=5, adaptiveThreshWinSizeMax=95, adaptiveThreshWinSizeStep=10),
            variant(adaptiveThreshConstant=12),
            variant()]
    search_us = [args.u + 22.5 * k for k in range(16)]
    R_state = {"R": None, "ready": False}
    map_cache = {}
    track_u = None                   # 따라가는 중인 방위(도). None 이면 찾는 중
    n_sent = n_frames = 0
    xs, zs, yaws = [], [], []
    sides = []
    t0 = time.time()
    print("마커 ID %d 를 찾는 중 (높이 %.2f m, 슬라이스 %d px) → %s:%d" %
          (args.id, args.marker_h, args.slice_size, args.unity_ip, args.port))

    def look(frame, u):
        """방위 u 를 가운데로 한 슬라이스에서 마커를 찾는다. 반환: 마커 또는 None"""
        hh, ww = frame.shape[:2]
        key = round(u * 2) / 2.0
        if key not in map_cache:
            if len(map_cache) > 40:
                map_cache.clear()
            map_cache[key] = apose.slice_maps([key], args.v, 90.0, args.slice_size, R_state["R"], ww, hh)[0]
        m1, m2 = map_cache[key]
        sl = cv2.remap(frame, m1, m2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        for dt in dets:
            ms = [m for m in aru.detect([sl], [key], args.u, args.cam_h, args.v, args.marker_h, dt)
                  if m["id"] == args.id and m["side_px"] >= args.min_side_px
                  and math.hypot(m["x"], m["z"]) <= args.max_dist]
            if ms:
                return ms[0]
        return None

    try:
        while args.seconds <= 0 or time.time() - t0 < args.seconds:
            frame, t_frame, _ = latest.take()
            if frame is None:
                time.sleep(0.01); continue
            n_frames += 1
            if not R_state["ready"]:
                R_state["ready"] = True
                try:
                    ref_band = np.load(args.pose_ref)["band"] if os.path.exists(args.pose_ref) else None
                    R_state["R"], info = apose.solve_pose(frame, ref_band)
                    print("[자세] 기울기 %.2f도, 기준 대비 방위 %+.2f도 (겹침 %s)" %
                          (info["tilt_deg"], info["heading_deg"], "%.2f" % info["corr"] if info["corr"] is not None else "-"))
                except Exception as e:
                    print("[자세] 맞춤 실패(%s) — 원본 좌표계로 진행" % e)
            found = None
            if track_u is not None:
                found = look(frame, track_u)
            if found is None:
                for u in search_us:
                    found = look(frame, u)
                    if found is not None:
                        break
            if found is not None:
                # 마커의 방위(기준 슬라이스 좌표계에서 본 각) → 다음 프레임은 그쪽을 가운데로
                track_u = args.u + math.degrees(math.atan2(found["x"], found["z"]))
            else:
                track_u = None
            if found is None:
                markers = []
            else:
                markers = [found]
                xs.append(found["x"]); zs.append(found["z"]); yaws.append(found["yaw_deg"])
                sides.append(found.get("side_m", 0.0))
            age = max(0.0, time.time() - float(t_frame)) if t_frame else 0.0
            sock.sendto(aru.packet(markers, age).encode("utf-8"), (args.unity_ip, args.port))
            n_sent += 1
            if not args.quiet and n_sent % 10 == 0:
                print("  %5.1fs  %s" % (time.time() - t0,
                      "ID %d  x=%.3f z=%.3f yaw=%.1f  (%d px)" % (found["id"], found["x"], found["z"], found["yaw_deg"], found["side_px"])
                      if found else "안 보임"))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        sts.send("camera._stopPreview", {})
        sts.hb_stop.set()
        sock.close()

    dur = time.time() - t0
    print("끝: %.1f초, 처리 %d장 (%.1f Hz), 마커 보인 것 %d장 (%.0f%%)" %
          (dur, n_frames, n_frames / max(dur, 1e-6), len(xs), 100.0 * len(xs) / max(n_frames, 1)))
    if xs:
        ya = np.radians(yaws)
        rlen = float(np.hypot(np.mean(np.sin(ya)), np.mean(np.cos(ya))))
        yaw_mean = math.degrees(math.atan2(np.mean(np.sin(ya)), np.mean(np.cos(ya))))
        yaw_sd = math.degrees(math.sqrt(max(0.0, -2.0 * math.log(max(1e-9, rlen)))))
        print("평균 위치 x=%.3f z=%.3f m (거리 %.2f m), 방향 %.1f도 | 흔들림 위치 %.1f cm, 방향 %.1f도" %
              (np.mean(xs), np.mean(zs), math.hypot(np.mean(xs), np.mean(zs)), yaw_mean,
               100 * float(np.hypot(np.std(xs), np.std(zs))), yaw_sd))
        print("가정한 높이 %.2f m 에서 계산한 마커 한 변: %.1f cm" % (args.marker_h, 100 * float(np.mean(sides))))
        if args.pose_out:
            # Robot360MarkerReceiver.ToWorld 와 같은 변환 (씬의 앵커 회전은 0)
            c = json.load(open(args.calib, encoding="utf-8"))
            sc = c.get("distanceScale", 1.0); sign = -1.0 if c.get("invertX") else 1.0
            lx, lz = float(np.mean(xs)) * sign * sc, float(np.mean(zs)) * sc
            t = math.radians(c["yawOffsetDeg"]); ct, st = math.cos(t), math.sin(t)
            wx = c["anchorX"] + lx * ct + lz * st
            wz = c["anchorZ"] - lx * st + lz * ct
            wyaw = (c["yawOffsetDeg"] + sign * yaw_mean) % 360.0
            os.makedirs(os.path.dirname(os.path.abspath(args.pose_out)), exist_ok=True)
            with open(args.pose_out, "w", encoding="utf-8") as fh:
                json.dump({"x": round(wx, 4), "z": round(wz, 4), "yaw_deg": round(wyaw, 2), "samples": len(xs),
                           "robot_id": args.robot_id, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "marker_h": args.marker_h}, fh)
            print("맵 좌표: (%.3f, %.3f) 방향 %.1f도 → %s" % (wx, wz, wyaw, args.pose_out))


if __name__ == "__main__":
    main()
