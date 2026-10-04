#!/usr/bin/env python3
"""
CANSAR-2 Raspberry Pi 브리지  v3 (2026-10-02) + 드론 쪽 제안(2026-10-04, `# [드론 쪽 제안 10/4]` 표시한 줄만 바뀜)
  ① CAP_ACK: SDR 이 캡처를 실제로 켠 직후 ~/CAP_ACK 에 그 시각, 끈 직후 지움(--ack, '' = 끔)
  ② 시계 짝: events.csv 의 pi_epoch 를 SSH **응답 시각**으로(SDR 이 uptime 을 읽은 순간에 가깝다 — 요청 시각은 note 에 req=).
     캡처 중 1 초마다 `clock` 행(왕복 가운데 시각 ↔ SDR uptime, note 에 rtt=)
  ③ SSH 연결을 한 번 열어 두고 다시 씀(ControlMaster) — 명령마다 접속하던 수백 ms 지연 · 들쭉날쭉을 없앤다
  ④ passes.csv 끝에 pass · flight 두 칸 — 드론 비행 프로그램이 CAP_ON 안에 적은 JSON 에서
  python cansar_pi.py --conn udp:127.0.0.1:14551          # 기본: ~/CAP_ON 파일 트리거 (Pi 팀 코드가 touch/rm)
  python cansar_pi.py --conn none --key                   # FC 없이 키보드(Enter)로 켜고 끄기 시험

동작
  · MAVLink 수신 → mav.csv. 주기 요청(위치 30·자세 10·GPS 5·시각 1 Hz)만 30 s 마다 송신, 그 외 송신 없음
  · ~/CAP_ON 이 있으면 SDR /tmp/CAP_ON 생성(캡처), 없으면 삭제 → events.csv 에 Pi 시각↔SDR uptime
  · 캡처가 끝날 때마다
      ① 패스 판정 한 줄 (길이·MB/s·위치 주기·속도·고도·직선성·헤딩 흔들림 → OK / 재비행?) → passes.csv
      ② SDR SD → ~/flight/ 자동 복사. 다음 캡처가 시작되면 즉시 중단, 끝나면 다시 이어서
  · RTK 보정 중계: 노트북 cansar_rtcm_send.py 가 UDP(--rtcm-port, 기본 14660)로 보낸 RTCM 을
      GPS_RTCM_DATA 로 감싸 FC 에 주입 (Mission Planner RTK Inject 와 같은 일)
  · 패스 판정에 RTK 조건 추가: 패스 내내 fix_type 6, 시작 시점에 Fixed 지속 ≥ --rtkmin s(기본 30)
  · --rc N (기본 0 = 끔), --wp S E (기본 끔) 은 옛 트리거, 필요할 때만
로그: ~/cansar_logs/<날짜시각>/  mav.csv, events.csv, passes.csv, pi.log      데이터: ~/flight/iq_N.bin, meta_N.txt
"""
import argparse, csv, os, subprocess, sys, time, threading, datetime, select, re, math, queue, collections, shutil

ap = argparse.ArgumentParser()
ap.add_argument('--conn', default='udp:127.0.0.1:14551'); ap.add_argument('--baud', type=int, default=921600)
ap.add_argument('--rc', type=int, default=0, help='캡처 스위치 RC 채널 (0 = 끔)'); ap.add_argument('--thr', type=int, default=1500)
ap.add_argument('--sdr', default='192.168.3.1'); ap.add_argument('--pw', default='analog')
ap.add_argument('--key', action='store_true', help='키보드 Enter 로 토글 (FC 없이 시험)')
ap.add_argument('--status', type=float, default=30.0)
ap.add_argument('--wp', type=int, nargs=2, default=None, help='미션 WP 도달 트리거: 시작 WP 정지 WP')
ap.add_argument('--file', default='/home/physical/CAP_ON', help='이 파일이 있으면 캡처')
ap.add_argument('--flight', default='/home/physical/flight', help='자동 복사 폴더')
ap.add_argument('--nocopy', action='store_true', help='자동 복사 끄기')
# 판정 기준
ap.add_argument('--vmin', type=float, default=3.0); ap.add_argument('--yawmax', type=float, default=5.0)
ap.add_argument('--hzmin', type=float, default=4.0); ap.add_argument('--durmin', type=float, default=8.0)
ap.add_argument('--rtcm-port', type=int, default=14660, help='RTCM 수신 UDP 포트 (0 = 끔)')
ap.add_argument('--rtkmin', type=float, default=30.0, help='패스 시작 전 Fixed 지속 최소 시간 [s]')
ap.add_argument('--ack', default='/home/physical/CAP_ACK', help="SDR 캡처가 실제로 켜지면 시각을 적는 파일 ('' = 끔)")  # [드론 쪽 제안 10/4]
ap.add_argument('--clock', type=float, default=1.0, help='캡처 중 시계 짝 간격 [s] (0 = 끔)')                         # [드론 쪽 제안 10/4]
a = ap.parse_args()

