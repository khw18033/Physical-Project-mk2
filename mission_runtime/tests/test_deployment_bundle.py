"""새 기능·새 모델이 **선언 한 건**으로 배포되는 경로.

implements: AI-B-02, AI-B-11, AI-C-16
tests: 선언 → Deployable, 이미지가 실제로 provider 에 닿음, 폐쇄망에서 공개 저장소
       거절, digest 고정, 비밀 거절, 실행영역마다 다른 오케스트레이터, 자산 조달
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.execution.control import LocalControlSupervisor
from mission_runtime.providers.k3s import K3sControlProvider
from mission_runtime.runtime.airgap import AirgapPolicy, AirgapViolation, AssetResolver
from mission_runtime.runtime.clusters import ClusterBinding
from mission_runtime.runtime.deployment_bundle import (
    BUNDLES_FILE,
    IMPLICIT_REGISTRY,
    PURPOSE_CONTAINER_IMAGE,
    REASON_DUPLICATE_BUNDLE,
    REASON_IMAGE_NOT_PINNED,
    REASON_MISSING_FIELD,
    REASON_SECRET_IN_DECLARATION,
    REASON_UNKNOWN_BUNDLE,
    BundleDeclarationError,
    BundleRegistry,
    DeploymentBundle,
    ImageRef,
    bundles_from_dict,
    declared_assets,
    deployables_for,
    load_bundles,
)
from mission_runtime.runtime.mlops_pipeline import (
    REFUSE_EGRESS_REQUIRED,
    DeploymentPhase,
    MlopsPipeline,
)
from mission_runtime.runtime.model_assignment import (
    DeviceProfile,
    MissionRequirement,
    ModelVersion,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
BUNDLES_PATH = PROJECT_DIR / "deploy" / BUNDLES_FILE

KIND = "perception.detect_ovd"
DIGEST = "sha256:" + "0" * 64


# --- helpers ----------------------------------------------------------------


def _declaration(**over) -> dict:
    row = {
        "bundle_id": "detector",
        "capability_kind": KIND,
        "image": f"registry.internal:5000/detector@{DIGEST}",
        "required_tags": ["zone-edge"],
    }
    row.update(over)
    return row


def _bundle(**over) -> DeploymentBundle:
    return bundles_from_dict({"bundles": [_declaration(**over)]})[0]


def _resolver(*, hosts=("registry.internal:5000",), closed=True) -> AssetResolver:
    return AssetResolver(
        base_locations={"generic": "registry.internal:5000",
                        "model": "registry.internal:5000/models"},
        internal_hosts=frozenset(hosts),
    )


#: 이 파일이 쓰는 단일 버전. 계보가 인용하는 값과 한 자리에서 묶어 둔다.
_VERSION_ID = "1"


def _approved_lineage(cites: str = _VERSION_ID) -> LearningLineage:
    """계보는 **어느 버전에 대한 것인지**를 인용해야 한다(AI-L-08).

    기본값이 `_version()` 이 내는 버전과 같아서 이 파일의 호출들은 그대로
    통과한다. 다른 버전을 인용하면 `plan()` 이 lineage_never_cited_this_version
    으로 거절한다 — 승인은 받았으나 **다른 것에 대한 승인**인 계보를 막는 관문이다.
    """
    lineage = LearningLineage("lin-1", actor="op", evidence_ref=cites, reason="candidate")
    while lineage.state is not LearningState.APPROVED:
        lineage.advance(actor="op", evidence_ref=cites, reason="stage")
    return lineage


def _version() -> ModelVersion:
    return ModelVersion(model_id="detector", version=_VERSION_ID, capability_kind=KIND,
                        quality=0.9, latency_ms=20.0, memory_mb=256.0)


DEVICE = DeviceProfile("dev-1", hw_tags=frozenset({"zone-edge"}), memory_mb=2048.0)
REQUIREMENT = MissionRequirement("mission-1", KIND, min_quality=0.5)


class _FakeKubectl(K3sControlProvider):
    """`kubectl` 을 돌리지 않고 **어떤 인자가 갔는지** 기록한다.

    여기서 검증하려는 것은 클러스터의 동작이 아니라 **선언한 이미지가 provider 에
    실제로 닿는가**다. 실제 클러스터 시험은 `tests/test_k3s_control.py` 가 한다.
    """

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.calls: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    def _run(self, args, timeout=None, stdin=None):
        self.calls.append(list(args))
        # `get deployment` 는 없는 것으로 답해 생성 경로로 보낸다.
        code = 1 if args[:2] == ["get", "deployment"] else 0
        return subprocess.CompletedProcess(args, code, stdout="", stderr="")


# --- 이미지 참조 -------------------------------------------------------------


def test_an_image_without_a_registry_resolves_to_the_public_one():
    """저장소를 적지 않은 참조는 공개 저장소를 가리킨다.

    그것이 폐쇄망에서 조용히 통과하면 안 되므로 명시적인 이름으로 바꿔 둔다.
    """
    assert ImageRef("detector:1").registry == IMPLICIT_REGISTRY
    assert ImageRef("library/detector:1").registry == IMPLICIT_REGISTRY
    assert ImageRef(f"registry.internal:5000/detector@{DIGEST}").registry == \
        "registry.internal:5000"
    assert ImageRef(f"localhost:5000/detector@{DIGEST}").registry == "localhost:5000"
    assert ImageRef(f"ghcr.io/org/detector@{DIGEST}").registry == "ghcr.io"


def test_pinning_is_read_from_the_reference_not_declared():
    pinned = ImageRef(f"registry.internal:5000/detector@{DIGEST}")
    assert pinned.pinned and pinned.digest == DIGEST and pinned.tag is None
    tagged = ImageRef("registry.internal:5000/detector:1.4")
    assert not tagged.pinned and tagged.tag == "1.4" and tagged.digest is None


def test_an_empty_image_reference_is_refused():
    with pytest.raises(BundleDeclarationError) as error:
        ImageRef("  ")
    assert REASON_MISSING_FIELD in str(error.value)


# --- 선언 → 선언 ------------------------------------------------------------


def test_a_declaration_becomes_a_deployable_with_the_image_the_provider_needs():
    """`providers/k3s.py::_start` 는 `params["image"]` 가 없으면 거절한다.

    선언 경로가 그 칸을 채우지 않으면 K3s 실행영역에서 **한 번도 뜨지 못한다.**
    로컬 supervisor 는 params 를 아예 읽지 않으므로 이 구멍은 조용하다.
    """
    deployable = _bundle().to_deployable()
    assert deployable.control_params["image"].endswith(DIGEST)
    assert deployable.control_params["require_image_digest"] is True
    assert deployable.capability_kind == KIND
    assert deployable.placement.required_tags == frozenset({"zone-edge"})


def test_the_declared_image_actually_reaches_the_orchestrator():
    """선언 → Deployable → 파이프라인 → provider 까지 이미지가 끊기지 않는다."""
    kubectl = _FakeKubectl(namespace="test")
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", kubectl, frozenset({"zone-edge"}))])
    pipeline.register_version(_version())
    status = pipeline.submit(_bundle().to_deployable(), DEVICE, REQUIREMENT,
                             lineage=_approved_lineage(), actor="op", evidence_ref="ev")

    assert status.phase is DeploymentPhase.PLACED
    created = [c for c in kubectl.calls if c[:2] == ["create", "deployment"]]
    assert created, kubectl.calls
    assert any(arg.startswith("--image=") and DIGEST in arg for arg in created[0])


def test_a_deployable_without_a_bundle_is_still_refused_by_the_orchestrator():
    """선언을 거치지 않으면 여전히 `missing_image` 다 — 그것이 메운 공백의 증거다."""
    from mission_runtime.runtime.mlops_pipeline import Deployable
    from mission_runtime.runtime.clusters import PlacementRequest

    kubectl = _FakeKubectl(namespace="test")
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", kubectl, frozenset({"zone-edge"}))])
    pipeline.register_version(_version())
    bare = Deployable("detector", KIND,
                      placement=PlacementRequest(required_tags=frozenset({"zone-edge"})))
    status = pipeline.submit(bare, DEVICE, REQUIREMENT, lineage=_approved_lineage(),
                             actor="op", evidence_ref="ev")
    assert status.phase is DeploymentPhase.REFUSED
    assert "missing_image" in status.reason


def test_the_same_declaration_runs_on_two_execution_areas_with_different_control_planes():
    """AI-B-11: 모든 실행영역이 같은 오케스트레이터를 설치해야 한다는 전제는 없다.

    같은 선언이 K3s 영역과 로컬 supervisor 영역 어느 쪽에서도 쓰인다 — 로컬 쪽은
    `control_params` 를 읽지도 않는다.
    """
    kubectl = _FakeKubectl(namespace="test")
    deployable = _bundle(required_tags=["zone-edge"]).to_deployable()
    for provider in (kubectl, LocalControlSupervisor()):
        pipeline = MlopsPipeline(
            [ClusterBinding("area", provider, frozenset({"zone-edge"}))])
        pipeline.register_version(_version())
        status = pipeline.submit(deployable, DEVICE, REQUIREMENT,
                                 lineage=_approved_lineage(), actor="op",
                                 evidence_ref="ev")
        assert status.phase is DeploymentPhase.PLACED


def test_the_device_id_is_a_deployment_value_not_a_declaration():
    """기기 이름을 선언에 적으면 같은 기능을 다른 기기에 올릴 때마다 선언이 늘어난다."""
    one, = deployables_for([_bundle()], device_id="dev-7")
    assert one.deployable_id == "detector@dev-7"
    assert one.control_params["device_id"] == "dev-7"
    plain, = deployables_for([_bundle()])
    assert plain.deployable_id == "detector"
    assert "device_id" not in plain.control_params


# --- 폐쇄망 (AI-C-16) -------------------------------------------------------


def test_the_image_registry_is_a_non_optional_external_dependency():
    """이미지를 못 받으면 축소 운용이 아니라 아예 뜨지 못한다.

    선택 의존으로 적으면 "꺼진 선택 기능" 으로 조용히 넘어가고, 배치는 성공했는데
    아무것도 돌지 않는 상태가 된다.
    """
    deployable = _bundle().to_deployable()
    image_deps = [d for d in deployable.external_dependencies
                  if d.purpose == PURPOSE_CONTAINER_IMAGE]
    assert len(image_deps) == 1
    assert image_deps[0].optional is False
    assert image_deps[0].endpoint == "registry.internal:5000"


def test_a_public_registry_is_refused_before_placement_in_a_closed_network():
    """AI-C-16 은 '이미지·모델·패키지·규칙' 에서 **이미지를 먼저** 적는다.

    이 거절은 기존 `AirgapPolicy` 가 내는 것이고 이 모듈이 다시 판정하지 않는다.
    """
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", LocalControlSupervisor(),
                        frozenset({"zone-edge"}))],
        airgap=AirgapPolicy(_resolver(), closed_network=True))
    pipeline.register_version(_version())
    public = _bundle(image=f"docker.io/library/detector@{DIGEST}").to_deployable()
    plan = pipeline.plan(public, DEVICE, REQUIREMENT, lineage=_approved_lineage())

    assert not plan.would_place
    assert plan.refusal_reason == REFUSE_EGRESS_REQUIRED
    assert "docker.io" in plan.egress.blocking_dependencies


def test_an_implicit_registry_is_refused_too():
    """저장소를 적지 않은 참조가 조용히 통과하면 폐쇄망 점검이 무의미하다."""
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", LocalControlSupervisor(),
                        frozenset({"zone-edge"}))],
        airgap=AirgapPolicy(_resolver(), closed_network=True))
    pipeline.register_version(_version())
    plan = pipeline.plan(_bundle(image=f"detector@{DIGEST}").to_deployable(),
                         DEVICE, REQUIREMENT, lineage=_approved_lineage())
    assert plan.refusal_reason == REFUSE_EGRESS_REQUIRED


def test_an_internal_registry_places_in_the_same_closed_profile():
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", LocalControlSupervisor(),
                        frozenset({"zone-edge"}))],
        airgap=AirgapPolicy(_resolver(), closed_network=True))
    pipeline.register_version(_version())
    plan = pipeline.plan(_bundle().to_deployable(), DEVICE, REQUIREMENT,
                         lineage=_approved_lineage())
    assert plan.would_place
    assert plan.egress.blocking_dependencies == ()


def test_an_optional_external_service_is_reduced_not_refused():
    """AI-C-16: 외부 서비스는 선택 기능이고 없으면 그 기능만 비활성화한다."""
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", LocalControlSupervisor(),
                        frozenset({"zone-edge"}))],
        airgap=AirgapPolicy(_resolver(), closed_network=True))
    pipeline.register_version(_version())
    bundle = _bundle(external_dependencies=[
        {"endpoint": "https://vlm.example.com", "purpose": "hypothesis",
         "optional": True}])
    plan = pipeline.plan(bundle.to_deployable(), DEVICE, REQUIREMENT,
                         lineage=_approved_lineage())
    assert plan.would_place
    assert "https://vlm.example.com" in plan.disabled_optional


def test_an_open_network_profile_places_a_public_registry():
    """폐쇄망은 모든 배포의 필수조건이 아니다(원칙 #18)."""
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", LocalControlSupervisor(),
                        frozenset({"zone-edge"}))],
        airgap=AirgapPolicy(_resolver(), closed_network=False))
    pipeline.register_version(_version())
    plan = pipeline.plan(_bundle(image=f"ghcr.io/org/detector@{DIGEST}").to_deployable(),
                         DEVICE, REQUIREMENT, lineage=_approved_lineage())
    assert plan.would_place


