"""
Pin the workflow-definition policy checks.

The base-branch-independence check exists because the failure it catches is
invisible: a filtered-out workflow reports *no* check on the PR, which looks
identical to "this PR needs no validation". So the checker has to flag every
spelling that makes a trigger depend on the base branch, and must stay quiet
for the push-side filters and the filter-less trigger forms that are correct.

The cancellation-yield check exists because that failure is invisible too: a
superseded run keeps a job alive, holds its concurrency group, and the
replacement run reports nothing at all while it waits. So the checker has to
catch every condition shape that forces a job true after cancellation, and stay
quiet for the ones a cancellation can never reach.
"""

from pathlib import Path

import pytest
import yaml

from ci_esta.testing.workflow_policy import (
    assert_no_cancel_immune_jobs,
    assert_pr_triggers_ignore_base_branch,
    find_base_branch_filtered_triggers,
    find_cancel_immune_jobs,
    iter_workflow_files,
    job_is_cancel_immune,
    workflows_in_scope,
)


@pytest.fixture
def workflows(tmp_path: Path) -> Path:
    directory = tmp_path / "workflows"
    directory.mkdir()
    return directory


def _write(workflows: Path, name: str, body: str) -> None:
    (workflows / name).write_text(body, encoding="utf-8")


def _keys(workflows: Path) -> list[str]:
    return [trigger.key for trigger in find_base_branch_filtered_triggers(workflows)]


class TestFilteredTriggersAreFlagged:
    def test_branches_on_pull_request_is_flagged(self, workflows: Path) -> None:
        _write(workflows, "type-check.yaml", "on:\n  pull_request:\n    branches: [main]\n")

        assert _keys(workflows) == ["type-check.yaml:pull_request"]

    def test_branches_ignore_is_flagged_too(self, workflows: Path) -> None:
        """It excludes bases instead of selecting them, but still keys on the base."""
        _write(workflows, "tests.yaml", "on:\n  pull_request:\n    branches-ignore: [main]\n")

        assert _keys(workflows) == ["tests.yaml:pull_request"]

    def test_pull_request_target_is_flagged(self, workflows: Path) -> None:
        _write(workflows, "fork.yaml", "on:\n  pull_request_target:\n    branches: [main]\n")

        assert _keys(workflows) == ["fork.yaml:pull_request_target"]

    def test_the_quoted_on_key_is_read_like_the_bare_one(self, workflows: Path) -> None:
        """YAML 1.1 reads a bare `on` as the boolean True; both spellings ship."""
        _write(workflows, "quoted.yaml", '"on":\n  pull_request:\n    branches: [main]\n')

        assert _keys(workflows) == ["quoted.yaml:pull_request"]

    def test_a_scalar_branch_filter_is_flagged(self, workflows: Path) -> None:
        _write(workflows, "scalar.yaml", "on:\n  pull_request:\n    branches: main\n")

        trigger = find_base_branch_filtered_triggers(workflows)[0]
        assert trigger.patterns == ("main",)

    def test_both_events_in_one_workflow_are_reported_separately(self, workflows: Path) -> None:
        _write(
            workflows,
            "both.yaml",
            "on:\n  pull_request:\n    branches: [main]\n  pull_request_target:\n    branches: [main]\n",
        )

        assert _keys(workflows) == ["both.yaml:pull_request", "both.yaml:pull_request_target"]


class TestCorrectWorkflowsStayQuiet:
    def test_a_push_branch_filter_is_not_flagged(self, workflows: Path) -> None:
        """The control: on push the filter selects the pushed branch, which is its job."""
        _write(
            workflows,
            "type-check.yaml",
            "on:\n  push:\n    branches: [main]\n  pull_request:\n    paths: ['**/*.py']\n",
        )

        assert _keys(workflows) == []

    def test_a_path_filter_alone_is_not_flagged(self, workflows: Path) -> None:
        _write(workflows, "docs.yaml", "on:\n  pull_request:\n    paths: ['docs/**']\n")

        assert _keys(workflows) == []

    def test_the_shorthand_trigger_forms_cannot_carry_a_filter(self, workflows: Path) -> None:
        _write(workflows, "scalar-on.yaml", "on: pull_request\n")
        _write(workflows, "list-on.yaml", "on: [push, pull_request]\n")

        assert _keys(workflows) == []

    def test_a_workflow_without_a_pull_request_trigger_is_skipped(self, workflows: Path) -> None:
        """
        The rot that broke the hand-listed version: a workflow folded into
        another one keeps its file but loses the trigger the check named.
        """
        _write(workflows, "typecheck.yaml", "on:\n  workflow_dispatch:\n")

        assert _keys(workflows) == []

    def test_non_workflow_and_unparseable_entries_are_ignored(self, workflows: Path) -> None:
        _write(workflows, "real.yaml", "on:\n  pull_request:\n    types: [opened]\n")
        _write(workflows, "README.md", "on:\n  pull_request:\n    branches: [main]\n")
        _write(workflows, "empty.yaml", "")
        (workflows / "nested").mkdir()

        assert _keys(workflows) == []

    def test_a_directory_named_like_a_workflow_is_not_read(self, workflows: Path) -> None:
        """It matches the suffix test but raises on read, so it must be filtered out."""
        _write(workflows, "real.yaml", "on:\n  pull_request:\n    types: [opened]\n")
        (workflows / "trap.yaml").mkdir()

        assert [path.name for path in iter_workflow_files(workflows)] == ["real.yaml"]


