import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from unittest.mock import MagicMock, patch

import httpx
import pytest
import yaml
from pydantic import BaseModel, JsonValue, ValidationError
from pytest_selective.impact_models import ExplanationUnavailable, SelectionExplanation, SelectionRoute

import ci_esta.ci_observability.action as action_module
from ci_esta.ci_observability.action import REFERENCE_SAMPLE, ActionConfig, run
from ci_esta.ci_observability.enrichment.profiles import pytest_timings
from ci_esta.ci_observability.github import GitHubActionsClient, GitHubArtifactV1
from ci_esta.ci_observability.models import (
    ActionsJobGateSelectorV1,
    CiObservabilityReportV1,
    CommitStatusGateSelectorV1,
    FullSuiteReferenceV1,
    GateKind,
    GitHubCommitStatusV1,
    GitHubJobV1,
    GitHubPullRequestV1,
    GitHubRunV1,
    PytestTimingMetadata,
    RepositorySignalV1,
    RunnerSkuRateV1,
)
from ci_esta.ci_observability.report import STICKY_MARKER
from tests.ci_observability.builders import (
    AI_TIMINGS,
    TOTAL_FILES,
    ai_extensions,
    artifact,
    backend_extensions,
    floor,
    full_suite_reference,
)

REPOSITORY = "gigaverse-app/example"
TOKEN = "test-token"
API_URL = "https://api.github.test"
RUN_ID = 123
RUN_ATTEMPT = 2
PR_NUMBER = 86
HEAD_SHA = "a" * 40
NOW = datetime(2026, 7, 23, 6, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 7, 23, 6, 1, 1, tzinfo=timezone.utc)
STATUS_CONTEXT = "required"
COMMENT_ID = 77
WORKFLOW_ID = 30095599
BRANCH = "agent/example"


class ExampleExtension(BaseModel):
    service_count: int


def _config(tmp_path: Path, *, post_sticky: bool = True) -> ActionConfig:
    return ActionConfig(
        repository=REPOSITORY,
        github_token=TOKEN,
        api_url=API_URL,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        commit_sha=HEAD_SHA,
        pull_request_number=PR_NUMBER,
        gate_selectors=[
            CommitStatusGateSelectorV1(
                kind=GateKind.COMMIT_STATUS,
                context=STATUS_CONTEXT,
            )
        ],
        repository_signals=[
            RepositorySignalV1(
                key="pytest",
                label="pytest",
                value="42 passed, 0 failed",
            )
        ],
        extensions={"example": ExampleExtension(service_count=3).model_dump(mode="json")},
        report_output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        prometheus_output=tmp_path / "report.prom",
        post_sticky=post_sticky,
        append_summary=True,
    )


def _run_metadata() -> GitHubRunV1:
    return GitHubRunV1(
        id=RUN_ID,
        name="Primary CI",
        run_attempt=RUN_ATTEMPT,
        status="completed",
        conclusion="success",
        created_at=NOW,
        run_started_at=NOW,
        head_sha=HEAD_SHA,
    )


def _job() -> GitHubJobV1:
    return GitHubJobV1(
        id=1,
        name="Tests",
        run_attempt=RUN_ATTEMPT,
        status="completed",
        conclusion="success",
        started_at=NOW,
        completed_at=LATER,
    )


def _status() -> GitHubCommitStatusV1:
    return GitHubCommitStatusV1(
        context=STATUS_CONTEXT,
        state="success",
        created_at=NOW,
        updated_at=LATER,
    )


