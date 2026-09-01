"""implements: AI-B-01, AI-B-04, AI-B-08, AI-C-12
covers: vendor-neutral accelerator discovery, CPU/OpenCL provider swap,
        automatic fallback when no accelerator exists

These tests are written to pass on a node with **no NVIDIA driver and no
discrete GPU in use** — that is the point (원칙 #1). If a vendor
dependency ever leaks into core code, this suite fails here first.
"""

import tokenize
from pathlib import Path

import numpy as np
import pytest

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from perception_framework.providers.adapters import AIRuntimeProvider
from perception_framework.providers.compute import (
    TAG_CPU,
    TAG_GPU,
    TAG_OPENCL,
    CpuImageRuntimeProvider,
    OnnxRuntimeProvider,
    OpenClImageRuntimeProvider,
    discover_node_tags,
    onnx_execution_providers,
    onnx_provider_available,
    opencl_available,
)
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.selection.selector import CapabilitySelector

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "perception_framework"
BUDGET = ResourceBudget(compute_units=100, memory_mb=4096)


def registration(provider, tags, *, priority, cost_units, preferred=()):
    return ProviderRegistration(
        capability_kind="image.smooth",
        provider_id=provider.provider_id,
        version="1",
        compatibility=CompatibilityProfile(
            required_hw_tags=tags,
            preferred_hw_tags=preferred,
            priority=priority,
            cost=ResourceCost(compute_units=cost_units),
        ),
        requirement=CapabilityRequirement(),
    )


def test_both_runtimes_satisfy_the_same_protocol():
    assert isinstance(CpuImageRuntimeProvider(), AIRuntimeProvider)
    assert isinstance(OpenClImageRuntimeProvider(), AIRuntimeProvider)
    assert isinstance(
        OnnxRuntimeProvider(
            "missing.onnx",
            capability_kinds=("perception.detect",),
            provider_id="onnx-missing",
        ),
        AIRuntimeProvider,
    )


def test_discovery_never_fails_and_always_reports_cpu():
    tags = discover_node_tags()

    # 가속기가 없어도 오류가 아니라 태그가 없을 뿐이다 (금지 사항: GPU가 항상
    # 존재한다고 가정하지 않는다).
    assert TAG_CPU in tags
    assert isinstance(tags, set)
    assert TAG_GPU not in tags or any(p != "CPUExecutionProvider" for p in onnx_execution_providers())


def test_no_vendor_name_appears_in_executable_package_source():
    """원칙 #1: GPU/NPU 벤더를 핵심 코드에 하드코딩하지 않는다.

    Comments and docstrings may *discuss* vendors (this repo's docs do);
    what must never happen is a vendor name reaching executable code —
    an import, an attribute, a literal or a tag value. Checked by
    tokenizing away comments and strings.
    """
    vendors = {"nvidia", "cuda", "tensorrt", "rocm", "cudnn", "cupy"}
    offending = []

    for path in PACKAGE_DIR.rglob("*.py"):
        with open(path, "rb") as fh:
            for token in tokenize.tokenize(fh.readline):
                if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
                    continue
                if token.string.lower() in vendors:
                    offending.append(f"{path.name}:{token.start[0]}: {token.string}")

    assert not offending, "vendor name in executable code:\n" + "\n".join(offending)


def test_selector_falls_back_to_cpu_when_accelerator_tag_is_absent():
    registry = CapabilityRegistry()
    registry.register_local(
        registration(OpenClImageRuntimeProvider(), (TAG_OPENCL,), priority=10, cost_units=2)
    )
    registry.register_local(registration(CpuImageRuntimeProvider(), (TAG_CPU,), priority=50, cost_units=8))
    selector = CapabilitySelector(registry)

    result = selector.select("image.smooth", node_tags={TAG_CPU}, budget=BUDGET)

    # 선호 자원이 없으면 호환 가능한 일반 자원으로 대체 (AI-B-04).
    assert result.provider.provider_id == "cpu-image-runtime"


def test_selector_switches_to_accelerator_when_tag_appears():
    registry = CapabilityRegistry()
    registry.register_local(
        registration(OpenClImageRuntimeProvider(), (TAG_OPENCL,), priority=10, cost_units=2)
    )
    registry.register_local(registration(CpuImageRuntimeProvider(), (TAG_CPU,), priority=50, cost_units=8))
    selector = CapabilitySelector(registry)

    result = selector.select("image.smooth", node_tags={TAG_CPU, TAG_OPENCL}, budget=BUDGET)

    # 노드 태그 한 줄만 달라졌을 뿐, 호출부 코드는 동일하다 (AI-B-08).
    assert result.provider.provider_id == "opencl-image-runtime"


