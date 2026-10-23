"""
Escaping for text the sticky did not write: job names, gate names, repository paths.

Everything here targets GitHub-flavored Markdown as GitHub renders PR comments. Repository paths
are chosen by whoever opens the PR, so none of them may end a code span, split a table cell,
or add markup.
"""

from __future__ import annotations

import re
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci_esta.ci_observability.brand import Badge
    from ci_esta.ci_observability.svg_headlines import SvgHeadlines

LONGEST_BACKTICK_RUN = re.compile(r"`+")


def cell(value: str) -> str:
    """Text inside a table cell: a pipe or a line break would start a new cell or row."""
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def inline(value: str) -> str:
    """Plain text with every Markdown and HTML metacharacter taken literally."""
    escaped = value.replace("\\", "\\\\").replace("\n", " ").replace("\r", " ")
    for character in ("`", "*", "_", "[", "]", "<", ">"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def code(value: str) -> str:
    """
    A code span that shows `value` verbatim, whatever backticks it contains.

    The fence is one backtick longer than the longest run inside, padded with spaces so a leading
    or trailing backtick cannot merge into it. Code spans take no other escaping; a table cell
    still needs `cell` around the result, because GFM splits cells before it parses code.
    """
    value = value.replace("\n", " ").replace("\r", " ")
    fence = "`" * (max((len(run) for run in LONGEST_BACKTICK_RUN.findall(value)), default=0) + 1)
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{padding}{value}{padding}{fence}"


def html_code(value: str) -> str:
    """Inline code inside an HTML block such as <summary>, where GitHub renders no Markdown."""
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<code>{escaped}</code>"


def report_section(title: str, facts: list[str], body: list[str], *, note: str = "",
                   metrics: list[Badge] | None = None, headlines: SvgHeadlines | None = None) -> str:
    """Keep titles and key figures visible while diagnostics stay closed.

    GitHub strips custom CSS and does not parse Markdown inside summary. Explicit
    HTML line breaks and emphasis preserve the approved hierarchy in real comments.
    Facts are escaped plain text; only the diagnostic body accepts Markdown.
    """
    summary = [f"<summary><strong>{escape(title)}</strong><br>"]
    if metrics is not None and headlines is not None:
        summary.append(headlines.row(metrics, title))
        # Copyable and accessible values also survive failed image loads.
        body = [" · ".join(f"**{inline(m.value)}** {inline(m.label)}" for m in metrics), "", *body]
    elif metrics is not None:
        # Inline HTML survives GitHub's sanitizer and wraps naturally on narrow
        # screens. Emphasize values, keep labels quiet, and avoid custom CSS.
        summary.append("&emsp;" + " &ensp;│&ensp; ".join(
            f"<strong>{escape(item.value)}</strong> <sub>{escape(item.label)}</sub>" for item in metrics))
    else:
        summary += ["<br>\n".join(f"&emsp;<strong>{escape(fact)}</strong>" for fact in facts)]
    if note:
        summary.append(f"<br>\n&emsp;<sub>{escape(note)}</sub>")
    return "\n".join(["<details>", *summary, "</summary>", "", *body, "", "</details>", ""])
