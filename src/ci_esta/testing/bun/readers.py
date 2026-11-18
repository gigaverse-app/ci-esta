"""Whether a module's source can name repository inputs that Bun's import graph cannot see.

A match requires a reader-owned declaration (or makes the graph uncertain). Reads and inspection of
paths, computed imports and module-relative paths count; writes, temporary directories and removal
do not, so importing `node:fs` alone is not a read. Names that are also ordinary words (`stat`,
`access`, `watch`...) count only when they are reached through an `fs` binding the file creates.
"""

import re

_FS_MODULE = r"[\"'](?:node:)?fs(?:/promises)?[\"']"
_AMBIGUOUS = ("stat", "lstat", "access", "exists", "cp", "glob", "watch", "open")

_UNAMBIGUOUS = re.compile(
    r"\b(?:Bun\s*\.\s*(?:file|Glob)|import\s*\.\s*meta\s*\.\s*(?:glob|resolve)|require\s*\.\s*resolve"
    r"|(?:readFile|readdir|opendir|readlink|realpath|copyFile)(?:Sync)?|createReadStream|watchFile"
    rf"|(?:{'|'.join(_AMBIGUOUS)})Sync)\b"
    # A computed specifier: the module is chosen at runtime.
    r"|\b(?:import|require)\s*\(\s*(?![\"'])[^\s)]"
    # Module-relative paths: how a reader names a sibling to read, execute or start as a worker.
    r"|\bnew\s+URL\s*\([^)]*\bimport\s*\.\s*meta\s*\.\s*url\b"
    r"|\bimport\s*\.\s*meta\s*\.\s*(?:dir|dirname|filename|path)\b|\b__(?:dirname|filename)\b"
    r"|\bnew\s+Worker\s*\(\s*[\"'`]"
)
#: `import fs from "fs"`, `import * as fs from "fs"`, `const fs = require("fs")`, `= await import("fs")`.
_NAMESPACE = re.compile(
    rf"\bimport\s+(?:\*\s+as\s+)?(\w+)\s*(?:,\s*\{{[^}}]*\}}\s*)?from\s*{_FS_MODULE}"
    rf"|\b(\w+)\s*=\s*(?:require|await\s+import)\s*\(\s*{_FS_MODULE}\s*\)"
)
#: `import {stat} from "fs"`, `const {stat} = require("fs")`, `const {stat} = await import("fs")`.
_NAMED = re.compile(
    rf"\bimport\s*(?:\w+\s*,\s*)?\{{([^}}]*)\}}\s*from\s*{_FS_MODULE}"
    rf"|\{{([^}}]*)\}}\s*=\s*(?:require|await\s+import)\s*\(\s*{_FS_MODULE}"
)


def _fs_bindings(source: str) -> tuple[set[str], set[str]]:
    """Namespaces bound to `fs` (including `promises` re-exports) and the fs names imported directly."""
    namespaces = {"fs", "fsp", "promises"}
    namespaces.update(name for match in _NAMESPACE.findall(source) for name in match if name)
    named: set[str] = set()
    for match in _NAMED.findall(source):
        for item in ",".join(match).split(","):
            parts = item.replace(":", " as ").split()
            if not parts:
                continue
            imported, local = parts[0], parts[-1]
            if imported == "promises":
                namespaces.add(local)
            named.add(imported)
    return namespaces, named


def names_untracked_inputs(source: str) -> bool:
    if _UNAMBIGUOUS.search(source):
        return True
    namespaces, named = _fs_bindings(source)
    if named & set(_AMBIGUOUS):
        return True
    members = "|".join(re.escape(name) for name in sorted(namespaces))
    return re.search(rf"\b(?:{members})\s*\.\s*(?:promises\s*\.\s*)?(?:{'|'.join(_AMBIGUOUS)})\s*\(", source) is not None