D = os.path.expanduser('~/cansar_logs/' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')); os.makedirs(D, exist_ok=True)
os.makedirs(a.flight, exist_ok=True)
plog = open(D + '/pi.log', 'a')
def log(*x):
    s = f"[{time.time():.3f}] " + " ".join(str(i) for i in x); print(s, flush=True); plog.write(s + "\n"); plog.flush()

OPT = ['-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null', '-o', 'LogLevel=ERROR', '-o', 'ConnectTimeout=3',
       '-o', 'ControlMaster=auto', '-o', 'ControlPath=/tmp/cansar-ssh-%r@%h:%p', '-o', 'ControlPersist=600']   # [드론 쪽 제안 10/4] ③
SSH = ['sshpass', '-p', a.pw, 'ssh'] + OPT + [f'root@{a.sdr}']
SCP = ['sshpass', '-p', a.pw, 'scp', '-O'] + OPT
def sdr(cmd, timeout=6):
    try: return subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e: return f"ERR {e}"

def sdr_timed(cmd, timeout=6):                                                       # [드론 쪽 제안 10/4] ②
    """→ (출력, 보낸 시각, 응답 시각). SDR 이 명령을 실행한 순간은 접속 뒤라 응답 시각에 가깝다."""
    tb = time.time(); out = sdr(cmd, timeout); return out, tb, time.time()

def cap_info():                                                                      # [드론 쪽 제안 10/4] ④
    """CAP_ON 안의 JSON(드론 비행 프로그램이 적음: pass · flight). 비었거나 JSON 이 아니면 {}."""
    try:
        import json
        with open(a.file, encoding='utf-8') as fh: return json.loads(fh.read() or '{}')
    except Exception: return {}

# ── 위치·자세 버퍼 (판정용) ──
lock = threading.Lock()
POS = collections.deque(maxlen=200000)   # (t, x=N, y=E, z=D, vx, vy)
ATT = collections.deque(maxlen=200000)   # (t, yaw rad)
GPSF = collections.deque(maxlen=50000)   # (t, fix_type)
rtcm_stat = {'bytes': 0, 'frames': 0, 'last': 0.0, 'msgs': 0}
sendlock = threading.Lock()

# ── 캡처 제어 ──
evf = open(D + '/events.csv', 'w', newline=''); ev = csv.writer(evf)
ev.writerow(['event', 'pi_epoch', 'pi_mono', 'sdr_uptime', 'note']); evf.flush()
evlock = threading.Lock()                                                            # [드론 쪽 제안 10/4] 시계 행을 다른 스레드가 같이 쓴다
capturing = False; cap_t0 = None; cap_meta = {}
jobs = queue.Queue()
def set_capture(on, note=''):
    global capturing, cap_t0, cap_meta
    if on == capturing: return
    t0 = time.time()
    if on and not a.key: cap_meta = cap_info()                                       # [드론 쪽 제안 10/4] ④
    up, tb, ta = sdr_timed(('touch' if on else 'rm -f') + ' /tmp/CAP_ON; cut -d" " -f1 /proc/uptime')
    m1 = time.monotonic()
    with evlock:                                                                     # [드론 쪽 제안 10/4] ② pi_epoch = 응답 시각
        ev.writerow(['start' if on else 'stop', f"{ta:.6f}", f"{m1:.6f}", up, f"{note} req={tb:.6f} rtt={ta - tb:.3f}"]); evf.flush()
    capturing = on; log('CAPTURE', 'ON' if on else 'OFF', 'sdr_uptime', up, note, f'rtt {ta - tb:.3f}s')
    if a.ack:                                                                        # [드론 쪽 제안 10/4] ①
        try:
            if on and not up.startswith('ERR'):
                tmp = a.ack + '.tmp'
                with open(tmp, 'w') as fh: fh.write(f"{ta:.6f}\n")
                os.replace(tmp, a.ack)
            elif not on and os.path.exists(a.ack): os.remove(a.ack)
        except OSError as e: log('CAP_ACK 오류', e)
    if on: cap_t0 = t0
    elif cap_t0 is not None: jobs.put((cap_t0, t0, cap_meta)); cap_t0 = None; cap_meta = {}   # [드론 쪽 제안 10/4] ④

def clock_loop():                                                                    # [드론 쪽 제안 10/4] ②
    """캡처 중 a.clock 초마다 (왕복 가운데 Pi 시각 ↔ SDR uptime). 영상 처리가 두 시계의 어긋남 · 흐름을 직선으로 맞춘다."""
    while True:
        time.sleep(a.clock)
        if not capturing: continue
        up, tb, ta = sdr_timed('cut -d" " -f1 /proc/uptime', timeout=2)
        if up.startswith('ERR') or not up: continue
        with evlock:
            ev.writerow(['clock', f"{(tb + ta) / 2:.6f}", f"{time.monotonic():.6f}", up, f"rtt={ta - tb:.3f}"]); evf.flush()
if a.clock > 0:
    threading.Thread(target=clock_loop, daemon=True).start()

# ── 패스 판정 ──
pf = open(D + '/passes.csv', 'w', newline=''); pcsv = csv.writer(pf)
pcsv.writerow(['n', 't0', 't1', 'dur_s', 'MB', 'MBps', 'pos_n', 'pos_hz', 'v_mean', 'v_std', 'alt_mean', 'alt_std',
               'track_deg', 'straight', 'yaw_std_deg', 'fix_min', 'fixed_before_s', 'verdict', 'pass', 'flight']); pf.flush()   # [드론 쪽 제안 10/4] ④

def _mean(x): return sum(x) / len(x)
def _std(x):
    m = _mean(x); return math.sqrt(sum((i - m) ** 2 for i in x) / len(x))

def judge(n, size, t0, t1, info=None):                                              # [드론 쪽 제안 10/4] ④
    dur = t1 - t0; mb = size / 1e6; mbps = mb / dur if dur > 0 else 0
    with lock:
        P = [p for p in POS if t0 <= p[0] <= t1]; Y = [y for (t, y) in ATT if t0 <= t <= t1]
    bad = []
    hz = len(P) / dur if dur > 0 else 0
    v = vs = am = asd = trk = st = float('nan')
    if len(P) >= 3:
        sp = [math.hypot(p[4], p[5]) for p in P]; v, vs = _mean(sp), _std(sp)
        al = [-p[3] for p in P]; am, asd = _mean(al), _std(al)
        L = sum(math.hypot(P[i + 1][1] - P[i][1], P[i + 1][2] - P[i][2]) for i in range(len(P) - 1))
        dn, de = P[-1][1] - P[0][1], P[-1][2] - P[0][2]
        st = math.hypot(dn, de) / L if L > 0 else 0
        trk = math.degrees(math.atan2(de, dn)) % 360
    ysd = float('nan')
    if len(Y) >= 3:
        R = math.hypot(_mean([math.cos(y) for y in Y]), _mean([math.sin(y) for y in Y]))
        ysd = math.degrees(math.sqrt(max(0.0, -2 * math.log(max(R, 1e-12)))))
    if dur < a.durmin: bad.append(f'짧음 {dur:.1f}s')
    if not (3.5 <= mbps <= 4.2): bad.append(f'MB/s {mbps:.2f}')
    if hz < a.hzmin: bad.append(f'위치 {hz:.1f}Hz')
    if not math.isnan(v) and v < a.vmin: bad.append(f'느림 {v:.1f}m/s')
    if not math.isnan(st) and st < 0.95: bad.append(f'직선성 {st:.2f}')
    if not math.isnan(ysd) and ysd > a.yawmax: bad.append(f'헤딩흔들림 {ysd:.1f}°')
    if not math.isnan(asd) and asd > 1.0: bad.append(f'고도흔들림 {asd:.1f}m')
    with lock: GF = list(GPSF)
    fmin = None; fb = float('nan')
    if GF:
        inwin = [f for (t, f) in GF if t0 <= t <= t1]
        fmin = min(inwin) if inwin else None
        before = [(t, f) for (t, f) in GF if t <= t0]
        if before and before[-1][1] == 6:
            ts = before[-1][0]
            for (t, f) in reversed(before):
                if f != 6: break
                ts = t
            fb = t0 - ts
        else:
            fb = 0.0
        if fmin is None: bad.append('GPS 기록 없음')
        elif fmin < 6: bad.append(f'RTK 아님(최저 fix {fmin})')
        if fb < a.rtkmin: bad.append(f'Fixed 후 {fb:.0f}s')
    verdict = 'OK' if not bad else '재비행? ' + ', '.join(bad)
    pcsv.writerow([n, f"{t0:.3f}", f"{t1:.3f}", f"{dur:.1f}", f"{mb:.1f}", f"{mbps:.2f}", len(P), f"{hz:.1f}",
                   f"{v:.2f}", f"{vs:.2f}", f"{am:.1f}", f"{asd:.2f}", f"{trk:.0f}", f"{st:.3f}", f"{ysd:.1f}",
                   fmin, f"{fb:.0f}", verdict, (info or {}).get('pass', ''), (info or {}).get('flight', '')]); pf.flush()   # [드론 쪽 제안 10/4] ④
    log(f'PASS #{n}  {dur:.1f}s {mb:.0f}MB ({mbps:.2f}MB/s)  위치 {len(P)}개({hz:.1f}Hz)  속도 {v:.1f}±{vs:.1f}m/s  '
        f'고도 {am:.1f}±{asd:.1f}m  방향 {trk:.0f}°  직선 {st:.2f}  헤딩std {ysd:.1f}°  fix {fmin} (Fixed {fb:.0f}s 전부터)  → {verdict}')

def last_end():
    s = sdr("grep 'end t1' /tmp/cansar2.log | tail -1")
    m = re.search(r'capture #(\d+) end t1=[\d.]+ size=(\d+)', s)
    return (int(m.group(1)), int(m.group(2))) if m else None

def amp_check(path):
    try:
        import numpy as np
        d = np.fromfile(path, dtype=np.int16, count=4 * 1_000_000).reshape(-1, 4).astype(np.float32)
        return f"amp ch0 {np.abs(d[:, 0] + 1j * d[:, 1]).mean():.0f} / ch1 {np.abs(d[:, 2] + 1j * d[:, 3]).mean():.0f}"
    except Exception as e:
        return f"amp 생략({type(e).__name__})"

pending = []   # [n, size, tries]
def try_copy(item):
    n, size, tries = item
    dst = os.path.join(a.flight, f'iq_{n}.bin')
    if os.path.exists(dst) and os.path.getsize(dst) == size:
        pending.remove(item); return
    if shutil.disk_usage(a.flight).free < size * 1.2:
        log('복사 보류: Pi 디스크 여유 부족', n); pending.remove(item); return
    t = time.time()
    p = subprocess.Popen(SCP + [f'root@{a.sdr}:/mnt/sd/iq_{n}.bin', a.flight + '/'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    while p.poll() is None:
        if capturing:
            p.kill(); p.wait(); log(f'복사 중단 #{n} (캡처 시작) — 끝나면 다시'); return
        time.sleep(0.2)
    got = os.path.getsize(dst) if os.path.exists(dst) else -1
    if got == size:
        pending.remove(item); dt = time.time() - t
        try: subprocess.run(SCP + [f'root@{a.sdr}:/mnt/sd/meta_{n}.txt', a.flight + '/'], capture_output=True, timeout=10)
        except Exception as e: log('meta 복사 오류', e)
        if not os.path.exists(os.path.join(a.flight, f'meta_{n}.txt')): log(f'meta_{n}.txt 못 받음 — events.csv 로 시각 복원 가능')
        log(f'복사 완료 #{n}  {size/1e6:.0f}MB {dt:.0f}s ({size/1e6/max(dt,0.1):.1f}MB/s)  {amp_check(dst)}  → {dst}')
    else:
        item[2] += 1
        log(f'복사 실패 #{n} ({got}/{size}) 시도 {item[2]}', p.stderr.read().decode(errors="replace")[:80])
        if item[2] >= 3: pending.remove(item); log(f'복사 포기 #{n} — SD 에서 직접 회수')

seen_end = [None]
def worker():
    e = last_end(); seen_end[0] = e[0] if e else None
    while True:
        try: t0, t1, info = jobs.get(timeout=1)                                      # [드론 쪽 제안 10/4] ④
        except queue.Empty: t0 = None
        if t0 is not None:
            got = None
            for _ in range(30):                       # 파일 닫힘(end 줄) 최대 15 s 대기
                e = last_end()
                if e and e[0] != seen_end[0]: got = e; break
                time.sleep(0.5)
            if got:
                seen_end[0] = got[0]; judge(got[0], got[1], t0, t1, info)                # [드론 쪽 제안 10/4] ④
                if not a.nocopy: pending.append([got[0], got[1], 0])
            else:
                log(f'캡처 파일 없음 ({t1-t0:.1f}s 구간) — 너무 짧았거나 SDR 응답 없음')
        if pending and not capturing:
            try_copy(pending[0])
threading.Thread(target=worker, daemon=True).start()

# ── MAVLink ──
mav = None
RATES = ((32, 30), (30, 10), (24, 5), (2, 1))   # LOCAL_POSITION_NED 30, ATTITUDE 10, GPS_RAW 5, SYSTEM_TIME 1 Hz
def req_rates():
    for mid, hz in RATES:
        try:
            with sendlock: mav.mav.command_long_send(mav.target_system, mav.target_component, 511, 0, mid, int(1e6 / hz), 0, 0, 0, 0, 0)
        except Exception as e: log('interval err', e)
if a.conn != 'none':
    from pymavlink import mavutil
    mav = mavutil.mavlink_connection(a.conn, baud=a.baud, autoreconnect=True)
    log('MAVLink 대기', a.conn); mav.wait_heartbeat(); log('heartbeat sys', mav.target_system)
    req_rates()
mf = open(D + '/mav.csv', 'w', newline=''); mcsv = csv.writer(mf)
mcsv.writerow(['pi_epoch', 'pi_mono', 'msg', 'time_boot_ms', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6'])

def rtcm_loop():
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sk.bind(('0.0.0.0', a.rtcm_port))
    log('RTCM 중계 대기 UDP', a.rtcm_port); seq = 0
    while True:
        data, _ = sk.recvfrom(4096)
        if not data or mav is None: continue
        rtcm_stat['bytes'] += len(data); rtcm_stat['frames'] += 1; rtcm_stat['last'] = time.time()
        chunks = [data[i:i + 180] for i in range(0, len(data), 180)]
        if len(data) > 180 and len(data) % 180 == 0: chunks.append(b'')     # 180 배수면 빈 조각으로 끝 표시
        try:
            with sendlock:
                if len(chunks) == 1:
                    c = chunks[0]; mav.mav.gps_rtcm_data_send((seq & 0x1F) << 3, len(c), c.ljust(180, b'\0')); rtcm_stat['msgs'] += 1
                else:
                    for fi, c in enumerate(chunks):
                        if fi > 3: seq = (seq + 1) & 0x1F; fi = fi % 4       # 4 조각 넘는 프레임: PX4 는 바이트를 이어 붙여 GPS 로 보내므로 그대로 이어서 전송
                        mav.mav.gps_rtcm_data_send(1 | (fi << 1) | ((seq & 0x1F) << 3), len(c), c.ljust(180, b'\0')); rtcm_stat['msgs'] += 1
            seq = (seq + 1) & 0x1F
        except Exception as e:
            log('RTCM 주입 오류', e)
if a.rtcm_port > 0 and a.conn != 'none':
    threading.Thread(target=rtcm_loop, daemon=True).start()

def status_loop():
    while True:
        time.sleep(a.status)
        if mav: req_rates()
        s = sdr("tail -1 /tmp/cansar2.log | cut -c1-40; df -h /mnt/sd | tail -1 | awk '{print $4}'")
        with lock: n = sum(1 for p in POS if p[0] > time.time() - a.status)
        with lock: gf = GPSF[-1][1] if GPSF else None
        rb = rtcm_stat['bytes']; rtcm_stat['bytes'] = 0
        rt = f"RTCM {rb / a.status:.0f}B/s" if rb else ("RTCM 끊김" if rtcm_stat['last'] else "RTCM 없음")
        log('STATUS', ' '.join(s.split())[:49], f'| 위치 {n / a.status:.1f}Hz | fix {gf} | {rt} | 복사대기 {len(pending)}')
threading.Thread(target=status_loop, daemon=True).start()

log('시작  로그 폴더', D, ' SDR', sdr('uptime')[:40], ' 트리거 파일', a.file)
last_rc = None
try:
    while True:
        if a.key:
            r, _, _ = select.select([sys.stdin], [], [], 0.2)
            if r: sys.stdin.readline(); set_capture(not capturing, 'key')
        else:
            fexists = os.path.exists(a.file)
            if fexists != capturing: set_capture(fexists, 'file')
        if mav is None: time.sleep(0.05); continue
        m = mav.recv_match(blocking=True, timeout=0.2)
        if m is None: mf.flush(); continue
        t = time.time(); mo = time.monotonic(); typ = m.get_type()
        if typ == 'GLOBAL_POSITION_INT':
            mcsv.writerow([f"{t:.3f}", f"{mo:.3f}", typ, m.time_boot_ms, m.lat, m.lon, m.alt, m.relative_alt, m.vx, m.vy])
        elif typ == 'LOCAL_POSITION_NED':
            mcsv.writerow([f"{t:.3f}", f"{mo:.3f}", typ, m.time_boot_ms, m.x, m.y, m.z, m.vx, m.vy, m.vz])
            with lock: POS.append((t, m.x, m.y, m.z, m.vx, m.vy))
        elif typ == 'ATTITUDE':
            mcsv.writerow([f"{t:.3f}", f"{mo:.3f}", typ, m.time_boot_ms, m.roll, m.pitch, m.yaw, '', '', ''])
            with lock: ATT.append((t, m.yaw))
        elif typ == 'GPS_RAW_INT':
            mcsv.writerow([f"{t:.3f}", f"{mo:.3f}", typ, m.time_usec, m.lat, m.lon, m.alt, m.fix_type, m.satellites_visible, m.eph])
            with lock: GPSF.append((t, m.fix_type))
        elif typ == 'SYSTEM_TIME':
            mcsv.writerow([f"{t:.3f}", f"{mo:.3f}", typ, m.time_boot_ms, m.time_unix_usec, '', '', '', '', ''])
        elif typ == 'MISSION_ITEM_REACHED' and a.wp:
            log('WP reached', m.seq)
            if m.seq == a.wp[0]: set_capture(True, f'wp{m.seq}')
            elif m.seq == a.wp[1]: set_capture(False, f'wp{m.seq}')
        elif typ == 'RC_CHANNELS' and a.rc > 0:
            v = getattr(m, f'chan{a.rc}_raw', 0)
            mcsv.writerow([f"{t:.3f}", f"{mo:.3f}", typ, m.time_boot_ms, v, '', '', '', '', ''])
            if v > 0 and v != last_rc:
                last_rc = v; set_capture(v > a.thr, f'rc{a.rc}={v}')
except KeyboardInterrupt:
    pass
finally:
    set_capture(False, 'exit'); log('종료')
