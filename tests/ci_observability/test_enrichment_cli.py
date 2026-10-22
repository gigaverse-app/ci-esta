"""
Pin the union enrichment CLI's interface and output bytes.

The output files feed the shared reporter's ``extensions-file`` /
``repository-signals-file`` inputs, and each consumer's dashboards read
them back — so the exact serialization (writer function, indent, trailing
newline) is contract, not style.
"""

import ast
import json
from pathlib import Path

import pytest

import ci_esta.ci_observability.enrichment.cli as cli_module
from ci_esta.ci_observability.enrichment.backend.artifacts import (
    build_extension,
)
from ci_esta.ci_observability.enrichment.backend.models import GitHubEnrichment
from ci_esta.ci_observability.enrichment.cli import main
from ci_esta.ci_observability.enrichment.models import PytestTimingMetadata

ACTION_PATH = Path(".github/actions/ci-observability-enrichment/action.yml")
GITHUB_ENV_VARS = ("GITHUB_REPOSITORY", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_RUN_ID")


class TestCapturePytest:
    def test_writes_parsed_timing_metadata(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "ci-pytest-timings.json"

        exit_code = main(
            [
                "capture-pytest",
                "--shard-count",
                "4",
                "--wall-time",
                "1m 34s",
                "--total-time",
                "4m 21s",
                "--out",
                str(out),
            ]
        )

        assert exit_code == 0
        metadata = PytestTimingMetadata.model_validate_json(out.read_text())
        assert metadata.shard_count == 4
        assert metadata.wall_seconds == 94.0
        assert metadata.total_test_seconds == 261.0
        assert out.read_text().endswith("\n")


class TestBuildBackend:
    def test_writes_extension_and_signals_with_original_formatting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in GITHUB_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        artifacts_dir = tmp_path / "coverage-artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "coverage.xml").write_text('<coverage line-rate="0.5"/>')
        out = tmp_path / "extension.json"
        signals_out = tmp_path / "signals.json"

        exit_code = main(
            [
                "build-backend",
                "--artifacts-dir",
                str(artifacts_dir),
                "--out",
                str(out),
                "--signals-out",
                str(signals_out),
            ]
        )

        assert exit_code == 0
        expected = build_extension(artifacts_dir, GitHubEnrichment())
        assert out.read_text() == expected.model_dump_json(indent=2) + "\n"
        signals = json.loads(signals_out.read_text())
        assert [signal["key"] for signal in signals] == ["line_coverage"]
        assert signals_out.read_text().endswith("\n")


class TestBuildAi:
    def test_deploy_uses_ai_json_formatting_and_default_outputs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        artifacts_dir = tmp_path / "ci-build-artifacts"
        artifacts_dir.mkdir()

        exit_code = main(["build-ai", "--workflow-class", "deploy"])

        assert exit_code == 0
        extension_text = (tmp_path / "ci-observability-extension.json").read_text()
        extension = json.loads(extension_text)
        assert extension["ai"]["workflow_class"] == "deploy"
        assert extension["ai"]["unavailable"] == ["no build metric artifacts were available"]
        assert extension_text == json.dumps(extension, indent=2) + "\n"
        assert json.loads((tmp_path / "ci-observability-signals.json").read_text()) == []

    def test_python_tests_flags_reach_the_snapshot(self, tmp_path: Path) -> None:
        out = tmp_path / "extension.json"
        signals_out = tmp_path / "signals.json"

        exit_code = main(
            [
                "build-ai",
                "--workflow-class",
                "python_tests",
                "--pytest-shard-count",
                "3",
                "--pytest-wall-time",
                "1m 34s",
                "--pytest-total-time",
                "4m 21s",
                "--out",
                str(out),
                "--signals-out",
                str(signals_out),
            ]
        )

        assert exit_code == 0
        extension = json.loads(out.read_text())
        assert extension["ai"]["pytest"] == {
            "shard_count": 3,
            "wall_seconds": 94.0,
            "total_test_seconds": 261.0,
        }
        signals = json.loads(signals_out.read_text())
        assert [signal["key"] for signal in signals] == ["pytest_parallelism"]


class TestLegacyMetrics:
    def test_renders_metrics_from_report_and_extension_files(self, tmp_path: Path) -> None:
        report_path = tmp_path / "ci-observability.json"
        extension_path = tmp_path / "extension.json"
        out = tmp_path / "ci-timing-legacy.prom"
        report_path.write_text(
            json.dumps(
                {
                    "latest_attempt_jobs": [],
                    "required_gates": [{"conclusion": "success"}],
                    "runner_cost": {
                        "raw_runner_seconds": 300,
                        "estimated_rounded_runner_minutes": 7,
                        "rounding_waste_seconds": 120,
                    },
                }
            )
        )
        extension_path.write_text(json.dumps({"backend": {"contract_version": "CI-OBS-BACKEND-ENRICH-v1"}}))

        exit_code = main(
            [
                "legacy-metrics",
                "--report",
                str(report_path),
                "--extension",
                str(extension_path),
                "--out",
                str(out),
            ]
        )

        assert exit_code == 0
        assert 'ci_raw_runner_seconds{test_conclusion="success"} 300.0' in out.read_text()


class TestLazyProfileImports:
    def test_backend_profile_modules_are_imported_only_inside_handlers(self) -> None:
        """
        Capture-pytest and build-ai must not pay for — or be broken by —
        the backend profile's GitHub client and XML parsing."""
        source = Path(cli_module.__file__).read_text(encoding="utf-8")
        module_level_imports = {
            name for node in ast.parse(source).body if isinstance(node, ast.ImportFrom) for name in [node.module or ""]
        }
        lazy_prefix = "ci_esta.ci_observability.enrichment.backend"
        assert not [module for module in module_level_imports if module.startswith(lazy_prefix)]
