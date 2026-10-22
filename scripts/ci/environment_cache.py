"""Portable, credential-free environment cache contracts for the composite action."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def sync_arguments(value: str) -> list[str]:
    tokens = shlex.split(value)
    flags = {"--all-packages", "--all-groups", "--all-extras", "--no-default-groups", "--no-install-project"}
    options = {"--extra", "--group", "--only-group", "--no-group", "--package", "--no-install-package"}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in flags:
            index += 1
        elif token in options and index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
            index += 2
        else:
            raise ValueError(f"Unsupported sync argument {token}; use working-directory/python-version inputs")
    return tokens


def identity(*, manifests: str, sync_args: str, root: Path, variant: str) -> str:
    if not manifests:
        raise ValueError("No lock/manifests matched; refusing an incomplete environment identity")
    contract = [manifests, sync_arguments(sync_args), str(root.resolve()), variant,
                platform.system(), platform.machine(), sys.version, sys.executable,
                hashlib.sha256(Path(__file__).read_bytes()).hexdigest()]
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


def validate(root: Path) -> bool:
    venv = root.resolve() / ".venv"
    if venv.is_symlink():
        venv.unlink()
        return False
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        probe = subprocess.run([str(python), "-c", "import json,sys; print(json.dumps([sys.version,sys.prefix]))"],
                               capture_output=True, text=True, timeout=15, check=True)
        version, prefix = json.loads(probe.stdout)
        if version == sys.version and Path(prefix).resolve() == venv:
            return True
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if venv.is_dir():
        shutil.rmtree(venv)
    elif venv.exists():
        venv.unlink()
    return False


def main() -> None:
    root = Path(os.environ.get("CACHE_WORKING_DIRECTORY", ".")).resolve()
    args = os.environ.get("CACHE_SYNC_ARGS", "")
    if sys.argv[1] == "identity":
        key = identity(manifests=os.environ.get("CACHE_MANIFESTS", ""), sync_args=args,
                       root=root, variant=os.environ.get("CACHE_VARIANT", ""))
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"key={key}\n")
    else:
        usable = validate(root)
        print(f"Restored environment usable: {usable}; verifying locked dependencies")
        # Always synchronize: restored environments are acceleration, never validation receipts.
        subprocess.run(["uv", "sync", "--locked", "--python", sys.executable, *sync_arguments(args)],
                       cwd=root, check=True)


if __name__ == "__main__":
    main()
