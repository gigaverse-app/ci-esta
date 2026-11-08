"""Run native Bun batches and require measured completion before reporting success."""

import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ci_esta.testing.bun.models import BatchExecution, BunExecution, ReportContext, RunRequest
from ci_esta.testing.bun.report import work_selection_report
from ci_esta.testing.bun.selection import plan_affected_tests, read_inventory, read_test_selection

ARGUMENT = re.compile(
    r"(?:--isolate|--parallel(?:=[1-9]\d*)?|--timeout=[1-9]\d*|--max-concurrency=[1-9]\d*"
    r"|--seed=\d+|--randomize|--concurrent|--dots)\Z"
)


class Timings(BaseModel):
    model_config = ConfigDict(strict=True)
    files: dict[str, float]


def write_json(path: Path, value: BaseModel) -> None:
    path.write_text(value.model_dump_json(by_alias=True, exclude_none=False, indent=2) + "\n")


def append_outputs(**values: str | bool | int) -> None:
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a") as output:
            for key, value in values.items():
                output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def report_context() -> ReportContext:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()) if os.environ.get("GITHUB_EVENT_PATH") else {}
    return ReportContext(run_id=int(os.environ["GITHUB_RUN_ID"]), attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),
                         head_sha=event.get("pull_request", {}).get("head", {}).get("sha") or os.environ["GITHUB_SHA"])


def _execute_batch(request: RunRequest, index: int, files: list[str], affected: bool, base: str) -> BatchExecution:
    timings = request.output_directory / f"timings-{index}-{'affected' if affected else 'full'}.json"
    timings.write_text('{"version":1,"files":{}}')
    command = [request.bun, "test", *(f"./{file}" for file in files), *request.args,
               *([f"--changed={base}"] if affected else []), f"--timings={timings}", "--update-timings"]
    print(f"Bun batch {index + 1}/{request.shards}: {'affected' if affected else 'full'}, {len(files)} candidate files", file=sys.stderr)
    before = time.perf_counter()
    error = None
    try:
        result = subprocess.run(command, cwd=request.cwd, stdout=sys.stderr, stderr=sys.stderr)
        status = result.returncode if result.returncode >= 0 else 1
        if result.returncode < 0:
            error = f"signal {-result.returncode}"
    except OSError as failure:
        status, error = 1, str(failure)
    executed = None
    try:
        values = Timings.model_validate_json(timings.read_text()).files
        if any(file not in files or not math.isfinite(duration) or duration < 0 for file, duration in values.items()):
            raise ValueError("Invalid Bun execution timings")
        executed = sorted(values)
    except (OSError, ValueError):
        pass
    return BatchExecution(shard=index + 1, affected=affected, exit_code=status,
                          duration_ms=(time.perf_counter() - before) * 1000, executed_files=executed, error=error)


def run_bun_tests(request: RunRequest) -> BunExecution:
    inventory = read_inventory(request.cwd / request.inventory_file, request.cwd)
    if not all(ARGUMENT.fullmatch(arg) for arg in request.args):
        raise ValueError("Unsupported Bun execution arguments; selection, reports and file paths are owned by the adapter")
    version = subprocess.run([request.bun, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r"1\.(?:4\.(?:[2-9]|[1-9]\d+)|[5-9]\.\d+|[1-9]\d+\.\d+)", version):
        raise ValueError(f"Bun {version} is outside the verified >=1.4.2 <2 runtime contract")
    request = request.model_copy(update={"always_run_files": inventory.always_run_files,
                                         "output_directory": request.output_directory.resolve()})
    plan = (read_test_selection(Path(request.plan_file), request) if request.plan_file and not request.full
            else plan_affected_tests(request))
    request.output_directory.mkdir(parents=True, exist_ok=True)
    write_json(request.output_directory / "test-selection.json", plan)
    executions = []
    started = time.perf_counter()
    for index in range(request.shards):
        shard = inventory.files[index::request.shards]
        groups = [(shard, False)] if plan.mode == "full" else [
            ([file for file in shard if file in inventory.always_run_files], False),
            ([] if plan.mode == "none" else [file for file in shard if file not in inventory.always_run_files], True),
        ]
        for files, affected in groups:
            # An empty file list tells Bun to discover the whole repository.
            if files:
                executions.append(_execute_batch(request, index, files, affected, plan.base))
    known = all(batch.executed_files is not None for batch in executions)
    executed = sorted({file for batch in executions for file in (batch.executed_files or [])}) if known else None
    result = BunExecution(
        **plan.model_dump(), bun_version=version, cpu_count=os.cpu_count(),
        workers=None if "--parallel" in request.args else next(
            (int(arg.split("=")[1]) for arg in request.args if arg.startswith("--parallel=")), 1),
        total_files=len(inventory.files), always_run_files=inventory.always_run_files, executed_files=executed,
        executions=executions, duration_ms=(time.perf_counter() - started) * 1000,
        exit_code=next((batch.exit_code for batch in reversed(executions) if batch.exit_code), 0),
    )
    if not result.complete and result.exit_code == 0:
        print("Bun execution inventory is incomplete; successful processes alone cannot establish validation", file=sys.stderr)
        result.exit_code = 1
    write_json(request.output_directory / "execution-selection.json", result)
    if os.environ.get("GITHUB_RUN_ID"):
        write_json(request.output_directory / "ci-work-selection.json", work_selection_report(result, report_context()))
    append_outputs(mode=plan.mode, fallback=plan.fallback, **{"exit-code": result.exit_code})
    return result
