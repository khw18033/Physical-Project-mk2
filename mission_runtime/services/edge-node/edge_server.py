"""엣지 노드: 단계형(staged) 판정 — 빠른 것부터 말단에 돌려준다.

implements: AI-E-01, AI-E-04, AI-S-03, AI-S-04, AI-S-06, AI-B-08, AI-B-09,
            AI-C-05, AI-C-19, AI-L-01, AI-L-02, AI-L-03, AI-O-03

**왜 단계형인가**: 이전 판은 OVD·CLIP·VLM을 모두 끝낸 뒤 응답했다. 그래서 말단이
기다리는 시간이 **모델 지연의 합**(실측 188~253 ms + 전송)이 되었고, 말단이 초당
8프레임을 내는데 엣지가 3프레임밖에 소화하지 못해 스풀이 계속 쌓였다.
이 판은 단계를 쪼갠다:

    stage1  OVD (동기, 실측 ~17 ms)      → 즉시 응답. 말단이 바로 반영한다.
    stage2  CLIP 근거화 (비동기)          → 준비되면 /api/verdicts 로 회수

프레임 처리 경로 **밖**에 명령 둘이 있다(POST /api/command):
    find_class      LLM이 특징 사전 항목을 만든다
    describe_scene  VLM이 최근 프레임의 현재 환경을 서술한다
둘 다 ollama 호출이 초 단위라 상시 실행하면 프레임 처리를 잡아먹는다.

말단은 **먼저 나온 것부터** 반영한다. 느린 근거가 빠른 근거를 막지 않는다.

**미지 후보의 세 갈래**(사용자 2026-09-21):
    background  1등이 배경 클래스이고 충분히 벌어짐 → **버린다**(crop도 저장 안 함)
    undecided   배경은 아닌데 뭔지 모름               → 저장 + 가시화로 올림
    confident   충분히 벌어짐                         → 저장 + **말단 시점 반영**

말단에 보내는 것은 confident뿐이다 — 확신하지 않는 근거로 말단 레코드를 오염시키지
않는다(AI-S-04). 저장되는 것에는 CLIP ranking 전체가 함께 남아 가시화가 "왜 이렇게
봤는지"를 보여줄 수 있다(AI-L-03).

**경계(AI-C-19)**: 여기서 나오는 것은 전부 근거와 가설이다. 물리 명령을 만들지
않고, 미지 crop을 학습 정답으로 승격하지 않는다(AI-L-02).

**저장소**(`store/`, AI-O-03):
    frames/<frame_id>.jpg        말단에서 받은 원본 (미디어 평면)
    meta/<frame_id>.json         말단에서 받은 RPN 후보 (업무 평면)
    records/<frame_id>.json      엣지 판정 결과(stage1 + 확정 후 갱신)
    overlay/<frame_id>.jpg       OVD(초록)/미지(빨강) 시각화
    unknown_crops/<frame_id>_uNNN.jpg  + <...>.json (추론 결과와 근거)
    scene/<frame_id>.json        VLM 환경 서술
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from common import expand_box, iou, load_config, resolve
from consensus import concept_key, merge_by_consensus
from object_tracks import ObjectTracks
from postprocess import absorb, merge_overlapping
from retention import CropGate, Rotation
from semantic import (FeatureDictionary, LlmFeatureGenerator, Ollama,
                      VlmDescriber, validate_entry)

STATE: dict = {}


def embed_tensor(out):
    """transformers `get_*_features` 반환에서 임베딩 텐서를 꺼낸다.

    4.x는 텐서를, 5.x는 `ModelOutput`을 돌려준다. 버전 차이를 여기 한 곳에서
    흡수한다 — 2026-09-21에 이 차이로 stage2가 매 프레임 실패했는데, 예외가
    비동기 워커 안에서만 나서 stage1은 멀쩡해 보였다. `pooler_output`은
    projection까지 적용된 512차원이라 그대로 쓸 수 있다.

    클래스 메서드가 아니라 모듈 함수인 이유: 같은 이름의 메서드를 두 scorer
    클래스에 각각 두면 한쪽만 고치는 실수가 나기 쉽다(실제로 한 번 냈다).
    """
    import torch

    if torch.is_tensor(out):
        return out
    for attr in ("image_embeds", "text_embeds", "pooler_output"):
        v = getattr(out, attr, None)
        if v is not None:
            return v
    raise TypeError(f"임베딩을 못 찾았다: {type(out).__name__}")



# --------------------------------------------------------------------------
# stage1 — OVD. YOLOE prompt-free 한 종만 쓴다.
# --------------------------------------------------------------------------
class YoloeOvd:
    """YOLOE prompt-free — 텍스트 프롬프트 없이 **내장 어휘 4585종**으로 검출한다.

    2026-09-21 확인(`yoloe-11s-seg-pf.pt`, ultralytics 8.4.146): `-pf` 가중치는
    prompt-free(PE-Free)라 `set_classes` 없이 그대로 predict된다. 어휘가 넓을수록
    '흔한 물체'가 OVD 쪽으로 흡수되어 미지 집합에 진짜 미지만 남는다.
    실측 비교(같은 10장): YOLOE 17.1 ms / 4585종 vs YOLO-World 12.0 ms / 87종.
    5 ms 손해를 어휘 53배와 바꾼 것이고, 어휘 설계를 사람이 하지 않아도 된다.
    """

    def __init__(self, cfg: dict):
        c = cfg["ovd"]
        self._cfg = cfg
        self.conf = float(c.get("conf", 0.10))
        self.iou = float(c.get("iou", 0.5))
        self.imgsz = int(c.get("imgsz", 640))
        self.mode = "prompt_free"
        self.model = None
        self._names: dict = {}
        self.vocab: list[str] = []
        # 시작부터 도메인 어휘로 연다 — prompt-free로 한 번 열었다 다시 여는 것은
        # 가중치를 두 번 읽는 낭비다.
        # **이 모델은 언제나 prompt-free다.** 도메인 어휘는 두 번째 모델(WorldOvd)이
        # 맡고, 확정은 둘의 합의로 정한다(consensus.py). 한쪽이라도 도메인에
        # 묶이면 "어휘 설계 없이 새 현장에 투입한다"는 요구가 깨진다(AI-C-15).
        self.set_vocabulary(None)

    def set_vocabulary(self, words) -> None:
        """어휘를 갈아 끼운다. None이면 prompt-free, 목록이면 텍스트 프롬프트.

        **왜 필요한가**(2026-09-21 실측): prompt-free 4585종은 실내 장면에서 모니터를
        `computer chair`, 벽면을 `press room`, 빈 곳을 `speaker`/`hassock`으로 불렀다.
        어휘가 넓으면 미지 집합이 깨끗해지는 대신, 화면에 올라오는 이름 자체를 믿을 수
        없게 된다 — 4585개 중 하나를 고르는 문제라 아무것이나 그럴듯하게 맞는다.

        텍스트 프롬프트 모드는 후보를 사람이 정한 몇십 개로 좁힌다. 어느 쪽이 나은지는
        배치마다 다르므로 **코드가 아니라 설정에서** 고른다(AI-C-15: 도메인 차이는
        분기문이 아니라 배포 프로파일). 어휘가 바뀌면 재측정 대상이다(AI-B-01).
        """
        from ultralytics import YOLOE  # 지연 import (AI-C-11)

        c = self._cfg["ovd"]
        if words:
            path = resolve(self._cfg, c.get("text_weights", c["weights"]))
            self.model = YOLOE(str(path))
            self.model.set_classes(list(words), self.model.get_text_pe(list(words)))
            self._names = {i: w for i, w in enumerate(words)}
            self.vocab = list(words)
            self.mode = "text_prompt"
        else:
            self.model = YOLOE(str(resolve(self._cfg, c["weights"])))
            names = getattr(self.model.model, "names", {}) or {}
            self._names = names
            self.vocab = [names[i] for i in sorted(names)] if names else []
            self.mode = "prompt_free"

    def detect(self, bgr) -> list[dict]:
        res = self.model.predict(bgr, conf=self.conf, iou=self.iou,
                                 imgsz=self.imgsz, verbose=False)[0]
        out = []
        if res.boxes is None:
            return out
        for b in res.boxes:
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
            out.append({"box": [x1, y1, x2, y2],
                        "label": self._names.get(int(b.cls[0]), str(int(b.cls[0]))),
                        "conf": float(b.conf[0])})
        return out


class WorldOvd:
    """YOLO-World 텍스트 프롬프트 — 현장 어휘로 좁혀 보는 두 번째 눈.

    **동기 경로에 둘 수 있다**(2026-09-21 실측, 같은 프레임·RTX 3060):
        YOLOE prompt-free 4585종  15 ms
        YOLO-World 텍스트 20종    16 ms
        Grounding DINO tiny       453 ms (autocast fp16 299 ms)
    GDINO는 라벨 품질과 무관하게 이 예산에 들어오지 못한다 — 말단 왕복이 이미
    ~0.5 s인데 여기에 0.3~0.45 s를 더하면 시점 반영의 의미가 없어진다.

    어휘는 설정이다(`ovd2.vocabularies[<domain>]`). 코드에 클래스 이름을 박으면
    도메인이 늘 때마다 핵심 코드가 바뀐다(AI-C-15).
    """

    def __init__(self, cfg: dict):
        self._cfg = cfg
        c = cfg.get("ovd2", {})
        self.conf = float(c.get("conf", 0.05))
        self.iou = float(c.get("iou", 0.5))
        self.imgsz = int(c.get("imgsz", 640))
        self.model = None
        self.vocab: list[str] = []
        self.set_vocabulary(
            (c.get("vocabularies") or {}).get(cfg["clip"].get("active_domain", "")))

    def set_vocabulary(self, words) -> None:
        from ultralytics import YOLOWorld  # 지연 import (AI-C-04)

        words = list(words or [])
        self.vocab = words
        if not words:
            self.model = None      # 어휘가 없으면 이 눈은 쉰다(선택 기능, AI-C-05)
            return
        self.model = YOLOWorld(str(resolve(self._cfg, self._cfg["ovd2"]["weights"])))
        self.model.set_classes(words)

    def detect(self, bgr) -> list[dict]:
        if self.model is None:
            return []
        res = self.model.predict(bgr, conf=self.conf, iou=self.iou,
                                 imgsz=self.imgsz, verbose=False)[0]
        if res.boxes is None:
            return []
        names = res.names
        return [{"box": [float(v) for v in b.xyxy[0].tolist()],
                 "label": names[int(b.cls[0])], "conf": float(b.conf[0])}
                for b in res.boxes]


# --------------------------------------------------------------------------
# CLIP — quantized ONNX 두 타워. 텍스트 임베딩은 프롬프트가 바뀔 때만 다시 만든다.
# --------------------------------------------------------------------------
class ClipScorer:
    def __init__(self, cfg: dict):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        c = cfg["clip"]
        self.size = int(c.get("input_size", 224))
        # 실행 provider를 코드에 고정하지 않는다(AI-B-08). 설정이 요구한 것 중 이 호스트가
        # 실제로 가진 것만 쓰고, 없으면 CPU로 내려간다 — 가속기 부재는 실패가 아니다(AI-C-05).
        want = list(c.get("providers", ["CUDAExecutionProvider", "CPUExecutionProvider"]))
        have = set(ort.get_available_providers())
        self.providers = [p for p in want if p in have] or ["CPUExecutionProvider"]
        self.vision = ort.InferenceSession(str(resolve(cfg, c["vision_onnx"])),
                                           providers=self.providers)
        self.text = ort.InferenceSession(str(resolve(cfg, c["text_onnx"])),
                                         providers=self.providers)
        self.tok = AutoTokenizer.from_pretrained(str(resolve(cfg, c["tokenizer_dir"])))
        self.prompts: list[str] = []
        self.text_emb: np.ndarray | None = None
        self._vis_in = self.vision.get_inputs()[0].name
        # CLIP 전처리 상수(OpenAI) — ImageNet 상수와 다르다. 섞으면 점수가 망가진다.
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)

    @staticmethod
    def _l2(a: np.ndarray) -> np.ndarray:
        return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)

    def set_prompts(self, prompts: list[str]) -> None:
        if prompts == self.prompts and self.text_emb is not None:
            return
        enc = self.tok(prompts, padding="max_length", max_length=77,
                       truncation=True, return_tensors="np")
        feed = {i.name: enc[i.name].astype(np.int64)
                for i in self.text.get_inputs() if i.name in enc}
        self.text_emb = self._l2(np.asarray(self.text.run(None, feed)[0], np.float32))
        self.prompts = list(prompts)

    def score(self, crops: list[np.ndarray], batch_size: int = 16) -> list[list[float]]:
        """crop들을 배치로 인코딩한다.

        **정정(2026-09-21)**: 배치를 지연 대책으로 넣었으나 효과가 없었다(900→950 ms).
        이전 판이 이미 전체를 한 번에 넣고 있었으므로 쪼갠 것이 오히려 호출을 늘렸다.
        900 ms는 quantized ViT-B/32로 crop 60개를 도는 고유 비용이고, 실제 대책은
        실행 provider(CUDA)다. batch_size는 메모리 상한 용도로만 남긴다.
        """
        if not crops or self.text_emb is None:
            return []
        prep = []
        for c in crops:
            r = cv2.resize(c, (self.size, self.size))
            x = cv2.cvtColor(r, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            prep.append(((x - self.mean) / self.std).transpose(2, 0, 1))
        embs = []
        for i in range(0, len(prep), max(1, batch_size)):
            chunk = np.ascontiguousarray(np.stack(prep[i:i + batch_size]))
            embs.append(np.asarray(self.vision.run(None, {self._vis_in: chunk})[0],
                                   np.float32))
        return (self._l2(np.concatenate(embs)) @ self.text_emb.T).tolist()


class TorchClipScorer:
    """torch CUDA fp16 CLIP. 2026-09-21 벤치의 승자다(`bench_clip.py`).

    crop 60장 기준 실측:

        int8 ONNX  CPU   823.4 ms   13.72 ms/crop   (이전 기본값)
        int8 ONNX  CUDA  969.2 ms   16.15 ms/crop   ← GPU가 **더 느리다**
        fp32 ONNX  CUDA   80.6 ms    1.34 ms/crop
        torch      fp16   34.6 ms    0.58 ms/crop   ← 기준선 대비 **24배**
        MobileCLIP2-S0 fp16  96.3 ms  1.61 ms/crop
        MobileCLIP-S1  fp16 165.6 ms  2.76 ms/crop

    두 가지가 드러났다. (1) **quantized 그래프는 GPU로 갈 수 없다** — CUDA EP에 해당
    연산이 없어 memcpy 노드가 끼고 CPU↔GPU를 오간다. 그래서 양자화는 CPU 전용 최적화다.
    (2) **작은 모델이 GPU에서 빠른 것이 아니다** — MobileCLIP2-S0는 파라미터가 7.7배
    적은데 2.8배 느리다. 지연을 정하는 것은 파라미터 수가 아니라 연산 깊이와 커널이다.

    **두 타워를 같은 체크포인트에서 쓴다.** 이미지 타워만 바꾸고 텍스트 임베딩을 예전
    int8 것으로 두면 두 벡터가 서로 다른 공간에 있어 유사도가 무의미해진다.

    **주의(AI-B-01)**: fp16 점수는 int8 점수와 척도가 다르다(같은 crop에서 코사인
    0.879). `background_margin`·`confident_margin`은 int8 분포에서 잡은 값이므로
    백엔드를 바꾸면 재확인 대상이다.
    """

    def __init__(self, cfg: dict):
        import torch
        from transformers import CLIPModel, CLIPTokenizerFast

        c = cfg["clip"]
        name = c.get("torch_model", "openai/clip-vit-base-patch32")
        want = c.get("device", "cuda")
        self.device = want if (want != "cuda" or torch.cuda.is_available()) else "cpu"
        # 가속기 부재는 실패가 아니다 — CPU로 내려가고 그 사실이 로그에 남는다(AI-C-05).
        self.half = bool(c.get("fp16", True)) and self.device == "cuda"
        self.torch = torch
        self.model = CLIPModel.from_pretrained(name).to(self.device).eval()
        if self.half:
            self.model = self.model.half()
        self.tok = CLIPTokenizerFast.from_pretrained(name)
        self.size = int(c.get("input_size", 224))
        self.prompts: list[str] = []
        self.text_emb = None
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
        self.providers = [f"torch/{self.device}{'/fp16' if self.half else '/fp32'}"]

    def set_prompts(self, prompts: list[str]) -> None:
        if prompts == self.prompts and self.text_emb is not None:
            return
        enc = self.tok(prompts, padding=True, truncation=True, max_length=77,
                       return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            t = embed_tensor(self.model.get_text_features(**enc)).float()
        self.text_emb = t / (t.norm(dim=-1, keepdim=True) + 1e-9)
        self.prompts = list(prompts)

    def score(self, crops: list[np.ndarray], batch_size: int = 64) -> list[list[float]]:
        if not crops or self.text_emb is None:
            return []
        prep = []
        for c in crops:
            r = cv2.resize(c, (self.size, self.size))
            x = cv2.cvtColor(r, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            prep.append(((x - self.mean) / self.std).transpose(2, 0, 1))
        embs = []
        for i in range(0, len(prep), max(1, batch_size)):
            x = self.torch.from_numpy(np.ascontiguousarray(
                np.stack(prep[i:i + batch_size]))).to(self.device)
            if self.half:
                x = x.half()
            with self.torch.inference_mode():
                f = embed_tensor(
                    self.model.get_image_features(pixel_values=x)).float()
            embs.append(f / (f.norm(dim=-1, keepdim=True) + 1e-9))
        return (self.torch.cat(embs) @ self.text_emb.T).cpu().numpy().tolist()


LIVE: dict[int, dict] = {}      # camera_id → {"jpeg": bytes, "at": float, "info": dict}
LIVE_LOCK = threading.Lock()
# **비교용 기준선.** RPN·ByteTrack·합의·객체 레코드를 전부 빼고 YOLOE 결과만 그린
# 스트림이다. 프레임워크가 얹은 것들이 실제로 무엇을 바꾸는지 보려면, 아무것도
# 얹지 않은 출력이 같은 화면에 있어야 한다(사용자 2026-09-21).
RAW: dict[int, dict] = {}


def live_overlay(bgr, meta: dict, rec: dict | None, unknown=None, staged: int = 2):
    """**엣지가 추적 중인 지속 객체**를 현재 프레임 위에 그린다.

    그리는 것은 두 층이다.

    1. **객체**(`rec["objects"]`) — OVD 검출을 엣지가 직접 추적해 만든 지속 객체다
       (object_tracks.py). 기하는 OVD 것이고 정체성은 검출 자신의 궤적에서 온다.
       RPN 후보에서 정체성을 빌리지 않는 이유는 후보 구성이 매 프레임 바뀌어
       근거가 흩어지기 때문이다 — 정지 장면에서 확정 집합이 프레임당 0.3~0.70개씩
       들고났다(2026-09-21 실측). RPN 기하는 **객체로 그리지 않는다**: class-agnostic
       후보라 경계가 엉뚱한 곳을 포함하거나 일부만 덮는다.

    2. **시점 반영 검증선**(`meta["tracks"]`) — 말단이 늦게 온 근거를 현재 트랙에
       붙였다는 증거다. 관측 당시 박스에서 현재 박스로 선을 긋는다. 이것이
       말단 RPN+ByteTracker를 두는 이유 자체이므로 화면에 남긴다.

        진초록  두 OVD 모델이 **누적 합의**한 확정 객체 (또렷하게)
        노랑    아직 확정 아님 — 한 모델만 말했거나 합의 횟수가 모자람 (흐린 층)

    확정은 한 프레임의 일치가 아니라 창 안의 누적이며, 오를 때와 내릴 때 조건이
    달라(이력) 경계에서 뒤집히지 않는다(AI-S-03, AI-S-06).
    """
    GREEN, YELLOW, GREY = (0, 200, 0), (0, 215, 255), (150, 150, 150)
    out = bgr.copy()
    faint = out.copy()
    n = {"confirmed": 0, "pending": 0}
    moved = []
    later: list = []
    taken: list = []
    hidden = 0

    def label(txt, x, y, color, scale=0.62, th=2, canvas=None):
        c = out if canvas is None else canvas
        cv2.putText(c, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), th + 2)
        cv2.putText(c, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, th)

    objects = list((rec or {}).get("objects") or [])
    objects.sort(key=lambda o: (-int(o.get("confirmed", False)), -o.get("conf", 0.0)))

    for o in objects:
        x1, y1, x2, y2 = (int(v) for v in o["box"])
        ok = bool(o.get("confirmed"))
        color = GREEN if ok else YELLOW
        n["confirmed" if ok else "pending"] += 1

        alt = o.get("alt") or {}
        if ok and alt:
            txt = (f"{o['label']} {o.get('conf', 0):.2f}"
                   f" = {alt.get('label', '?')} {alt.get('conf', 0):.2f}")
        else:
            txt = f"{o['label']} {o.get('conf', 0):.2f}?"
        txt += (f" [{o.get('groups', 0)}그룹 r{o.get('revision', 0)}]"
                f" {o.get('lifecycle', '?')} {o.get('seen_obs', 0)}관측")

        if ok:
            later.append((cv2.rectangle, ((x1, y1), (x2, y2), color, 2)))
        else:
            cv2.rectangle(faint, (x1, y1), (x2, y2), color, 2)

        lx, ly = x1, max(70, y1 - 7)
        (w, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.62, 2)
        if any(abs(ly - py) < th + 6 and lx < px + pw and px < lx + w
               for px, py, pw in taken):
            hidden += 1
        else:
            taken.append((lx, ly, w))
            if ok:
                later.append(("label", (txt, lx, ly, color)))
            else:
                label(txt, lx, ly, color, canvas=faint)

    # 시점 반영 검증선 — 말단이 정체성으로 근거를 붙였다는 증거(흐린 층).
    for t in meta.get("tracks", []):
        ev = t.get("ovd") or t.get("clip")
        if not ev or not ev.get("observed_box") or ev.get("moved_px", 0) < 2:
            continue
        ox1, oy1, ox2, oy2 = (int(v) for v in ev["observed_box"])
        tb = t["box"]
        cv2.line(faint, ((ox1 + ox2) // 2, (oy1 + oy2) // 2),
                 (int((tb[0] + tb[2]) / 2), int((tb[1] + tb[3]) / 2)),
                 GREY, 1, cv2.LINE_AA)
        moved.append(ev["moved_px"])

    a = float((STATE.get("cfg", {}).get("stream", {}) or {}).get("faint_alpha", 0.28))
    cv2.addWeighted(faint, a, out, 1.0 - a, 0.0, dst=out)
    for fn, args in later:
        if fn == "label":
            label(*args)
        else:
            fn(out, *args)

    head = (f"cam{meta.get('camera_id', 0)}  seq {meta.get('frame_seq', 0)}  "
            f"객체 {len(objects)}  RPN {len(meta.get('candidates', []))}")
    sub = (f"확정(두 모델 합의) {n['confirmed']}  미확정 {n['pending']}"
           + (f"   시점반영 {len(moved)}건 평균 {sum(moved)/len(moved):.0f}px"
              if moved else "   (트랙 이동 없음)")
           + (f"   라벨생략 {hidden}" if hidden else ""))
    label(head, 10, 30, (255, 255, 255), 0.8, 2)
    label(sub, 10, 58, (255, 255, 255), 0.68, 2)
    return out


def raw_overlay(bgr, dets, meta: dict, ms: float):
    """**YOLOE 결과만** 그린다 — 기준선.

    여기에는 RPN도, ByteTracker도, 두 모델 합의도, 지속 객체 레코드도 없다.
    드론이 보낸 프레임을 그대로 추론해 그 프레임 위에 그린 것이다. 그래서

      * 정체성이 없다 — 같은 물체라도 프레임마다 새 박스일 뿐이다.
      * 시점 보정이 없다 — 이 결과가 말단에 닿을 때 시야는 이미 움직여 있다.
      * 확정/잠정 구분이 없다 — conf 하나뿐이다.

    이 세 가지가 없을 때 화면이 어떻게 보이는지가 나머지 기계의 존재 이유를
    판단할 근거다.
    """
    out = bgr.copy()
    for d in sorted(dets, key=lambda x: -x["conf"]):
        x1, y1, x2, y2 = (int(v) for v in d["box"])
        c = (0, 200, 0) if d["conf"] >= 0.35 else (0, 215, 255)
        cv2.rectangle(out, (x1, y1), (x2, y2), c, 2)
        t = f"{d['label']} {d['conf']:.2f}"
        y = max(20, y1 - 6)
        cv2.putText(out, t, (x1, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(out, t, (x1, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)
    head = (f"[기준선] YOLOE prompt-free만  cam{meta.get('camera_id', 0)}  "
            f"seq {meta.get('frame_seq', 0)}  검출 {len(dets)}  {ms:.0f}ms")
    sub = "RPN 없음 · ByteTrack 없음 · 합의 없음 · 객체 레코드 없음 · 시점 보정 없음"
    for txt, yy, sc in ((head, 30, 0.8), (sub, 58, 0.62)):
        cv2.putText(out, txt, (10, yy), cv2.FONT_HERSHEY_SIMPLEX, sc, (0, 0, 0), 4)
        cv2.putText(out, txt, (10, yy), cv2.FONT_HERSHEY_SIMPLEX, sc, (255, 255, 255), 2)
    return out


def publish_raw(cfg: dict, meta: dict, bgr, dets, ms: float) -> None:
    cam = int(meta.get("camera_id", 0))
    q = int(cfg.get("stream", {}).get("jpeg_quality", 70))
    ok, enc = cv2.imencode(".jpg", raw_overlay(bgr, dets, meta, ms),
                           [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        return
    with LIVE_LOCK:
        RAW[cam] = {"jpeg": enc.tobytes(), "at": time.time(),
                    "n": len(dets), "ms": round(ms, 1),
                    "seq": meta.get("frame_seq"),
                    # 기준선의 프레임 간 안정성을 파이프라인과 **같은 기준**으로
                    # 재려면 라벨과 박스가 필요하다. 정체성이 없으므로 집합으로만
                    # 비교할 수 있다 — 그 사실 자체가 비교의 요점이다.
                    "dets": [{"label": d["label"], "conf": round(d["conf"], 3),
                              "box": [round(v, 1) for v in d["box"]]}
                             for d in dets]}


def compose_compare(cam: int):
    """기준선과 파이프라인을 **같은 순간**으로 위아래에 붙인다.

    둘은 같은 stage1 호출에서 발행되므로 보통 같은 frame_seq다. 그러나 stage2가
    파이프라인 쪽만 다시 발행할 수 있어 어긋날 수 있으므로, 각 패널에 seq를 적어
    **어긋났는지 눈으로 확인할 수 있게** 한다 — 같은 프레임이라고 가정하지 않는다.
    """
    with LIVE_LOCK:
        a = RAW.get(cam)
        b = LIVE.get(cam)
    if not a or not b:
        return None
    top = cv2.imdecode(np.frombuffer(a["jpeg"], np.uint8), cv2.IMREAD_COLOR)
    bot = cv2.imdecode(np.frombuffer(b["jpeg"], np.uint8), cv2.IMREAD_COLOR)
    if top is None or bot is None:
        return None
    if top.shape[1] != bot.shape[1]:
        bot = cv2.resize(bot, (top.shape[1], int(bot.shape[0] * top.shape[1]
                                                 / bot.shape[1])))
    bar = 46
    w = top.shape[1]
    out = np.zeros((top.shape[0] + bot.shape[0] + bar * 2, w, 3), np.uint8)

    def caption(y, text, color):
        cv2.rectangle(out, (0, y), (w, y + bar), (24, 24, 24), -1)
        cv2.putText(out, text, (14, y + 31), cv2.FONT_HERSHEY_SIMPLEX, 0.72,
                    color, 2)

    caption(0, f"A. YOLOE prompt-free only  -  no RPN / no ByteTrack / no reflection"
               f"   [seq {a.get('seq')}  det {a.get('n')}  {a.get('ms')}ms]",
            (200, 200, 255))
    out[bar:bar + top.shape[0]] = top
    y2 = bar + top.shape[0]
    n_obj = len(b.get("objects") or [])
    n_conf = sum(1 for o in (b.get("objects") or []) if o.get("confirmed"))
    caption(y2, f"B. + RPN + ByteTrack + 2-model consensus + object record"
                f"   [seq {b['info'].get('seq')}  obj {n_obj}  confirmed {n_conf}]",
            (200, 255, 200))
    out[y2 + bar:y2 + bar + bot.shape[0]] = bot
    return out


def publish_live(cfg: dict, meta: dict, bgr, rec: dict | None,
                 unknown=None, staged: int = 1) -> None:
    cam = int(meta.get("camera_id", 0))
    q = int(cfg.get("stream", {}).get("jpeg_quality", 70))
    scale = float(cfg.get("stream", {}).get("scale", 1.0))
    img = live_overlay(bgr, meta, rec, unknown, staged)
    if scale != 1.0:
        img = cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)))
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        return
    with LIVE_LOCK:
        LIVE[cam] = {"jpeg": enc.tobytes(), "at": time.time(),
                     # 말단이 보낸 트랙 원본. 시점 반영을 **눈이 아니라 수치로**
                     # 검증하려면 화면에 그린 값이 아니라 이 원본이 필요하다.
                     "tracks": meta.get("tracks", []),
                     # 엣지가 추적 중인 지속 객체 — 확정 집합의 안정성을 수치로
                     # 확인하려면 화면이 아니라 이 목록을 봐야 한다.
                     "objects": list((rec or {}).get("objects") or []),
                     "object_stats": dict((rec or {}).get("object_stats") or {}),
                     "info": {"rpn": len(meta.get("candidates", [])),
                              "ovd": (rec or {}).get("ovd_count", 0),
                              "seq": meta.get("frame_seq"), "stage": staged}}


def apply_domain(cfg: dict, domain: str) -> dict:
    """도메인 사전과 배경 클래스를 갈아 끼운다.

    사전과 배경 클래스는 **한 쌍**이다. 하천의 water_surface와 도시의 road_surface는
    같은 역할(배경 흡수)을 하지만 이름이 다르므로 따로 옮기면 배경 판정이 깨진다.
    그래서 domains[<key>]가 둘을 같이 들고 있다.

    텍스트 임베딩 캐시를 비우는 것이 중요하다 — 사전이 바뀌면 프롬프트 집합이
    바뀌는데 캐시를 그대로 두면 이전 도메인의 앵커로 계속 점수를 매긴다.
    """
    spec = cfg["clip"].get("domains", {}).get(domain)
    if not spec:
        raise KeyError(f"모르는 도메인: {domain} "
                       f"(가능: {list(cfg['clip'].get('domains', {}))})")
    fd = FeatureDictionary(resolve(cfg, spec["dictionary"]),
                           int(cfg["clip"].get("dictionary_top_k", 3)))
    STATE["dict"] = fd
    # 배경 목록은 **사전이 선언한다**. config에 두면 사전을 고칠 때 어긋난다
    # (2026-09-21에 실제로 어긋났다 — semantic.FeatureDictionary.background_classes 참고).
    STATE["background_classes"] = fd.background_classes()
    STATE["active_domain"] = domain
    cfg["clip"]["active_domain"] = domain
    # OVD 어휘도 도메인을 따라간다. 사전과 어휘는 같은 도메인의 두 면이고, 따로
    # 옮기면 CLIP은 하천을 보는데 OVD는 도시를 보는 상태가 된다(AI-C-15).
    if STATE.get("ovd2") is not None:
        words = (cfg.get("ovd2", {}).get("vocabularies") or {}).get(domain) or []
        if list(words) != list(STATE["ovd2"].vocab):
            STATE["ovd2"].set_vocabulary(words)
    if STATE.get("clip") is not None:
        STATE["clip"].prompts = []          # 앵커 재생성 강제
        STATE["clip"].text_emb = None
    STATE.pop("clip_cache", None)            # 이전 도메인 판정 재사용 금지

    # VLM 장면 프롬프트도 같은 도메인으로 옮긴다. 두 키(clip.active_domain /
    # vlm.active_domain)가 따로 놀면 사전은 도시인데 장면 서술은 하천을 묻는
    # 상태가 된다 — 2026-09-21에 실제로 그렇게 떠 있었다.
    cfg.setdefault("vlm", {})["active_domain"] = domain
    if STATE.get("vlm") is not None:
        sp = cfg["vlm"].get("scene_prompts", {}).get(domain)
        if sp:
            STATE["vlm"].scene_prompt = sp

    return {"domain": domain, "dictionary": spec["dictionary"],
            "classes": fd.classes(),
            "background_classes": sorted(STATE["background_classes"])}


# --------------------------------------------------------------------------
# 판정 버퍼 — 비동기 결과를 말단이 /api/verdicts 로 회수한다
# --------------------------------------------------------------------------
class VerdictBuffer:
    """단조 증가 커서로 읽는 링 버퍼. 말단은 마지막으로 받은 cursor만 기억하면 된다."""

    def __init__(self, maxlen: int):
        self._items: deque = deque(maxlen=maxlen)
        self._next = 1
        self._lock = threading.Lock()

    def put(self, verdict: dict) -> int:
        with self._lock:
            cur = self._next
            self._next += 1
            verdict["cursor"] = cur
            self._items.append(verdict)
            return cur

    def since(self, cursor: int, limit: int = 50) -> tuple[list[dict], int]:
        with self._lock:
            out = [v for v in self._items if v["cursor"] > cursor][:limit]
            return out, (out[-1]["cursor"] if out else cursor)


# --------------------------------------------------------------------------
# stage1: OVD → 즉시 응답
# --------------------------------------------------------------------------
def stage1(cfg: dict, meta: dict, bgr) -> dict:
    t0 = time.perf_counter()
    h, w = bgr.shape[:2]
    rpn_items = meta.get("candidates", [])
    skipped: list[str] = []

    ovd_dets, ovd_ms = [], 0.0
    if STATE.get("ovd") is not None:
        t = time.perf_counter()
        ovd_dets = STATE["ovd"].detect(bgr)
        ovd_ms = (time.perf_counter() - t) * 1000.0
    elif cfg["ovd"].get("enabled", True):
        skipped.append(f"ovd_unavailable:{STATE.get('ovd_error','?')}")

    # 두 번째 눈 — 현장 어휘로 좁혀 본다. 없으면 이 단계만 빠진다(AI-C-05).
    ovd2_dets, ovd2_ms = [], 0.0
    if STATE.get("ovd2") is not None:
        t = time.perf_counter()
        ovd2_dets = STATE["ovd2"].detect(bgr)
        ovd2_ms = (time.perf_counter() - t) * 1000.0

    # **확정은 합의로 정한다**(consensus.py). 단일 모델의 conf는 그 모델의 확신일
    # 뿐 근거 충분도가 아니다(AI-S-03). 실측에서 YOLOE는 0.94/0.87처럼 **높은
    # conf로** 틀렸으므로 임계를 올려서는 그 오답을 거를 수 없었다.
    # verdict를 **흡수보다 먼저** 매긴다 — absorb가 확신 검출만 흡수하기 때문이다.
    # 기준선 스트림 — 아무것도 얹지 않은 YOLOE 결과를 따로 내보낸다.
    if cfg.get("stream", {}).get("raw_baseline", True):
        publish_raw(cfg, meta, bgr, ovd_dets, ovd_ms)

    # 합치기 **전** 목록을 남긴다 — 근거는 모델별로 따로 트랙에 붙여야 하고,
    # 합친 목록에서는 어느 모델이 말했는지가 한 항목에 뭉개진다.
    pf_dets = list(ovd_dets)
    if ovd2_dets:
        ovd_dets, consensus_stats = merge_by_consensus(ovd_dets, ovd2_dets,
                                                       {**cfg.get("ovd2", {})})
    else:
        # 두 번째 눈이 없으면 예전 규칙(단일 conf 임계)으로 물러난다. 축소지
        # 실패가 아니다 — 다만 확정의 근거가 약해졌다는 사실은 남긴다.
        cconf = float(cfg["ovd"].get("confident_conf", 0.35))
        for det in ovd_dets:
            det["verdict"] = "confident" if det["conf"] >= cconf else "tentative"
            det["sources"] = ["prompt_free"]
        consensus_stats = {"degraded": "single_model"}
    ovd_counts = {"confident": sum(1 for d in ovd_dets if d["verdict"] == "confident"),
                  "tentative": sum(1 for d in ovd_dets if d["verdict"] == "tentative")}

    # **표시 대상의 정체성은 검출을 직접 추적해 만든다**(object_tracks.py).
    # RPN 후보에서 빌려 오면 후보 구성이 매 프레임 바뀌어 근거가 흩어진다.
    for d in ovd_dets:
        d.setdefault("concept", concept_key(d["label"],
                                            cfg.get("ovd2", {}).get("synonyms") or {}))
    cam_key = int(meta.get("camera_id", 0))
    ot = STATE.setdefault("obj_tracks", {}).get(cam_key)
    if ot is None:
        ot = STATE["obj_tracks"][cam_key] = ObjectTracks(cfg)
    now_t = time.time()
    objects = [o.to_dict() for o in ot.update(ovd_dets, now_t)]

    # 후처리 — IoU만 보면 조각과 병합 박스가 미지로 샌다(postprocess.py 참고).
    u = dict(cfg["unknown"])
    u["_frame_area"] = float(w * h)      # 흡수 자격 판정에 프레임 면적이 필요하다
    known, unknown, absorb_stats = absorb(rpn_items, ovd_dets, u)
    unknown = [d for d in unknown
               if min(d["box"][2] - d["box"][0], d["box"][3] - d["box"][1])
               >= float(u.get("min_short_side_px", 8))]
    unknown, merged_away = merge_overlapping(
        unknown, float(u.get("merge_unknown_iou", 0.0)))
    absorb_stats["merged_away"] = merged_away
    absorb_stats["after_filters"] = len(unknown)
    unknown = unknown[: int(u.get("max_per_frame", 60))]

    # 말단이 **좌표가 아니라 정체성**으로 붙일 수 있게 track_id별로 묶는다.
    # 말단 레코드에 올리는 것은 OVD 확신뿐이다 — 잠정 OVD도 CLIP도 "배경이 아닌데
    # 모르는 것"이라 확정 근거가 못 된다(사용자 2026-09-21).
    # **검출 하나는 트랙 하나에만 붙는다.** RPN 후보가 촘촘히 겹치므로 같은 검출에
    # match_iou를 넘는 후보가 수십 개 나온다. 전부에 붙이면 검출 1건이 객체 N건으로
    # 불어난다 — 2026-09-21 실측에서 "computer chair 0.76"이 118개 트랙에 동시에
    # 붙어 화면을 덮었다. 검출은 객체 하나를 가리키므로 IoU가 가장 큰 트랙 하나가
    # 가져가고, 나머지 후보는 known으로 남아(= CLIP에 다시 보내지 않되) 라벨을 갖지
    # 않는다. 그 후보들은 이미 설명된 객체의 파편이다.
    # **근거는 두 모델이 각각, 매 프레임 보낸다.** 예전에는 "이번 프레임에 두 모델이
    # 동시에 검출하고 그 합의 박스에 RPN 후보가 붙는" 우연의 일치가 있을 때만
    # 근거를 보냈다. 실측에서 그 우연은 검출 50건 중 8건뿐이라, 한 번 받은 근거가
    # TTL 6초를 버티다 만료되면 다음 우연까지 화면이 비었다 — 정지 장면에서
    # 프레임당 1.37건이 그렇게 깜빡였다(2026-09-21 실측: 소실된 근거의 age가 5.98s).
    #
    # 이제 각 모델의 검출을 따로 트랙에 붙인다. 확정 여부는 여기서 정하지 않고,
    # 말단이 **누적된 두 근거**로 판정한다(records.transmit_view). 한 프레임에서
    # 한쪽이 빠져도 다른 근거가 창 안에 남아 있으므로 확정이 끊기지 않는다.
    # AI-S-06이 요구하는 것이 프레임 단위 판정이 아니라 지속 객체에의 누적이다.
    syn = cfg.get("ovd2", {}).get("synonyms") or {}
    sticky = float(cfg["ovd"].get("sticky_label_bonus", 0.10))
    m_iou = float(cfg["unknown"].get("match_iou", 0.3))
    # 말단이 이미 들고 있는 개념. **원 라벨이 아니라 개념 키로 비교한다** — 같은
    # 물체를 두 프레임에 걸쳐 `chair`/`computer chair`로 달리 불러도 연속성은
    # 유지되어야 한다.
    held = {}
    for t in (meta.get("tracks") or []):
        e = t.get("ovd")
        if e:
            held[t.get("track_id")] = (e.get("payload") or {}).get("concept")

    tracked = [it for it in rpn_items if it.get("track_id") is not None]

    def _assign(dets):
        """**합의한 쌍을 통째로 한 트랙에** 붙인다. 검출↔트랙 양방향 1:1.

        두 모델의 근거를 따로 배정하면 서로 다른 트랙에 떨어져 합의가 성립하지
        않는다 — 실측에서 확정 집합이 정지 장면인데도 프레임당 0.42개씩 들고났다
        (2026-09-21). 그래서 엣지에서 이미 쌍으로 묶인 검출(merge_by_consensus)을
        하나의 근거로 싣는다. 말단은 그 근거를 누적해 판정한다.
        """
        cands = []
        for det_i, det in enumerate(dets):
            key = concept_key(det["label"], syn)
            for it in tracked:
                v = iou(it["box"], det["box"])
                if v < m_iou:
                    continue
                tid = it["track_id"]
                cands.append((v + (sticky if held.get(tid) == key else 0.0),
                              v, det_i, tid, it["box"], key))
        cands.sort(key=lambda c: -c[0])
        used_d, used_t, out = set(), set(), []
        for _, v, det_i, tid, cb, key in cands:
            if det_i in used_d or tid in used_t:
                continue
            used_d.add(det_i)
            used_t.add(tid)
            det = dets[det_i]
            out.append({"track_id": tid,
                        "ovd": {**det, "iou": round(v, 3), "concept": key,
                                "agreed": det.get("verdict") == "confident",
                                "cand_box": [round(q, 1) for q in cb]}})
        return out

    per_track = _assign(ovd_dets)

    return {
        "stage": 1,
        "frame_id": meta["frame_id"], "frame_seq": meta.get("frame_seq"),
        "node_id": meta.get("node_id"), "camera_id": meta.get("camera_id", 0),
        "observed_at": meta.get("observed_at") or meta.get("captured_at"),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "frame_wh": [w, h],
        "rpn_candidates": len(rpn_items),
        "ovd": ovd_dets, "ovd_count": len(ovd_dets),
        "ovd2_count": len(ovd2_dets), "consensus": consensus_stats,
        "objects": objects,
        "objects_confirmed": sum(1 for o in objects if o["confirmed"]),
        "object_stats": dict(getattr(ot, "last_stats", {})),
        "known_count": len(known), "unknown_count": len(unknown),
        "known": known, "ovd_verdicts": ovd_counts,
        "absorb": absorb_stats,
        "per_track": per_track,
        "timing_ms": {"ovd": round(ovd_ms, 1), "ovd2": round(ovd2_ms, 1),
                      "stage1_total": round((time.perf_counter() - t0) * 1000.0, 1)},
        "skipped": skipped,
        "pi4_timing_ms": meta.get("rpn", {}).get("timing_ms"),
        "_unknown": unknown,      # stage2로 넘기는 내부 필드(응답에서 뺀다)
    }


# --------------------------------------------------------------------------
# stage2: CLIP 근거화 — background 버림 / undecided 저장 / confident 반영
# --------------------------------------------------------------------------
def stage2(cfg: dict, record: dict, bgr) -> dict:
    cc = cfg["clip"]
    unknown = record.pop("_unknown", [])
    root = resolve(cfg, cfg["store"]["root"])
    st = cfg["store"]
    h, w = bgr.shape[:2]

    if STATE.get("clip") is None or not unknown:
        record["stage2"] = {"skipped": "clip_unavailable" if unknown else "no_unknown"}
        return record

    fd = STATE["dict"]
    dict_prompts, dict_index = fd.prompt_plan()
    free_prompts = list(cc.get("prompts", []))
    STATE["clip"].set_prompts(dict_prompts + free_prompts)
    base_free = len(dict_prompts)

    ctx = float(cfg["unknown"].get("crop_context", 1.5))
    take = unknown[: int(cc.get("max_crops_per_frame", 60))]

    # 같은 track_id를 매 프레임 다시 분류하지 않는다. 추적이 정체성을 유지하므로
    # 한 번 본 객체는 recheck 창 안에서는 이전 판정을 재사용한다. crop을 **줄이는**
    # 것이 아니라 **중복을 줄이는** 것이라, RPN이 후보를 넓게 내는 목적과 충돌하지 않는다.
    dedup = bool(cc.get("dedup_by_track", True))
    recheck = float(cc.get("dedup_recheck_s", 3.0))
    cache: dict = STATE.setdefault("clip_cache", {})
    now = time.time()
    for tid in [k for k, v in cache.items() if now - v["at"] > recheck * 4]:
        cache.pop(tid, None)          # 오래된 항목은 버린다(무한 증가 방지)

    crops, kept, reused = [], [], 0
    for d in take:
        tid = d.get("track_id")
        if dedup and tid is not None:
            hit = cache.get(tid)
            if hit and (now - hit["at"]) <= recheck:
                d["clip"] = {**hit["clip"], "reused_from_frame": hit["frame_id"],
                             "reused_age_s": round(now - hit["at"], 2)}
                reused += 1
                continue
        x1, y1, x2, y2 = expand_box(d["box"], ctx, w, h)
        if x2 <= x1 or y2 <= y1:
            continue
        crops.append(bgr[y1:y2, x1:x2])
        kept.append(d)

    t = time.perf_counter()
    sims = (STATE["clip"].score(crops, int(cc.get("batch_size", 16)))
            if crops else [])
    clip_ms = (time.perf_counter() - t) * 1000.0

    bg_set = STATE.get("background_classes", set())
    bg_margin = float(cc.get("background_margin", 0.010))
    cf_margin = float(cc.get("confident_margin", 0.030))
    use_abs = bool(cc.get("use_target_sim_threshold", True))
    default_target_sim = float(cc.get("default_target_sim", 0.22))
    top_k = int(cc.get("top_k", 5))

    counts = {"background": 0, "unidentified": 0}
    per_track, saved = [], []
    crop_dir = root / "unknown_crops"
    untracked_saved = 0            # 이 프레임에서 실제로 저장한 수(상한 적용)

    for d, crop, row in zip(kept, crops, sims):
        per_class = fd.score_row(row, dict_index)
        ranked = sorted(per_class.items(), key=lambda kv: -kv[1])
        gap = (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else 1.0
        top1 = ranked[0][0]

        # **두 갈래.** CLIP이 설명한 것은 확신이 아니라 추론이다(사용자 2026-09-21).
        # 실제 오추론 사례: 차량 일부나 여러 차량이 합쳐진 박스를 damaged_vehicle로
        # 찍었다. 사전은 닫힌 집합이고 argmax에는 "해당 없음"이 없으므로, 점수가
        # 아무리 갈려도 그것이 "맞다"는 근거가 되지 못한다.
        # 그래서 CLIP은 말단 레코드에 올리지 않고 **가시화로 관리자에게 전달할
        # 근거**로만 쓴다 — 연초록(OVD 잠정)과 같은 성격이다(AI-S-04, AI-L-03).
        #
        # 판정 축이 둘이다(2026-09-21 재보정으로 추가):
        #   상대(gap)  1등과 2등의 차이. 사전 안에서 얼마나 갈렸나.
        #   절대(top1) 1등 점수 자체. 사전 어느 항목과도 별로 안 닮았으면 높은 gap도
        #              의미가 없다 — 8개 중 덜 안 닮은 것을 고른 것뿐이다.
        # 상대만 쓰던 이전 판은 crop 512개 실측에서 배경/비배경 gap 분포가 거의 겹쳤다
        # (비배경 gap이 배경보다 큰 비율 0.683, 0.5면 구분 불가). 절대 축은 사전이
        # 이미 항목마다 들고 있던 `target_sim_threshold`를 실제로 쓰는 것이다 —
        # 지금까지 선언만 되어 있고 판정에 반영되지 않았다.
        need = fd.entries.get(top1, {}).get("target_sim_threshold")
        if need is None:
            need = default_target_sim
        meets_abs = (not use_abs) or (ranked[0][1] >= float(need))

        if top1 in bg_set and gap >= bg_margin:
            verdict = "background"
        else:
            verdict = "unidentified"
        # 얼마나 갈렸는지는 버리지 않고 근거로 남긴다 — 관리자가 정렬·필터할 축이다.
        # 판정을 바꾸지는 않는다(둘 다 unidentified다).
        strength = ("strong" if (top1 not in bg_set and gap >= cf_margin and meets_abs)
                    else "weak")
        counts[verdict] += 1

        free_row = row[base_free:]
        clip_ev = {
            "verdict": verdict, "status": "inference",  # 확신이 아니다
            "strength": strength,
            "ranking": [{"class": k, "score": round(v, 4),
                         "verified": bool(fd.entries.get(k, {}).get("_verified", True))}
                        for k, v in ranked[:top_k]],
            "top1_gap": round(float(gap), 4),
            "top1_score": round(float(ranked[0][1]), 4),
            "target_sim_threshold": round(float(need), 4),
            "meets_absolute": bool(meets_abs),
            "free_prompt_best": (free_prompts[int(np.argmax(free_row))]
                                 if free_row else None),
            "free_prompt_score": (round(float(np.max(free_row)), 4)
                                  if free_row else None),
        }
        d["clip"] = clip_ev
        if dedup and d.get("track_id") is not None:
            cache[d["track_id"]] = {"clip": clip_ev, "at": now,
                                    "frame_id": record["frame_id"]}

        # 배경은 **저장하지 않는다**(저장소가 오탐으로 차는 것을 막는 유일한 경로.
        # RPN precision@50 0.19~0.25). 다만 오버레이에는 **회색으로 그린다** —
        # 도로·건물을 실제로 지우고 있는지 눈으로 확인할 수 있어야 한다
        # (사용자 2026-09-21).
        if verdict == "background" and not st.get("save_background_crops", False):
            continue

        # **같은 물체를 프레임마다 다시 저장하지 않는다.** 1000번째 crop은 새 이유를
        # 담고 있지 않으므로 학습 후보가 아니다(AI-L-01). 정체성 기준으로 거르고,
        # track_id가 없는 후보는 프레임당 몇 장까지만 받는다.
        gate = STATE.get("crop_gate")
        cam_i = int(record.get("camera_id", 0))
        if gate is None:
            allow = True
        elif untracked_saved >= gate.max_per_frame:
            allow = False          # 한 프레임이 저장을 독차지하지 않게 한다
        else:
            allow = gate.allow(cam_i, d["box"], clip_ev.get("verdict", ""))
            if allow:
                untracked_saved += 1

        if st.get("save_unknown_crops", True) and allow:
            crop_dir.mkdir(parents=True, exist_ok=True)
            base = f"{record['frame_id']}_u{len(saved):03d}"
            cv2.imwrite(str(crop_dir / f"{base}.jpg"), crop,
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            # 추론 결과와 **근거를 함께** 남긴다 — 가시화가 "왜 이렇게 봤는지"를
            # 보여줄 수 있어야 한다(AI-L-03). 이것은 정답이 아니라 후보다(AI-L-02).
            (crop_dir / f"{base}.json").write_text(json.dumps({
                "frame_id": record["frame_id"], "frame_seq": record.get("frame_seq"),
                "observed_at": record.get("observed_at"),
                "track_id": d.get("track_id"), "box": d["box"],
                "objectness": d.get("objectness"), "best_iou_with_ovd": d.get("best_iou"),
                "clip": clip_ev, "verified": False,
                "for_visualization": True,   # 저장된 것은 전부 가시화 대상이다
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            d["crop"] = f"unknown_crops/{base}.jpg"
            saved.append(base)

        # **말단에 보내지 않는다.** CLIP은 추론이지 확신이 아니므로 말단의 지속
        # 레코드를 바꿀 근거가 못 된다(사용자 2026-09-21). 말단이 반영하는 것은
        # OVD 확신뿐이고, CLIP 결과는 store에 남아 가시화가 소비한다.
        if cfg["clip"].get("send_to_terminal", False) and d.get("track_id") is not None:
            # 관측 당시 박스를 함께 보낸다 — 말단이 "이 근거가 관측된 위치"와
            # "지금 위치"를 비교해 시점 반영이 실제로 일어났는지 검증한다.
            per_track.append({"track_id": d["track_id"],
                              "clip": {**clip_ev, "box": d["box"]},
                              "crop": d.get("crop")})

    # 재사용분도 카운트에 넣어 "이 프레임에서 무엇이 무엇으로 보였나"가 온전히 남게 한다.
    for d in take:
        if "reused_from_frame" in d.get("clip", {}):
            counts[d["clip"]["verdict"]] = counts.get(d["clip"]["verdict"], 0) + 1

    record["unknown"] = take
    record["stage2"] = {"counts": counts, "saved_crops": len(saved),
                        "clip_ms": round(clip_ms, 1), "scored": len(crops),
                        "reused_from_track": reused,
                        "sent_to_terminal": len(per_track)}
    record["timing_ms"]["clip"] = round(clip_ms, 1)
    record["_stage2_per_track"] = per_track
    return record


def detect_domain(cfg: dict, switch: bool = True) -> dict:
    """VLM이 현재 장면을 보고 어느 도메인인지 고르면 CLIP 사전을 그에 맞게 바꾼다.

    사용자 제안(2026-09-21). 고리가 이렇게 닫힌다:

        VLM(장면이 무엇인가) → 도메인 선택 → CLIP 사전 교체 → 근거 품질 향상

    왜 필요한가: 사전은 닫힌 집합이고 argmax에는 "해당 없음"이 없다. 그래서 **틀린
    도메인의 사전을 쓰면 조용히 그럴듯한 오답이 나온다** — 실측으로 하천 사전을 도시
    영상에 쓰자 미지 crop의 71.7%가 tire/plastic_bag으로 몰렸다. 사람이 도메인을 미리
    지정하는 대신 장면에서 읽어내면 이 실패 방식 자체가 사라진다.

    판정은 VLM 한 번으로 끝내지 않는다. VLM은 자유 서술을 하고, 그 서술을 설정에 있는
    도메인 **후보 목록**과 맞춘다. 후보 밖이면 바꾸지 않고 사유를 돌려준다 —
    모르는 도메인으로 멋대로 갈아타는 것이 틀린 사전을 쓰는 것보다 낫지 않다.
    """
    if STATE.get("vlm") is None:
        return {"error": f"vlm_unavailable:{STATE.get('vlm_error','?')}"}
    last = STATE.get("last_frame")
    if not last:
        return {"error": "아직 받은 프레임이 없다"}

    domains = cfg["clip"].get("domains", {})
    menu = "\n".join(f'- "{k}": {v.get("hint", k)}' for k, v in domains.items())
    prompt = (
        "You are looking at one frame from a drone camera. Decide which operating "
        "domain this scene belongs to.\n\nCandidate domains:\n" + menu +
        '\n\nAnswer strictly as JSON:\n'
        '{"domain": "<one of the keys above, or \'unknown\'>", '
        '"scene": "<one short sentence describing what you see>", '
        '"confidence": 0.0-1.0}\n'
        "Use 'unknown' if the scene clearly matches none of them."
    )
    t0 = time.perf_counter()
    try:
        raw = STATE["vlm"].ollama.generate(STATE["vlm"].model, prompt,
                                           images_b64=[_b64(last["jpeg"])])
    except Exception as exc:
        return {"error": repr(exc)[:200]}
    from semantic import _extract_json

    parsed = _extract_json(raw) or {}
    picked = str(parsed.get("domain", "unknown")).strip()
    out = {"frame_id": last["frame_id"], "detected": picked,
           "scene": str(parsed.get("scene", ""))[:300],
           "confidence": parsed.get("confidence"),
           "previous_domain": STATE.get("active_domain"),
           "vlm_ms": round((time.perf_counter() - t0) * 1000.0, 1),
           "model": STATE["vlm"].model, "switched": False,
           "status": "hypothesis"}     # 장면 판단도 가설이다(AI-S-04)

    if picked in domains and switch and picked != STATE.get("active_domain"):
        out.update(apply_domain(cfg, picked))
        out["switched"] = True
    elif picked not in domains:
        out["reason"] = ("후보 밖이라 바꾸지 않았다 — 모르는 도메인으로 갈아타는 것이 "
                         "틀린 사전을 쓰는 것보다 낫지 않다")
    elif picked == STATE.get("active_domain"):
        out["reason"] = "이미 그 도메인이다"

    root = resolve(cfg, cfg["store"]["root"]) / "scene"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{last['frame_id']}.domain.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _b64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode()


# --------------------------------------------------------------------------
# VLM 환경 서술 — **명령이 올 때만** 돈다(사용자 2026-09-21).
# --------------------------------------------------------------------------
def describe_scene(cfg: dict) -> dict:
    """가장 최근 프레임의 환경 서술. LLM과 마찬가지로 프레임 처리 경로에 없다.

    주기 실행을 뺀 이유: 이것은 객체 판정이 아니라 **현재 상황 서술**이라 매 프레임
    필요하지 않고, ollama 호출이 초 단위라 상시로 돌면 비동기 큐만 잡아먹는다.
    가시화나 운영자가 "지금 무슨 상황인가"를 물을 때 답하면 된다.
    """
    if STATE.get("vlm") is None:
        return {"error": f"vlm_unavailable:{STATE.get('vlm_error','?')}"}
    last = STATE.get("last_frame")
    if not last:
        return {"error": "아직 받은 프레임이 없다"}
    t = time.perf_counter()
    desc = STATE["vlm"].describe_scene(last["jpeg"])
    out = {"frame_id": last["frame_id"], "frame_seq": last.get("frame_seq"),
           "observed_at": last.get("observed_at"),
           "domain": cfg["vlm"].get("active_domain"),
           "age_s": round(time.time() - (last.get("at") or time.time()), 2),
           "scene": desc, "vlm_ms": round((time.perf_counter() - t) * 1000.0, 1)}
    root = resolve(cfg, cfg["store"]["root"]) / "scene"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{last['frame_id']}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# 비동기 워커
# --------------------------------------------------------------------------
def worker(cfg: dict) -> None:
    q: queue.Queue = STATE["async_q"]
    buf: VerdictBuffer = STATE["verdicts"]
    n = 0
    while True:
        item = q.get()
        if item is None:
            return
        record, bgr = item
        n += 1
        # **주기적으로 오래된 것부터 지운다.** 비동기 워커에서 도는 이유는 stage1의
        # 동기 예산을 건드리지 않기 위해서다 — 디렉터리 훑기는 파일 수에 비례한다.
        rot = STATE.get("rotation")
        if rot is not None:
            gone = rot.maybe_prune()
            if gone:
                g = STATE.get("crop_gate")
                if g is not None:
                    g.sweep()
                print(f"  [보존] 정리 {gone}  누적 {rot.removed_total}"
                      + (f"  crop {g.stats()}" if g is not None else ""), flush=True)
        try:
            record = stage2(cfg, record, bgr)
            pt = record.pop("_stage2_per_track", [])
            if pt:
                buf.put({"stage": 2, "frame_id": record["frame_id"],
                         "frame_seq": record.get("frame_seq"),
                         "observed_at": record.get("observed_at"),
                         "per_track": pt})
            # **여기서 다시 발행하지 않는다.** 이 판정은 말단으로 가서 track_id로
            # 반영되고, 그 결과는 **다음 프레임의 meta["tracks"]**에 실려 돌아온다.
            # 화면이 보여줘야 하는 것은 엣지가 방금 본 것이 아니라 말단이 지금 들고
            # 있는 상태이므로, 그 왕복을 건너뛰면 검증하려는 대상 자체가 사라진다.
            _persist(cfg, record, bgr)
            c = record.get("stage2", {}).get("counts", {})
            s2 = record.get("stage2", {})
            print(f"  [async] {record['frame_id']}  배경 {c.get('background',0)} 버림 / "
                  f"미식별 {c.get('unidentified',0)} 저장  "
                  f"CLIP {record['timing_ms'].get('clip',0):.0f}ms"
                  f"(신규 {s2.get('scored',0)} / 재사용 {s2.get('reused_from_track',0)})",
                  flush=True)
        except Exception as exc:
            # 조용한 실패가 stage1을 멀쩡해 보이게 만든다. 스택까지 남긴다(AI-O-02).
            import traceback
            print(f"  [async] {record.get('frame_id')} 실패: {exc!r}", flush=True)
            traceback.print_exc()


def _persist(cfg: dict, record: dict, bgr) -> None:
    st = cfg["store"]
    root = resolve(cfg, st["root"])
    fid = record["frame_id"]
    if st.get("save_record", True):
        (root / "records").mkdir(parents=True, exist_ok=True)
        (root / "records" / f"{fid}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    if st.get("save_overlay", True):
        (root / "overlay").mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(root / "overlay" / f"{fid}.jpg"),
                    overlay(bgr, record.get("ovd", []), record.get("unknown", []),
                            bool(cfg["clip"].get("visualize_weak", True))))


def overlay(bgr, ovd_dets, unknown, show_weak: bool = True):
    """색 = **판정 범주**. 세 가지뿐이다(사용자 2026-09-21).

        진초록  확인됨      OVD가 확신을 갖고 이름 붙임  → 말단 레코드에 반영
        노랑    미식별      배경이 아닌데 뭔지 모름      → 근거만, 관리자 판단용
        회색    배경        버림                         → crop 저장 안 함

    **연초록을 없애고 노랑으로 합쳤다.** 잠정 OVD(낮은 conf)는 미식별과 같은
    범주다 — 둘 다 "배경이 아닌데 모르는 것"이고, 다른 것은 어느 근거가 붙어
    있느냐뿐이다. 그래서 라벨에 **두 근거를 나란히** 적는다:

        car 0.22? | vehicle_part 0.24?      ← OVD 근거 + CLIP 근거
        ? | road_debris 0.27?               ← CLIP 근거만
        person 0.19?                        ← OVD 근거만 (RPN 후보가 없던 검출)

    관리자는 이 둘을 같이 보고 판단한다(AI-S-03: 신뢰도와 근거 충분도는 별개,
    AI-L-03: 판단에 쓸 근거를 사용자에게 제공한다).

    배경도 그린다 — 도로·건물을 실제로 지우고 있는지 눈으로 확인할 수 있어야 한다.
    저장은 여전히 안 한다. 그리는 것과 저장하는 것은 다른 결정이다.
    """
    GREEN, YELLOW, GREY = (0, 200, 0), (0, 215, 255), (150, 150, 150)
    out = bgr.copy()
    n = {"confirmed": 0, "unidentified": 0, "background": 0, "weak_hidden": 0}

    def label(txt, x, y, color):
        cv2.putText(out, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, color, 1)

    # 1) 확인됨 — OVD 확신
    for d in ovd_dets:
        if d.get("verdict") != "confident":
            continue
        n["confirmed"] += 1
        x1, y1, x2, y2 = [int(t) for t in d["box"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), GREEN, 2)
        label(f"{d['label']} {d['conf']:.2f}", x1, max(12, y1 - 5), GREEN)

    # 2) 미식별 / 배경 — RPN 후보에서 온 것. 두 근거를 나란히 적는다.
    hinted = set()
    for d in unknown:
        v = d.get("clip", {}).get("verdict")
        if v not in ("background", "unidentified"):
            continue
        # weak는 화면에서만 숨긴다 — **저장은 그대로다**. 프레임당 미식별이 53~62개라
        # 전부 그리면 관리자가 볼 수 없다(2026-09-21). 데이터를 버리는 것이 아니라
        # 가시화 기본값을 정하는 것이고, show_weak로 되돌린다.
        if (v == "unidentified" and not show_weak
                and d.get("clip", {}).get("strength") != "strong"):
            n["weak_hidden"] += 1
            continue
        n[v] += 1
        is_bg = v == "background"
        color = GREY if is_bg else YELLOW
        x1, y1, x2, y2 = [int(t) for t in d["box"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 1 if is_bg else 2)

        parts = []
        h = d.get("ovd_hint")
        if h:
            parts.append(f"{h['label']} {h['conf']:.2f}?")
            hinted.add(h["label"])
        top = d["clip"]["ranking"][0]
        parts.append(f"{top['class']} {top['score']:.2f}?")
        label(" | ".join(parts), x1, min(bgr.shape[0] - 4, y2 + 13), color)

    # 3) RPN 후보가 없던 잠정 OVD 검출도 미식별이다 — 빠뜨리면 근거가 사라진다.
    for d in ovd_dets:
        if d.get("verdict") != "tentative":
            continue
        n["unidentified"] += 1
        x1, y1, x2, y2 = [int(t) for t in d["box"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), YELLOW, 1)
        label(f"{d['label']} {d['conf']:.2f}?", x1, max(12, y1 - 5), YELLOW)

    hidden = f"  +{n['weak_hidden']} weak hidden" if n["weak_hidden"] else ""
    lines = [f"confirmed {n['confirmed']} (green)",
             f"unidentified {n['unidentified']} (yellow){hidden}  "
             f"background {n['background']} (grey, dropped)"]
    for k, txt in enumerate(lines):
        y = 26 + k * 26
        for col, th in (((0, 0, 0), 4), ((255, 255, 255), 1)):
            cv2.putText(out, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, th)
    return out


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def parse_multipart(body: bytes, ctype: str) -> dict[str, bytes]:
    import email

    msg = email.message_from_bytes(
        b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    parts: dict[str, bytes] = {}
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        name = None
        for token in part.get("Content-Disposition", "").split(";"):
            token = token.strip()
            if token.startswith("name="):
                name = token[5:].strip('"')
        if name:
            parts[name] = part.get_payload(decode=True)
    return parts


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, code: int, obj: dict):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # ------------------------------------------------------------------
    # 실시간 스트림
    # ------------------------------------------------------------------
    def _compare(self, cam: int):
        """기준선/파이프라인 비교 MJPEG."""
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q = int(STATE["cfg"].get("stream", {}).get("jpeg_quality", 70))
        fps = float(STATE["cfg"].get("stream", {}).get("max_fps", 12))
        last = 0.0
        try:
            while True:
                with LIVE_LOCK:
                    at = (LIVE.get(cam) or {}).get("at", 0.0)
                if at > last:
                    last = at
                    img = compose_compare(cam)
                    if img is not None:
                        ok, enc = cv2.imencode(".jpg", img,
                                               [cv2.IMWRITE_JPEG_QUALITY, q])
                        if ok:
                            data = enc.tobytes()
                            self.wfile.write(
                                b"--frame\r\nContent-Type: image/jpeg\r\n"
                                + f"Content-Length: {len(data)}\r\n\r\n".encode()
                                + data + b"\r\n")
                time.sleep(1.0 / max(1.0, fps))
        except (BrokenPipeError, ConnectionResetError):
            return

    def _stream(self, cam: int, store: dict | None = None):
        """MJPEG(multipart/x-mixed-replace). 브라우저 <img>가 그대로 받는다.

        WebSocket이나 별도 런타임을 들이지 않은 이유: 이 경로에 필요한 것은
        '최신 프레임을 계속 밀어 넣기'뿐이고 MJPEG는 표준 HTTP만으로 그걸 한다.
        영상 픽셀은 업무·관측 평면이 아니라 이 별도 미디어 경로로만 나간다(AI-C-08).
        """
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last = 0.0
        fps = float(STATE["cfg"].get("stream", {}).get("max_fps", 12))
        try:
            while True:
                with LIVE_LOCK:
                    item = (LIVE if store is None else store).get(cam)
                if item and item["at"] > last:
                    last = item["at"]
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                     + f"Content-Length: {len(item['jpeg'])}\r\n\r\n"
                                     .encode() + item["jpeg"] + b"\r\n")
                    self.wfile.flush()
                time.sleep(1.0 / max(1.0, fps))
        except (BrokenPipeError, ConnectionResetError):
            return

    def _page(self):
        with LIVE_LOCK:
            cams = sorted(LIVE)
        if not cams:
            cams = [c.get("index", 0) for c in
                    STATE["cfg"].get("_pi4_cameras", [])] or [0, 1]
        # 두 줄로 나란히 둔다 — 위가 파이프라인, 아래가 아무것도 얹지 않은 기준선.
        # 같은 화면에 놓아야 얹은 것들이 무엇을 바꾸는지 눈으로 비교할 수 있다.
        panes = "".join(
            f'<figure><figcaption>camera {c} — 파이프라인 '
            f'(합의 + 객체 레코드 + 시점 반영)</figcaption>'
            f'<img src="/stream?camera={c}" alt="camera {c}"></figure>'
            for c in cams)
        panes += "".join(
            f'<figure><figcaption>camera {c} — 기준선 '
            f'(YOLOE만, RPN·ByteTrack 없음)</figcaption>'
            f'<img src="/raw?camera={c}" alt="raw {c}"></figure>'
            for c in cams)
        panes += "".join(
            f'<figure style="flex:1 1 100%"><figcaption>camera {c} — 비교 '
            f'(위 기준선 / 아래 파이프라인)</figcaption>'
            f'<img src="/compare?camera={c}" alt="compare {c}"></figure>'
            for c in cams)
        html = f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<title>pi4 RPN live</title>
<style>
 :root{{color-scheme:dark light;--bg:#111;--fg:#eee;--mut:#9aa}}
 body{{margin:0;background:var(--bg);color:var(--fg);
      font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}}
 header{{padding:10px 16px;border-bottom:1px solid #333}}
 main{{display:flex;flex-wrap:wrap;gap:12px;padding:12px}}
 figure{{margin:0;flex:1 1 520px}} img{{width:100%;display:block;background:#000}}
 figcaption{{color:var(--mut);padding:4px 2px}}
 .legend span{{margin-right:14px}} .b{{color:#999}} .g{{color:#0c0}} .y{{color:#fc0}}
</style>
<header>drone pi4 ↔ edge
 <span class="legend" style="margin-left:16px">
  <span class="g">■ 확인됨 (OVD 확신)</span><span class="y">■ 미식별</span>
  <span class="b">■ 배경 (버림)</span><span style="color:#5a5a5a">■ CLIP 대기</span></span>
 <span style="color:var(--mut);margin-left:16px">OVD: YOLOE prompt-free 4585종 · CLIP: generic 사전</span>
</header>
<main>{panes}</main></html>"""
        raw = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        cfg = STATE["cfg"]
        if self.path == "/" or self.path.startswith("/index"):
            self._page()
            return
        if self.path.startswith("/stream"):
            m = re.search(r"camera=(\d+)", self.path)
            self._stream(int(m.group(1)) if m else 0)
            return
        if self.path.startswith("/api/tracks"):
            # 시점 반영 검증용 원본 덤프 — moved_px와 age_s의 분포를 본다.
            m = re.search(r"camera=(\d+)", self.path)
            cam = int(m.group(1)) if m else 0
            with LIVE_LOCK:
                tr = list((LIVE.get(cam) or {}).get("tracks", []))
            ev = [(t[s]["age_s"], t[s].get("moved_px", 0), t["track_id"], s)
                  for t in tr for s in ("ovd", "clip") if t.get(s)]
            objs = list((LIVE.get(cam) or {}).get("objects", []))
            self._json(200, {"camera": cam, "n_tracks": len(tr),
                             "n_evidence": len(ev), "evidence": ev,
                             # 살아있는 트랙 id 전체 — 라벨이 사라졌을 때 그것이
                             # '근거를 잃은 것'인지 '트랙이 죽은 것'인지 가르려면
                             # 잘리지 않은 목록이 필요하다.
                             "all_ids": [t["track_id"] for t in tr],
                             "objects": objs,
                             "object_stats": (LIVE.get(cam) or {}).get("object_stats", {}),
                             "n_confirmed": sum(1 for o in objs if o.get("confirmed")),
                             "tracks": tr[:40]})
            return
        if self.path.startswith("/compare"):
            m = re.search(r"camera=(\d+)", self.path)
            self._compare(int(m.group(1)) if m else 0)
            return
        if self.path.startswith("/api/raw"):
            m = re.search(r"camera=(\d+)", self.path)
            cam = int(m.group(1)) if m else 0
            with LIVE_LOCK:
                it = dict(RAW.get(cam) or {})
            it.pop("jpeg", None)
            self._json(200, it)
            return
        if self.path.startswith("/raw"):
            m = re.search(r"camera=(\d+)", self.path)
            self._stream(int(m.group(1)) if m else 0, store=RAW)
            return
        if self.path == "/api/live":
            with LIVE_LOCK:
                self._json(200, {str(k): {**v["info"], "age_s": round(time.time() - v["at"], 2)}
                                 for k, v in LIVE.items()})
            return
        if self.path.startswith("/api/verdicts"):
            m = re.search(r"since=(\d+)", self.path)
            items, cursor = STATE["verdicts"].since(int(m.group(1)) if m else 0)
            self._json(200, {"verdicts": items, "cursor": cursor,
                             "pending_async": STATE["async_q"].qsize()})
        elif self.path == "/api/health":
            self._json(200, {
                "ok": True,
                "ovd": STATE.get("ovd") is not None,
                "clip": STATE.get("clip") is not None,
                "llm": STATE.get("llm") is not None,
                "vlm": STATE.get("vlm") is not None,
                "ovd_error": STATE.get("ovd_error"), "clip_error": STATE.get("clip_error"),
                "llm_error": STATE.get("llm_error"), "vlm_error": STATE.get("vlm_error"),
                "ovd_vocabulary_size": len(STATE["ovd"].vocab) if STATE.get("ovd") else 0,
                "ovd_mode": getattr(STATE.get("ovd"), "mode", None),
                "ovd2": STATE.get("ovd2") is not None,
                "ovd2_error": STATE.get("ovd2_error"),
                "ovd2_vocabulary": list(getattr(STATE.get("ovd2"), "vocab", []) or []),
                "active_domain": STATE.get("active_domain"),
                "domains": list(cfg["clip"].get("domains", {})),
                "dictionary": STATE["dict"].classes() if STATE.get("dict") else [],
                "background_classes": sorted(STATE.get("background_classes", [])),
                "pending_async": STATE["async_q"].qsize(),
            })
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        cfg = STATE["cfg"]
        if self.path == "/api/command":
            self._command(cfg)
        elif self.path == "/api/observe":
            self._observe(cfg)
        else:
            self._json(404, {"error": "not found"})

    def _command(self, cfg: dict):
        """가시화에서 오는 명령. 지금은 '이 클래스를 찾아라' 하나다.

        **LLM은 여기서만 돈다**(사용자 2026-09-21) — 프레임 처리 경로에는 없다.
        생성된 특징은 사전에 올라가 다음 프레임부터 CLIP 앵커로 쓰인다.
        """
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as exc:
            self._json(400, {"error": repr(exc)[:200]})
            return
        cmd = body.get("command")
        if cmd == "describe_scene":
            self._json(200, describe_scene(cfg))
            return
        if cmd == "detect_domain":
            self._json(200, detect_domain(cfg, bool(body.get("switch", True))))
            return
        if cmd == "set_domain":
            try:
                self._json(200, apply_domain(cfg, str(body.get("domain", ""))))
            except KeyError as exc:
                self._json(400, {"error": str(exc)})
            return
        if cmd != "find_class":
            self._json(400, {"error": "unknown command",
                             "supported": ["find_class", "describe_scene",
                                           "detect_domain", "set_domain"]})
            return
        if STATE.get("llm") is None:
            self._json(503, {"error": f"llm_unavailable:{STATE.get('llm_error','?')}"})
            return
        query = str(body.get("query", "")).strip()
        if not query:
            self._json(400, {"error": "query 없음"})
            return
        key = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "query_class"
        fd = STATE["dict"]
        if key in fd.entries:
            self._json(200, {"class": key, "already_known": True,
                             "features": fd.entries[key].get("features", [])})
            return
        try:
            gen = STATE["llm"].generate(query, key)
            ok, why = validate_entry(gen["entry"])
            if ok:
                fd.add(key, gen["entry"], provenance={
                    "source": "llm", "model": gen["model"], "query": query,
                    "at": time.time(), "trigger": "visualization_command"})
                STATE["clip"].prompts = []   # 사전이 바뀌었으니 텍스트 임베딩 재생성
            self._json(200, {"class": key, "accepted": ok, "reason": why,
                             "features": (gen["entry"] or {}).get("features"),
                             "rationale": (gen["entry"] or {}).get("rationale"),
                             "latency_ms": gen["latency_ms"], "model": gen["model"],
                             "verified": False})
        except Exception as exc:
            self._json(500, {"error": repr(exc)[:300]})

    def _observe(self, cfg: dict):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            parts = parse_multipart(self.rfile.read(n),
                                    self.headers.get("Content-Type", ""))
            meta = json.loads(parts["meta"].decode("utf-8"))
            if "frame" not in parts:
                self._json(200, {"stage": 1, "frame_id": meta.get("frame_id"),
                                 "per_track": [],
                                 "skipped": ["no_frame: OVD/CLIP require pixels"]})
                return
            bgr = cv2.imdecode(np.frombuffer(parts["frame"], np.uint8),
                               cv2.IMREAD_COLOR)

            # 수신물은 먼저 남긴다 — 이후 단계가 실패해도 입력은 보존된다(AI-O-03).
            st, root = cfg["store"], resolve(cfg, cfg["store"]["root"])
            fid = meta["frame_id"]
            if st.get("save_incoming_frame", True):
                (root / "frames").mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(root / "frames" / f"{fid}.jpg"), bgr)
            if st.get("save_incoming_meta", True):
                (root / "meta").mkdir(parents=True, exist_ok=True)
                (root / "meta" / f"{fid}.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

            # 환경 서술 명령이 올 때 쓸 최근 프레임 하나만 들고 있는다.
            STATE["last_frame"] = {"frame_id": fid, "frame_seq": meta.get("frame_seq"),
                                   "observed_at": meta.get("observed_at"),
                                   "at": time.time(), "jpeg": parts["frame"]}

            rec = stage1(cfg, meta, bgr)
            resp = {k: v for k, v in rec.items() if not k.startswith("_")}
            self._json(200, resp)      # ← 여기서 말단은 이미 반영을 시작한다
            # 프레임당 **한 번만** 발행한다(사용자 2026-09-21 B안). 이전에는 stage1과
            # stage2에서 두 번 그려 같은 seq가 번갈아 나왔고, stage1이 RPN 후보
            # 100여 개를 '판정 대기'로 깔아 화면이 주기적으로 뒤집혀 보였다.
            #
            # 그릴 대상도 바꿨다 — 엣지가 방금 검출한 것이 아니라 말단이 보낸
            # `tracks`(시점 반영된 현재 상태)를 그린다. 이 프레임의 판정은 말단을
            # 거쳐 다음 프레임의 tracks로 돌아온다.
            publish_live(cfg, meta, bgr, rec, staged=2)

            try:
                STATE["async_q"].put_nowait((rec, bgr))
            except queue.Full:
                # 비동기가 밀리면 stage2/3을 건너뛴다. stage1은 이미 나갔다 —
                # 느린 단계가 빠른 단계를 막지 않는다(AI-C-05).
                STATE["async_dropped"] = STATE.get("async_dropped", 0) + 1

            print(f"{rec['frame_id']} [stage1]  RPN {rec['rpn_candidates']}  "
                  f"OVD {rec['ovd_count']}({rec['timing_ms']['ovd']:.0f}ms)  "
                  f"(확신 {rec['ovd_verdicts']['confident']}/잠정 {rec['ovd_verdicts']['tentative']})  "
                  f"흡수 m{rec['absorb']['match']}/f{rec['absorb']['fragment']}"
                  f"/g{rec['absorb']['merged']}"
                  f"+병합{rec['absorb']['merged_away']}  "
                  f"미지 {rec['unknown_count']}  응답 {rec['timing_ms']['stage1_total']:.0f}ms  "
                  f"async대기 {STATE['async_q'].qsize()}", flush=True)
        except Exception as exc:
            self._json(500, {"error": repr(exc)[:400]})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--host", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    STATE["cfg"] = cfg
    STATE["verdicts"] = VerdictBuffer(int(cfg["server"].get("verdict_buffer", 2000)))
    STATE["async_q"] = queue.Queue(maxsize=32)

    # optional provider 결손은 기동 실패가 아니다(AI-C-05).
    if cfg["ovd"].get("enabled", True):
        try:
            STATE["ovd"] = YoloeOvd(cfg)
            print(f"OVD 로드됨 — YOLOE prompt-free, 내장 어휘 {len(STATE['ovd'].vocab)}종")
        except Exception as exc:
            STATE["ovd"], STATE["ovd_error"] = None, repr(exc)[:200]
            print(f"OVD 없음 → 해당 단계만 비활성: {STATE['ovd_error']}")
    st_cfg = cfg.get("store", {})
    STATE["crop_gate"] = CropGate(st_cfg)
    STATE["rotation"] = Rotation(resolve(cfg, st_cfg.get("root", "store")), st_cfg)
    caps = STATE["rotation"].caps
    g = STATE["crop_gate"]
    print(f"보존 정책 — crop 게이트 IoU {g.match_iou:.2f} 슬롯당 {g.max_per_slot}장/"
          f"{g.min_interval_s:.0f}s, 프레임당 최대 {g.max_per_frame}장, "
          f"디렉터리 상한 {caps}")
    if cfg.get("ovd2", {}).get("enabled", False):
        try:
            STATE["ovd2"] = WorldOvd(cfg)
            n = len(STATE["ovd2"].vocab)
            print(f"OVD2 로드됨 — YOLO-World 텍스트 어휘 {n}종"
                  if n else "OVD2 어휘 없음 → 합의 비활성(단일 모델로 축소)")
        except Exception as exc:
            STATE["ovd2"], STATE["ovd2_error"] = None, repr(exc)[:200]
            print(f"OVD2 없음 → 합의 비활성: {STATE['ovd2_error']}")
    if cfg["clip"].get("enabled", True):
        try:
            backend = cfg["clip"].get("backend", "torch")
            STATE["clip"] = (TorchClipScorer(cfg) if backend == "torch"
                             else ClipScorer(cfg))
            print(f"CLIP 로드됨 — EP {STATE['clip'].providers}")
        except Exception as exc:
            STATE["clip"], STATE["clip_error"] = None, repr(exc)[:200]
            print(f"CLIP 없음 → 해당 단계만 비활성: {STATE['clip_error']}")

    info = apply_domain(cfg, cfg["clip"].get("active_domain", "urban"))
    print(f"도메인 '{info['domain']}' — 사전 {len(info['classes'])}개 "
          f"(배경 {len(info['background_classes'])}개) ← {info['dictionary']}")

    if cfg.get("llm", {}).get("enabled"):
        try:
            o = Ollama(cfg["llm"]["host"], float(cfg["llm"].get("timeout_s", 120)))
            want = cfg["llm"]["model"]
            if want not in o.available_models():
                raise RuntimeError(f"ollama에 {want} 없음")
            STATE["llm"] = LlmFeatureGenerator(o, want)
            print(f"LLM 로드됨 — {want} (가시화 명령 시에만 실행)")
        except Exception as exc:
            STATE["llm"], STATE["llm_error"] = None, repr(exc)[:200]
            print(f"LLM 없음 → 사전 즉석생성만 비활성: {STATE['llm_error']}")

    if cfg.get("vlm", {}).get("enabled"):
        try:
            want = (cfg["vlm"].get("model") or "").strip()
            if not want:
                raise RuntimeError("vlm.model 미지정 — 예: ollama pull qwen2.5vl:3b")
            o = Ollama(cfg["vlm"]["host"], float(cfg["vlm"].get("timeout_s", 120)))
            if want not in o.available_models():
                raise RuntimeError(f"ollama에 {want} 없음")
            # 사전 도메인을 따른다 — VLM만 다른 도메인을 보고 있으면 안 된다.
            dom = STATE.get("active_domain") or cfg["vlm"].get("active_domain", "generic")
            cfg["vlm"]["active_domain"] = dom
            STATE["vlm"] = VlmDescriber(
                o, want, scene_prompt=cfg["vlm"].get("scene_prompts", {}).get(dom))
            print(f"VLM 로드됨 — {want}, 장면 서술 도메인 {dom} "
                  f"(POST /api/command describe_scene 시에만 실행)")
        except Exception as exc:
            STATE["vlm"], STATE["vlm_error"] = None, repr(exc)[:200]
            print(f"VLM 없음 → 환경 서술만 비활성: {STATE['vlm_error']}")

    threading.Thread(target=worker, args=(cfg,), daemon=True).start()

    host = args.host or cfg["server"].get("host", "0.0.0.0")
    port = int(cfg["server"]["port"])
    print(f"엣지 서버 http://{host}:{port}  저장소 {resolve(cfg, cfg['store']['root'])}")
    print(f"  **실시간 화면: http://{host if host != '0.0.0.0' else '<이 기기 주소>'}:{port}/**")
    print("  stage1 OVD 동기 / stage2 CLIP 비동기 → GET /api/verdicts?since=N")
    print("  명령: POST /api/command "
          "{find_class | describe_scene | detect_domain | set_domain}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
