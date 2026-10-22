"""
Record the REST methods that a pinned ``actions/github-script`` release provides.

Shared JavaScript calls ``github.rest.<namespace>.<method>``, and tests replace that
client with fakes. A fake that defines a method the real client lacks hides the bug:
``resolve.cjs`` called ``actions.listWorkflowRunsForWorkflow`` for weeks, the real
Octokit has no such method, ``github.paginate(undefined)`` fetched the API root, and
every same-head reuse silently fell back. The recorded surface is what the contract
test and the strict fake check against.

Regenerate after changing the ``actions/github-script`` pin::

    gh api -H "Accept: application/vnd.github.raw" \\
      "repos/actions/github-script/contents/dist/index.js?ref=<sha>" > /tmp/github-script.js
    python -m scripts.ci.github_script_surface --sha <sha> --bundle /tmp/github-script.js \\
      --output tests/ci/github_script_rest_surface.json
"""

import argparse
import json
import re
from pathlib import Path

ENDPOINTS_START = "const Endpoints = {"
NAMESPACE = re.compile(r"^  (\w+): \{$")
METHOD = re.compile(r"^    (\w+): \[")


def rest_surface(bundle: str) -> dict[str, list[str]]:
    """Parse the Octokit endpoint table bundled into github-script's ``dist/index.js``."""
    lines = bundle.splitlines()
    try:
        start = lines.index(ENDPOINTS_START)
    except ValueError:
        raise ValueError(f"bundle has no line {ENDPOINTS_START!r}; its layout changed") from None
    surface: dict[str, list[str]] = {}
    namespace = ""
    for line in lines[start + 1 :]:
        if line == "};":
            break
        if match := NAMESPACE.match(line):
            namespace = match.group(1)
            surface[namespace] = []
        elif (match := METHOD.match(line)) and namespace:
            surface[namespace].append(match.group(1))
    else:
        raise ValueError("endpoint table never closed; the bundle layout changed")
    if not surface.get("actions"):
        raise ValueError("no actions methods found; the bundle layout changed")
    return {name: sorted(methods) for name, methods in sorted(surface.items())}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Record the REST methods a pinned actions/github-script provides.")
    parser.add_argument("--sha", required=True, help="actions/github-script commit the bundle came from")
    parser.add_argument("--bundle", required=True, type=Path, help="that commit's dist/index.js")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    surface = rest_surface(args.bundle.read_text(encoding="utf-8"))
    record = {"github_script_sha": args.sha, "rest": surface}
    args.output.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
