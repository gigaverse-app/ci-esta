"""Render project branding from one mark and brand.json; optionally export PNGs."""

import argparse
import json
import re
from hashlib import sha256
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets"


def digest(path):
    content = path.read_bytes() if path.suffix == ".png" else path.read_text(encoding="utf-8").encode("utf-8")
    return sha256(content).hexdigest()


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


def banner(theme: dict[str, str], mark: str) -> str:
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
    <linearGradient id="glow" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#EA580C" stop-opacity="0.18"/>
      <stop offset="0.45" stop-color="#EA580C" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect x="0.5" y="0.5" width="639" height="55" rx="10" fill="{theme["bg"]}" stroke="{theme["edge"]}"/>
  <rect x="0.5" y="0.5" width="639" height="55" rx="10" fill="url(#glow)"/>
  <g transform="translate(10 8) scale(0.625)">{mark}</g>
  <text x="62" y="36" font-family="{FONT}" font-size="25" font-weight="800" letter-spacing="-0.5" fill="{theme["ink"]}">CI<tspan fill="#EA580C">-esta</tspan></text>
  <text x="168" y="25" font-family="{FONT}" font-size="12" font-weight="600" fill="{theme["muted"]}">pull request report</text>
  <text x="168" y="41" font-family="{FONT}" font-size="12" fill="{theme["muted"]}">time · cost · what ran and why</text>
{tracks}
{bars}
</svg>
"""


def render():
    brand = json.loads((ASSETS / "brand.json").read_text(encoding="utf-8"))
    logo = (ASSETS / "logo.svg").read_text(encoding="utf-8")
    result = {f"docs/assets/sticky-banner-{theme}.svg": banner(colors, logo) for theme, colors in THEMES.items()}
    result["docs/assets/banner.svg"] = banner(THEMES["dark"], logo).replace(
        "pull request report", "faster GitHub Actions"
    )
    result["docs/assets/social-preview.svg"] = (
        (ASSETS / "social-preview.template.svg")
        .read_text(encoding="utf-8")
        .replace("<!-- canonical-logo -->", logo)
        .replace("<!-- tagline -->", escape(brand["tagline"]))
    )
    for alias in brand["logo_aliases"]:
        result[alias] = logo
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", action="store_true", help="Export PNGs with resvg-py 0.2.6")
    parser.add_argument("--check", action="store_true", help="Check generated SVGs without writing")
    args = parser.parse_args()
    stale = []
    for name, content in render().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
    if stale:
        parser.exit(1, "Regenerate branding: " + ", ".join(stale) + "\n")
    if args.png:
        import resvg_py

        for source, target, width, height in (
            ("logo.svg", "icon.png", 256, 256),
            ("banner.svg", "banner.png", 1280, 112),
            ("social-preview.svg", "social-preview.png", 1280, 640),
        ):
            (ASSETS / target).write_bytes(
                bytes(resvg_py.svg_to_bytes(svg_path=str(ASSETS / source), width=width, height=height))
            )
        names = [
            "logo.svg",
            "brand.json",
            "banner.svg",
            "social-preview.svg",
            "icon.png",
            "banner.png",
            "social-preview.png",
        ]
        hashes = {name: digest(ASSETS / name) for name in names}
        (ASSETS / "raster-sources.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    if args.check:
        hashes = json.loads((ASSETS / "raster-sources.json").read_text(encoding="utf-8"))
        for name, expected in hashes.items():
            if digest(ASSETS / name) != expected:
                parser.exit(1, "Regenerate PNG exports with --png: " + name + "\n")
    # README images need the same cache refresh as documentation image URLs.
    brand = json.loads((ASSETS / "brand.json").read_text(encoding="utf-8"))
    image_url = f"https://raw.githubusercontent.com/gigaverse-app/{brand['repository']}/main/docs/assets/banner.png"
    versioned_url = image_url + "?v=" + digest(ASSETS / "banner.png")[:12]
    for readme in (ROOT / "README.md", ROOT / "package/README.md"):
        if not readme.exists():
            continue
        text = readme.read_text(encoding="utf-8")
        if args.png:
            readme.write_text(
                re.sub(re.escape(image_url) + r"(?:\?v=[0-9a-f]+)?", versioned_url, text),
                encoding="utf-8",
                newline="\n",
            )
        elif args.check and versioned_url not in text:
            parser.exit(1, "Refresh the README banner with --png: " + str(readme) + "\n")
    print("Brand assets verified" if args.check else "Brand assets rendered")


if __name__ == "__main__":
    main()
