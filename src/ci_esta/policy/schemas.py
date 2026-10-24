"""Generate the public JSON schemas from the canonical runtime contracts."""

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from ci_esta.policy.models import ExecutionPlan, Policy, Request, Requirement, Work
from ci_esta.policy.resource_cli import ResourcePlan
from ci_esta.policy.resources import Resource


def schemas() -> dict[str, dict]:
    contracts = {
        "policy": Policy,
        "request": Request,
        "plan": ExecutionPlan,
        "inventory": tuple[Work, ...],
        "resource-registry": dict[str, Resource],
        "requirements": dict[str, tuple[Requirement, ...]],
        "resource-plan": ResourcePlan,
    }
    return {
        name: {"$schema": "https://json-schema.org/draft/2020-12/schema", **TypeAdapter(contract).json_schema()}
        for name, contract in contracts.items()
    }


if __name__ == "__main__":
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=True)
    for name, schema in schemas().items():
        (root / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
