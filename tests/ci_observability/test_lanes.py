"""The sticky's lane section: a pytest-selective lane plan, and what skipping its lanes saved."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_selective.ci import LanePlan

from ci_esta.ci_observability.action import ActionConfig, run
from ci_esta.ci_observability.github import GitHubActionsClient, GitHubArtifactV1
from ci_esta.ci_observability.lanes import job_family, render_lane_section, skipped_reference
from ci_esta.ci_observability.models import (
    CiObservabilityReportV1,
    GitHubJobV1,
    GitHubRunV1,
    LaneSelectionSectionV1,
    SkippedLaneReferenceV1,
)
from ci_esta.ci_observability.report import STICKY_MARKER, sticky_marker

from .builders import artifact

REPOSITORY = "gigaverse-app/example"
RUN_ID = 900
REFERENCE_RUN_ID = 800
WORKFLOW_ID = 7
LANE_ARTIFACT = "test-lane-selection"
LANE_ARTIFACT_ID = 61
START = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

MONGODB_ONLY = LanePlan(
    lanes={"mongodb": True, "saleor": False, "core": False},
    selected=["tests/mongodb/test_store.py"],
    changed=["tests/mongodb/test_store.py"],
    reason="dependency closure: 1 test file",
    lane_reasons={
        "mongodb": ["affected test: tests/mongodb/test_store.py"],
        "saleor": ["no affected tests or changed inputs"],
        "core": ["no affected tests or changed inputs"],
    },
)


def _job(name: str, conclusion: str, seconds: float | None = None, job_id: int = 1) -> GitHubJobV1:
    return GitHubJobV1(
        id=job_id,
        name=name,
        status="completed",
        conclusion=conclusion,
        started_at=START if seconds is not None else None,
        completed_at=START + timedelta(seconds=seconds) if seconds is not None else None,
    )


def _run(run_id: int, head_branch: str = "main") -> GitHubRunV1:
    return GitHubRunV1(
        id=run_id,
        name="CI",
        workflow_id=WORKFLOW_ID,
        run_attempt=1,
        event="pull_request" if run_id == RUN_ID else "push",
        status="completed",
        conclusion="success",
        created_at=START,
        run_started_at=START,
        head_branch=head_branch,
        head_sha="b" * 40,
    )


def test_a_skipped_matrix_and_its_expanded_jobs_share_a_family() -> None:
    assert job_family("saleor (${{ matrix.python }})") == job_family("saleor (3.14)") == "saleor"
    assert job_family("lint") == "lint"


def test_skipping_saves_what_the_skipped_families_took_on_the_reference_run() -> None:
    jobs = [
        _job("mongodb", "success", 50),
        _job("saleor (${{ matrix.python }})", "skipped"),
        _job("core", "skipped"),
        # Half of `demos` ran, so the sticky cannot tell which half the reference's time belongs to.
        _job("demos (a)", "skipped"),
        _job("demos (b)", "success", 30),
    ]
    reference_jobs = [
        _job("mongodb", "success", 60),
        _job("saleor (3.11)", "success", 240),
        _job("saleor (3.14)", "success", 180),
        _job("core", "failure", 90),  # Only a green job is a fair measure of the work.
        _job("demos (a)", "success", 100),
    ]

    reference = skipped_reference(jobs, _run(REFERENCE_RUN_ID), reference_jobs)

    assert reference == SkippedLaneReferenceV1(
        run_id=REFERENCE_RUN_ID, head_branch="main", jobs=["saleor (3.11)", "saleor (3.14)"], runner_seconds=420
    )


def test_nothing_skipped_or_nothing_comparable_is_no_estimate() -> None:
    assert (
        skipped_reference([_job("core", "success", 10)], _run(REFERENCE_RUN_ID), [_job("core", "success", 9)]) is None
    )
    assert skipped_reference([_job("core", "skipped")], _run(REFERENCE_RUN_ID), [_job("lint", "success", 9)]) is None


def test_the_section_says_what_ran_why_and_what_skipping_saved() -> None:
    reference = SkippedLaneReferenceV1(
        run_id=REFERENCE_RUN_ID, head_branch="main", jobs=["saleor"], runner_seconds=1500
    )

    section = render_lane_section(LaneSelectionSectionV1(plan=MONGODB_ONLY, reference=reference), REPOSITORY)

    assert section.startswith("<details>\n<summary><strong>Test lanes</strong>")
    assert "1 / 3 lanes selected" in section.split("</summary>", 1)[0]
    assert "Historical cost of skipped jobs: ≈25 runner-min" in section
    assert "The 1 changed file reaches `mongodb`; the other lanes were not selected." in section
    # Lanes that ran come first, with the path that selected them.
    assert section.index("| `mongodb` | selected | affected test `tests/mongodb/test_store.py` |") < section.index(
        "| `saleor` | not selected | no affected tests or changed inputs |"
    )
    assert f"[run {REFERENCE_RUN_ID}](https://github.com/{REPOSITORY}/actions/runs/{REFERENCE_RUN_ID})" in section


@pytest.mark.parametrize(
    ("plan", "takeaway"),
    [
        (
            MONGODB_ONLY.model_copy(
                update={
                    "lanes": dict.fromkeys(MONGODB_ONLY.lanes, True),
                    "reason": "global CI/dependency input",
                    "lane_reasons": dict.fromkeys(MONGODB_ONLY.lanes, ["global input: uv.lock"]),
                }
            ),
            "Every lane was selected: `uv.lock` is a CI or dependency input every lane reads.",
        ),
        (
            MONGODB_ONLY.model_copy(
                update={
                    "lanes": dict.fromkeys(MONGODB_ONLY.lanes, True),
                    "reason": "full-suite fallback: missing history",
                    "lane_reasons": dict.fromkeys(MONGODB_ONLY.lanes, ["full-suite fallback: missing history"]),
                }
            ),
            "⚠️ Every lane was selected because planning fell back: full-suite fallback: missing history.",
        ),
        (
            MONGODB_ONLY.model_copy(
                update={
                    "lanes": dict.fromkeys(MONGODB_ONLY.lanes, False),
                    "changed": ["README.md", "docs/a.md"],
                    "lane_reasons": {},
                }
            ),
            "No lane reads the 2 changed files: no test lane was selected.",
        ),
    ],
    ids=["global-input", "fallback", "docs-only"],
)
def test_the_takeaway_names_why_lanes_ran(plan: LanePlan, takeaway: str) -> None:
    assert takeaway in render_lane_section(LaneSelectionSectionV1(plan=plan))


def test_a_hostile_path_cannot_break_the_lane_table() -> None:
    plan = MONGODB_ONLY.model_copy(update={"lane_reasons": {"mongodb": ["affected test: a|b`c<script>"]}})

    section = render_lane_section(LaneSelectionSectionV1(plan=plan))

    assert "| `mongodb` | selected | affected test ``a\\|b`c<script>`` |" in section


def test_a_keyed_sticky_never_matches_the_bare_one() -> None:
    assert sticky_marker() == STICKY_MARKER
    keyed = sticky_marker("Widget Store comparison")
    assert keyed == "<!-- ci-observability-v1 key=widget-store-comparison -->"
    assert STICKY_MARKER not in keyed


class FakeLaneGitHub:
    """This run's lane plan, a fork's plan, and the default branch's last full run."""

    def __init__(self, plan_payload: bytes, *, reference_run: GitHubRunV1 | None) -> None:
        self.plan_payload = plan_payload
        self.reference_run = reference_run

    def list_artifacts(self, name: str, run_id: int | None = None) -> list[GitHubArtifactV1]:
        if name is None:
            return []
        assert (name, run_id) == (LANE_ARTIFACT, RUN_ID)
        return [artifact(LANE_ARTIFACT_ID + 1, RUN_ID, fork=True), artifact(LANE_ARTIFACT_ID, RUN_ID)]

    def read_single_file_artifact(self, artifact_id: int) -> bytes:
        assert artifact_id == LANE_ARTIFACT_ID, "a fork's upload is never read"
        return self.plan_payload

    def list_jobs(self, run_id: int, *, include_all_attempts: bool) -> list[GitHubJobV1]:
        if run_id == REFERENCE_RUN_ID:
            return [_job("mongodb", "success", 60, 11), _job("saleor (3.14)", "success", 600, 12)]
        return [_job("mongodb", "success", 50, 1), _job("saleor (${{ matrix.python }})", "skipped", None, 2)]


