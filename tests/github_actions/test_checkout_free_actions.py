"""Actions that run from their own path stay quiet in a job without a checkout."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
# These run CI-esta from the action's own path and are documented for jobs with no checkout (a planner, an observer,
# an artifact aggregator). setup-uv warns "Empty workdir detected" on every such run unless told the workspace may be
# empty. Actions that need the repository keep the warning: there it signals a missing checkout.
CHECKOUT_FREE = ["plan-runner-pools", "ci-observability", "ci-observability-enrichment", "pytest-timings", "test-budget"]
NEEDS_CHECKOUT = ["setup-cached-uv", "setup-python-uv", "plan-pytest-shards", "typecheck-scope", "run-bun-tests"]


def setup_uv(action: str) -> dict:
    steps = yaml.safe_load((ROOT / "actions" / action / "action.yml").read_text())["runs"]["steps"]
    [step] = [step for step in steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")]
    return step.get("with") or {}


@pytest.mark.parametrize("action", CHECKOUT_FREE)
def test_checkout_free_actions_accept_an_empty_workspace(action: str) -> None:
    assert setup_uv(action).get("ignore-empty-workdir") is True


@pytest.mark.parametrize("action", NEEDS_CHECKOUT)
def test_actions_that_read_the_repository_keep_the_empty_workspace_warning(action: str) -> None:
    assert "ignore-empty-workdir" not in setup_uv(action)