def test_preferred_tag_ranks_but_never_excludes():
    """AI-B-04 gap fix: preferred tags now influence ranking."""
    registry = CapabilityRegistry()
    registry.register_local(
        registration(
            OpenClImageRuntimeProvider(), (), priority=10, cost_units=2, preferred=(TAG_OPENCL,)
        )
    )
    registry.register_local(registration(CpuImageRuntimeProvider(), (), priority=10, cost_units=2))
    selector = CapabilitySelector(registry)

    without_accel = selector.select("image.smooth", node_tags={TAG_CPU}, budget=BUDGET)
    with_accel = selector.select("image.smooth", node_tags={TAG_CPU, TAG_OPENCL}, budget=BUDGET)

    # Same priority and cost: the unmet preference decides, and the
    # accelerator provider is still *eligible* (not excluded) either way.
    assert without_accel.provider.provider_id == "cpu-image-runtime"
    assert with_accel.provider.provider_id == "opencl-image-runtime"


def test_cpu_runtime_produces_a_result_on_this_node():
    image = np.zeros((32, 32), dtype=np.uint8)
    image[16, 16] = 255

    out = CpuImageRuntimeProvider().infer("image.smooth", image)

    assert out.shape == image.shape
    assert out[16, 16] < 255  # smoothing actually happened


def test_unsupported_capability_kind_is_rejected_by_both_runtimes():
    image = np.zeros((8, 8), dtype=np.uint8)
    for provider in (CpuImageRuntimeProvider(), OpenClImageRuntimeProvider()):
        with pytest.raises(ValueError):
            provider.infer("perception.detect", image)


@pytest.mark.skipif(not opencl_available(), reason="no OpenCL platform on this node")
def test_opencl_runtime_matches_cpu_result_when_available():
    """Runs only where an OpenCL device exists; identical contract and
    numerically equivalent output prove the swap is transparent."""
    image = (np.arange(32 * 32, dtype=np.uint8).reshape(32, 32))

    cpu_out = CpuImageRuntimeProvider().infer("image.smooth", image)
    accel_out = OpenClImageRuntimeProvider().infer("image.smooth", image)

    assert np.allclose(cpu_out, accel_out, atol=1)


def test_opencl_runtime_reports_unavailable_instead_of_crashing():
    provider = OpenClImageRuntimeProvider()
    available = provider.is_available()

    assert isinstance(available, bool)
    if not available:
        image = np.zeros((8, 8), dtype=np.uint8)
        with pytest.raises(RuntimeError):
            provider.infer("image.smooth", image)


def test_onnx_provider_reports_unavailable_without_model_file():
    provider = OnnxRuntimeProvider(
        "missing.onnx",
        capability_kinds=("perception.detect",),
        provider_id="onnx-detector",
    )

    assert provider.is_available() is False
    assert isinstance(onnx_execution_providers(), tuple)
    assert isinstance(onnx_provider_available("CPUExecutionProvider"), bool)


def test_selector_can_represent_cpu_and_accelerator_onnx_models():
    registry = CapabilityRegistry()
    cpu = OnnxRuntimeProvider(
        "missing-cpu.onnx",
        capability_kinds=("perception.detect",),
        provider_id="onnx-cpu-detector",
    )
    accel = OnnxRuntimeProvider(
        "missing-accelerator.onnx",
        capability_kinds=("perception.detect",),
        provider_id="onnx-accelerator-detector",
        execution_providers=("UnavailableExecutionProvider",),
    )
    registry.register_local(
        ProviderRegistration(
            capability_kind="perception.detect",
            provider_id=cpu.provider_id,
            version="1",
            compatibility=CompatibilityProfile(
                required_hw_tags=(TAG_CPU,),
                priority=50,
                cost=ResourceCost(compute_units=4, memory_mb=256),
            ),
        )
    )
    registry.register_local(
        ProviderRegistration(
            capability_kind="perception.detect",
            provider_id=accel.provider_id,
            version="1",
            compatibility=CompatibilityProfile(
                required_hw_tags=(TAG_GPU,),
                priority=10,
                cost=ResourceCost(compute_units=12, memory_mb=1024),
            ),
        )
    )

    selected = CapabilitySelector(registry).select(
        "perception.detect",
        node_tags={TAG_CPU},
        budget=ResourceBudget(compute_units=16, memory_mb=2048),
    )

    assert selected.provider.provider_id == "onnx-cpu-detector"
