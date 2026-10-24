"""The sticky's banner and badges."""

from __future__ import annotations

from ci_esta.ci_observability.brand import GREEN, Badge, badge, banner
from ci_esta.ci_observability.markdown import report_section
from ci_esta.ci_observability.report import render_markdown
from tests.ci_observability.efficiency_builders import report


def test_a_badge_escapes_shields_syntax_and_keeps_its_figure_in_the_alt_text() -> None:
    rendered = badge(Badge("runner-min", "≈28 runner_min $0.03", GREEN))

    assert rendered.startswith("![runner-min: ≈28 runner_min $0.03](https://img.shields.io/badge/")
    # `-` and `_` double, spaces become `_`, and the rest is URL-quoted.
    assert "/badge/runner--min-%E2%89%8828_runner__min_%240.03-2EA043?" in rendered


def test_the_banner_follows_the_readers_theme() -> None:
    html = banner()

    assert '<source media="(prefers-color-scheme: dark)" srcset="' in html
    assert html.count("sticky-banner-dark.svg") == 1 and html.count("sticky-banner-light.svg") == 1


def test_header_badges_wrap_naturally_without_forced_row_breaks() -> None:
    header = render_markdown(report()).split("\n---\n", 1)[0]
    assert "<br>" not in header
    badge_line = next(line for line in header.splitlines() if "![selected:" in line)
    assert "![runner:" in badge_line and "![est. cost:" in badge_line


def test_summary_metrics_keep_labels_on_the_value_baseline() -> None:
    summary = report_section("Selection", [], [], metrics=[Badge("selected", "2 / 998 files", GREEN)])
    assert "<strong>2 / 998 files</strong> selected" in summary
    assert "<sub>" not in summary
