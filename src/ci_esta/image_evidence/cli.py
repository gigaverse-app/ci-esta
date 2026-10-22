"""Host-side commands for reproducible, credential-safe image evidence."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from ci_esta.image_evidence import parse_digest, sanitize
from ci_esta.image_evidence.nodes import NodeProbeConfig, run_node_probes
from ci_esta.image_evidence.observer import write_observer
from ci_esta.image_evidence.plan import prepare_pull_plan, prepare_sequence


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    digest = commands.add_parser("digest", help="Resolve an immutable image identity using Buildx")
    digest.add_argument("image")
    artifacts = commands.add_parser("sanitize", help="Redact an artifact tree before publication")
    artifacts.add_argument("directory", type=Path)
    artifacts.add_argument("--required-secret-env", action="append", required=True)
    pulls = commands.add_parser("pulls", help="Measure pulls in disposable overlay2 Docker daemons")
    pulls.add_argument("directory", type=Path)
    observer = commands.add_parser("observer", help="Freeze a standalone consumer probe and shared runtime inspector")
    observer.add_argument("adapter", type=Path)
    observer.add_argument("output", type=Path)
    nodes = commands.add_parser("nodes", help="Observe immutable images on explicitly selected Kubernetes nodes")
    nodes.add_argument("directory", type=Path)
    nodes.add_argument("--observer", type=Path, required=True)
    nodes.add_argument("--context", required=True)
    nodes.add_argument("--namespace", required=True)
    nodes.add_argument("--node", action="append", required=True)
    nodes.add_argument("--run", required=True)
    nodes.add_argument("--probe-arg", action="append", default=[])
    sequence = commands.add_parser("sequence", help="Prepare a named independent pull sequence")
    sequence.add_argument("directory", type=Path)
    sequence.add_argument("name")
    sequence.add_argument("scenarios", nargs="+")
    args = parser.parse_args(argv)
    if args.operation == "digest":
        report = subprocess.check_output(["docker", "buildx", "imagetools", "inspect", args.image], text=True)
        print(parse_digest(report))
    elif args.operation == "sanitize":
        required = [os.environ.get(name, "") for name in args.required_secret_env]
        if not all(required):
            parser.error("Required build secret is unavailable for artifact redaction")
        secrets = [value.encode() for value in required]
        secrets.extend(
            value.encode()
            for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "GITHUB_TOKEN")
            if (value := os.environ.get(name))
        )
        print(f"Sanitized {sanitize(args.directory, secrets)} evidence files")
    elif args.operation == "nodes":
        plan = prepare_pull_plan(args.directory)
        config = NodeProbeConfig(
            context=args.context,
            namespace=args.namespace,
            nodes=tuple(args.node),
            run=args.run,
            probe_args=tuple(args.probe_arg),
        )
        run_node_probes(args.directory, plan, config, args.observer)
    elif args.operation == "sequence":
        print(prepare_sequence(args.directory, args.name, tuple(args.scenarios)))
    elif args.operation == "observer":
        print(write_observer(args.adapter, args.output))
    else:
        plan = prepare_pull_plan(args.directory)
        snapshot = args.directory / "pull-plan.json"
        snapshot.write_text(plan.model_dump_json(indent=2) + "\n")
        subprocess.run(["bash", str(Path(__file__).with_name("pulls.sh")), str(args.directory)], check=True)
