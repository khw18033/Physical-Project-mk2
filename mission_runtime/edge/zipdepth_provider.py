"""ZipDepth ONNX monocular depth provider — the real runtime behind `DepthProvider`.

implements: AI-B-08 (실행 provider 추상화), AI-E-02, AI-C-05 (선택 기능 결손은 축소)
관련: AI-B-10 (말단 경량), AI-C-02, AI-B-01

`edge/depth_contract.py` 의 `DepthProvider` 자리를 **실제 모델**로 채운다. 이
모듈이 하는 일은 셋뿐이다 — 전처리, 세션 실행, `DepthField` 로 감싸기. 상대값을
미터로 바꾸는 일은 여기서 하지 않는다(보정 프로파일의 몫이다).

이 모델이 내는 것과 내지 않는 것
--------------------------------
낸다: **affine-invariant 역깊이** 한 장. 값이 클수록 가깝다.
내지 않는다: 미터 스케일, 내부 파라미터(fx·cx). 그래서 `intrinsics=None` 이고,
소비자는 방위각을 각도가 아니라 `unmeasured_no_intrinsics` 로 받는다.

`onnxruntime` 은 모듈 최상단이 아니라 **생성자 안에서 지연 import** 한다 — 이
선택 의존성이 없는 노드도 이 모듈 자체는 계속 import 할 수 있어야 한다(AI-C-05,
`edge/yolo_world_provider.py` 와 같은 관례). `is_available()` 은 가중치 파일
존재만 보고, `estimate()` 는 가중치가 없으면 로드를 시도하지 않는다.

실행 위치를 코드에 박지 않는다
------------------------------
`providers` 인자를 주지 않으면 onnxruntime 이 그 기계에서 쓸 수 있는 것을 쓴다.
CUDA 를 명시했는데 없으면 **조용히 CPU 로 떨어지지 않고** 그 사실이 `health()` 에
남는다 — 조용한 강등은 "GPU 로 쟀다" 는 거짓 기록을 만든다.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Sequence

from mission_runtime.edge.depth_contract import (
    DEPTH_SPACE_AFFINE_INVERSE,
    DepthField,
)

#: 이 가중치들이 받는 정사각 입력 변 길이. 파일 이름이 아니라 **세션이** 정한다 —
#: 아래 `_input_side()` 가 ONNX 그래프에서 읽는다.
DEFAULT_PROVIDERS: tuple[str, ...] = ("CPUExecutionProvider",)


class ZipDepthProvider:
    """ZipDepth ONNX 한 장을 `DepthField` 로 감싼다."""

    depth_space = DEPTH_SPACE_AFFINE_INVERSE

    def __init__(self, weights_path: str | Path, *,
                 providers: Sequence[str] | None = None,
                 crop_box: tuple[int, int, int, int] | None = None) -> None:
        self.weights_path = Path(weights_path)
        self.providers = tuple(providers or DEFAULT_PROVIDERS)
        #: 추론 전에 잘라낼 **원본 좌표** 박스. 테두리를 자르는 배치가 있고, 그
        #: 사실이 `DepthField.crop_box` 로 함께 나가야 박스 환산이 맞는다.
        self.crop_box = crop_box
        self._session: Any | None = None
        self._side: int | None = None
        self._load_error: str = ""

    # ── capability ──────────────────────────────────────────────────────────

    @property
    def provider_key(self) -> str:
        """보정 프로파일이 묶이는 키. **가중치 이름이 들어간다** — 가중치가 바뀌면
        다른 구성이고, 다른 구성의 보정을 물려받지 않는다(AI-B-01)."""
        runtime = "cuda" if any("CUDA" in p for p in self.providers) else "cpu"
        return f"{self.weights_path.name}.{runtime}"

    def is_available(self) -> bool:
        return self.weights_path.exists()

    def health(self) -> dict:
        """무엇을 못 하는지가 드러나는 모양으로 낸다."""
        return {
            "provider_key": self.provider_key,
            "depth_space": self.depth_space,
            "weights_present": self.is_available(),
            "loaded": self._session is not None,
            "requested_providers": list(self.providers),
            "active_providers": (list(self._session.get_providers())
                                 if self._session is not None else []),
            # 이 provider 가 **내주지 않는** 출력. 소비자가 요구하기 전에 알 수 있다.
            "missing_outputs": ["intrinsics_fx_cx", "metric_scale_calibrated"],
            "load_error": self._load_error,
        }

    # ── 실행 ────────────────────────────────────────────────────────────────

    def _load(self):
        if self._session is None:
            import onnxruntime as ort

            self._session = ort.InferenceSession(str(self.weights_path),
                                                 providers=list(self.providers))
            self._side = _input_side(self._session)
        return self._session

    def estimate(self, frame: Any) -> DepthField | None:
        """BGR 프레임 한 장 → 역깊이 한 장. 가중치가 없으면 **None** 이다.

        `None` 은 "깊이가 0" 이 아니라 "이 선택 기능이 이 노드에 없다" 이고,
        소비자는 그때 거리 없이 영상 좌표 근거만 유지한다(AI-C-05).
        """
        if not self.is_available():
            self._load_error = f"weights_missing:{self.weights_path}"
            return None
        import cv2
        import numpy as np

        session = self._load()
        side = int(self._side or 0)
        if side <= 0:
            return None

        frame_h, frame_w = frame.shape[0], frame.shape[1]
        source = frame
        if self.crop_box is not None:
            x1, y1, x2, y2 = self.crop_box
            source = frame[y1:y2, x1:x2]
        source_h, source_w = source.shape[0], source.shape[1]

        rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (side, side)).astype(np.float32) / 255.0
        batch = resized.transpose(2, 0, 1)[None]

        started = time.perf_counter()
        values = session.run(None, {session.get_inputs()[0].name: batch})[0][0, 0]
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        return DepthField(
            values=values,
            depth_space=self.depth_space,
            provider_key=self.provider_key,
            source_wh=(source_w, source_h),
            infer_wh=(values.shape[1], values.shape[0]),
            # 이 모델은 내부 파라미터를 내주지 않는다. 0 이나 추정치를 넣지 않는다.
            intrinsics=None,
            infer_ms=round(elapsed_ms, 2),
            crop_box=self.crop_box,
            frame_wh=(frame_w, frame_h),
        )


def _input_side(session) -> int:
    """입력 변 길이를 **그래프에서 읽는다.** 파일 이름에서 숫자를 뽑지 않는다 —
    이름이 내용과 어긋난 가중치가 하나 섞이면 그때부터 전부 조용히 틀린다."""
    shape = session.get_inputs()[0].shape
    side = shape[-1]
    return int(side) if isinstance(side, int) else 0
