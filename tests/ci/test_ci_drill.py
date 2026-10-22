"""
The drill's verdict: a validation job that passed on a commit and runs again on it is repeated work.

The fixture is gigaverse-backend#4957, the probe where one head was re-triggered twice and
every lane and the unit shards ran all three times. A harness that passes that is broken.
"""

import datetime as dt
import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from ci_esta.drill import (
    ACTIONS,
    PROFILES,
    RETAG_LABEL,
    SCENARIOS,
    DrillFailure,
    JobOutcome,
    MainMovedCard,
    RunOutcome,
    Scorecard,
    Selection,
    compare,
    compare_main_moved,
    drill_branch,
    met,
    parse_selection,
    pinned,
    plan_delta,
    report,
    require_current_bump,
    retag_pin,
    score,
)

FIXTURE = Path(__file__).with_name("ci_drill_probe_4957.json")
BACKEND = PROFILES["gigaverse-backend"]
HEAD = "eaf32c3e21848c818623a94455ab8cfe61def5b2"


def _probe_runs() -> list[RunOutcome]:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))["runs"]
    return [
        RunOutcome(label=label, run_id=index, jobs=tuple(JobOutcome.model_validate(job) for job in jobs))
        for index, (label, jobs) in enumerate(recorded.items())
    ]


def _reused(runs: list[RunOutcome], jobs: set[str]) -> list[RunOutcome]:
    """The same runs, as a working reuse would have produced them: the named jobs skipped."""
    first, *retriggers = runs
    return [
        first,
        *(
            run.model_copy(
                update={
                    "jobs": tuple(
                        job.model_copy(update={"conclusion": "skipped"}) if job.name in jobs else job
                        for job in run.jobs
                    )
                }
            )
            for run in retriggers
        ),
    ]


# What working reuse skips on a re-trigger: the lanes, the unit shards and the rebuilt image.
VALIDATED_JOBS = {
    "Check Python types, migrations and workflow policy",
    "Test unit behavior · 6 concurrent shards",
    "Build image for tests",
}


def test_the_recorded_probe_fails_and_names_what_repeated() -> None:
    card = score(BACKEND, "main", HEAD, _probe_runs())

    assert not card.passed
    repeated = {(item.scenario, item.job) for item in card.repeated}
    for scenario in ("ready_immediately", "ready_after_4_minutes"):
        assert (scenario, "Check Python types, migrations and workflow policy") in repeated
        assert (scenario, "Test unit behavior · N concurrent shards") in repeated


def test_working_reuse_passes() -> None:
    """CONTROL: the same runs with the validated jobs skipped on re-trigger pass."""
    runs = _reused(_probe_runs(), VALIDATED_JOBS)

    card = score(BACKEND, "update-backend-common-pr216", HEAD, runs)

    assert card.passed, card.repeated
    assert "PASS" in card.markdown()


def test_reusing_only_one_lane_still_fails() -> None:
    runs = _reused(_probe_runs(), {"Check Python types, migrations and workflow policy"})

    card = score(BACKEND, "update-backend-common-pr216", HEAD, runs)

    assert {item.job for item in card.repeated} == {"Test unit behavior · N concurrent shards", "Build image for tests"}


@pytest.mark.parametrize(
    "job",
    ["Plan test paths", "Resolve backend check gate", "Publish unit test artifacts", "Lint OpenAPI compatibility"],
)
def test_declared_always_run_jobs_are_not_repeated_work(job: str) -> None:
    card = score(BACKEND, "main", HEAD, _probe_runs())

    assert job not in card.validated
    assert job not in {item.job for item in card.repeated}


def test_the_image_built_by_the_ready_event_is_repeated_work_when_built_again() -> None:
    """The draft skips the image and the first ready builds it; building it again for the same commit is a repeat."""
    card = score(BACKEND, "main", HEAD, _probe_runs())

    assert ("ready_after_4_minutes", "Build image for tests") in {(item.scenario, item.job) for item in card.repeated}
    assert ("ready_immediately", "Build image for tests") not in {(item.scenario, item.job) for item in card.repeated}
    assert "Test search integration · real OpenSearch" not in card.validated


