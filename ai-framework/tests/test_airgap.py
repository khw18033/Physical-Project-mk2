"""tests for: AI-C-16, AI-C-09, AI-B-09
covers: internal-only asset procurement, public egress refused before
        placement, optional external services degrade instead of blocking
"""

import pytest

from ai_framework.runtime.airgap import (
    AirgapPolicy,
    AirgapViolation,
    AssetRef,
    AssetResolver,
    ExternalDependency,
)

INTERNAL = AssetResolver(
    base_locations={
        "image": "https://registry.internal.example/ai",
        "model": "https://artifacts.internal.example/models",
        "generic": "/var/lib/ai-framework/assets",
    },
    internal_hosts=frozenset({"registry.internal.example", "artifacts.internal.example"}),
    internal_suffixes=frozenset({".internal"}),
)


def test_assets_resolve_against_the_internal_repository():
    resolved = INTERNAL.resolve(AssetRef("detector", kind="model", version="3"))

    assert resolved.internal is True
    assert resolved.location.startswith("https://artifacts.internal.example/models/")
    assert resolved.location.endswith("detector:3")


def test_a_bare_filesystem_path_counts_as_internal():
    resolved = INTERNAL.resolve(AssetRef("zone-rules", kind="generic"))

    assert resolved.internal is True


def test_an_asset_kind_with_no_internal_source_is_refused():
    resolver = AssetResolver(base_locations={}, internal_hosts=frozenset())

    with pytest.raises(AirgapViolation):
        resolver.resolve(AssetRef("detector", kind="model"))


def test_public_repository_is_refused_in_a_closed_network():
    public = AssetResolver(
        base_locations={"image": "https://public-registry.example/library"},
        internal_hosts=frozenset({"registry.internal.example"}),
    )

    with pytest.raises(AirgapViolation):
        public.resolve(AssetRef("python", kind="image", version="3.10"))


def test_public_repository_is_allowed_only_when_explicitly_opted_in():
    development = AssetResolver(
        base_locations={"image": "https://public-registry.example/library"},
        internal_hosts=frozenset(),
        allow_public=True,
    )

    resolved = development.resolve(AssetRef("python", kind="image"))

    assert resolved.internal is False  # 사실을 숨기지 않는다


def test_an_internal_domain_suffix_covers_hosts_not_listed_individually():
    """폐쇄망은 보통 호스트 목록이 아니라 도메인 대역을 소유한다."""
    assert INTERNAL.is_internal("mqtt://edge-broker.internal:1883") is True
    assert INTERNAL.is_internal("https://someone.external.example") is False


def test_internal_host_classification():
    assert INTERNAL.is_internal("https://registry.internal.example/ai/x") is True
    assert INTERNAL.is_internal("https://huggingface.co/model") is False
    assert INTERNAL.is_internal("/opt/models/detector.onnx") is True
    assert INTERNAL.is_internal("localhost:8080/x") is True


# --- placement-time policy -------------------------------------------------


def test_a_unit_needing_mandatory_public_egress_cannot_be_placed():
    policy = AirgapPolicy(INTERNAL)

    verdict = policy.evaluate(
        "cloud-vlm-analyzer",
        [ExternalDependency("https://api.vendor.example/v1", purpose="VLM", optional=False)],
    )

    assert verdict.placeable is False
    assert verdict.blocking_dependencies == ("https://api.vendor.example/v1",)


def test_an_optional_external_service_only_disables_itself():
    """원칙 #18: 외부 서비스 provider는 항상 선택 기능이다."""
    policy = AirgapPolicy(INTERNAL)

    verdict = policy.evaluate(
        "perception-with-optional-vlm",
        [
            ExternalDependency("https://artifacts.internal.example/models", optional=False),
            ExternalDependency("https://api.vendor.example/v1", purpose="VLM", optional=True),
        ],
    )

    assert verdict.placeable is True
    assert verdict.disabled_optional == ("https://api.vendor.example/v1",)


def test_a_unit_with_only_internal_dependencies_is_fully_placeable():
    policy = AirgapPolicy(INTERNAL)

    verdict = policy.evaluate(
        "zone-perception",
        [ExternalDependency("https://registry.internal.example/ai", optional=False)],
    )

    assert verdict.placeable is True
    assert verdict.disabled_optional == ()


def test_assert_placeable_raises_before_placement_not_at_runtime():
    policy = AirgapPolicy(INTERNAL)

    with pytest.raises(AirgapViolation):
        policy.assert_placeable(
            "cloud-only", [ExternalDependency("https://api.vendor.example", optional=False)]
        )


def test_an_open_network_profile_places_everything():
    policy = AirgapPolicy(INTERNAL, closed_network=False)

    verdict = policy.evaluate(
        "cloud-vlm-analyzer",
        [ExternalDependency("https://api.vendor.example/v1", optional=False)],
    )

    assert verdict.placeable is True


def test_the_framework_itself_declares_no_mandatory_public_dependency():
    """이 프레임워크의 기본 구성은 폐쇄망에서 그대로 기동되어야 한다."""
    policy = AirgapPolicy(INTERNAL)

    verdict = policy.evaluate(
        "ai-framework-core",
        [
            ExternalDependency("mqtt://edge-broker.internal:1883", optional=False),
            ExternalDependency("kafka://server.internal:9092", optional=False),
            ExternalDependency("/var/lib/ai-framework/assets", optional=False),
        ],
    )

    assert verdict.placeable is True