def test_action_config_reads_typed_environment_and_extension(
    monkeypatch,
    tmp_path: Path,
) -> None:
    extension_path = tmp_path / "extension.json"
    extension_path.write_text(ExampleExtension(service_count=3).model_dump_json())
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(
        json.dumps(
            [
                {
                    "key": "pytest",
                    "label": "pytest",
                    "value": "42 passed, 0 failed",
                }
            ]
        )
    )
    report_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    prometheus_path = tmp_path / "report.prom"
    gate = CommitStatusGateSelectorV1(
        kind=GateKind.COMMIT_STATUS,
        context=STATUS_CONTEXT,
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_API_URL", API_URL)
    monkeypatch.setenv("INPUT_GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("INPUT_RUN_ID", str(RUN_ID))
    monkeypatch.setenv("INPUT_RUN_ATTEMPT", str(RUN_ATTEMPT))
    monkeypatch.setenv("INPUT_COMMIT_SHA", HEAD_SHA)
    monkeypatch.setenv("INPUT_PULL_REQUEST_NUMBER", str(PR_NUMBER))
    monkeypatch.setenv("INPUT_REQUIRED_GATES_JSON", f"[{gate.model_dump_json()}]")
    monkeypatch.setenv("INPUT_EXTENSIONS_FILE", str(extension_path))
    monkeypatch.setenv("INPUT_REPOSITORY_SIGNALS_FILE", str(signals_path))
    monkeypatch.setenv("INPUT_REPORT_OUTPUT", str(report_path))
    monkeypatch.setenv("INPUT_MARKDOWN_OUTPUT", str(markdown_path))
    monkeypatch.setenv("INPUT_PROMETHEUS_OUTPUT", str(prometheus_path))
    monkeypatch.setenv("INPUT_POST_STICKY", "false")
    monkeypatch.setenv("INPUT_STICKY_WORKFLOW", "Primary CI")
    monkeypatch.setenv("INPUT_APPEND_SUMMARY", "false")
    monkeypatch.setenv(
        "INPUT_RUNNER_SKU_RATES_JSON",
        '[{"sku":"linux_8_core","runner_label":"8vcpu-runner","usd_per_minute":"0.022"}]',
    )

    config = ActionConfig.from_environment()

    assert config.pull_request_number == PR_NUMBER
    assert config.gate_selectors == [gate]
    assert config.extensions == {"service_count": 3}
    assert config.repository_signals == [
        RepositorySignalV1(
            key="pytest",
            label="pytest",
            value="42 passed, 0 failed",
        )
    ]
    assert config.report_output == report_path
    assert config.post_sticky is False
    assert config.sticky_workflow == "Primary CI"
    assert config.append_summary is False
    assert config.runner_sku_rates == [
        RunnerSkuRateV1(
            sku="linux_8_core",
            runner_label="8vcpu-runner",
            usd_per_minute=Decimal("0.022"),
        )
    ]


@pytest.mark.parametrize("owner,publishes", [("", True), ("Primary CI", True), ("Other workflow", False)])
def test_run_writes_all_outputs_summary_and_sticky(
    monkeypatch,
    tmp_path: Path,
    owner,
    publishes,
) -> None:
    config = _config(tmp_path).model_copy(update={"sticky_workflow": owner})
    summary_path = tmp_path / "summary.md"
    action_output_path = tmp_path / "action-output.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(action_output_path))

    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(GitHubActionsClient, "list_jobs", return_value=[_job()]),
        patch.object(GitHubActionsClient, "list_commit_statuses", return_value=[_status()]),
        patch.object(GitHubActionsClient, "upsert_sticky", return_value=COMMENT_ID) as upsert,
    ):
        result = run(config, LATER)

    assert result == 0
    report = json.loads(config.report_output.read_text())
    assert report["schema_version"] == "ci-observability/v1"
    assert report["collection_status"] == "complete"
    assert "| CI gates passed |" in config.markdown_output.read_text()
    assert "_pytest: 42 passed, 0 failed._" in config.markdown_output.read_text()
    assert "ci_raw_runner_seconds" in config.prometheus_output.read_text()
    assert summary_path.read_text() == config.markdown_output.read_text() + "\n"
    assert "report-file=" in action_output_path.read_text()
    assert upsert.called is publishes
    if publishes:
        assert upsert.call_args.args[0] == PR_NUMBER


def test_historical_attempt_recovers_exact_metadata_and_jobs(tmp_path):
    config = _config(tmp_path, post_sticky=False)
    current = _run_metadata().model_copy(update={"run_attempt": RUN_ATTEMPT + 1})
    newer_job = _job().model_copy(update={"run_attempt": RUN_ATTEMPT + 1})
    with (
        patch.object(GitHubActionsClient, "get_run", side_effect=[current, _run_metadata()]) as metadata,
        patch.object(GitHubActionsClient, "list_jobs", side_effect=[[newer_job], [_job()], [_job(), newer_job]]) as jobs,
        patch.object(GitHubActionsClient, "list_commit_statuses", return_value=[_status()]),
    ):
        assert run(config, LATER) == 0
    metadata.assert_called_with(RUN_ID, run_attempt=RUN_ATTEMPT)
    assert jobs.call_args_list[1].kwargs == {"include_all_attempts": False, "run_attempt": RUN_ATTEMPT}
    report = json.loads(config.report_output.read_text())
    assert report["collection_status"] == "complete"
    assert report["provenance"]["run_attempt"] == RUN_ATTEMPT


@pytest.mark.parametrize("conclusion", ["success", "failure", None])
def test_completed_run_refreshes_stale_job_listing_without_inventing_a_verdict(tmp_path, conclusion):
    config = _config(tmp_path, post_sticky=False).model_copy(update={
        "gate_selectors": [ActionsJobGateSelectorV1(kind=GateKind.ACTIONS_JOB, job_name="Tests")],
    })
    stale = _job().model_copy(update={"status": "in_progress", "conclusion": None, "completed_at": None})
    refreshed = _job().model_copy(update={"conclusion": conclusion}) if conclusion else stale
    calls = []

    def jobs(run_id, *, include_all_attempts, run_attempt=None):
        assert run_id == RUN_ID
        calls.append((include_all_attempts, run_attempt))
        # The generic latest/all endpoints can lag the completed run. The
        # attempt-specific endpoint provides an independent recovery path.
        return [refreshed] if run_attempt == RUN_ATTEMPT else [stale]

    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(GitHubActionsClient, "list_jobs", side_effect=jobs),
    ):
        assert run(config, LATER) == 0
    report = json.loads(config.report_output.read_text())
    assert calls == [(False, None), (False, RUN_ATTEMPT), (True, None)]
    assert report["required_gates"][0]["conclusion"] == conclusion
    assert report["latest_attempt_jobs"][0]["conclusion"] == conclusion
    assert report["billing_jobs"][0]["conclusion"] == conclusion
    assert report["collection_status"] == ("complete" if conclusion else "partial")
    if conclusion is None:
        assert any("completed source run" in error for error in report["collection_errors"])