def test_every_always_run_rule_says_why() -> None:
    for profile in PROFILES.values():
        for rule in profile.always_runs:
            assert len(rule.reason) > 10, rule


def _timed(runs: list[RunOutcome], seconds: float) -> list[RunOutcome]:
    return [run.model_copy(update={"wall_seconds": seconds}) for run in runs]


def test_a_fix_that_stops_the_repeats_is_an_improvement_over_main() -> None:
    main = score(BACKEND, "main", HEAD, _timed(_probe_runs(), 300))
    fixed = score(BACKEND, "update-backend-common-pr216", HEAD, _timed(_reused(_probe_runs(), VALIDATED_JOBS), 120))

    comparison = compare(main, fixed)

    assert comparison.verdict == "improved"
    assert met("improved", [main, fixed], [comparison])


def test_identical_behaviour_is_unchanged_not_improved() -> None:
    """CONTROL: a change that alters nothing cannot claim an improvement."""
    main = score(BACKEND, "main", HEAD, _timed(_probe_runs(), 300))
    same = score(BACKEND, "update-backend-common-pr216", HEAD, _timed(_probe_runs(), 300))

    comparison = compare(main, same)

    assert comparison.verdict == "unchanged"
    assert not met("improved", [main, same], [comparison])


@pytest.mark.parametrize(
    ("candidate_runs", "reason"),
    [
        (lambda runs: _timed(runs, 600), "took 1200s against 600s"),
        (
            lambda runs: [runs[0], runs[1].model_copy(update={"conclusion": "failure"}), *runs[2:]],
            "red run on the candidate",
        ),
    ],
    ids=["slower", "red"],
)
def test_a_slower_or_red_candidate_is_a_regression(
    candidate_runs: Callable[[list[RunOutcome]], list[RunOutcome]], reason: str
) -> None:
    main = score(BACKEND, "main", HEAD, _timed(_probe_runs(), 300))
    candidate = score(BACKEND, "update-backend-common-pr216", HEAD, candidate_runs(_timed(_probe_runs(), 300)))

    comparison = compare(main, candidate)

    assert comparison.verdict == "regressed"
    assert any(reason in item for item in comparison.reasons), comparison.reasons
    assert not met("pass", [main, candidate], [comparison])


def test_a_new_repeat_that_main_does_not_have_is_a_regression() -> None:
    main = score(BACKEND, "main", HEAD, _reused(_probe_runs(), VALIDATED_JOBS))
    candidate = score(BACKEND, "update-backend-common-pr216", HEAD, _probe_runs())

    comparison = compare(main, candidate)

    assert comparison.verdict == "regressed"
    assert any("which main validated and reused" in item for item in comparison.reasons)


def test_a_stale_bump_branch_is_refused() -> None:
    record = json.dumps({"sha": "a" * 40, "runtime_changed": False})

    require_current_bump(record, "a" * 40, "update-backend-common-pr1")
    with pytest.raises(RuntimeError, match="not the source head"):
        require_current_bump(record, "b" * 40, "update-backend-common-pr1")


def test_scenarios_have_unique_labels_and_known_actions() -> None:
    labels = [scenario.label for scenario in SCENARIOS.values()]

    assert len(set(labels)) == len(labels)
    assert {scenario.action for scenario in SCENARIOS.values()} <= set(ACTIONS)


AI = PROFILES["gigaverse-ai"]


@pytest.mark.parametrize(
    "rerun_name",
    ["Run pytest (2 concurrent shards)", "Run pytest (${{ needs.plan.outputs.shard-count }} concurrent shards)"],
)
def test_a_rerun_under_another_shard_count_is_still_a_repeat(rerun_name: str) -> None:
    """Job names carry the shard count, so a re-run with a different count must still match."""
    first = RunOutcome(
        label="first run", run_id=1, jobs=(JobOutcome(name="Run pytest (3 concurrent shards)", conclusion="success"),)
    )
    rerun = RunOutcome(
        label="ready right after green", run_id=2, jobs=(JobOutcome(name=rerun_name, conclusion="success"),)
    )

    card = score(AI, "main", HEAD, [first, rerun])

    assert [item.job for item in card.repeated] == ["Run pytest (N concurrent shards)"]


