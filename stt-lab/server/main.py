"""stt-lab 서버 — FastAPI 앱 + 정적 서빙 + 라우터.

이 파일에 엔진 이름이 나오면 안 된다. 엔진은 `engines/` 뒤에 있고 여기서는
`get_engine()` 이 준 것을 그대로 쓴다 (REQ-1302). 대시보드(5173 / 8787~8788)와
포트를 겹치지 않게 8799를 쓰고, npm·Vite를 도입하지 않으므로 화면은 이 서버가
정적 파일 한 장으로 내보낸다.

실행: `python -m server.main` (stt-lab/ 에서)
"""

from __future__ import annotations

import os
import re
import shutil
import traceback
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engines, registry, scoring, store
from .engines import TranscribeOptions

LAB_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = LAB_ROOT / "web"
SAMPLES_DIR = Path(os.environ.get("STT_LAB_SAMPLES_DIR") or (LAB_ROOT / "samples"))
PORT = int(os.environ.get("STT_LAB_PORT", "8799"))

ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac", ".mp4"}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

# samples/·results/ 는 .gitignore 로 빠져 있어 clone 직후엔 없다. StaticFiles 가
# 마운트 시점에 폴더 존재를 확인하므로 startup 이벤트가 아니라 여기서 만들어야 한다.
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
store.RESULTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="stt-lab", version="0.1.0")


# --- 조회 -----------------------------------------------------------------


@app.get("/api/models")
def api_models() -> dict[str, Any]:
    """모델 목록 + 현재 런타임. 엔진이 여럿이 되면 항목이 늘어날 뿐 형태는 같다."""
    items = []
    for engine in engines.list_engines():
        info = engine.runtime_info()
        items.append(
            {
                "engine": engine.engine_id,
                "display_name": engine.display_name,
                "models": engine.available_models(),
                "default_model": engine.default_model(),
                **info,
            }
        )
    return {
        "engines": items,
        # 엔진 하나가 임포트에 실패해도 서버는 뜬다. 대신 실패 사실을 숨기지 않는다.
        "load_errors": engines.load_errors(),
    }


@app.get("/api/vocab")
def api_vocab() -> dict[str, Any]:
    try:
        return registry.vocabulary()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/presets")
def api_presets() -> dict[str, Any]:
    """registry 조합으로 만든 시험 발화 목록. 읽고 녹음하면 정답 텍스트가 이미 정해져 있다."""
    try:
        return registry.utterance_presets()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/samples")
def api_samples() -> dict[str, Any]:
    """보관 중인 오디오 목록. '같은 오디오를 설정만 바꿔 다시 돌리기'가 이 목록을 쓴다."""
    items = []
    for path in sorted(SAMPLES_DIR.glob("*"), reverse=True):
        if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES:
            items.append(
                {"name": path.name, "size": path.stat().st_size, "url": f"/samples/{path.name}"}
            )
    return {"count": len(items), "items": items}


@app.get("/api/runs")
def api_runs() -> dict[str, Any]:
    records = store.read_all()
    return {"count": len(records), "items": records}


@app.get("/api/runs.csv")
def api_runs_csv() -> PlainTextResponse:
    # Excel이 UTF-8 CSV를 CP949로 읽어 한글을 깨뜨리므로 BOM을 붙인다.
    return PlainTextResponse(
        "﻿" + store.to_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="stt-lab-runs.csv"'},
    )


# --- 전사 -----------------------------------------------------------------


def _resolve_sample(audio: Optional[UploadFile], sample: Optional[str]) -> tuple[Path, str]:
    """새 업로드를 저장하거나, 기존 보관본을 그대로 쓴다.

    같은 오디오를 설정만 바꿔 다시 돌릴 수 있어야 비교가 성립한다. 그래서 업로드는
    항상 samples/ 에 남기고, 재실행은 파일을 다시 올리지 않고 이름으로 참조한다.
    """
    if sample:
        if not _SAFE_NAME.match(sample):
            raise HTTPException(status_code=400, detail=f"허용되지 않는 파일명: {sample}")
        path = SAMPLES_DIR / sample
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"보관된 오디오가 없다: {sample}")
        return path, sample

    if audio is None or not audio.filename:
        raise HTTPException(status_code=400, detail="audio 파일이나 sample 이름 중 하나는 있어야 한다.")

    suffix = Path(audio.filename).suffix.lower() or ".webm"
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식: {suffix} (허용: {', '.join(sorted(ALLOWED_SUFFIXES))})",
        )
    name = f"{store.now_iso().replace(':', '').replace('-', '')}-{store.new_run_id()[:6]}{suffix}"
    path = SAMPLES_DIR / name
    with path.open("wb") as fp:
        shutil.copyfileobj(audio.file, fp)
    return path, name