@pytest.mark.parametrize("failure", ["unavailable", "wrong_attempt"])
def test_terminal_job_refresh_failure_retains_the_original_snapshot(tmp_path, failure):
    config = _config(tmp_path, post_sticky=False)
    stale = _job().model_copy(update={"status": "in_progress", "conclusion": None, "completed_at": None})

    def jobs(run_id, *, include_all_attempts, run_attempt=None):
        if run_attempt is not None:
            if failure == "unavailable":
                raise RuntimeError("GitHub temporarily unavailable")
            return [_job().model_copy(update={"run_attempt": RUN_ATTEMPT + 1})]
        return [stale]

    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(GitHubActionsClient, "list_jobs", side_effect=jobs),
        patch.object(GitHubActionsClient, "list_commit_statuses", return_value=[_status()]),
    ):
        assert run(config, LATER) == 0
    report = json.loads(config.report_output.read_text())
    assert report["collection_status"] == "partial"
    assert len(report["latest_attempt_jobs"]) == 1
    assert report["latest_attempt_jobs"][0]["run_attempt"] == RUN_ATTEMPT
    assert report["latest_attempt_jobs"][0]["status"] == "in_progress"
    assert any("refresh unavailable" in error for error in report["collection_errors"])


def test_live_run_keeps_its_nonterminal_snapshot_without_extra_fetch(tmp_path):
    config = _config(tmp_path, post_sticky=False)
    live = _run_metadata().model_copy(update={"status": "in_progress", "conclusion": None})
    job = _job().model_copy(update={"status": "in_progress", "conclusion": None, "completed_at": None})
    with (
        patch.object(GitHubActionsClient, "get_run", return_value=live),
        patch.object(GitHubActionsClient, "list_jobs", return_value=[job]) as jobs,
        patch.object(GitHubActionsClient, "list_commit_statuses", return_value=[_status()]),
    ):
        assert run(config, LATER) == 0
    assert jobs.call_count == 2  # Latest and billing, no terminal recovery.
    report = json.loads(config.report_output.read_text())
    assert report["collection_status"] == "complete"
    assert report["latest_attempt_jobs"][0]["status"] == "in_progress"


def test_cli_without_explicit_head_uses_source_metadata(tmp_path):
    config = _config(tmp_path, post_sticky=False).model_copy(update={"commit_sha": ""})
    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(GitHubActionsClient, "list_jobs", return_value=[_job()]),
        patch.object(GitHubActionsClient, "list_commit_statuses", return_value=[_status()]),
    ):
        assert run(config, LATER) == 0
    report = json.loads(config.report_output.read_text())
    assert report["collection_status"] == "complete"
    assert report["provenance"]["head_sha"] == HEAD_SHA


