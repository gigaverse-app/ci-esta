"""Actions and compatibility entry points use the same Python implementation."""

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import BaseModel
from pytest_selective.checkpoint import full_checkpoint_reason

from ci_esta.testing.bun.execution import report_context, run_bun_tests, write_json
from ci_esta.testing.bun.models import BunExecution, ReportContext, RunRequest, SelectionRequest
from ci_esta.testing.bun.report import work_selection_report
from ci_esta.testing.bun.selection import plan_affected_tests, read_inventory, read_test_selection, safe_path


def request_from_env() -> RunRequest:
    reason = full_checkpoint_reason(os.environ.get("BUN_TEST_FULL") or "auto")
    return RunRequest(
        inventory_file=os.environ["BUN_TEST_INVENTORY"],
        policy_file=os.environ.get("BUN_TEST_POLICY") or ".github/test-selection.json",
        base=os.environ.get("BUN_TEST_BASE", ""), validated_head=os.environ.get("BUN_TEST_VALIDATED_HEAD", ""),
        full=reason is not None, checkpoint_reason=reason,
        output_directory=Path(os.environ["BUN_TEST_OUTPUT"]),
        args=json.loads(os.environ.get("BUN_TEST_ARGS") or '["--isolate","--parallel"]'),
        shards=int(os.environ.get("BUN_TEST_SHARDS") or "1"),
    )


class BridgeRequest(BaseModel):
    options: SelectionRequest | None = None
    path: Path | None = None
    cwd: Path | None = None
    execution: BunExecution | None = None
    context: ReportContext | None = None
    value: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["run", "report", "plan", "read-plan", "inventory", "safe-path"])
    parser.add_argument("--json-input", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == "run":
            request = RunRequest.model_validate_json(sys.stdin.read()) if args.json_input else request_from_env()
            result = run_bun_tests(request)
            if args.json_input:
                print(result.model_dump_json(by_alias=True))
                return 0
            return result.exit_code
        if args.operation == "report" and not args.json_input:
            execution = BunExecution.model_validate_json(Path(os.environ["BUN_EXECUTION_FILE"]).read_text())
            write_json(Path(os.environ.get("BUN_WORK_REPORT") or "ci-work-selection.json"),
                       work_selection_report(execution, report_context()))
            return 0
        request = BridgeRequest.model_validate_json(sys.stdin.read())
        if args.operation == "plan":
            if request.options is None:
                parser.error("plan requires options")
            value = plan_affected_tests(request.options).model_dump(by_alias=True, exclude_none=True)
        elif args.operation == "read-plan":
            if request.path is None:
                parser.error("read-plan requires path")
            value = read_test_selection(request.path, request.options or SelectionRequest()).model_dump(by_alias=True, exclude_none=True)
        elif args.operation == "inventory":
            if request.path is None:
                parser.error("inventory requires path")
            value = read_inventory(request.path, request.cwd or Path.cwd()).model_dump(by_alias=True)
        elif args.operation == "report":
            if request.execution is None or request.context is None:
                parser.error("report requires execution and context")
            value = work_selection_report(request.execution, request.context).model_dump(mode="json")
        elif args.operation == "safe-path":
            value = safe_path(request.value or "")
        else:
            parser.error("unsupported operation")
        print(json.dumps(value))
        return 0
    except (OSError, ValueError, KeyError, argparse.ArgumentTypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
