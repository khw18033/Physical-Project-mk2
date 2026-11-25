"""녹화 프레임(video_frames*/run_XXXX_조건/f_*.jpg)에 자막을 넣어 mp4로 합친다.

사용: python make_videos.py <프레임 폴더> <세션 폴더(runs.csv, traj/)> <출력 폴더> <이름 앞머리> [trial 번호]
출력: 조건별 영상 + 다섯 조건을 한 화면에 나란히 놓은 비교 영상
trial 번호를 주면 그 trial의 run만 쓴다 (한 세션에 trial이 여러 개일 때).
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

FPS = 15
FONT = r"C:\Windows\Fonts\malgunbd.ttf"
LABELS = {
    "A_RobotStop": ("A", "로봇이 탐지 → 정지 → 재탐색 (기존 방식)", "로봇 카메라"),
    "B_OnboardReplan": ("B", "로봇이 탐지 → 주행 중 재계획 (온보드 내비게이션)", "로봇 카메라"),
    "C_InfraNoStop": ("C", "인프라가 탐지 → 정지 없이 경로 교체 (제안)", "360 카메라"),
    "D_OnboardDStarLite": ("D", "로봇이 탐지 → D* Lite 재계획", "로봇 카메라"),
    "E_OnboardDWA": ("E", "로봇이 탐지 → DWA 로컬 회피", "로봇 카메라"),
}
LEGEND = ("하늘색 원: 로봇   파란 선: 지나온 길   초록 선: 따라가는 경로   반투명 빨강: 현실에 새로 놓인 장애물(트윈에는 아직 없음)   "
          "노랑: 탐지되어 트윈에 배치된 장애물   분홍 원: 목표")
BANNER_SEC = 1.6


def font(size):
    return ImageFont.truetype(FONT, size)


def times(text):
    return [float(x) for x in str(text).split("|") if x not in ("", "nan")]


def state_at(traj, t):
    r = traj.iloc[(traj.t - t).abs().argmin()]
    if r.stop_replan == 1 or r.replay_active == 0:
        return "정지: 재탐색 중 (움직이는 로봇 모형은 경로 계산용 가상 주행, 실제 위치는 하늘색 원)", (255, 70, 60)
    if r.speed < 0.03 and t > 0.5:
        return "정지", (255, 70, 60)
    return "주행 중", (90, 230, 120)


def annotate(img, cond, t, traj, row, done):
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(im, "RGBA")
    w, h = im.size
    letter, text, sensor = LABELS[cond]
    d.rectangle([0, 0, w, 78], fill=(0, 0, 0, 190))
    d.text((16, 6), f"{letter}. {text}", font=font(28), fill=(255, 255, 255))
    st, col = ("도착" if row.success == 1 else "종료(미도착)", (120, 200, 255)) if done else state_at(traj, t)
    d.text((16, 44), f"시간 {t:5.1f} s", font=font(24), fill=(255, 255, 255))
    d.text((190, 44), st, font=font(24), fill=col)
    n_app = sum(1 for x in times(row.appear_ts) if x <= t)
    n_det = sum(1 for x in times(row.spawn_ts) if x <= t)
    if done:
        d.text((330, 44), f"총 {row.t_total:.1f} s · 정지 {int(row.stop_events)}회 ({row.stopped_after_appear:.1f} s) · 주행 {row.travel:.1f} m",
               font=font(24), fill=(255, 255, 255))
    else:
        d.text((w - 430, 44), f"장애물 등장 {n_app} / 트윈 반영 {n_det} (전체 {int(row.obstacle_count)})",
               font=font(22), fill=(255, 255, 255))

    # 사건 알림: 방금 일어난 일을 잠깐 띄운다
    y = 88
    if not done:
        if any(0 <= t - x <= BANNER_SEC for x in times(row.spawn_ts)):
            msg = f"{sensor}가 탐지 → 트윈에 장애물 배치(노랑) → 경로 재계획"
            d.rectangle([0, y, w, y + 40], fill=(200, 150, 0, 215))
            d.text((16, y + 5), msg, font=font(24), fill=(0, 0, 0))
            y += 44
        if any(0 <= t - x <= BANNER_SEC for x in times(row.appear_ts)):
            d.rectangle([0, y, w, y + 40], fill=(190, 30, 30, 215))
            d.text((16, y + 5), "현실에 새 장애물이 놓임 (트윈은 아직 모름)", font=font(24), fill=(255, 255, 255))

    d.rectangle([0, h - 34, w, h], fill=(0, 0, 0, 190))
    d.text((10, h - 29), LEGEND, font=font(14), fill=(230, 230, 230))
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def writer(path, size):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, size)
    if not vw.isOpened():
        raise RuntimeError("video writer failed: " + str(path))
    return vw


def main():
    frames_root, session, out, prefix = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    only_trial = int(sys.argv[5]) if len(sys.argv) > 5 else None
    out.mkdir(parents=True, exist_ok=True)
    runs = pd.read_csv(session / "runs.csv", dtype={"appear_ts": str, "spawn_ts": str})
    clips = {}
    for d in sorted(p for p in frames_root.iterdir() if p.is_dir()):
        run = int(d.name.split("_")[1])
        cond = d.name.split("_", 2)[2]
        if cond not in LABELS:
            continue
        row = runs[runs.run == run].iloc[0]
        if only_trial is not None and int(row.trial) != only_trial:
            continue
        traj = pd.read_csv(session / "traj" / f"run_{run:04d}.csv")
        ft = pd.read_csv(d / "frames.csv")
        n_live = len(ft) - FPS            # 마지막 1초는 끝 장면 반복
        imgs = []
        for i, r in ft.iterrows():
            img = cv2.imread(str(d / f"f_{int(r.frame):05d}.jpg"))
            imgs.append(annotate(img, cond, min(r.t, row.t_total), traj, row, i >= n_live))
        imgs += [imgs[-1]] * (FPS * 2)    # 결과를 2초 더 보여 준다
        clips[cond] = imgs
        name = f"{prefix}_{LABELS[cond][0]}_{cond.split('_', 1)[1]}.mp4"
        vw = writer(out / name, (imgs[0].shape[1], imgs[0].shape[0]))
        for im in imgs:
            vw.write(im)
        vw.release()
        print(name, len(imgs), "frames")

    # 나란히 비교: 3 x 2 칸 (마지막 칸은 설명)
    order = [c for c in LABELS if c in clips]
    if len(order) >= 2:
        cw, ch = 640, 360
        n = max(len(clips[c]) for c in order)
        vw = writer(out / f"{prefix}_비교_A-E_동시재생.mp4", (cw * 3, ch * 2))
        note = Image.new("RGB", (cw, ch), (20, 20, 24))
        dn = ImageDraw.Draw(note)
        dn.text((24, 30), "같은 시작·목표·장애물에서\n다섯 방식을 동시에 재생", font=font(30), fill=(255, 255, 255))
        dn.text((24, 150), "먼저 끝난 칸은 마지막 장면에서 멈춰 있습니다.", font=font(20), fill=(210, 210, 210))
        note = cv2.cvtColor(np.asarray(note), cv2.COLOR_RGB2BGR)
        for i in range(n):
            cells = [cv2.resize(clips[c][min(i, len(clips[c]) - 1)], (cw, ch), interpolation=cv2.INTER_AREA) for c in order]
            cells += [note] * (6 - len(cells))
            vw.write(np.vstack([np.hstack(cells[:3]), np.hstack(cells[3:6])]))
        vw.release()
        print("comparison", n, "frames")


if __name__ == "__main__":
    main()
