"""
pro2_auto_bg.py — Pro2 연속 자동화 (백그라운드 stitch)

[구조]
  메인 스레드:   촬영 → 완료대기 → 다운로드(RAM) → 디스크저장
                 → stitch+upload 작업을 큐에 넣고 즉시 다음 촬영
  워커 스레드(1): 큐에서 작업 꺼내 stitch → 서버 전송 (순차, 하나씩)

  촬영계열(~20s) > stitch+upload(~14s) 이므로 stitch가 다음 촬영에 숨겨짐.
  GTX 1080 메모리 보호 위해 워커는 1개 (동시 stitch 금지).

[모드]
  --interval 0   : 연속 (촬영 끝나면 바로 다음, 방식1)
  --interval 60  : 60초 고정 주기 (방식2, 논문용)
  --count 5      : 5장 찍고 종료 (기본 0 = 무한, Ctrl+C로 종료)

[종료]
  Ctrl+C → 진행 중인 촬영 마치고, 큐에 남은 stitch 작업 모두 완료 후 종료.

[의존]
  같은 폴더에 stitch_prostitcher.py / 서버 pano_receiver.py(7866) 실행 중

[TRT 캐시]
  실행 시 sync_trt_cache()가 %TEMP%의 ProStitcher 엔진 캐시를 백업 폴더와
  동기화한다. %TEMP%가 비어 있으면 백업에서 복원하여 콜드 빌드(~19분)를 방지.

[실행]
  python pro2_auto_bg.py --count 3            (3장, 연속)
  python pro2_auto_bg.py --interval 60         (1분 주기, 무한)
"""

import os
import io
import time
import glob
import queue
import shutil
import argparse
import threading
import requests
import datetime
from concurrent.futures import ThreadPoolExecutor

from stitch_prostitcher import stitch_folder, DEFAULT_STITCHER

# =========================================================
CAMERA_IP = "192.168.100.124"
SERVER_IP = "210.110.250.33"
SERVER_PORT = 7866
SERVER_UPLOAD_URL = f"http://{SERVER_IP}:{SERVER_PORT}/upload_pano"
CAMERA_ID = "pro2_anchor"

CMD_URL = f"http://{CAMERA_IP}:20000/osc/commands/execute"
STATE_URL = f"http://{CAMERA_IP}:20000/osc/state"
FILE_BASE = f"http://{CAMERA_IP}:8000"

DOWNLOAD_FILES = [
    "origin_1.jpg", "origin_2.jpg", "origin_3.jpg",
    "origin_4.jpg", "origin_5.jpg", "origin_6.jpg",
    "pro.prj", "gyro.mp4",
]
LOCAL_BASE = "captures"

# stitch 설정 (전역, main에서 채움)
STITCH_CFG = {"width": 3840, "height": 1920, "mode": "ai",
              "topfixer": 1, "blender": "auto"}

fingerprint = None
heartbeat_stop = threading.Event()
heartbeat_thread = None
T0 = time.time()

# 백그라운드 작업 큐 + 통계
task_queue = queue.Queue()
stop_worker = threading.Event()
stats_lock = threading.Lock()
stats = {"shot": 0, "stitched": 0, "uploaded": 0, "failed": 0}


# ── TRT 엔진 캐시 자동 복원/백업 ──────────────────────────
#  ProStitcher(CLI/GUI)가 실제로 읽는 엔진 캐시는 %TEMP% 한 곳뿐이다.
#  %TEMP%가 비면(저장소 센스/재부팅/드라이버 교체 등) 콜드 빌드(~19분)가
#  다시 걸리므로, 실행 시마다 백업 폴더와 동기화해 이를 방지한다.
#    - %TEMP%에 엔진이 없고 백업에 있으면  → 복원 (콜드 빌드 방지)
#    - %TEMP%에 최신 엔진이 있으면          → 백업 갱신 (재빌드 후 자동 보존)
#  ※ _TRT_BACKUP_DIR 경로는 이 PC(asdfa 계정) 기준. 계정/경로 바뀌면 수정.
_TRT_BACKUP_DIR = r"C:\Users\asdfa\docx2026_code\trt_cache"
_TRT_GLOB = "*_fp16.trt"