@pytest.mark.parametrize("label,sku,price,expected", [
    ("ubuntu-latest", "actions_linux", "0.006", "0.012"),
    ("custom-runner", "actions_linux", "0.006", None),
    ("ubuntu-latest", "actions_linux", None, "0.012"),
    ("8vcpu-runner", "linux_8_core", None, "0.044"),
    ("8vcpu-runner", "linux_8_core", "0.009", "0.018"),
])
def test_reusable_pricing_reaches_the_report_without_pricing_unknown_runners(
    monkeypatch, tmp_path, label, sku, price, expected,
):
    workflow = yaml.safe_load(Path(".github/workflows/report.yml").read_text())
    inputs = workflow[True]["workflow_call"]["inputs"]
    forwarded = workflow["jobs"]["report"]["steps"][1]["with"]
    action = yaml.safe_load(Path("actions/ci-observability/action.yml").read_text())
    assert inputs["runner-sku-rates-json"]["default"] == "[]"
    assert forwarded["runner-sku-rates-json"] == "${{ inputs.runner-sku-rates-json }}"
    assert action["runs"]["steps"][1]["env"]["INPUT_RUNNER_SKU_RATES_JSON"] == "${{ inputs.runner-sku-rates-json }}"
    for name, metadata in action["inputs"].items():
        if "default" in metadata:
            monkeypatch.setenv("INPUT_" + name.upper().replace("-", "_"), str(metadata["default"]))
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("INPUT_GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("INPUT_RUN_ID", str(RUN_ID))
    mapping = {"sku": sku, "runner_label": "8vcpu-runner" if sku == "linux_8_core" else "ubuntu-latest"}
    if price is not None:
        mapping["usd_per_minute"] = price
    monkeypatch.setenv("INPUT_RUNNER_SKU_RATES_JSON", json.dumps([mapping]))
    monkeypatch.setenv("INPUT_RUN_ATTEMPT", str(RUN_ATTEMPT))
    monkeypatch.setenv("INPUT_COMMIT_SHA", HEAD_SHA)
    rates = ActionConfig.from_environment().runner_sku_rates
    config = _config(tmp_path, post_sticky=False).model_copy(update={"runner_sku_rates": rates})
    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(GitHubActionsClient, "list_jobs", return_value=[_job().model_copy(update={"labels": [label]})]),
        patch.object(GitHubActionsClient, "list_commit_statuses", return_value=[_status()]),
    ):
        assert run(config, LATER) == 0
    report = json.loads(config.report_output.read_text())
    assert report["runner_cost"]["estimated_cost_usd"] == expected
    badge = f"![est. cost: ${float(expected):.2f}]" if expected else "![est. cost: unavailable]"
    assert badge in config.markdown_output.read_text()


def test_run_collects_jobs_for_overlapping_prior_same_pr_run(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, post_sticky=False)
    current_run = _run_metadata().model_copy(
        update={
            "workflow_id": WORKFLOW_ID,
            "event": "pull_request",
            "head_branch": BRANCH,
            "pull_requests": [GitHubPullRequestV1(number=PR_NUMBER)],
        }
    )
    prior_run = current_run.model_copy(
        update={
            "id": RUN_ID - 1,
            "status": "completed",
            "conclusion": "cancelled",
            "created_at": datetime(
                2026,
                7,
                23,
                5,
                59,
                30,
                tzinfo=timezone.utc,
            ),
            "updated_at": LATER,
        }
    )
    prior_job = _job().model_copy(
        update={
            "id": 2,
            "run_attempt": 1,
            "conclusion": "cancelled",
        }
    )

    def list_jobs(
        run_id: int,
        *,
        include_all_attempts: bool,
    ) -> list[GitHubJobV1]:
        assert include_all_attempts or run_id == RUN_ID
        return [prior_job] if run_id == prior_run.id else [_job()]

    with (
        patch.object(GitHubActionsClient, "get_run", return_value=current_run),
        patch.object(GitHubActionsClient, "list_jobs", side_effect=list_jobs),
        patch.object(
            GitHubActionsClient,
            "list_overlapping_prior_runs",
            return_value=[prior_run],
        ),
        patch.object(
            GitHubActionsClient,
            "list_commit_statuses",
            return_value=[_status()],
        ),
    ):
        assert run(config, LATER) == 0

    report = json.loads(config.report_output.read_text())
    assert report["overlapping_prior_runner_cost"]["estimated_rounded_runner_minutes"] == 2
    assert report["overlapping_prior_runner_cost"]["runs"][0]["run_id"] == (RUN_ID - 1)


def test_run_degrades_to_unavailable_report_when_run_collection_fails(
    capsys,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, post_sticky=False)

    with patch.object(
        GitHubActionsClient,
        "get_run",
        side_effect=RuntimeError("API unavailable"),
    ):
        result = run(config, LATER)

    assert result == 0
    report = json.loads(config.report_output.read_text())
    assert report["collection_status"] == "unavailable"
    assert report["collection_errors"] == ["report collection unavailable: API unavailable"]
    assert '"collection_status": "unavailable"' in capsys.readouterr().out


def test_run_keeps_report_when_optional_collections_and_sticky_fail(
    capsys,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(
            GitHubActionsClient,
            "list_jobs",
            side_effect=RuntimeError("jobs unavailable"),
        ),
        patch.object(
            GitHubActionsClient,
            "list_commit_statuses",
            side_effect=RuntimeError("statuses unavailable"),
        ),
        patch.object(
            GitHubActionsClient,
            "upsert_sticky",
            side_effect=RuntimeError("comments unavailable"),
        ),
    ):
        result = run(config, LATER)

    assert result == 0
    report = json.loads(config.report_output.read_text())
    assert report["collection_status"] == "partial"
    assert report["collection_errors"] == [
        "latest-attempt jobs unavailable: jobs unavailable",
        "all-attempt jobs unavailable; latest attempt only: jobs unavailable",
        "commit statuses unavailable: statuses unavailable",
        f"required gates were not observed: {STATUS_CONTEXT}",
    ]
    assert "sticky unavailable: comments unavailable" in capsys.readouterr().out


