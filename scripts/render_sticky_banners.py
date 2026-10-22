"""Write the sticky's dark and light banners into docs/assets; run from the repository root."""

import pathlib

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
THEMES = {
    "dark": {"bg": "#0D1117", "edge": "#30363D", "ink": "#F0F6FC", "muted": "#8B949E", "track": "#21262D"},
    "light": {"bg": "#FFFFFF", "edge": "#D1D9E0", "ink": "#1F2328", "muted": "#59636E", "track": "#EFF2F5"},
}
#: The motif is a tiny gantt: waits in amber, runs in blue, the critical path in orange.
BARS = [
    (0, 18, "#F59E0B", 0),
    (18, 44, "#3B82F6", 0),
    (8, 20, "#F59E0B", 1),
    (20, 92, "#EA580C", 1),
    (14, 30, "#F59E0B", 2),
    (30, 66, "#3B82F6", 2),
]


def banner(theme: dict[str, str]) -> str:
    motif_x, motif_y = 498, 15
    bars = "\n".join(
        f'    <rect x="{motif_x + start}" y="{motif_y + row * 10}" width="{end - start}" height="7" rx="3.5" fill="{color}"/>'
        for start, end, color, row in BARS
    )
    tracks = "\n".join(
        f'    <rect x="{motif_x}" y="{motif_y + row * 10}" width="120" height="7" rx="3.5" fill="{theme["track"]}"/>'
        for row in range(3)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="56" viewBox="0 0 640 56" role="img" aria-label="CI-esta pull request report">
  <title>CI-esta pull request report</title>
  <defs>
    <linearGradient id="sunset" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#FB923C"/>
      <stop offset="0.55" stop-color="#EA580C"/>
      <stop offset="1" stop-color="#C2410C"/>
    </linearGradient>
    <linearGradient id="glow" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#EA580C" stop-opacity="0.18"/>
      <stop offset="0.45" stop-color="#EA580C" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect x="0.5" y="0.5" width="639" height="55" rx="10" fill="{theme["bg"]}" stroke="{theme["edge"]}"/>
  <rect x="0.5" y="0.5" width="639" height="55" rx="10" fill="url(#glow)"/>
  <g transform="translate(10 8) scale(0.625)">
    <rect width="64" height="64" rx="15" fill="url(#sunset)"/>
    <path d="M15 34 L26 45 L46 23" fill="none" stroke="#FFFFFF" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
    <text x="42" y="19" font-family="{FONT}" font-size="11" font-weight="800" fill="#FFF7ED" opacity="0.85">z</text>
    <text x="49" y="13" font-family="{FONT}" font-size="14" font-weight="800" fill="#FFFFFF">Z</text>
  </g>
  <text x="62" y="36" font-family="{FONT}" font-size="25" font-weight="800" letter-spacing="-0.5" fill="{theme["ink"]}">CI<tspan fill="#EA580C">-esta</tspan></text>
  <text x="168" y="25" font-family="{FONT}" font-size="12" font-weight="600" fill="{theme["muted"]}">pull request report</text>
  <text x="168" y="41" font-family="{FONT}" font-size="12" fill="{theme["muted"]}">time · cost · what ran and why</text>
{tracks}
{bars}
</svg>
"""


out = pathlib.Path("docs/assets")
out.mkdir(parents=True, exist_ok=True)
for name, theme in THEMES.items():
    (out / f"sticky-banner-{name}.svg").write_text(banner(theme), encoding="utf-8", newline="\n")
print("written")
