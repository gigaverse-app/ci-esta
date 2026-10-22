"""
Union CLI over both consumer enrichment profiles.

Subcommands preserve each consumer's original interface and output bytes:
``capture-pytest``, ``build-backend``, ``adopt-legacy-sticky`` and
``legacy-metrics`` mirror gigaverse-backend's
``deployment/scripts/ci_observability_enrichment.py``; ``build-ai`` mirrors
gigaverse-ai's ``.github/scripts/ci_observability_enrichment.py`` flags.
``render-selection`` is shared: it renders the sticky's test-selection section
from a ``gv-test-impact affected --explanation-output`` file.

The backend profile's modules are imported inside their handlers, so
``capture-pytest`` and ``build-ai`` never load the GitHub client or XML
parsing they do not use.
"""

import argparse
import json
from pathlib import Path

from ci_esta.ci_observability.enrichment.ai import (
    WorkflowClass,
    build_deploy_extension,
    build_workflow_extension,
)
from ci_esta.ci_observability.enrichment.ai import build_repository_signals as build_ai_repository_signals
from ci_esta.ci_observability.enrichment.models import PytestTimingMetadata
from ci_esta.ci_observability.enrichment.primitives import write_pytest_metadata


def _capture_pytest(args: argparse.Namespace) -> None:
    write_pytest_metadata(
        args.out,
        shard_count=args.shard_count,
        wall_time=args.wall_time,
        total_time=args.total_time,
    )


def _build_backend(args: argparse.Namespace) -> None:
    from ci_esta.ci_observability.enrichment.backend.artifacts import (
        build_extension,
        build_repository_signals,
    )
    from ci_esta.ci_observability.enrichment.backend.github import (
        collect_github_enrichment,
    )

    extension = build_extension(
        args.artifacts_dir,
        collect_github_enrichment(),
    )
    args.out.write_text(extension.model_dump_json(indent=2) + "\n")
    args.signals_out.write_text(
        json.dumps(
            [signal.model_dump(mode="json") for signal in build_repository_signals(extension)],
            indent=2,
        )
        + "\n"
    )


def _legacy_metrics(args: argparse.Namespace) -> None:
    from ci_esta.ci_observability.enrichment.backend.legacy import (
        SharedReport,
        render_legacy_metrics,
    )
    from ci_esta.ci_observability.enrichment.backend.models import (
        BackendExtensions,
    )

    report = SharedReport.model_validate_json(args.report.read_text())
    extension = BackendExtensions.model_validate_json(args.extension.read_text())
    args.out.write_text(render_legacy_metrics(report, extension))


def _adopt_legacy_sticky(args: argparse.Namespace) -> None:
    from ci_esta.ci_observability.enrichment.backend.github import (
        adopt_legacy_sticky,
    )

    adopt_legacy_sticky(args.pull_request)


def _build_ai(args: argparse.Namespace) -> None:
    workflow_class = WorkflowClass(args.workflow_class)
    if workflow_class == WorkflowClass.DEPLOY:
        extension = build_deploy_extension(args.artifacts_dir or Path("ci-build-artifacts"))
    else:
        extension = build_workflow_extension(
            workflow_class,
            pytest_shard_count=args.pytest_shard_count,
            pytest_wall_time=args.pytest_wall_time,
            pytest_total_time=args.pytest_total_time,
        )
    args.out.write_text(json.dumps(extension.model_dump(mode="json"), indent=2) + "\n")
    args.signals_out.write_text(
        json.dumps(
            [signal.model_dump(mode="json") for signal in build_ai_repository_signals(extension)],
            indent=2,
        )
        + "\n"
    )


def _render_selection(args: argparse.Namespace) -> None:
    from pytest_selective.impact_models import SelectionExplanation

    from ci_esta.ci_observability.models import FullSuiteReferenceV1, SelectionSectionV1
    from ci_esta.ci_observability.selection import render_selection_section

    section = SelectionSectionV1(
        explanation=SelectionExplanation.model_validate_json(args.explanation.read_text(encoding="utf-8")),
        pytest=PytestTimingMetadata.model_validate_json(args.pytest.read_text()) if args.pytest else None,
        references=[FullSuiteReferenceV1.model_validate_json(path.read_text()) for path in args.reference],
    )
    args.out.write_text(render_selection_section(section), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gv-ci-enrichment")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture-pytest")
    capture.add_argument("--shard-count", type=int, required=True)
    capture.add_argument("--wall-time", required=True)
    capture.add_argument("--total-time", required=True)
    capture.add_argument("--out", type=Path, required=True)
    capture.set_defaults(handler=_capture_pytest)

    build_backend = subparsers.add_parser("build-backend")
    build_backend.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("coverage-artifacts"),
    )
    build_backend.add_argument(
        "--out",
        type=Path,
        default=Path("ci-observability-extension.json"),
    )
    build_backend.add_argument(
        "--signals-out",
        type=Path,
        default=Path("ci-observability-signals.json"),
    )
    build_backend.set_defaults(handler=_build_backend)

    adopt = subparsers.add_parser("adopt-legacy-sticky")
    adopt.add_argument("--pull-request", type=int, required=True)
    adopt.set_defaults(handler=_adopt_legacy_sticky)

    legacy = subparsers.add_parser("legacy-metrics")
    legacy.add_argument("--report", type=Path, required=True)
    legacy.add_argument("--extension", type=Path, required=True)
    legacy.add_argument("--out", type=Path, required=True)
    legacy.set_defaults(handler=_legacy_metrics)

    build_ai = subparsers.add_parser("build-ai")
    build_ai.add_argument(
        "--workflow-class",
        required=True,
        choices=[item.value for item in WorkflowClass],
    )
    build_ai.add_argument("--artifacts-dir", type=Path)
    build_ai.add_argument("--pytest-shard-count", type=int)
    build_ai.add_argument("--pytest-wall-time", default="")
    build_ai.add_argument("--pytest-total-time", default="")
    build_ai.add_argument("--out", type=Path, default=Path("ci-observability-extension.json"))
    build_ai.add_argument(
        "--signals-out",
        type=Path,
        default=Path("ci-observability-signals.json"),
    )
    build_ai.set_defaults(handler=_build_ai)

    selection = subparsers.add_parser("render-selection")
    selection.add_argument("--explanation", type=Path, required=True, help="gv-test-impact --explanation-output")
    selection.add_argument("--pytest", type=Path, help="capture-pytest output for this run")
    selection.add_argument(
        "--reference",
        type=Path,
        action="append",
        default=[],
        help="a full-suite run to measure against; repeat for a median",
    )
    selection.add_argument("--out", type=Path, required=True)
    selection.set_defaults(handler=_render_selection)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.handler(args)
    return 0
