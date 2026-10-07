#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
apply_received_at.py — server_stream_multi_source.py 에 받은 시각(edge_received_at) 칸을 넣는다
================================================================================
2026-10-07 · 261006_received_at.patch 와 같은 내용을 행 번호 없이 넣는다

하는 일
  server_stream_multi_source.py 의 8곳을 고친다. 자리는 행 번호가 아니라 "기준 줄의 글자"로
  찾으므로, 다른 곳에 줄이 늘거나 줄어 있어도 된다.
    [1] import          from collections import deque 다음에 datetime import 한 줄
    [2] 고정값          STOP = threading.Event() 다음에 KST · received_now()
    [3] add_frame       첫 줄에 received_at = received_now()   (잠금·디스크 쓰기 전)
    [4] add_frame       머리(header)의 "file" 다음에 "edge_received_at"
    [5] add_state       첫 줄에 received_at = received_now()
    [6] add_state       한 줄(rec)의 "topic" 다음에 "edge_received_at"
    [7] /push 영상      넘겨준 쪽의 edge_received_at 을 edge 안에 남긴다
    [8] /push 상태      같음

  - 이미 들어간 곳은 건너뛴다. 몇 번을 돌려도 결과는 같다.
  - 한 곳이라도 기준 줄을 못 찾으면 아무것도 쓰지 않고 끝낸다.
  - 쓰기 전에 원본을 같은 폴더에 백업한다: <파일>.bak_<YYMMDD_HHMMSS>  (있는 파일은 덮어쓰지 않음)
  - 고친 내용을 먼저 문법 검사(compile)하고, 통과해야 원본 자리에 바꿔 넣는다.
  - 줄바꿈(LF·CRLF)과 BOM 은 원래 파일 것을 그대로 둔다.

실행 (파이썬 3.6 이상, 추가 패키지 없음)
  python apply_received_at.py <파일 또는 그 파일이 있는 폴더> [...]     여러 개를 한 번에 줘도 된다
  python apply_received_at.py --check <...>                           고칠 곳만 보여 주고 쓰지 않는다
  인자를 안 주면 지금 폴더의 server_stream_multi_source.py

  예) 노트북   python apply_received_at.py "C:\Users\asdfa\physical mk2\data_stream"
      서버     python3 apply_received_at.py <data_stream 폴더>

되돌리기
  백업 파일(<파일>.bak_<시각>)을 원래 이름으로 복사한다.

끝 코드
  0  적용했거나 이미 적용되어 있음 (--check 는 적용할 수 있음)
  1  파일을 못 찾거나 못 읽음
  2  기준 줄을 못 찾음 · 일부만 들어가 있음 · 문법 오류 — 아무것도 쓰지 않았다

돌고 있는 server_stream_multi_source.py 는 껐다 켜야 바뀐 것이 적용된다.
엣지 노트북과 서버 둘 다 적용해야 엣지가 받은 시각이 서버까지 간다.
"""
import argparse
import hashlib
import os
import shutil
import sys
import time
import unicodedata
from pathlib import Path

TARGET = "server_stream_multi_source.py"
KNOWN = {                                            # md5 → 무엇인지 (확인용으로만 쓴다)
    "53c2540d8ba25328028f9acb8432fff0": "10-06 data_stream 원본 (패치 전)",
    "5783112ebe8c5b8aa1226cfeb213fe75": "10-06 패치본 (Claude outputs/261006_received_at_패치)",
}

STAMP_LINE = "received_at = received_now()            # 잠금·디스크 쓰기 전에 잰다"

# (번호, 이름, 방식, 기준 줄, 새 줄들)
#   after   = 기준 줄 바로 다음에 새 줄들을 넣는다
#   replace = 기준 줄을 새 줄들로 바꾼다
#   새 줄 = (기준 줄 들여쓰기에 더할 칸 수, 글자).  글자가 "" 이면 빈 줄
#   기준 줄은 앞뒤 공백을 뺀 글자가 정확히 같아야 하고, 파일 안에 한 번만 있어야 한다
EDITS = [
    (1, "import datetime", "after",
     "from collections import deque",
     [(0, "from datetime import datetime, timedelta, timezone")]),
    (2, "KST · received_now()", "after",
     "STOP = threading.Event()",
     [(0, "KST = timezone(timedelta(hours=9))     # 받은 시각은 이 기기 시간대와 상관없이 +09:00 으로 적는다"),
      (0, ""),
      (0, ""),
      (0, "def received_now():"),
      (4, '"""이 기기가 받은 시각 (ISO 8601 · 밀리초 · +09:00). 시계는 이 기기 것이다."""'),
      (4, 'return datetime.fromtimestamp(time.time(), KST).isoformat(timespec="milliseconds")')]),
    (3, "add_frame 첫 줄", "after",
     "def add_frame(self, image, sender, via, edge=None):",
     [(4, STAMP_LINE)]),
    (4, "add_frame 머리 칸", "after",
     '"file": self.rel + "/frames/" + fname,',
     [(0, '"edge_received_at": received_at,')]),
    (5, "add_state 첫 줄", "after",
     "def add_state(self, topic, payload, qos, retain, via, edge=None):",
     [(4, STAMP_LINE)]),
    (6, "add_state 한 줄(rec) 칸", "replace",
     'rec = {"n": self.n_state, "topic": topic, "qos": qos, "retain": retain, "via": via, "host": HOSTNAME}',
     [(0, 'rec = {"n": self.n_state, "topic": topic, "edge_received_at": received_at,'),
      (7, '"qos": qos, "retain": retain, "via": via, "host": HOSTNAME}')]),
    (7, "/push 영상 edge 칸", "replace",
     'edge = dict((k, header.get(k)) for k in ("n", "file", "via", "host"))',
     [(0, 'edge = dict((k, header.get(k)) for k in ("n", "file", "via", "host", "edge_received_at"))')]),
    (8, "/push 상태 edge 칸", "replace",
     'edge = dict((k, rec.get(k)) for k in ("n", "via", "host"))',
     [(0, 'edge = dict((k, rec.get(k)) for k in ("n", "via", "host", "edge_received_at"))')]),
]


def md5(data):
    try:
        return hashlib.md5(data).hexdigest()
    except Exception:                          # md5 를 막아 둔 환경
        return None


def pad(text, width):
    """한글처럼 두 칸 먹는 글자를 세어 오른쪽을 공백으로 채운다 (줄 맞춤용)"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - w)


