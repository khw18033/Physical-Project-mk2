#!/usr/bin/env python3
"""
CANSAR-2 비행 데이터 역투영 (현장 노트북용, torch CUDA 있으면 GPU / 없으면 numpy)
  python3 cansar_flight.py --iq iq_456.bin --meta meta_456.txt --logs cansar_logs/20260930_101500 [--ev 0]
     [--dec 8] [--res 0.25] [--roff 0.4] [--tscan -1 1 0.1] [--side right] [--demean]

궤적: logs/mav.csv 의 LOCAL_POSITION_NED(x=N, y=E, z=D) 를 Pi 시각으로 보간.
시각: events.csv 의 start 행(--ev 번째)에서 offset = pi_epoch − sdr_uptime, 스윕 k 시각 = t0 + k·(t1−t0)/N.
영상: 지상 평면(z=0) NED 격자, 안테나가 보는 쪽(--side) 만 그림. 결과 flight_img.png + flight_img.npz
"""
import argparse, csv, numpy as np, os, sys, zlib, struct
FS=480e3; BW=50e6; TP=100e-6; K=BW/TP; c=3e8
SUBF={i: 5.525e9+0.046e9*i for i in range(8)}
W0,W1=8,53; L=W1-W0; NF=4096
t=np.arange(L)/FS
fq=np.concatenate([SUBF[s]-BW/2+K*t for s in range(8)]); o=np.argsort(fq); f=fq[o]
fu=np.linspace(f.min(),f.max(),4096); FMIN=fu[0]; DFU=fu[1]-fu[0]
Rax=np.fft.fftfreq(NF,DFU)*c/2
dB=lambda x:20*np.log10(np.abs(x)+1e-12)

ap=argparse.ArgumentParser()
ap.add_argument('--iq',required=True); ap.add_argument('--meta',required=True); ap.add_argument('--logs',required=True)
ap.add_argument('--ev',type=int,default=0,help='events.csv 의 몇 번째 start 행인지 (0부터)')
ap.add_argument('--dec',type=int,default=8); ap.add_argument('--res',type=float,default=0.25)
ap.add_argument('--roff',type=float,default=0.4); ap.add_argument('--side',default='right',choices=['right','left','both'])
ap.add_argument('--tscan',type=float,nargs=3,default=None,help='시각 오프셋 스캔 [s]: 시작 끝 간격 (CR 첨두 최대)')
ap.add_argument('--toff',type=float,default=0.0); ap.add_argument('--demean',action='store_true')
ap.add_argument('--rmax',type=float,default=80.0)
ap.add_argument('--sub',type=float,default=0.0,help='부분 개구 [s]: 이 길이 창마다 역투영해 |영상| 비코히런트 합 (GPS 드리프트 회피)')
ap.add_argument('--af',type=int,default=0,help='자동초점 반복 수 (0=끔). 영상 첨두 주변 ±8 m 창, 궤적 매듭 8개 보정')
ap.add_argument('--knots',type=int,default=8); ap.add_argument('--win',type=float,default=60.0,help='영상 폭(m, 비행선 옆 방향)')
a=ap.parse_args()

# ── 스윕별 프로파일 ──
d=np.fromfile(a.iq,dtype=np.int16).reshape(-1,4).astype(np.float32)
mk=np.where(d[:,0].astype(np.int64)==0x5A5A)[0]; mk=mk[np.concatenate([[True],np.diff(mk)>10])]
ant={};ref={}
for i in range(len(mk)-1):
    s=int(d[mk[i]+1,0])
    if not 0<=s<=7: continue
    g=d[mk[i]+W0:mk[i]+W1]
    if len(g)<L: continue
    ant.setdefault(s,[]).append((g[:,0]+1j*g[:,1])[:L]); ref.setdefault(s,[]).append((g[:,2]+1j*g[:,3])[:L])
