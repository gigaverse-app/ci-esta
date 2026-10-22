"""
Write CI-esta's brand assets into docs/assets; run from the repository root.

The sticky's dark and light banners, and the 1280x640 social-preview card. GitHub takes the card
only as an uploaded PNG (repository Settings, Social preview); render it with
`uv run --no-project --with resvg-py==0.2.6 python scripts/render_sticky_banners.py --png`.
"""

import pathlib
import sys

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


SOCIAL_PREVIEW = '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640">\n  <defs>\n    <linearGradient id="sunset" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FB923C"/><stop offset="0.55" stop-color="#EA580C"/><stop offset="1" stop-color="#C2410C"/></linearGradient>\n    <radialGradient id="glow" cx="0.15" cy="0.2" r="0.9"><stop offset="0" stop-color="#EA580C" stop-opacity="0.28"/><stop offset="0.6" stop-color="#EA580C" stop-opacity="0"/></radialGradient>\n  </defs>\n  <rect width="1280" height="640" fill="#0D1117"/>\n  <rect width="1280" height="640" fill="url(#glow)"/>\n  <g transform="translate(80 96) scale(2.5)">\n    <rect width="64" height="64" rx="15" fill="url(#sunset)"/>\n    <path d="M15 34 L26 45 L46 23" fill="none" stroke="#FFFFFF" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>\n    <path d="M42 13h7l-7 7h7" fill="none" stroke="#FFF7ED" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>\n    <path d="M50 4h9l-9 9h9" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>\n  </g>\n  <text x="290" y="200" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif" font-size="104" font-weight="800" letter-spacing="-2" fill="#F0F6FC">CI<tspan fill="#EA580C">-esta</tspan></text>\n  <text x="290" y="256" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif" font-size="34" fill="#8B949E">Let proven work rest. Measure the rest.</text>\n  <text x="80" y="440" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif" font-size="30" font-weight="600" fill="#F0F6FC">Faster GitHub Actions,</text>\n  <text x="80" y="484" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif" font-size="30" font-weight="600" fill="#F0F6FC">with evidence.</text>\n  <text x="80" y="600" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif" font-size="22" fill="#8B949E">time · cost · what ran and why · github.com/gigaverse-app/ci-esta</text>\n  <rect x="640" y="420" width="560" height="28" rx="14" fill="#21262D"/>\n  <rect x="640" y="464" width="560" height="28" rx="14" fill="#21262D"/>\n  <rect x="640" y="508" width="560" height="28" rx="14" fill="#21262D"/>\n  <rect x="640" y="420" width="90" height="28" rx="14" fill="#F59E0B"/>\n  <rect x="730" y="420" width="170" height="28" rx="14" fill="#3B82F6"/>\n  <rect x="680" y="464" width="60" height="28" rx="14" fill="#F59E0B"/>\n  <rect x="740" y="464" width="420" height="28" rx="14" fill="#EA580C"/>\n  <rect x="710" y="508" width="80" height="28" rx="14" fill="#F59E0B"/>\n  <rect x="790" y="508" width="230" height="28" rx="14" fill="#3B82F6"/>\n</svg>\n'


out = pathlib.Path("docs/assets")
out.mkdir(parents=True, exist_ok=True)
for name, theme in THEMES.items():
    (out / f"sticky-banner-{name}.svg").write_text(banner(theme), encoding="utf-8", newline="\n")
(out / "social-preview.svg").write_text(SOCIAL_PREVIEW, encoding="utf-8", newline="\n")
if "--png" in sys.argv:
    import resvg_py

    png = resvg_py.svg_to_bytes(svg_path=str(out / "social-preview.svg"), width=1280, height=640)
    (out / "social-preview.png").write_bytes(bytes(png))
print("written")
