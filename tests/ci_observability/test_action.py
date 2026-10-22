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
from pydantic import BaseModel, JsonValue, ValidationError
from pytest_selective.impact_models import ExplanationUnavailable, SelectionExplanation, SelectionRoute

import ci_esta.ci_observability.action as action_module
from ci_esta.ci_observability.action import REFERENCE_SAMPLE, ActionConfig, run
from ci_esta.ci_observability.enrichment.profiles import pytest_timings
from ci_esta.ci_observability.github import GitHubActionsClient, GitHubArtifactV1
from ci_esta.ci_observability.models import (
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
    assert config.append_summary is False
    assert config.runner_sku_rates == [
        RunnerSkuRateV1(
            sku="linux_8_core",
            runner_label="8vcpu-runner",
            usd_per_minute=Decimal("0.022"),
        )
    ]


def test_run_writes_all_outputs_summary_and_sticky(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
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
    assert "| Merge-ready |" in config.markdown_output.read_text()
    assert "_pytest: 42 passed, 0 failed._" in config.markdown_output.read_text()
    assert "ci_raw_runner_seconds" in config.prometheus_output.read_text()
    assert summary_path.read_text() == config.markdown_output.read_text() + "\n"
    assert "report-file=" in action_output_path.read_text()
    assert upsert.call_args.args[0] == PR_NUMBER


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
    assert sticky.index("![tests: ") < sticky.index("#### 🎯 Test selection")
    assert f"| {SELECTED} of 1,087 files | 1m 18s | ▰▰▱▱▱▱▱▱▱▱ 4m 53s | 81% | unchanged |" in sticky
    # The latency report folds into one closed expander after the section; the footer stays visible.
    latency = sticky.index("<details><summary>⏱️ CI time and cost: ")
    assert sticky.index("#### 🎯 Test selection") < latency < sticky.index("| Merge-ready |")
    assert sticky.rstrip().endswith("· schema `ci-observability/v1`</sub>")
    assert sticky.index("</details>", sticky.index("| Merge-ready |")) < sticky.index(STICKY_MARKER)
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

    github["list_artifacts"].assert_not_called()
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

    assert "#### ⏱️ CI time and cost" in github["upsert"].call_args.args[2]
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

    assert f"| {SELECTED} of 1,087 files | 1m 18s | 4m 53s | — | unchanged |" in github["upsert"].call_args.args[2]
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
