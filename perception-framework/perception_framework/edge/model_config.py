"""설정 파일 기반 provider 구성 로더 (AI-C-15, AI-B-01, AI-B-04).

implements: AI-C-15, AI-B-01, AI-B-04

2026-09-17 사용자 확정 설계: "사용 모델, 모델별 임계값, 게이트, 특징 등 세부
파라미터나 변수들과 설계 내 설정들을 config나 json 같은 설정 파일로 수정이
가능하도록 하고 어댑터로 분리하여 확장이 용이하도록 설계." 이 모듈이 그
설정 파일 → provider 인스턴스 조립을 담당한다. YAML이 아니라 JSON을 쓴다 --
`contracts/profile_loader.py`가 이미 이 패턴(json.loads 후 데이터클래스로)을
쓰고 있고, PyYAML을 새 필수 의존성으로 들이지 않기 위해서다.

모델 경로·디바이스·임계값을 여기 설정 파일 하나로 몰아 두면, 실행 위치를
바꾸거나(엣지 CPU -> 실제 로봇 하드웨어) 모델을 바꾸는 것이 **이 파일 하나만
편집**하는 문제가 된다 -- `ondevice/rpn_propose.py` 등 provider 코드 자체는
건드리지 않는다. `class_features.json`(클래스별 CLIP 게이트/임계값)은 이미
이 패턴을 만족하는 별도 파일이라 이 로더가 감싸지 않고 경로만 가리킨다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REQUIRED_TOP_LEVEL_KEYS = ("rpn", "clip", "grounding_dino", "yolo_world", "fastsam")


class ModelConfigError(ValueError):
    pass


#: 이 이름의 값은 상대경로일 수 있다 -- 있으면 설정 파일 자신의 위치 기준으로
#: 풀어 준다. 그래야 실행 위치를 옮겨도(git pull) 어느 디렉터리에서 실행하든
#: 같은 파일을 가리킨다(현재 작업 디렉터리 기준이면 깨진다).
_PATH_KEYS = (
    "weights_path", "vision_model_path", "text_model_path", "tokenizer_path", "class_features_path",
)


def _resolve_relative_paths(node: Any, base_dir: Path) -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in _PATH_KEYS and isinstance(v, str) and not Path(v).is_absolute():
                out[k] = str((base_dir / v).resolve())
            else:
                out[k] = _resolve_relative_paths(v, base_dir)
        return out
    return node


def load_model_config(path: str | Path) -> dict[str, Any]:
    """설정 파일을 dict로 읽고, 알려진 경로 필드의 상대경로를 설정 파일
    자신의 위치 기준으로 풀어 준다(실행 디렉터리에 의존하지 않게). 스키마
    해석 자체는 `build_*` 함수들이 한다(이 함수는 새 provider가 추가돼도
    안 바뀐다)."""
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED_TOP_LEVEL_KEYS if k not in raw]
    if missing:
        raise ModelConfigError(f"missing required model_config sections: {missing}")
    return _resolve_relative_paths(raw, path.parent)


def build_rpn_provider(config: dict[str, Any]):
    from perception_framework.ondevice.rpn_propose import RpnProposalProvider

    cfg = config["rpn"]
    return RpnProposalProvider(
        cfg["weights_path"],
        device=cfg.get("device"),
        conf=cfg.get("conf", 1e-4),
        iou=cfg.get("iou", 0.50),
        top_n=cfg.get("top_n", 1000),
    )


def build_clip_engine(config: dict[str, Any]):
    from perception_framework.edge.clip_dictionary_provider import ClipEngine

    cfg = config["clip"]
    return ClipEngine(cfg["vision_model_path"], cfg["text_model_path"], cfg["tokenizer_path"])


def build_clip_dictionary_providers(config: dict[str, Any], class_names: list[str], *, repo_root: str | Path | None = None):
    """`class_features.json`(경로는 설정의 `clip.class_features_path`)에서
    `class_names` 각각의 provider를 만든다 -- CLIP 엔진(무거운 ONNX 세션)은
    한 번만 만들어 클래스 수만큼 공유한다."""
    from perception_framework.edge.clip_dictionary_provider import ClipDictionaryPerceptionProvider

    cfg = config["clip"]
    class_dict = json.loads(Path(cfg["class_features_path"]).read_text(encoding="utf-8"))
    engine = build_clip_engine(config)
    return {
        name: ClipDictionaryPerceptionProvider(name, class_dict[name], engine, repo_root=repo_root)
        for name in class_names
    }


def build_grounding_dino_provider(config: dict[str, Any], class_names: list[str]):
    from perception_framework.edge.grounding_dino_provider import GroundingDinoPerceptionProvider

    cfg = config["grounding_dino"]
    return GroundingDinoPerceptionProvider(
        class_names,
        model_id=cfg.get("model_id", "IDEA-Research/grounding-dino-tiny"),
        device=cfg.get("device"),
        box_threshold=cfg.get("box_threshold", 0.15),
        text_threshold=cfg.get("text_threshold", 0.15),
    )


def build_yolo_world_provider(config: dict[str, Any], class_names: list[str]):
    from perception_framework.edge.yolo_world_provider import YoloWorldPerceptionProvider

    cfg = config["yolo_world"]
    return YoloWorldPerceptionProvider(
        class_names, cfg["weights_path"], device=cfg.get("device"), conf=cfg.get("conf", 0.05),
    )


def build_fastsam_provider(config: dict[str, Any]):
    from perception_framework.edge.fastsam_provider import FastSamPerceptionProvider

    cfg = config["fastsam"]
    return FastSamPerceptionProvider(cfg["weights_path"], device=cfg.get("device"))


def build_unidepth_provider(config: dict[str, Any]):
    from perception_framework.edge.self_localization import UniDepthCameraProvider

    cfg = config.get("unidepth", {})
    return UniDepthCameraProvider(
        cfg.get("model_id", "lpiccinelli/unidepth-v2-vitb14"), device=cfg.get("device", "cuda"),
    )


def build_all_providers(config: dict[str, Any], class_names: list[str], *, repo_root: str | Path | None = None) -> dict[str, Any]:
    """설정 파일 하나로 이번 통합 설계의 provider 전부를 조립한다. 5번째
    모델을 추가할 때는 이 함수에 `build_x_provider` 호출 한 줄만 늘리면
    된다(각 provider 클래스·`class_features.json`은 그대로)."""
    providers: dict[str, Any] = {
        "rpn": build_rpn_provider(config),
        "clip_dictionary": build_clip_dictionary_providers(config, class_names, repo_root=repo_root),
        "grounding_dino": build_grounding_dino_provider(config, class_names),
        "yolo_world": build_yolo_world_provider(config, class_names),
        "fastsam": build_fastsam_provider(config),
    }
    if "unidepth" in config:
        providers["unidepth"] = build_unidepth_provider(config)
    return providers
