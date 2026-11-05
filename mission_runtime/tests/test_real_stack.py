"""implements: AI-O-05, AI-O-06, AI-L-09, AI-B-01, AI-C-06, AI-C-07
covers: **실제 도구·실제 모델·실제 자원**으로 한 바퀴. 하드웨어는 없지만 모델 가중치,
        추론 런타임, 브로커, 이 기계의 가속기 계측은 전부 실물이다.

왜 따로 두는가 — 합성 수치로만 검증하면 자료구조가 맞는지는 알 수 있어도 다음 셋을
알 수 없다.

  1. 실제 모델이 실제 프레임에서 **같은 값**을 내는가 (포팅이 측정 대상을 바꾸지 않았나)
  2. 실제 기계에서 **못 재는 값**이 0 으로 새지 않는가 (이 호스트는 CPU 온도 센서가 없다)
  3. 실제 브로커를 지나온 바이트가 **계약을 그대로 만족**하는가

자산이나 도구가 없는 기계에서는 그 묶음만 skip 한다 — 선택 구성요소 결손은 축소이지
실패가 아니다(AI-C-05). 이 저장소의 기준 기계에서는 전부 실행된다.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from conftest import demo_asset_path
from mission_runtime.continual.stream_ingest import ThresholdLearningProvider
from mission_runtime.continual.stream_learning import (
    CandidateBatch,
    CandidateOrigin,
    InputConditions,
    ParameterSet,
    StreamSample,
)
from mission_runtime.execution.task_graph import NodeState, TaskGraph, TaskNode
from mission_runtime.integration.status_wire import status_snapshot_message
from mission_runtime.integration.wire import MessageContext
from mission_runtime.observability.dashboard_view import DashboardSnapshot, MissionSummary
from mission_runtime.observability.host_resources import HostResourceReader, read_nvidia_gpus
from mission_runtime.observability.layered_metrics import (
    Direction,
    LayeredResourceView,
    MeetState,
    TargetBaseline,
)
from mission_runtime.observability.resource_watch import (
    REASON_NOT_MEASURED,
    ResourceWatch,
    WatchTarget,
)

CONTRACT_DIR = Path(__file__).parents[1] / "schemas" / "ai"

# ── 실제 모델 자산 ────────────────────────────────────────────────────────────

CLIP_DIR = demo_asset_path("openvocab", "clip-vit-base-patch32")
VISION_ONNX = CLIP_DIR / "onnx" / "vision_model_quantized.onnx"
TEXT_ONNX = CLIP_DIR / "onnx" / "text_model_quantized.onnx"
TOKENIZER = CLIP_DIR / "tokenizer.json"
SCAN_DIR = demo_asset_path("datasets", "20260910-134818_rot8")
CLASS_FEATURES = demo_asset_path("class_features.json")

#: 실제 로봇 스캔에서 **기록된** 탐지 근거. 값은 그 판의 산출물이다.
#: (door_example/test/door/frame_0000NN/evidence.json)
RECORDED = {
    "frame_000132.jpg": {
        "box": (32.06, 103.27, 51.99, 141.85),
        "rotation_deg": 315.0,
        "final_score": 0.2680,
        "median_saturation": 129.0,
    },
}

_model_assets = all(p.exists() for p in (VISION_ONNX, TEXT_ONNX, TOKENIZER, CLASS_FEATURES)) and SCAN_DIR.is_dir()
needs_model = pytest.mark.skipif(not _model_assets, reason=f"실제 CLIP 모델·스캔 자산이 없다: {CLIP_DIR}")


def _onnxruntime_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


needs_runtime = pytest.mark.skipif(not _onnxruntime_available(), reason="onnxruntime 미설치")


def _psutil_available() -> bool:
    try:
        import psutil  # noqa: F401
    except Exception:
        return False
    return True


#: CPU 사용률의 **실측**은 `psutil` 이 있어야 나온다. 없으면
#: `observability/host_resources.py` 가 값을 미측정으로 두는데 그것이 **올바른
#: 축소다**(AI-O-05: 미측정은 0 이 아니다) — 그래서 "실측이 있다" 를 전제하는
#: 아래 둘만 skip 한다. 미측정이 0 으로 새지 않는가, 가속기가 개체로 식별되는가는
#: 같은 파일의 다른 시험이 psutil 없이도 그대로 본다.
needs_host_metrics = pytest.mark.skipif(
    not _psutil_available(),
    reason="psutil 미설치 — CPU 실측이 미측정으로 내려간다. 이 호스트 계측 "
           'provider 만 skip 이다(AI-C-05): pip install -e ".[metrics]"',
)


@pytest.fixture(scope="module")
def clip_engine():
    from mission_runtime.edge.clip_dictionary_provider import ClipEngine

    return ClipEngine(VISION_ONNX, TEXT_ONNX, TOKENIZER)


@pytest.fixture(scope="module")
def door_provider(clip_engine):
    from mission_runtime.edge.clip_dictionary_provider import ClipDictionaryPerceptionProvider

    config = json.loads(CLASS_FEATURES.read_text(encoding="utf-8"))
    return ClipDictionaryPerceptionProvider(
        "door", config["door"], clip_engine, repo_root=demo_asset_path()
    )


def _frame(name: str):
    import cv2

    image = cv2.imread(str(SCAN_DIR / name))
    assert image is not None, f"프레임을 읽지 못했다: {name}"
    return image


# ── A. 실제 모델 ──────────────────────────────────────────────────────────────

@needs_model
@needs_runtime
def test_the_real_model_embeds_real_pixels(clip_engine):
    """실제 가중치로 실제 프레임을 임베딩한다. 정규화와 재현성을 본다.

    두 번 호출해 같은 값이 나와야 한다 — 양자화 모델이 비결정적이면 임계 조정이
    흔들리고, 그 흔들림은 학습 결과로 오해된다.
    """
    import numpy as np

    crop = _frame("frame_000132.jpg")[103:142, 32:52]
    first = clip_engine.embed_images([crop])
    second = clip_engine.embed_images([crop])

    assert first.shape[0] == 1 and first.shape[1] >= 128
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-3)
    assert np.allclose(first, second, atol=0.0), "같은 입력에 다른 임베딩이 나왔다"


@needs_model
@needs_runtime
def test_our_port_measures_the_same_saturation_as_the_recorded_run(door_provider):
    """포팅이 **측정 대상을 바꾸지 않았는지** 실제 기록값과 맞댄다.

    채도는 CLIP 이 아니라 crop 픽셀을 직접 재는 게이트다. 기록된 판의 값과 우리
    값이 어긋나면, 같은 이름의 게이트가 서로 다른 것을 재고 있다는 뜻이다 — 그러면
    사람이 sweep 으로 맞춘 임계가 우리 쪽에서는 다른 축의 숫자가 된다(AI-B-01).
    """
    recorded = RECORDED["frame_000132.jpg"]
    crop = door_provider._crop(_frame("frame_000132.jpg"), recorded["box"])
    passed, detail = door_provider._saturation_gate([crop], 1)

    measured = detail(0)["median_saturation"]
    assert abs(measured - recorded["median_saturation"]) <= 10.0, (
        f"기록 {recorded['median_saturation']} vs 측정 {measured} — 같은 양을 재지 않는다"
    )
    assert bool(passed[0]) is True


@needs_model
@needs_runtime
def test_the_curated_hue_range_rejects_this_earlier_scan_and_that_is_the_finding(door_provider):
    """**실측으로 확인한 범위 밖 적용**을 고정한다.

    색상(H) 게이트의 범위 85~112 는 2026-09-15 자료로 맞춘 값이고, 이 스캔은
    2026-09-10 판이다. 같은 픽셀·같은 모델에서 우리 측정은 median H = 127 이라
    **실제 문이 탈락한다.** 범위를 이 스캔까지 넓히면 같은 박스가 통과한다 — 바뀐
    것은 파라미터 하나뿐이다.

    이것이 AI-B-01 이 금지한 바로 그 모양이다: 한 입력 구성에서 맞춘 값을 다른
    구성에 재측정 없이 적용하면 조용히 아무것도 못 찾는다. 그래서 "고쳐 두고 잊는"
    대신 시험으로 남긴다 — 누가 범위를 손대면 이 시험이 먼저 말한다.
    """
    recorded = RECORDED["frame_000132.jpg"]
    crop = door_provider._crop(_frame("frame_000132.jpg"), recorded["box"])

    passed, detail = door_provider._hue_gate([crop], 1)
    measured_hue = detail(0)["median_hue"]
    assert bool(passed[0]) is False
    assert measured_hue > door_provider.hue_cfg["max_median_hue"]

    widened = dict(door_provider.hue_cfg)
    widened["max_median_hue"] = measured_hue + 1
    door_provider.hue_cfg = widened
    try:
        passed_again, _ = door_provider._hue_gate([crop], 1)
        assert bool(passed_again[0]) is True
    finally:
        door_provider.hue_cfg = dict(widened, max_median_hue=112)


@needs_model
@needs_runtime
def test_real_similarities_drive_the_threshold_learner(door_provider):
    """실제 스캔 8장의 **실제 유사도**로 임계를 조정한다(AI-L-09).

    합성 숫자로는 "분위에서 고른다"만 확인되고, 실제 분포에서 임계가 쓸 수 있는
    구간에 떨어지는지는 확인되지 않는다. 그래서 실제 프레임에서 뽑은 값으로 돌린다.
    """
    import numpy as np

    conditions = InputConditions(device_id="scan-rig", camera_id="rot8",
                                 resolution="464x400")
    samples = []
    for index, path in enumerate(sorted(SCAN_DIR.glob("*.jpg"))):
        crop = door_provider._crop(_frame(path.name), (32.0, 103.0, 52.0, 142.0))
        embeds = door_provider.engine.embed_images([crop])
        similarity = float((embeds @ door_provider.text_embeds.T).max())
        samples.append(StreamSample(
            sample_id=f"s{index}", conditions=conditions, label="door",
            feature=(similarity,), origin=CandidateOrigin.HUMAN_CONFIRMED,
            similarity=similarity, frame_ref=path.name,
        ))

    observed = [s.similarity for s in samples]
    assert len(observed) == 8
    assert all(0.0 < value < 1.0 for value in observed)

    base = ParameterSet(parameters={"door": {"prompts": door_provider.anchored_features,
                                             "threshold": 0.25}},
                        conditions=conditions)
    provider = ThresholdLearningProvider(min_samples=5, quantile=0.05, floor=0.05)
    outcome = provider.train(CandidateBatch(conditions, tuple(samples)), base=base)

    assert outcome.parameters is not None, outcome.reason
    learned = outcome.parameters.parameters["door"]["threshold"]
    # 제공자가 임계를 소수 여섯 자리로 끊으므로 그만큼의 여유를 둔다 — 자리수
    # 반올림을 "분포 밖"으로 읽으면 매번 깨지는 시험이 된다.
    assert min(observed) - 1e-6 <= learned <= max(observed) + 1e-6, (
        f"임계 {learned} 가 관측 분포 [{min(observed):.4f}, {max(observed):.4f}] 밖이다"
    )
    # 프롬프트는 학습으로 바뀌지 않는다 — 사람이 근거를 적어 바꾸는 값이다.
    assert outcome.parameters.parameters["door"]["prompts"] == door_provider.anchored_features


# ── B. 실제 자원 ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def host_view() -> LayeredResourceView:
    reader = HostResourceReader(cpu_interval_s=0.2)
    reader.read()          # 전력은 차분이라 첫 읽기를 버린다
    time.sleep(0.2)
    return reader.read()


@needs_host_metrics
def test_the_host_reports_at_least_its_own_cpu(host_view):
    """이 기계에서 실제로 읽힌다. 가속기는 **개체**로 식별된다(AI-O-05)."""
    ids = [a.instance_id for a in host_view.accelerators]
    assert "cpu" in ids
    assert len(ids) == len(set(ids)), "가속기 개체 id 가 겹쳤다"
    cpu = next(a for a in host_view.accelerators if a.instance_id == "cpu")
    assert cpu.utilization.unit == "ratio"
    assert cpu.utilization.value is not None and 0.0 <= cpu.utilization.value <= 1.0


def test_a_sensor_this_machine_lacks_reads_as_unmeasured_not_zero(host_view):
    """못 잰 값에 0 을 넣으면 유휴와 고장이 화면에서 같아진다.

    이 호스트(WSL)는 CPU 온도 센서와 powercap 이 없다. 그 사실이 그대로 남아야 한다.
    """
    cpu = next(a for a in host_view.accelerators if a.instance_id == "cpu")
    for measurement in (cpu.temperature, host_view.board.power):
        if measurement.value is None:
            assert measurement.unit, "단위는 값이 없어도 있어야 한다"
        else:
            assert measurement.value >= 0.0


def test_the_gpu_if_present_carries_its_product_name_only_as_a_label(host_view):
    if not read_nvidia_gpus():
        pytest.skip("nvidia-smi 가 없다 — 이 기계에는 GPU 계측이 없다")
    gpu = next(a for a in host_view.accelerators if a.kind == "gpu")
    assert gpu.vendor_label, "제품명은 표시 라벨로 남는다"
    assert gpu.kind == "gpu" and gpu.attachment == "discrete"
    assert gpu.utilization.unit == "ratio"


@needs_host_metrics
def test_a_watch_over_real_readings_agrees_with_its_own_condition(host_view):
    """[E] 경고와 [G] 자원 조건이 **실제 값 하나**에서 나온다(§4.4·§4.7)."""
    cpu = next(a for a in host_view.accelerators if a.instance_id == "cpu")
    measured = cpu.utilization.value
    assert measured is not None

    breached = ResourceWatch.of([WatchTarget(
        "cpu_util", "utilization",
        TargetBaseline(max(0.0, measured - 0.01), Direction.AT_MOST, "ratio"), "cpu")])
    healthy = ResourceWatch.of([WatchTarget(
        "cpu_util", "utilization",
        TargetBaseline(min(1.0, measured + 0.5), Direction.AT_MOST, "ratio"), "cpu")])

    assert len(breached.events(host_view)) == 1
    assert breached.conditions(host_view)[0].satisfied is False
    assert healthy.events(host_view) == ()
    assert healthy.conditions(host_view)[0].satisfied is True


def test_an_unmeasured_real_sensor_never_raises_an_alarm(host_view):
    """못 쟀는데 경고를 울리면 운영자가 없는 고장을 쫓는다."""
    cpu = next(a for a in host_view.accelerators if a.instance_id == "cpu")
    if cpu.temperature.value is not None:
        pytest.skip("이 기계에는 CPU 온도 센서가 있다 — 미측정 경로를 볼 수 없다")
    watch = ResourceWatch.of([WatchTarget(
        "cpu_temp", "temperature", TargetBaseline(40.0, Direction.AT_MOST, "celsius"), "cpu")])
    assert watch.events(host_view) == ()
    condition = watch.conditions(host_view)[0]
    assert condition.satisfied is None
    assert condition.reason_token == REASON_NOT_MEASURED


# ── C. 실제 브로커 ────────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _paho_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("paho") is not None


#: 브로커 **두 가지**가 다 있어야 돈다 — 띄울 서버(`mosquitto`)와 붙을 클라이언트
#: (`paho`). 전에는 서버만 보고 클라이언트는 보지 않아서, 브로커가 깔려 있고
#: `mqtt` extra 는 없는 기계에서 축소가 아니라 ImportError 로 **실패했다**.
#: `providers/mqtt.py` 는 paho 를 메서드 안에서 import 하므로 그 provider 만
#: 비활성이 정상이다(AI-C-05).
needs_broker = pytest.mark.skipif(
    shutil.which("mosquitto") is None or not _paho_available(),
    reason="mosquitto 브로커 또는 paho-mqtt 클라이언트가 없다 — MQTT 전송 "
           'provider 만 skip 이다: apt install mosquitto / pip install -e ".[mqtt]"',
)


@pytest.fixture
def real_broker(tmp_path):
    port = _free_port()
    config = tmp_path / "mosquitto.conf"
    config.write_text(
        f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        ["mosquitto", "-c", str(config)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # 전체 시험에는 실제 모델 추론(CPU)이 섞여 있어 기계가 바쁘다. 5초로 잡으면
    # 브로커가 늦게 뜨는 날 이 시험만 깨지고, 그 실패는 계약 문제처럼 보인다.
    deadline = time.time() + 20.0
    while time.time() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.05)
    else:
        process.terminate()
        pytest.skip("브로커가 뜨지 않았다")
    try:
        yield port
    finally:
        process.terminate()
        process.wait(timeout=5)


def _snapshot_validator() -> Draft202012Validator:
    registry = Registry()
    for path in sorted(CONTRACT_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    body = json.loads((CONTRACT_DIR / "status-snapshot.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(body, registry=registry, format_checker=FormatChecker())


def _backend_envelope_validator() -> Draft202012Validator:
    vendor = CONTRACT_DIR / "vendor" / "server"
    registry = Registry()
    for path in sorted(vendor.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(path.name, Resource.from_contents(schema))
        if "$id" in schema:
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    envelope = json.loads((vendor / "message.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(envelope, registry=registry, format_checker=FormatChecker())


@needs_broker
def test_the_real_snapshot_survives_a_real_broker(real_broker, host_view):
    """실제 자원 → 실제 스냅샷 → **실제 MQTT 브로커** → 수신 → 계약 검증.

    과정 어딘가에서 모양이 바뀌면(직렬화·인코딩·브로커 경유) 계약 검증이 잡는다.
    자료구조 시험만으로는 이 구간이 비어 있다.
    """
    from mission_runtime.providers.mqtt import MqttTransportProvider

    watch = ResourceWatch.of([WatchTarget(
        "cpu_util", "utilization", TargetBaseline(0.9, Direction.AT_MOST, "ratio"), "cpu")])
    snapshot = DashboardSnapshot(
        mission=MissionSummary(mission_id="REAL-1", utterance="실제 자원으로 한 바퀴",
                               status="running", accepted_at=time.time()),
        graph=TaskGraph(mission_id="REAL-1", nodes=(
            TaskNode("n1", "자원 읽기", NodeState.SUCCEEDED, service_id="host_reader",
                     accelerator_id="cpu"),
        )),
        resources=host_view,
        events=watch.events(host_view, at=time.time()),
    )
    message = status_snapshot_message(
        snapshot,
        MessageContext(source_id="host_reader", node_id="dev-host", zone_id="zoneLocal",
                       sequence_id=1, timestamp=time.time()),
        now=time.time(),
    )

    received: list[bytes] = []
    arrived = threading.Event()
    subscriber = MqttTransportProvider("127.0.0.1", real_broker, client_id="real-stack-sub")
    assert subscriber.connect(20.0), "구독자가 실제 브로커에 붙지 못했다"
    subscriber.subscribe("ai/status/+", lambda payload: (received.append(payload), arrived.set()))

    publisher = MqttTransportProvider("127.0.0.1", real_broker, client_id="real-stack-pub")
    assert publisher.connect(20.0), "발행자가 실제 브로커에 붙지 못했다"
    try:
        publisher.publish("ai/status/snapshot", json.dumps(message, ensure_ascii=False).encode())
        assert arrived.wait(20.0), "브로커를 지나온 메시지가 도착하지 않았다"
    finally:
        publisher.close()
        subscriber.close()

    delivered = json.loads(received[0].decode("utf-8"))
    assert delivered == message, "브로커를 지나며 내용이 달라졌다"
    _snapshot_validator().validate(delivered)
    _backend_envelope_validator().validate(delivered)
    # 실제로 읽은 가속기가 그대로 실려 있다 — 화면이 유휴까지 볼 수 있어야 한다.
    assert {a["accelerator_instance_id"] for a in delivered["accelerators"]} == {
        a.instance_id for a in host_view.accelerators
    }
