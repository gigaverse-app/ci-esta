"""Admission invariants across Python, browser and operational suites."""

import pytest

from ci_esta.policy import Policy, Request, Work, plan
from ci_esta.policy.models import Profile


def policy() -> Policy:
    return Policy(
        profiles={
            "pr": Profile(occasions={"pr", "push"}, include={"unit", "integration"}),
            "thorough": Profile(occasions={"pr", "manual"}, include={"unit", "integration", "paid"}),
            "weekly": Profile(occasions={"schedule", "manual"}, include={"*"}, scope="all"),
            "probe": Profile(occasions={"manual"}, include={"*"}, scope="explicit"),
            "deployment": Profile(
                occasions={"deployment"},
                include={"smoke"},
                scope="all",
                require_deployment=True,
                environments={"staging"},
            ),
        }
    )


INVENTORY = (
    Work(id="bun-unit", tags={"unit"}),
    Work(id="due-conformance", tags={"integration"}),
    Work(id="llm", tags={"paid"}),
    Work(id="broadcast", tags={"live"}, effects={"publish"}),
    Work(id="smoke", tags={"smoke"}),
)


def test_affected_does_not_authorize_paid_or_visible_work():
    result = plan(
        policy(),
        Request(profile="pr", occasion="pr", revision="abc", affected={work.id for work in INVENTORY}),
        INVENTORY,
    )
    assert [item.work.id for item in result.runnable] == ["bun-unit", "due-conformance"]


def test_unknown_impact_broadens_only_permitted_work():
    result = plan(policy(), Request(profile="pr", occasion="pr", revision="abc"), INVENTORY)
    assert result.fallback
    assert [item.work.id for item in result.runnable] == ["bun-unit", "due-conformance"]


def test_empty_affected_scope_selects_nothing():
    result = plan(policy(), Request(profile="pr", occasion="pr", revision="abc", affected=set()), INVENTORY)
    assert not result.runnable
    assert not result.fallback


def test_scheduled_checks_ignore_unchanged_code_but_preserve_effect_permissions():
    result = plan(policy(), Request(profile="weekly", occasion="schedule", revision="abc", affected=set()), INVENTORY)
    assert {item.work.id for item in result.runnable} == {"bun-unit", "due-conformance", "llm", "smoke"}
    assert all(item.fresh for item in result.runnable)


def test_explicit_probe_overrides_impact_without_expanding_requested_scope():
    result = plan(
        policy(),
        Request(profile="probe", occasion="manual", revision="abc", affected=set(), requested={"llm"}),
        INVENTORY,
    )
    assert [item.work.id for item in result.runnable] == ["llm"]


@pytest.mark.parametrize("requested", [{"typo"}, {"broadcast"}, set()])
def test_invalid_or_disallowed_explicit_scope_is_an_error(requested):
    with pytest.raises(ValueError):
        plan(policy(), Request(profile="probe", occasion="manual", revision="abc", requested=requested), INVENTORY)


@pytest.mark.parametrize("environment,deployed", [(None, None), ("staging", "old"), ("production", "abc")])
def test_deployment_requires_matching_revision_and_environment(environment, deployed):
    result = plan(
        policy(),
        Request(
            profile="deployment",
            occasion="deployment",
            revision="abc",
            environment=environment,
            deployed_revision=deployed,
        ),
        INVENTORY,
    )
    assert not result.runnable
    assert [item.work.id for item in result.unavailable] == ["smoke"]


def test_matching_deployment_runs_fresh():
    result = plan(
        policy(),
        Request(
            profile="deployment", occasion="deployment", revision="abc", environment="staging", deployed_revision="abc"
        ),
        INVENTORY,
    )
    assert [item.work.id for item in result.runnable] == ["smoke"]
    assert result.runnable[0].fresh


def test_budget_preserves_cleanup_and_never_weakens_test_timeout():
    configured = Policy(
        profiles={"live": Profile(occasions={"manual"}, include={"live"}, budget_seconds=120, reserve_seconds=30)}
    )
    result = plan(
        configured,
        Request(profile="live", occasion="manual", revision="abc"),
        (
            Work(id="short", tags={"live"}, timeout_seconds=20),
            Work(id="long", tags={"live"}, timeout_seconds=200),
        ),
    )
    assert [item.timeout_seconds for item in result.runnable] == [20, 90]


def test_wrong_occasion_and_duplicate_inventory_fail():
    with pytest.raises(ValueError, match="occasion"):
        plan(policy(), Request(profile="pr", occasion="schedule", revision="abc"), INVENTORY)
    with pytest.raises(ValueError, match="unique"):
        plan(policy(), Request(profile="pr", occasion="pr", revision="abc"), INVENTORY + INVENTORY)
