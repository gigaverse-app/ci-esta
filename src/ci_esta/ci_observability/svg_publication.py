"""Upload passive images to the report's own repository, never a public asset host.

Uses the same endpoint as GitHub CLI v2.102.0's attachment uploader. The ordinary
Actions installation token is unsupported there; missing user credentials keep
the complete text report. No permission or repository visibility is changed.
"""

from __future__ import annotations

import re

import httpx

from ci_esta.ci_observability.models import CiObservabilityReportV1
from ci_esta.ci_observability.report import render_markdown
from ci_esta.ci_observability.svg_headlines import SvgHeadlines

ASSET_URL = re.compile(r"https://github\.com/user-attachments/assets/[a-fA-F0-9-]+\Z")
PROBE = '<svg xmlns="http://www.w3.org/2000/svg"><title>ci-esta privacy probe</title></svg>'


def publish_headlines(report: CiObservabilityReportV1, marker: str, *, repository: str,
                      token: str, transport: httpx.BaseTransport | None = None) -> str:
    """Return hybrid Markdown only after successful, same-repository uploads.

    A harmless probe establishes anonymous denial *before* private metrics leave
    the runner. Uncertain visibility, unsupported auth, upload failure or a
    suspect URL preserve a text-only report, without public badge requests.
    Exceptions never expose response bodies, credentials or redirect URLs.
    """
    if report.provenance.repository.casefold() != repository.casefold():
        raise ValueError("Report and attachment repository must match")
    fallback = render_markdown(report, marker, private_metrics=True)
    if not token.startswith(("ghp_", "gho_", "github_pat_", "ghu_")):
        print("::notice::SVG headlines need a supported GitHub user token; retaining text headlines")
        return fallback
    try:
        with httpx.Client(headers={"Authorization": f"Bearer {token}",
                                   "Accept": "application/vnd.github+json"},
                          timeout=20, transport=transport, follow_redirects=False) as client:
            response = client.get(f"https://api.github.com/repos/{repository}")
            response.raise_for_status()
            repo = response.json()
            if (repo.get("full_name", "").casefold() != repository.casefold()
                    or type(repo.get("id")) is not int or repo["id"] <= 0
                    or type(repo.get("private")) is not bool):
                raise ValueError("Repository identity or visibility unavailable")

            def upload(name: str, svg: str) -> str:
                result = client.post("https://uploads.github.com/user-attachments/assets",
                                     params={"name": name, "content_type": "image/svg+xml",
                                             "repository_id": str(repo["id"])},
                                     headers={"Content-Type": "application/octet-stream"},
                                     content=svg.encode())
                result.raise_for_status()
                url = result.json().get("url", "")
                if not ASSET_URL.fullmatch(url):
                    raise ValueError("Unexpected attachment location")
                return url

            if repo["private"]:
                probe = upload("ci-esta-privacy-probe.svg", PROBE)
                # This client has no credentials or cookies. Do not follow a
                # redirect and mistake a public image or login page for denial.
                with httpx.Client(timeout=20, transport=transport, follow_redirects=False) as anonymous:
                    denied = anonymous.get(probe)
                    if denied.status_code not in (401, 403, 404):
                        raise ValueError("Private attachment anonymous denial unconfirmed")

            images = SvgHeadlines()
            render_markdown(report, marker, headlines=images)
            for name, svg in images.assets.items():
                images.urls[name] = upload(name, svg)
            return render_markdown(report, marker, headlines=images)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        print("::warning::SVG attachment publication unavailable or privacy unconfirmed; retaining text headlines")
        return fallback
