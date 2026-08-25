"""Vendor-neutral accelerator discovery and two interchangeable image
runtime providers (CPU and OpenCL) for the same capability kind.

implements: AI-B-01, AI-B-04, AI-B-08, AI-C-04, AI-C-12

Purpose is to *prove* the vendor-independence the requirements demand
(원칙 #1, AI-B-08: "특정 모델 파일 형식, 추론 엔진, 가속기 API ... 에 직접
의존하지 않고"). Both classes below satisfy the same `AIRuntimeProvider`
Protocol and return the same result; only their registered tags and cost
differ, so switching between them is a registry decision, never a code
change in any caller.

Tags are expressed as *capabilities* ("this node can execute OpenCL"),
never as vendor names ("cuda"/"nvidia"), so no vendor can leak into a
selection rule. The tag strings here are provisional and stay local to
this module until the common data dictionary is fixed (원칙 #8, AI-C-01).
"""

from __future__ import annotations

from typing import Any

TAG_CPU = "compute.cpu"
TAG_OPENCL = "compute.opencl"
TAG_HW_VIDEO_DECODE = "media.hw_decode"


def _cv2():
    """Imported lazily so a node without OpenCV can still import this
    module and simply report fewer tags (AI-C-11 격리)."""
    import cv2

    return cv2


def opencl_available() -> bool:
    """True when an OpenCL platform is actually usable on this node.

    Note this is a *capability* probe, not a vendor probe: an Intel iGPU,
    an AMD card or an ARM Mali all answer the same way.
    """
    try:
        cv2 = _cv2()
    except Exception:
        return False
    try:
        return bool(cv2.ocl.haveOpenCL()) and bool(cv2.ocl.useOpenCL() or _try_enable_opencl(cv2))
    except Exception:
        return False


def _try_enable_opencl(cv2) -> bool:
    try:
        cv2.ocl.setUseOpenCL(True)
        return bool(cv2.ocl.useOpenCL())
    except Exception:
        return False


def hw_video_decode_available() -> bool:
    """Whether a hardware video decode path exists (VAAPI/QSV/NVDEC/...).

    Probed through OpenCV's backend registry rather than by looking for
    any particular vendor's device node.
    """
    try:
        cv2 = _cv2()
        names = {cv2.videoio_registry.getBackendName(b) for b in cv2.videoio_registry.getBackends()}
    except Exception:
        return False
    return bool(names & {"INTEL_MFX", "GSTREAMER", "FFMPEG"})


def discover_node_tags() -> set[str]:
    """Runtime resource discovery for this node (AI-B-04, 원칙 #5).

    Absent accelerators are simply absent tags — never an error, never a
    startup blocker (금지 사항: GPU/NPU가 항상 존재한다고 가정하지 않는다).
    """
    tags = {TAG_CPU}
    if opencl_available():
        tags.add(TAG_OPENCL)
    if hw_video_decode_available():
        tags.add(TAG_HW_VIDEO_DECODE)
    return tags


class CpuImageRuntimeProvider:
    """Reference `AIRuntimeProvider` running an image op on the CPU.

    Capability kind handled: "image.smooth" — deliberately a trivial op,
    because what is under test is the interface boundary, not accuracy
    (AI-B-09).
    """

    capability_kinds = ("image.smooth",)
    provider_id = "cpu-image-runtime"

    def infer(self, capability_kind: str, inputs: Any) -> Any:
        if capability_kind not in self.capability_kinds:
            raise ValueError(f"unsupported capability_kind: {capability_kind}")
        cv2 = _cv2()
        return cv2.GaussianBlur(inputs, (5, 5), 0)

    def is_available(self) -> bool:
        try:
            _cv2()
            return True
        except Exception:
            return False


class OpenClImageRuntimeProvider:
    """Same capability, executed through OpenCV's T-API (`UMat`) so the
    work lands on whatever OpenCL device the node exposes.

    Nothing here names a vendor or a driver. If no OpenCL platform is
    present, `is_available()` returns False and the selector picks the
    CPU provider instead — the required degradation path (AI-B-04/B-06).
    """

    capability_kinds = ("image.smooth",)
    provider_id = "opencl-image-runtime"

    def infer(self, capability_kind: str, inputs: Any) -> Any:
        if capability_kind not in self.capability_kinds:
            raise ValueError(f"unsupported capability_kind: {capability_kind}")
        if not self.is_available():
            raise RuntimeError("no OpenCL device available")
        cv2 = _cv2()
        device_input = cv2.UMat(inputs)
        result = cv2.GaussianBlur(device_input, (5, 5), 0)
        return result.get()  # back to host memory; callers see a plain array either way

    def is_available(self) -> bool:
        return opencl_available()
