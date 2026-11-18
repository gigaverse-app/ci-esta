"""`ci-esta bun-declarations`: what to declare, delete and merge, listed together in one run."""

import shutil
from pathlib import Path

from ci_esta.git import tracked_files
from ci_esta.testing.bun.discovery import test_files
from ci_esta.testing.bun.graph import audit_declarations, test_preloads
from ci_esta.testing.bun.models import DeclarationAudit

GUIDE = "https://ci-esta.readthedocs.io/en/latest/docs/dependency-declarations/"


def render(audit: DeclarationAudit) -> str:
    sections: list[str] = []
    if audit.undeclared:
        sections.append(
            "Undeclared readers: selection runs the full suite until each one is declared.\n"
            + "\n".join(f"  {path}" for path in audit.undeclared)
        )
    if audit.unreached:
        sections.append(
            "Declared readers no test reaches: these declarations change no selection; delete them.\n"
            + "\n".join(f"  {path}" for path in audit.unreached)
        )
    if audit.crowded:
        sections.append(
            "Directories with several sidecars: merge each into one <directory>/.gv-dependencies.yaml.\n"
            + "\n".join(f"  {directory}/ ({len(paths)} sidecars)" for directory, paths in audit.crowded.items())
        )
    if not sections:
        return "Declarations are complete: every reachable reader is declared, reached and grouped."
    return "\n\n".join([*sections, f"Authoring rules: {GUIDE}"])


def report(repo: Path, roots: list[str], bun: str, as_json: bool) -> int:
    """Exit 2 while a reachable reader is undeclared: selection cannot narrow until it is."""
    files = set(tracked_files(repo))
    tests = set(test_files(tracked_files(repo, *roots) if roots else files))
    entries = sorted(tests | set(test_preloads(repo, files)))
    audit = audit_declarations(repo, entries, shutil.which(bun) or bun, files)
    print(audit.model_dump_json(indent=2) if as_json else render(audit))
    return 2 if audit.undeclared else 0
