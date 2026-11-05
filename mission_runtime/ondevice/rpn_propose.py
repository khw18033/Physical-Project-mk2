"""Class-agnostic region proposal on-device (AI-B-10, AI-N-01 sibling capability).

implements: AI-B-10, AI-E-01, AI-B-09, AI-C-05

2026-09-16 door/pedestal 랜드마크 통합 설계(계획 문서 "데모 파이프라인의
mission_runtime 통합 설계" 참고): 검증된 PoC(demo/test/class_finder_service.py
의 `_DeploymentYoloProposer`)에서 후보제안(RPN) 부분만 온디바이스(말단) 계층으로
분리한다. 의미 분류(어떤 클래스인가)는 여기서 하지 않는다 — 그건 엣지의 CLIP/OVD/
FastSAM provider들이 이 결과를 받아 하는 일이다(perception/object_record.py로
융합). 이 provider는 "여기 뭔가 있을 수 있다"는 class-agnostic 후보 박스만 낸다.

**실행 위치 이식성(사용자 확정 설계)**: 지금 로봇(Go1)/라즈베리파이(pi7)에는 AI
연산을 돌릴 확인된 하드웨어가 없어(HW 브랜치 `pi/robot/go1_link.py` 확인 결과
Go1은 MQTT 구독 전용 릴레이일 뿐 온보드 연산이 없다) 당분간 엣지 박스의 CPU에서
이 코드를 그대로 돌린다. 그래서 `device`를 코드에 하드코딩하지 않고:
  1) 생성자 인자로 명시적으로 받거나,
  2) 안 주면 `providers/compute.py::discover_node_tags()`로 이 프로세스가 실행
     중인 노드를 실측 프로브해 `compute.gpu` 태그가 있으면 "cuda", 없으면 "cpu"를
     쓴다.
실제 로봇 하드웨어가 생기면 `git pull` + 배포 설정(`CompatibilityProfile`/모델
config 파일)만 바꿔서 이식하면 되고, 이 모듈 자체는 코드 변경이 필요 없다.

`ultralytics`는 모듈 최상단이 아니라 생성자 안에서 지연 import한다(AI-C-05:
이 optional 의존성이 없는 노드도 이 모듈 자체는 계속 import할 수 있어야 한다 —
`perception/open_vocabulary.py::OwlVitPerceptionProvider`와 동일 패턴).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mission_runtime.perception.detection import PerceptionProvider, PerceptionResult

#: PoC(YOLO_CONF/YOLO_TOPN, demo/test/class_finder_service.py)에서 실측 확정된
#: 기본값 — 후보를 최대한 넓게 뽑고(낮은 conf) 이후 엣지의 CLIP/OVD가 좁힌다.
DEFAULT_CONF = 1e-4
DEFAULT_IOU = 0.50
DEFAULT_TOP_N = 1000

#: class-agnostic 후보라는 것을 명시하는 label — 실제 의미 분류는 엣지가 한다.
PROPOSAL_LABEL = "region_proposal"


#: 이 프로세스가 가속기를 **쓰지 않기로** 선언하는 환경변수. 다른 세션이 GPU 를
#: 점유한 동안 같은 기계에서 통합 작업을 계속할 때 쓴다.
#:
#: 태그 탐색(`discover_node_tags`)은 **건드리지 않는다.** 가속기가 있는데 태그에
#: 없다고 적으면 그것은 배치 판정에 들어가는 거짓이 되고, "이 노드에 GPU 가 없다"
#: 와 "지금 쓰지 않기로 했다" 는 다른 사실이다. 그래서 이 변수는 **고르는 쪽**만
#: 바꾼다 — 노드가 무엇을 할 수 있는지는 그대로 보고된다.
#:
#: `CUDA_VISIBLE_DEVICES=""` 로 숨기는 쪽을 쓰지 않는 이유: 이 기계에서 그렇게 하면
#: NVBLAS 가 CPU BLAS 를 가로채 **예외 없이 틀린 값**을 낸다(local/demo/CLAUDE.md
#: 가 실측으로 기록). 조용히 틀린 수는 느린 수보다 나쁘다.
NO_GPU_ENV = "MISSION_RUNTIME_NO_GPU"


def gpu_use_declined() -> bool:
    """이 프로세스가 가속기를 쓰지 않기로 선언했는가."""
    import os

    return os.environ.get(NO_GPU_ENV, "").strip().lower() in {"1", "true", "yes"}


def default_device() -> str:
    """이 프로세스가 **기본으로 쓸** 가속기. 선언·태그를 함께 반영한 결과다.

    공개 함수인 이유: 설치 자가 점검(`tools/preflight.py`)과 운영 화면이 "지금
    무엇으로 돌 것인가" 를 물어야 하고, 그 답을 각자 다시 유도하면 provider 가
    실제로 고르는 것과 화면이 말하는 것이 갈린다.
    """
    return _resolve_device(None)


def _resolve_device(device: str | None) -> str:
    """`device`가 명시되지 않으면 이 노드를 실측 프로브해서 고른다.

    GPU가 없다고 실패하지 않는다(금지 사항: GPU/NPU가 항상 존재한다고 가정하지
    않는다) — 태그가 없으면 그냥 "cpu"다.

    명시한 device 는 그대로 쓴다. 명시하지 않았고 이 프로세스가 가속기를 쓰지
    않기로 선언했으면 "cpu" 다 — 명시를 덮지 않는 이유는 그것이 호출자의 결정이고,
    선언은 **기본값에 대한 제약**이기 때문이다.
    """
    if device is not None:
        return device
    if gpu_use_declined():
        return "cpu"
    from mission_runtime.providers.compute import TAG_GPU, discover_node_tags

    return "cuda" if TAG_GPU in discover_node_tags() else "cpu"


class RpnProposalProvider:
    """YOLO 기반 class-agnostic 후보 제안(Region Proposal Network 역할).

    `perception.detect`(AI-S-06/`object_record.py`의 필수 근거 소스) capability
    kind로 등록되는 것을 전제로 설계됐다 — 여기서 나온 박스는 그 자체로 확정
    아니고, 엣지의 CLIP dictionary/GroundingDINO/YOLO-World/FastSAM provider들이
    같은 프레임에 대해 독립적으로 만든 의미 근거(Evidence)와 함께
    `perception.object_record.ProgressiveRecordBuilder`에 들어가 융합된다.
    """

    def __init__(
        self,
        weights_path: str | Path,
        *,
        device: str | None = None,
        conf: float = DEFAULT_CONF,
        iou: float = DEFAULT_IOU,
        top_n: int = DEFAULT_TOP_N,
    ) -> None:
        self.weights_path = Path(weights_path)
        self.device = _resolve_device(device)
        self.conf = conf
        self.iou = iou
        self.top_n = top_n
        self._model: Any | None = None

    def is_available(self) -> bool:
        return self.weights_path.exists()

    def _load(self) -> Any:
        if self._model is None:
            from ultralytics import YOLO

            model = YOLO(str(self.weights_path))
            model.to(self.device)
            self._model = model
        return self._model

    def detect(self, frame: Any) -> list[PerceptionResult]:
        """프레임 하나에서 class-agnostic 후보 박스를 낸다.

        점수는 YOLO의 objectness/class confidence를 그대로 쓰되, label은
        의미 없이 `PROPOSAL_LABEL` 고정값이다 — "이게 무엇인지"는 여기서
        정하지 않는다.
        """
        if not self.is_available():
            return []
        model = self._load()
        results = model.predict(
            frame,
            conf=self.conf,
            iou=self.iou,
            device=self.device,
            max_det=self.top_n,
            verbose=False,
        )
        out: list[PerceptionResult] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            xyxy = boxes.xyxy.tolist()
            confs = boxes.conf.tolist()
            for (x1, y1, x2, y2), score in zip(xyxy, confs):
                out.append(
                    PerceptionResult(
                        box=(float(x1), float(y1), float(x2), float(y2)),
                        label=PROPOSAL_LABEL,
                        confidence=float(score),
                    )
                )
        return out
