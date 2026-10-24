"""A sticky uses observed work and known prices without inventing missing evidence."""

from datetime import timedelta
from decimal import Decimal

import pytest

from ci_esta.ci_observability.models import GitHubJobV1, GitHubRunV1, RunnerSkuRateV1
from ci_esta.ci_observability.report import _runner_cost, build_report, render_markdown
from ci_esta.ci_observability.work_selection import WorkDecisionV1, WorkSelectionV1
from tests.ci_observability.builders import RECORDED_AT
from tests.ci_observability.efficiency_builders import pool, report


def priced_report(labels, *, rates=(), public=None):
    run = GitHubRunV1(id=431, run_attempt=2, head_sha="a" * 40, name="CI", status="completed",
                     created_at=RECORDED_AT, run_started_at=RECORDED_AT)
    observed_at = RECORDED_AT + timedelta(seconds=175)
    if public is not None:
        run = type(run).model_validate({**run.model_dump(), "repository": {"private": not public}})
    job = GitHubJobV1(id=1, name="Tests", run_attempt=run.run_attempt, status="completed", conclusion="success",
                      labels=labels, started_at=run.run_started_at, completed_at=observed_at)
    return build_report(repository="org/repo", pull_request_number=1, run=run, latest_jobs=[job],
                        billing_jobs=[job], commit_statuses=[], gate_selectors=[], observed_at=observed_at,
                        runner_sku_rates=list(rates))


@pytest.mark.parametrize("labels,rate", [(["ubuntu-latest"], "0.006"), (["ubuntu-24.04"], "0.006"),
                                       (["ubuntu-24.04-arm"], "0.005"), (["windows-latest"], "0.010"),
                                       (["macos-latest"], "0.062"), (["ubuntu-slim"], "0.002")])
def test_standard_hosted_jobs_have_traceable_list_price_estimates(labels, rate):
    measured = priced_report(labels)
    cost = measured.runner_cost
    assert cost.estimated_cost_usd == cost.estimated_rounded_runner_minutes * Decimal(rate)
    assert cost.by_sku[0].sku.startswith("github_20261024_")
    assert "before included minutes" in render_markdown(measured)


def test_public_standard_runners_are_free_when_repository_visibility_is_known():
    measured = priced_report(["ubuntu-latest"], public=True)
    assert measured.runner_cost.estimated_cost_usd == 0
    assert measured.runner_cost.by_sku[0].sku.startswith("github_public_")


@pytest.mark.parametrize("labels", [["self-hosted", "ubuntu-latest"], ["16vcpu-runner"], [],
                                    ["ubuntu-latest", "custom-hardware"]])
def test_unknown_runner_hardware_requires_an_explicit_rate(labels):
    measured = priced_report(labels)
    assert measured.runner_cost.estimated_cost_usd is None
    assert measured.runner_cost.unpriced_rounded_runner_minutes == measured.runner_cost.estimated_rounded_runner_minutes
    assert "runner-sku-rates-json" in render_markdown(measured)


def test_explicit_rate_overrides_defaults_and_custom_hardware_is_preserved():
    rate = RunnerSkuRateV1(sku="custom", runner_label="ubuntu-latest", usd_per_minute=Decimal("0.02"))
    measured = priced_report(["ubuntu-latest"], rates=[rate], public=True)
    assert measured.runner_cost.by_sku[0].usd_per_minute == Decimal("0.02")
    assert measured.runner_cost.by_sku[0].sku == "custom"


def test_python_execution_uses_measured_shards_before_workflow_jobs():
    measured = report().model_copy(update={"measurements": [pool()]})
    assert "![executed: 2 shards]" in render_markdown(measured)


def test_admission_without_file_inventory_preserves_observed_execution():
    measured = report().model_copy(update={"work_selection": WorkSelectionV1(
        provider="Example", run_id=431, run_attempt=2, head_sha="a" * 40, input_identity="tree",
        decisions=[WorkDecisionV1(name="tests", decision="run", reason="affected input")])})
    assert "![executed: 1 jobs]" in render_markdown(measured)


def test_partial_pricing_keeps_the_known_breakdown_and_identifies_the_gap():
    measured = priced_report(["ubuntu-latest"])
    job = measured.billing_jobs[0].model_copy(update={"job_id": 2, "runner_labels": ["custom"]})
    cost = _runner_cost([*measured.billing_jobs, job], [])
    assert cost.estimated_cost_usd is None
    assert cost.unpriced_rounded_runner_minutes == 3
    assert len(cost.by_sku) == 1
    sticky = render_markdown(measured.model_copy(update={"runner_cost": cost}))
    assert "partial estimate" in sticky
    assert "actions_linux" in sticky


def test_execution_falls_back_to_started_jobs_with_an_explicit_unit_and_scope():
    measured = report()
    job = measured.latest_attempt_jobs[0]
    skipped = job.model_copy(update={"job_id": 12, "conclusion": "skipped"})
    queued = job.model_copy(update={"job_id": 13, "status": "queued", "conclusion": None, "started_at": None})
    old = job.model_copy(update={"job_id": 14, "run_attempt": 1})
    measured = measured.model_copy(update={"latest_attempt_jobs": [job, skipped, queued, old]})
    sticky = render_markdown(measured)
    assert "![executed: 1 jobs]" in sticky
    assert "includes setup, checks and reporting" in sticky
    assert "Sharding &amp; runner efficiency" not in sticky
    assert "publish-shard-measurements" in sticky


def test_disabled_caches_are_known_outcomes():
    from ci_esta.measurements import CacheMeasurement

    measured = report().model_copy(update={"measurements": [CacheMeasurement(
        run_id=431, run_attempt=2, head_sha="a" * 40, job="tests", scope="env",
        outcome="disabled", sync_seconds=1)]})
    sticky = render_markdown(measured)
    assert "1 disabled</strong> <sub>environment caches</sub>" in sticky
    assert "unavailable</strong> <sub>environment cache hits</sub>" not in sticky
