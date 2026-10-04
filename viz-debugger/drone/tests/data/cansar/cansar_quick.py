#!/usr/bin/env python3
"""
CANSAR-2 현장 quick-look (2026-10-02)  —  받기 + 시각 매칭 + 역투영을 한 번에
  py -3.12 cansar_quick.py --pi physical@10.176.68.116 --side right          # Pi 의 최신 패스
  py -3.12 cansar_quick.py --pi physical@10.176.68.116 --n 163150            # 특정 번호
  py -3.12 cansar_quick.py --nopull --n 163150                                # 이미 받은 파일만 처리
  py -3.12 cansar_quick.py ... --fine                                         # 정밀(dec 4, 0.25 m, 시각 스캔) — 느림

동작
  1. Pi ~/flight 에서 최신(또는 --n) iq_N.bin / meta_N.txt 를 작업 폴더로 (이미 같은 크기면 건너뜀)
  2. Pi ~/cansar_logs/*/passes.csv 에서 N 이 들어 있는 로그 폴더를 찾아 통째로 받음 → 판정 줄 출력
  3. 그 폴더 events.csv 의 start 행 중 passes.csv 의 t0 와 맞는 것 → cansar_flight.py --ev 자동 결정
  4. cansar_flight.py 실행 → flight_img.png 를 quick_N.png 로 복사하고 열기
"""
import argparse, csv, os, shutil, subprocess, sys, glob

ap = argparse.ArgumentParser()
ap.add_argument('--pi', default='physical@10.176.68.116')
ap.add_argument('--n', type=int, default=None, help='캡처 번호 (없으면 최신)')
ap.add_argument('--side', default='right', choices=['right', 'left', 'both'], help='안테나가 보는 쪽')
ap.add_argument('--nopull', action='store_true', help='Pi 에서 받지 않고 작업 폴더 파일만 처리')
ap.add_argument('--fine', action='store_true', help='정밀 처리 (dec 4, res 0.25, 시각 오프셋 스캔)')
ap.add_argument('--flight', default='cansar_flight.py')
ap.add_argument('--noopen', action='store_true')
ap.add_argument('--data-dir', default='.', help='--nopull 일 때 iq_N.bin / meta_N.txt 가 있는 폴더 (Pi 에서는 /home/physical/flight)')
ap.add_argument('--logs-root', default='cansar_logs', help='--nopull 일 때 로그 폴더들의 상위 폴더 (Pi 에서는 /home/physical/cansar_logs)')
ap.add_argument('extra', nargs=argparse.REMAINDER, help='-- 뒤 인자는 cansar_flight.py 로 그대로 전달')
a = ap.parse_args()
os.environ['PYTHONIOENCODING'] = 'utf-8'
if not os.path.exists(a.flight):   # 작업 폴더에 없으면 이 스크립트와 같은 폴더에서 찾기
    a.flight = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.path.basename(a.flight))

