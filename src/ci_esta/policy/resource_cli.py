"""Resolve declared prerequisites into placements without reading credentials."""

import argparse
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from ci_esta.policy.models import Contract, Requirement
from ci_esta.policy.resources import Placement, Resource, placement_for, resolve_pins


class ResourceDecision(Contract):
    status: Literal["resolved", "unavailable"]
    reasons: tuple[str, ...]
    placement: Placement | None


class ResourcePlan(Contract):
    schema_version: Literal["ci-esta/test-resources/v1"] = "ci-esta/test-resources/v1"
    work: dict[str, ResourceDecision]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, help="JSON resource-name to Resource mapping")
    parser.add_argument("--requirements", required=True, help="JSON work-id to Requirement list mapping")
    parser.add_argument("--available", default="", help="Comma-separated available credential NAMES, never values")
    parser.add_argument("--environment", default="any")
    parser.add_argument("--cluster", action="store_true", help="Resolve for a target that provisions cluster config")
    parser.add_argument("--output", default="test-resource-plan.json")
    args = parser.parse_args(argv)
    destination = Path(args.output)
    destination.unlink(missing_ok=True)
    registry = TypeAdapter(dict[str, Resource]).validate_json(Path(args.registry).read_text())
    requirements = TypeAdapter(dict[str, tuple[Requirement, ...]]).validate_json(Path(args.requirements).read_text())
    if any(key != resource.name for key, resource in registry.items()):
        raise ValueError("registry keys must equal resource names")
    context = {name.strip(): "available" for name in args.available.split(",") if name.strip()}
    decisions = {}
    for work_id, pins in requirements.items():
        providers, reasons = resolve_pins(
            pins, resources=registry, env_vars=context, active_env_scope=args.environment, cluster_mode=args.cluster
        )
        if not args.cluster and any(provider.cluster_internal for provider in providers):
            providers, reasons = resolve_pins(
                pins, resources=registry, env_vars=context, active_env_scope=args.environment, cluster_mode=True
            )
        decisions[work_id] = ResourceDecision(
            status="unavailable" if reasons else "resolved",
            reasons=tuple(reasons),
            placement=None if reasons else placement_for(providers),
        )
    result = ResourcePlan(work=decisions)
    destination.write_text(result.model_dump_json(indent=2) + "\n")
    return int(any(item.status == "unavailable" for item in decisions.values()))


if __name__ == "__main__":
    raise SystemExit(main())