n_all=min(len(ant[s]) for s in ant)
A=np.array([np.array(ant[s])[:n_all] for s in range(8)]); R=np.array([np.array(ref[s])[:n_all] for s in range(8)])
print(f"스윕 {n_all}  |ant| {np.abs(A).mean():.0f}  |ref| {np.abs(R).mean():.0f}")
A=A[:,::a.dec]; R=R[:,::a.dec]; n=A.shape[1]
Z=(A/R).transpose(1,0,2).reshape(n,-1)[:,o]
zu=np.array([np.interp(fu,f,z.real)+1j*np.interp(fu,f,z.imag) for z in Z])
P=np.fft.fft(np.conj(zu)*np.hanning(4096)[None,:],NF,axis=1)
m=(Rax>=0)&(Rax<a.rmax+5); r=Rax[m]-a.roff; profs=P[:,m].astype(np.complex64)
if a.demean: profs=profs-profs.mean(0,keepdims=True); print("스윕 평균 차감(정지 성분 제거)")
kidx=np.arange(n)*a.dec

# ── 시각 ──
meta=dict(l.strip().split('=',1) for l in open(a.meta) if '=' in l)
t0s=float(meta['t_start']); t1s=float(meta['t_end']); prf_eff=n_all/(t1s-t0s)
print(f"캡처 {t1s-t0s:.2f} s, 유효 PRF {prf_eff:.1f} Hz")
ev=[row for row in csv.DictReader(open(os.path.join(a.logs,'events.csv')))]
starts=[e for e in ev if e['event']=='start']
if not starts: sys.exit("events.csv 에 start 없음")
e=starts[min(a.ev,len(starts)-1)]; off=float(e['pi_epoch'])-float(e['sdr_uptime'])
print(f"오프셋 pi−sdr = {off:.3f} s  (event {a.ev}: sdr_uptime {e['sdr_uptime']})")
tsw=t0s+kidx/prf_eff+off+a.toff            # 스윕 시각 (Pi epoch)

# ── 궤적 ──
mav=[row for row in csv.DictReader(open(os.path.join(a.logs,'mav.csv'))) if row['msg']=='LOCAL_POSITION_NED']
if not mav: sys.exit("LOCAL_POSITION_NED 없음")
tm=np.array([float(x['pi_epoch']) for x in mav]); N=np.array([float(x['f1']) for x in mav]); E=np.array([float(x['f2']) for x in mav]); D=np.array([float(x['f3']) for x in mav])
att=[row for row in csv.DictReader(open(os.path.join(a.logs,'mav.csv'))) if row['msg']=='ATTITUDE']
ta=np.array([float(x['pi_epoch']) for x in att]); yaw=np.array([float(x['f3']) for x in att]) if att else None
if tsw[0]<tm[0]-1 or tsw[-1]>tm[-1]+1: print(f"[!] 스윕 시각 {tsw[0]:.1f}~{tsw[-1]:.1f} 이 궤적 {tm[0]:.1f}~{tm[-1]:.1f} 밖")
pN=np.interp(tsw,tm,N); pE=np.interp(tsw,tm,E); pH=-np.interp(tsw,tm,D)
hdg=np.interp(tsw,ta,np.unwrap(yaw)) if yaw is not None else np.arctan2(pE[-1]-pE[0],pN[-1]-pN[0])*np.ones(n)
L_ap=np.hypot(pN[-1]-pN[0],pE[-1]-pE[0]); print(f"궤적: 고도 {pH.mean():.1f} m, 이동 {L_ap:.1f} m, 평균속도 {L_ap/(tsw[-1]-tsw[0]):.2f} m/s, 헤딩 {np.degrees(hdg.mean()):.0f}°")

# ── 격자 (비행선 좌표: u=진행, v=옆(우측 +)) ──
h0=hdg.mean(); cN,cE=pN.mean(),pE.mean()
def to_uv(nn,ee): du,dv=nn-cN,ee-cE; return du*np.cos(h0)+dv*np.sin(h0), -du*np.sin(h0)+dv*np.cos(h0)
pu,pv=to_uv(pN,pE)
us=np.arange(pu.min()-10,pu.max()+10,a.res)
vs=np.arange(5,a.win,a.res) if a.side=='right' else (np.arange(-a.win,-5,a.res) if a.side=='left' else np.arange(-a.win,a.win,a.res))
U,V=np.meshgrid(us,vs)

use_gpu=False
try:
    import torch
    if torch.cuda.is_available(): use_gpu=True
except Exception: pass