def test_a_skipped_rerun_under_an_unrendered_name_is_not_a_repeat() -> None:
    """CONTROL: gigaverse-ai skips the pytest job under an unrendered name when evidence is reused."""
    first = RunOutcome(
        label="first run", run_id=1, jobs=(JobOutcome(name="Run pytest (3 concurrent shards)", conclusion="success"),)
    )
    rerun = RunOutcome(
        label="ready right after green",
        run_id=2,
        jobs=(
            JobOutcome(
                name="Run pytest (${{ needs.plan.outputs.shard-count }} concurrent shards)", conclusion="skipped"
            ),
        ),
    )

    assert score(AI, "main", HEAD, [first, rerun]).passed


NOW = dt.datetime(2026, 9, 23, 12, 5, 56, tzinfo=dt.UTC)


def test_drills_started_in_the_same_second_get_distinct_branches() -> None:
    """The main and bump-branch drills of one consumer start together; their branches must not collide."""
    names = {
        drill_branch(BACKEND, base, NOW, token)
        for base in ("main", "update-backend-common-pr216")
        for token in ("a1b2c3", "d4e5f6")
    }

    assert len(names) == 4
    assert all(re.fullmatch(r"ci-drill/[0-9A-Za-z._/-]+", name) for name in names), names


def test_one_failed_drill_is_reported_without_losing_the_others() -> None:
    card = score(BACKEND, "main", HEAD, _probe_runs())
    failure = DrillFailure(consumer=BACKEND.repository, base="update-backend-common-pr216", error="boom")

    text = report(216, [card], [], [failure])

    assert "boom" in text
    assert card.consumer in text
    assert not met("pass", [card], [], [failure])


def test_a_job_first_admitted_on_ready_and_run_again_later_is_a_repeat() -> None:
    """Drafts skip some jobs; once one has passed on this commit, running it again is repeated work."""
    scan = "Source security scan"
    runs = [
        RunOutcome(label="first run", run_id=1, jobs=(JobOutcome(name=scan, conclusion="skipped"),)),
        RunOutcome(label="ready right after green", run_id=2, jobs=(JobOutcome(name=scan, conclusion="success"),)),
        RunOutcome(label="ready again 4 minutes later", run_id=3, jobs=(JobOutcome(name=scan, conclusion="success"),)),
    ]

    card = score(AI, "main", HEAD, runs)

    assert [(item.scenario, item.job) for item in card.repeated] == [("ready again 4 minutes later", scan)]


def _card(base: str, first: dict[str, str], *retriggers: dict[str, str]) -> Scorecard:
    labels = ["ready right after green", "ready again 4 minutes later"]
    runs = [
        RunOutcome(label="first run", run_id=1, jobs=tuple(JobOutcome(name=n, conclusion=c) for n, c in first.items()))
    ]
    runs += [
        RunOutcome(label=labels[i], run_id=i + 2, jobs=tuple(JobOutcome(name=n, conclusion=c) for n, c in jobs.items()))
        for i, jobs in enumerate(retriggers)
    ]
    return score(BACKEND, base, HEAD, runs)


def test_waste_main_also_has_is_pre_existing_not_a_regression() -> None:
    """
    The #216 drill: main skipped the image on the draft and rebuilt it later; the candidate built it
    every time. The same waste exists on main, so it is reported, not called a regression.
    """
    image, lane = "Build image for tests", "Check Python types, migrations and workflow policy"
    main = _card(
        "main",
        {image: "skipped", lane: "success"},
        {image: "success", lane: "success"},
        {image: "success", lane: "success"},
    )
    fixed = _card(
        "update-backend-common-pr216",
        {image: "success", lane: "success"},
        {image: "success", lane: "skipped"},
        {image: "success", lane: "skipped"},
    )

    comparison = compare(main, fixed)

    assert comparison.verdict == "improved", comparison.reasons
    assert any("also repeats on main" in reason and image in reason for reason in comparison.reasons)


