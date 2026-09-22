"""
detect_ground_3b1.py — 3b-① 바닥평면 깊이 (검증 모드)
슬라이스 검출 → 필터(HARD_OBSTACLE/AGENT + 바닥접지) → NMS → 바닥평면 교차 → anchor360 (x,z) + 수평거리 D

사용:
  python3 detect_ground_3b1.py <슬라이스> <config.yaml> [출력이미지] [imgsz] [cam_h_m] [pitch_deg]
예:
  python3 detect_ground_3b1.py .../360cam_u-60_v-35.jpg .../unidepth_dual_yolo_config.yaml gnd_u-60.jpg 640 1.85 -35

기하:
  슬라이스 = e2p fov=(90,90), 720x720 합성 핀홀 → fx=fy=360, cx=cy=360 (계산으로 확정, 캘리브레이션 불필요)
  카메라: 높이 cam_h_m, 하향 pitch_deg 로 고정, roll 0
  각 박스의 하단중앙 픽셀 → 카메라광선 → pitch 회전 → 바닥(y=0) 교차 → (x,0,z)
  좌표 규약(anchor360): +x 오른쪽, +y 위(바닥 y=0), +z 카메라 정면(슬라이스가 보는 방향)
  수평거리 D = sqrt(x^2 + z^2)  ← 줄자로 잰 '카메라 발밑↔박스 바닥접지' 수평거리와 대조
"""
import sys, math, yaml, cv2, numpy as np
from ultralytics import YOLOWorld

img_path = sys.argv[1]
cfg_path = sys.argv[2]
out_path = sys.argv[3] if len(sys.argv) > 3 else "gnd_out.jpg"
imgsz    = int(sys.argv[4])   if len(sys.argv) > 4 else 640
CAM_H    = float(sys.argv[5]) if len(sys.argv) > 5 else 1.85     # 렌즈중심 높이(m)
PITCH    = float(sys.argv[6]) if len(sys.argv) > 6 else -35.0    # 하향각(deg), 아래가 음수

# --- 반영 대상 그룹 ---
KEEP_GROUPS = {"HARD_OBSTACLE", "AGENT"}

# --- config ---
CFG = yaml.safe_load(open(cfg_path))
ZS_W    = CFG["models"]["zeroshot_detector"]["weight"]
ZS_CLS  = CFG["classes"]["zeroshot"]
ZS_CONF = float(CFG["models"]["zeroshot_detector"]["conf"])
GROUP   = CFG["group_mapping"]
CC      = CFG.get("class_conf", {}).get("zeroshot", {})
IOU     = float(CFG.get("fusion", {}).get("iou", 0.45))

def min_conf(name):
    return float(CC.get(name, CC.get("default", 0.0)))

# --- 슬라이스 핀홀 내부 파라미터 (720x720, fov 90) ---
img = cv2.imread(img_path)
if img is None:
    sys.exit(f"이미지 못 읽음: {img_path}")
H, W = img.shape[:2]
fx = fy = W / (2.0 * math.tan(math.radians(90) / 2.0))   # =360 for W=720
cx, cy = W / 2.0, H / 2.0

# --- pitch 회전행렬 (x축 기준, 카메라를 아래로 PITCH도 기울임) ---
# 카메라 좌표: x오른쪽, y아래(이미지), z전방.  월드: x오른쪽, y위, z전방.
# 먼저 이미지 y(아래+)를 월드 y(위+)로: y_cam_up = -(py-cy)
th = math.radians(PITCH)   # -35deg
# 광선을 월드로 돌리는 회전(피치): 아래로 th 만큼 숙인 카메라의 전방/상하 성분 보정
cos_t, sin_t = math.cos(th), math.sin(th)