class TestAssertion:
    def test_it_passes_when_every_trigger_is_base_branch_independent(self, workflows: Path) -> None:
        _write(workflows, "tests.yaml", "on:\n  pull_request:\n    types: [opened]\n")

        assert_pr_triggers_ignore_base_branch(workflows)

    def test_it_names_the_workflow_the_event_and_the_patterns(self, workflows: Path) -> None:
        _write(workflows, "type-check.yaml", "on:\n  pull_request:\n    branches: [main, staging]\n")

        with pytest.raises(AssertionError) as failure:
            assert_pr_triggers_ignore_base_branch(workflows)

        message = str(failure.value)
        assert "type-check.yaml:pull_request" in message
        assert "['main', 'staging']" in message

    def test_an_allowed_trigger_does_not_fail_the_assertion(self, workflows: Path) -> None:
        _write(workflows, "merge-to-main.yaml", "on:\n  pull_request:\n    branches: [main]\n")

        assert_pr_triggers_ignore_base_branch(workflows, allow={"merge-to-main.yaml:pull_request"})

    def test_allowing_one_trigger_does_not_excuse_another(self, workflows: Path) -> None:
        """A trivial implementation that returns early on any allowance would pass otherwise."""
        _write(workflows, "merge-to-main.yaml", "on:\n  pull_request:\n    branches: [main]\n")
        _write(workflows, "type-check.yaml", "on:\n  pull_request:\n    branches: [main]\n")

        with pytest.raises(AssertionError) as failure:
            assert_pr_triggers_ignore_base_branch(workflows, allow={"merge-to-main.yaml:pull_request"})

        message = str(failure.value)
        assert "type-check.yaml:pull_request" in message
        assert "merge-to-main.yaml" not in message


class TestItRefusesToPassOnNothing:
    """
    The failure this whole invariant exists to catch, turned on itself.

    A directory-wide check is vacuously true over an empty directory, so a mistyped
    path would leave every consumer's guard green forever while asserting nothing --
    indistinguishable from a repository that genuinely has no offending workflow.
    """

    def test_an_empty_workflow_directory_is_a_failure(self, workflows: Path) -> None:
        with pytest.raises(AssertionError, match="No workflow files found"):
            assert_pr_triggers_ignore_base_branch(workflows)

    def test_a_mistyped_directory_is_a_failure(self, workflows: Path) -> None:
        with pytest.raises(AssertionError, match="No workflow files found"):
            assert_pr_triggers_ignore_base_branch(workflows / "workflow")

    def test_a_directory_holding_only_non_workflows_is_a_failure(self, workflows: Path) -> None:
        _write(workflows, "README.md", "not a workflow\n")

        with pytest.raises(AssertionError, match="No workflow files found"):
            assert_pr_triggers_ignore_base_branch(workflows)

    def test_a_fully_allowed_directory_is_still_a_real_scan(self, workflows: Path) -> None:
        """Emptiness is about what was scanned, not about what was left to report."""
        _write(workflows, "merge-to-main.yaml", "on:\n  pull_request:\n    branches: [main]\n")

        assert_pr_triggers_ignore_base_branch(workflows, allow={"merge-to-main.yaml:pull_request"})


def test_backend_commons_own_workflows_hold_the_invariant() -> None:
    """This repo's reusable workflows are consumed by stacked PRs too."""
    assert_pr_triggers_ignore_base_branch(Path(__file__).parents[2] / ".github" / "workflows")


