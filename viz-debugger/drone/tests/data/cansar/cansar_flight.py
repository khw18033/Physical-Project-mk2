#!/usr/bin/env python3
"""
CANSAR-2 비행 데이터 역투영 v2 (2026-10-04)  — torch CUDA 있으면 GPU / 없으면 numpy
  python3 cansar_flight.py --iq iq_N.bin --meta meta_N.txt --logs cansar_logs/<날짜> [--ev 0]
     [--dec 1] [--res 0.25] [--roff 0.4] [--tscan -1 1 0.1] [--side right] [--demean]
     [--lever F R D]  [--af 40]

v2 변경 (v1 과 명령 형식 동일, 결과 파일 이름 동일)
  · 빛의 속도 299 792 458 m/s
  · 스윕 묶기: 서브밴드 번호가 0→7 로 온전히 이어진 묶음만 사용. 끊긴 곳(마커 손실)은 세어서 출력하고,
    스윕 시각은 파일 안 묶음 위치(마커 행 번호) 비율로 계산 → 마커가 빠져도 뒤 스윕이 밀리지 않음
  · 거리 압축: 균일 격자 보간 없이 실제 주파수 표본으로 직접 합산 (먼 표적 손실 제거)
  · --lever F R D : 레이더 안테나 위상중심의 FC(IMU) 기준 위치 [m] (앞·오른쪽·아래).
    ATTITUDE(roll·pitch·yaw)로 NED 로 돌려 궤적에 더함
  · 기본 --dec 1 (방위 표본 간격 ≤ λ/4 유지. quick 은 속도에 맞춰 자동으로 정함)

궤적: logs/mav.csv 의 LOCAL_POSITION_NED(x=N, y=E, z=D) 를 Pi 시각으로 보간.
시각: events.csv 의 start 행(--ev 번째)에서 offset = pi_epoch − sdr_uptime, 묶음 시각 = t0 + (행 위치 비율)·(t1−t0).
영상: 지상 평면(z=0) NED 격자, 안테나가 보는 쪽(--side) 만. 결과 flight_img.png + flight_img.npz
"""
import argparse, csv, numpy as np, os, sys, zlib, struct
FS = 480e3; BW = 50e6; TP = 100e-6; K = BW / TP; c = 299792458.0
SUBF = {i: 5.525e9 + 0.046e9 * i for i in range(8)}
W0, W1 = 8, 53; L = W1 - W0
t = np.arange(L) / FS
fq = np.concatenate([SUBF[s] - BW / 2 + K * t for s in range(8)]); o = np.argsort(fq); f = fq[o]
FMIN = f[0]
dB = lambda x: 20 * np.log10(np.abs(x) + 1e-12)

ap = argparse.ArgumentParser()
ap.add_argument('--iq', required=True); ap.add_argument('--meta', required=True); ap.add_argument('--logs', required=True)
ap.add_argument('--ev', type=int, default=0, help='events.csv 의 몇 번째 start 행인지 (0부터)')
ap.add_argument('--dec', type=int, default=1); ap.add_argument('--res', type=float, default=0.25)
ap.add_argument('--roff', type=float, default=0.4); ap.add_argument('--side', default='right', choices=['right', 'left', 'both'])
ap.add_argument('--tscan', type=float, nargs=3, default=None, help='시각 오프셋 스캔 [s]: 시작 끝 간격 (영상 첨두 최대)')
ap.add_argument('--toff', type=float, default=0.0); ap.add_argument('--demean', action='store_true')
ap.add_argument('--rmax', type=float, default=80.0); ap.add_argument('--rstep', type=float, default=0.05, help='거리 프로파일 간격 [m]')
ap.add_argument('--sub', type=float, default=0.0, help='부분 개구 [s]: 창마다 역투영해 |영상| 비코히런트 합')
ap.add_argument('--af', type=int, default=0, help='자동초점 반복 수 (0=끔). 영상 첨두 주변 ±8 m 창')
ap.add_argument('--knots', type=int, default=8); ap.add_argument('--af-lr', type=float, default=0.003, help='자동초점 학습률 [m]')
ap.add_argument('--win', type=float, default=60.0, help='영상 폭(m, 비행선 옆 방향)')
ap.add_argument('--roi', type=float, nargs=3, default=None, metavar=('U', 'V', 'HALF'),
                help='작은 구역만 영상화: 중심(진행 U, 옆 V) ± HALF [m]. CR 확대 확인용')
