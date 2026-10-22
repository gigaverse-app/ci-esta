import re
from pathlib import Path

import pytest
from pytest_selective.impact_models import (
    BlastRadiusChange,
    ChangedFileReach,
    FloorCycle,
    FloorEntry,
    PathStep,
    SelectionExplanation,
    SelectionRoute,
)

from ci_esta.ci_observability.enrichment.cli import main
from ci_esta.ci_observability.models import FullSuiteReferenceV1, PytestTimingMetadata, SelectionSectionV1
from ci_esta.ci_observability.selection import (
    FLOOR_DIRECTORIES,
    FLOOR_NAMES,
    HUB_ADVICE_MIN_TESTS,
    HUB_SHARE,
    LISTED_ENTRIES,
    LISTED_FILES,
    WORTH_OPENING,
    render_selection_section,
)
from tests.ci_observability.builders import (
    AI_TIMINGS,
    FLOOR_FILES,
    FULL_SUITE_TIMINGS,
    TOTAL_FILES,
    floor,
    full_suite_reference,
)

APP_FACTORY = "src/persistence/application.py"
FIXTURES = "tests/helpers/fixtures.py"
BILLING = "src/models/billing.py"
SLACK = "src/integrations/slack.py"
#: AI #2814: 104 selected; 68 through the app factory, 41 of them through one fixture.
SELECTED, APP_FACTORY_TESTS, FIXTURE_TESTS = 104, 68, 41
OTHER_TESTS = SELECTED - APP_FACTORY_TESTS
#: AI #2817 widened the billing models from 104 to 348 dependent test files.
WIDENED_BEFORE, WIDENED_AFTER = 104, 348
REFERENCE_RUN = 36683460891
REFERENCES = [full_suite_reference(REFERENCE_RUN)]
#: A floor entry's share, and a cycle holding most of the floor.
ENTRY_FLOOR_FILES = 7
CYCLE_FILES, CYCLE_HUB_READERS = 27, 25
#: 4m 53s against 25m 44s.
SAVED_PERCENT = "81%"
APP_FACTORY_LINE = 64
SLACK_LINE = 17


def explanation(**changes: object) -> SelectionExplanation:
    """A narrowed selection with one funnel, overridden per test."""
    fields: dict[str, object] = {
        "base": "base-tree",
        "head": "head-tree",
        "graph_base": "base-tree",
        "selected": SELECTED,
        "total": TOTAL_FILES,
        "routes": [
            SelectionRoute(kind="funnel", tests=APP_FACTORY_TESTS, via=APP_FACTORY),
            SelectionRoute(kind="funnel", tests=FIXTURE_TESTS, via=FIXTURES, parent=APP_FACTORY),
            SelectionRoute(kind="other", tests=OTHER_TESTS),
        ],
        "path": [PathStep(path=APP_FACTORY, kind="import", line=APP_FACTORY_LINE), PathStep(path=BILLING)],
        "floor": floor(),
    }
    fields.update(changes)
    return SelectionExplanation.model_validate(fields)


def render(
    selection: SelectionExplanation,
    pytest_timing: PytestTimingMetadata | None = None,
    references: list[FullSuiteReferenceV1] | None = None,
) -> str:
    return render_selection_section(
        SelectionSectionV1(explanation=selection, pytest=pytest_timing, references=references or [])
    )


def summaries(markdown: str) -> list[str]:
    return re.findall(r"<summary>(.*?)</summary>", markdown)


def tldr_row(markdown: str) -> str:
    return markdown.splitlines()[4]


def test_a_narrowed_selection_leads_with_time_saved_and_its_funnel() -> None:
    markdown = render(explanation(), AI_TIMINGS, REFERENCES)

    assert tldr_row(markdown) == (
        f"| {SELECTED} of 1,087 files | 1m 18s | ▰▰▱▱▱▱▱▱▱▱ 4m 53s | {SAVED_PERCENT} | unchanged |"
    )
    assert f"{APP_FACTORY_TESTS} of these come through `{APP_FACTORY}`." in markdown
    # The floor doesn't touch, change or inflate this PR's selection, so it isn't shown.
    assert summaries(markdown) == [f"{WORTH_OPENING}Why these {SELECTED} tests?"]
    assert "Startup floor" not in markdown
    assert f"| ↳ via `{FIXTURES}` | {FIXTURE_TESTS} |" in markdown
    assert f"Import path: `{APP_FACTORY}:{APP_FACTORY_LINE}` → `{BILLING}`" in markdown


