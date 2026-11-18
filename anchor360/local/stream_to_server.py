"""
stream_to_server.py — pro2_auto_bg.py 의 영상판 (사진 촬영 → 실시간 프레임)

[무엇을 대체하나]
  기존 : 촬영(20s) → 다운로드 → ProStitcher stitch(50s) → 업로드     ← stitch 가 병목
  이것 : 인카메라 실시간 스티칭 RTMP → 프레임 뽑기 → 업로드           ← stitch 없음

  서버(pano_receiver, anchor360_live)와 유니티는 한 줄도 바꾸지 않는다.
  같은 /upload_pano 에 같은 equirect.jpg 를 올리므로 live.py 감시 루프가 그대로 집어간다.

[지연 누적 방지 — 이 스크립트의 핵심]
  cv2.VideoCapture 는 RTMP 프레임을 내부 버퍼에 쌓는다. 메인 루프가 5fps 로
  read() 를 부르면 15fps 로 들어오는 프레임이 계속 밀려 '오래된 프레임'이 나온다.
  사진 방식에서 stitch 큐가 적체된 것과 같은 현상이 버퍼 안에서 재현된다.
  그래서 리더 스레드가 쉬지 않고 read() 해서 최신 한 장만 들고 있고,
  메인 루프는 그 최신 장만 집어간다. 오래된 프레임은 즉시 버린다.

[디스크]
  서버에 capture_id 폴더 하나를 계속 덮어쓴다. 디스크 증가 0.
  PC 에는 아무것도 저장하지 않는다(메모리에서 바로 업로드).

[서버 쪽 주의]
  anchor360_live.py 의 --poll 기본값이 1.0초다. 5fps 로 올려도 초당 1장만 집는다.
  반드시 --poll 0.1 로 낮춰서 띄울 것.

[사용]
  python stream_to_server.py                      # 5fps 무한
  python stream_to_server.py --fps 3              # 3fps
  python stream_to_server.py --count 30           # 30장만 올리고 종료(측정용)
  python stream_to_server.py --dry-run --count 20 # 업로드 없이 스트림 성능만

[의존]
  requests, opencv-python

[종료]
  Ctrl+C  → _stopPreview 후 통계 출력
"""

import sys
import json
import time
import signal
import argparse
import threading
import statistics

import cv2
import requests

DEF_IP         = "192.168.100.124"
DEF_UPLOAD     = "http://210.110.250.33:7866/upload_pano"
DEF_CAPTURE_ID = "LIVE_STREAM"
DEF_CAMERA_ID  = "pro2_anchor"

fingerprint = None
hb_stop = threading.Event()
hb_thread = None
CMD_URL = None
STATE_URL = None
_running = True


# ── 카메라 제어 (preview_probe.py 와 동일) ───────────────
def headers():
    h = {"Content-Type": "application/json"}
    if fingerprint:
        h["Fingerprint"] = fingerprint
    return h


def heartbeat():
    while not hb_stop.is_set():
        try:
            requests.post(STATE_URL, json={}, headers=headers(), timeout=3)
        except Exception:
            pass
        time.sleep(1)


def connect(max_retry=3):
    global fingerprint
    for attempt in range(1, max_retry + 1):
        try:
            body = requests.post(CMD_URL,
                                 json={"name": "camera._connect", "parameters": {}},
                                 timeout=10).json()
            fp = body.get("results", {}).get("Fingerprint")
            if fp:
                fingerprint = fp
                print("[연결] Fingerprint=%s" % fp)
                return True
            err = body.get("error", {})
            print("[연결] 시도 %d: %s — %s"
                  % (attempt, err.get("code"), err.get("description")))
            if err.get("description") == "already connected by another":
                print("        → 다른 창(preview_probe / pro2_auto_bg)이 세션을 쥐고 있습니다.")
                return False
        except Exception as e:
            print("[연결] 시도 %d 실패: %s" % (attempt, e))
        time.sleep(1.5)
    return False


def send(name, params=None, timeout=20):
    body = {"name": name}
    if params is not None:
        body["parameters"] = params
    try:
        return requests.post(CMD_URL, json=body, headers=headers(), timeout=timeout).json()
    except Exception as e:
        return {"state": "exception", "error": {"description": str(e)}}


