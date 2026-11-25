"""
anchor360_pose.py — 카메라 자세 자동 맞춤 (수평 + 방위)

[왜 필요한가]  2026-11-18 실측
  - 카메라가 약 2~3도 기울어 있다. 기울기를 0 으로 가정하면 3 m 거리에서 방향에 따라 ±15 cm 가 틀린다.
  - 카메라의 손떨림 보정(stabilization)을 켜면 접속할 때마다 기준 방위가 바뀐다(실측 10.5도).
    끄면 다시 켜도 0.01도 이내로 같다. 그래도 삼각대를 건드리면 바뀌므로 시작할 때마다 확인한다.

[하는 일]
  1) 수직선(문틀·벽 모서리·책장 등)으로 참 수직 방향을 구한다 → 수평 맞춤 회전 L
  2) 수평 맞춘 영상의 위쪽 띠(벽·천장, 사람이 없는 부분)를 기준 영상의 띠와 겹쳐 방위 차를 구한다 → Ry
  3) R = Ry · L.  b_보정 = R · b_원본.  슬라이스는 '보정 좌표계'에서 뽑는다.
  기준(anchor360_pose_ref.npz)은 보정값(anchor360_calib.json)을 구할 때 쓴 영상에서 만든다.
  카메라 '위치'를 옮겼으면 이 맞춤으로는 안 되고 보정을 다시 해야 한다.

좌표: x 오른쪽, y 위, z = equirect 가운데(u=0) 정면. u 는 오른쪽으로 +.
"""
import math
import cv2
import numpy as np

def bearing(lon, lat):
    return np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], -1)
def view_basis(u, v):
    u, v = math.radians(u), math.radians(v)
    f = bearing(np.array(u), np.array(v)); r = np.array([math.cos(u), 0.0, -math.sin(u)]); up = np.cross(f, r)
    return f, r, up
def pix2bear(u, v, fov, size, px, py):
    """투시 뷰 픽셀 → equirect 좌표계 단위벡터 (x 오른쪽, y 위, z = u=0 정면)."""
    f, r, up = view_basis(u, v); t = math.tan(math.radians(fov) / 2)
    x = t * (2 * np.asarray(px, float) / (size - 1) - 1); y = -t * (2 * np.asarray(py, float) / (size - 1) - 1)
    d = f + x[..., None] * r + y[..., None] * up
    return d / np.linalg.norm(d, axis=-1, keepdims=True)
def bear2equ(b, W, H):
    lon = np.arctan2(b[..., 0], b[..., 2]); lat = np.arcsin(np.clip(b[..., 1], -1, 1))
    return (lon / (2 * np.pi) + 0.5) * W - 0.5, (0.5 - lat / np.pi) * H - 0.5
def persp(equ, u, v, fov, size):
    H, W = equ.shape[:2]; xs, ys = np.meshgrid(np.arange(size), np.arange(size))
    ex, ey = bear2equ(pix2bear(u, v, fov, size, xs, ys), W, H)
    return cv2.remap(equ, ex.astype(np.float32), ey.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
def level_R(g):
    """g(원본 좌표계에서 본 참 수직) 를 +y 로 보내는 최소 회전. b_level = R @ b_raw."""
    g = np.asarray(g, float) / np.linalg.norm(g); y = np.array([0.0, 1.0, 0.0])
    ax = np.cross(g, y); s = np.linalg.norm(ax); c = float(g @ y)
    if s < 1e-12: return np.eye(3)
    ax /= s; K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + s * K + (1 - c) * K @ K
def persp_R(equ, u, v, fov, size, R):
    """수평 맞춘 좌표계에서의 투시 뷰."""
    H, W = equ.shape[:2]; xs, ys = np.meshgrid(np.arange(size), np.arange(size))
    b = pix2bear(u, v, fov, size, xs, ys) @ R          # = (R^T b_level)
    ex, ey = bear2equ(b, W, H)
    return cv2.remap(equ, ex.astype(np.float32), ey.astype(np.float32), cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)
def estimate_vertical(equ, size=1000, fov=90, seed=0):
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD); N, Wt = [], []
    for u in range(0, 360, 30):
        g = cv2.cvtColor(persp(equ, u, 0, fov, size), cv2.COLOR_BGR2GRAY)
        ls = lsd.detect(g)[0]
        if ls is None: continue
        ls = ls[:, 0]; L = np.hypot(ls[:, 2] - ls[:, 0], ls[:, 3] - ls[:, 1]); k = L > size * 0.075; ls, L = ls[k], L[k]
        b1 = pix2bear(u, 0, fov, size, ls[:, 0], ls[:, 1]); b2 = pix2bear(u, 0, fov, size, ls[:, 2], ls[:, 3])
        n = np.cross(b1, b2); n /= np.linalg.norm(n, axis=1, keepdims=True)
        ok = np.abs(n[:, 1]) < math.sin(math.radians(8)); N.append(n[ok]); Wt.append(L[ok])
    N = np.concatenate(N); Wt = np.concatenate(Wt); rng = np.random.default_rng(seed); thr = math.sin(math.radians(0.35)); best = (0, None)
    for _ in range(3000):
        i, j = rng.choice(len(N), 2, replace=False); g = np.cross(N[i], N[j]); ng = np.linalg.norm(g)
        if ng < 0.2: continue
        g /= ng; g = g if g[1] > 0 else -g
        if g[1] < 0.95: continue
        sc = Wt[np.abs(N @ g) < thr].sum()
        if sc > best[0]: best = (sc, g)
    g = best[1]
    for _ in range(5):
        inl = np.abs(N @ g) < thr; g = np.linalg.svd(N[inl] * Wt[inl, None], full_matrices=False)[2][-1]; g = g if g[1] > 0 else -g
    return g, int((np.abs(N @ g) < thr).sum()), len(N)
