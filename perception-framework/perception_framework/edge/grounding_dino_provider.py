"""GroundingDINO(zero-shot open-vocabulary detector)-backed 인지 provider (AI-E-01, AI-E-04).

implements: AI-E-01, AI-B-09, AI-C-11

검증된 PoC(demo/test/class_finder_service.py의 `GroundingDinoProvider`)를 이
프레임워크의 provider 계약으로 옮긴다. GroundingDINO는 무거운 zero-shot
open-vocabulary detector라 AI-E-04("선택형 보조 기능")가 요구하는 대로 구역
엣지에서만 선택적으로 실행한다 — `ondevice/rpn_propose.py`가 말단(로봇)에서
가볍게 돌리는 class-agnostic 후보 제안(RPN)과 대비된다.

PoC와의 인터페이스 차이: PoC의 `detect(bgr, class_names)`는 호출마다 어휘를
바꿀 수 있었지만, 이 프레임워크의 `PerceptionProvider.detect(frame)`
(`perception/detection.py`)는 인자가 frame 하나뿐이다 — 그래서 `class_names`는
생성자 인자가 된다(`open_vocabulary.py::OwlVitPerceptionProvider`가 `vocab`을
생성자에서 한 번만 받는 것과 동일 패턴). 어휘를 바꾸려면 새 provider 인스턴스를
만든다.

`transformers`/`torch`/`cv2`는 모듈 최상단이 아니라 생성자/메서드 안에서 지연
import한다(AI-C-11: 이 optional 의존성이 없는 노드도 이 모듈 자체는 계속
import할 수 있어야 다른 capability가 함께 죽지 않는다 — `rpn_propose.py`/
`open_vocabulary.py`와 동일 패턴). 이 모델은 로컬 가중치 파일이 아니라
HuggingFace Hub에서 최초 사용 시 다운로드되므로(model_id=
"IDEA-Research/grounding-dino-tiny"), `is_available()`는 다운로드를 유발하지
않는 가벼운 import 가능 여부 확인에 한정한다. 실제 모델 로드/다운로드 실패는
`detect()`가 흡수해 빈 결과를 반환한다 — 폐쇄망 등 외부 연결이 없는 배치에서도
이 선택 기능의 실패가 다른 기능을 막아서는 안 된다(AI-C-05, AI-C-16).

device는 코드에 하드코딩하지 않는다 — `ondevice/rpn_propose.py`의
`_resolve_device` 패턴을 그대로 재사용한다(명시적으로 주지 않으면
`providers/compute.py::discover_node_tags()`가 이 노드를 실측 프로브해
`compute.gpu` 태그가 있으면 "cuda", 없으면 "cpu").
"""

from __future__ import annotations

from typing import Any

from perception_framework.ondevice.rpn_propose import _resolve_device
from perception_framework.perception.detection import PerceptionProvider, PerceptionResult

GROUNDING_DINO_MODEL_ID = "IDEA-Research/grounding-dino-tiny"
#: PoC(demo/test/class_finder_service.py)에서 실측 확정된 기본 임계값.
DEFAULT_BOX_THRESHOLD = 0.15
DEFAULT_TEXT_THRESHOLD = 0.15


class GroundingDinoPerceptionProvider:
    """GroundingDINO 기반 open-vocabulary 인지 provider.

    `class_names`는 생성자에서 한 번 고정되고 `detect()`는 그 어휘에 대해서만
    매칭한다 — 이 결과도 확정 분류가 아니라 텍스트-이미지 grounding 근거이며
    (`open_vocabulary.py`의 `OpenVocabularyPerceptionResult`와 동일한 성격),
    상위 `perception.object_record.ProgressiveRecordBuilder`가 다른 provider의
    근거와 함께 융합한다.
    """

    def __init__(
        self,
        class_names: list[str],
        *,
        model_id: str = GROUNDING_DINO_MODEL_ID,
        device: str | None = None,
        box_threshold: float = DEFAULT_BOX_THRESHOLD,
        text_threshold: float = DEFAULT_TEXT_THRESHOLD,
    ) -> None:
        if not class_names:
            raise ValueError("class_names must be non-empty — an empty vocabulary can never match anything")
        self.class_names = list(class_names)
        self.model_id = model_id
        self.device = _resolve_device(device)
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self._processor: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._load_failed = False

    def is_available(self) -> bool:
        """`transformers`가 import 가능한지만 확인한다 — HF Hub 다운로드를
        유발하지 않는 가벼운 체크다. 모델 실제 로드는 최초 `detect()` 호출 시
        지연 수행되고, 그 시점의 실패(예: 네트워크 없음)는 `_load_failed`로
        기록되어 이후 `is_available()`도 False를 반환한다."""
        if self._load_failed:
            return False
        try:
            import transformers  # noqa: F401
        except Exception:
            return False
        return True

    def _load(self) -> tuple[Any, Any]:
        if self._model is None:
            import torch
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

            self._processor = AutoProcessor.from_pretrained(self.model_id)
            self._model = (
                AutoModelForZeroShotObjectDetection.from_pretrained(self.model_id).to(self.device).eval()
            )
            self._torch = torch
        return self._processor, self._model

    def detect(self, frame: Any) -> list[PerceptionResult]:
        """프레임 하나에서 생성자에 고정된 어휘로 open-vocabulary 검출을 수행한다.

        모델 로드(최초 1회 HF Hub 다운로드 포함)가 실패하면 예외를 올리지
        않고 빈 결과를 반환한다 — 이 선택 기능의 부재/실패가 다른 capability를
        막아서는 안 된다(AI-C-05).
        """
        if not self.is_available():
            return []
        try:
            processor, model = self._load()
        except Exception:
            self._load_failed = True
            self._model = None
            self._processor = None
            return []

        import cv2

        torch = self._torch
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        text = ". ".join(c.lower() for c in self.class_names) + "."
        inputs = processor(images=rgb, text=text, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = model(**inputs)
        h, w = frame.shape[:2]
        result = processor.post_process_grounded_object_detection(
            outputs,
            input_ids=inputs["input_ids"],
            threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            target_sizes=[(h, w)],
        )[0]
        labels = result.get("text_labels", result.get("labels"))

        out: list[PerceptionResult] = []
        for box, score, label in zip(result["boxes"], result["scores"], labels):
            x1, y1, x2, y2 = (float(v) for v in box.tolist())
            out.append(
                PerceptionResult(
                    box=(x1, y1, x2, y2),
                    label=label,
                    confidence=float(score),
                )
            )
        return out
