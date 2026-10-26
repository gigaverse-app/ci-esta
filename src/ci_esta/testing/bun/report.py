"""Translate native Bun measurements through the shared portable report models."""

import math

from ci_esta.ci_observability.work_selection import WorkDecisionV1, WorkExecutionV1, WorkSelectionV1
from ci_esta.testing.bun.models import BunExecution, ReportContext


def work_selection_report(execution: BunExecution, context: ReportContext) -> WorkSelectionV1:
    reused = execution.mode == "reused"
    status = "not_run" if reused else "failed" if execution.exit_code else "passed" if execution.complete else "incomplete"
    duration = execution.duration_ms
    return WorkSelectionV1(
        provider="Bun", run_id=context.run_id, run_attempt=context.attempt, head_sha=context.head_sha,
        input_identity=execution.tested_sha, fallback=execution.fallback,
        decisions=[WorkDecisionV1(
            name="Bun tests", decision="reused" if reused else "unaffected" if execution.mode == "none" else "run",
            reason=execution.reason[:1000], receipt=execution.receipt if reused else None,
            execution=WorkExecutionV1(
                mode=execution.mode, status=status, total_files=execution.total_files,
                executed_files=execution.executed_files, always_run_files=execution.always_run_files,
                duration_seconds=duration / 1000 if duration is not None and math.isfinite(duration) else None,
                cpu_count=execution.cpu_count, worker_limit=execution.workers, runner_label=execution.runner_label,
                tested_sha=execution.tested_sha, base_sha=execution.base or None, runtime=f"Bun {execution.bun_version}",
            ),
        )],
    )