def test_a_repeat_main_does_not_have_for_a_job_main_validated_is_a_regression() -> None:
    """CONTROL: main validated the lane and reused it; the candidate repeats it. That is a regression."""
    lane = "Check Python types, migrations and workflow policy"
    main = _card("main", {lane: "success"}, {lane: "skipped"})
    worse = _card("update-backend-common-pr216", {lane: "success"}, {lane: "success"})

    assert compare(main, worse).verdict == "regressed"


# The main-moved drill: gigaverse-backend#4959 ran 750/750 files after main edited settings.py,
# where the PR's diff against main selects 7.
PLAN_LOG = """Plan test paths	Select affected test files	2026-09-23T14:55:04Z Test impact: 750/750 files; full; 1.12s planning"""


def test_the_plan_log_selection_line_is_read() -> None:
    assert parse_selection(PLAN_LOG) == Selection(selected=750, total=750, mode="full")
    assert parse_selection("no planner here") is None


def _moved(
    base: str, selected: int, *, seconds: float = 300, after: str = "success", validated_selected: int = 6
) -> MainMovedCard:
    validated = RunOutcome(
        label="validated PR",
        run_id=1,
        jobs=(),
        wall_seconds=300,
        selection=Selection(selected=validated_selected, total=750, mode="scoped"),
    )
    moved = RunOutcome(
        label="after main moved",
        run_id=2,
        jobs=(),
        conclusion=after,
        wall_seconds=seconds,
        selection=Selection(selected=selected, total=750, mode="full" if selected == 750 else "scoped"),
    )
    return MainMovedCard(consumer=BACKEND.repository, base=base, runs=(validated, moved))


def test_selecting_fewer_tests_after_main_moved_is_an_improvement() -> None:
    comparison = compare_main_moved(
        _moved("main", 750, seconds=530), _moved("update-backend-common-pr217", 7, seconds=180)
    )
    assert comparison.verdict == "improved"
    assert "750 → 7 of 750" in "; ".join(comparison.reasons)


def test_the_same_selection_after_main_moved_is_unchanged() -> None:
    """CONTROL: an unrelated change cannot claim a selection gain."""
    comparison = compare_main_moved(_moved("main", 750), _moved("update-backend-common-pr217", 750))
    assert comparison.verdict == "unchanged"


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (_moved("update-backend-common-pr217", 751), "selected 751 test files against 750"),
        (_moved("update-backend-common-pr217", 7, after="failure"), "red run on the candidate"),
        (_moved("update-backend-common-pr217", 7, seconds=900), "took 900s against 300s"),
    ],
    ids=["larger", "red", "slower"],
)
def test_a_larger_red_or_slower_run_after_main_moved_is_a_regression(candidate: MainMovedCard, reason: str) -> None:
    comparison = compare_main_moved(_moved("main", 750), candidate)
    assert comparison.verdict == "regressed"
    assert any(reason in item for item in comparison.reasons), comparison.reasons


def test_a_run_whose_log_shows_no_selection_proves_nothing() -> None:
    blind = _moved("update-backend-common-pr217", 7)
    blind = blind.model_copy(update={"runs": (blind.runs[0], blind.after.model_copy(update={"selection": None}))})
    assert compare_main_moved(_moved("main", 750), blind).verdict == "regressed"


def test_improved_needs_each_consumer_to_improve_in_some_drill_and_regress_in_none() -> None:
    """A selection fix leaves re-triggers unchanged; that is still an improvement for the consumer."""
    reusing = _timed(_reused(_probe_runs(), VALIDATED_JOBS), 120)
    main = score(BACKEND, "main", HEAD, reusing)
    same = score(BACKEND, "update-backend-common-pr217", HEAD, reusing)
    retrigger = compare(main, same)
    assert retrigger.verdict == "unchanged"
    moved_main, moved_candidate = _moved("main", 750), _moved("update-backend-common-pr217", 7)
    selection = compare_main_moved(moved_main, moved_candidate)
    cards, moved = [main, same], [moved_main, moved_candidate]
    assert met("improved", cards, [retrigger], (), moved, [selection])
    unchanged = compare_main_moved(moved_main, _moved("update-backend-common-pr217", 750))
    assert not met("improved", cards, [retrigger], (), moved, [unchanged])
    red = _moved("update-backend-common-pr217", 7, after="failure")
    assert not met("pass", cards, [retrigger], (), [moved_main, red], [compare_main_moved(moved_main, red)])