def bp(profs,r,pu,pv,pH,U,V):
    if use_gpu:
        dev='cuda'; Pt=torch.tensor(profs,device=dev); rt=torch.tensor(r,device=dev,dtype=torch.float32)
        Ut=torch.tensor(U,device=dev,dtype=torch.float32); Vt=torch.tensor(V,device=dev,dtype=torch.float32)
        img=torch.zeros(U.shape,dtype=torch.complex64,device=dev); dr=float(r[1]-r[0]); nr=len(r)
        for k in range(len(pu)):
            rr=torch.sqrt((Ut-float(pu[k]))**2+(Vt-float(pv[k]))**2+float(pH[k])**2)
            idx=(rr-float(r[0]))/dr; i0=torch.clamp(idx.floor().long(),0,nr-2); w=(idx-i0.float()).clamp(0,1)
            val=Pt[k][i0]*(1-w)+Pt[k][i0+1]*w
            img+=val*torch.exp(-1j*4*np.pi*FMIN*rr/c)
        return img.cpu().numpy()
    img=np.zeros(U.shape,np.complex64)
    for k in range(len(pu)):
        rr=np.sqrt((U-pu[k])**2+(V-pv[k])**2+pH[k]**2)
        img+=(np.interp(rr,r,profs[k].real)+1j*np.interp(rr,r,profs[k].imag))*np.exp(-1j*4*np.pi*FMIN*rr/c)
    return img
print("역투영:",'GPU' if use_gpu else 'CPU', f"격자 {U.shape[1]}×{U.shape[0]}, 스윕 {n}")

def peak(img):
    A_=np.abs(img); j=np.unravel_index(np.argmax(A_),A_.shape); return dB(A_[j]), us[j[1]], vs[j[0]], A_

if a.tscan:
    best=None; print("시각 오프셋 스캔 (영상 최대 첨두)")
    for to in np.arange(a.tscan[0],a.tscan[1]+1e-9,a.tscan[2]):
        ts2=tsw+to; pN2=np.interp(ts2,tm,N); pE2=np.interp(ts2,tm,E); pH2=-np.interp(ts2,tm,D); pu2,pv2=to_uv(pN2,pE2)
        pk,_,_,_=peak(bp(profs[::4],r,pu2[::4],pv2[::4],pH2[::4],U,V)); print(f"  toff {to:+.2f} s  {pk:6.1f} dB")
        if best is None or pk>best[0]: best=(pk,to)
    a.toff=best[1]; print(f"→ toff {a.toff:+.2f} s 채택"); tsw=tsw+a.toff
    pN=np.interp(tsw,tm,N); pE=np.interp(tsw,tm,E); pH=-np.interp(tsw,tm,D); pu,pv=to_uv(pN,pE)

if a.sub>0:
    nsub=max(1,int(round((tsw[-1]-tsw[0])/a.sub))); edges=np.linspace(0,n,nsub+1).astype(int); acc=np.zeros(U.shape,np.float32)
    print(f"부분 개구 {a.sub} s × {nsub}개 (창당 스윕 {n//nsub}, 개구 {L_ap/nsub:.1f} m) → |영상| 합")
    for i in range(nsub):
        s0,s1=edges[i],edges[i+1]
        if s1-s0<10: continue
        acc+=np.abs(bp(profs[s0:s1],r,pu[s0:s1],pv[s0:s1],pH[s0:s1],U,V))
    img=acc.astype(np.complex64)
else:
    img=bp(profs,r,pu,pv,pH,U,V)
