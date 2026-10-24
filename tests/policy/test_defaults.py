"""Default policy must work through the public API and installed CLI."""

import json

import pytest

from ci_esta.policy import Policy, Request, Work, plan
from ci_esta.policy.cli import main


@pytest.mark.parametrize(
    "profile,occasion,expected",
    [
        ("ci", "pr", {"unit", "smoke"}),
        ("thorough", "manual", {"unit", "smoke"}),
        ("deep", "pr", {"unit", "smoke", "benchmark"}),
        ("weekly", "schedule", {"unit", "smoke", "benchmark"}),
        ("performance", "manual", {"benchmark"}),
        ("smoke", "deployment", {"smoke"}),
    ],
)
def test_defaults_admit_by_cost_and_keep_effects_opt_in(profile, occasion, expected):
    inventory = (
        Work(id="unit"),
        Work(id="smoke"),
        Work(id="benchmark", tags={"expensive", "performance"}),
        Work(id="paid", tags={"expensive"}, effects={"spend"}),
        Work(id="broadcast", tags={"manual"}),
    )
    result = plan(Policy(), Request(profile=profile, occasion=occasion, revision="abc"), inventory)
    assert {d.work.id for d in result.runnable} == expected


def test_single_field_override_inherits_defaults_and_empty_set_replaces():
    policy = Policy.model_validate(
        {
            "profiles": {
                "weekly": {"allow_effects": ["spend"]},
                "cheap-weekly": {"extends": "weekly", "allow_effects": []},
            }
        }
    )
    work = (Work(id="paid", effects={"spend"}),)
    for profile, expected in [("weekly", 1), ("cheap-weekly", 0)]:
        result = plan(policy, Request(profile=profile, occasion="schedule", revision="abc", affected=set()), work)
        assert len(result.runnable) == expected
    assert policy.profiles["weekly"].fresh
    assert policy.profiles["weekly"].scope == "all"


@pytest.mark.parametrize(
    "profiles",
    [
        {"typo": {"scope": "all"}},
        {"custom": {"extends": "missing"}},
        {"a": {"extends": "b"}, "b": {"extends": "a"}},
        {"weekly": {"exclude_typo": []}},
    ],
)
def test_invalid_overrides_fail_instead_of_inventing_policy(profiles):
    with pytest.raises(ValueError):
        Policy.model_validate({"profiles": profiles})


def test_disable_defaults_is_a_complete_escape_hatch():
    policy = Policy.model_validate(
        {"defaults": "none", "profiles": {"custom": {"occasions": ["manual"], "include": ["*"]}}}
    )
    assert set(policy.profiles) == {"custom"}
    with pytest.raises(ValueError, match="unknown profile"):
        plan(policy, Request(profile="weekly", occasion="manual", revision="abc"), ())


def test_inventory_reuses_selector_ids_and_rejects_stale_metadata():
    policy = Policy(work=(Work(id="benchmark", tags={"expensive"}),))
    inventory = policy.inventory(["unit", "benchmark"])
    assert inventory == (Work(id="unit"), Work(id="benchmark", tags={"expensive"}))
    with pytest.raises(ValueError, match="unknown"):
        policy.inventory(["unit"])


def test_cli_needs_no_policy_file_and_normalizes_github_event(tmp_path):
    output = tmp_path / "plan.json"
    assert (
        main(
            [
                "--work",
                '["unit", {"id":"benchmark", "tags":["expensive"]}]',
                "--occasion",
                "pull_request",
                "--revision",
                "abc",
                "--output",
                str(output),
                "--github-output",
                "",
            ]
        )
        == 0
    )
    result = json.loads(output.read_text())
    assert [d["work"]["id"] for d in result["decisions"] if d["status"] == "run"] == ["unit"]


def test_cli_reads_authoritative_lane_ids_and_overlay(tmp_path):
    lanes = tmp_path / "lanes.json"
    lanes.write_text(json.dumps({"lanes": {"unit": {}, "benchmark": {}}}))
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"work": [{"id": "benchmark", "tags": ["expensive", "performance"]}]}))
    output = tmp_path / "plan.json"
    assert (
        main(
            [
                "--lanes",
                str(lanes),
                "--policy",
                str(policy),
                "--profile",
                "performance",
                "--occasion",
                "workflow_dispatch",
                "--revision",
                "abc",
                "--output",
                str(output),
                "--github-output",
                "",
            ]
        )
        == 0
    )
    result = json.loads(output.read_text())
    assert [d["work"]["id"] for d in result["decisions"] if d["status"] == "run"] == ["benchmark"]