def _probability_summary(result_dict: dict[str, Any]) -> dict[str, Any]:
    """REQ-1306 임계값 후보가 될 세 수치의 요약.

    원본은 응답에 그대로 실려 나가고, 여기 요약은 비교표·CSV에서 한 줄로 훑기 위한 것이다.
    임계값을 이 요약만 보고 정하면 안 된다 — 분포를 봐야 한다.
    """
    segments = result_dict["segments"]
    words = result_dict["words"]
    probs = [w["probability"] for w in words if w.get("probability") is not None]
    return {
        "min_avg_logprob": min((s["avg_logprob"] for s in segments), default=None),
        "max_no_speech_prob": max((s["no_speech_prob"] for s in segments), default=None),
        "min_word_prob": min(probs, default=None),
        "mean_word_prob": (sum(probs) / len(probs)) if probs else None,
    }


@app.post("/api/transcribe")
def api_transcribe(
    audio: Optional[UploadFile] = File(default=None),
    sample: Optional[str] = Form(default=None),
    engine_id: Optional[str] = Form(default=None),
    model: Optional[str] = Form(default=None),
    language: str = Form(default="ko"),
    use_hotwords: bool = Form(default=True),
    initial_prompt: str = Form(default=""),
    vad_filter: bool = Form(default=True),
    beam_size: int = Form(default=5),
    temperature: float = Form(default=0.0),
    reference: str = Form(default=""),
    strip_punctuation: bool = Form(default=True),
) -> dict[str, Any]:
    engine = engines.get_engine(engine_id)
    audio_path, sample_name = _resolve_sample(audio, sample)

    # hotwords 는 registry 원본에서 매번 새로 뽑는다. 화면이 보내온 문자열을 믿으면
    # 원본이 바뀌었을 때 조용히 옛 어휘로 측정하게 된다.
    hotwords = None
    hotword_count = 0
    if use_hotwords:
        vocab = registry.vocabulary()
        hotwords = vocab["hotwords"]
        hotword_count = vocab["count"]

    options = TranscribeOptions(
        model=model or engine.default_model(),
        language=language,
        hotwords=hotwords,
        initial_prompt=initial_prompt.strip() or None,
        vad_filter=vad_filter,
        beam_size=beam_size,
        temperature=temperature,
    )

    try:
        result = engine.transcribe(str(audio_path), options).to_dict()
    except Exception as exc:
        # 모델 다운로드 실패·오디오 디코딩 실패가 여기로 온다. 화면에 원문을 그대로 보여준다.
        return JSONResponse(
            status_code=500,
            content={
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=6),
            },
        )

    summary = _probability_summary(result)
    run_id = store.new_run_id()
    record = {
        "run_id": run_id,
        "ts": store.now_iso(),
        "sample": sample_name,
        "engine": result["engine"],
        "model": result["model"],
        "device": result["device"],
        "compute_type": result["compute_type"],
        "use_hotwords": use_hotwords,
        "hotword_count": hotword_count,
        "vad_filter": vad_filter,
        "beam_size": beam_size,
        "temperature": temperature,
        "language": language,
        "initial_prompt": options.initial_prompt or "",
        "duration_sec": round(result["duration_sec"], 3),
        "elapsed_sec": round(result["elapsed_sec"], 3),
        "load_sec": round(result["load_sec"], 3),
        "rtf": round(result["rtf"], 3),
        "text": result["text"],
        **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in summary.items()},
        "reference": "",
        "cer": "",
        "cer_jamo": "",
        "wer": "",
        "strip_punctuation": strip_punctuation,
    }

    # 정답을 미리 알고 녹음한 경우(프리셋 발화)는 여기서 바로 채점한다.
    scored = None
    if reference.strip():
        scored = scoring.score(reference, result["text"], strip_punctuation=strip_punctuation)
        record.update(
            {
                "reference": reference.strip(),
                "cer": scored["cer"],
                "cer_jamo": scored["cer_jamo"],
                "wer": scored["wer"],
            }
        )

    store.append(record)

    return {
        "run_id": run_id,
        "sample": sample_name,
        "sample_url": f"/samples/{sample_name}",
        "summary": summary,
        "score": scored,
        "record": record,
        **result,
    }


# --- 채점 -----------------------------------------------------------------


class ScoreRequest(BaseModel):
    reference: str
    hypothesis: str
    strip_punctuation: bool = True
    # 채점 결과를 이미 적재된 실행에 덧붙일 때만 준다.
    run_id: Optional[str] = None


@app.post("/api/score")
def api_score(body: ScoreRequest) -> dict[str, Any]:
    result = scoring.score(
        body.reference, body.hypothesis, strip_punctuation=body.strip_punctuation
    )
    updated = None
    if body.run_id:
        updated = store.update(
            body.run_id,
            {
                "reference": body.reference.strip(),
                "cer": result["cer"],
                "cer_jamo": result["cer_jamo"],
                "wer": result["wer"],
                "strip_punctuation": body.strip_punctuation,
            },
        )
    return {**result, "run_id": body.run_id, "record": updated}


# --- 정적 서빙 -------------------------------------------------------------
# 라우터보다 뒤에 mount 해야 "/" catch-all 이 API를 가리지 않는다.

app.mount("/samples", StaticFiles(directory=str(SAMPLES_DIR)), name="samples")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    import uvicorn

    print(f"stt-lab  →  http://127.0.0.1:{PORT}")
    print(f"registry →  {registry.registry_path()}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