def test_declared_assets_resolve_to_the_internal_repository():
    """가중치는 이미지에 굽지 않고 내부 저장소에서 조달한다."""
    bundle = _bundle(assets=[{"asset_id": "model:detector", "kind": "model",
                              "version": "2"}])
    resolved = bundle.resolve_assets(_resolver())
    assert len(resolved) == 1
    assert resolved[0].internal
    assert resolved[0].location.startswith("registry.internal:5000/models/")
    assert "model:detector" in declared_assets([bundle])[0].asset_id


def test_an_asset_that_resolves_outside_the_closed_network_is_refused():
    outside = AssetResolver(base_locations={"model": "https://models.example.com"},
                            internal_hosts=frozenset({"registry.internal:5000"}))
    bundle = _bundle(assets=[{"asset_id": "model:detector", "kind": "model"}])
    with pytest.raises(AirgapViolation):
        bundle.resolve_assets(outside)


def test_the_registry_lists_external_registries_before_deployment():
    """배치 **전에** 점검할 수 있어야 한다(AI-C-16)."""
    registry = BundleRegistry(bundles_from_dict({"bundles": [
        _declaration(),
        _declaration(bundle_id="other", image=f"docker.io/x/y@{DIGEST}"),
    ]}))
    assert registry.external_registries(_resolver()) == (IMPLICIT_REGISTRY,)