def test_expanders_stay_closed_even_when_worth_opening() -> None:
    markdown = render(explanation(floor=floor(after=FLOOR_FILES + 1, added=[BILLING])), AI_TIMINGS, REFERENCES)

    assert "<details open" not in markdown
    assert markdown.count("<details>") == len(summaries(markdown))


def test_a_full_suite_saves_nothing_and_blames_the_startup_floor() -> None:
    markdown = render(
        explanation(
            selected=TOTAL_FILES, floor_seeds=[BILLING], routes=[SelectionRoute(kind="floor", tests=TOTAL_FILES)]
        ),
        AI_TIMINGS,
        REFERENCES,
    )

    assert "| none | unchanged |" in tldr_row(markdown)
    assert "▰▰▰▰▰▰▰▰▰▰ " in tldr_row(markdown)
    assert "they're in the startup floor" in markdown
    assert summaries(markdown) == [
        f"{WORTH_OPENING}Why all 1,087 tests?",
        f"{WORTH_OPENING}Startup floor: {FLOOR_FILES} files nearly every test loads · unchanged",
    ]
    assert f"**Your change is in the floor:** `{BILLING}`, so nearly every test ran." in markdown


def test_floor_growth_is_a_warning_and_marks_the_graph_worth_opening() -> None:
    path = [PathStep(path=SLACK, kind="import", line=SLACK_LINE), PathStep(path=BILLING)]
    markdown = render(
        explanation(floor=floor(after=FLOOR_FILES + 1, added=[BILLING], path=path)), AI_TIMINGS, REFERENCES
    )

    assert tldr_row(markdown).endswith("| **wider** |")
    assert "**Warning:** this PR grows the startup floor by 1 file." in markdown
    assert summaries(markdown)[1] == f"{WORTH_OPENING}Startup floor grew {FLOOR_FILES} → {FLOOR_FILES + 1} files"
    assert f"**This PR adds 1 to the floor:** `{BILLING}`. To undo it, remove the import" in markdown
    # The graph records imports anywhere in a file, so the advice can't be to move one.
    assert "inside the function or fixture" not in markdown
    assert f"They enter through `{SLACK}:{SLACK_LINE}` → `{BILLING}`." in markdown


def test_a_split_that_swaps_a_small_file_in_for_larger_ones_reads_as_a_shrink() -> None:
    """gigaverse-ai#2833: a dependency-free module joined the floor and the two it was split from left."""
    leaf, left = "src/app/formats.py", ["src/app/integration.py", "src/app/sinks.py"]
    swap = floor(after=FLOOR_FILES - 1, added=[leaf], removed=left)
    markdown = render(explanation(floor=swap, floor_seeds=[leaf]), AI_TIMINGS, REFERENCES)

    assert tldr_row(markdown).endswith("| narrower |")
    assert "This PR shrinks the startup floor by 1 file." in markdown
    assert "Warning" not in markdown
    assert summaries(markdown)[1] == (f"{WORTH_OPENING}Startup floor {FLOOR_FILES} → {FLOOR_FILES - 1} files: +1, −2")
    assert f"**This PR adds 1 to the floor:** `{leaf}`.\n" in markdown
    assert "To undo it" not in markdown


def test_a_widened_file_is_named_as_html_code_in_its_summary() -> None:
    cause = [PathStep(path=SLACK, kind="import", line=SLACK_LINE), PathStep(path=BILLING)]
    widened = BlastRadiusChange(path=BILLING, before=WIDENED_BEFORE, after=WIDENED_AFTER, cause=cause)
    markdown = render(explanation(widened=[widened]), AI_TIMINGS, REFERENCES)

    graph = summaries(markdown)[1]
    # GitHub renders no Markdown inside <summary>: backticks there would show literally.
    assert graph == (
        f"{WORTH_OPENING}<code>{BILLING}</code> now reaches {WIDENED_AFTER} test files, up from {WIDENED_BEFORE}"
    )
    assert f"**Warning:** `{BILLING}` now reaches {WIDENED_AFTER} test files, up from {WIDENED_BEFORE}." in markdown
    assert (
        f"**`{BILLING}` now reaches {WIDENED_AFTER} test files**, up from {WIDENED_BEFORE} "
        f"through `{SLACK}:{SLACK_LINE}` → `{BILLING}`."
    ) in markdown