def test_the_report_shows_both_drills() -> None:
    moved_main, moved_candidate = _moved("main", 750), _moved("update-backend-common-pr217", 7)
    text = report(217, [], [], (), [moved_main, moved_candidate], [compare_main_moved(moved_main, moved_candidate)])
    assert "| main moved | **improved** |" in text
    assert "| after main moved | 2 | success | 300s | ? | 7/750 (scoped) |" in text


def test_every_profile_names_a_broad_module_it_can_edit() -> None:
    for profile in PROFILES.values():
        assert profile.broad_path.endswith(".py"), profile.repository


def _with_job(card: Scorecard, name: str, seconds: float) -> Scorecard:
    """Add one successful first-time job to every re-trigger run, and its time to the run."""
    runs = [card.runs[0]] + [
        run.model_copy(
            update={
                "jobs": (*run.jobs, JobOutcome(name=name, conclusion="success", seconds=seconds)),
                "wall_seconds": (run.wall_seconds or 0.0) + seconds,
            }
        )
        for run in card.runs[1:]
    ]
    return card.model_copy(update={"runs": tuple(runs)})


def test_a_lane_only_the_candidates_diff_admits_is_not_a_slowdown() -> None:
    """
    A bump PR changes the lock, so its ready event admits the dependency scan main's drill never
    runs (gigaverse-ai, backend-common#217: 218s against 142s, all of it Trivy). That is the PR's
    content, not the CI change; wall time is only compared when both sides ran the same jobs.
    """
    reusing = _timed(_reused(_probe_runs(), VALIDATED_JOBS), 120)
    main = score(BACKEND, "main", HEAD, reusing)
    candidate = _with_job(score(BACKEND, "update-backend-common-pr217", HEAD, reusing), "Trivy inventories", 400)
    comparison = compare(main, candidate)
    assert comparison.verdict == "unchanged"
    assert any("not comparable" in reason and "Trivy inventories" in reason for reason in comparison.reasons)
    # CONTROL: the same slowdown with the same jobs on both sides is a regression.
    slow = score(BACKEND, "update-backend-common-pr217", HEAD, _timed(_reused(_probe_runs(), VALIDATED_JOBS), 400))
    assert compare(main, slow).verdict == "regressed"


def _planned(seconds: float) -> list[RunOutcome]:
    return [RunOutcome(label=f"run {index}", run_id=index, jobs=(), plan_seconds=seconds) for index in range(2)]


def test_a_faster_plan_job_is_a_gain_and_a_slower_one_a_regression() -> None:
    """The plan job gates every other job: backend's took 93s, 38s of it an evidence search."""
    assert plan_delta(_planned(93), _planned(50)) == (None, "plan job 93s \u2192 50s")
    assert plan_delta(_planned(50), _planned(93)) == ("plan job took 93s against 50s on main", None)
    # CONTROL: within noise, or unmeasured, is neither.
    assert plan_delta(_planned(60), _planned(55)) == (None, None)
    assert plan_delta(_planned(60), [RunOutcome(label="x", run_id=1, jobs=())]) == (None, None)


def test_plan_time_is_reported_but_never_decides_the_verdict() -> None:
    """The candidate's diff moves the pin, so its plan does work main's drill never can."""
    reusing = _timed(_reused(_probe_runs(), VALIDATED_JOBS), 120)
    main = score(BACKEND, "main", HEAD, [run.model_copy(update={"plan_seconds": 36}) for run in reusing])
    slower = score(BACKEND, "pr", HEAD, [run.model_copy(update={"plan_seconds": 50}) for run in reusing])
    comparison = compare(main, slower)
    assert comparison.verdict == "unchanged"
    assert "plan job took 50s against 36s on main" in comparison.reasons
    moved = compare_main_moved(_moved("main", 750), _moved("pr", 750))
    assert moved.verdict == "unchanged"


