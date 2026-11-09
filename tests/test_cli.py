import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ci_esta.ci_observability.report import build_unavailable_report


def test_installed_cli_renders_a_saved_report_without_credentials(tmp_path: Path) -> None:
    report = build_unavailable_report(
        repository="example/project", run_id=42, run_attempt=1, head_sha="a" * 40,
        pull_request_number=None, observed_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
        error="API unavailable", repository_signals=[],
    )
    source = tmp_path / "input.json"
    source.write_text(report.model_dump_json(), encoding="utf-8")
    markdown, metrics = tmp_path / "report.md", tmp_path / "report.prom"
    result = subprocess.run(
        [sys.executable, "-m", "ci_esta.cli", "render", str(source), "--markdown", str(markdown), "--prometheus", str(metrics)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "API unavailable" in markdown.read_text(encoding="utf-8")
    assert "ci_raw_runner_seconds" in metrics.read_text(encoding="utf-8")


def test_cli_help_describes_report_and_render() -> None:
    result = subprocess.run([sys.executable, "-m", "ci_esta.cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "report" in result.stdout and "render" in result.stdout


def test_cli_version_names_the_installed_release() -> None:
    from importlib.metadata import version

    result = subprocess.run([sys.executable, "-m", "ci_esta.cli", "--version"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"ci-esta {version('ci-esta')}"


def run_without_selection(module: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a CLI as a base install sees it: pytest-selective and pytest cannot be imported."""
    code = (
        "import sys; sys.modules.update(pytest_selective=None, pytest=None, _pytest=None); "
        f"from {module} import main; raise SystemExit(main(sys.argv[1:]))"
    )
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=env)


@pytest.mark.parametrize("module, args", [
    ("ci_esta.testing.cli", ["plan", "--shards", "2", "--output-dir", "splits"]),
    ("ci_esta.testing.cli", ["merge", "missing.json"]),
    ("ci_esta.cli", ["check-workflow", "--workflow", "ci.yml"]),
    ("ci_esta.cli", ["lanes", "--help"]),
])
def test_commands_needing_selection_name_the_extra_on_a_base_install(tmp_path, module, args) -> None:
    result = run_without_selection(module, *args)
    assert result.returncode == 2, result.stderr
    assert "ci-esta[selection]" in result.stderr
    assert "Traceback" not in result.stderr


def test_runner_pools_and_junit_tools_work_on_a_base_install() -> None:
    result = run_without_selection("ci_esta.testing.cli", "pools", "--shards", "3", "--shards-per-runner", "2")
    assert result.returncode == 0, result.stderr
    assert [pool["id"] for pool in json.loads(result.stdout)] == ["1", "2"]


def test_report_without_a_token_says_which_variable_and_how_to_get_one(tmp_path) -> None:
    env = {name: value for name, value in os.environ.items() if name not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    result = subprocess.run(
        [sys.executable, "-m", "ci_esta.cli", "report", "--repository", "owner/repo", "--run-id", "1",
         "--output-dir", str(tmp_path / "report")],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 2
    assert "GH_TOKEN" in result.stderr and "gh auth token" in result.stderr
    assert not (tmp_path / "report").exists()
