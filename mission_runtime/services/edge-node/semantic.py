"""엣지 의미 계층: 특징 사전 + CLIP + LLM(사전 생성) + VLM(미지 crop 서술).

implements: AI-E-04, AI-S-03, AI-S-04, AI-S-06, AI-L-01, AI-B-08, AI-C-05,  AI-C-19

세 provider가 서로 다른 일을 한다. 하나가 없어도 나머지는 돈다(AI-C-05).

  * **특징 사전 + CLIP** — 클래스 이름이 아니라 **특징 문구**에 crop을 맞춘다.
    `demo/test/class_features.json` 형식을 그대로 쓴다. 이름 하나로 비교하는 것보다
    사전이 나은 이유는 실측 근거가 있다: 2026-09-10 dog 실험에서 한국어 특징 문장은
    CLIP이 거의 구분하지 못했고(그래서 사전은 **항상 영어**), 색 하나만 필수조건으로
    쓰면 "파란 옷 입은 사람"류 오탐을 못 걸렀다(그래서 색+모양+참조 AND 게이트).

  * **LLM** — 사전에 없는 클래스가 질의로 들어오면 항목을 즉석 생성한다.
    프롬프트는 `research/class_feature_llm/prompts.py`의 `reason_json` 변형을
    그대로 따른다(판단 → JSON 순서). 생성물은 **검증 전까지 사전에 올리지 않는다**.

  * **VLM** — 미지 crop을 자유 서술한다. 나오는 것은 **가설**이지 확정 label이
    아니다(AI-S-04). 서술에서 뽑은 명사는 다음 프레임의 CLIP 프롬프트 후보가 되고,
    사람 확인을 거쳐야 학습 데이터로 승격된다(AI-L-02).

**경계(AI-C-19)**: 여기 어느 것도 정답을 만들지 않는다. 근거·점수·가설만 만든다.
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np


# --------------------------------------------------------------------------
# Ollama — LLM·VLM 공통 바닥. HTTP 하나뿐이라 SDK를 들이지 않는다(AI-C-04).
# --------------------------------------------------------------------------
class Ollama:
    def __init__(self, host: str, timeout_s: float = 120.0):
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s

    def generate(self, model: str, prompt: str, *, system: str | None = None,
                 images_b64: list[str] | None = None,
                 temperature: float = 0.0, seed: int = 42) -> str:
        import requests

        payload: dict[str, Any] = {
            "model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": temperature, "seed": seed},
        }
        if system:
            payload["system"] = system
        if images_b64:
            payload["images"] = images_b64
        r = requests.post(f"{self.host}/api/generate", json=payload,
                          timeout=self.timeout_s)
        r.raise_for_status()
        return r.json().get("response", "")

    def available_models(self) -> list[str]:
        import requests

        r = requests.get(f"{self.host}/api/tags", timeout=10)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]


# --------------------------------------------------------------------------
# 특징 사전
# --------------------------------------------------------------------------
class FeatureDictionary:
    """클래스 → 특징 문구. CLIP 텍스트 앵커로 쓴다.

    `class_features.json`과 같은 모양이며 `_meta`는 무시한다. 클래스별 점수는
    그 클래스 특징 문구들의 상위 `top_k` 유사도 평균이다 — 문구 하나가 우연히
    튀는 것을 완화하려는 것이고, 원 PoC의 AND 게이트(색·모양·채도)는 여기 없다.
    그 게이트들은 문(door)처럼 **알려진 클래스**에 튜닝된 값이라 미지 객체 서술에는
    쓸 수 없다. 즉 이 클래스는 PoC보다 **약한** 판정기다 — 그 대신 어떤 클래스에도
    적용된다.
    """

    def __init__(self, path: Path | None, top_k: int = 3):
        self.path = path
        self.top_k = top_k
        self.entries: dict[str, dict] = {}
        if path and path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.entries = {k: v for k, v in raw.items() if not k.startswith("_")}

    def classes(self) -> list[str]:
        return list(self.entries)

    def background_classes(self) -> set[str]:
        """사전이 스스로 선언한 배경 클래스.

        **단일 출처다.** config에 같은 목록을 두면 반드시 어긋난다 — 2026-09-21에
        사전에 배경 5개를 추가하고 config를 안 고쳐서 crop의 64%(vehicle_part/
        vehicle_group)가 객체로 취급됐고, 배경 버림이 30개에서 4개로 붕괴했다.
        """
        return {k for k, v in self.entries.items() if v.get("background")}

    def prompt_plan(self) -> tuple[list[str], dict[str, list[int]]]:
        """(전체 프롬프트 목록, 클래스 → 그 프롬프트들의 인덱스)."""
        prompts: list[str] = []
        index: dict[str, list[int]] = {}
        for cls, entry in self.entries.items():
            feats = [f for f in entry.get("features", []) if isinstance(f, str)]
            if not feats:
                feats = [cls]
            idx = []
            for f in feats:
                # CLIP은 문장형 프롬프트에서 더 안정적이다(PoC 관례).
                prompts.append(f"a photo of {cls}, {f}")
                idx.append(len(prompts) - 1)
            index[cls] = idx
        return prompts, index

    def score_row(self, sims: list[float], index: dict[str, list[int]]) -> dict[str, float]:
        out = {}
        for cls, idx in index.items():
            vals = sorted((sims[i] for i in idx), reverse=True)[: self.top_k]
            out[cls] = float(np.mean(vals)) if vals else float("-inf")
        return out

    def add(self, cls: str, entry: dict, *, provenance: dict) -> None:
        """생성 항목을 **메모리에만** 올린다. 디스크 사전은 사람 검수 뒤에 쓴다."""
        e = dict(entry)
        e["_provenance"] = provenance
        e["_verified"] = False
        self.entries[cls] = e


# --------------------------------------------------------------------------
# LLM — 사전에 없는 클래스의 항목 생성
# --------------------------------------------------------------------------
SYSTEM = ("너는 로봇 인지 파이프라인의 클래스 특징 사전을 작성한다. "
          "CLIP(clip-vit-base-patch32) 텍스트 앵커를 쓰는 실제 소비자 코드가 "
          "이 출력을 그대로 읽는다.")

SCHEMA = """\
{
  "features": ["영어 특징 문구 4~8개"],
  "min_aspect_ratio_h_over_w": 숫자 또는 null,
  "target_sim_threshold": 0.2~0.3 사이 숫자,
  "rationale": "왜 이 특징·게이트를 골랐는지 한국어 한두 문장"
}"""


class LlmFeatureGenerator:
    """`research/class_feature_llm`의 reason_json 변형을 그대로 쓴다.

    거기 하니스가 프롬프트 4종을 격자로 비교한 결과물이므로, 여기서 프롬프트를
    새로 지어내면 그 비교 결과를 버리는 셈이 된다.
    """

    def __init__(self, ollama: Ollama, model: str):
        self.ollama = ollama
        self.model = model

    def generate(self, korean: str, english: str) -> dict:
        prompt = (
            f'로봇이 새 탐색 명령 "{korean}"을 받았다. 이 클래스는 아직 특징 사전에 없다.\n'
            f'영어 클래스 키는 "{english}"다.\n\n'
            "이 클래스를 CLIP 기반 후보 게이트로 찾기 위한 특징 사전 항목을 만들어라.\n\n"
            f"## 출력 스키마\n{SCHEMA}\n\n"
            "## 출력 순서 (반드시 지킨다)\n"
            "1) \"## 판단\" 아래에서 한국어로 짧게 따져본다: 세로로 긴가 가로로 넓은가, "
            "색이 클래스 정의의 일부인가, 어떤 문구가 비특이적인가.\n"
            "2) 그 다음 \"## JSON\" 아래에 JSON 객체 하나만 코드블록으로 출력한다.\n"
            "**특징 문구는 반드시 영어로 쓴다** — CLIP이 한국어를 거의 구분하지 못한다는 "
            "실측 결과가 있다."
        )
        t0 = time.perf_counter()
        text = self.ollama.generate(self.model, prompt, system=SYSTEM)
        entry = _extract_json(text)
        return {"entry": entry, "raw": text[:4000], "model": self.model,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 1)}


def _extract_json(text: str) -> dict | None:
    """코드블록 우선, 없으면 마지막 중괄호 덩어리. 실패는 None이지 예외가 아니다."""
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    start = None
    return None


def validate_entry(entry: dict | None) -> tuple[bool, str]:
    """`research/class_feature_llm/validator.py`의 LOADABLE/USABLE 2단계를 줄인 것."""
    if not isinstance(entry, dict):
        return False, "JSON 파싱 실패"
    feats = entry.get("features")
    if not isinstance(feats, list) or not feats:
        return False, "features 없음"
    if not all(isinstance(f, str) and f.strip() for f in feats):
        return False, "features에 비문자열"
    if any(re.search(r"[가-힣]", f) for f in feats):
        return False, "features에 한국어 — CLIP이 구분 못 한다"
    thr = entry.get("target_sim_threshold")
    if thr is not None and not (isinstance(thr, (int, float)) and 0.0 < thr < 1.0):
        return False, "target_sim_threshold 범위 밖"
    ar = entry.get("min_aspect_ratio_h_over_w")
    if ar is not None and not (isinstance(ar, (int, float)) and ar > 0):
        return False, "종횡비 값 이상"
    return True, "ok"


# --------------------------------------------------------------------------
# VLM — 미지 crop 서술
# --------------------------------------------------------------------------
class VlmDescriber:
    """**현재 환경 서술**. 객체 확정이 아니다(사용자 2026-09-21).

    이전 판은 미지 crop마다 "이게 뭐냐"를 물었다. 그 쓰임에서는 RPN 후보 다수가
    오탐이라 VLM이 배경에도 그럴듯한 이름을 붙이는 문제가 있었다. 지금 역할은
    프레임 한 장을 통째로 보고 **장면이 어떤 상황인가**를 서술하는 것이며, 그래서
    객체 판정 경로(stage2)에서 분리돼 저빈도·비동기로 돈다.

    프롬프트는 도메인마다 다르다 — 하천 감시와 도시 안전은 같은 그림에서 서로 다른
    것을 봐야 한다. 그래서 프롬프트가 생성자 인자다(AI-C-15: 도메인 차이는 핵심 코드
    분기가 아니라 구성으로 표현한다).
    """

    SCENE_PROMPT = ("Describe this aerial scene in one sentence: what kind of place "
                    "is it, and what is happening?")

    def __init__(self, ollama: Ollama, model: str, scene_prompt: str | None = None):
        self.ollama = ollama
        self.model = model
        self.scene_prompt = scene_prompt or self.SCENE_PROMPT

    def describe_scene(self, jpeg_bytes: bytes) -> dict:
        """프레임 한 장의 환경 서술. 실패는 예외가 아니라 사유로 돌려준다(AI-C-05)."""
        b64 = base64.b64encode(jpeg_bytes).decode()
        try:
            t0 = time.perf_counter()
            text = self.ollama.generate(self.model, self.scene_prompt, images_b64=[b64])
            return {"text": text.strip()[:600], "model": self.model,
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                    "status": "description"}   # 확정 label이 아니다
        except Exception as exc:
            return {"error": repr(exc)[:160], "status": "unavailable"}
