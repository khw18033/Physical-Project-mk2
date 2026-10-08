#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pairs.py — 360 · 드론 · GO1 사진 중 같은 시각에 찍힌 것끼리 짝 목록(pairs.csv)을 만든다
================================================================================
2026-10-07 · 하천 실증 대비 (다음 단계 match_pairs.py 가 이 pairs.csv 를 읽는다)

무엇을 하나
  server_stream_multi_source.py 가 저장한 실행 폴더에서 소스별 frames.jsonl · states.jsonl 을 읽어
  기준 소스(기본 360)의 사진 한 장마다 드론 · GO1 에서 시각이 가장 가까운 사진을 찾는다.
  원본 파일은 읽기만 한다.

입력 — 저장 폴더만 주면 실행 폴더는 알아서 찾는다
  DS 꼴    <저장 폴더>/cam360/<실행>/ · drone/<실행>/ · robot1/<실행>/
  복사 꼴  <폴더>/<실행>_360 · <실행>_drone · <실행>_go1
  쓰는 것  frames.jsonl (필수) · states.jsonl (드론 위치 · GO1 위치) · vision/*/results.jsonl 의 recv_ms (받은 시각)
           frames/<번호>.jpg 는 비었는지만 확인한다

출력 — <출력 폴더>/<실행>/
  pairs.csv            기준 사진 한 장 = 한 줄 (짝이 없어도 남긴다. status 로 구분)
  flagged_frames.csv   고치거나 뺀 사진과 이유
  summary.txt          소스별 통계 · 시계 · 짝 비율
  pairs_meta.json      입력 · 옵션 · 개수 (match_pairs.py 가 읽는다)

사용 (파이썬 3.8 이상, 표준 라이브러리만)
  python build_pairs.py --list                                  실행 목록
  python build_pairs.py                                         기본 저장 폴더의 가장 최근 실행
  python build_pairs.py --run 20261002_185223
  python build_pairs.py --save /mnt/c/.../stream_data --run 20261002_185223
  python build_pairs.py --save /mnt/c/Users/me/Desktop --run 20261002_185223    (복사 꼴)
  python build_pairs.py --cam360 <폴더> --drone <폴더> --go1 <폴더>               (폴더를 직접)

시각 (모두 epoch 초로 바꿔 비교한다)
  360   sender.timestamp   글자, epoch 초      — 360 노트북이 카메라 스트림에서 그 장을 받은 시각
  드론  sender.ts           숫자, epoch 초      — pi3 가 찍은 시각
  GO1   sender.X-Timestamp  글자, epoch 밀리초  — pi7 이 내보낸 시각

고치거나 빼는 사진 (flagged_frames.csv 에 전부 남는다)
  clock_fixed    시계가 튄 장 → 받은 시각으로 고쳐 쓴다 (빼지 않는다)
                 받은 시각과 평소보다 --clock-tol 초 넘게 어긋나고, 보낸 쪽 시각이 앞 사진보다 뒤로 갔거나
                 어긋남이 --clock-jump 초를 넘을 때. 드론 pi3 가 다시 켜진 직후 시계가 몇 분 늦게 시작하는 경우
                 (10-02 저녁 실행에서 65장, 155초 · 89초 늦음)
  late_arrival   받은 시각과 어긋나지만 보낸 쪽 시각은 순서대로 → 네트워크가 잠깐 막혀 늦게 도착한 것.
                 보낸 쪽 시각을 그대로 쓴다 (표시만. 10-02 저녁 드론 2장)
  clock_suspect  받은 시각이 없는데 보낸 쪽 시각이 앞 사진보다 --clock-tol 초 넘게 뒤로 감 → 뺀다
  resend         GO1 스트림이 멈췄을 때 pi7 이 마지막 사진을 새 시각으로 다시 보낸 사본 (같은 X-Sha1) → 뺀다
                 처음 온 원본은 원래 시각 그대로 남는다
  empty_file     사진 파일이 없거나 0바이트 → 그 장 대신 다음으로 가까운 장을 쓴다

받은 시각을 어디서 얻나 (있는 것부터)
  1) frames.jsonl 의 edge_received_at (received_at 패치본 DS)
  2) vision/*/results.jsonl 의 recv_ms (비전이 처리한 장만)
  3) --use-mtime: 사진 파일 수정 시각 (엣지 원본 폴더에서만. 복사하면 수정 시각이 바뀐다)
