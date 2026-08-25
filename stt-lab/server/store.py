"""실행 기록 적재 (JSONL).

JSONL을 쓰는 이유: 실험 도중 서버가 죽어도 그 전까지 돈 실행은 남아 있어야 하고,
한 줄이 깨져도 나머지가 읽힌다. DB를 넣으면 이 폴더를 통째로 복사해 다른 PC에서
여는 일이 어려워진다.

채점(`/api/score`)은 이미 적재된 실행에 CER을 덧붙인다. 추가 전용 파일에 수정이
필요하므로 그때만 전량 다시 쓴다 — 실험 기록은 수백 줄 규모라 이 단순함이 옳다.
"""

from __future__ import annotations

import csv
import io
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = Path(os.environ.get("STT_LAB_RESULTS_DIR") or (LAB_ROOT / "results"))
RUNS_PATH = RESULTS_DIR / "runs.jsonl"

_lock = threading.Lock()

# CSV 열 순서. 앞쪽 여덟 개가 화면 비교표와 같은 순서다 —
# 화면에서 보던 것과 CSV가 다른 순서면 옮겨 적다가 틀린다.
CSV_COLUMNS = (
    "ts",
    "model",
    "use_hotwords",
    "vad_filter",
    "cer",
    "rtf",
    "duration_sec",
    "sample",
    "run_id",
    "engine",
    "device",
    "compute_type",
    "beam_size",
    "temperature",
    "language",
    "hotword_count",
    "initial_prompt",
    "elapsed_sec",
    "load_sec",
    "min_avg_logprob",
    "max_no_speech_prob",
    "min_word_prob",
    "mean_word_prob",
    "cer_jamo",
    "wer",
    "strip_punctuation",
    "text",
    "reference",
)


def _ensure_dir() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    # 로컬 시각. 여러 PC의 측정을 합칠 일이 생기면 그때 UTC로 바꾼다.
    return datetime.now().isoformat(timespec="seconds")


def append(record: dict[str, Any]) -> dict[str, Any]:
    _ensure_dir()
    with _lock:
        with RUNS_PATH.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_all() -> list[dict[str, Any]]:
    if not RUNS_PATH.exists():
        return []
    records: list[dict[str, Any]] = []
    with _lock:
        for line in RUNS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # 한 줄이 깨져도 나머지는 살린다. JSONL을 고른 이유가 이거다.
                continue
    return records


def update(run_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    records = read_all()
    updated: dict[str, Any] | None = None
    for record in records:
        if record.get("run_id") == run_id:
            record.update(patch)
            updated = record
    if updated is None:
        return None
    _ensure_dir()
    with _lock:
        tmp = RUNS_PATH.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fp:
            for record in records:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp.replace(RUNS_PATH)
    return updated


def to_csv() -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for record in read_all():
        writer.writerow({key: record.get(key, "") for key in CSV_COLUMNS})
    return buffer.getvalue()
