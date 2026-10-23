"""
The names, links, marks and colors the sticky signs itself with.

The banner and mark are SVGs in this repository's `docs/assets`: GitHub serves them as
`image/svg+xml` and proxies them into comments, and a `<picture>` picks the dark or light banner
by the reader's theme. Run figures go in shields.io badges, whose alt text keeps each figure
readable if the badge service is down. Colors are GitHub's own status palette, so the badges
look native in both themes.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

CI_ESTA = "CI-esta"
CI_ESTA_URL = "https://github.com/gigaverse-app/ci-esta"
CI_ESTA_DOCS_URL = f"{CI_ESTA_URL}/blob/main/docs/github-actions-observability.md"
ASSETS_URL = "https://raw.githubusercontent.com/gigaverse-app/ci-esta/main/docs/assets"
BANNER_WIDTH = 640
MARK_URL = f"{ASSETS_URL}/ci-esta-mark.svg"
TAGLINE = "Let proven work rest. Measure the rest."
SELECTIVE_URL = "https://github.com/gigaverse-app/pytest-selective"

GREEN = "2EA043"
RED = "CF222E"
AMBER = "D29922"
BLUE = "2563EB"
GREY = "6E7781"
#: The badges' label half: dark enough to read white text on, on either theme.
BADGE_LABEL_COLOR = "24292F"


@dataclass(frozen=True)
class Badge:
    """One figure on the sticky's badge line; every value is a number the reporter computed."""

    label: str
    value: str
    color: str

    @property
    def summary(self) -> str:
        """The same figure in an expander headline, without presentation markup."""
        return f"{self.value} {self.label}"


def quantity(label: str, count: int, total: int, unit: str) -> Badge:
    return Badge(label, f"{count:,} / {total:,} {unit}", BLUE)


def _shields(text: str) -> str:
    """shields.io path escaping: `-` and `_` double, a space becomes `_`, the rest is URL-quoted."""
    return quote(text.replace("-", "--").replace("_", "__").replace(" ", "_"), safe="_")


def badge(item: Badge) -> str:
    alt = f"{item.label}: {item.value}".replace("[", "(").replace("]", ")")
    return (
        f"![{alt}](https://img.shields.io/badge/{_shields(item.label)}-{_shields(item.value)}-{item.color}"
        f"?style=flat-square&labelColor={BADGE_LABEL_COLOR})"
    )


def status_badge(label: str, color: str) -> str:
    """A rounded status pill with readable alt text when images are unavailable."""
    return f"![{label}](https://img.shields.io/badge/{_shields(label)}-{color}?style=flat)"


def mark(size: int = 14) -> str:
    """The CI-esta mark, sized to sit in a line of text."""
    return f'<img src="{MARK_URL}" alt="" width="{size}" height="{size}">'


def banner() -> str:
    """The sticky's banner, linked to CI-esta, in the reader's theme."""
    return (
        f'<a href="{CI_ESTA_URL}"><picture>'
        f'<source media="(prefers-color-scheme: dark)" srcset="{ASSETS_URL}/sticky-banner-dark.svg">'
        f'<img alt="{CI_ESTA} pull request report" src="{ASSETS_URL}/sticky-banner-light.svg" width="{BANNER_WIDTH}">'
        "</picture></a>"
    )