CANCELLING_HEADER = """
on:
  pull_request:
    types: [opened, synchronize]
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
"""

ALWAYS_JOB = """
jobs:
  stage:
    if: always()
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
"""


def _immune_keys(workflows: Path) -> list[str]:
    return [job.key for job in find_cancel_immune_jobs(workflows)]


class TestCancelImmunityIsRecognised:
    @pytest.mark.parametrize(
        ("condition", "immune"),
        [
            ("always() && needs.plan.result == 'success'", True),
            ("${{ always() }}", True),
            ("always ( ) && needs.plan.result == 'success'", True),
            ("always() && !cancelled() && needs.plan.result == 'success'", False),
            ("always() && ! cancelled()", False),
            # Expression functions are case-insensitive, so an uppercase
            # spelling is a real offender, not a different function.
            ("ALWAYS() && needs.plan.result == 'success'", True),
            ("Always()", True),
            # Both spellings of the negation are valid and must be honoured.
            ("always() && !(cancelled())", False),
            ("ALWAYS() && !CANCELLED()", False),
            ("!cancelled() && needs.plan.result == 'success'", False),
            ("needs.plan.result == 'success'", False),
            # A cleanup job that runs only on cancellation never forces itself
            # true on the paths that matter, so it is not immune.
            ("cancelled()", False),
            ("", False),
            (None, False),
        ],
    )
    def test_only_an_unqualified_always_is_cancel_immune(self, condition: str | None, immune: bool) -> None:
        assert job_is_cancel_immune(condition) is immune

    def test_the_immune_job_is_flagged_and_its_qualified_sibling_is_not(self, workflows: Path) -> None:
        _write(
            workflows,
            "validate.yaml",
            CANCELLING_HEADER
            + """
jobs:
  plan:
    if: always() && (needs.guard.result == 'skipped')
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
  report:
    if: always() && !cancelled()
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
""",
        )

        assert _immune_keys(workflows) == ["validate.yaml:plan"]


class TestScopeFollowsWhatCanActuallyCancel:
    @pytest.mark.parametrize(
        ("header", "in_scope"),
        [
            ("on: pull_request\nconcurrency:\n  group: g\n  cancel-in-progress: true\n", True),
            ("on: pull_request\nconcurrency:\n  group: g\n  cancel-in-progress: ${{ github.event_name }}\n", True),
            ("on: pull_request\nconcurrency:\n  group: g\n  cancel-in-progress: false\n", False),
            # The group-only shorthand queues, it never cancels.
            ("on: pull_request\nconcurrency: deploy\n", False),
            ("on: pull_request\n", False),
            # A reusable workflow with no caller here is published for another
            # repository, where a cancelling caller is the norm.
            ("on:\n  workflow_call:\n", True),
            ("on: workflow_call\n", True),
            ("'on':\n  workflow_call:\n", True),
        ],
    )
    def test_a_workflow_is_in_scope_when_its_runs_can_be_cancelled(self, header: str, in_scope: bool) -> None:
        assert ("solo.yaml" in workflows_in_scope({"solo.yaml": yaml.safe_load(header)})) is in_scope

    def test_a_workflow_that_cannot_cancel_may_always_run_a_summary_job(self, workflows: Path) -> None:
        """A deploy summary has nothing to strand, which is why scope is not repo-wide."""
        _write(workflows, "deploy.yaml", "on: push\n" + ALWAYS_JOB)

        assert find_cancel_immune_jobs(workflows) == []

    def test_a_reusable_stage_of_an_uncancellable_pipeline_is_left_alone(self, workflows: Path) -> None:
        """
        The real shape this protects: gigaverse-ai's deploy pipeline has no
        concurrency at all, and the reusable build-and-deploy stage it calls
        runs an `always()` metrics job. No cancellation can reach it, so
        flagging it would hand the consumer a false positive.
        """
        _write(
            workflows,
            "deploy.yaml",
            """
on: push
jobs:
  transcript:
    uses: ./.github/workflows/build-and-deploy-transcript.yaml
""",
        )
        _write(workflows, "build-and-deploy-transcript.yaml", "on:\n  workflow_call:\n" + ALWAYS_JOB)

        assert find_cancel_immune_jobs(workflows) == []

    def test_a_reusable_workflow_called_by_a_cancelling_caller_is_judged(self, workflows: Path) -> None:
        _write(
            workflows,
            "validate.yaml",
            CANCELLING_HEADER
            + """
jobs:
  delegate:
    uses: ./.github/workflows/reusable-scan.yaml
""",
        )
        _write(workflows, "reusable-scan.yaml", "on:\n  workflow_call:\n" + ALWAYS_JOB)

        assert _immune_keys(workflows) == ["reusable-scan.yaml:stage"]

    def test_scope_reaches_a_reusable_workflow_called_by_another_reusable_one(self, workflows: Path) -> None:
        _write(
            workflows,
            "validate.yaml",
            CANCELLING_HEADER
            + """
jobs:
  delegate:
    uses: ./.github/workflows/middle.yaml
""",
        )
        _write(
            workflows,
            "middle.yaml",
            """
on:
  workflow_call:
jobs:
  delegate:
    uses: ./.github/workflows/inner.yaml
""",
        )
        _write(workflows, "inner.yaml", "on:\n  workflow_call:\n" + ALWAYS_JOB)

        assert _immune_keys(workflows) == ["inner.yaml:stage"]

    def test_a_job_with_its_own_cancelling_concurrency_is_judged(self, workflows: Path) -> None:
        """
        A job may carry `concurrency:` while its workflow carries none, and
        that group cancels the job just as a workflow-level one would. Reading
        only the workflow level leaves such a job permanently unguarded; three
        workflows across these repositories have this shape.
        """
        _write(
            workflows,
            "observability.yaml",
            """
on: push
jobs:
  publish:
    concurrency:
      group: observability-${{ github.ref }}
      cancel-in-progress: true
    if: always()
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
""",
        )

        assert _immune_keys(workflows) == ["observability.yaml:publish"]

    def test_a_job_whose_own_concurrency_only_queues_is_left_alone(self, workflows: Path) -> None:
        _write(
            workflows,
            "observability.yaml",
            """
on: push
jobs:
  publish:
    concurrency:
      group: observability
      cancel-in-progress: false
    if: always()
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
""",
        )

        assert find_cancel_immune_jobs(workflows) == []