def test_a_shrinking_floor_is_good_news_not_a_warning() -> None:
    markdown = render(explanation(floor=floor(after=FLOOR_FILES - 1, removed=[BILLING])), AI_TIMINGS, REFERENCES)

    assert summaries(markdown)[1] == f"Startup floor shrank {FLOOR_FILES} → {FLOOR_FILES - 1} files"
    assert "Warning" not in markdown
    assert f"**This PR takes 1 out of the floor:** `{BILLING}`." in markdown


def test_the_floor_label_states_the_threshold_the_explanation_applied() -> None:
    assert "the Python files at least 80% of test files load" in render(
        explanation(floor=floor(share=0.8), floor_seeds=[BILLING])
    )


def test_long_floor_changes_name_the_first_files_and_count_the_rest() -> None:
    extra = 2
    added = [f"src/app/module_{number}.py" for number in range(LISTED_FILES + extra)]
    markdown = render(explanation(floor=floor(after=FLOOR_FILES + len(added), added=added)))

    assert f"`{added[LISTED_FILES - 1]}` and {extra} more" in markdown
    assert added[LISTED_FILES] not in markdown


def test_repository_paths_cannot_break_out_of_code_cells_or_the_summary() -> None:
    hostile = "src/a|b`c</summary><img src=x>.py"
    widened = BlastRadiusChange(path=hostile, before=WIDENED_BEFORE, after=WIDENED_AFTER)
    funnel = SelectionRoute(kind="funnel", tests=SELECTED, via=hostile)
    markdown = render(explanation(widened=[widened], routes=[funnel], path=[]))

    # The summary stays one element, with the markup shown as text.
    assert summaries(markdown)[1].startswith(f"{WORTH_OPENING}<code>src/a|b`c&lt;/summary&gt;&lt;img")
    assert not any("<img" in summary for summary in summaries(markdown))
    # In table cells the pipe is escaped and the code span outlasts the backtick inside it.
    assert "| via ``src/a\\|b`c</summary><img src=x>.py`` |" in markdown
    assert "**``src/a|b`c</summary><img src=x>.py`` now reaches" in markdown
    floor_table = render(explanation(floor=floor(files=[hostile]), floor_seeds=[BILLING]))
    assert "| ``src/a\\|b`c</`` | 1 | `summary><img src=x>.py` |" in floor_table


@pytest.mark.parametrize(
    ("pytest_timing", "references", "expected"),
    [
        (None, REFERENCES, f"| {SELECTED} of 1,087 files | — | — | — | unchanged |"),
        (AI_TIMINGS, [], f"| {SELECTED} of 1,087 files | 1m 18s | 4m 53s | — | unchanged |"),
    ],
    ids=["no-timing", "no-reference"],
)
def test_missing_measurements_show_as_unknown_not_as_zero(
    pytest_timing: PytestTimingMetadata | None, references: list[FullSuiteReferenceV1], expected: str
) -> None:
    assert tldr_row(render(explanation(), pytest_timing, references)) == expected


def test_a_run_slower_than_the_full_suite_saved_nothing() -> None:
    full_suite_seconds = FULL_SUITE_TIMINGS.total_test_seconds
    assert full_suite_seconds is not None
    slower = FULL_SUITE_TIMINGS.model_copy(update={"total_test_seconds": full_suite_seconds * 2})

    assert "| 0% |" in tldr_row(render(explanation(), slower, REFERENCES))


def test_the_saving_is_against_the_median_of_recent_full_suite_runs() -> None:
    newest, *older = [
        full_suite_reference(REFERENCE_RUN + offset, timings=FULL_SUITE_TIMINGS.model_copy(update=timings))
        for offset, timings in [
            (2, {"total_test_seconds": 1600, "wall_seconds": 220}),
            (1, {"total_test_seconds": 1544, "wall_seconds": 213}),
            (0, {"total_test_seconds": 1000, "wall_seconds": 150}),
        ]
    ]
    markdown = render(explanation(), AI_TIMINGS, [newest, *older])

    assert (
        f"<sub>Saved is against the median of 3 full-suite runs (newest: run {newest.run_id}, "
        "2026-09-30): 25m 44s test time, 3m 33s wall.</sub>"
    ) in markdown
    linked = render_selection_section(
        SelectionSectionV1(explanation=explanation(), pytest=AI_TIMINGS, references=[newest]),
        "gigaverse-app/gigaverse-ai",
    )
    assert (
        f"(newest: [run {newest.run_id}](https://github.com/gigaverse-app/gigaverse-ai/actions/runs/{newest.run_id}),"
        in linked
    )
    assert f"| {SAVED_PERCENT} |" in tldr_row(markdown)