def pixel_to_ground(px, py):
    # 카메라 광선(정규화 전): x오른쪽, y위, z전방
    dx = (px - cx) / fx
    dy = -(py - cy) / fy          # 이미지 아래+ → 월드(카메라 광학축 기준) 위+
    dz = 1.0
    # 카메라를 아래로 |PITCH|도 숙였을 때, 카메라광선을 월드(중력)좌표로 되돌리는 회전.
    # 하향 카메라의 전방(dz)은 월드에서 아래+전방을 향해야 하므로:
    #   wy = cos*dy + sin*dz , wz = -sin*dy + cos*dz   (th=PITCH<0 → sin<0 → 전방광선이 아래로)
    wy = cos_t * dy + sin_t * dz
    wz = -sin_t * dy + cos_t * dz
    wx = dx
    if wy >= -1e-6:               # 위를 향하거나 수평 → 바닥과 안 만남
        return None, wy, None
    t = -CAM_H / wy               # 카메라(높이 CAM_H)에서 바닥 y=0 까지
    X = wx * t
    Z = wz * t
    return (X, Z), wy, t          # anchor360 바닥좌표(m). 발밑 원점.

# --- 검출 ---
model = YOLOWorld(ZS_W)
model.set_classes(ZS_CLS)
res = model.predict(img, conf=ZS_CONF, imgsz=imgsz, verbose=False)

raw = []
if res and res[0].boxes is not None:
    for b in res[0].boxes:
        cid = int(b.cls[0]); name = ZS_CLS[cid] if cid < len(ZS_CLS) else f"cls{cid}"
        conf = float(b.conf[0])
        if conf < min_conf(name):
            continue
        grp = GROUP.get(name, "UNKNOWN_OBSTACLE")
        if grp not in KEEP_GROUPS:                    # 필터: hard_obstacle/agent만
            continue
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        raw.append({"name": name, "group": grp, "conf": conf, "bbox": [x1, y1, x2, y2]})

# --- NMS (그룹 무관 전체 중복 제거) ---
def iou(a, b):
    ax1, ay1, ax2, ay2 = a; bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
    return inter / ua if ua > 0 else 0.0

raw.sort(key=lambda d: -d["conf"])
kept = []
for d in raw:
    if all(iou(d["bbox"], k["bbox"]) < IOU for k in kept):
        kept.append(d)

# --- 바닥평면 좌표 + 출력 ---
print(f"슬라이스 {W}x{H}, fx=fy={fx:.1f}, cx=cy={cx:.0f} | 높이={CAM_H}m, 하향={PITCH}deg")
print(f"필터 통과(HARD/AGENT+접지) {len(kept)}개 (NMS 후)")
print(f"{'name':14}{'group':14}{'conf':>5}  하단중앙px   {'X(m)':>7}{'Z(m)':>7}{'D=√(X²+Z²)':>12}{'접지잘림':>8}")
for d in kept:
    x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
    bcx, bcy = (x1 + x2) // 2, y2
    clipped = "예" if y2 >= H - 2 else "아니오"          # 발밑이 프레임 밑변에 붙음 → 거리 신뢰 낮음
    g, wy, t = pixel_to_ground(bcx, bcy)
    if g is None:
        Xs = Zs = Ds = "지평선위"
        d["ground"] = None
    else:
        X, Z = g; D = math.hypot(X, Z)
        Xs, Zs, Ds = f"{X:7.2f}", f"{Z:7.2f}", f"{D:12.2f}"
        d["ground"] = (X, Z, D)
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.circle(img, (bcx, bcy), 5, (0, 0, 255), -1)
    label = f'{d["name"]} {d["conf"]:.2f}' + ("" if g is None else f' D={math.hypot(*g):.2f}m')
    cv2.putText(img, label, (x1, max(y1 - 5, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    print(f'{d["name"]:14}{d["group"]:14}{d["conf"]:5.2f}  ({bcx:3d},{bcy:3d})  {Xs}{Zs}{Ds}{clipped:>8}   wy={wy:+.3f}')

cv2.imwrite(out_path, img)
print("저장:", out_path)
print("\n[검증] 슬라이스에서 그 큰 박스의 D 값을 실측 1.45m와 비교하세요.")