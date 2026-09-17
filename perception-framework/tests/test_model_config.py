"""implements: AI-C-15, AI-B-01, AI-B-04

`config/model_config.example.json`이 이 저장소에 실제로 존재하는 모델
파일들을 가리키므로, provider들이 전부 조립 가능한지까지 확인한다(무거운
추론 자체는 하지 않는다 -- 그건 각 provider 자신의 테스트 몫).
"""
from pathlib import Path

import pytest

from perception_framework.edge.model_config import (
    ModelConfigError,
    build_all_providers,
    load_model_config,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "model_config.example.json"
REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not CONFIG_PATH.exists(), reason="example model_config.json not present")


def test_missing_required_section_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"rpn": {}}', encoding="utf-8")

    with pytest.raises(ModelConfigError):
        load_model_config(bad)


def test_relative_paths_resolve_against_the_config_files_own_directory():
    config = load_model_config(CONFIG_PATH)

    assert Path(config["rpn"]["weights_path"]).is_absolute()
    assert Path(config["rpn"]["weights_path"]).name == "yolov8n.pt"
    assert Path(config["clip"]["class_features_path"]).is_absolute()


def test_null_device_is_preserved_for_auto_detection():
    config = load_model_config(CONFIG_PATH)

    assert config["rpn"]["device"] is None


@pytest.mark.skipif(
    not (REPO_ROOT / "models" / "openvocab" / "clip-vit-base-patch32" / "onnx" / "vision_model_quantized.onnx").exists(),
    reason="실제 CLIP/YOLO 가중치 파일이 이 기기에 없음",
)
def test_build_all_providers_assembles_every_provider_from_one_config_file():
    """이 저장소에 실제 존재하는 모델 경로를 가리키는 설정 하나로 5개
    provider 전부(+클래스별 CLIP dictionary)가 조립돼야 한다 -- 모델 교체나
    실행 위치 이전이 코드 변경 없이 '이 파일 하나만 편집'으로 되는지 확인."""
    config = load_model_config(CONFIG_PATH)

    providers = build_all_providers(config, class_names=["door", "pedestal"], repo_root=REPO_ROOT)

    assert set(providers) >= {"rpn", "clip_dictionary", "grounding_dino", "yolo_world", "fastsam"}
    assert set(providers["clip_dictionary"]) == {"door", "pedestal"}
    assert providers["rpn"].is_available() is True