pk,pu_,pv_,A_=peak(img); Dimg=dB(A_)
if a.af>0:
    import torch
    print(f"자동초점: 첨두 ({pu_:+.1f},{pv_:+.1f}) 주변 ±8 m 창, 매듭 {a.knots}, {a.af} 회")
    uw=np.arange(pu_-8,pu_+8,a.res); vw=np.arange(pv_-8,pv_+8,a.res); Uw,Vw=np.meshgrid(uw,vw)
    dev='cuda' if use_gpu else 'cpu'
    Pt=torch.tensor(profs,device=dev); rt0=float(r[0]); dr=float(r[1]-r[0]); nr=len(r)
    Ut=torch.tensor(Uw,device=dev,dtype=torch.float32); Vt=torch.tensor(Vw,device=dev,dtype=torch.float32)
    pu_t=torch.tensor(pu,device=dev,dtype=torch.float32); pv_t=torch.tensor(pv,device=dev,dtype=torch.float32); pH_t=torch.tensor(pH,device=dev,dtype=torch.float32)
    tau=torch.linspace(0,1,n,device=dev); kn=torch.linspace(0,1,a.knots,device=dev)
    W=torch.clamp(1-torch.abs(tau[:,None]-kn[None,:])*(a.knots-1),min=0)          # 선형 보간 기저 (n,K)
    par=torch.zeros(2,a.knots,device=dev,requires_grad=True)                         # du, dv 매듭 [m]
    opt=torch.optim.Adam([par],lr=0.05)
    def bpw(du,dv):
        img=torch.zeros(Uw.shape,dtype=torch.complex64,device=dev)
        for k in range(n):
            rr=torch.sqrt((Ut-(pu_t[k]+du[k]))**2+(Vt-(pv_t[k]+dv[k]))**2+pH_t[k]**2)
            idx=(rr-rt0)/dr; i0=torch.clamp(idx.floor().long(),0,nr-2); w=(idx-i0.float()).clamp(0,1)
            img=img+(Pt[k][i0]*(1-w)+Pt[k][i0+1]*w)*torch.exp(-1j*4*np.pi*FMIN*rr/c)
        return img
    def ent(x): p=x.abs()**2; p=p/p.sum(); return -(p*torch.log(p+1e-20)).sum()
    best=None
    for it in range(a.af):
        du=W@par[0]; dv=W@par[1]; im=bpw(du,dv); e=ent(im)
        if best is None or e.item()<best[0]: best=(e.item(),par.detach().clone(),im.detach())
        if it%10==0 or it==a.af-1: print(f"  step {it:3d}  entropy {e.item():.4f}  |du|max {du.abs().max().item():.2f} m  |dv|max {dv.abs().max().item():.2f} m")
        opt.zero_grad(); e.backward(); opt.step()
    par=best[1]; du=(W@par[0]).cpu().numpy(); dv=(W@par[1]).cpu().numpy()
    Aw=best[2].abs().cpu().numpy(); j=np.unravel_index(np.argmax(Aw),Aw.shape); row=Aw[j[0]]; h=np.where(row>Aw[j]/np.sqrt(2))[0]
    print(f"  자동초점 후: 창 첨두 대비 배경 중앙값 {np.median(dB(Aw))-dB(Aw[j]):+.1f} dB, 진행방향 −3 dB 폭 {(h[-1]-h[0]+1)*a.res:.2f} m")
    pu=pu+du; pv=pv+dv
    img=bp(profs,r,pu,pv,pH,U,V); pk,pu_,pv_,A_=peak(img); Dimg=dB(A_)
print(f"영상 첨두 {pk:.1f} dB @ 진행 {pu_:+.1f} m, 옆 {pv_:+.1f} m  (배경 중앙값 {np.median(Dimg)-pk:+.1f} dB)")
np.savez('flight_img.npz',img=img,us=us,vs=vs,pu=pu,pv=pv,pH=pH,toff=a.toff)
g=(np.clip((Dimg-Dimg.max()+30)/30,0,1)*255).astype(np.uint8)[::-1]; h,w=g.shape
raw=b"".join(b"\x00"+g[i].tobytes() for i in range(h))
ch=lambda tp,dd: struct.pack(">I",len(dd))+tp+dd+struct.pack(">I",zlib.crc32(tp+dd)&0xffffffff)
open('flight_img.png','wb').write(b"\x89PNG\r\n\x1a\n"+ch(b"IHDR",struct.pack(">IIBBBBB",w,h,8,0,0,0,0))+ch(b"IDAT",zlib.compress(raw,9))+ch(b"IEND",b""))
print(f"flight_img.png 저장  (가로 = 진행 방향 {us[0]:.0f}~{us[-1]:.0f} m, 세로 = 옆 거리 {vs[0]:.0f}~{vs[-1]:.0f} m, 위=먼 쪽, 0~−30 dB)")