# --- 재현성 (AI-B-02) -------------------------------------------------------


def test_a_tag_only_image_is_refused_by_default():
    """태그는 같은 이름이 다른 내용을 가리킬 수 있어 재현의 근거가 되지 못한다."""
    with pytest.raises(BundleDeclarationError) as error:
        _bundle(image="registry.internal:5000/detector:1.4")
    assert REASON_IMAGE_NOT_PINNED in str(error.value)


def test_an_explicit_exemption_is_allowed_but_visible():
    """면제가 조용히 넘어가지 않아야 재현성 이탈을 배치 전에 볼 수 있다."""
    registry = BundleRegistry(bundles_from_dict({"bundles": [_declaration(
        image="registry.internal:5000/detector:1.4", require_digest=False)]}))
    assert registry.unpinned() == ("detector",)
    assert registry.bundles[0].to_deployable().control_params[
        "require_image_digest"] is False


def test_a_secret_value_in_the_declaration_is_refused():
    """AI-B-02: 자격증명·비밀정보를 이미지와 구성에 넣지 않는다."""
    for row in ({"registry_password": "x"},
                {"security_context": {"api_key": "x"}},
                {"external_dependencies": [{"endpoint": "a", "token": "x"}]}):
        with pytest.raises(BundleDeclarationError) as error:
            _bundle(**row)
        assert REASON_SECRET_IN_DECLARATION in str(error.value)