@pytest.mark.parametrize(
    ("pytest_timing", "selection"),
    [(AI_TIMINGS, explanation(selected=TOTAL_FILES)), (None, explanation())],
    ids=["full-suite", "no-timing"],
)
def test_no_reference_note_when_nothing_is_compared_against_it(
    pytest_timing: PytestTimingMetadata | None, selection: SelectionExplanation
) -> None:
    assert "Saved is against" not in render(selection, pytest_timing, REFERENCES)


def test_an_empty_selection_says_nothing_depends_on_the_change() -> None:
    markdown = render(explanation(selected=0, routes=[], path=[]))

    assert "No test depends on your changes." in markdown
    assert summaries(markdown) == []


@pytest.mark.parametrize(
    ("funnel_tests", "worth_opening"),
    [(SELECTED // 2, True), (SELECTED // 2 - 1, False)],
    ids=["half-the-selection", "just-under-half"],
)
def test_a_funnel_is_worth_opening_from_half_the_selection(funnel_tests: int, worth_opening: bool) -> None:
    routes = [
        SelectionRoute(kind="funnel", tests=funnel_tests, via=APP_FACTORY),
        SelectionRoute(kind="other", tests=SELECTED - funnel_tests),
    ]

    assert summaries(render(explanation(routes=routes)))[0].startswith(WORTH_OPENING) is worth_opening


def test_a_selection_outside_the_floor_without_a_funnel_is_not_worth_opening() -> None:
    edited, other = 2, 10
    routes = [SelectionRoute(kind="changed", tests=edited), SelectionRoute(kind="other", tests=other)]
    markdown = render(explanation(selected=edited + other, routes=routes, path=[]))

    assert "Your changes are outside the startup floor." in markdown
    assert not any(summary.startswith(WORTH_OPENING) for summary in summaries(markdown))


def test_cli_renders_the_section_from_saved_artifacts(tmp_path: Path) -> None:
    explanation_path, pytest_path, out = (
        tmp_path / "explanation.json",
        tmp_path / "pytest.json",
        tmp_path / "section.md",
    )
    explanation_path.write_text(explanation().model_dump_json())
    pytest_path.write_text(AI_TIMINGS.model_dump_json())
    reference_args: list[str] = []
    for index, reference in enumerate(REFERENCES):
        reference_path = tmp_path / f"reference-{index}.json"
        reference_path.write_text(reference.model_dump_json())
        reference_args += ["--reference", str(reference_path)]

    status = main(
        [
            "render-selection",
            "--explanation",
            str(explanation_path),
            "--pytest",
            str(pytest_path),
            *reference_args,
            "--out",
            str(out),
        ]
    )

    assert status == 0
    assert out.read_text(encoding="utf-8") == render(explanation(), AI_TIMINGS, REFERENCES)


@pytest.mark.parametrize(
    ("selected", "sentence"),
    [
        (TOTAL_FILES, "Full suite: every test reaches your change through `tests/conftest.py` → `uv.lock`."),
        (SELECTED, f"All {SELECTED} reach your change through `tests/conftest.py` → `uv.lock`."),
    ],
    ids=["full-suite", "narrowed"],
)
def test_one_route_carrying_every_test_names_the_change_it_leads_to(selected: int, sentence: str) -> None:
    routes = [SelectionRoute(kind="funnel", tests=selected, via="tests/conftest.py")]
    path = [PathStep(path="tests/conftest.py", kind="declared"), PathStep(path="uv.lock")]

    assert sentence in render(explanation(selected=selected, routes=routes, path=path))


def test_one_route_to_the_whole_selection_needs_no_why_expander() -> None:
    routes = [SelectionRoute(kind="funnel", tests=TOTAL_FILES, via="tests/conftest.py")]
    path = [PathStep(path="tests/conftest.py", kind="declared"), PathStep(path="uv.lock")]
    markdown = render(explanation(selected=TOTAL_FILES, routes=routes, path=path))

    assert summaries(markdown) == []


def test_the_floor_expander_names_its_files_by_directory() -> None:
    core = [f"src/app/core/module_{number}.py" for number in range(FLOOR_NAMES + 1)]
    others = [f"src/app/area_{number}/module.py" for number in range(FLOOR_DIRECTORIES)]
    markdown = render(explanation(floor=floor(files=sorted([*core, *others])), floor_seeds=[BILLING]))

    names = ", ".join(f"`module_{number}.py`" for number in range(FLOOR_NAMES))
    assert f"| `src/app/core/` | {len(core)} | {names} +1 more |" in markdown
    listed_areas = FLOOR_DIRECTORIES - 1
    assert "| 1 other directory | 1 | |" in markdown
    assert markdown.count("| `src/app/area_") == listed_areas


@pytest.mark.parametrize(
    ("entry", "advice"),
    [
        (
            FloorEntry(path="tests/conftest.py", kind="conftest", floor_files=ENTRY_FLOOR_FILES),
            "every test under `tests/` loads it. Autouse fixtures and hooks belong there. A fixture only "
            "some tests use belongs in their directory's conftest, together with the imports it needs.",
        ),
        (
            FloorEntry(path="conftest.py", kind="conftest", floor_files=ENTRY_FLOOR_FILES),
            "every test loads it. Autouse fixtures",
        ),
        (
            FloorEntry(path="tests/hub/conftest.py", kind="hooks", floor_files=ENTRY_FLOOR_FILES),
            "it defines pytest hooks, so every test loads it wherever it is.",
        ),
        (
            FloorEntry(path="src/app/settings.py", kind="startup", floor_files=ENTRY_FLOOR_FILES),
            "a startup module in the test-impact configuration, so every test loads it and everything it "
            "imports or names by module path.",
        ),
        (
            FloorEntry(path="src/app/__init__.py", kind="package", floor_files=ENTRY_FLOOR_FILES),
            "a package initializer: every import of a module in its package runs it",
        ),
        (
            FloorEntry(path="src/app/shared.py", kind="import", floor_files=ENTRY_FLOOR_FILES),
            "most test files import it directly.",
        ),
        (
            FloorEntry(path="uv.lock", kind="declared", floor_files=ENTRY_FLOOR_FILES),
            "a declared input (a `gv:test-dependency` comment",
        ),
    ],
    ids=["conftest", "root-conftest", "hooks", "startup", "package", "import", "declared"],
)
def test_each_floor_entry_gets_the_fix_its_kind_of_edge_rewards(entry: FloorEntry, advice: str) -> None:
    markdown = render(explanation(floor=floor(entries=[entry]), floor_seeds=[BILLING]))

    assert f"- `{entry.path}` ({ENTRY_FLOOR_FILES} of {FLOOR_FILES}): {advice}" in markdown
    # The graph records imports anywhere in a file, so moving one never shrinks the floor.
    assert "into the fixtures and functions" not in markdown


def test_floor_entries_are_listed_up_to_a_limit_and_the_rest_counted() -> None:
    entries = [
        FloorEntry(path=f"src/app/pkg_{number}/__init__.py", kind="package", floor_files=1)
        for number in range(LISTED_ENTRIES + 1)
    ]
    markdown = render(explanation(floor=floor(entries=entries), floor_seeds=[BILLING]))

    assert markdown.count("- `src/app/pkg_") == LISTED_ENTRIES
    assert "- and 1 more" in markdown


def test_an_import_cycle_holding_the_floor_is_named_before_its_entries() -> None:
    cycle = FloorCycle(size=CYCLE_FILES, hub="gigaverse/__init__.py", hub_readers=CYCLE_HUB_READERS)
    entry = FloorEntry(path="conftest.py", kind="conftest", floor_files=FLOOR_FILES)
    markdown = render(explanation(floor=floor(cycle=cycle, entries=[entry]), floor_seeds=[BILLING]))

    sentence = (
        f"**{CYCLE_FILES} of the floor's {FLOOR_FILES} files are one import cycle:** each reaches all the others, "
        f"so while the cycle holds, anything that loads one of them loads all {CYCLE_FILES}. "
        f"{CYCLE_HUB_READERS} of them depend directly on `gigaverse/__init__.py`, so whatever it imports is "
        "loaded by the whole cycle."
    )
    assert sentence in markdown
    assert markdown.index(sentence) < markdown.index("Where it comes from")


#: AI #2819-like: a change most selected tests load through a hub, some only through the floor.
CHANGE = "src/app/rooms.py"
HUB = "src/app/urls.py"
CHANGE_TESTS, CHANGE_OWN, CHANGE_DIRECT, HUB_TESTS = 100, 80, 6, 70


def change(**changes: object) -> ChangedFileReach:
    fields: dict[str, object] = {
        "path": CHANGE,
        "tests": CHANGE_TESTS,
        "direct": CHANGE_DIRECT,
        "own": CHANGE_OWN,
        "hub": HUB,
        "hub_tests": HUB_TESTS,
        "hub_kind": "declared",
    }
    fields.update(changes)
    return ChangedFileReach.model_validate(fields)


def test_the_takeaway_names_the_changed_file_its_floor_share_and_its_hub() -> None:
    markdown = render(explanation(selected=CHANGE_TESTS, routes=[], path=[], changes=[change()]))

    assert (
        f"`{CHANGE}` alone selects {CHANGE_TESTS}; the startup floor adds {CHANGE_TESTS - CHANGE_OWN} of them; "
        f"{HUB_TESTS} come through `{HUB}`."
    ) in markdown
    assert "Your changes are outside the startup floor." not in markdown


def test_the_why_expander_tabulates_each_changed_file_and_gives_its_hub_the_fix() -> None:
    markdown = render(explanation(selected=CHANGE_TESTS, routes=[], path=[], changes=[change()]))

    assert (f"| `{CHANGE}` | {CHANGE_TESTS} | {CHANGE_OWN} | {CHANGE_DIRECT} | `{HUB}` · {HUB_TESTS} |") in markdown
    assert f"- `{HUB}`: a declared dependency" in markdown
    # A hub carrying most of the selection makes the expander worth opening.
    assert summaries(markdown)[0] == f"{WORTH_OPENING}Why these {CHANGE_TESTS} tests?"


def test_a_change_its_tests_import_directly_is_called_its_real_users() -> None:
    direct = change(own=CHANGE_TESTS, direct=CHANGE_TESTS - 1, hub=None, hub_tests=0, hub_kind=None)
    markdown = render(explanation(selected=CHANGE_TESTS, routes=[], path=[], changes=[direct]))

    assert (
        f"`{CHANGE}` alone selects {CHANGE_TESTS}; {CHANGE_TESTS - 1} depend on it directly: its real users."
        in markdown
    )
    assert "| — |" in markdown


def test_a_small_hub_is_not_named() -> None:
    small = change(own=CHANGE_TESTS, hub_tests=int(CHANGE_TESTS * HUB_SHARE) - 1)
    markdown = render(explanation(selected=CHANGE_TESTS, routes=[], path=[], changes=[small]))

    assert "come through" not in markdown
    assert f"- `{HUB}`" not in markdown


def test_the_floor_is_shown_when_it_inflates_a_changed_files_selection() -> None:
    markdown = render(explanation(selected=CHANGE_TESTS, routes=[], path=[], changes=[change()]))

    assert f"Startup floor: {FLOOR_FILES} files nearly every test loads · unchanged" in summaries(markdown)


def test_a_change_in_the_floor_still_says_what_would_run_without_it() -> None:
    markdown = render(explanation(selected=CHANGE_TESTS, routes=[], path=[], floor_seeds=[CHANGE], changes=[change()]))

    assert f"Without the floor, {CHANGE_OWN} would still load `{CHANGE}`." in markdown


def test_an_empty_saving_explains_that_no_full_suite_reference_exists_yet() -> None:
    markdown = render(explanation(), AI_TIMINGS, [])

    assert "Saved needs a full-suite reference, and this repository has none yet" in markdown


def test_a_hub_carrying_a_handful_of_tests_gets_no_fix() -> None:
    few = HUB_ADVICE_MIN_TESTS - 1
    handful = change(tests=few + 1, own=few + 1, direct=1, hub_tests=few)
    markdown = render(explanation(selected=few + 1, routes=[], path=[], changes=[handful]))

    assert f"`{HUB}` · {few}" in markdown
    assert f"- `{HUB}`:" not in markdown


def test_a_hub_fix_says_it_waits_on_the_floor_while_the_floor_loads_the_change() -> None:
    markdown = render(explanation(selected=CHANGE_TESTS, routes=[], path=[], changes=[change()]))

    assert (
        f"- `{HUB}`: a declared dependency" in markdown
        and "This narrows the selection only once the startup floor no longer loads these files." in markdown
    )


def test_a_hub_fix_outside_the_floor_is_unconditional() -> None:
    clear = change(own=CHANGE_TESTS)
    markdown = render(explanation(selected=CHANGE_TESTS, routes=[], path=[], changes=[clear]))

    assert f"- `{HUB}`: a declared dependency" in markdown
    assert "only once the startup floor" not in markdown