def _lane_config(tmp_path: Path) -> ActionConfig:
    return ActionConfig(
        repository=REPOSITORY,
        github_token="token",
        api_url="https://api.github.test",
        run_id=RUN_ID,
        run_attempt=1,
        commit_sha="b" * 40,
        pull_request_number=5,
        gate_selectors=[],
        repository_signals=[],
        extensions={},
        report_output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        prometheus_output=tmp_path / "report.prom",
        post_sticky=True,
        append_summary=False,
        lane_selection_artifact=LANE_ARTIFACT,
        sticky_key="CI",
    )


def _run_with(fake: FakeLaneGitHub, tmp_path: Path) -> tuple[CiObservabilityReportV1, str, str]:
    config = _lane_config(tmp_path)
    with (
        patch.object(GitHubActionsClient, "get_run", return_value=_run(RUN_ID, head_branch="feature")),
        patch.object(GitHubActionsClient, "list_jobs", side_effect=fake.list_jobs),
        patch.object(GitHubActionsClient, "list_overlapping_prior_runs", return_value=[]),
        patch.object(GitHubActionsClient, "list_artifacts", side_effect=fake.list_artifacts),
        patch.object(GitHubActionsClient, "read_single_file_artifact", side_effect=fake.read_single_file_artifact),
        patch.object(GitHubActionsClient, "default_branch", return_value="main"),
        patch.object(GitHubActionsClient, "latest_successful_push_run", return_value=fake.reference_run),
        patch.object(GitHubActionsClient, "upsert_sticky", return_value=1) as upsert,
    ):
        assert run(config, START + timedelta(minutes=5)) == 0
    report = CiObservabilityReportV1.model_validate_json(config.report_output.read_text())
    return report, upsert.call_args.args[1], upsert.call_args.args[2]


def test_the_action_prices_skipped_lanes_against_the_last_full_run(tmp_path: Path) -> None:
    fake = FakeLaneGitHub(MONGODB_ONLY.model_dump_json().encode(), reference_run=_run(REFERENCE_RUN_ID))

    report, marker, sticky = _run_with(fake, tmp_path)

    assert report.lane_selection is not None
    assert report.lane_selection.reference == SkippedLaneReferenceV1(
        run_id=REFERENCE_RUN_ID, head_branch="main", jobs=["saleor (3.14)"], runner_seconds=600
    )
    assert "![selected: 1 / 3 lanes](" in sticky
    assert "Historical cost of skipped jobs: ≈10 runner-min" in sticky
    assert marker == sticky_marker("CI") and marker in sticky


def test_an_unreadable_plan_is_a_warning_not_a_lost_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report, _, sticky = _run_with(FakeLaneGitHub(b"{broken", reference_run=None), tmp_path)

    assert report.lane_selection is None
    assert "Test lanes" not in sticky
    assert "::warning::Lane selection section unavailable" in capsys.readouterr().out
