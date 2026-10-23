"""Shared, passive SVG metric strips. No scripts, fonts, URLs or private data in image URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from html import escape

from ci_esta.ci_observability.brand import Badge


def _width(value: str, size: int) -> float:
    # Conservative character widths for system sans fonts; layout wraps before
    # the right edge. Labels remain separate from values at every size.
    return sum(0.36 if c in " il.,:;/|" else 0.9 if c in "MW@%" else 0.66 for c in value) * size


def render_strip(metrics: list[Badge], *, dark: bool, chips: bool = False) -> tuple[str, int]:
    width, x, y = 680, 14, 18
    fg, muted, border = ("#f0f6fc", "#9da7b3", "#3d444d") if dark else ("#1f2328", "#59636e", "#d1d9e0")
    nodes = []
    for metric in metrics:
        value_width = _width(metric.value, 12 if chips else 14)
        label_width = _width(metric.label, 11)
        cell_width = value_width + label_width + (20 if chips else 10)
        if x > 14 and x + cell_width > width - 14:
            x, y = 14, y + 26
        elif x > 14 and not chips:
            nodes.append(f'<line x1="{x - 14}" x2="{x - 14}" y1="{y - 13}" y2="{y + 3}" stroke="{border}"/>')
        if chips:
            # Palette is controlled here, not interpolated from report input.
            color = "#238636" if metric.color == "2EA043" else "#1f6feb" if metric.color == "2563EB" else "#484f58"
            nodes += [f'<rect x="{x}" y="{y - 15}" width="{cell_width:.1f}" height="21" rx="3" fill="{color}"/>',
                      f'<text x="{x + 6}" y="{y}" font-size="11" fill="#ffffff">{escape(metric.label)}'
                      f'<tspan dx="5" font-size="12" font-weight="700">{escape(metric.value)}</tspan></text>']
        else:
            nodes.append(f'<text x="{x}" y="{y}" font-size="14" font-weight="700" fill="{fg}">'
                         f'{escape(metric.value)}<tspan dx="7" font-size="11" font-weight="400" '
                         f'fill="{muted}">{escape(metric.label)}</tspan></text>')
        x += cell_width + (6 if chips else 30)
    height = y + 9
    title = escape("; ".join(f"{m.value} {m.label}" for m in metrics))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" role="img" font-family="Arial, Helvetica, sans-serif">'
           f'<title>{title}</title>' + "".join(nodes) + '</svg>')
    return svg, height


@dataclass
class SvgHeadlines:
    """Collect exact image bytes first; bind only repository-scoped attachment URLs later."""

    urls: dict[str, str] = field(default_factory=dict)
    assets: dict[str, str] = field(default_factory=dict)

    def row(self, metrics: list[Badge], key: str) -> str:
        sources = []
        for dark in (True, False):
            svg, height = render_strip(metrics, dark=dark, chips=key == "headline")
            name = f"ci-esta-{sha256(svg.encode()).hexdigest()[:24]}.svg"
            self.assets[name] = svg
            sources.append(self.urls.get(name, name))
        alt = escape("; ".join(f"{m.value} {m.label}" for m in metrics), quote=True)
        return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{escape(sources[0], quote=True)}">'
                f'<img src="{escape(sources[1], quote=True)}" alt="{alt}" width="680" height="{height}"></picture>')
