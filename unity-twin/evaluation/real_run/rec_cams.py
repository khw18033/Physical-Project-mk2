# 실제 카메라 영상을 시각과 함께 저장한다 (주행 기록용).
#   360: anchor360_local.py 가 갱신하는 탐지 화면(live_out/anchor360_latest.jpg)을 바뀔 때마다 복사
#   Go1 정면: pi7 카메라 뷰어(MJPEG)에서 초당 4장
import os, sys, time, shutil, threading
import cv2
out = os.path.dirname(os.path.abspath(__file__))
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 600
src = r"D:\HW_coupling\insta360 pro2\live_out\anchor360_latest.jpg"
d360 = os.path.join(out, "cam360"); dgo = os.path.join(out, "go1front")
os.makedirs(d360, exist_ok=True); os.makedirs(dgo, exist_ok=True)
t_end = time.time() + secs

def front():
    cap = cv2.VideoCapture("http://100.72.109.9:8090/stream/1"); last = 0   # pi7 Tailscale (이전: 192.168.50.170)
    while time.time() < t_end:
        ok, fr = cap.read()
        if not ok:
            time.sleep(0.2); continue
        if time.time() - last >= 0.25:
            last = time.time(); cv2.imwrite(os.path.join(dgo, "%.3f.jpg" % last), fr)
    cap.release()

threading.Thread(target=front, daemon=True).start()
seen = 0
while time.time() < t_end and not os.path.exists(os.path.join(out, "REC_STOP")):
    try:
        m = os.path.getmtime(src)
        if m != seen:
            seen = m; time.sleep(0.05); shutil.copyfile(src, os.path.join(d360, "%.3f.jpg" % time.time()))
    except OSError:
        pass
    time.sleep(0.1)
print("rec done", len(os.listdir(d360)), len(os.listdir(dgo)))