def start_preview(args):
    params = {
        "origin": {"mime": "h264", "width": 1920, "height": 1440,
                   "framerate": 30, "bitrate": 20480},
        "stiching": {"mode": "pano", "mime": "h264",
                     "width": args.width, "height": args.height,
                     "framerate": 30, "bitrate": args.bitrate},
        "stabilization": True,
    }
    send("camera._stopPreview", {})          # 남아 있을 수 있으니 먼저 끈다
    time.sleep(1.0)
    res = send("camera._startPreview", params)
    if res.get("state") != "done":
        err = res.get("error", {})
        print("[프리뷰] 실패: %s — %s" % (err.get("code"), err.get("description")))
        return None
    url = res.get("results", {}).get("_previewUrl", "")
    # 카메라가 자기 자신 기준(127.0.0.1)으로 주므로 카메라 IP 로 바꾼다
    url = url.replace("//127.0.0.1", "//" + args.ip).replace("//localhost", "//" + args.ip)
    if "://" in url and ":" not in url.split("://", 1)[1].split("/", 1)[0]:
        scheme, rest = url.split("://", 1)
        host, path = rest.split("/", 1)
        url = "%s://%s:1935/%s" % (scheme, host, path)
    print("[프리뷰] %s  (%dx%d, %d kbps)" % (url, args.width, args.height, args.bitrate))
    return url


# ── 최신 프레임 한 장만 들고 있는 리더 ───────────────────
class Latest:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.t = 0.0
        self.seq = 0
        self.dropped = 0

    def put(self, f, t):
        with self.lock:
            if self.frame is not None:
                self.dropped += 1      # 메인이 안 집어간 것 = 버린 프레임
            self.frame, self.t, self.seq = f, t, self.seq + 1

    def take(self):
        with self.lock:
            f, t, s = self.frame, self.t, self.seq
            self.frame = None
            return f, t, s


def reader(cap, latest, stop, stat):
    """
    cap.read() 가 진행 중일 때 다른 스레드가 cap.release() 를 부르면
    libavcodec 이 'Assertion fctx->async_lock failed' 로 프로세스를 죽인다.
    그래서 cap 의 수명을 이 스레드가 전적으로 소유하고, 여기서만 해제한다.
    """
    try:
        while not stop.is_set():
            ok, f = cap.read()
            if not ok:
                stat["read_fail"] += 1
                if stop.is_set():
                    break
                time.sleep(0.05)
                continue
            stat["read_ok"] += 1
            latest.put(f, time.time())
    finally:
        try:
            cap.release()
        except Exception:
            pass