def test_main_loads_environment_and_runs_reporter(tmp_path: Path) -> None:
    config = _config(tmp_path, post_sticky=False)

    with (
        patch.object(ActionConfig, "from_environment", return_value=config),
        patch.object(action_module, "run", return_value=0) as run_reporter,
    ):
        assert action_module.main() == 0

    assert run_reporter.call_args.args[0] == config
    assert isinstance(run_reporter.call_args.args[1], datetime)


def test_run_does_not_fetch_commit_statuses_without_status_gate(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, post_sticky=False).model_copy(update={"gate_selectors": []})

    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(GitHubActionsClient, "list_jobs", return_value=[_job()]),
        patch.object(GitHubActionsClient, "list_commit_statuses") as list_statuses,
    ):
        assert run(config, LATER) == 0

    list_statuses.assert_not_called()


SELECTED = 104
EXPLANATION_ARTIFACT = "test-impact-explanation"
REFERENCE_ARTIFACT = "ci-full-suite-reference-v1"
EXPLANATION_ID = 501
OWN_ID, FORK_ID, UNREADABLE_ID, OTHER_SUITE_ID, NEWEST_ID, OLDER_ID = 601, 602, 603, 604, 605, 606
NEWEST_RUN, OLDER_RUN = 456, 455
#: A suite outside the size tolerance of this run's, like an old tree with half the tests.
OTHER_SUITE_FILES = TOTAL_FILES // 2
NEWEST, OLDER = full_suite_reference(NEWEST_RUN), full_suite_reference(OLDER_RUN)


def _explanation(selected: int = SELECTED, *, forced_full: bool = False) -> SelectionExplanation:
    return SelectionExplanation(
        base="base-tree",
        head="head-tree",
        graph_base="base-tree",
        selected=selected,
        total=TOTAL_FILES,
        forced_full=forced_full,
        routes=[SelectionRoute(kind="other", tests=selected)],
        floor=floor(),
    )


def _selection_config(tmp_path: Path, extensions: dict[str, JsonValue], *, post_sticky: bool = True) -> ActionConfig:
    return _config(tmp_path, post_sticky=post_sticky).model_copy(
        update={
            "extensions": extensions,
            "test_selection_artifact": EXPLANATION_ARTIFACT,
            "full_suite_reference_artifact": REFERENCE_ARTIFACT,
            "full_suite_reference_output": tmp_path / "reference.json",
        }
    )


def _selection_run(head_branch: str | None = BRANCH) -> GitHubRunV1:
    return _run_metadata().model_copy(update={"event": "pull_request", "head_branch": head_branch})


def _status_with(state: str) -> GitHubCommitStatusV1:
    return _status().model_copy(update={"state": state})


class FakeArtifacts:
    """Artifacts as GitHub lists them, newest first: this run's plan, and other runs' references."""

    def __init__(self, explanation: SelectionExplanation | ExplanationUnavailable | None) -> None:
        other_suite = full_suite_reference(NEWEST_RUN + 1, total_files=OTHER_SUITE_FILES)
        self.payloads: dict[int, bytes] = {
            OWN_ID: full_suite_reference(RUN_ID).model_dump_json().encode(),
            FORK_ID: full_suite_reference(NEWEST_RUN + 2).model_dump_json().encode(),
            UNREADABLE_ID: b"{not json",
            OTHER_SUITE_ID: other_suite.model_dump_json().encode(),
            NEWEST_ID: NEWEST.model_dump_json().encode(),
            OLDER_ID: OLDER.model_dump_json().encode(),
        }
        self.explanation = explanation
        if explanation is not None:
            self.payloads[EXPLANATION_ID] = explanation.model_dump_json().encode()

    def list_artifacts(self, name: str, run_id: int | None = None) -> list[GitHubArtifactV1]:
        if name == EXPLANATION_ARTIFACT:
            assert run_id == RUN_ID
            return [artifact(EXPLANATION_ID, RUN_ID)] if self.explanation is not None else []
        assert (name, run_id) == (REFERENCE_ARTIFACT, None)
        return [
            artifact(OWN_ID, RUN_ID),
            artifact(FORK_ID, NEWEST_RUN + 2, fork=True),
            artifact(UNREADABLE_ID, NEWEST_RUN + 3),
            artifact(OTHER_SUITE_ID, NEWEST_RUN + 1),
            artifact(NEWEST_ID, NEWEST_RUN),
            artifact(OLDER_ID, OLDER_RUN),
        ]

    def read_single_file_artifact(self, artifact_id: int) -> bytes:
        return self.payloads[artifact_id]


class GitHubMocks(TypedDict):
    upsert: MagicMock
    list_artifacts: MagicMock


