"""The sticky's banner and badges."""

from __future__ import annotations

from ci_esta.ci_observability.brand import GREEN, Badge, badge, banner


def test_a_badge_escapes_shields_syntax_and_keeps_its_figure_in_the_alt_text() -> None:
    rendered = badge(Badge("runner-min", "≈28 runner_min $0.03", GREEN))

    assert rendered.startswith("![runner-min: ≈28 runner_min $0.03](https://img.shields.io/badge/")
    # `-` and `_` double, spaces become `_`, and the rest is URL-quoted.
    assert "/badge/runner--min-%E2%89%8828_runner__min_%240.03-2EA043?" in rendered


def test_the_banner_follows_the_readers_theme() -> None:
    html = banner()

    assert '<source media="(prefers-color-scheme: dark)" srcset="' in html
    assert html.count("sticky-banner-dark.svg") == 1 and html.count("sticky-banner-light.svg") == 1