def test_the_slow_listing_lag_scenario_is_opt_in() -> None:
    assert [key for key, scenario in SCENARIOS.items() if not scenario.thorough] == ["ready-now"]
    assert SCENARIOS["ready-later"].thorough


def test_touch_files_are_leaves_not_modules_every_test_reaches() -> None:
    """A touch file every test reaches makes each first run a full suite and hides selection gains."""
    for profile in PROFILES.values():
        assert profile.touch_path != profile.broad_path
        assert "constants.py" not in profile.touch_path, "the old touch files reached 752 and 74 test files"


# The lines backend-common#217's retag rewrote in gigaverse-backend (PR217 -> v217, one tree).
PR_COMMIT = "6e48180ffd223644e678cdb88c65418570e42cc7"
TAG_COMMIT = "0d34ec37f755980e25edd3be4c993dc0e605a6d1"
LOCK = (
    '    { name = "gigaverse-backend-common", git = "https://github.com/gigaverse-app/backend-common.git?rev=PR217" },\n'
    f'source = {{ git = "https://github.com/gigaverse-app/backend-common.git?rev=PR217#{PR_COMMIT}" }}\n'
)
MANIFEST = 'gigaverse-backend-common = { git = "https://github.com/gigaverse-app/backend-common.git", rev = "PR217" }\n'
BUMP = f'{{\n  "sha": "{PR_COMMIT}",\n  "runtime_changed": true\n}}\n'


def test_the_retag_rewrites_the_pin_exactly_as_the_automation_did() -> None:
    old = pinned(LOCK)
    assert old == ("PR217", PR_COMMIT)
    new = ("v217", TAG_COMMIT)
    assert retag_pin(LOCK, old, new) == LOCK.replace("PR217", "v217").replace(PR_COMMIT, TAG_COMMIT)
    assert retag_pin(MANIFEST, old, new) == MANIFEST.replace('"PR217"', '"v217"')
    assert retag_pin(BUMP, old, new) == BUMP.replace(PR_COMMIT, TAG_COMMIT)


def test_a_lock_without_exactly_one_pin_is_refused() -> None:
    with pytest.raises(ValueError, match="one backend-common pin"):
        pinned("no pin here")
    with pytest.raises(ValueError, match="one backend-common pin"):
        pinned(LOCK + LOCK.replace(PR_COMMIT, TAG_COMMIT))


def _retag_runs(retag_jobs: dict[str, str]) -> list[RunOutcome]:
    validated = {"Build image for tests": "success", "Test unit behavior · 6 concurrent shards": "success"}
    return [
        RunOutcome(
            label=label,
            run_id=index,
            jobs=tuple(JobOutcome(name=name, conclusion=conclusion) for name, conclusion in jobs.items()),
        )
        for index, (label, jobs) in enumerate((("first run", validated), (RETAG_LABEL, retag_jobs)))
    ]


def test_after_a_retag_only_jobs_that_read_the_pin_text_may_rerun() -> None:
    """
    INVARIANT: a retag to an identical tree re-runs nothing but what reads the lock's text.

    backend-common#217's retag re-ran the image build, migrations and OpenSearch on backend.
    """
    reused = score(
        BACKEND,
        "pr",
        HEAD,
        _retag_runs({"Build image for tests": "skipped", "Test unit behavior · 6 concurrent shards": "success"}),
        family="retag",
    )
    assert reused.passed, reused.repeated
    # CONTROL: rebuilding the image after a retag is repeated work.
    rebuilt = score(BACKEND, "pr", HEAD, _retag_runs({"Build image for tests": "success"}), family="retag")
    assert [item.job for item in rebuilt.repeated] == ["Build image for tests"]


def test_every_retag_rerun_says_why() -> None:
    for profile in PROFILES.values():
        assert profile.retag_reruns, profile.repository
        assert all(rule.reason for rule in profile.retag_reruns)


