"""Scanner ownership must preserve full scans and the original CLI verdict."""

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("persisted", [False, True])
def test_diff_fetch_sends_exactly_one_authorization_header(tmp_path: Path, persisted: bool) -> None:
    """Exercise real Git's multi-valued config merging, not a Git stub's environment."""
    headers: list[list[str]] = []
    expected_auth = "basic eC1hY2Nlc3MtdG9rZW46Zml4dHVyZS10b2tlbg=="

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            headers.append(self.headers.get_all("Authorization", []))
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            env = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": str(tmp_path / "global"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "SCAN_SCOPE": "diff",
                "BASE_SHA": "a" * 40,
                "GITHUB_SERVER_URL": url,
                "SCAN_GITHUB_TOKEN": "fixture-token",
                "GITHUB_OUTPUT": str(tmp_path / "output"),
                "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            }

            def git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)

            git("init", "-q")
            git("remote", "add", "origin", url + "/private.git")
            if persisted:
                git("config", f"http.{url}/.extraheader", "AUTHORIZATION: basic checkout-token")
            original_config = (tmp_path / ".git/config").read_text()
            action = yaml.safe_load((ROOT / "actions/semgrep-scan/action.yml").read_text())
            script = next(step["run"] for step in action["runs"]["steps"] if step.get("id") == "targets")
            result = subprocess.run(
                ["sh", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10
            )
            assert result.returncode == 0, result.stderr
            assert headers == [[expected_auth]], "Inherited checkout authentication must be replaced, not appended"
            assert (tmp_path / ".git/config").read_text() == original_config, (
                "Fetch must not mutate checkout credentials"
            )
            assert (tmp_path / "output").read_text().strip() == "mode=full", "Missing remote still fails open"
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.parametrize("fetch_result", [0, 1])
def test_private_diff_fetch_authenticates_without_persisted_checkout_credentials(
    tmp_path: Path, fetch_result: int
) -> None:
    action = yaml.load((ROOT / "actions/semgrep-scan/action.yml").read_text(), Loader=yaml.BaseLoader)
    step = next(step for step in action["runs"]["steps"] if step.get("name") == "Resolve scan targets")
    binary = tmp_path / "git"
    binary.write_text(
        "#!/usr/bin/env python3\nimport os, sys\n"
        'if sys.argv[1] == "fetch":\n'
        ' sys.exit(int(os.environ["FETCH_RESULT"]))\n'
        'if sys.argv[1] == "diff": print("changed.py")\n'
    )
    binary.chmod(0o755)
    result = subprocess.run(
        ["sh", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "SCAN_SCOPE": "diff",
            "BASE_SHA": "a" * 40,
            "GITHUB_SERVER_URL": "https://github.com",
            "SCAN_GITHUB_TOKEN": "fixture-token",
            "FETCH_RESULT": str(fetch_result),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text().strip() == ("mode=diff" if fetch_result == 0 else "mode=full")
    assert step["env"]["SCAN_GITHUB_TOKEN"] == "${{ inputs.github-token }}"
    assert action["inputs"]["github-token"]["default"] == "${{ github.token }}"


@pytest.mark.parametrize("mode", ["diff", "full"])
@pytest.mark.parametrize("scanner_result", [0, 1, 2])
def test_scanner_keeps_verdict_and_only_excludes_ci_from_diff(tmp_path: Path, mode: str, scanner_result: int) -> None:
    action = yaml.load((ROOT / "actions/semgrep-scan/action.yml").read_text(), Loader=yaml.BaseLoader)
    script = next(step["run"] for step in action["runs"]["steps"] if step.get("name") == "Run semgrep scan")
    binary = tmp_path / "semgrep"
    binary.write_text(
        '#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\nPath("args.json").write_text(json.dumps(sys.argv[1:]))\nsys.exit(int(os.environ["SCANNER_RESULT"]))\n'
    )
    binary.chmod(0o755)
    (tmp_path / "changed-scan-targets.txt").write_text("--filename.py\nfile with spaces.py\n")
    result = subprocess.run(
        ["sh", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "CONFIGS": "p/python p/secrets",
            "SEMGREP_SEVERITY": "ERROR",
            "EXCLUDES": ".devcontainer",
            "DIFF_EXCLUDES": ".github tools/ci",
            "EXCLUDE_RULES": "",
            "SCAN_MODE": mode,
            "SCANNER_RESULT": str(scanner_result),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == scanner_result, result.stderr
    args = json.loads((tmp_path / "args.json").read_text())
    assert (".github" in args) is (mode == "diff")
    assert ("tools/ci" in args) is (mode == "diff")
    assert args[args.index("--") + 1 :] == (["--filename.py", "file with spaces.py"] if mode == "diff" else ["."])
    assert "--error" in args
    assert "--config" in args and "p/secrets" in args


def test_ci_owner_includes_every_source_ruleset() -> None:
    def configs(action_name: str) -> set[str]:
        action = yaml.load((ROOT / f"actions/{action_name}/action.yml").read_text(), Loader=yaml.BaseLoader)
        return set(action["inputs"]["configs"]["default"].split())

    assert configs("semgrep-scan") <= configs("semgrep-scan-ci-code")


@pytest.mark.parametrize("remaining", ["", "src/application.py", ".github-other/action.py"])
def test_diff_targets_remove_files_owned_by_ci_before_scanning(tmp_path: Path, remaining: str) -> None:
    """Explicit Semgrep file arguments must never bypass the CI ownership boundary."""
    action = yaml.safe_load((ROOT / "actions/semgrep-scan/action.yml").read_text())
    script = next(step["run"] for step in action["runs"]["steps"] if step.get("id") == "targets")
    git = tmp_path / "git"
    git.write_text('#!/bin/sh\nif [ "$1" = diff ]; then cat "$DIFF_FILE"; fi\n')
    git.chmod(0o755)
    (tmp_path / "diff").write_text(
        ".github/workflows/tests.yaml\ntools/ci/check.py\n" + (remaining + "\n" if remaining else "")
    )
    result = subprocess.run(
        ["sh", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "SCAN_SCOPE": "diff",
            "BASE_SHA": "a" * 40,
            "DIFF_FILE": str(tmp_path / "diff"),
            "DIFF_EXCLUDES": ".github tools/ci",
            "GITHUB_SERVER_URL": "https://github.com",
            "SCAN_GITHUB_TOKEN": "fixture",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        },
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "changed-scan-targets.txt").read_text().splitlines() == ([remaining] if remaining else [])
    assert (tmp_path / "output").read_text().strip() == ("mode=diff" if remaining else "mode=empty")