# ── main ─────────────────────────────────────────────────
def main():
    global CMD_URL, STATE_URL, hb_thread, _running

    ap = argparse.ArgumentParser(description="Pro2 실시간 스트림 → 서버 업로드")
    ap.add_argument("--ip", default=DEF_IP)
    ap.add_argument("--upload", default=DEF_UPLOAD)
    ap.add_argument("--capture-id", default=DEF_CAPTURE_ID,
                    help="서버에 덮어쓸 폴더명. 고정이라 디스크가 늘지 않는다")
    ap.add_argument("--camera-id", default=DEF_CAMERA_ID)
    ap.add_argument("--rotate", type=int, default=0,
                    help="capture_id 를 N개 폴더로 돌려쓴다. 0=고정 1개. "
                         "서버 live.py 의 wait_stable 이 '쓰이는 중'으로 오판해 "
                         "1.5초를 버리는 것을 피하려면 8 이상 권장")
    ap.add_argument("--fps", type=float, default=5.0, help="서버로 올릴 목표 fps")
    ap.add_argument("--quality", type=int, default=92, help="JPEG 품질 (1~100)")
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--bitrate", type=int, default=10240)
    ap.add_argument("--count", type=int, default=0, help="N장 올리고 종료 (0=무한)")
    ap.add_argument("--dry-run", action="store_true", help="업로드 없이 스트림만 측정")
    ap.add_argument("--url", default=None, help="스트림 주소 직접 지정")
    args = ap.parse_args()

    CMD_URL   = "http://%s:20000/osc/commands/execute" % args.ip
    STATE_URL = "http://%s:20000/osc/state" % args.ip

    print("=" * 70)
    print("stream_to_server — 카메라 %s → %s" % (args.ip, args.upload))
    print("  목표 %.1f fps | JPEG q%d | capture_id=%s%s%s"
          % (args.fps, args.quality, args.capture_id,
             ("  (%d개 회전)" % args.rotate) if args.rotate > 0 else "  (고정)",
             "  [DRY-RUN]" if args.dry_run else ""))
    print("=" * 70)

    if not connect():
        sys.exit(1)
    hb_stop.clear()
    hb_thread = threading.Thread(target=heartbeat, daemon=True)
    hb_thread.start()
    time.sleep(0.5)

    url = args.url or start_preview(args)
    if not url:
        hb_stop.set()
        sys.exit(2)

    t_open = time.time()
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print("[스트림] 열기 실패: %s" % url)
        send("camera._stopPreview", {})
        hb_stop.set()
        sys.exit(3)
    print("[스트림] 열림 %.2fs" % (time.time() - t_open))

    latest = Latest()
    stop = threading.Event()
    rstat = {"read_ok": 0, "read_fail": 0}
    th = threading.Thread(target=reader, args=(cap, latest, stop, rstat), daemon=True)
    th.start()

    sess = requests.Session()
    ages, encs, ups, totals = [], [], [], []
    n_up = 0
    t_start = time.time()
    period = 1.0 / args.fps
    next_t = time.time()

    def bye(sig, frm):
        global _running
        _running = False
    signal.signal(signal.SIGINT, bye)

    print("\n프레임나이 = 카메라에서 받은 뒤 집을 때까지 기다린 시간 (작을수록 실시간)")
    print("PC구간     = 나이 + JPEG인코딩 + 업로드\n")

    while _running and (args.count == 0 or n_up < args.count):
        now = time.time()
        if now < next_t:
            time.sleep(min(0.005, next_t - now))
            continue
        next_t += period
        if next_t < now:                      # 밀렸으면 따라잡지 말고 현재로 리셋
            next_t = now + period

        frame, t_frame, seq = latest.take()
        if frame is None:
            continue

        age = now - t_frame
        t0 = time.perf_counter()
        ok, buf = cv2.imencode(".jpg", frame,
                               [int(cv2.IMWRITE_JPEG_QUALITY), args.quality])
        t_enc = time.perf_counter() - t0
        if not ok:
            continue
        data = buf.tobytes()

        cap_id = (args.capture_id if args.rotate <= 0
                  else "%s_%02d" % (args.capture_id, n_up % args.rotate))

        t1 = time.perf_counter()
        if args.dry_run:
            t_up = 0.0
            status = "dry"
        else:
            try:
                r = sess.post(args.upload,
                              data={"capture_id": cap_id,
                                    "camera_id": args.camera_id},
                              files={"file": ("equirect.jpg", data, "image/jpeg")},
                              timeout=15)
                status = r.json().get("status", "?")
            except Exception as e:
                status = "ERR:%s" % str(e)[:40]
            t_up = time.perf_counter() - t1

        n_up += 1
        tot = age + t_enc + t_up
        ages.append(age); encs.append(t_enc); ups.append(t_up); totals.append(tot)
        print("  #%-4d 나이 %5.0fms  인코딩 %4.0fms  업로드 %5.0fms  | PC구간 %5.0fms"
              "  %4dKB  %s" % (n_up, age*1000, t_enc*1000, t_up*1000, tot*1000,
                               len(data)//1024, status))

    # ── 정리 ──
    stop.set()
    send("camera._stopPreview", {})   # 스트림을 끊어야 read() 가 즉시 반환된다
    th.join(timeout=3.0)              # 리더가 스스로 cap.release() 하고 빠져나감
    hb_stop.set()

    el = time.time() - t_start
    print("\n" + "=" * 70)
    print("종료 — %.1f초 동안 %d장 업로드 (%.2f fps 실측)" % (el, n_up, n_up/el if el else 0))
    print("  리더 스레드 수신 %d프레임 (%.1f fps), read 실패 %d"
          % (rstat["read_ok"], rstat["read_ok"]/el if el else 0, rstat["read_fail"]))
    print("  버린 프레임 %d장  ← 목표 fps 로 솎아낸 결과 (정상)" % latest.dropped)
    if totals:
        def s(v):
            v = sorted(v)
            return (statistics.median(v)*1000, v[int(len(v)*0.9)]*1000, v[-1]*1000)
        for name, v in [("프레임 나이", ages), ("JPEG 인코딩", encs),
                        ("업로드", ups), ("PC 구간 합계", totals)]:
            m, p90, mx = s(v)
            print("  %-12s 중앙 %6.0fms   p90 %6.0fms   최대 %6.0fms" % (name, m, p90, mx))
        print("\n  ※ 종단 지연 = 위 'PC 구간 합계' + 서버 live.py 감시주기 + live 총처리시간")
    print("=" * 70)


if __name__ == "__main__":
    main()