@contextmanager
def github_with_artifacts(
    fake: FakeArtifacts, run_metadata: GitHubRunV1, *, gate_state: str = "success"
) -> Iterator[GitHubMocks]:
    with (
        patch.object(GitHubActionsClient, "get_run", return_value=run_metadata),
        patch.object(GitHubActionsClient, "list_jobs", return_value=[_job()]),
        patch.object(GitHubActionsClient, "list_commit_statuses", return_value=[_status_with(gate_state)]),
        patch.object(GitHubActionsClient, "list_artifacts", side_effect=fake.list_artifacts) as list_artifacts,
        patch.object(GitHubActionsClient, "read_single_file_artifact", side_effect=fake.read_single_file_artifact),
        patch.object(GitHubActionsClient, "upsert_sticky", return_value=COMMENT_ID) as upsert,
    ):
        yield GitHubMocks(upsert=upsert, list_artifacts=list_artifacts)


def _report(config: ActionConfig) -> CiObservabilityReportV1:
    return CiObservabilityReportV1.model_validate_json(config.report_output.read_text())


def test_sticky_leads_with_the_selection_measured_against_comparable_runs_of_others(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "action-output.txt"))
    config = _selection_config(tmp_path, ai_extensions())

    with github_with_artifacts(FakeArtifacts(_explanation()), _selection_run()) as github:
        assert run(config, LATER) == 0

    sticky = github["upsert"].call_args.args[2]
    assert sticky.startswith('<a href="https://github.com/gigaverse-app/ci-esta"><picture>')
    assert sticky.index("![selected: ") < sticky.index("#### 🎯 Test selection")
    assert f"{SELECTED} / 1,087 files selected · 81% less summed test time" in sticky
    assert "1m 18s longest-shard wall, 4m 53s summed test time" in sticky
    # The latency report folds into one closed expander after the section; the footer stays visible.
    latency = sticky.index("<details>\n<summary><strong>CI time and cost</strong>")
    assert sticky.index("#### 🎯 Test selection") < latency < sticky.index("| CI gates passed |")
    assert sticky.rstrip().endswith("· schema `ci-observability/v1`</sub>")
    assert sticky.index("</details>", sticky.index("| CI gates passed |")) < sticky.index(STICKY_MARKER)
    section = _report(config).test_selection
    assert section is not None
    # Not this run's own, not a fork's, not unreadable, not another suite size; newest first.
    assert section.references == [NEWEST, OLDER]
    assert f"Skipped unreadable full-suite reference {UNREADABLE_ID}" in capsys.readouterr().out
    # A narrowed run is no baseline.
    assert not config.full_suite_reference_output.exists()


@pytest.mark.parametrize(
    ("explanation", "extensions", "run_metadata", "gate_state", "records"),
    [
        (_explanation(TOTAL_FILES), ai_extensions(), _selection_run(), "success", True),
        (_explanation(TOTAL_FILES), backend_extensions(), _selection_run(), "success", True),
        (_explanation(TOTAL_FILES, forced_full=True), ai_extensions(), _selection_run(), "success", False),
        (_explanation(TOTAL_FILES), ai_extensions(), _selection_run(), "failure", False),
        (_explanation(TOTAL_FILES), ai_extensions(), _selection_run(), "pending", False),
        (_explanation(), ai_extensions(), _selection_run(), "success", False),
        (
            _explanation(TOTAL_FILES),
            ai_extensions(AI_TIMINGS.model_copy(update={"wall_seconds": None})),
            _selection_run(),
            "success",
            False,
        ),
        (
            _explanation(TOTAL_FILES),
            ai_extensions(AI_TIMINGS.model_copy(update={"total_test_seconds": None})),
            _selection_run(),
            "success",
            False,
        ),
        (_explanation(TOTAL_FILES), ai_extensions(), _selection_run(head_branch=None), "success", False),
    ],
    ids=[
        "ai-natural-full",
        "backend-natural-full",
        "forced-full",
        "red-gate",
        "gate-still-running",
        "narrowed",
        "no-wall-time",
        "no-test-time",
        "no-branch",
    ],
)
def test_only_a_green_run_the_change_made_full_records_itself_as_a_reference(
    monkeypatch,
    tmp_path: Path,
    explanation: SelectionExplanation,
    extensions: dict[str, JsonValue],
    run_metadata: GitHubRunV1,
    gate_state: str,
    records: bool,
) -> None:
    action_output = tmp_path / "action-output.txt"
    action_output.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(action_output))
    config = _selection_config(tmp_path, extensions)

    with github_with_artifacts(FakeArtifacts(explanation), run_metadata, gate_state=gate_state):
        assert run(config, LATER) == 0

    # Declining to record is a decision, never a lost report.
    report = _report(config)
    assert report.collection_status == "complete"
    assert report.test_selection is not None
    assert config.full_suite_reference_output.exists() is records
    assert ("full-suite-reference-file=" in action_output.read_text()) is records
    if records:
        recorded = FullSuiteReferenceV1.model_validate_json(config.full_suite_reference_output.read_text())
        assert (recorded.run_id, recorded.head_branch, recorded.recorded_at) == (RUN_ID, BRANCH, LATER)
        timings = pytest_timings(extensions)
        assert timings is not None
        # The reference keeps the shared timing contract, whichever profile measured it.
        assert type(recorded.timings) is PytestTimingMetadata
        assert (recorded.timings.wall_seconds, recorded.timings.total_test_seconds, recorded.total_files) == (
            timings.wall_seconds,
            timings.total_test_seconds,
            TOTAL_FILES,
        )