def test_pull_secrets_and_service_accounts_carry_names_only():
    bundle = _bundle(image_pull_secrets=["internal-registry"],
                     service_account="runner")
    params = bundle.to_deployable().control_params
    assert params["image_pull_secrets"] == ["internal-registry"]
    assert params["service_account"] == "runner"


# --- 선언 파일 ---------------------------------------------------------------


def test_a_duplicate_bundle_id_is_refused():
    """중복을 조용히 덮어쓰면 무엇이 올라가는가가 파일 순서에 달린다."""
    with pytest.raises(BundleDeclarationError) as error:
        bundles_from_dict({"bundles": [_declaration(), _declaration()]})
    assert REASON_DUPLICATE_BUNDLE in str(error.value)


def test_a_missing_required_field_is_refused():
    for key in ("bundle_id", "capability_kind", "image"):
        row = _declaration()
        row.pop(key)
        with pytest.raises(BundleDeclarationError) as error:
            bundles_from_dict({"bundles": [row]})
        assert REASON_MISSING_FIELD in str(error.value)


def test_an_absent_declaration_file_is_an_empty_registry_not_a_failure(tmp_path):
    """배포 관리 기능이 없는 실행영역에서 이 경로는 그냥 비어 있어야 한다(AI-C-05)."""
    assert load_bundles(tmp_path / "nope.json") == ()
    assert BundleRegistry.from_file(tmp_path / "nope.json").ids() == ()


