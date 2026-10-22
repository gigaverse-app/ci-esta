"""
Render the test-selection section of the CI sticky.

The layout is fixed: a one-row TLDR (what ran, wall and test time, the saving against a full
suite, whether the graph changed), one sentence with the thing to know, then collapsed expanders:
why these tests (left out when that sentence already names the one route), and the startup floor
(which files, what this PR did to it, what to do). An expander whose contents are worth opening
is marked yellow, never opened: the sticky stays short on every PR, and the marker is the prompt.

Repository paths come from whoever opened the PR, so every one goes through `markdown`.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from pytest_selective.impact_models import (
    ChangedFileReach,
    FloorEntry,
    FloorEntryKind,
    PathStep,
    SelectionExplanation,
    SelectionRoute,
)

from ci_esta.ci_observability import markdown
from ci_esta.ci_observability.brand import BLUE, GREEN, SELECTIVE_URL, Badge
from ci_esta.ci_observability.enrichment.primitives import format_seconds
from ci_esta.ci_observability.models import SelectionSectionV1

WORTH_OPENING = "🟡 "
#: Gauges are plain text in the reader's text color. Block characters in a code span render as a
#: solid bright box in GitHub's dark theme.
GAUGE_CELLS = 10
FILLED, EMPTY = "▰", "▱"
#: Why-expander is worth opening when one file funnels at least this share of the selection.
FUNNEL_WORTH_SHARE = 0.5
#: Files listed by name before the rest are counted: GitHub caps a comment at 65,536 characters.
LISTED_FILES = 10
#: The floor table lists this many directories, and this many file names in each.
FLOOR_DIRECTORIES = 5
FLOOR_NAMES = 4
#: Floor entries listed, largest share of the floor first.
LISTED_ENTRIES = 5
#: A hub is named when it carries at least this share of the tests a changed file selects.
HUB_SHARE = 0.25
#: The startup floor is called out when it adds at least this share of a changed file's tests.
FLOOR_ADDS_SHARE = 0.1
#: The why expander is worth opening when a hub or the floor carries this share of the selection.
HUB_WORTH_SHARE = 0.5
#: A hub gets a fix only when it carries this many test files and this share of the suite: splitting
#: a module for a handful of tests is not worth the advice.
HUB_ADVICE_MIN_TESTS = 20
HUB_ADVICE_MIN_SHARE = 0.05


def _count(value: int) -> str:
    return f"{value:,}"


def _step(step: PathStep) -> str:
    return markdown.code(f"{step.path}:{step.line}" if step.line else step.path)


def _path(steps: list[PathStep]) -> str:
    return " → ".join(_step(step) for step in steps)


def _gauge(share: float) -> str:
    """`share` of the cells filled, at least one when anything is there."""
    filled = min(GAUGE_CELLS, max(1 if share > 0 else 0, round(share * GAUGE_CELLS)))
    return FILLED * filled + EMPTY * (GAUGE_CELLS - filled)


def _bar(value: int, total: int) -> str:
    return _gauge(value / total if total else 0)


def _files(paths: list[str]) -> str:
    listed = ", ".join(markdown.code(path) for path in paths[:LISTED_FILES])
    rest = len(paths) - LISTED_FILES
    return f"{listed} and {_count(rest)} more" if rest > 0 else listed


def _floor_table(files: list[str]) -> list[str]:
    """The floor by directory, largest first: which files, without a wall of long paths."""
    by_directory: dict[str, list[str]] = {}
    for path in files:
        directory, _, name = path.rpartition("/")
        by_directory.setdefault(f"{directory}/" if directory else "./", []).append(name)
    ranked = sorted(by_directory.items(), key=lambda item: (-len(item[1]), item[0]))
    rows = []
    for directory, names in ranked[:FLOOR_DIRECTORIES]:
        listed = ", ".join(markdown.code(name) for name in names[:FLOOR_NAMES])
        rest = len(names) - FLOOR_NAMES
        rows.append(
            f"| {markdown.cell(markdown.code(directory))} | {_count(len(names))} | "
            f"{markdown.cell(listed + (f' +{_count(rest)} more' if rest > 0 else ''))} |"
        )
    others = ranked[FLOOR_DIRECTORIES:]
    if others:
        directories = f"{_count(len(others))} other director{'y' if len(others) == 1 else 'ies'}"
        rows.append(f"| {directories} | {_count(sum(len(names) for _, names in others))} | |")
    return ["| Floor directory | Files | |", "|:--|--:|:--|", *rows]


def _expander(summary_html: str, worth_opening: bool, body: list[str]) -> list[str]:
    """A closed expander; GitHub renders no Markdown in <summary>, so the title is HTML."""
    title = (WORTH_OPENING if worth_opening else "") + summary_html
    return [f"<details><summary>{title}</summary>", "", *body, "", "</details>", ""]


def _test_share(section: SelectionSectionV1) -> float | None:
    """This run's test time as a share of the full-suite baseline; 1.0 for a full suite."""
    test_seconds = section.pytest.total_test_seconds if section.pytest else None
    baseline = section.baseline_test_seconds
    if section.explanation.full_suite:
        return 1.0
    if baseline is None or test_seconds is None:
        return None
    return test_seconds / baseline