def test_default_probe_requires_target_and_never_grants_effects():
    policy = Policy()
    request = dict(profile="probe", occasion="manual", revision="abc")
    inventory = (Work(id="visible", tags={"manual"}, effects={"publish"}),)
    with pytest.raises(ValueError, match="explicit scope"):
        plan(policy, Request(**request), inventory)
    with pytest.raises(ValueError, match="permissions"):
        plan(policy, Request(**request, requested={"visible"}), inventory)


def test_cli_missing_inventory_cannot_pass_as_an_empty_selection(tmp_path):
    output = tmp_path / "plan.json"
    output.write_text("stale success")
    assert main(["--occasion", "pr", "--revision", "abc", "--output", str(output), "--github-output", ""]) == 2
    assert not output.exists()


def test_typed_inheritance_resolves_once_and_roundtrips():
    from ci_esta.policy.models import Profile

    policy = Policy(profiles={"costly": Profile(extends="weekly", allow_effects={"spend"})})
    assert policy.profiles["costly"].scope == "all"
    assert policy.profiles["costly"].occasions == {"manual", "schedule"}
    assert Policy.model_validate_json(policy.model_dump_json()) == policy


@pytest.mark.parametrize(
    "profile,expected",
    [
        ("affected", {"changed"}),
        ("affected_deep", {"changed", "costly_changed"}),
        ("weekly", {"changed", "unchanged", "costly_changed", "costly_unchanged"}),
    ],
)
def test_affected_profiles_do_not_expand_unchanged_work(profile, expected):
    inventory = (
        Work(id="changed"),
        Work(id="unchanged"),
        Work(id="costly_changed", tags={"expensive"}),
        Work(id="costly_unchanged", tags={"expensive"}),
        Work(id="manual_changed", tags={"manual"}),
    )
    request = Request(
        profile=profile, occasion="manual", revision="abc", affected={"changed", "costly_changed", "manual_changed"}
    )
    result = plan(Policy(), request, inventory)
    assert {d.work.id for d in result.runnable} == expected


@pytest.mark.parametrize(
    "occasion,labels,explicit,expected",
    [
        ("pr", [], "", "affected"),
        ("pr", ["test:affected-deep"], "", "affected_deep"),
        ("pr", ["test:deep"], "", "affected_deep"),
        ("pr", ["test:full"], "", "full"),
        ("pr", ["test:full", "test:affected-deep"], "", "full"),
        ("schedule", [], "", "weekly"),
        ("manual", [], "", "affected"),
        ("pr", ["test:full"], "legacy", "legacy"),
    ],
)
def test_profile_selection_uses_explicit_request_then_occasion_and_labels(occasion, labels, explicit, expected):
    from ci_esta.policy.defaults import profile_for_run

    assert profile_for_run(occasion=occasion, labels=labels, profile=explicit) == expected


@pytest.mark.parametrize(
    "occasion,labels,expected",
    [
        ("pull_request", [], ["cheap"]),
        ("pull_request", ["test:affected-deep"], ["cheap", "costly"]),
        ("schedule", [], ["cheap", "costly", "unchanged"]),
    ],
)
def test_cli_routes_events_without_a_copied_profile_expression(tmp_path, occasion, labels, expected):
    output = tmp_path / "plan.json"
    assert (
        main(
            [
                "--work",
                json.dumps(["cheap", {"id": "costly", "tags": ["expensive"]}, "unchanged"]),
                "--affected",
                '["cheap", "costly"]',
                "--labels",
                json.dumps(labels),
                "--occasion",
                occasion,
                "--revision",
                "abc",
                "--output",
                str(output),
                "--github-output",
                "",
            ]
        )
        == 0
    )
    result = json.loads(output.read_text())
    assert [d["work"]["id"] for d in result["decisions"] if d["status"] == "run"] == expected