class TestTheCancellationAssertionReportsUsefully:
    def test_it_names_each_offender_and_how_to_fix_it(self, workflows: Path) -> None:
        _write(
            workflows,
            "validate.yaml",
            CANCELLING_HEADER
            + """
jobs:
  plan:
    if: always() && needs.guard.result == 'skipped'
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
""",
        )

        with pytest.raises(AssertionError) as failure:
            assert_no_cancel_immune_jobs(workflows)

        message = str(failure.value)
        assert "validate.yaml:plan" in message
        assert "needs.guard.result == 'skipped'" in message
        assert "!cancelled()" in message

    def test_an_allowed_job_is_accepted_while_its_neighbour_still_fails(self, workflows: Path) -> None:
        _write(
            workflows,
            "validate.yaml",
            CANCELLING_HEADER
            + """
jobs:
  plan:
    if: always()
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
  publish:
    if: always()
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
""",
        )

        assert_no_cancel_immune_jobs(workflows, allow=["validate.yaml:plan", "validate.yaml:publish"])

        with pytest.raises(AssertionError, match="validate.yaml:publish"):
            assert_no_cancel_immune_jobs(workflows, allow=["validate.yaml:plan"])

    def test_a_stale_allow_entry_is_reported_so_it_gets_removed(self, workflows: Path) -> None:
        """An allow entry that no longer matches anything is drift, not silence."""
        _write(
            workflows,
            "validate.yaml",
            CANCELLING_HEADER
            + """
jobs:
  fine:
    if: "!cancelled()"
    runs-on: ubuntu-24.04
    steps: [{run: 'true'}]
""",
        )

        with pytest.raises(AssertionError, match="validate.yaml:departed"):
            assert_no_cancel_immune_jobs(workflows, allow=["validate.yaml:departed"])

    def test_an_empty_directory_is_a_failure_not_a_pass(self, workflows: Path) -> None:
        """Shared with the base-branch check: a vacuous invariant is silent green."""
        with pytest.raises(AssertionError, match="No workflow files found"):
            assert_no_cancel_immune_jobs(workflows)

    def test_an_unparseable_workflow_names_the_file(self, workflows: Path) -> None:
        _write(workflows, "broken.yaml", "on: push\njobs:\n  a: [unclosed\n")

        with pytest.raises(ValueError, match="broken.yaml"):
            find_cancel_immune_jobs(workflows)


def test_backend_commons_own_workflows_yield_to_cancellation() -> None:
    """The repository that ships the rule has to satisfy it."""
    assert_no_cancel_immune_jobs(Path(__file__).parents[2] / ".github" / "workflows")