def test_a_report_that_posts_no_sticky_reads_no_selection(tmp_path: Path) -> None:
    config = _selection_config(tmp_path, ai_extensions(), post_sticky=False)

    with github_with_artifacts(FakeArtifacts(_explanation()), _selection_run()) as github:
        assert run(config, LATER) == 0

    github["list_artifacts"].assert_called_once_with(None, run_id=RUN_ID)
    assert "Test selection" not in config.markdown_output.read_text()


@pytest.mark.parametrize(
    "explanation",
    [None, ExplanationUnavailable(unavailable="Test impact proof unavailable; complete suite fallback")],
    ids=["no-artifact", "fallback-plan"],
)
def test_a_run_without_an_explanation_keeps_the_rest_of_the_sticky(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], explanation: ExplanationUnavailable | None
) -> None:
    config = _selection_config(tmp_path, ai_extensions())

    with github_with_artifacts(FakeArtifacts(explanation), _selection_run()) as github:
        assert run(config, LATER) == 0

    assert "<details>\n<summary><strong>CI time and cost" in github["upsert"].call_args.args[2]
    assert _report(config).collection_status == "complete"
    # A fallback plan is an expected outcome, not a failure to read.
    assert "::warning::" not in capsys.readouterr().out


def test_an_unreadable_explanation_is_a_warning_not_a_lost_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _selection_config(tmp_path, ai_extensions())
    fake = FakeArtifacts(_explanation())
    fake.payloads[EXPLANATION_ID] = b"{broken"

    with github_with_artifacts(fake, _selection_run()) as github:
        assert run(config, LATER) == 0

    assert "Test selection" not in github["upsert"].call_args.args[2]
    assert "::warning::Test selection section unavailable" in capsys.readouterr().out
    assert _report(config).collection_status == "complete"


def test_unavailable_references_leave_the_saving_unknown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _selection_config(tmp_path, ai_extensions())
    fake = FakeArtifacts(_explanation())

    def list_or_fail(name: str, run_id: int | None = None) -> list[GitHubArtifactV1]:
        if name == REFERENCE_ARTIFACT:
            raise httpx.HTTPError("artifact listing unavailable")
        return fake.list_artifacts(name, run_id)

    with github_with_artifacts(fake, _selection_run()) as github:
        github["list_artifacts"].side_effect = list_or_fail
        assert run(config, LATER) == 0

    sticky = github["upsert"].call_args.args[2]
    assert f"<strong>{SELECTED} / 1,087 files selected</strong>" in sticky
    assert "1m 18s longest-shard wall, 4m 53s summed test time" in sticky
    assert "less summed test time" not in sticky
    assert "::warning::Full-suite references unavailable" in capsys.readouterr().out
    assert _report(config).collection_status == "complete"


def test_action_config_reads_the_selection_inputs(monkeypatch, tmp_path: Path) -> None:
    for name, value in {
        "GITHUB_REPOSITORY": REPOSITORY,
        "INPUT_GITHUB_TOKEN": TOKEN,
        "INPUT_RUN_ID": str(RUN_ID),
        "INPUT_RUN_ATTEMPT": str(RUN_ATTEMPT),
        "INPUT_COMMIT_SHA": HEAD_SHA,
        "INPUT_REPORT_OUTPUT": str(tmp_path / "report.json"),
        "INPUT_MARKDOWN_OUTPUT": str(tmp_path / "report.md"),
        "INPUT_PROMETHEUS_OUTPUT": str(tmp_path / "report.prom"),
        "INPUT_TEST_SELECTION_ARTIFACT": f" {EXPLANATION_ARTIFACT} ",
        "INPUT_FULL_SUITE_REFERENCE_ARTIFACT": REFERENCE_ARTIFACT,
        "INPUT_FULL_SUITE_REFERENCE_OUTPUT": str(tmp_path / "reference.json"),
    }.items():
        monkeypatch.setenv(name, value)

    config = ActionConfig.from_environment()

    assert (config.test_selection_artifact, config.full_suite_reference_artifact) == (
        EXPLANATION_ARTIFACT,
        REFERENCE_ARTIFACT,
    )
    assert config.full_suite_reference_output == tmp_path / "reference.json"