def test_retag_and_retrigger_cards_are_never_compared_with_each_other() -> None:
    main = score(BACKEND, "main", HEAD, _retag_runs({"Build image for tests": "success"}), family="retag")
    text = report(217, [main], [], ())
    assert "from `main`, retag" in text


def test_selection_is_judged_by_how_much_it_grows_when_main_moves() -> None:
    """
    INVARIANT: the main-moved verdict compares growth, not the size of each PR's own diff.

    backend-common#218's drill called gigaverse-ai regressed for selecting 22 files against
    main's 4: the bump PR's own diff selects 22 before main moves and after. Neither grew.
    """
    main = _moved("main", 4, validated_selected=4)
    candidate = _moved("update-backend-common-pr218", 22, validated_selected=22)
    assert compare_main_moved(main, candidate).verdict == "unchanged"
    # CONTROL: growing where main does not is still a regression.
    grown = _moved("update-backend-common-pr218", 40, validated_selected=22)
    regressed = compare_main_moved(main, grown)
    assert regressed.verdict == "regressed"
    assert any("grew by 18" in reason for reason in regressed.reasons), regressed.reasons


def test_wall_time_after_main_moved_counts_only_when_both_sides_ran_the_same_jobs() -> None:
    """The candidate's diff can admit its own jobs (#218: the image carry job); that is not the CI change."""
    main = _moved("main", 6, seconds=182, validated_selected=6)
    candidate = _moved("update-backend-common-pr218", 6, seconds=246, validated_selected=6)
    extra = candidate.after.model_copy(
        update={"jobs": (JobOutcome(name="Carry the reused test image to this tree", conclusion="success"),)}
    )
    candidate = candidate.model_copy(update={"runs": (candidate.runs[0], extra)})
    comparison = compare_main_moved(main, candidate)
    assert comparison.verdict == "unchanged"
    assert any("not comparable" in reason for reason in comparison.reasons)


@pytest.mark.parametrize("fails", [False, True])
def test_reuse_drill_base_stays_frozen_and_is_cleaned_after_failure(
    monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    from ci_esta import drill as ci_drill

    refs = {"main": "before"}

    def branch_from(repository: str, source: str, branch: str) -> None:
        assert repository == BACKEND.repository
        refs[branch] = refs[source]

    def gh(*args: str, check: bool = True) -> str:
        assert args[:3] == ("api", "-X", "DELETE")
        assert check is False
        del refs[args[3].split("refs/heads/", 1)[1]]
        return ""

    monkeypatch.setattr(ci_drill, "_branch_from", branch_from)
    monkeypatch.setattr(ci_drill, "_gh", gh)
    try:
        with ci_drill._frozen_main(BACKEND, "ci-drill/probe") as base:
            refs["main"] = "unrelated-merge"
            assert refs[base] == "before"
            if fails:
                raise RuntimeError("consumer failed")
    except RuntimeError:
        assert fails
    assert refs == {"main": "unrelated-merge"}


def test_main_probe_starts_from_the_frozen_pr_base(monkeypatch: pytest.MonkeyPatch) -> None:
    from ci_esta import drill as ci_drill

    refs = {"main": "unrelated-merge", "ci-drill/base": "before"}

    def branch_from(repository: str, source: str, branch: str) -> None:
        refs[branch] = refs[source]

    def comment_commit(repository: str, branch: str, path: str) -> str:
        assert refs[branch] == "before", "the baseline accidentally copied live main"
        return HEAD

    def gh(*args: str) -> str:
        assert args[args.index("--base") + 1] == "ci-drill/base"
        return "https://github.com/gigaverse-app/gigaverse-backend/pull/1"

    monkeypatch.setattr(ci_drill, "_branch_from", branch_from)
    monkeypatch.setattr(ci_drill, "_probe_commit", comment_commit)
    monkeypatch.setattr(ci_drill, "_gh", gh)
    ci_drill._open_drill_pr(BACKEND, "main", "ci-drill/head", pr_base="ci-drill/base")