def _saved(share: float | None) -> str | None:
    return None if share is None else f"{max(0, round((1 - share) * 100))}%"


def badges(section: SelectionSectionV1) -> list[Badge]:
    """The sticky's badges for file selection: what ran, and the saving when there is a baseline."""
    explanation = section.explanation
    items = [Badge("tests", f"{_count(explanation.selected)} of {_count(explanation.total)} files", BLUE)]
    saved = _saved(_test_share(section))
    if saved is not None and not explanation.full_suite:
        items.append(Badge("saved", saved, GREEN))
    return items


def _tldr_row(section: SelectionSectionV1) -> str:
    explanation, pytest = section.explanation, section.pytest
    wall = format_seconds(pytest.wall_seconds) if pytest and pytest.wall_seconds is not None else "—"
    test_seconds = pytest.total_test_seconds if pytest else None
    test_time = format_seconds(test_seconds) if test_seconds is not None else "—"
    share = _test_share(section)
    if explanation.full_suite:
        saved = "none"
    else:
        saved = _saved(share) or "—"
    if share is not None and test_seconds is not None:
        test_time = f"{_gauge(share)} {test_time}"
    graph = "**wider**" if explanation.graph_widened else "narrower" if explanation.graph_narrowed else "unchanged"
    ran = f"{_count(explanation.selected)} of {_count(explanation.total)} files"
    return f"| {ran} | {wall} | {test_time} | {saved} | {graph} |"


def _one_funnel(explanation: SelectionExplanation) -> bool:
    """Every selected test comes through one file, and the path from it to the change is known."""
    funnel = explanation.top_funnel
    return funnel is not None and funnel.tests == explanation.selected and bool(explanation.path)


def _floor_adds(change: ChangedFileReach) -> int:
    return change.tests - change.own if change.tests - change.own >= FLOOR_ADDS_SHARE * change.tests else 0


def _named_hub(change: ChangedFileReach) -> bool:
    return change.hub is not None and change.hub_tests >= HUB_SHARE * change.tests


def _change_story(change: ChangedFileReach) -> str:
    """What one changed file alone selects, and the biggest reason, in one sentence."""
    parts = [f"{markdown.code(change.path)} alone selects {_count(change.tests)}"]
    if added := _floor_adds(change):
        parts.append(f"the startup floor adds {_count(added)} of them")
    if _named_hub(change):
        assert change.hub is not None, "a named hub has a path"
        parts.append(f"{_count(change.hub_tests)} come through {markdown.code(change.hub)}")
    elif change.own and change.direct >= change.own / 2:
        parts.append(f"{_count(change.direct)} depend on it directly: its real users")
    return "; ".join(parts) + "."


