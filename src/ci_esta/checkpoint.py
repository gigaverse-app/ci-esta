"""Dispatch full-validation entry points without keeping a coordinator runner idle."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator

from ci_esta.ci_observability.github import GitHubActionsClient, WorkflowDispatch
from ci_esta.github_outputs import append_outputs


class Checkpoint(WorkflowDispatch):
    ref: str = ""
    workflows: list[str] = Field(default_factory=lambda: ["ci.yml"])

    @field_validator("workflows")
    @classmethod
    def valid_workflows(cls, value: list[str]) -> list[str]:
        if not value or len(value) != len(set(value)) or any(
            not re.fullmatch(r"[\w.-]+\.ya?ml", name) for name in value
        ):
            raise ValueError("workflows must be a nonempty list of unique workflow filenames")
        return value


def dispatch(client: GitHubActionsClient, config: Checkpoint, *, dry_run: bool = False) -> Checkpoint:
    ref = config.ref or client.default_branch()
    # Validate every target before the first mutation. Target workflows own full execution.
    for workflow in config.workflows:
        source = client.workflow_source(workflow, ref)
        events = source.get("on", source.get(True))
        if isinstance(events, str):
            events = {events: None}
        elif isinstance(events, list):
            events = dict.fromkeys(events)
        if not isinstance(events, dict) or "workflow_dispatch" not in events:
            raise ValueError(f"{workflow}: workflow_dispatch is required")
        declarations = (events["workflow_dispatch"] or {}).get("inputs", {})
        unknown = config.inputs.keys() - declarations.keys()
        if unknown:
            raise ValueError(f"{workflow}: unknown inputs: {', '.join(sorted(unknown))}")
        for name, declaration in declarations.items():
            if declaration.get("required") and "default" not in declaration and name not in config.inputs:
                raise ValueError(f"{workflow}: required input {name!r} is missing")
            if name in config.inputs:
                value = config.inputs[name]
                kind = declaration.get("type", "string")
                if kind == "boolean" and not isinstance(value, bool):
                    raise ValueError(f"{workflow}: input {name!r} must be a boolean")
                if kind == "choice" and value not in declaration.get("options", []):
                    raise ValueError(f"{workflow}: input {name!r} is not an allowed choice")
    request = WorkflowDispatch(ref=ref, inputs=config.inputs)
    if not dry_run:
        for workflow in config.workflows:
            client.dispatch_workflow(workflow, request)
            print(f"Dispatch accepted: {workflow} at {ref}", flush=True)
    return config.model_copy(update={"ref": ref})


def workflow_document(config: Checkpoint, cron: str) -> dict[str, Any]:
    """The schedule belongs to the adopter; runtime behavior stays in the shared action."""
    return {
        "name": "Weekly full checkpoint",
        "on": {"schedule": [{"cron": cron}], "workflow_dispatch": None},
        "permissions": {"contents": "read", "actions": "write"},
        "concurrency": {"group": "weekly-full-checkpoint", "cancel-in-progress": False},
        "jobs": {"dispatch": {"runs-on": "ubuntu-latest", "timeout-minutes": 5, "steps": [{
            "uses": "gigaverse-app/ci-esta/actions/weekly-checkpoint@v1",
            "with": {"workflows": json.dumps(config.workflows), "ref": config.ref,
                     "workflow-inputs": json.dumps(config.inputs)},
        }]}},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "init"])
    parser.add_argument("--workflows", default=os.environ.get("CHECKPOINT_WORKFLOWS", '["ci.yml"]'))
    parser.add_argument("--ref", default=os.environ.get("CHECKPOINT_REF", ""))
    parser.add_argument("--inputs", default=os.environ.get("CHECKPOINT_INPUTS", "{}"))
    parser.add_argument("--dry-run", action="store_true", default=os.environ.get("CHECKPOINT_DRY_RUN") == "true")
    parser.add_argument("--cron", default="17 3 * * 1")
    parser.add_argument("--output", type=Path, default=Path(".github/workflows/weekly-checkpoint.yml"))
    args = parser.parse_args(argv)
    config = Checkpoint(workflows=json.loads(args.workflows), ref=args.ref, inputs=json.loads(args.inputs))
    if args.command == "init":
        document = yaml.safe_dump(workflow_document(config, args.cron), sort_keys=False)
        if args.dry_run:
            print(document)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(document)
            print(f"Created {args.output}; review full-run behavior in each target before merging.")
        return 0
    client = GitHubActionsClient.from_environment()
    assert client is not None
    try:
        result = dispatch(client, config, dry_run=args.dry_run)
    finally:
        client.close()
    append_outputs(ref=result.ref, workflows=json.dumps(result.workflows), dispatched=not args.dry_run)
    print("Preflight passed." if args.dry_run else "Dispatch complete. Target workflow runs report validation results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
