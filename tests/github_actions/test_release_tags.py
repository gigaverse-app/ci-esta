"""Exercise the publish workflow's actual tag promotion against a fake GitHub API."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("exists", [True, False])
@pytest.mark.parametrize("release,alias", [
    ("v0.3.1", "v1"), ("v0.4.0", "v1"),
    ("v1.0.0", "v1"), ("v1.0.1", "v1"), ("v1.2.0", "v1"), ("v2.0.0", "v1"),
    ("v1.1.0-rc.1", None), ("v1.1.0+build", None), ("main", None), ("v1", None),
])
def test_publication_updates_only_the_compatible_alias(release: str, alias: str | None, exists: bool) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    job = workflow["jobs"]["action-version"]
    assert job["needs"] == "publish"
    script = job["steps"][0]["run"]
    fake = '''
gh() {
  printf '%s\\n' "$*"
  if [[ "$2" != "--method" ]]; then
    return "$LOOKUP_STATUS"
  fi
}
'''
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", fake + script],
        capture_output=True, text=True, check=True,
        env=os.environ | {"RELEASE_TAG": release, "RELEASE_SHA": "tested-release-sha",
                          "ACTION_API_MAJOR": job["steps"][0]["env"]["ACTION_API_MAJOR"], "GH_REPO": "org/tool", "LOOKUP_STATUS": "0" if exists else "1"},
    )
    if alias is None:
        assert not result.stdout
        return
    mutation = (
        f"api --method PATCH repos/org/tool/git/refs/tags/{alias} -f sha=tested-release-sha -F force=true --silent"
        if exists else
        f"api --method POST repos/org/tool/git/refs -f ref=refs/tags/{alias} -f sha=tested-release-sha --silent"
    )
    assert result.stdout.splitlines() == [f"api repos/org/tool/git/ref/tags/{alias} --silent", mutation]