def _takeaway(explanation: SelectionExplanation) -> str:
    sentences = []
    funnel = explanation.top_funnel
    top = explanation.changes[0] if explanation.changes else None
    if explanation.selected == 0:
        sentences.append("No test depends on your changes.")
    elif explanation.floor_seeds:
        sentences.append(
            "Every test loads some of your changes (they're in the startup floor), so this PR can't narrow."
        )
        # The floor explains why everything ran; the rest says what would still run without it.
        if top is not None and top.own < top.tests:
            sentences.append(f"Without the floor, {_count(top.own)} would still load {markdown.code(top.path)}.")
    elif _one_funnel(explanation):
        assert funnel is not None, "one funnel carries the selection"
        # One route carries everything: name the change it leads to, not just the funnel.
        who = "Full suite: every test reaches" if explanation.full_suite else f"All {_count(funnel.tests)} reach"
        sentences.append(f"{who} your change through {_path(explanation.path)}.")
    elif top is not None:
        sentences.append(_change_story(top))
    elif funnel is not None and funnel.via is not None:
        sentences.append(f"{_count(funnel.tests)} of these come through {markdown.code(funnel.via)}.")
    else:
        sentences.append("Your changes are outside the startup floor.")
    floor = explanation.floor
    if floor.after > floor.before:
        grown = floor.after - floor.before
        sentences.append(
            f"**Warning:** this PR grows the startup floor by {grown} file{'s' if grown > 1 else ''}. "
            "From now on, a change to any file in it runs almost every test file."
        )
    elif floor.after < floor.before:
        shrunk = floor.before - floor.after
        sentences.append(f"This PR shrinks the startup floor by {shrunk} file{'s' if shrunk > 1 else ''}.")
    for widened in explanation.widened[:1]:
        sentences.append(
            f"**Warning:** {markdown.code(widened.path)} now reaches {_count(widened.after)} test files, "
            f"up from {_count(widened.before)}."
        )
    return " ".join(sentences)


ROUTE_LABELS = {
    "floor": "Through the startup floor (every test loads it)",
    "changed": "Test files this PR edits, or that failed before and are retried",
    "other": "All other routes",
    "unreached": "Selected without depending on the change (always-run, full-suite requests, shard padding)",
}


def _route_label(route: SelectionRoute) -> str:
    if route.kind == "funnel" and route.via is not None:
        return ("↳ " if route.parent else "") + f"via {markdown.cell(markdown.code(route.via))}"
    return ROUTE_LABELS[route.kind]


HUB_ADVICE: dict[FloorEntryKind, str] = {
    "conftest": (
        "a directory conftest: every test under it loads what it imports. Move the fixture that needs "
        "this file into the conftest of the directory that uses it."
    ),
    "declared": (
        "a declared dependency (a `gv:test-dependency` comment, or a test-impact configuration rule or "
        "policy such as `django_urlconf.http_tests`). Narrow it to the tests that really need it."
    ),
    "import": "a module these tests import. Split it so each test imports only the part it uses.",
    "package": "a package initializer that imports it. Keep package initializers free of imports.",
    "hooks": "a conftest whose pytest hooks make every test load it. Keep its imports few.",
    "startup": "a startup module in the test-impact configuration. Keep what it imports small.",
}


def _changes_table(explanation: SelectionExplanation) -> list[str]:
    """The selection by changed file, then the fix for each hub that carries a file's tests."""
    if not explanation.changes:
        return []
    rows = []
    for change in explanation.changes:
        hub = (
            f"{markdown.cell(markdown.code(change.hub))} · {_count(change.hub_tests)}"
            if _named_hub(change) and change.hub is not None
            else "—"
        )
        rows.append(
            f"| {markdown.cell(markdown.code(change.path))} | {_count(change.tests)} | {_count(change.own)} | "
            f"{_count(change.direct)} | {hub} |"
        )
    hubs: dict[str, tuple[FloorEntryKind, bool]] = {}
    worth_fixing = max(HUB_ADVICE_MIN_TESTS, HUB_ADVICE_MIN_SHARE * explanation.total)
    for change in explanation.changes:
        if _named_hub(change) and change.hub is not None and change.hub_kind is not None:
            if change.hub_tests >= worth_fixing:
                # While the floor loads the change too, a narrower hub still leaves every test selected.
                gated = bool(explanation.floor_seeds or _floor_adds(change))
                kind, earlier = hubs.get(change.hub, (change.hub_kind, True))
                hubs[change.hub] = (kind, earlier and gated)
    advice = [
        f"- {markdown.code(hub)}: {HUB_ADVICE[kind]}"
        + (" This narrows the selection only once the startup floor no longer loads these files." if gated else "")
        for hub, (kind, gated) in hubs.items()
    ]
    return [
        "Each changed file, and what it alone selects:",
        "",
        "| Changed file | Selects | Without the startup floor | Depend on it directly | Most of the rest through |",
        "|:--|--:|--:|--:|:--|",
        *rows,
        *(["", *advice] if advice else []),
        "",
    ]