ap.add_argument('--lever', type=float, nargs=3, default=None, metavar=('F', 'R', 'D'),
                help='레이더 안테나 위치, FC 기준 앞·오른쪽·아래 [m]')
a = ap.parse_args()

# ── 스윕 읽기: 0→7 완결 묶음만 ──
d = np.fromfile(a.iq, dtype=np.int16).reshape(-1, 4).astype(np.float32)
mk = np.where(d[:, 0].astype(np.int64) == 0x5A5A)[0]; mk = mk[np.concatenate([[True], np.diff(mk) > 10])]
recs = []   # (행 위치, 서브밴드, ant, ref)
for i in range(len(mk) - 1):
    s = int(d[mk[i] + 1, 0])
    if not 0 <= s <= 7: continue
    g = d[mk[i] + W0:mk[i] + W1]
    if len(g) < L: continue
    recs.append((mk[i], s, (g[:, 0] + 1j * g[:, 1])[:L], (g[:, 2] + 1j * g[:, 3])[:L]))
cycles = []; cur = []; breaks = 0; insync = False
for r in recs:
    if r[1] == len(cur):
        cur.append(r); insync = insync or r[1] == 0
    else:
        if insync: breaks += 1                     # 순서가 끊긴 곳 한 번만 셈 (첫 묶음 앞의 조각은 제외)
        insync = r[1] == 0
        cur = [r] if r[1] == 0 else []
    if len(cur) == 8: cycles.append(cur); cur = []
n_all = len(cycles)
if n_all < 10: sys.exit(f"완결 스윕 묶음이 {n_all} 개뿐 — 데이터 확인")
A = np.array([[c_[s][2] for s in range(8)] for c_ in cycles])     # (n, 8, L)
R = np.array([[c_[s][3] for s in range(8)] for c_ in cycles])
row = np.array([c_[0][0] for c_ in cycles], dtype=np.float64)       # 묶음 시작 행 번호
print(f"완결 스윕 {n_all}  끊김 {breaks} 곳  |ant| {np.abs(A).mean():.0f}  |ref| {np.abs(R).mean():.0f}")
A = A[::a.dec]; R = R[::a.dec]; row = row[::a.dec]; n = A.shape[0]
Z = (A / R).reshape(n, -1)[:, o]                                     # (n, 360) 주파수 오름차순

# ── 거리 압축: 실제 주파수로 직접 합산 ──
r_ax = np.arange(0, a.rmax + 5, a.rstep)
win = np.hanning(len(f))
M = np.exp(-2j * np.pi * np.outer(f - FMIN, 2 * r_ax / c)).astype(np.complex64)   # (360, nr)
profs = np.empty((n, len(r_ax)), np.complex64)
for i0 in range(0, n, 2000):
    profs[i0:i0 + 2000] = (np.conj(Z[i0:i0 + 2000]) * win).astype(np.complex64) @ M
r = r_ax - a.roff
if a.demean: profs = profs - profs.mean(0, keepdims=True); print("스윕 평균 차감(정지 성분 제거)")

# ── 시각 ──
meta = dict(l.strip().split('=', 1) for l in open(a.meta, encoding='utf-8') if '=' in l)
t0s = float(meta['t_start']); t1s = float(meta['t_end'])
prf_eff = n_all / (t1s - t0s)
print(f"캡처 {t1s-t0s:.2f} s, 유효 PRF {prf_eff:.1f} Hz (완결 묶음 기준)")
ev = [x for x in csv.DictReader(open(os.path.join(a.logs, 'events.csv'), encoding='utf-8'))]
starts = [e for e in ev if e['event'] == 'start']
if not starts: sys.exit("events.csv 에 start 없음")
e = starts[min(a.ev, len(starts) - 1)]; off = float(e['pi_epoch']) - float(e['sdr_uptime'])
print(f"오프셋 pi−sdr = {off:.3f} s  (event {a.ev}: sdr_uptime {e['sdr_uptime']})")
nrow = d.shape[0]
tsw = t0s + (row / nrow) * (t1s - t0s) + off + a.toff               # 행 위치 비율 → 마커 손실에도 시각 유지

