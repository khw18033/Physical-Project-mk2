"""FastSAM-backed class-agnostic 박스/마스크 provider (AI-E-01, AI-E-04).

implements: AI-E-01, AI-B-09, AI-C-11

검증된 PoC(demo/test/class_finder_service.py의 `FastSamProvider`)를 이
프레임워크의 provider 계약으로 옮긴다. PoC 주석 그대로: "마스크 전용(의미
없음) -- 의미 투표에 참여하지 않고 기하만 보강한다". FastSAM은 어떤 클래스인지
전혀 모른다 — 순수 기하(박스) 근거만 내고, `ondevice/rpn_propose.py`의
`PROPOSAL_LABEL`과 동일한 관례로 고정된 비-의미 라벨을 붙인다(둘 다 "이게
무엇인지"를 정하지 않는 class-agnostic 근거라는 같은 이유이므로, 별도 문자열을
새로 만들지 않고 그 상수를 그대로 재사용한다).

무거운 세그멘테이션 모델이라 AI-E-04("선택형 보조 기능")가 요구하는 대로 구역
엣지에서만 선택적으로 실행한다 — `rpn_propose.py`가 말단(로봇)에서 가볍게 돌리는
class-agnostic 후보 제안(RPN)과 대비된다(둘 다 class-agnostic이지만 실행 위치와
비용이 다르다).

`ultralytics`는 모듈 최상단이 아니라 생성자 안에서 지연 import한다(AI-C-11).
`is_available()`은 가중치 파일 존재 여부만 보고(`rpn_propose.py`와 동일 관례),
`detect()`는 `is_available()`이 False면 로드를 시도하지 않고 빈 리스트를
반환한다.

device는 코드에 하드코딩하지 않는다 — `ondevice/rpn_propose.py`의
`_resolve_device` 패턴을 그대로 재사용한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from perception_framework.ondevice.rpn_propose import PROPOSAL_LABEL, _resolve_device
from perception_framework.perception.detection import PerceptionProvider, PerceptionResult

#: FastSAM은 마스크/박스 전용 근거이고 의미 분류에 참여하지 않는다 --
#: `rpn_propose.PROPOSAL_LABEL`과 동일한 class-agnostic 관례를 그대로 재사용한다.
SEGMENT_ONLY_LABEL = PROPOSAL_LABEL


class FastSamPerceptionProvider:
    """FastSAM 기반 class-agnostic 박스 provider (마스크 전용, 의미 없음).

    `class_names`를 받지 않는다 — 어떤 프레임을 넣어도 동일하게 "여기 뭔가
    있을 수 있다"는 기하 근거만 낸다. 의미 분류는 GroundingDINO/YOLO-World/CLIP
    dictionary provider가 담당하고, 이 provider의 결과는 상위
    `perception.object_record.ProgressiveRecordBuilder`에서 기하 보강 근거로만
    쓰인다.
    """

    def __init__(self, weights_path: str | Path, *, device: str | None = None) -> None:
        self.weights_path = Path(weights_path)
        self.device = _resolve_device(device)
        self._model: Any | None = None

    def is_available(self) -> bool:
        return self.weights_path.exists()

    def _load(self) -> Any:
        if self._model is None:
            from ultralytics import FastSAM

            self._model = FastSAM(str(self.weights_path))
        return self._model

    def detect(self, frame: Any) -> list[PerceptionResult]:
        """프레임 하나에서 class-agnostic 박스를 낸다.

        가중치가 없으면(`is_available()` False) 로드를 시도하지 않고 빈
        리스트를 반환한다 — 이 선택 기능의 부재가 다른 capability를 막아서는
        안 된다(AI-C-05). 추론 해상도와 원본 프레임 해상도가 다를 수 있어
        (`res.orig_shape`), 반환 전에 원본 좌표계로 재투영한다(PoC와 동일 로직).
        """
        if not self.is_available():
            return []
        model = self._load()
        h, w = frame.shape[:2]
        results = model.predict(frame, device=self.device, verbose=False)
        res = results[0]
        boxes = getattr(res, "boxes", None)
        out: list[PerceptionResult] = []
        if boxes is None:
            return out
        infer_h, infer_w = res.orig_shape if hasattr(res, "orig_shape") else (h, w)
        sx, sy = w / infer_w, h / infer_h
        for b in boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            out.append(
                PerceptionResult(
                    box=(x1 * sx, y1 * sy, x2 * sx, y2 * sy),
                    label=SEGMENT_ONLY_LABEL,
                    confidence=float(b.conf[0]),
                )
            )
        return out