def count_lines(text, nl):
    return text.count(nl) + (0 if (text.endswith(nl) or not text) else 1)


def find(lines, text):
    return [i for i, line in enumerate(lines) if line.strip() == text]


def indent_of(line):
    return line[:len(line) - len(line.lstrip())]


def build(anchor_line, new):
    ind = indent_of(anchor_line)
    return [(ind + " " * extra + text) if text else "" for extra, text in new]


def same(lines, start, texts):
    got = [line.strip() for line in lines[start:start + len(texts)]]
    return got == [t.strip() for t in texts]


def inspect(lines):
    """고칠 곳마다 (상태, 위치) 를 낸다. 상태: todo · done · bad.  위치: todo 는 기준 줄 번호(0부터),
    done 은 들어가 있는 첫 줄 번호(0부터), bad 는 이유 글자."""
    out = []
    for no, name, how, anchor, new in EDITS:
        texts = [t for _, t in new]
        hits = find(lines, anchor)
        if how == "after":
            if len(hits) != 1:
                out.append(("bad", "기준 줄이 %d번 나옴 (1번이어야 함): %s" % (len(hits), anchor)))
            elif same(lines, hits[0] + 1, texts):
                out.append(("done", hits[0] + 1))
            elif hits[0] + 1 < len(lines) and lines[hits[0] + 1].strip() == texts[0].strip():
                out.append(("bad", "일부만 들어가 있음 — 손으로 확인 필요 (기준 줄 %d행)" % (hits[0] + 1)))
            else:
                out.append(("todo", hits[0]))
        else:
            if len(hits) == 1:
                out.append(("todo", hits[0]))
            elif len(hits) > 1:
                out.append(("bad", "기준 줄이 %d번 나옴 (1번이어야 함): %s" % (len(hits), anchor)))
            else:
                done = [i for i in find(lines, texts[0].strip()) if same(lines, i, texts)]
                if len(done) == 1:
                    out.append(("done", done[0]))
                else:
                    out.append(("bad", "기준 줄도, 고친 줄도 없음: %s" % anchor))
    return out


def apply_edits(lines, states):
    """todo 인 곳만 고친 새 목록. 아래쪽부터 고쳐서 위쪽 번호가 밀리지 않게 한다."""
    lines = list(lines)
    todo = sorted(((pos, e) for (st, pos), e in zip(states, EDITS) if st == "todo"),
                  key=lambda x: x[0], reverse=True)
    for pos, (no, name, how, anchor, new) in todo:
        new_lines = build(lines[pos], new)
        if how == "after":
            lines[pos + 1:pos + 1] = new_lines
        else:
            lines[pos:pos + 1] = new_lines
    return lines


def where(state, edit):
    st, pos = state
    n_new = len(edit[4])
    if n_new == 1:
        return "%d행" % (pos + 1)
    return "%d~%d행" % (pos + 1, pos + n_new)


