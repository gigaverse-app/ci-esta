"""Advisory Lean planning and measurement tools."""

import argparse
import subprocess
from pathlib import Path

from ci_esta.lean import preflight, queue_report, retry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci-esta-lean", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("preflight", "Plan a Lean diff and prioritize previous failures"),
        ("queue", "Measure GitHub Actions Lake jobs and the live queue"),
        ("retry", "Print a Lake retry command from a failed build log"),
    ):
        commands.add_parser(command, help=help_text, add_help=False)
    statements = commands.add_parser("statements", help="Find equal elaborated theorem statements")
    statements.add_argument("modules", nargs="+")
    statements.add_argument("--lake", default="lake")
    compare = commands.add_parser("compare", help="Compare named declaration types in two built Lean modules")
    compare.add_argument("before", type=Path, help="Baseline .olean file")
    compare.add_argument("after", type=Path, help="Refactored .olean file")
    compare.add_argument("declarations", nargs="+", help="Fully qualified declaration names")
    compare.add_argument("--lean", default="lean", help="Compiler that built both files")
    parsed, rest = parser.parse_known_args(argv)
    if parsed.command == "preflight":
        preflight.main(rest)
    elif parsed.command == "queue":
        queue_report.main(rest)
    elif parsed.command == "retry":
        return retry.main(rest)
    else:
        if rest:
            parser.error(f"unrecognized arguments: {' '.join(rest)}")
        scanner = Path(__file__).with_name("TheoremMatches.lean")
        if parsed.command == "compare":
            command = [
                parsed.lean,
                "--run",
                str(scanner),
                "--compare",
                str(parsed.before),
                str(parsed.after),
                *parsed.declarations,
            ]
        else:
            command = [parsed.lake, "env", "lean", "--run", str(scanner), *parsed.modules]
        try:
            return subprocess.run(command, check=False).returncode
        except OSError as error:
            parser.exit(1, f"{error}\n")
    return 0