def test_the_saving_uses_only_the_newest_few_comparable_runs(tmp_path: Path) -> None:
    config = _selection_config(tmp_path, ai_extensions())
    fake = FakeArtifacts(_explanation())
    references = [full_suite_reference(OLDER_RUN - offset) for offset in range(REFERENCE_SAMPLE + 2)]
    first_id = NEWEST_ID + len(fake.payloads)
    fake.payloads.update(
        {first_id + offset: reference.model_dump_json().encode() for offset, reference in enumerate(references)}
    )

    def list_many(name: str, run_id: int | None = None) -> list[GitHubArtifactV1]:
        if name == REFERENCE_ARTIFACT:
            return [artifact(first_id + offset, reference.run_id) for offset, reference in enumerate(references)]
        return fake.list_artifacts(name, run_id)

    with github_with_artifacts(fake, _selection_run()) as github:
        github["list_artifacts"].side_effect = list_many
        assert run(config, LATER) == 0

    section = _report(config).test_selection
    assert section is not None
    assert section.references == references[:REFERENCE_SAMPLE]


def test_a_reference_must_carry_measured_times() -> None:
    with pytest.raises(ValidationError, match="measured wall and summed test time"):
        full_suite_reference(NEWEST_RUN, timings=AI_TIMINGS.model_copy(update={"wall_seconds": None}))


@pytest.mark.parametrize("identity", ["valid", "run", "attempt", "head"])
def test_generic_work_artifact_matches_observed_source(tmp_path, identity):
    from ci_esta.ci_observability.work_selection import WorkDecisionV1, WorkSelectionV1
    plan = WorkSelectionV1(provider="bun", run_id=RUN_ID, run_attempt=RUN_ATTEMPT, head_sha=HEAD_SHA,
                           input_identity="tree abc", decisions=[WorkDecisionV1(name="Tests", decision="run", reason="Full")])
    data = plan.model_dump(mode="json")
    if identity == "run":
        data["run_id"] += 1
    elif identity == "attempt":
        data["run_attempt"] += 1
    elif identity == "head":
        data["head_sha"] = "b" * 40
    config = _config(tmp_path).model_copy(update={"work_selection_artifact": "ci-work-selection"})
    client = MagicMock(spec=GitHubActionsClient)
    client.list_artifacts.return_value = [artifact(42, run_id=RUN_ID)]
    client.read_single_file_artifact.return_value = json.dumps(data).encode()
    result = action_module._work_selection(client, config, _run_metadata())
    assert (result is not None) == (identity == "valid")


def test_action_default_uses_source_head_instead_of_pull_request_merge_sha(tmp_path):
    definition = yaml.safe_load((Path(__file__).parents[2] / "actions/ci-observability/action.yml").read_text())
    default = definition["inputs"]["commit-sha"]["default"]
    # In a pull_request job github.sha is the synthetic merge commit, while the
    # Actions run API identifies the source branch head.
    configured_sha = "b" * 40 if default == "${{ github.sha }}" else default
    config = _config(tmp_path, post_sticky=False).model_copy(update={"commit_sha": configured_sha})
    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(GitHubActionsClient, "list_jobs", return_value=[_job()]),
        patch.object(GitHubActionsClient, "list_commit_statuses", return_value=[_status()]) as statuses,
    ):
        assert run(config, LATER) == 0
    report = json.loads(config.report_output.read_text())
    assert report["collection_status"] == "complete"
    assert report["provenance"]["head_sha"] == HEAD_SHA
    statuses.assert_called_once_with(HEAD_SHA)


def test_unavailable_comment_preserves_test_results_without_zero_usage(tmp_path):
    config = _config(tmp_path, post_sticky=False)
    with patch.object(GitHubActionsClient, "get_run", side_effect=RuntimeError("identity unavailable")):
        assert run(config, LATER) == 0
    markdown = config.markdown_output.read_text()
    assert "42 passed, 0 failed" in markdown
    assert "identity unavailable" in markdown
    assert "0 min" not in markdown
    assert "0 rounded min" not in markdown
    assert "gates running" not in markdown
    assert "unavailable" in markdown


def test_explicit_wrong_source_head_still_rejects_collection(tmp_path):
    config = _config(tmp_path, post_sticky=False).model_copy(update={"commit_sha": "b" * 40})
    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run_metadata()),
        patch.object(GitHubActionsClient, "list_jobs") as jobs,
    ):
        assert run(config, LATER) == 0
    jobs.assert_not_called()
    report = json.loads(config.report_output.read_text())
    assert report["collection_status"] == "unavailable"
    assert "does not match" in report["collection_errors"][0]