def test_a_broken_declaration_file_is_refused(tmp_path):
    path = tmp_path / BUNDLES_FILE
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(BundleDeclarationError):
        load_bundles(path)


def test_unknown_bundle_lookup_says_so():
    registry = BundleRegistry(bundles_from_dict({"bundles": [_declaration()]}))
    with pytest.raises(KeyError) as error:
        registry.get("nope")
    assert REASON_UNKNOWN_BUNDLE in str(error.value)


def test_bundles_are_found_by_capability_not_by_name():
    registry = BundleRegistry(bundles_from_dict({"bundles": [
        _declaration(),
        _declaration(bundle_id="other", capability_kind="perception.classify"),
    ]}))
    assert [b.bundle_id for b in registry.for_kind(KIND)] == ["detector"]
    assert registry.for_kind("nothing.here") == ()


# --- 저장소에 들어 있는 선언 파일 -------------------------------------------


def test_the_shipped_declaration_file_loads_and_is_pinned():
    """새 기능이 선언 한 건이라는 주장을 실제 파일로 확인한다."""
    registry = BundleRegistry.from_file(BUNDLES_PATH)
    assert registry.ids()
    assert registry.unpinned() == ()
    for bundle in registry.bundles:
        assert bundle.image.pinned
        deployable = bundle.to_deployable()
        assert deployable.control_params["image"] == bundle.image.reference


def test_adding_a_bundle_to_the_shipped_file_needs_no_code_change(tmp_path):
    """선언을 한 건 더해도 어느 모듈도 고치지 않는다(AI-B-09 와 같은 확장 방식)."""
    raw = json.loads(BUNDLES_PATH.read_text(encoding="utf-8"))
    before = len(bundles_from_dict(raw))
    raw["bundles"].append(_declaration(bundle_id="a-brand-new-function",
                                       capability_kind="perception.something_new"))
    after = bundles_from_dict(raw)
    assert len(after) == before + 1
    fresh = [b for b in after if b.bundle_id == "a-brand-new-function"][0]
    assert fresh.to_deployable().capability_kind == "perception.something_new"


def test_the_shipped_file_declares_an_internal_registry():
    """현장 자료이지만 예시가 공개 저장소를 가리키면 폐쇄망 점검이 무의미하다."""
    registry = BundleRegistry.from_file(BUNDLES_PATH)
    assert registry.external_registries(_resolver()) == ()