# ── 궤적 ──
rows = list(csv.DictReader(open(os.path.join(a.logs, 'mav.csv'), encoding='utf-8')))
mav = [x for x in rows if x['msg'] == 'LOCAL_POSITION_NED']
if not mav: sys.exit("LOCAL_POSITION_NED 없음")
tm = np.array([float(x['pi_epoch']) for x in mav]); N_ = np.array([float(x['f1']) for x in mav])
E_ = np.array([float(x['f2']) for x in mav]); D_ = np.array([float(x['f3']) for x in mav])
att = [x for x in rows if x['msg'] == 'ATTITUDE']
ta = np.array([float(x['pi_epoch']) for x in att]) if att else None
roll = np.array([float(x['f1']) for x in att]) if att else None
pitch = np.array([float(x['f2']) for x in att]) if att else None
yaw = np.unwrap(np.array([float(x['f3']) for x in att])) if att else None
if a.lever and not att: sys.exit("--lever 에는 ATTITUDE 기록이 필요")

def traj(ts):
    pN = np.interp(ts, tm, N_); pE = np.interp(ts, tm, E_); pD = np.interp(ts, tm, D_)
    if a.lever:
        rr = np.interp(ts, ta, roll); pp = np.interp(ts, ta, pitch); yy = np.interp(ts, ta, yaw)
        F, Rg, Dn = a.lever
        cr, sr, cp, sp, cy, sy = np.cos(rr), np.sin(rr), np.cos(pp), np.sin(pp), np.cos(yy), np.sin(yy)
        # 몸체(FRD) → NED : Rz(yaw)·Ry(pitch)·Rx(roll)
        pN = pN + (cy*cp)*F + (cy*sp*sr - sy*cr)*Rg + (cy*sp*cr + sy*sr)*Dn
        pE = pE + (sy*cp)*F + (sy*sp*sr + cy*cr)*Rg + (sy*sp*cr - cy*sr)*Dn
        pD = pD + (-sp)*F + (cp*sr)*Rg + (cp*cr)*Dn
    return pN, pE, -pD

if tsw[0] < tm[0] - 1 or tsw[-1] > tm[-1] + 1: print(f"[!] 스윕 시각 {tsw[0]:.1f}~{tsw[-1]:.1f} 이 궤적 {tm[0]:.1f}~{tm[-1]:.1f} 밖")
pN, pE, pH = traj(tsw)
hdg = np.interp(tsw, ta, yaw) if att else np.arctan2(pE[-1]-pE[0], pN[-1]-pN[0]) * np.ones(n)
L_ap = np.hypot(pN[-1]-pN[0], pE[-1]-pE[0]); vel = L_ap / max(tsw[-1]-tsw[0], 1e-6)
lam = c / f.mean(); dx = vel / (prf_eff / a.dec)
print(f"궤적: 고도 {pH.mean():.1f} m, 이동 {L_ap:.1f} m, 평균속도 {vel:.2f} m/s, 헤딩 {np.degrees(hdg.mean()):.0f}°"
      + (f", 레버암 F{a.lever[0]:+.2f} R{a.lever[1]:+.2f} D{a.lever[2]:+.2f} m" if a.lever else ""))
print(f"방위 표본 간격 {dx*100:.2f} cm (λ/4 = {lam/4*100:.2f} cm)" + ("  [!] λ/4 초과 — 앨리어싱 가능, --dec 를 낮추세요" if dx > lam/4 else ""))

# ── 격자 (비행선 좌표: u=진행, v=옆(우측 +)) ──
h0 = hdg.mean(); cN, cE = pN.mean(), pE.mean()
def to_uv(nn, ee): du, dv = nn-cN, ee-cE; return du*np.cos(h0)+dv*np.sin(h0), -du*np.sin(h0)+dv*np.cos(h0)
pu, pv = to_uv(pN, pE)
us = np.arange(pu.min()-10, pu.max()+10, a.res)
vs = np.arange(5, a.win, a.res) if a.side == 'right' else (np.arange(-a.win, -5, a.res) if a.side == 'left' else np.arange(-a.win, a.win, a.res))
if a.roi:
    us = np.arange(a.roi[0]-a.roi[2], a.roi[0]+a.roi[2]+1e-9, a.res); vs = np.arange(a.roi[1]-a.roi[2], a.roi[1]+a.roi[2]+1e-9, a.res)