def _why(explanation: SelectionExplanation) -> list[str]:
    if not explanation.selected or (_one_funnel(explanation) and len(explanation.routes) == 1):
        # Nothing to explain, or the takeaway already names the one route and its path.
        return []
    summary = f"Why {'all' if explanation.full_suite else 'these'} {_count(explanation.selected)} tests?"
    funnel = explanation.top_funnel
    carried = max(
        (max(change.hub_tests if _named_hub(change) else 0, _floor_adds(change)) for change in explanation.changes),
        default=0,
    )
    worth_opening = (
        bool(explanation.floor_seeds)
        or (funnel is not None and funnel.tests >= FUNNEL_WORTH_SHARE * explanation.selected)
        or carried >= HUB_WORTH_SHARE * explanation.selected
    )
    body = [
        *_changes_table(explanation),
        "| How the selected tests reach your change | Test files | Share |",
        "|:--|--:|:--|",
        *(
            f"| {_route_label(route)} | {_count(route.tests)} | {_bar(route.tests, explanation.selected)} |"
            for route in explanation.routes
        ),
    ]
    if explanation.path:
        body += ["", f"Import path: {_path(explanation.path)}"]
    return _expander(summary, worth_opening, body)


ENTRY_ADVICE: dict[FloorEntryKind, str] = {
    "hooks": (
        "it defines pytest hooks, so every test loads it wherever it is. Keep its imports few, or "
        "review it into `scoped_hooks` in the test-impact configuration."
    ),
    "startup": (
        "a startup module in the test-impact configuration, so every test loads it and everything it imports "
        "or names by module path. Keep those to what every test needs."
    ),
    "package": (
        "a package initializer: every import of a module in its package runs it, so whatever it imports "
        "loads too. Keep package initializers free of imports."
    ),
    "import": (
        "most test files import it directly. If they use different parts of it, splitting it keeps each "
        "part's changes to the tests that use that part."
    ),
    "declared": (
        "a declared input (a `gv:test-dependency` comment or the test-impact configuration). Narrow the "
        "declaration if its readers don't all need all of it."
    ),
}


def _entry_line(entry: FloorEntry, floor_files: int) -> str:
    share = f"{markdown.code(entry.path)} ({_count(entry.floor_files)} of {_count(floor_files)})"
    if entry.kind != "conftest":
        return f"{share}: {ENTRY_ADVICE[entry.kind]}"
    directory = str(PurePosixPath(entry.path).parent)
    scope = "every test loads it" if directory == "." else f"every test under {markdown.code(directory + '/')} loads it"
    return (
        f"{share}: {scope}. Autouse fixtures and hooks belong there. A fixture only some tests use belongs "
        "in their directory's conftest, together with the imports it needs."
    )


def _floor_summary(explanation: SelectionExplanation) -> str:
    floor = explanation.floor
    if floor.added and floor.removed:
        return (
            f"Startup floor {_count(floor.before)} → {_count(floor.after)} files: "
            f"+{_count(len(floor.added))}, −{_count(len(floor.removed))}"
        )
    if floor.added:
        return f"Startup floor grew {_count(floor.before)} → {_count(floor.after)} files"
    if explanation.widened:
        widened = explanation.widened[0]
        return (
            f"{markdown.html_code(widened.path)} now reaches {_count(widened.after)} test files, "
            f"up from {_count(widened.before)}"
        )
    if floor.removed:
        return f"Startup floor shrank {_count(floor.before)} → {_count(floor.after)} files"
    return f"Startup floor: {_count(floor.after)} files nearly every test loads · unchanged"


def _floor_verdict(explanation: SelectionExplanation) -> list[str]:
    """What this PR did to the floor, and what to do about it."""
    floor, lines = explanation.floor, []
    if floor.added:
        # A net shrink is a split doing its job; only growth needs undoing.
        undo = (
            " To undo it, remove the import that brings it in, or move what the floor needs into a smaller "
            "module. Moving an import into a function doesn't help: the graph records it wherever it is."
            if floor.after > floor.before
            else ""
        )
        lines.append(f"**This PR adds {_count(len(floor.added))} to the floor:** {_files(floor.added)}.{undo}")
        if floor.path:
            lines += ["", f"They enter through {_path(floor.path)}."]
    if explanation.floor_seeds:
        lines += [
            *([""] if lines else []),
            f"**Your change is in the floor:** {_files(explanation.floor_seeds)}, so nearly every test "
            "ran. If these change often, taking them out of the floor narrows every PR that touches them.",
        ]
    if floor.removed:
        lines += [
            *([""] if lines else []),
            f"**This PR takes {_count(len(floor.removed))} out of the floor:** {_files(floor.removed)}. "
            "PRs that change them now run only the tests that use them.",
        ]
    for widened in explanation.widened:
        cause = f" through {_path(widened.cause)}" if widened.cause else ""
        lines += [
            *([""] if lines else []),
            f"**{markdown.code(widened.path)} now reaches {_count(widened.after)} test files**, up from "
            f"{_count(widened.before)}{cause}. A change to it will run that many.",
        ]
    return lines or ["This PR doesn't change the floor. Nothing to do here."]