def sh(cmd):  # 원격 명령 → stdout
    r = subprocess.run(['ssh', a.pi, cmd], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0: print('[ssh]', r.stderr.strip()[:200])
    return r.stdout.strip()

def scp(src, dst, rec=False):
    r = subprocess.run(['scp'] + (['-r'] if rec else []) + [f'{a.pi}:{src}', dst])
    return r.returncode == 0

# ── 1. 파일 ──
DD = a.data_dir if a.nopull else '.'
if a.nopull:
    if a.n is None:
        cands = sorted(glob.glob(os.path.join(DD, 'iq_*.bin')), key=os.path.getmtime)
        if not cands: sys.exit(f'{DD} 에 iq_*.bin 없음')
        a.n = int(os.path.basename(cands[-1])[3:-4])
else:
    if a.n is None:
        last = sh("ls -t ~/flight/iq_*.bin 2>/dev/null | head -1")
        if not last: sys.exit('Pi ~/flight 에 iq 파일 없음 (자동 복사 전이거나 캡처 없음)')
        a.n = int(os.path.basename(last)[3:-4])
    rsize = sh(f"stat -c %s ~/flight/iq_{a.n}.bin")
    loc = f'iq_{a.n}.bin'
    if os.path.exists(loc) and rsize.isdigit() and os.path.getsize(loc) == int(rsize):
        print(f'iq_{a.n}.bin 이미 있음 — 건너뜀')
    else:
        print(f'받는 중 iq_{a.n}.bin ({int(rsize)/1e6:.0f} MB)' if rsize.isdigit() else f'받는 중 iq_{a.n}.bin')
        if not scp(f'flight/iq_{a.n}.bin', '.'): sys.exit('iq 받기 실패')
    scp(f'flight/meta_{a.n}.txt', '.')
N = a.n
IQ, META = os.path.join(DD, f'iq_{N}.bin'), os.path.join(DD, f'meta_{N}.txt')
if not os.path.exists(IQ) or not os.path.exists(META):
    sys.exit(f'{IQ} 또는 {META} 없음')

# ── 2. 로그 폴더 ──
logdir = None
if not a.nopull:
    hit = sh(f"grep -l '^{N},' ~/cansar_logs/*/passes.csv 2>/dev/null | tail -1")
    if hit:
        name = hit.split('/')[-2]
        os.makedirs('cansar_logs', exist_ok=True)
        if scp(f'cansar_logs/{name}', 'cansar_logs/', rec=True): logdir = os.path.join('cansar_logs', name)
if logdir is None:   # 로컬에서 찾기
    for p in sorted(glob.glob(os.path.join(a.logs_root if a.nopull else 'cansar_logs', '*', 'passes.csv')), key=os.path.getmtime, reverse=True):
        if any(r.get('n') == str(N) for r in csv.DictReader(open(p, encoding='utf-8'))):
            logdir = os.path.dirname(p); break
if logdir is None: sys.exit(f'passes.csv 에 #{N} 이 있는 로그 폴더를 못 찾음')

row = next(r for r in csv.DictReader(open(os.path.join(logdir, 'passes.csv'), encoding='utf-8')) if r['n'] == str(N))
print(f"\n[판정] #{N}  {row['dur_s']} s  {row['MBps']} MB/s  위치 {row['pos_hz']} Hz  속도 {row['v_mean']}±{row['v_std']} m/s  "
      f"고도 {row['alt_mean']} m  방향 {row['track_deg']}°  직선 {row['straight']}  헤딩std {row['yaw_std_deg']}°  → {row['verdict']}")

# ── 3. events 매칭 ──
t0 = float(row['t0'])
starts = [r for r in csv.DictReader(open(os.path.join(logdir, 'events.csv'), encoding='utf-8')) if r['event'] == 'start']
if not starts: sys.exit('events.csv 에 start 없음')
ev = min(range(len(starts)), key=lambda i: abs(float(starts[i]['pi_epoch']) - t0))
dt = abs(float(starts[ev]['pi_epoch']) - t0)
print(f"[시각] events start #{ev} (pi_epoch 차 {dt:.3f} s)" + ("  [!] 1 s 넘게 어긋남 — 확인 필요" if dt > 1 else ""))

# ── 4. 역투영 ──
opt = ['--dec', '4', '--res', '0.25', '--tscan', '-1', '1', '0.2'] if a.fine else ['--dec', '8', '--res', '0.5']
extra = [x for x in a.extra if x != '--']
cmd = [sys.executable, a.flight, '--iq', IQ, '--meta', META, '--logs', logdir,
       '--ev', str(ev), '--side', a.side, '--demean'] + opt + extra
print('[실행]', ' '.join(cmd[1:]), '\n')
r = subprocess.run(cmd)
if r.returncode != 0: sys.exit('cansar_flight.py 실패')
out = f'quick_{N}{"_fine" if a.fine else ""}.png'
shutil.copy('flight_img.png', out); shutil.copy('flight_img.npz', out[:-4] + '.npz')
print(f'\n→ {out}')
if not a.noopen:
    try: os.startfile(out)                       # Windows
    except AttributeError: subprocess.run(['xdg-open', out])
    except Exception: pass
