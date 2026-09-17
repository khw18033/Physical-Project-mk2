"""OWL-ViT-backed open-vocabulary PerceptionProvider (AI-E-01, AI-S-04).

implements: AI-E-01, AI-S-04, AI-B-08, AI-B-09, AI-C-11

과거 0B/0C 실험(실행 코드는 이후 정리 과정에서 저장소에서 제거됨)에서 실측
검증된 결과를 실제 framework 코드로 옮긴 것이다(회귀 없음 확인: TAO 6비디오에서
known recall 0.757, unknown recall 0.392, 20260901 재현). 두 가지 실측 사실을
그대로 반영한다.

1. 단일 추상 프롬프트("an object")는 grounding이 매우 약하다(0B: known
   0.007, unknown 0.004). 그래서 이 provider는 **넓은 구체 명사 어휘**를
   기본으로 받는다 — 추상 프롬프트 모드는 제공하지 않는다.
2. 이 ONNX 모델은 int8 양자화본이고, CUDAExecutionProvider와 CPU 사이에
   원점수가 유의미하게 다르다(같은 입력에서 max prob diff 0.183 실측,
   과거 실험의 "GPU 실행 환경" 기록 참고 — 원본 실행 코드는 이후 정리 과정에서
   저장소에서 제거됨). 그래서
   이 provider는 **어떤 execution provider로 실행됐는지를 결과에 함께
   기록**한다 — 서로 다른 provider로 낸 결과를 같은 실험에서 섞으면 안 된다.

onnxruntime/tokenizers/cv2/numpy는 모듈 최상단이 아니라 생성자 안에서
지연 import한다(AI-C-11: 이 optional 의존성이 없는 노드도 이 모듈 자체는
계속 import할 수 있어야 다른 capability가 함께 죽지 않는다 — providers/compute.py
의 `_cv2()` 패턴과 동일).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perception_framework.perception.detection import PerceptionProvider, PerceptionResult

INPUT_SIZE = 768
# CLIP 정규화 상수. 과거 실험 스크립트(제거됨)의 smoke test와 동일한 값을 사용한다.
_MEAN = (0.48145466, 0.4578275, 0.40821073)
_STD = (0.26862954, 0.26130258, 0.27577711)


@dataclass(frozen=True)
class OpenVocabularyPerceptionResult(PerceptionResult):
    """`PerceptionResult`에 어떤 어휘 단어가 매칭됐는지와 실행 provider를 더한다.

    known class 이름 하나로 확정하지 않는다 — label은 매칭된 어휘 항목이지
    ground truth 분류가 아니다(0C 실험에서 확인: 정답 라벨이 아예 어휘에
    없어도 시각적으로 유사한 다른 단어에 매칭되는 경우가 다수였다).
    """

    matched_vocab: str = ""
    execution_provider: str = ""


@dataclass(frozen=True)
class RawVocabScores:
    """One frame's full known-vs-vocab probability matrix, pre-threshold.

    `probs[box_i, vocab_i]` is the sigmoid score of box `box_i` against
    `vocab[vocab_i]`. `boxes` are already pixel-space xyxy, aligned to
    `probs`' first axis. Box regression in OWL-ViT is computed from the
    image tower alone (text-independent), so two `detect_raw()` calls on the
    same frame with different vocabularies yield the same boxes at the same
    index — this is what lets a caller align a known-class run and an
    attribute run by box index without re-matching geometry.
    """

    vocab: tuple[str, ...]
    boxes: tuple[tuple[float, float, float, float], ...]
    probs: Any  # numpy ndarray [n_boxes, len(vocab)]; typed Any to avoid a hard numpy import here
    execution_provider: str


class OwlVitPerceptionProvider:
    """OWL-ViT(quantized ONNX) 기반 넓은-어휘 open-vocabulary 검출.

    벡터화된 클래스 전체가 아니라 `vocab`으로 받은 구체 명사 목록에 대해서만
    매칭한다 — known/unknown 여부 판정은 이 provider의 책임이 아니다
    (AI-S-04: 미확인 상태 유지는 상위 `UnconfirmedCandidateRegistry`가 한다).
    """

    def __init__(
        self,
        model_path: str | Path,
        tokenizer_path: str | Path,
        vocab: list[str],
        *,
        score_thr: float = 0.10,
        execution_providers: tuple[str, ...] = ("CUDAExecutionProvider", "CPUExecutionProvider"),
    ) -> None:
        if not vocab:
            raise ValueError("vocab must be non-empty — an empty vocabulary can never match anything")

        import onnxruntime as ort
        from tokenizers import Tokenizer

        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(model_path), sess_options=so, providers=list(execution_providers))
        self._active_provider = self._session.get_providers()[0]

        tok = Tokenizer.from_file(str(tokenizer_path))
        tok.enable_padding(pad_id=0, length=16)
        tok.enable_truncation(16)
        enc = tok.encode_batch(vocab)

        import numpy as np

        self._np = np
        self._vocab = list(vocab)
        self._input_ids = np.array([e.ids for e in enc], np.int64)
        self._attention_mask = np.array([e.attention_mask for e in enc], np.int64)
        self._score_thr = score_thr

    def active_execution_provider(self) -> str:
        """실제로 선택된 ONNX Runtime execution provider (CUDA 요청해도
        드라이버/라이브러리가 없으면 onnxruntime이 CPU로 조용히 내려간다 —
        결과 provenance에 무엇으로 실행됐는지 남기기 위해 노출한다)."""
        return self._active_provider

    @property
    def vocab(self) -> tuple[str, ...]:
        return tuple(self._vocab)

    def _preprocess(self, frame: Any) -> Any:
        import cv2

        np = self._np
        rgb = frame[:, :, ::-1]
        im = cv2.resize(rgb, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
        im = (im - np.array(_MEAN, np.float32)) / np.array(_STD, np.float32)
        return im.transpose(2, 0, 1)[None]

    def detect_raw(self, frame: Any) -> RawVocabScores:
        """Per-box, per-vocab sigmoid scores before any threshold is applied.

        `detect()` is a thresholded, single-vocab view over this. Exposed
        separately because unknown-object scoring (AI-S-04, e.g. FOMO's
        p_unknown = (1 - max(known)) * max(attribute)) needs the full known
        vs. attribute probability distribution, not just the labels that
        happened to clear one provider's own threshold.
        """
        np = self._np
        h, w = frame.shape[:2]
        pixel_values = self._preprocess(frame)
        logits, boxes = self._session.run(
            ["logits", "pred_boxes"],
            {"input_ids": self._input_ids, "pixel_values": pixel_values, "attention_mask": self._attention_mask},
        )
        probs = 1.0 / (1.0 + np.exp(-logits[0]))  # [n_boxes, n_vocab]

        pixel_boxes = []
        for cx, cy, bw, bh in boxes[0]:
            pixel_boxes.append(
                (
                    float((cx - bw / 2) * w),
                    float((cy - bh / 2) * h),
                    float((cx + bw / 2) * w),
                    float((cy + bh / 2) * h),
                )
            )
        return RawVocabScores(
            vocab=tuple(self._vocab),
            boxes=tuple(pixel_boxes),
            probs=probs,
            execution_provider=self._active_provider,
        )

    def detect(self, frame: Any) -> list[OpenVocabularyPerceptionResult]:
        raw = self.detect_raw(frame)
        out: list[OpenVocabularyPerceptionResult] = []
        for box_i, vocab_i in self._np.argwhere(raw.probs > self._score_thr):
            out.append(
                OpenVocabularyPerceptionResult(
                    box=raw.boxes[box_i],
                    label=raw.vocab[vocab_i],
                    confidence=float(raw.probs[box_i, vocab_i]),
                    matched_vocab=raw.vocab[vocab_i],
                    execution_provider=raw.execution_provider,
                )
            )
        return out
