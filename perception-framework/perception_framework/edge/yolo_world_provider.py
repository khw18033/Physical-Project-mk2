"""YOLO-World-backed open-vocabulary 인지 provider (AI-E-01, AI-E-04).

implements: AI-E-01, AI-B-09, AI-C-11

검증된 PoC(demo/test/class_finder_service.py의 `YoloWorldProvider`)를 이
프레임워크의 provider 계약으로 옮긴다. YOLO-World는 GroundingDINO보다 가볍지만
여전히 open-vocabulary 재추론(어휘가 바뀔 때마다 `set_classes` 재호출)이 필요한
선택 기능이라(AI-E-04) 구역 엣지에서 실행한다 — 말단(로봇)의 경량 실행 경계
(AI-B-10)와는 별도 계층이다.

PoC와의 인터페이스 차이: PoC의 `detect(bgr, class_names)`는 호출마다 어휘를
바꿀 수 있었지만, 이 프레임워크의 `PerceptionProvider.detect(frame)`
(`perception/detection.py`)는 인자가 frame 하나뿐이다 — 그래서 `class_names`는
생성자 인자가 되고 `set_classes()`는 모델 최초 로드 시 한 번만 호출한다
(`open_vocabulary.py::OwlVitPerceptionProvider`가 `vocab`을 생성자에서 한 번만
받는 것과 동일 패턴). 어휘를 바꾸려면 새 provider 인스턴스를 만든다.

`ultralytics`는 모듈 최상단이 아니라 생성자 안에서 지연 import한다(AI-C-11:
이 optional 의존성이 없는 노드도 이 모듈 자체는 계속 import할 수 있어야 한다 —
`rpn_propose.py`와 동일 패턴). `is_available()`은 가중치 파일 존재 여부만 보고
(`rpn_propose.RpnProposalProvider.is_available`와 동일 관례), `detect()`는
`is_available()`이 False면 로드를 시도하지 않고 빈 리스트를 반환한다.

device는 코드에 하드코딩하지 않는다 — `ondevice/rpn_propose.py`의
`_resolve_device` 패턴을 그대로 재사용한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from perception_framework.ondevice.rpn_propose import _resolve_device
from perception_framework.perception.detection import PerceptionProvider, PerceptionResult

#: PoC(YOLO_WORLD_CONF, demo/test/class_finder_service.py)에서 실측 확정된 기본값.
DEFAULT_CONF = 0.05


class YoloWorldPerceptionProvider:
    """YOLO-World 기반 open-vocabulary 인지 provider.

    `class_names`는 생성자에서 한 번 고정된다 — 이 결과도 확정 분류가 아니라
    open-vocabulary grounding 근거이며, 상위
    `perception.object_record.ProgressiveRecordBuilder`가 다른 provider의
    근거와 함께 융합한다.
    """

    def __init__(
        self,
        class_names: list[str],
        weights_path: str | Path,
        *,
        device: str | None = None,
        conf: float = DEFAULT_CONF,
    ) -> None:
        if not class_names:
            raise ValueError("class_names must be non-empty — an empty vocabulary can never match anything")
        self.class_names = list(class_names)
        self.weights_path = Path(weights_path)
        self.device = _resolve_device(device)
        self.conf = conf
        self._model: Any | None = None

    def is_available(self) -> bool:
        return self.weights_path.exists()

    def _load(self) -> Any:
        if self._model is None:
            from ultralytics import YOLO

            model = YOLO(str(self.weights_path))
            model.to(self.device)
            model.set_classes(self.class_names)
            self._model = model
        return self._model

    def detect(self, frame: Any) -> list[PerceptionResult]:
        """프레임 하나에서 생성자에 고정된 어휘로 open-vocabulary 검출을 수행한다.

        가중치가 없으면(`is_available()` False) 로드를 시도하지 않고 빈
        리스트를 반환한다 — 이 선택 기능의 부재가 다른 capability를 막아서는
        안 된다(AI-C-05).
        """
        if not self.is_available():
            return []
        model = self._load()
        results = model.predict(frame, conf=self.conf, device=self.device, verbose=False)
        res = results[0]
        boxes = getattr(res, "boxes", None)
        out: list[PerceptionResult] = []
        if boxes is None:
            return out
        for b in boxes:
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            out.append(
                PerceptionResult(
                    box=(x1, y1, x2, y2),
                    label=res.names[int(b.cls[0])],
                    confidence=float(b.conf[0]),
                )
            )
        return out