def _floor_matters(explanation: SelectionExplanation) -> bool:
    """The floor expander is shown only for a PR it explains: it touches, changes or inflates it."""
    floor = explanation.floor
    return bool(
        explanation.floor_seeds
        or floor.added
        or floor.removed
        or explanation.widened
        or any(_floor_adds(change) for change in explanation.changes)
    )


def _graph(explanation: SelectionExplanation) -> list[str]:
    if not _floor_matters(explanation):
        return []
    floor = explanation.floor
    body = [
        f"The startup floor is the Python files at least {round(floor.share * 100)}% of test files load. "
        "Changing any of them runs nearly the whole suite, so the smaller it is, the more PRs run only "
        "their own tests.",
        "",
        *_floor_verdict(explanation),
    ]
    if floor.cycle is not None:
        cycle = floor.cycle
        body += [
            "",
            f"**{_count(cycle.size)} of the floor's {_count(floor.after)} files are one import cycle:** "
            f"each reaches all the others, so while the cycle holds, anything that loads one of them "
            f"loads all {_count(cycle.size)}. {_count(cycle.hub_readers)} of them depend directly on "
            f"{markdown.code(cycle.hub)}, so whatever it imports is loaded by the whole cycle.",
        ]
    if floor.entries:
        # Tests load the floor through these; each kind of entry shrinks a different way.
        body += ["", "Where it comes from, largest share first:", ""]
        body += [f"- {_entry_line(entry, floor.after)}" for entry in floor.entries[:LISTED_ENTRIES]]
        if len(floor.entries) > LISTED_ENTRIES:
            body.append(f"- and {_count(len(floor.entries) - LISTED_ENTRIES)} more")
    if floor.files:
        body += ["", *_floor_table(floor.files)]
    worth_opening = explanation.graph_widened or bool(explanation.floor_seeds)
    return _expander(_floor_summary(explanation), worth_opening, body)


def _reference_note(section: SelectionSectionV1, repository: str | None) -> list[str]:
    """What the saving is measured against, so a reader can open the run it came from."""
    references, baseline = section.references, section.baseline_test_seconds
    wall = section.baseline_wall_seconds
    if section.explanation.full_suite or section.pytest is None:
        return []
    if not references:
        return [
            "<sub>Saved needs a full-suite reference, and this repository has none yet: one is recorded from "
            "each green run whose change reaches every test.</sub>",
            "",
        ]
    assert baseline is not None and wall is not None, "a full-suite reference always carries both timings"
    newest = references[0]
    runs = "a full-suite run" if len(references) == 1 else f"the median of {len(references)} full-suite runs"
    # A branch name can be a long generated one; the run it links to says everything else.
    run = f"run {newest.run_id}"
    if repository:
        run = f"[{run}](https://github.com/{repository}/actions/runs/{newest.run_id})"
    return [
        f"<sub>Saved is against {runs} (newest: {run}, {newest.recorded_at:%Y-%m-%d}): "
        f"{format_seconds(baseline)} test time, {format_seconds(wall)} wall.</sub>",
        "",
    ]


def render_selection_section(section: SelectionSectionV1, repository: str | None = None) -> str:
    """The sticky's test-selection section, as GitHub-flavored Markdown; `repository` links runs."""
    explanation = section.explanation
    lines = [
        f"#### 🎯 Test selection · by [pytest-selective]({SELECTIVE_URL})",
        "",
        "| Ran | Wall | Test time | Saved | Graph |",
        "|:--|--:|--:|--:|:--|",
        _tldr_row(section),
        "",
        _takeaway(explanation),
        "",
        *_why(explanation),
        *_graph(explanation),
        *_reference_note(section, repository),
    ]
    return "\n".join(lines).rstrip() + "\n"