def run(path, check):
    path = Path(path).expanduser()
    if path.is_dir():
        path = path / TARGET
    print("==> %s" % path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        print("  파일을 못 읽음: %s" % e)
        return 1

    bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if bom else raw
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as e:
        print("  UTF-8 이 아님: %s" % e)
        return 1
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    h = md5(raw)
    print("  지금   %d줄 · md5 %s%s" % (count_lines(text, nl), h or "-",
                                     (" · " + KNOWN[h]) if h in KNOWN else ""))

    try:
        compile(text, str(path), "exec")
    except SyntaxError as e:
        print("  고치기 전 파일부터 문법 오류: %s — 아무것도 안 씀" % e)
        return 2

    states = inspect(lines)
    bad = [(e, s) for e, s in zip(EDITS, states) if s[0] == "bad"]
    if bad:
        for e, s in zip(EDITS, states):
            print("  [%d] %s %s" % (e[0], pad(e[1], 24), "문제 — " + s[1] if s[0] == "bad" else "확인됨"))
        print("  고칠 수 없는 곳이 있어 아무것도 쓰지 않았다.")
        return 2

    if all(s[0] == "done" for s in states):
        for e, s in zip(EDITS, states):
            print("  [%d] %s 이미 있음  %s" % (e[0], pad(e[1], 24), where(s, e)))
        print("  이미 전부 들어가 있다 — 바꾼 것 없음")
        return 0

    new_lines = apply_edits(lines, states)
    after = inspect(new_lines)
    if any(s[0] != "done" for s in after):     # 고친 뒤 다시 찾아 8곳이 전부 제자리에 있어야 한다
        print("  고친 결과를 다시 확인했더니 맞지 않음 — 아무것도 안 씀")
        for e, s in zip(EDITS, after):
            print("  [%d] %s %s" % (e[0], pad(e[1], 24), s))
        return 2
    new_text = nl.join(new_lines)
    try:
        compile(new_text, str(path), "exec")
    except SyntaxError as e:
        print("  고친 결과가 문법 검사를 통과하지 못함: %s — 아무것도 안 씀" % e)
        return 2

    verb = "넣을 곳" if check else "넣음"
    for e, s0, s1 in zip(EDITS, states, after):
        print("  [%d] %s %s  → %s" % (e[0], pad(e[1], 24), verb if s0[0] == "todo" else "이미 있음", where(s1, e)))
    new_raw = (b"\xef\xbb\xbf" if bom else b"") + new_text.encode("utf-8")
    h2 = md5(new_raw)
    tail = (" · " + KNOWN[h2]) if h2 in KNOWN else ""
    if check:
        print("  고치면 %d줄 · md5 %s%s" % (count_lines(new_text, nl), h2 or "-", tail))
        print("  --check 라서 아무것도 쓰지 않았다")
        return 0

    stamp = time.strftime("%y%m%d_%H%M%S")
    k = 1
    while True:                                 # 백업은 새로 만들기만 한다
        bak = path.with_name("%s.bak_%s%s" % (path.name, stamp, "" if k == 1 else "_%d" % k))
        try:
            with open(str(bak), "xb") as f:
                f.write(raw)
            break
        except FileExistsError:
            k += 1
        except OSError as e:
            print("  백업을 못 만듦 (%s) — 아무것도 안 씀" % e)
            return 1
    tmp = path.with_name(path.name + ".tmp_received_at")
    try:
        with open(str(tmp), "wb") as f:
            f.write(new_raw)
        try:
            shutil.copymode(str(path), str(tmp))
        except OSError:
            pass
        os.replace(str(tmp), str(path))         # 다 쓴 뒤 한 번에 바꿔 넣는다
    except OSError as e:
        print("  저장 실패 (%s) — 원본은 그대로, 백업 %s" % (e, bak.name))
        try:
            os.remove(str(tmp))
        except OSError:
            pass
        return 1
    if path.read_bytes() != new_raw:
        print("  저장한 내용을 다시 읽었더니 다름 — 백업 %s 로 되돌릴 것" % bak.name)
        return 1
    print("  백업   %s" % bak.name)
    print("  저장함 %d줄 · md5 %s%s" % (count_lines(new_text, nl), h2 or "-", tail))
    print("  문법 검사 통과. 돌고 있으면 껐다 켜야 적용된다.")
    return 0


def main():
    try:
        sys.stdout.reconfigure(errors="replace")    # 윈도우 콘솔에서 못 찍는 글자 때문에 멈추지 않게
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="server_stream_multi_source.py 에 받은 시각(edge_received_at) 칸을 넣는다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="자세한 설명은 파일 맨 위 주석.")
    ap.add_argument("paths", nargs="*", default=[TARGET], metavar="파일또는폴더",
                    help="고칠 파일, 또는 그 파일이 있는 폴더 (기본: 지금 폴더의 %s)" % TARGET)
    ap.add_argument("--check", action="store_true", help="고칠 곳만 보여 주고 쓰지 않는다")
    args = ap.parse_args()
    rc = 0
    for p in args.paths:
        rc = max(rc, run(p, args.check))
    return rc


if __name__ == "__main__":
    sys.exit(main())
