"""콘솔 배포 경로가 선언된 실행 번들을 집어 든다 — 그 전에는 집지 않았다.

**이 묶음이 막는 것**: 콘솔에서 보낸 배포가 오케스트레이터 실행영역에서 한 번도
뜰 수 없는 상태. `providers/k3s.py::_start` 는 `params["image"]` 가 없으면
`missing_image` 로 거절하는데, `deployable_for()` 가 기기 식별자만 담아 보내고
있었다. 로컬 supervisor 는 params 를 **아예 읽지 않으므로** 시험은 통과했고 그래서
이 구멍이 보이지 않았다. 실제 클러스터에 보내 보고서야 드러났다.

이미지의 주인은 번들 선언 하나다. 콘솔이 이미지 이름을 손으로 짜 넣으면 주인이
둘이 되고, 번들을 고쳐도 콘솔 경로만 옛 이미지를 계속 보낸다.

implements: AI-B-02, AI-B-05, AI-B-11, AI-C-16, AI-C-05
tests: image flows from the declaration, digest pinning, airgap input, no-bundle
       fallback still refused by the orchestrator, broken declaration surfaces
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from providers.k3s import K3sControlProvider  # noqa: E402
from runtime.deployment_bundle import BundleRegistry  # noqa: E402
from tools.fms_console.deployment import (  # noqa: E402
    DEFAULT_BUNDLE_PATH,
    bundle_registry,
    deployable_for,
)

#: 이 kubectl 은 없다 — provider 가 클러스터에 **아무것도 만들지 않는다.**
#: 우리가 보려는 것은 거절 사유가 `missing_image` 가 아니라는 사실뿐이다.
ABSENT_KUBECTL = "kubectl-definitely-absent-for-this-test"

BUNDLED_KIND = "perception.classify"
UNBUNDLED_KIND = "perception.no_such_capability"


def test_the_declared_bundles_are_actually_found():
    """경로가 틀려도 빈 등록부가 나오면 "선언이 없는 정상 배치" 로 숨는다.

    실제로 한 번 숨었다 — `parents[1]` 이 `tools/` 를 가리키고 있었고, 이미지가
    여전히 흐르지 않는데도 아무 사유도 나오지 않았다.
    """
    assert DEFAULT_BUNDLE_PATH.is_file(), f"번들 선언이 있어야 한다: {DEFAULT_BUNDLE_PATH}"
    assert bundle_registry().ids(), "선언을 읽었는데 비어 있으면 경로가 틀린 것이다"


def test_the_image_comes_from_the_declaration_not_from_the_console():
    """이미지의 주인은 번들 하나다."""
    deployable = deployable_for(BUNDLED_KIND, "go1-001")

    image = deployable.control_params.get("image")
    assert image, "이 연결이 빠져 있던 동안 이 칸이 비어 있었다"

    declared = bundle_registry().for_kind(BUNDLED_KIND)[0]
    assert image == declared.image.reference, "선언된 참조 그대로여야 한다"


def test_the_image_is_pinned_by_digest():
    """태그는 같은 이름이 다른 내용을 가리킬 수 있다 — 재현성이 사라진다(AI-B-02)."""
    declared = bundle_registry().for_kind(BUNDLED_KIND)[0]

    assert declared.image.pinned
    assert declared.image.digest
    assert deployable_for(BUNDLED_KIND, "go1-001").control_params["require_image_digest"]


def test_the_image_registry_reaches_the_airgap_judgement_as_a_required_dependency():
    """이미지를 못 받으면 축소 운용이 아니라 **아예 뜨지 못한다**(AI-C-16).

    선택 의존으로 적으면 "꺼진 선택 기능" 으로 조용히 넘어가고, 배치는 성공했는데
    아무것도 돌지 않는 상태가 된다.
    """
    deployable = deployable_for(BUNDLED_KIND, "go1-001")

    image_deps = [d for d in deployable.external_dependencies
                  if d.purpose == "container_image"]
    assert len(image_deps) == 1
    assert image_deps[0].optional is False
    assert image_deps[0].endpoint


def test_the_device_identifier_still_rides_along():
    """번들을 집어 들면서 기기 식별자를 잃으면 어느 기기에 올릴지 사라진다."""
    assert deployable_for(BUNDLED_KIND, "pi6").control_params["device_id"] == "pi6"
    assert deployable_for(BUNDLED_KIND, "pi6").deployable_id == f"{BUNDLED_KIND}@pi6"


def test_a_bundled_kind_is_no_longer_refused_for_a_missing_image():
    """**이것이 이 파일의 요점이다.** 없는 kubectl 을 써서 클러스터는 건드리지 않는다.

    거절은 여전히 나올 수 있지만(오케스트레이터가 없으니) 그 사유가
    `missing_image` 면 안 된다 — 이미지는 이제 선언에서 온다.
    """
    deployable = deployable_for(BUNDLED_KIND, "go1-001")
    provider = K3sControlProvider(kubectl=ABSENT_KUBECTL)

    result = provider.request("start", deployable.deployable_id, deployable.control_params)

    assert result.rejection_reason != "missing_image"


def test_a_kind_with_no_bundle_keeps_the_old_shape_and_is_still_refused():
    """선언이 없는 배치는 정상이다(AI-C-05). 그때 오케스트레이터가 거절하는 것도 맞다.

    이미지 없이 띄우면 무엇이 돌고 있는지 아무도 모르게 된다.
    """
    deployable = deployable_for(UNBUNDLED_KIND, "go1-001")
    assert "image" not in deployable.control_params

    provider = K3sControlProvider(kubectl=ABSENT_KUBECTL)
    result = provider.request("start", deployable.deployable_id, deployable.control_params)

    assert result.accepted is False
    assert result.rejection_reason == "missing_image", (
        "선언이 없으면 이미지가 없다는 사실이 사유로 나와야 한다")


def test_the_local_execution_zone_takes_the_same_declaration_unchanged():
    """같은 선언이 양쪽 실행영역에서 그대로 쓰인다(AI-B-11).

    로컬 supervisor 는 params 를 읽지 않으므로 이미지가 있어도 없어도 돈다 — 그
    사실이 바로 이 구멍을 숨겼으므로, 양쪽이 같은 선언을 받는다는 것만 고정한다.
    """
    from execution.control import LocalControlSupervisor

    deployable = deployable_for(BUNDLED_KIND, "go1-001")
    supervisor = LocalControlSupervisor()

    result = supervisor.request("start", deployable.deployable_id, deployable.control_params)

    assert result.accepted, "로컬 실행영역은 같은 선언으로 그대로 돈다"


def test_a_missing_declaration_file_is_normal_but_a_broken_one_is_not(tmp_path):
    """파일이 없는 것과 선언이 깨진 것은 다른 사실이다."""
    assert bundle_registry(tmp_path / "없는파일.json").ids() == ()

    broken = tmp_path / "broken.json"
    broken.write_text('{"bundles": [{"bundle_id": "x"}]}', encoding="utf-8")
    with pytest.raises((ValueError, KeyError)):
        bundle_registry(broken)


def test_an_injected_registry_wins_so_a_deployment_can_be_tested_in_isolation(tmp_path):
    """선언 자리를 주입할 수 있어야 시험이 운영 선언에 묶이지 않는다."""
    declaration = json.loads(DEFAULT_BUNDLE_PATH.read_text(encoding="utf-8"))
    only_one = {"bundles": [b for b in declaration["bundles"]
                            if b["capability_kind"] == BUNDLED_KIND]}
    path = tmp_path / "one.json"
    path.write_text(json.dumps(only_one, ensure_ascii=False), encoding="utf-8")

    pool = BundleRegistry.from_file(path)
    deployable = deployable_for(BUNDLED_KIND, "go1-001", registry=pool)

    assert deployable.control_params["image"]
    assert deployable_for(UNBUNDLED_KIND, "go1-001", registry=pool).control_params.keys() \
        == {"device_id"}


def test_the_airgap_judgement_now_blocks_an_undeclared_image_registry():
    """두 번째 공백 — AI-C-16 은 "**이미지**·모델·패키지·규칙" 에서 이미지를 먼저
    적는데, 그 이미지가 어디서 오는지는 배치 전 판정에 **들어가지도 않았다.**

    판정 기구를 새로 만들지 않았다. 번들이 저장소를 비선택 외부 의존 1건으로
    내보내고 기존 `AirgapPolicy` 가 그것을 본다.
    """
    from runtime.airgap import AirgapPolicy, AssetResolver

    deployable = deployable_for(BUNDLED_KIND, "go1-001")
    dependencies = list(deployable.external_dependencies)
    registry_endpoint = next(d.endpoint for d in dependencies
                             if d.purpose == "container_image")

    declared_inside = AirgapPolicy(
        AssetResolver(internal_hosts=frozenset({registry_endpoint})))
    assert declared_inside.evaluate(deployable.deployable_id, dependencies).placeable

    not_declared = AirgapPolicy(AssetResolver(internal_hosts=frozenset({"other.internal"})))
    verdict = not_declared.evaluate(deployable.deployable_id, dependencies)

    assert verdict.placeable is False
    assert registry_endpoint in verdict.blocking_dependencies
    assert verdict.disabled_optional == (), (
        "이미지는 선택 의존이 아니다 — 못 받으면 축소가 아니라 아예 뜨지 못한다")


def test_an_open_network_profile_is_not_blocked_by_the_image_registry():
    """폐쇄망은 **모든 배포의 필수조건이 아니다**(AI-C-16). 열린 배치는 그대로 간다."""
    from runtime.airgap import AirgapPolicy, AssetResolver

    deployable = deployable_for(BUNDLED_KIND, "go1-001")
    open_profile = AirgapPolicy(AssetResolver(), closed_network=False)

    assert open_profile.evaluate(deployable.deployable_id,
                                 list(deployable.external_dependencies)).placeable