"""
import argparse
import bisect
import csv
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
VERSION = "2026-10-07"
SOURCES = ("cam360", "drone", "go1")
COPY_SUFFIX = {"cam360": "360", "drone": "drone", "go1": "go1"}
RUN_RE = re.compile(r"^\d{8}_\d{6}(?:_\d+)?$")
COPY_RE = re.compile(r"^(\d{8}_\d{6}(?:_\d+)?)_(360|drone|go1)$")
HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- 시각
def iso(t):
    return "" if t is None else datetime.fromtimestamp(t, KST).isoformat(timespec="milliseconds")


def parse_iso(s):
    try:
        d = datetime.fromisoformat(str(s))
        if d.tzinfo is None:
            d = d.replace(tzinfo=KST)
        return d.timestamp()
    except (TypeError, ValueError):
        return None


def sender_time(src, s):
    """보낸 쪽 시각 (epoch 초). 못 읽으면 None"""
    try:
        if src == "cam360":
            return float(s["timestamp"])
        if src == "drone":
            for k in ("ts", "captured_at", "observed_at"):
                if isinstance(s.get(k), (int, float)):
                    return float(s[k])
            return None
        if "X-Timestamp" in s:
            return int(str(s["X-Timestamp"]).strip()) / 1000.0
        return parse_iso(s.get("X-Timestamp-Iso"))
    except (KeyError, TypeError, ValueError):
        return None


def sender_seq(src, s):
    k = {"cam360": "seq", "drone": "frame_seq", "go1": "X-Frame-Seq"}[src]
    try:
        return int(str(s.get(k)).strip())
    except (TypeError, ValueError):
        return None


def read_jsonl(path):
    """다 쓴 줄만 (DS 가 쓰는 중인 마지막 줄은 건너뛴다)"""
    if not path.exists():
        return
    with open(path, "rb") as f:
        for line in f:
            if not line.endswith(b"\n"):
                break
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def pct(a, p):
    if not a:
        return None
    a = sorted(a)
    return a[min(len(a) - 1, int(len(a) * p))]


# ---------------------------------------------------------------- 실행 폴더 찾기
def default_save():
    for p in (HERE.parent / "data_stream" / "stream_data", HERE.parent / "stream_data", Path.cwd() / "stream_data"):
        if p.is_dir():
            return p
    return None


def find_runs(save, robot):
    """{실행: {소스: 폴더}} — DS 꼴과 복사 꼴을 모두 본다"""
    runs = {}
    ds_name = {"cam360": "cam360", "drone": "drone", "go1": robot}
    for src, name in ds_name.items():
        d = save / name
        if d.is_dir():
            for r in d.iterdir():
                if r.is_dir() and RUN_RE.match(r.name) and (r / "frames.jsonl").exists():
                    runs.setdefault(r.name, {})[src] = r
    for r in save.iterdir():
        m = COPY_RE.match(r.name)
        if m and r.is_dir() and (r / "frames.jsonl").exists():
            src = {v: k for k, v in COPY_SUFFIX.items()}[m.group(2)]
            runs.setdefault(m.group(1), {})[src] = r
    return runs


def count_lines(p):
    try:
        with open(p, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# ---------------------------------------------------------------- 소스 하나 읽기
class Source:
    def __init__(self, name, folder):
        self.name, self.dir = name, folder
        self.frames = []            # dict: n, path, file, t_sender, t_recv, recv_from, t, seq, sha, flags
        self.recv_from = None
        self.offset_base = None     # 받은 시각 − 보낸 쪽 시각 의 중앙값 (초)
        self.offsets = []

    def load(self, use_mtime):
        recv_vision = {}
        for rj in sorted((self.dir / "vision").glob("*/results.jsonl")) if (self.dir / "vision").is_dir() else []:
            for r in read_jsonl(rj):
                n, ms = r.get("n"), r.get("recv_ms")
                if n is not None and isinstance(ms, (int, float)) and n not in recv_vision:
                    recv_vision[n] = ms / 1000.0
        for r in read_jsonl(self.dir / "frames.jsonl"):
            s = r.get("sender") or {}
            name = Path(str(r.get("file") or "")).name
            if not name:
                continue
            f = {"n": r.get("n"), "file": r.get("file"), "path": self.dir / "frames" / name,
                 "t_sender": sender_time(self.name, s), "seq": sender_seq(self.name, s),
                 "sha": s.get("X-Sha1"), "t_recv": None, "recv_from": "", "flags": []}
            for k in ("edge_received_at", "received_at"):
                if r.get(k):
                    f["t_recv"], f["recv_from"] = parse_iso(r[k]), "edge_received_at"
                    break
            if f["t_recv"] is None and f["n"] in recv_vision:
                f["t_recv"], f["recv_from"] = recv_vision[f["n"]], "vision_recv_ms"
            if f["t_recv"] is None and use_mtime:
                try:
                    f["t_recv"], f["recv_from"] = f["path"].stat().st_mtime, "file_mtime"
                except OSError:
                    pass
            if f["t_sender"] is None:
                f["flags"].append("no_time")
            self.frames.append(f)
        self.frames.sort(key=lambda f: (f["n"] is None, f["n"]))     # 도착 순서 (DS 저장 번호)
        kinds = sorted(set(f["recv_from"] for f in self.frames if f["recv_from"]))
        self.recv_from = ",".join(kinds) if kinds else "없음"

    def fix_clock(self, clock_tol, clock_jump, offset):
        """시계가 튄 장은 받은 시각으로 고치고, 늦게 도착한 장은 그대로 둔다

        받은 시각 − 보낸 쪽 시각 이 평소(중앙값)보다 clock_tol 초 넘게 어긋나면 둘 중 하나다
          시계가 튐   보낸 쪽 시각이 도착 순서로 앞 사진보다 뒤로 갔거나, 어긋남이 clock_jump 초를 넘는다
                      → clock_fixed: 받은 시각 − 평소 차이 로 고쳐 쓴다
          늦게 도착   보낸 쪽 시각은 순서대로다 (네트워크가 잠깐 막힘) → late_arrival: 보낸 쪽 시각을 그대로 쓴다
        받은 시각이 없는 장은 보낸 쪽 시각이 앞 사진보다 clock_tol 초 넘게 뒤로 가면 clock_suspect 로 뺀다
        """
        offs = [f["t_recv"] - f["t_sender"] for f in self.frames
                if f["t_recv"] is not None and f["t_sender"] is not None]
        if offs:
            base = statistics.median(offs)
            good = [o for o in offs if abs(o - base) <= clock_tol]
            self.offset_base = statistics.median(good) if good else base
            self.offsets = good
        hi = None       # 지금까지 시계가 멀쩡했던 장의 보낸 쪽 시각 최댓값 (도착 순서)
        for f in self.frames:
            if f["t_sender"] is None:
                f["t"] = None
                continue
            t = f["t_sender"]
            back = hi is not None and t < hi - clock_tol
            if f["t_recv"] is not None and self.offset_base is not None:
                dev = (f["t_recv"] - t) - self.offset_base
                if abs(dev) > clock_tol and (back or abs(dev) > clock_jump):
                    f["flags"].append("clock_fixed")
                    t = f["t_recv"] - self.offset_base
                elif abs(dev) > clock_tol:
                    f["flags"].append("late_arrival")
            elif back:
                f["flags"].append("clock_suspect")
            if not ({"clock_fixed", "clock_suspect"} & set(f["flags"])):
                hi = t if hi is None else max(hi, t)
            f["t"] = t + offset

    def mark_resend(self):
        """GO1: 같은 X-Sha1 이 다시 오면 (멈춤 중 재전송) 두 번째부터 뺀다"""
        seen = set()
        for f in self.frames:
            if not f["sha"]:
                continue
            if f["sha"] in seen:
                f["flags"].append("resend")
            else:
                seen.add(f["sha"])

    def usable(self):
        return [f for f in self.frames
                if f.get("t") is not None and not ({"clock_suspect", "resend", "no_time"} & set(f["flags"]))]


# ---------------------------------------------------------------- 상태 (위치)
def drone_poses(folder):
    """드론 state: 보낸 쪽 ts → 위치 · 자세 (사진 ts 와 같은 값)"""
    out = {}
    for r in read_jsonl(folder / "states.jsonl"):
        if not str(r.get("topic", "")).endswith("/state"):
            continue
        try:
            p = json.loads(r.get("payload") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(p, dict) or not isinstance(p.get("ts"), (int, float)):
            continue
        g, a, al = p.get("gps") or {}, p.get("attitude") or {}, p.get("altitude") or {}
        out[round(p["ts"], 6)] = {"lat": g.get("lat"), "lon": g.get("lon"), "fix_type": g.get("fix_type"),
                                  "amsl_m": al.get("amsl_m"), "relative_m": al.get("relative_m"),
                                  "roll_deg": a.get("roll_deg"), "pitch_deg": a.get("pitch_deg"),
                                  "yaw_deg": a.get("yaw_deg")}
    return out


def go1_states(folder):
    """GO1 state (약 5초마다): [(시각, x, y, heading_deg)] — 사진과 같은 pi7 시계"""
    out = []
    for r in read_jsonl(folder / "states.jsonl"):
        if "/robot/" not in str(r.get("topic", "")) or not str(r.get("topic")).endswith("/state"):
            continue
        try:
            p = json.loads(r.get("payload") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(p, dict):
            continue
        t = parse_iso((p.get("freshness") or {}).get("sampled_at") or p.get("timestamp"))
        pos = p.get("position") or {}
        if t is not None and pos:
            out.append((t, pos.get("x"), pos.get("y"), pos.get("heading_deg")))
    out.sort()
    return out


# ---------------------------------------------------------------- 짝 찾기
class Finder:
    """시각순 목록에서 가장 가까운 '쓸 수 있는' 사진. 빈 파일이면 다음으로 가까운 장"""

    def __init__(self, frames, check_files):
        self.f = sorted(frames, key=lambda x: x["t"])
        self.t = [x["t"] for x in self.f]
        self.check = check_files
        self.ok_cache = {}

    def ok(self, fr):
        if not self.check:
            return True
        key = id(fr)
        if key not in self.ok_cache:
            try:
                good = fr["path"].stat().st_size > 0
            except OSError:
                good = False
            self.ok_cache[key] = good
            if not good:
                fr["flags"].append("empty_file")
        return self.ok_cache[key]

    def nearest(self, t, window):
        i = bisect.bisect_left(self.t, t)
        lo, hi = i - 1, i
        while lo >= 0 or hi < len(self.f):
            dl = t - self.t[lo] if lo >= 0 else float("inf")
            dh = self.t[hi] - t if hi < len(self.f) else float("inf")
            if min(dl, dh) > window:
                return None
            if dl <= dh:
                fr, lo = self.f[lo], lo - 1
            else:
                fr, hi = self.f[hi], hi + 1
            if self.ok(fr):
                return fr
        return None


def nearest_go1_state(states, t):
    if not states or t is None:
        return None
    ts = [s[0] for s in states]
    i = bisect.bisect_left(ts, t)
    j = min((j for j in (i - 1, i) if 0 <= j < len(states)), key=lambda j: abs(ts[j] - t))
    return states[j], states[j][0] - t


def fmt(v, nd=None):
    if v is None:
        return ""
    if nd is not None and isinstance(v, float):
        return ("%." + str(nd) + "f") % v
    return v


# ---------------------------------------------------------------- 메인
def parse_offsets(items):
    out = {s: 0.0 for s in SOURCES}
    for it in items or []:
        for part in it.split(","):
            if not part.strip():
                continue
            k, _, v = part.partition("=")
            k = k.strip().lower()
            k = "cam360" if k == "360" else k
            if k not in out:
                raise SystemExit("--offset 소스 이름은 cam360 · drone · go1: %s" % part)
            out[k] = float(v)
    return out


def main():
    ap = argparse.ArgumentParser(description="360 · 드론 · GO1 사진 중 같은 시각에 찍힌 것끼리 짝 목록(pairs.csv)을 만든다",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--save", help="저장 폴더 (server_stream_multi_source.py --save, 또는 복사한 폴더들이 있는 곳)")
    ap.add_argument("--run", help="실행 이름 (예: 20261002_185223). 안 주면 세 소스에 다 있는 가장 최근 실행")
    ap.add_argument("--list", action="store_true", help="실행 목록만 보여 주고 끝낸다")
    ap.add_argument("--cam360", help="360 실행 폴더를 직접 준다 (frames.jsonl 이 있는 폴더)")
    ap.add_argument("--drone", help="드론 실행 폴더를 직접 준다")
    ap.add_argument("--go1", help="GO1 실행 폴더를 직접 준다")
    ap.add_argument("--robot", default="robot1", help="GO1 이 들어오는 DS 소스 이름 (기본 robot1)")
    ap.add_argument("--anchor", default="cam360", choices=SOURCES, help="기준 소스 (기본 cam360)")
    ap.add_argument("--tol", type=float, default=0.5, help="짝으로 인정하는 시각 차이 (초, 기본 0.5)")
    ap.add_argument("--window", type=float, default=2.0, help="이 안에서 가장 가까운 장을 찾아 기록한다 (초, 기본 2.0)")
    ap.add_argument("--offset", action="append", metavar="소스=초",
                    help="소스별 시각 보정 (보낸 쪽 시각에 더함). 예: --offset cam360=-0.5")
    ap.add_argument("--clock-tol", type=float, default=2.0,
                    help="받은 시각과 이만큼 넘게 어긋나면 시계가 튄 것인지 본다 (초, 기본 2.0)")
    ap.add_argument("--clock-jump", type=float, default=30.0,
                    help="어긋남이 이보다 크면 순서와 상관없이 시계가 튄 것으로 본다 (초, 기본 30)")
    ap.add_argument("--use-mtime", action="store_true",
                    help="사진 파일 수정 시각을 받은 시각으로 쓴다 (엣지 원본 폴더에서만 의미가 있다)")
    ap.add_argument("--no-file-check", action="store_true", help="사진 파일이 비었는지 확인하지 않는다")
    ap.add_argument("--out", help="출력 폴더 (기본: 이 파일 옆 out/)")
    a = ap.parse_args()

    # 폴더 정하기
    dirs = {s: Path(getattr(a, s)).expanduser().resolve() for s in SOURCES if getattr(a, s)}
    run = a.run
    if not dirs:
        save = Path(a.save).expanduser().resolve() if a.save else default_save()
        if save is None or not save.is_dir():
            raise SystemExit("저장 폴더를 못 찾았습니다. --save <폴더> 를 주세요")
        runs = find_runs(save, a.robot)
        if a.list:
            print("저장 폴더: %s" % save)
            print("%-20s %8s %8s %8s" % ("실행", "cam360", "drone", "go1"))
            for r in sorted(runs):
                print("%-20s %8s %8s %8s" % (r, *[count_lines(runs[r][s] / "frames.jsonl") if s in runs[r] else "-"
                                                 for s in SOURCES]))
            return 0
        if not runs:
            raise SystemExit("실행 폴더가 없습니다: %s" % save)
        if run is None:
            full = [r for r in runs if all(s in runs[r] for s in SOURCES)]
            run = max(full) if full else max(runs)
            if not full:
                print("주의: 세 소스가 다 있는 실행이 없어 가장 최근 실행 %s 를 씁니다" % run)
        if run not in runs:
            raise SystemExit("실행 %s 가 없습니다. --list 로 확인하세요" % run)
        dirs = runs[run]
    else:
        run = run or next((COPY_RE.match(p.name).group(1) if COPY_RE.match(p.name) else p.name)
                          for p in dirs.values())
    if a.anchor not in dirs:
        raise SystemExit("기준 소스 %s 의 폴더가 없습니다" % a.anchor)
    offsets = parse_offsets(a.offset)
    t0 = time.time()

    # 읽기 · 시계 · 재전송
    src = {}
    for s, d in dirs.items():
        x = Source(s, d)
        x.load(a.use_mtime)
        x.fix_clock(a.clock_tol, a.clock_jump, offsets[s])
        if s == "go1":
            x.mark_resend()
        src[s] = x
        print("%-6s %6d장  받은 시각: %s  ← %s" % (s, len(x.frames), x.recv_from, d))
    finders = {s: Finder(x.usable(), not a.no_file_check) for s, x in src.items()}
    poses = drone_poses(dirs["drone"]) if "drone" in dirs else {}
    gstates = go1_states(dirs["go1"]) if "go1" in dirs else []

    # 짝
    rows, stat = [], {}
    others = [s for s in SOURCES if s != a.anchor]
    anchor_frames = sorted((f for f in src[a.anchor].frames if f.get("t") is not None), key=lambda f: f["t"])
    for f in anchor_frames:
        row = {"pair_id": len(rows) + 1, "anchor": a.anchor, "t_anchor": iso(f["t"])}
        bad_anchor = bool({"clock_suspect", "resend", "no_time"} & set(f["flags"])) or not finders[a.anchor].ok(f)
        got = []
        picks = {a.anchor: (f, 0.0)}
        for s in others:
            if s not in finders:
                continue
            g = finders[s].nearest(f["t"], a.window)
            if g is not None:
                dt = g["t"] - f["t"]
                picks[s] = (g, dt)
                if abs(dt) <= a.tol:
                    got.append(s)
        for s in SOURCES:
            g, dt = picks.get(s, (None, None))
            row[s + "_n"] = g["n"] if g else ""
            row[s + "_time"] = iso(g["t"]) if g else ""
            row[s + "_dt_s"] = fmt(dt, 3) if g else ""
            row[s + "_flags"] = "|".join(g["flags"]) if g else ""
            row[s + "_path"] = str(g["path"]) if g else ""
        if bad_anchor:
            status = "anchor_bad"
        elif len(got) == len(others):
            status = "all"
        elif got:
            status = a.anchor + "+" + "+".join(got)
        else:
            status = a.anchor + "_only"
        row["status"] = status
        stat[status] = stat.get(status, 0) + 1
        dg = picks.get("drone", (None, None))[0]
        pose = poses.get(round(dg["t_sender"], 6)) if dg and dg["t_sender"] is not None else None
        for k in ("lat", "lon", "fix_type", "amsl_m", "relative_m", "roll_deg", "pitch_deg", "yaw_deg"):
            row["drone_" + k] = fmt((pose or {}).get(k))
        gg = picks.get("go1", (None, None))[0]
        ns = nearest_go1_state(gstates, gg["t_sender"]) if gg else None
        row["go1_x"] = fmt(ns[0][1]) if ns else ""
        row["go1_y"] = fmt(ns[0][2]) if ns else ""
        row["go1_heading_deg"] = fmt(ns[0][3]) if ns else ""
        row["go1_state_dt_s"] = fmt(ns[1], 2) if ns else ""
        rows.append(row)

    # 쓰기
    out_dir = (Path(a.out).expanduser().resolve() if a.out else HERE / "out") / run
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["pair_id", "status", "anchor", "t_anchor"]
    for s in SOURCES:
        cols += [s + "_n", s + "_time", s + "_dt_s", s + "_flags", s + "_path"]
    cols += ["drone_lat", "drone_lon", "drone_fix_type", "drone_amsl_m", "drone_relative_m",
             "drone_roll_deg", "drone_pitch_deg", "drone_yaw_deg",
             "go1_x", "go1_y", "go1_heading_deg", "go1_state_dt_s"]
    with open(out_dir / "pairs.csv", "w", newline="", encoding="utf-8-sig") as fo:   # 엑셀에서 한글이 안 깨지게
        w = csv.DictWriter(fo, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(out_dir / "flagged_frames.csv", "w", newline="", encoding="utf-8-sig") as fo:
        w = csv.writer(fo)
        w.writerow(["source", "n", "reason", "t_sender", "t_used", "recv_from", "path"])
        for x in src.values():
            for f in x.frames:
                if f["flags"]:
                    w.writerow([x.name, f["n"], "|".join(f["flags"]), iso(f["t_sender"]), iso(f.get("t")),
                                f["recv_from"], f["path"]])

    # 요약
    L = []
    L.append("build_pairs.py %s · 실행 %s · 기준 %s · 허용 ±%.2fs · 보정 %s"
             % (VERSION, run, a.anchor, a.tol, " ".join("%s%+g" % (k, v) for k, v in offsets.items() if v) or "없음"))
    L.append("")
    L.append("[소스]")
    for s, x in src.items():
        ts = sorted(f["t"] for f in x.frames if f.get("t") is not None)
        d = [(b - c) * 1000 for c, b in zip(ts, ts[1:])]
        fl = {}
        for f in x.frames:
            for k in f["flags"]:
                fl[k] = fl.get(k, 0) + 1
        L.append("  %-6s %6d장  %s ~ %s  간격 중앙 %s ms  1초+ 끊김 %d  표시 %s"
                 % (s, len(x.frames), iso(ts[0])[11:23] if ts else "-", iso(ts[-1])[11:23] if ts else "-",
                    "%.0f" % pct(d, .5) if d else "-", sum(1 for v in d if v > 1000),
                    " ".join("%s %d" % kv for kv in sorted(fl.items())) or "없음"))
    L.append("")
    L.append("[시계] 받은 시각 − 보낸 쪽 시각 (튄 장 뺀 값). 최소값 ≈ 시계 차이 (가장 빨리 도착한 장)")
    for s, x in src.items():
        if x.offsets:
            m = min(x.offsets)
            L.append("  %-6s %6d장  최소 %+.3fs  중앙 %+.3fs  95%% %+.3fs  → %s  (받은 시각: %s)"
                     % (s, len(x.offsets), m, statistics.median(x.offsets), pct(x.offsets, .95),
                        ("보낸 쪽 시계가 받는 PC보다 약 %.2f초 빠름 (맞추려면 --offset %s=%+.2f)" % (-m, s, m))
                        if m < -0.05 else "받는 PC 시계와 거의 같음", x.recv_from))
        else:
            L.append("  %-6s 받은 시각 없음 — 시계 차이를 잴 수 없다" % s)
    L.append("")
    L.append("[짝] 기준 %s %d장" % (a.anchor, len(rows)))
    for k, v in sorted(stat.items(), key=lambda kv: -kv[1]):
        L.append("  %-22s %6d (%.1f%%)" % (k, v, 100.0 * v / max(1, len(rows))))
    ok_rows = [r for r in rows if r["status"] != "anchor_bad"]
    for th in (0.1, 0.25, 0.5, 1.0):
        both = sum(1 for r in ok_rows if all(r[s + "_dt_s"] != "" and abs(float(r[s + "_dt_s"])) <= th
                                             for s in others if s in finders))
        L.append("  ±%.2fs 안에 %s 모두 있음: %d (%.1f%%)" % (th, "·".join(o for o in others if o in finders), both,
                                                       100.0 * both / max(1, len(ok_rows))))
    L.append("")
    L.append("출력 %s  (%.1f초)" % (out_dir, time.time() - t0))
    text = "\n".join(L)
    (out_dir / "summary.txt").write_text(text + "\n", encoding="utf-8")
    meta = {"version": VERSION, "created_at": iso(time.time()), "run": run,
            "dirs": {s: str(d) for s, d in dirs.items()}, "anchor": a.anchor, "tol_s": a.tol,
            "window_s": a.window, "offsets_s": offsets, "clock_tol_s": a.clock_tol, "clock_jump_s": a.clock_jump,
            "use_mtime": a.use_mtime,
            "file_check": not a.no_file_check, "rows": len(rows), "status": stat,
            "clock_offset_median_s": {s: x.offset_base for s, x in src.items()},
            "recv_from": {s: x.recv_from for s, x in src.items()}}
    (out_dir / "pairs_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
