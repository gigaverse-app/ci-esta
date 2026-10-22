import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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