def Ry(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
def band(equ, R, W=1440, lat0=8.0, lat1=48.0):
    """R 로 맞춘 좌표계의 equirect 띠(위쪽 벽·천장 — 사람이 없는 부분). 가로=방위 360도."""
    Hh = int(round((lat1 - lat0) / 360.0 * W)); lon = (np.arange(W) + 0.5) / W * 2 * np.pi - np.pi
    lat = np.radians(lat1 - (np.arange(Hh) + 0.5) / Hh * (lat1 - lat0)); lo, la = np.meshgrid(lon, lat)
    b = bearing(lo, la) @ R; ex, ey = bear2equ(b, equ.shape[1], equ.shape[0])
    im = cv2.remap(equ, ex.astype(np.float32), ey.astype(np.float32), cv2.INTER_AREA if False else cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32); g = cv2.GaussianBlur(g, (0, 0), 1.5)
    return g - cv2.GaussianBlur(g, (0, 0), 25)          # 조명 변화 제거
def heading_delta(band_new, band_ref):
    """band_new 를 방위로 몇 도 돌리면 band_ref 와 겹치는가. (도, 상관값). 가로 원형 상관 + 포물선 보간."""
    W = band_ref.shape[1]; A = np.fft.rfft(band_ref, axis=1); B = np.fft.rfft(band_new, axis=1)
    cc = np.fft.irfft((A * np.conj(B)).sum(0), n=W); cc /= (np.linalg.norm(band_ref) * np.linalg.norm(band_new) + 1e-9)
    k = int(np.argmax(cc)); y0, y1, y2 = cc[(k - 1) % W], cc[k], cc[(k + 1) % W]; d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)
    s = (k + d); s = s - W if s > W / 2 else s
    return s * 360.0 / W, float(y1)


def solve_pose(equ, ref_band, log=print):
    """프레임 한 장 → (R, 정보). ref_band 가 None 이면 수평만 맞춘다."""
    g, n_in, n_all = estimate_vertical(equ)
    L = level_R(g)
    info = {"tilt_deg": math.degrees(math.acos(min(1.0, g[1]))),
            "tilt_dir_deg": math.degrees(math.atan2(g[0], g[2])) % 360.0,
            "lines": (n_in, n_all), "heading_deg": 0.0, "corr": None}
    if ref_band is None or n_in < 30:
        return L, info
    d, _ = heading_delta(band(equ, L, ref_band.shape[1]), ref_band)
    best = None
    for cand in (d, -d):                       # 회전 부호는 실제로 겹쳐 보고 정한다
        R = Ry(cand) @ L
        resid, c = heading_delta(band(equ, R, ref_band.shape[1]), ref_band)
        if best is None or c - abs(resid) > best[0]:
            best = (c - abs(resid), R, cand, c, resid)
    _, R, cand, c, resid = best
    info.update(heading_deg=cand, corr=c, resid_deg=resid)
    return R, info


def slice_maps(u_list, v_deg, fov, size, R, W, H):
    """보정 좌표계에서 뽑는 슬라이스들의 cv2.remap 맵. R=None 이면 원본 좌표계(=py360convert.e2p 와 동일)."""
    xs, ys = np.meshgrid(np.arange(size), np.arange(size))
    out = []
    for u in u_list:
        b = pix2bear(u, v_deg, fov, size, xs, ys)
        if R is not None:
            b = b @ R                         # = R^T b
        ex, ey = bear2equ(b, W, H)
        out.append(cv2.convertMaps(ex.astype(np.float32), ey.astype(np.float32), cv2.CV_16SC2))
    return out
