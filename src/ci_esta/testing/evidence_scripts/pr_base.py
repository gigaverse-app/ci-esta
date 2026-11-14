"""Pair the complete PR path list with its actual fork point, retaining uncertainty."""

import subprocess
import sys


def selection_base(base: str, head: str) -> str:
    """Use a unique merge base; unavailable or ambiguous history retains the conservative tree delta."""
    result = subprocess.run(["git", "merge-base", "--all", base, head], capture_output=True, text=True, check=False)
    ancestors = result.stdout.splitlines()
    # Main-only changes are not PR edits. A unique fork point preserves all PR
    # changes, including merge conflict resolutions, without reversing main.
    if result.returncode == 0 and len(ancestors) == 1:
        return ancestors[0]
    return base


if __name__ == "__main__":
    print(selection_base(*sys.argv[1:]))