def sync_trt_cache():
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    if not temp_dir:
        print("[trt] TEMP 환경변수 없음 — 캐시 동기화 생략")
        return
    try:
        os.makedirs(_TRT_BACKUP_DIR, exist_ok=True)
    except Exception as e:
        print(f"[trt] 백업 폴더 준비 실패({e}) — 캐시 동기화 생략")
        return

    def _valid(p):
        try:
            return os.path.getsize(p) > 0      # 0바이트/손상 파일 제외
        except OSError:
            return False

    # 1) 복원: %TEMP%에 없고 백업에 있으면 되돌림
    for bkp in glob.glob(os.path.join(_TRT_BACKUP_DIR, _TRT_GLOB)):
        if not _valid(bkp):
            continue
        dst = os.path.join(temp_dir, os.path.basename(bkp))
        if not _valid(dst):
            try:
                shutil.copy2(bkp, dst)
                print(f"[trt] 캐시 복원: {os.path.basename(dst)}")
            except Exception as e:
                print(f"[trt] 복원 실패 {os.path.basename(bkp)}: {e}")

    # 2) 백업 갱신: %TEMP%에 최신 엔진이 생겼으면 백업으로 보존
    for src in glob.glob(os.path.join(temp_dir, _TRT_GLOB)):
        if not _valid(src):
            continue
        dst = os.path.join(_TRT_BACKUP_DIR, os.path.basename(src))
        if (not os.path.exists(dst)) or (os.path.getmtime(src) > os.path.getmtime(dst) + 1):
            try:
                shutil.copy2(src, dst)
                print(f"[trt] 백업 갱신: {os.path.basename(dst)}")
            except Exception as e:
                print(f"[trt] 백업 실패 {os.path.basename(src)}: {e}")


def ts():
    return f"[+{time.time() - T0:6.1f}s]"


# ── 헤더 / 하트비트 ──────────────────────────────────────
def get_headers():
    h = {"Content-Type": "application/json"}
    if fingerprint:
        h["Fingerprint"] = fingerprint
    return h


def heartbeat():
    while not heartbeat_stop.is_set():
        try:
            requests.post(STATE_URL, json={}, headers=get_headers(), timeout=3)
        except Exception:
            pass
        time.sleep(1)


def start_heartbeat():
    global heartbeat_thread
    heartbeat_stop.clear()
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()


def stop_heartbeat():
    heartbeat_stop.set()
    if heartbeat_thread:
        heartbeat_thread.join(timeout=3)


# ── 카메라 ───────────────────────────────────────────────
def connect_camera(max_retry=3):
    global fingerprint
    for attempt in range(1, max_retry + 1):
        try:
            resp = requests.post(CMD_URL, json={
                "name": "camera._connect", "parameters": {}}, timeout=10)
            fp = resp.json().get("results", {}).get("Fingerprint")
            if fp:
                fingerprint = fp
                print(f"{ts()} camera connected")
                return True
            time.sleep(1.5)
        except Exception as e:
            print(f"{ts()} connect error: {e}")
            time.sleep(1.5)
    return False


def take_picture():
    resp = requests.post(CMD_URL, json={
        "name": "camera._takePicture",
        "parameters": {"origin": {"mime": "jpeg", "width": 4000,
                                  "height": 3000, "saveOrigin": True}}
    }, headers=get_headers(), timeout=120)
    return resp.json().get("sequence")


def wait_for_sequence(seq_id, timeout=90):
    stop_heartbeat()
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.post(STATE_URL, json={}, headers=get_headers(), timeout=5)
            if seq_id in resp.json().get("state", {}).get("_idRes", []):
                start_heartbeat()
                return True
        except Exception:
            pass
        time.sleep(0.5)
    start_heartbeat()
    return False


def get_result(seq_id):
    resp = requests.post(CMD_URL, json={
        "name": "camera._getResult", "parameters": {"list_ids": [seq_id]}
    }, headers=get_headers(), timeout=10)
    try:
        return (resp.json()["results"]["res_array"][0]
                ["results"]["results"]["_picUrl"])
    except Exception:
        return None


def _download_one(args):
    filename, folder_path = args
    url = FILE_BASE + folder_path + "/" + filename
    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 200:
            buf = io.BytesIO()
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                buf.write(chunk)
            buf.seek(0)
            return filename, buf
        return filename, None
    except Exception:
        return filename, None


def download_all(folder_path):
    args = [(fn, folder_path) for fn in DOWNLOAD_FILES]
    buffers = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for fn, buf in ex.map(_download_one, args):
            if buf:
                buffers[fn] = buf
    return buffers


def save_to_disk(buffers, capture_id):
    local_dir = os.path.join(LOCAL_BASE, capture_id)
    os.makedirs(local_dir, exist_ok=True)
    for fn, buf in buffers.items():
        buf.seek(0)
        with open(os.path.join(local_dir, fn), "wb") as f:
            f.write(buf.read())
    return os.path.abspath(local_dir)


def upload_stitched(equirect_path, capture_id):
    try:
        with open(equirect_path, "rb") as f:
            files = {"file": ("equirect.jpg", f, "image/jpeg")}
            form = {"capture_id": capture_id, "camera_id": CAMERA_ID}
            resp = requests.post(SERVER_UPLOAD_URL, files=files, data=form, timeout=60)
        return resp.status_code == 200
    except Exception as e:
        print(f"{ts()} [worker] upload error: {e}")
        return False


