"""CLIP text-feature dictionary matching for pre-proposed candidate boxes
(AI-E-04, AI-S-04, AI-S-06, AI-C-11).

implements: AI-E-04, AI-S-04, AI-S-06, AI-B-09, AI-C-11

2026-09-16 door/pedestal 랜드마크 통합 설계. 검증된 PoC(demo/test/
class_finder_service.py의 `BatchClipEngine`/`_dictionary_gate_and_score`)를
옮긴다. 실측으로 확정된 것들을 그대로 유지한다:

* CLIP은 quantized ONNX를 쓴다(fp32 시도 결과 정확도가 깨진다는 실측 결론,
  PoC 주석 그대로).
* 클래스별 판정은 AND 게이트(색상/모양/기준영상 유사도/채도/색상(H)/종횡비) 중
  설정된 것만 전부 통과해야 확정된다 — 하나라도 걸리면 탈락.
* 색상 게이트는 "anchored"(`a {class}'s {color} color`)와 "unanchored"
  (`{color} color`) 두 프롬프트 모드를 구분한다 — 문(door)의 하늘색처럼
  클래스 이름과 묶어 말하면 오히려 약해지는 색이 있었다는 실측 근거.

**2026-09-16 실제 로봇 리허설 반영(door_gate_relax/door_gate_harden 연구
결과, physical_demo 저장소 반영분 그대로 포팅)**: 데이터셋 8장만으로 튜닝한
값은 실제 로봇 카메라(조명·각도가 다름)에서 그대로 안 맞았다.
  * 색상/모양 게이트가 "1등이어야 통과"(top-1) 대신 `color_gate_tolerance`/
    `shape_gate.tolerance`로 **1등과의 차이가 이 값 이내면 통과**하는 마진
    방식으로 완화됐다 — 설정에 이 키가 없으면 마진 0(기존 top-1과 동일)이라
    이전 동작과 호환된다.
  * `hue_gate`(신규) — crop 픽셀의 HSV 색상(H) 중앙값이 범위 안이어야 통과.
    `_median_saturation`과 같은 방식으로 CLIP이 아니라 픽셀을 직접 재는
    게이트다. 단상·사람 다리를 문으로 오검출하는 걸 채도 게이트 혼자로는 못
    막아서 추가됐다(2026-09-15, `research/door_gate_harden/RESULT.md`).

**이 provider가 `PerceptionProvider` Protocol을 그대로 구현하지 않는 이유**:
CLIP 자체는 region-proposal 모델이 아니다 — 후보 박스는
`ondevice/rpn_propose.py`(class-agnostic RPN)가 낸 것을 받아서 그 각각을
텍스트 특징과 비교(gate + score)할 뿐이다. 그래서 `detect(frame)` 대신
`score_candidates(frame, candidate_boxes)`를 쓴다. 이 provider 하나가 클래스
하나(예: "door")에 바인딩된다 — `open_vocabulary.py::OwlVitPerceptionProvider`가
`vocab`을 생성 시점에 고정하는 것과 같은 패턴이다.

`onnxruntime`/`tokenizers`/`cv2`/`numpy`는 모듈 최상단이 아니라 필요한 지점에서
지연 import한다(AI-C-11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perception_framework.contracts.data_dictionary import FEATURE_SIMILARITIES, MANDATORY_GATES
from perception_framework.perception.detection import PerceptionResult

IMAGE_SIZE = 224
CONTEXT_LENGTH = 77
_CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
_CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
DEFAULT_TARGET_SIM_THRESHOLD = 0.26
#: 색상 게이트에서 "우리 클래스가 주장하는 색"과 경쟁시키는 대표 색 어휘
#: (PoC 실측 확정값 그대로 — 이 목록을 넓히거나 좁히는 건 별도 실험 대상).
COLOR_COMPETITOR_WORDS = ("white", "gray", "black", "brown", "red", "yellow", "green")


@dataclass(frozen=True)
class DictionaryPerceptionResult(PerceptionResult):
    """`PerceptionResult`에 재현 가능한 근거(어떤 특징을 비교했고 어떤 게이트를
    통과했는지)를 더한다. `contracts.data_dictionary`의 FEATURE_SIMILARITIES/
    MANDATORY_GATES 이름을 그대로 쓴다 — evidence.json에 그대로 실어도
    이름이 어긋나지 않는다."""

    detail: dict = field(default_factory=dict)


def _clip_preprocess(bgr: Any) -> Any:
    import cv2
    import numpy as np

    rgb = bgr[:, :, ::-1]
    h, w = rgb.shape[:2]
    s = IMAGE_SIZE / min(h, w)
    r = cv2.resize(
        np.ascontiguousarray(rgb),
        (max(IMAGE_SIZE, int(round(w * s))), max(IMAGE_SIZE, int(round(h * s)))),
        interpolation=cv2.INTER_CUBIC,
    )
    y = (r.shape[0] - IMAGE_SIZE) // 2
    x = (r.shape[1] - IMAGE_SIZE) // 2
    c = r[y:y + IMAGE_SIZE, x:x + IMAGE_SIZE].astype(np.float32) / 255.0
    mean = np.array(_CLIP_MEAN, np.float32)
    std = np.array(_CLIP_STD, np.float32)
    return ((c - mean) / std).transpose(2, 0, 1)


def _median_saturation(crop_bgr: Any) -> float:
    """crop 픽셀의 HSV 채도(S) 직접 측정 -- CLIP 텍스트 색상 게이트로 못
    가르던 오탐(예: 하얀 하늘색 vs 진한 하늘색 door)을 실측으로 분리한
    게이트(PoC에서 이 세션에 발견된 핵심 breakthrough)."""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    return float(np.median(hsv[..., 1]))


def _median_hue(crop_bgr: Any) -> float:
    """crop 픽셀의 HSV 색상(H, OpenCV 0~179) 중앙값 -- `hue_gate`(2026-09-15
    실제 로봇 리허설 반영, `research/door_gate_harden/RESULT.md`)가 쓴다.
    채도 게이트와 같은 방식(CLIP이 아니라 픽셀 직접 측정)으로, 짝 IoU로 못
    막는 "단상·사람 다리를 CLIP·OVD가 함께 문으로 오검출"한 사례를 줄인다."""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    return float(np.median(hsv[..., 0]))


class ClipEngine:
    """CLIP(quantized ONNX) 이미지/텍스트 인코더. 클래스마다 새로 만들 필요
    없이 여러 `ClipDictionaryPerceptionProvider` 인스턴스가 공유해도 된다."""

    def __init__(self, vision_model_path: str | Path, text_model_path: str | Path, tokenizer_path: str | Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        so = ort.SessionOptions()
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.vision = ort.InferenceSession(str(vision_model_path), sess_options=so, providers=providers)
        self.text = ort.InferenceSession(str(text_model_path), sess_options=so, providers=providers)
        tok = Tokenizer.from_file(str(tokenizer_path))
        eot = tok.token_to_id("<|endoftext|>")
        tok.enable_padding(pad_id=eot if eot is not None else 0, length=CONTEXT_LENGTH)
        tok.enable_truncation(CONTEXT_LENGTH)
        self.tok = tok

    def embed_images(self, crops_bgr: list[Any]):
        import numpy as np

        batch = np.stack([_clip_preprocess(c) for c in crops_bgr], axis=0)
        e = self.vision.run(None, {"pixel_values": batch})[0]
        return e / np.linalg.norm(e, axis=-1, keepdims=True)

    def embed_texts(self, prompts: list[str]):
        import numpy as np

        ids = np.array([e.ids for e in self.tok.encode_batch(prompts)], np.int64)
        e = self.text.run(None, {"input_ids": ids})[0]
        return e / np.linalg.norm(e, axis=-1, keepdims=True)


class ClipDictionaryPerceptionProvider:
    """클래스 하나(예: "door")에 바인딩된 CLIP 사전 매칭 provider.

    `class_config`는 demo/test/class_features.json의 클래스별 엔트리와 같은
    모양이다: `features`(list[str]), `reference_image_features`
    (`{source_image, features, unanchored_features}`), `shape_gate`
    (`{positive_prompts, negative_prompts}`), `saturation_gate`
    (`{min_saturation, max_saturation}`), `min_aspect_ratio_h_over_w`,
    `target_sim_threshold`.
    """

    def __init__(
        self,
        class_name: str,
        class_config: dict,
        engine: ClipEngine,
        *,
        repo_root: str | Path | None = None,
    ) -> None:
        self.class_name = class_name
        self.engine = engine
        self._repo_root = Path(repo_root) if repo_root is not None else Path.cwd()

        llm_features = list(class_config.get("features", []))
        ref_block = class_config.get("reference_image_features", {})
        ref_features = list(ref_block.get("features", []))
        llm_features = llm_features + ref_features
        unanchored = set(ref_block.get("unanchored_features", []))
        self.anchored_features = [
            f if f in unanchored else f"a {class_name}'s {f}" for f in llm_features
        ]
        self.color_feature_k = [
            k for k, f in enumerate(llm_features) if f in ref_features and "color" in f.lower()
        ]
        self.text_embeds = engine.embed_texts(self.anchored_features)

        self.shape_cfg = class_config.get("shape_gate")
        self.shape_embeds = (
            engine.embed_texts(self.shape_cfg["positive_prompts"] + self.shape_cfg["negative_prompts"])
            if self.shape_cfg else None
        )

        self.ref_sim_min = class_config.get("reference_image_similarity_min")
        self.ref_image_embed = None
        ref_image_path_str = ref_block.get("source_image")
        if ref_image_path_str:
            import cv2

            ref_bgr = cv2.imread(str(self._repo_root / ref_image_path_str))
            if ref_bgr is not None:
                self.ref_image_embed = engine.embed_images([ref_bgr])

        self.min_aspect = class_config.get("min_aspect_ratio_h_over_w")
        self.saturation_cfg = class_config.get("saturation_gate")
        self.hue_cfg = class_config.get("hue_gate")
        self.target_sim_threshold = class_config.get("target_sim_threshold", DEFAULT_TARGET_SIM_THRESHOLD)
        #: 2026-09-16 실측 리허설 반영: 마진 0이면 기존 "1등만 통과"와 동일하다
        #: (하위호환) -- `class_config`에 이 키가 없는 기존 클래스는 동작이
        #: 안 바뀐다.
        self.color_gate_tolerance = class_config.get("color_gate_tolerance", 0.0)
        self.shape_gate_tolerance = (self.shape_cfg or {}).get("tolerance", 0.0)

    def score_candidates(
        self, frame_bgr: Any, candidate_boxes: list[tuple[float, float, float, float]],
    ) -> list[DictionaryPerceptionResult]:
        """`candidate_boxes`(ondevice RPN 등이 낸 class-agnostic 후보)를 이
        클래스의 텍스트 특징과 비교해, AND 게이트를 전부 통과한 것만 반환한다."""
        import numpy as np

        if not candidate_boxes:
            return []
        crops = [self._crop(frame_bgr, box) for box in candidate_boxes]
        image_embeds = self.engine.embed_images(crops)

        sim_matrix = image_embeds @ self.text_embeds.T
        best_feature_idx = sim_matrix.argmax(axis=1)
        target_sim = sim_matrix.max(axis=1)
        n = len(candidate_boxes)

        color_passed, color_detail = self._color_gate(image_embeds, n)
        shape_passed, shape_detail = self._shape_gate(image_embeds, n)
        ref_passed, ref_detail = self._reference_image_gate(image_embeds, n)
        sat_passed, sat_detail = self._saturation_gate(crops, n)
        hue_passed, hue_detail = self._hue_gate(crops, n)

        out: list[DictionaryPerceptionResult] = []
        for i in range(n):
            if not (
                target_sim[i] >= self.target_sim_threshold
                and self._passes_aspect(candidate_boxes[i])
                and color_passed[i] and shape_passed[i] and ref_passed[i]
                and sat_passed[i] and hue_passed[i]
            ):
                continue
            gates: dict[str, Any] = {}
            if color_detail is not None:
                gates["color"] = color_detail(i)
            if shape_detail is not None:
                gates["shape"] = shape_detail(i)
            if ref_detail is not None:
                gates["reference_image"] = ref_detail(i)
            if sat_detail is not None:
                gates["saturation"] = sat_detail(i)
            if hue_detail is not None:
                gates["hue"] = hue_detail(i)
            if self.min_aspect is not None:
                x1, y1, x2, y2 = candidate_boxes[i]
                bw, bh = x2 - x1, y2 - y1
                gates["aspect_ratio"] = {
                    "passed": self._passes_aspect(candidate_boxes[i]),
                    "h_over_w": round(bh / bw, 3) if bw > 0 else None,
                    "min_required": self.min_aspect,
                }
            out.append(
                DictionaryPerceptionResult(
                    box=tuple(candidate_boxes[i]),
                    label=self.anchored_features[int(best_feature_idx[i])],
                    confidence=float(target_sim[i]),
                    detail={
                        FEATURE_SIMILARITIES: {
                            self.anchored_features[k]: round(float(sim_matrix[i, k]), 4)
                            for k in range(len(self.anchored_features))
                        },
                        MANDATORY_GATES: gates,
                    },
                )
            )
        return out

    def _crop(self, frame_bgr: Any, box: tuple[float, float, float, float]) -> Any:
        x1, y1, x2, y2 = (int(round(v)) for v in box)
        h, w = frame_bgr.shape[:2]
        x1, x2 = max(0, min(x1, w - 1)), max(1, min(x2, w))
        y1, y2 = max(0, min(y1, h - 1)), max(1, min(y2, h))
        return frame_bgr[y1:y2, x1:x2]

    def _passes_aspect(self, box: tuple[float, float, float, float]) -> bool:
        if self.min_aspect is None:
            return True
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        return bw > 0 and (bh / bw) >= self.min_aspect

    def _color_gate(self, image_embeds: Any, n: int):
        import numpy as np

        if not self.color_feature_k:
            return np.ones(n, dtype=bool), None
        own_color_feature_text = self.anchored_features[self.color_feature_k[0]].split("'s ", 1)[-1]
        own_color_word = own_color_feature_text.rsplit(" color", 1)[0]
        is_anchored = self.anchored_features[self.color_feature_k[0]].startswith(f"a {self.class_name}'s ")
        if is_anchored:
            prompts = [f"a {self.class_name}'s {own_color_word} color"] + [
                f"a {self.class_name}'s {c} color" for c in COLOR_COMPETITOR_WORDS
            ]
        else:
            prompts = [f"{own_color_word} color"] + [f"{c} color" for c in COLOR_COMPETITOR_WORDS]
        sim = image_embeds @ self.engine.embed_texts(prompts).T
        # 2026-09-16 실측 리허설 반영: "1등"이 아니라 "1등과의 차이가
        # color_gate_tolerance 이내"면 통과 -- tolerance=0(기본값)이면 own
        # color가 정확히 1등일 때만 통과해 기존 동작과 같다.
        own_sim = sim[:, 0]
        best_sim = sim.max(axis=1)
        passed = own_sim >= best_sim - self.color_gate_tolerance

        def detail(i: int) -> dict:
            winner = prompts[int(sim[i].argmax())]
            return {
                "passed": bool(passed[i]),
                "winning_color": winner,
                "tolerance": self.color_gate_tolerance,
                "margin_from_winner": round(float(own_sim[i] - best_sim[i]), 4),
                "candidates": {p: round(float(sim[i, k]), 4) for k, p in enumerate(prompts)},
            }

        return passed, detail

    def _shape_gate(self, image_embeds: Any, n: int):
        import numpy as np

        if not self.shape_cfg or self.shape_embeds is None:
            return np.ones(n, dtype=bool), None
        prompts = self.shape_cfg["positive_prompts"] + self.shape_cfg["negative_prompts"]
        n_positive = len(self.shape_cfg["positive_prompts"])
        sim = image_embeds @ self.shape_embeds.T
        best_positive = sim[:, :n_positive].max(axis=1)
        best_negative = sim[:, n_positive:].max(axis=1)
        # 2026-09-16 실측 리허설 반영: "positive 진영이 1등"이 아니라 "best
        # positive가 best negative보다 tolerance 이상 낮지만 않으면" 통과 --
        # tolerance=0(기본값)이면 기존 top-1 판정과 동일하다.
        passed = best_positive >= best_negative - self.shape_gate_tolerance

        def detail(i: int) -> dict:
            winner = prompts[int(sim[i].argmax())]
            return {
                "passed": bool(passed[i]),
                "winning_shape": winner,
                "tolerance": self.shape_gate_tolerance,
                "margin_positive_minus_negative": round(float(best_positive[i] - best_negative[i]), 4),
                "candidates": {p: round(float(sim[i, k]), 4) for k, p in enumerate(prompts)},
            }

        return passed, detail

    def _reference_image_gate(self, image_embeds: Any, n: int):
        import numpy as np

        if self.ref_sim_min is None or self.ref_image_embed is None:
            return np.ones(n, dtype=bool), None
        sim = image_embeds @ self.ref_image_embed.T
        passed = sim[:, 0] >= self.ref_sim_min

        def detail(i: int) -> dict:
            return {"passed": bool(passed[i]), "similarity": round(float(sim[i, 0]), 4),
                    "threshold_min": self.ref_sim_min}

        return passed, detail

    def _hue_gate(self, crops: list[Any], n: int):
        import numpy as np

        if self.hue_cfg is None:
            return np.ones(n, dtype=bool), None
        values = np.array([_median_hue(c) for c in crops])
        passed = np.ones(n, dtype=bool)
        if "min_median_hue" in self.hue_cfg:
            passed &= values >= self.hue_cfg["min_median_hue"]
        if "max_median_hue" in self.hue_cfg:
            passed &= values <= self.hue_cfg["max_median_hue"]

        def detail(i: int) -> dict:
            return {
                "passed": bool(passed[i]),
                "median_hue": round(float(values[i]), 1),
                **{k: v for k, v in self.hue_cfg.items() if k in ("min_median_hue", "max_median_hue")},
            }

        return passed, detail

    def _saturation_gate(self, crops: list[Any], n: int):
        import numpy as np

        if self.saturation_cfg is None:
            return np.ones(n, dtype=bool), None
        values = np.array([_median_saturation(c) for c in crops])
        passed = np.ones(n, dtype=bool)
        if "min_saturation" in self.saturation_cfg:
            passed &= values >= self.saturation_cfg["min_saturation"]
        if "max_saturation" in self.saturation_cfg:
            passed &= values <= self.saturation_cfg["max_saturation"]

        def detail(i: int) -> dict:
            return {
                "passed": bool(passed[i]),
                "median_saturation": round(float(values[i]), 1),
                **{k: v for k, v in self.saturation_cfg.items() if k in ("min_saturation", "max_saturation")},
            }

        return passed, detail