U, V = np.meshgrid(us, vs)

use_gpu = False
try:
    import torch
    if torch.cuda.is_available(): use_gpu = True
except Exception: pass

def bp(profs, r, pu, pv, pH, U, V):
    if use_gpu:
        dev = 'cuda'; Pt = torch.tensor(profs, device=dev)
        Ut = torch.tensor(U, device=dev, dtype=torch.float32); Vt = torch.tensor(V, device=dev, dtype=torch.float32)
        img = torch.zeros(U.shape, dtype=torch.complex64, device=dev); dr = float(r[1]-r[0]); nr = len(r)
        for k in range(len(pu)):
            rr = torch.sqrt((Ut-float(pu[k]))**2+(Vt-float(pv[k]))**2+float(pH[k])**2)
            idx = (rr-float(r[0]))/dr; i0 = torch.clamp(idx.floor().long(), 0, nr-2); w = (idx-i0.float()).clamp(0, 1)
            img += (Pt[k][i0]*(1-w)+Pt[k][i0+1]*w)*torch.exp(-1j*4*np.pi*FMIN*rr/c)
        return img.cpu().numpy()
    img = np.zeros(U.shape, np.complex64)
    for k in range(len(pu)):
        rr = np.sqrt((U-pu[k])**2+(V-pv[k])**2+pH[k]**2)
        img += (np.interp(rr, r, profs[k].real)+1j*np.interp(rr, r, profs[k].imag))*np.exp(-1j*4*np.pi*FMIN*rr/c)
    return img
print("역투영:", 'GPU' if use_gpu else 'CPU', f"격자 {U.shape[1]}×{U.shape[0]}, 스윕 {n}")

def peak(img):
    A_ = np.abs(img); j = np.unravel_index(np.argmax(A_), A_.shape); return dB(A_[j]), us[j[1]], vs[j[0]], A_