# ── 백그라운드 워커 (stitch + upload) ────────────────────
def worker():
    while not (stop_worker.is_set() and task_queue.empty()):
        try:
            local_dir, capture_id = task_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            equirect = os.path.join(local_dir, "equirect.jpg")
            t0 = time.time()
            result, st = stitch_folder(
                local_dir, equirect,
                STITCH_CFG["width"], STITCH_CFG["height"],
                STITCH_CFG["blender"], DEFAULT_STITCHER,
                mode=STITCH_CFG["mode"], top_fixer=STITCH_CFG["topfixer"],
                verbose=False)
            if not result:
                print(f"{ts()} [worker] ❌ stitch failed: {capture_id}")
                with stats_lock:
                    stats["failed"] += 1
                continue
            with stats_lock:
                stats["stitched"] += 1
            print(f"{ts()} [worker] stitched {capture_id} ({st:.1f}s)")

            if upload_stitched(equirect, capture_id):
                with stats_lock:
                    stats["uploaded"] += 1
                print(f"{ts()} [worker] ✅ uploaded {capture_id} "
                      f"(total {time.time()-t0:.1f}s)")
            else:
                with stats_lock:
                    stats["failed"] += 1
                print(f"{ts()} [worker] ❌ upload failed: {capture_id}")
        finally:
            task_queue.task_done()


# ── 메인 루프 (촬영) ─────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=0, help="촬영 장수 (0=무한)")
    ap.add_argument("--interval", type=float, default=0,
                    help="촬영 주기(초). 0=연속(촬영 끝나면 바로)")
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--mode", default="ai", choices=["ai", "optical", "template"])
    ap.add_argument("--topfixer", type=int, default=1, choices=[0, 1])
    ap.add_argument("--blender", default="auto")
    args = ap.parse_args()

    STITCH_CFG.update(width=args.width, height=args.height, mode=args.mode,
                      topfixer=args.topfixer, blender=args.blender)

    print("=" * 55)
    print("pro2 auto (background stitch)")
    print(f"  count={args.count or '무한'}, interval={args.interval}s")
    print(f"  stitch: {args.mode}, tf={args.topfixer}, {args.width}x{args.height}")
    print("  Ctrl+C로 종료 (남은 stitch 작업 마치고 정리)")
    print("=" * 55)

    # TRT 엔진 캐시 복원/백업 (콜드 빌드 방지). stitch보다 먼저 실행.
    sync_trt_cache()

    start_heartbeat()
    if not connect_camera():
        raise SystemExit("camera connect failed")

    # 워커 시작
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    n = 0
    try:
        while args.count == 0 or n < args.count:
            cycle_start = time.time()
            n += 1
            print(f"\n{ts()} ── 촬영 #{n} ──")

            seq = take_picture()
            if not (seq and wait_for_sequence(seq)):
                print(f"{ts()} 촬영 #{n} 실패, 건너뜀")
                continue

            folder_path = get_result(seq)
            if not folder_path:
                print(f"{ts()} get_result 실패, 건너뜀")
                continue
            capture_id = folder_path.rstrip("/").split("/")[-1]
            capture_id = f"{capture_id}__{datetime.datetime.now():%Y%m%d_%H%M%S}"

            buffers = download_all(folder_path)
            local_dir = save_to_disk(buffers, capture_id)
            with stats_lock:
                stats["shot"] += 1

            # 백그라운드로 stitch+upload 던지기 (안 기다림)
            qsize = task_queue.qsize()
            task_queue.put((local_dir, capture_id))
            cap_elapsed = time.time() - cycle_start
            print(f"{ts()} 촬영 #{n} 완료 → 큐에 추가 ({capture_id}, "
                  f"촬영계열 {cap_elapsed:.1f}s, 큐 대기 {qsize})")

            # 큐가 계속 쌓이면 경고 (stitch가 촬영보다 느린 경우)
            if qsize >= 3:
                print(f"{ts()} ⚠️ 큐 {qsize}개 적체 — stitch가 촬영을 못 따라감")

            # interval 처리
            if args.interval > 0:
                sleep_t = args.interval - (time.time() - cycle_start)
                if sleep_t > 0:
                    time.sleep(sleep_t)

    except KeyboardInterrupt:
        print(f"\n{ts()} 종료 요청 — 큐에 남은 작업 마무리 중...")

    # 정리: 큐 비우고 워커 종료
    print(f"{ts()} 남은 stitch 작업 {task_queue.qsize()}개 처리 대기...")
    task_queue.join()
    stop_worker.set()
    worker_thread.join(timeout=5)
    stop_heartbeat()

    print("\n" + "=" * 55)
    print("종료 통계")
    print(f"  촬영: {stats['shot']} / stitch: {stats['stitched']} / "
          f"업로드: {stats['uploaded']} / 실패: {stats['failed']}")
    print("=" * 55)


if __name__ == "__main__":
    main()
