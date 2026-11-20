"""YOLOE 기반 zero-shot 인지 provider — 프롬프트 어휘와 **프롬프트 없는** 두 모드.

implements: AI-E-01, AI-B-09, AI-C-05
관련: AI-E-04(선택형 보조 기능), AI-S-04(미확인 객체), AI-L-02(미검증 추론을
      확정 정답으로 승격하지 않는다), AI-C-05(선택 기능 결손은 축소), AI-C-16(폐쇄망)

`edge/yolo_world_provider.py`·`edge/grounding_dino_provider.py` 와 같은 자리를
채운다 — 세 번째 zero-shot 탐지기 계열이다. 관례도 그 둘을 그대로 따른다:
`ultralytics` 는 모듈 최상단이 아니라 **생성자/로드 안에서 지연 import** 하고
(AI-C-05: 이 optional 의존성이 없는 노드도 이 모듈 자체는 계속 import 할 수 있어야
한다), `is_available()` 은 **가중치 파일 존재만** 보며, `detect()` 는 가중치가
없으면 로드를 시도하지 않고 빈 리스트를 반환한다. device 는 코드에 박지 않고
`ondevice/rpn_propose.py::_resolve_device` 를 재사용한다.

두 모드가 **같은 계약이 아니다**
--------------------------------
`yoloe-11s-seg.pt` / `yoloe-11l-seg.pt`
    텍스트 프롬프트 가중치. `set_classes(names, get_text_pe(names))` 로 어휘를
    심는다. YOLO-World 와 같은 축이지만 **임베딩을 호출자가 넘긴다**는 점이
    다르다 — `get_text_pe` 가 MobileCLIP 텍스트 인코더(`mobileclip_blt.ts`,
    572 MB)를 따로 요구하고, 그 자산이 없으면 ultralytics 가 공개 인터넷에서
    받으려 한다. 폐쇄망 배치에서 이것은 **배치 전에 드러나야 하는 사실**이라
    `config/detector_characteristics.example.json` 에 선언으로 적는다(AI-C-16).
`yoloe-11s-seg-pf.pt` (pf = prompt-free)
    **어휘를 주지 않는다.** 모델이 들고 있는 4585개 내장 범주로 검출한다.
    `set_classes` 는 ultralytics 가 AssertionError 로 거절한다("Prompt-free model
    does not support setting classes") — 즉 "프롬프트를 받지 않는다"는 것이 우리
    선언이 아니라 **모델이 강제하는 계약**이다.

프롬프트 없는 라벨을 어휘 매칭과 섞지 않는다
--------------------------------------------
prompt-free 결과의 이름은 **운영자가 고른 어휘에서 온 것이 아니다.** 그래서 그
이름을 그대로 내보내면 하류(`perception/obstacle_taxonomy.py::classify`)에서
운영자가 고른 어휘의 매칭과 **구분이 불가능해진다** — 같은 글자 `chair` 가 한쪽은
"운영자가 찾으라고 한 것", 다른 쪽은 "모델이 4585개 중에서 떠올린 것"이 된다.
그 둘은 같은 근거가 아니다.

실측이 이 구분을 요구한다. 같은 실물 스캔(`20260910-134818_rot8`, 8프레임)에서
prompt-free 가 낸 이름은 92종이고 그 중 `nightclub` 0.62, `sea ice` 0.61,
`science museum` 0.60, `summer evening` 0.32, `martial arts gym` 0.29 처럼
**장면·분위기 범주가 실제 물체보다 높은 점수**를 받는다. 실내 로봇 스캔에
`sea ice` 가 0.61 로 올라오는 것을 어휘 매칭과 같은 칸에 담으면 임계값도
의미를 잃는다.

그래서 prompt-free 라벨에는 `PROMPT_FREE_LABEL_PREFIX` 를 붙여 **이름 공간을
가른다**. 결과:

* `classify("promptfree:sea ice", vocabulary="zeroshot")` 는 접두사 때문에 어떤
  어휘 키와도 같아질 수 없고 `UNKNOWN_OBSTACLE` + `reason="unmapped_label"` +
  `label_status="hypothesis"` 가 된다 — 미확인 객체 경로(AI-S-04)와 학습 후보
  경로(AI-L-01)로 흐르는, 이름 없는 관측에 **원래 맞는 자리**다.
* 점수가 아무리 높아도 확정으로 승격되지 않는다(AI-L-02).
* 원래 이름은 접두사 뒤에 **보존된다.** 일부러 들여다보려는 소비자는
  `strip_prompt_free_prefix()` 를 거친다 — 사고가 아니라 **명시적 행위**가 된다.

왜 `PerceptionResult` 에 칸을 더하지 않는가: 그 자료형은 모든 인지 provider 가
공유하는 계약이고(`perception/detection.py`), 칸을 더하면 기존 provider 전부가
조용히 기본값("어휘에서 왔다")을 갖게 된다. 조용한 기본값은 이 구분이 막으려는
바로 그 혼동을 만든다. 접두사는 선언돼 있고, 되돌릴 수 있고, **틀리면 모르는
쪽으로 틀린다**(fail-safe).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mission_runtime.ondevice.rpn_propose import _resolve_device
from mission_runtime.perception.detection import PerceptionProvider, PerceptionResult

#: 어휘를 주는 모드. 자유 문자열 태그다 — 벤더 enum 을 만들지 않는다(원칙 #1).
PROMPT_MODE_TEXT = "text_prompted"
#: 어휘를 **주지 않는** 모드. 모델 내장 범주로 검출한다.
PROMPT_MODE_FREE = "prompt_free"

#: prompt-free 라벨의 이름 공간 접두사. 어휘 키와 절대 같아지지 않게 하는 것이
#: 목적이고, 값 자체는 하류가 문자열로만 다룬다(분기 대상이 아니다).
PROMPT_FREE_LABEL_PREFIX = "promptfree:"

#: 라벨이 어느 이름 공간에서 왔는가. `config/detector_characteristics.example.json`
#: 의 `label_namespace` 와 같은 어휘다 — 두 곳에 다른 말을 적으면 콘솔이 보는
#: 선언과 provider 가 내는 값이 갈린다.
LABEL_NAMESPACE_OPERATOR = "operator_vocabulary"
LABEL_NAMESPACE_BUILTIN = "model_builtin_vocabulary"

#: 비교 기준을 YOLO-World provider 와 같은 자리에 둔다(`yolo_world_provider.py`
#: 의 DEFAULT_CONF 와 같은 값) — 클래스별 하한은 여기가 아니라
#: `config/obstacle_taxonomy.example.json` 의 `class_conf` 가 소유한다.
DEFAULT_CONF = 0.05


def is_prompt_free_label(label: str) -> bool:
    """이 라벨이 어휘가 아니라 모델 내장 범주에서 온 것인가."""
    return str(label).startswith(PROMPT_FREE_LABEL_PREFIX)


def strip_prompt_free_prefix(label: str) -> str:
    """접두사를 떼고 모델이 실제로 말한 이름을 돌려준다.

    **의도적으로 호출해야** 한다 — 이 한 줄을 거치지 않으면 prompt-free 이름이
    어휘 매칭처럼 보이는 일이 일어나지 않는다. 어휘 라벨에는 아무 영향이 없다.
    """
    text = str(label)
    if text.startswith(PROMPT_FREE_LABEL_PREFIX):
        return text[len(PROMPT_FREE_LABEL_PREFIX):]
    return text


class YoloePerceptionProvider:
    """YOLOE 가중치 하나를 `PerceptionProvider` 로 감싼다.

    `class_names` 가 있으면 텍스트 프롬프트 모드이고 `set_classes` 는 모델 최초
    로드 때 **한 번만** 호출된다 — 어휘를 바꾸려면 새 provider 인스턴스를 만든다
    (`yolo_world_provider.YoloWorldPerceptionProvider` 와 같은 관례이고, 그
    비용이 `config/detector_characteristics.example.json` 의
    `vocabulary_change_requires` 에 선언으로 적혀 있다).

    `class_names=None` 이면 prompt-free 모드다. 어휘를 넘기지 않고, 나오는 라벨은
    `PROMPT_FREE_LABEL_PREFIX` 가 붙어 어휘 매칭과 구분된다.
    """

    def __init__(
        self,
        weights_path: str | Path,
        *,
        class_names: list[str] | None = None,
        device: str | None = None,
        conf: float = DEFAULT_CONF,
    ) -> None:
        if class_names is not None and not class_names:
            raise ValueError(
                "class_names must be non-empty — an empty vocabulary can never match anything; "
                "prompt-free 모드는 class_names=None 이다(빈 리스트가 아니다)"
            )
        self.weights_path = Path(weights_path)
        self.class_names = list(class_names) if class_names is not None else None
        self.prompt_mode = PROMPT_MODE_TEXT if class_names is not None else PROMPT_MODE_FREE
        self.device = _resolve_device(device)
        self.conf = conf
        self._model: Any | None = None
        self._load_error: str = ""

    # ── capability ──────────────────────────────────────────────────────────

    @property
    def label_namespace(self) -> str:
        """이 provider 가 내는 라벨이 어느 이름 공간에 있는가."""
        if self.prompt_mode == PROMPT_MODE_FREE:
            return LABEL_NAMESPACE_BUILTIN
        return LABEL_NAMESPACE_OPERATOR

    def is_available(self) -> bool:
        """가중치 파일 존재만 본다 — `yolo_world_provider` 와 같은 관례다.

        텍스트 인코더(MobileCLIP)의 부재는 여기서 판정하지 않는다. 그 자산이
        어디서 해소되는지는 ultralytics 가 정하고(자기 weights_dir·작업 디렉터리),
        우리가 그 탐색을 재현하면 두 곳이 서로 다른 답을 말한다. 실제 결손은
        `detect()` 가 흡수하고 사유가 `health()["load_error"]` 에 남으며,
        **요구 자체**는 선언 데이터로 배치 전에 드러난다(AI-C-16).
        """
        return self.weights_path.exists()

    def health(self) -> dict:
        """무엇을 못 하는지가 드러나는 모양으로 낸다(`edge/zipdepth_provider.py` 관례)."""
        model = self._model
        # 내장 범주 수는 **prompt-free 모드에서만** 뜻이 있다. 프롬프트 모드의
        # `model.names` 는 우리가 심은 어휘라 그것을 "내장"이라 적으면 거짓이 된다.
        names = (getattr(model, "names", None)
                 if model is not None and self.prompt_mode == PROMPT_MODE_FREE else None)
        return {
            "weights_path": str(self.weights_path),
            "weights_present": self.is_available(),
            "loaded": model is not None,
            "device": self.device,
            "prompt_mode": self.prompt_mode,
            "label_namespace": self.label_namespace,
            "vocabulary_size": len(self.class_names) if self.class_names is not None else None,
            # prompt-free 내장 범주 수. 로드 전에는 **모른다**(0 이 아니다).
            "builtin_vocabulary_size": len(names) if names else None,
            # 이 모델이 아예 내주지 않는 것. 요구되기 전에 알 수 있다.
            "missing_outputs": ["depth_m", "intrinsics_fx_cx", "global_pose"],
            # 모델은 계산하지만 `PerceptionResult` 가 실어 보내지 못하는 것 —
            # "없다"와 "못 싣는다"는 다른 사실이라 칸을 따로 둔다.
            "outputs_not_surfaced": ["instance_mask"],
            "load_error": self._load_error,
        }

    # ── 실행 ────────────────────────────────────────────────────────────────

    def _load(self) -> Any:
        if self._model is None:
            from ultralytics import YOLOE

            model = YOLOE(str(self.weights_path))
            model.to(self.device)
            if self.prompt_mode == PROMPT_MODE_TEXT:
                # 임베딩을 호출자가 넘긴다 — 이 한 줄이 MobileCLIP 텍스트
                # 인코더를 요구하는 자리다. prompt-free 가중치는 여기서
                # AssertionError 로 거절하고, 그 거절이 모델의 계약이다.
                assert self.class_names is not None
                model.set_classes(self.class_names, model.get_text_pe(self.class_names))
            self._model = model
        return self._model

    def detect(self, frame: Any) -> list[PerceptionResult]:
        """프레임 하나에서 이 모드의 계약대로 검출한다.

        가중치가 없으면(`is_available()` False) 로드를 시도하지 않고 빈 리스트를
        반환한다. 로드가 실패해도(텍스트 인코더 부재·네트워크 없음·모드와
        가중치 불일치) 예외를 올리지 않고 사유를 `health()` 에 남긴 뒤 빈
        리스트를 반환한다 — 이 선택 기능의 결손이 다른 capability 를 막아서는 안
        된다(AI-C-05). `grounding_dino_provider.detect` 와 같은 관례다.
        """
        if not self.is_available():
            self._load_error = f"weights_missing:{self.weights_path}"
            return []
        try:
            model = self._load()
        except Exception as exc:  # noqa: BLE001 — 사유를 남기고 축소한다
            self._load_error = f"{type(exc).__name__}: {exc}"
            self._model = None
            return []

        results = model.predict(frame, conf=self.conf, device=self.device, verbose=False)
        res = results[0]
        boxes = getattr(res, "boxes", None)
        out: list[PerceptionResult] = []
        if boxes is None:
            return out
        prefix = PROMPT_FREE_LABEL_PREFIX if self.prompt_mode == PROMPT_MODE_FREE else ""
        for b in boxes:
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            out.append(
                PerceptionResult(
                    box=(x1, y1, x2, y2),
                    label=f"{prefix}{res.names[int(b.cls[0])]}",
                    confidence=float(b.conf[0]),
                )
            )
        return out
