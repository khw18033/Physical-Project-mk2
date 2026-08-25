"""tests for: AI-E-01"""

import numpy as np

from ai_framework.perception.detection import BrightBlobDetector, NullPerceptionProvider, PerceptionProvider


def test_null_provider_returns_empty_list_never_raises():
    provider = NullPerceptionProvider()
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    assert provider.detect(frame) == []


def test_blob_detector_finds_a_known_bright_rectangle():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[20:40, 30:60] = 255  # y 20-40, x 30-60
    provider = BrightBlobDetector()

    results = provider.detect(frame)

    assert len(results) == 1
    x1, y1, x2, y2 = results[0].box
    assert abs(x1 - 30) <= 1 and abs(y1 - 20) <= 1
    assert abs(x2 - 60) <= 1 and abs(y2 - 40) <= 1


def test_blob_detector_returns_nothing_on_a_blank_frame():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    provider = BrightBlobDetector()

    assert provider.detect(frame) == []


def test_upper_layer_code_is_unchanged_across_provider_swap():
    def run_perception(provider: PerceptionProvider, frame: np.ndarray):
        return provider.detect(frame)

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[10:20, 10:20] = 255

    assert run_perception(NullPerceptionProvider(), frame) == []
    assert len(run_perception(BrightBlobDetector(), frame)) == 1
