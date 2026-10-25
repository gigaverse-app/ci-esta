"""The sticky's gantt: one row per job, its wait, its run, and the chain the merge waited on."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ci_esta.ci_observability.critical_path import CriticalPathResult
from ci_esta.ci_observability.models import CiObservabilityReportV1, GitHubJobV1, GitHubRunV1
from ci_esta.ci_observability.report import _observe_job, build_report
from ci_esta.ci_observability.timeline import critical_chain, render_timeline

CREATED = datetime(2026, 10, 22, 21, 0, tzinfo=timezone.utc)
OBSERVED = CREATED + timedelta(minutes=10)


def _job(job_id: int, name: str, queued: int, start: int, end: int) -> GitHubJobV1:
    return GitHubJobV1(
        id=job_id,
        name=name,
        status="completed",
        conclusion="success",
        created_at=CREATED + timedelta(seconds=queued),
        started_at=CREATED + timedelta(seconds=start),
        completed_at=CREATED + timedelta(seconds=end),
    )


#: The shape of pytest-selective run 39856136423: planning, then a matrix that needs it; the
#: Windows 3.14 leg finished last and the merge waited on it.
JOBS = [
    _job(1, "quality", 1, 21, 37),
    _job(2, "select-tests", 1, 25, 39),
    _job(3, "tests (3.11, ubuntu-latest)", 39, 87, 110),
    _job(4, "tests (3.14, windows-latest)", 39, 52, 221),
    _job(5, "tests (3.11, windows-latest)", 39, 42, 201),
    _job(6, "Contracts / Contract suite · due-application · 1", 1, 12, 102),
]


def _observed() -> list:
    return [_observe_job(job, CREATED, OBSERVED) for job in JOBS]


def test_the_chain_walks_back_through_the_job_that_finished_as_each_was_created() -> None:
    chain = critical_chain(_observed(), merge_ready_seconds=221)

    assert [job.name for job in chain] == ["select-tests", "tests (3.14, windows-latest)"]


def test_without_merge_ready_the_chain_ends_at_the_last_job_to_finish() -> None:
    chain = critical_chain(_observed(), merge_ready_seconds=None)

    assert chain[-1].name == "tests (3.14, windows-latest)"


def test_a_job_created_with_the_run_has_no_predecessor() -> None:
    quality = [job for job in _observed() if job.name == "quality"]

    assert [job.name for job in critical_chain(quality, merge_ready_seconds=None)] == ["quality"]


def _report() -> CiObservabilityReportV1:
    run = GitHubRunV1(
        id=1,
        name="CI",
        run_attempt=1,
        status="completed",
        conclusion="success",
        created_at=CREATED,
        run_started_at=CREATED,
        head_sha="c" * 40,
    )
    report = build_report(
        repository="gigaverse-app/example",
        pull_request_number=None,
        run=run,
        latest_jobs=JOBS,
        billing_jobs=JOBS,
        commit_statuses=[],
        gate_selectors=[],
        observed_at=OBSERVED,
    )
    return report


def _gantt() -> str:
    return "\n".join(render_timeline(_report()))


def test_each_job_is_one_row_labeled_with_its_run_and_its_wait() -> None:
    gantt = _gantt()

    # The bar is the run, labeled with its wait for a runner; a wait under five seconds is noise.
    assert "    section tests · 3.11, ubuntu-latest\n    23s · ⏳ 48s :done, j" in gantt
    assert "    section tests · 3.11, windows-latest\n    2m 39s :done, j" in gantt
    assert "    section quality\n    16s · ⏳ 20s :done, j" in gantt
    assert ":active" not in gantt
    # A reusable workflow's caller prefix is dropped, and a long name keeps its distinguishing end.
    assert "    section Contract suite ·…application · 1\n" in gantt
    assert "Contracts /" not in gantt
    # Rows run in the order jobs became runnable.
    assert gantt.index("section quality") < gantt.index("section tests · 3.11, ubuntu-latest")


def test_bars_are_dates_github_parses_and_end_clear_of_its_controls() -> None:
    gantt = "\n".join(render_timeline(_report().model_copy(update={"merge_ready_from_creation_seconds": 221.0})))

    # GitHub's Mermaid drew every `dateFormat X` bar from the axis origin; dates parse everywhere.
    assert "    dateFormat YYYY-MM-DD HH:mm:ss\n    axisFormat %M:%S\n" in gantt
    assert "2m 49s · ⏳ 13s :crit, j4, 2000-01-01 00:00:52, 2000-01-01 00:03:41\n" in gantt
    # GitHub ignores rightPadding: the CI gates passed bar extends the axis past the last job instead,
    # so GitHub's zoom and pan buttons cover it rather than the jobs.
    assert "    section ✅ CI gates passed 3m 41s\n    ✅ :active, m, 2000-01-01 00:03:41, 2000-01-01 00:04:48\n" in gantt


def test_the_theme_reads_on_both_github_themes_and_never_draws_a_today_line() -> None:
    gantt = _gantt()

    assert '"theme": "base"' in gantt
    assert '"critBkgColor": "#EA580C"' in gantt
    assert "    todayMarker off\n" in gantt


def test_the_needs_graph_path_overrides_the_timestamp_inference() -> None:
    graph = CriticalPathResult(status="complete", observed_path=["quality", "tests (3.11, windows-latest)"])
    gantt = "\n".join(render_timeline(_report().model_copy(update={"critical_path": graph})))

    assert "    section quality\n    16s · ⏳ 20s :crit, " in gantt
    assert "    section tests · 3.11, windows-latest\n    2m 39s :crit, " in gantt
    assert "    section select-tests\n    14s · ⏳ 24s :done, " in gantt
    assert "the critical path through the workflow's `needs` graph" in gantt


def test_an_unavailable_graph_falls_back_to_the_inferred_chain() -> None:
    graph = CriticalPathResult(status="unavailable", reason="no gates")
    gantt = "\n".join(render_timeline(_report().model_copy(update={"critical_path": graph})))

    assert "    section select-tests\n    14s · ⏳ 24s :crit, " in gantt
    assert "inferred from when each job was created" in gantt
