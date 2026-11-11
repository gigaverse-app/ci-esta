"""Check the design, including expected counterexamples. Requires Node and Java 21.

All checker output stays in a temporary directory, never in the source tree.
No application code or GitHub workflows are executed by this command.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUINT = "@informalsystems/quint@0.33.1"


def main() -> None:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise SystemExit("Install Node.js 22+ and Java 21 before checking the models")
    with tempfile.TemporaryDirectory(prefix="ci-esta-models-") as temporary:
        work = Path(temporary)
        config = work / "tlc.json"
        config.write_text('{"maxHeap":"-Xmx4G","workers":4}')

        def check(model: str, command: str, *options: str, counterexample: bool = False) -> None:
            args = [
                npm,
                "exec",
                "--yes",
                f"--package={QUINT}",
                "--",
                "quint",
                command,
                str(ROOT / f"{model}.qnt"),
                *options,
            ]
            if command == "verify":
                args.extend(["--backend", "tlc", "--tlc-config", str(config)])
            result = subprocess.run(
                args,
                cwd=work,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=300,
            )
            output = result.stdout
            # A tooling/parser failure must never count as a successful negative control.
            violation = "Invariant " in output and "is violated" in output
            violation = violation or "Temporal properties were violated" in output
            violation = violation or ("Temporal property " in output and "was violated" in output)
            passed = (result.returncode != 0 and violation) if counterexample else result.returncode == 0
            label = f"{model}: {command} {' '.join(options)}"
            print(f"{'PASS' if passed else 'FAIL'} {label}", flush=True)
            for line in output.splitlines():
                if "distinct states found" in line or " passing " in line or "Error:" in line:
                    print(f"  {line}", flush=True)
            if not passed:
                print(output, flush=True)
                raise SystemExit(1)

        for model in ["merged_pr_evidence", "timing_publication"]:
            check(model, "typecheck")
            check(model, "test", "--backend", "typescript", "--max-samples", "1")
            check(model, "verify", "--invariant", "safety")
        check(
            "merged_pr_evidence",
            "verify",
            "--init",
            "readyInit",
            "--step",
            "recoveryStep",
            "--temporal",
            "eventuallyPromoted",
        )
        for step, invariant in [
            ("brokenOpenStep", "onlyMergedGreen"),
            ("brokenFallbackStep", "lastAttemptOnly"),
            ("brokenReuseStep", "timingsNeverGrantReuse"),
        ]:
            check("merged_pr_evidence", "verify", "--step", step, "--invariant", invariant, counterexample=True)
        check("timing_publication", "verify", "--step", "brokenStep", "--invariant", "safety", counterexample=True)
        check(
            "merged_pr_evidence",
            "verify",
            "--init",
            "readyInit",
            "--step",
            "recoveryStep",
            "--temporal",
            "noRetryGuarantee",
            counterexample=True,
        )


if __name__ == "__main__":
    main()