if a.tscan:
    best = None; print("시각 오프셋 스캔 (영상 최대 첨두)")
    st = max(1, n // 2000)
    for to in np.arange(a.tscan[0], a.tscan[1]+1e-9, a.tscan[2]):
        pN2, pE2, pH2 = traj(tsw+to); pu2, pv2 = to_uv(pN2, pE2)
        pk, _, _, _ = peak(bp(profs[::st], r, pu2[::st], pv2[::st], pH2[::st], U, V)); print(f"  toff {to:+.2f} s  {pk:6.1f} dB")
        if best is None or pk > best[0]: best = (pk, to)
    a.toff += best[1]; print(f"→ toff {best[1]:+.2f} s 채택"); tsw = tsw+best[1]
    pN, pE, pH = traj(tsw); pu, pv = to_uv(pN, pE)

if a.sub > 0:
    nsub = max(1, int(round((tsw[-1]-tsw[0])/a.sub))); edges = np.linspace(0, n, nsub+1).astype(int); acc = np.zeros(U.shape, np.float32)
    print(f"부분 개구 {a.sub} s × {nsub}개 → |영상| 합")
    for i in range(nsub):
        s0, s1 = edges[i], edges[i+1]
        if s1-s0 < 10: continue
        acc += np.abs(bp(profs[s0:s1], r, pu[s0:s1], pv[s0:s1], pH[s0:s1], U, V))
    img = acc.astype(np.complex64)
else:
    img = bp(profs, r, pu, pv, pH, U, V)
pk, pu_, pv_, A_ = peak(img); Dimg = dB(A_)
if a.af > 0:
    import torch
    print(f"자동초점: 첨두 ({pu_:+.1f},{pv_:+.1f}) 주변 ±8 m 창, 매듭 {a.knots}, {a.af} 회, 학습률 {a.af_lr} m")
    uw = np.arange(pu_-8, pu_+8, a.res); vw = np.arange(pv_-8, pv_+8, a.res); Uw, Vw = np.meshgrid(uw, vw)
    dev = 'cuda' if use_gpu else 'cpu'
    Pt = torch.tensor(profs, device=dev); rt0 = float(r[0]); dr = float(r[1]-r[0]); nr = len(r)
    Ut = torch.tensor(Uw, device=dev, dtype=torch.float32); Vt = torch.tensor(Vw, device=dev, dtype=torch.float32)
    pu_t = torch.tensor(pu, device=dev, dtype=torch.float32); pv_t = torch.tensor(pv, device=dev, dtype=torch.float32); pH_t = torch.tensor(pH, device=dev, dtype=torch.float32)
    tau = torch.linspace(0, 1, n, device=dev); kn = torch.linspace(0, 1, a.knots, device=dev)
    W = torch.clamp(1-torch.abs(tau[:, None]-kn[None, :])*(a.knots-1), min=0)
    par = torch.zeros(2, a.knots, device=dev, requires_grad=True)
    opt = torch.optim.Adam([par], lr=a.af_lr)
    def bpw(du, dv):
        im = torch.zeros(Uw.shape, dtype=torch.complex64, device=dev)
        for k in range(n):
            rr = torch.sqrt((Ut-(pu_t[k]+du[k]))**2+(Vt-(pv_t[k]+dv[k]))**2+pH_t[k]**2)
            idx = (rr-rt0)/dr; i0 = torch.clamp(idx.floor().long(), 0, nr-2); w = (idx-i0.float()).clamp(0, 1)
            im = im+(Pt[k][i0]*(1-w)+Pt[k][i0+1]*w)*torch.exp(-1j*4*np.pi*FMIN*rr/c)
        return im
    def ent(x): p = x.abs()**2; p = p/p.sum(); return -(p*torch.log(p+1e-20)).sum()
    best = None
    for it in range(a.af):
        du = W@par[0]; dv = W@par[1]; im = bpw(du, dv); e_ = ent(im)
        if best is None or e_.item() < best[0]: best = (e_.item(), par.detach().clone(), im.detach())
        if it % 10 == 0 or it == a.af-1: print(f"  step {it:3d}  entropy {e_.item():.4f}  |du|max {du.abs().max().item():.3f} m  |dv|max {dv.abs().max().item():.3f} m")
        opt.zero_grad(); e_.backward(); opt.step()
    par = best[1]; du = (W@par[0]).cpu().numpy(); dv = (W@par[1]).cpu().numpy()
    pu = pu+du; pv = pv+dv
    img = bp(profs, r, pu, pv, pH, U, V); pk, pu_, pv_, A_ = peak(img); Dimg = dB(A_)
print(f"영상 첨두 {pk:.1f} dB @ 진행 {pu_:+.1f} m, 옆 {pv_:+.1f} m  (배경 중앙값 {np.median(Dimg)-pk:+.1f} dB)")
np.savez('flight_img.npz', img=img, us=us, vs=vs, pu=pu, pv=pv, pH=pH, toff=a.toff, h0=h0, cN=cN, cE=cE,
         lever=np.array(a.lever if a.lever else [0, 0, 0]), breaks=breaks)
g = (np.clip((Dimg-Dimg.max()+30)/30, 0, 1)*255).astype(np.uint8)[::-1]; hh, ww = g.shape
raw = b"".join(b"\x00"+g[i].tobytes() for i in range(hh))
ch = lambda tp, dd: struct.pack(">I", len(dd))+tp+dd+struct.pack(">I", zlib.crc32(tp+dd) & 0xffffffff)
open('flight_img.png', 'wb').write(b"\x89PNG\r\n\x1a\n"+ch(b"IHDR", struct.pack(">IIBBBBB", ww, hh, 8, 0, 0, 0, 0))+ch(b"IDAT", zlib.compress(raw, 9))+ch(b"IEND", b""))
print(f"flight_img.png 저장  (가로 = 진행 방향 {us[0]:.0f}~{us[-1]:.0f} m, 세로 = 옆 거리 {vs[0]:.0f}~{vs[-1]:.0f} m, 위=먼 쪽, 0~−30 dB)")
