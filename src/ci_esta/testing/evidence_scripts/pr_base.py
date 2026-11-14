"""Pair the complete PR path list with its actual fork point, retaining uncertainty."""

import subprocess
import sys


def complete_pr_base(base: str, head: str) -> str:
    """Use a unique merge base; unavailable or ambiguous history retains the conservative tree delta."""
    result = subprocess.run(["git", "merge-base", "--all", base, head], capture_output=True, text=True, check=False)
    ancestors = result.stdout.splitlines()
    # INVARIANT (PR-head checkout only): complete PR changes start at the unique
    # fork point. Never apply this normalization to a previously tested tree or
    # a synthetic-merge baseline: those must retain their exact tested identity.
    # Unknown/ambiguous history retains the conservative caller-supplied base.
    if result.returncode == 0 and len(ancestors) == 1:
        return ancestors[0]
    return base


if __name__ == "__main__":
    print(complete_pr_base(*sys.argv[1:]))
