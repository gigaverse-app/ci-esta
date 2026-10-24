import pytest

from ci_esta.policy.models import Requirement
from ci_esta.policy.resources import (
    KubernetesJobProfile,
    Provider,
    Resource,
    ServiceContainer,
    pick_provider,
    placement_for,
    resolve_pins,
)


def test_preferred_mock_cannot_satisfy_real_server_requirement():
    resource = Resource(
        name="redis",
        providers=[
            Provider(name="fake"),
            Provider(name="ephemeral", capabilities={"real", "lua"}),
        ],
    )
    chosen, reasons = resolve_pins(
        [Requirement(resource="redis", capabilities={"real", "lua"})],
        resources={"redis": resource},
        env_vars={},
        active_env_scope="preview-123",
    )
    assert [item.name for item in chosen] == ["ephemeral"]
    assert not reasons
    assert pick_provider(resource, env_vars={}, active_env_scope="any").name == "fake"


def test_explicit_provider_never_falls_back_or_downgrades_capabilities():
    resource = Resource(name="redis", providers=[Provider(name="fake"), Provider(name="real", capabilities={"lua"})])
    assert (
        pick_provider(resource, env_vars={}, active_env_scope="any", pinned_name="fake", required_capabilities={"lua"})
        is None
    )
    assert pick_provider(resource, env_vars={}, active_env_scope="any", pinned_name="typo") is None


def test_two_pass_resolution_preserves_cluster_secret_placement():
    registry = {
        "service": Resource(
            name="service",
            providers=[
                Provider(
                    name="deployed",
                    cluster_internal=True,
                    env_scope="preview-123",
                    kubernetes_job_profile=KubernetesJobProfile(service="api"),
                )
            ],
        ),
        "model": Resource(name="model", providers=[Provider(name="real", runner_secrets=["MODEL_TOKEN"])]),
    }
    pins = [Requirement(resource="service"), Requirement(resource="model")]
    first, reasons = resolve_pins(pins, resources=registry, env_vars={}, active_env_scope="preview-123")
    assert reasons and first[0].cluster_internal
    providers, reasons = resolve_pins(
        pins, resources=registry, env_vars={}, active_env_scope="preview-123", cluster_mode=True
    )
    assert not reasons
    placement = placement_for(providers)
    assert placement.mode == "kubernetes_job"
    assert placement.secrets == []
    assert placement.cluster_secrets == ["MODEL_TOKEN"]


def test_runner_container_is_not_assumed_available_inside_cluster():
    resource = Resource(
        name="redis",
        providers=[
            Provider(name="ephemeral", service_container=ServiceContainer(service_name="redis", image="redis:7"))
        ],
    )
    assert pick_provider(resource, env_vars={}, active_env_scope="any", cluster_mode=True) is None


@pytest.mark.parametrize(
    "providers",
    [
        [Provider(name="a", env_scope="staging"), Provider(name="b", env_scope="production")],
        [Provider(name="a", runtime_env={"HOST": "one"}), Provider(name="b", runtime_env={"HOST": "two"})],
        [
            Provider(name="a", service_container=ServiceContainer(service_name="db", image="one")),
            Provider(name="b", service_container=ServiceContainer(service_name="db", image="two")),
        ],
    ],
)
def test_conflicting_environments_and_services_cannot_share_placement(providers):
    with pytest.raises(ValueError):
        placement_for(providers)


def test_identical_service_requirements_are_deduplicated():
    service = ServiceContainer(service_name="db", image="postgres:17")
    result = placement_for(
        [Provider(name="a", service_container=service), Provider(name="b", service_container=service)]
    )
    assert result.services == [service]
