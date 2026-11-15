"""Read one verified immutable checkout object in the GitHub Git API wire shape.

This stdlib-only boundary is optional: no checkout, Python, or object means an
API fallback. It never fetches, reads working files, or decides evidence policy.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import TypedDict


class Commit(TypedDict):
    tree: dict[str, str]
    parents: list[dict[str, str]]


class Tree(TypedDict):
    tree: list[dict[str, str]]
    truncated: bool


class Blob(TypedDict):
    content: str
    encoding: str


def read_object(workspace: str, kind: str, sha: str) -> Commit | Tree | Blob:
    if kind not in {"commit", "tree", "blob"} or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected an immutable Git object")
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", workspace, "cat-file", "--batch"],
        input=f"{sha}\n".encode(), capture_output=True, check=True, timeout=5,
        # The protocol whitelist also prevents older Git versions, which do not
        # understand GIT_NO_LAZY_FETCH, from contacting a promisor remote.
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "", "GIT_TERMINAL_PROMPT": "0"},
    ).stdout
    header, body = result.split(b"\n", 1)
    oid, actual_kind, size = header.decode("ascii").split()
    raw = body[:-1]
    if oid != sha or actual_kind != kind or len(raw) != int(size) or not body.endswith(b"\n"):
        raise ValueError("Missing or mismatched Git object")
    if hashlib.sha1(f"{kind} {len(raw)}\0".encode() + raw).hexdigest() != sha:
        raise ValueError("Git content does not match its address")
    if kind == "blob":
        return {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"}
    if kind == "commit":
        headers = raw.split(b"\n\n", 1)[0].decode("utf-8", errors="replace").splitlines()
        return {"tree": {"sha": headers[0].removeprefix("tree ")}, "parents": [
            {"sha": line.removeprefix("parent ")} for line in headers if line.startswith("parent ")
        ]}
    entries: list[dict[str, str]] = []
    while raw:
        entry, rest = raw.split(b"\0", 1)
        mode, name = entry.split(b" ", 1)
        if len(rest) < 20:
            raise ValueError("Incomplete tree entry")
        mode_text = mode.decode("ascii").zfill(6)
        entry_type = "tree" if mode_text == "040000" else "commit" if mode_text == "160000" else "blob"
        entries.append({"mode": mode_text, "type": entry_type, "sha": rest[:20].hex(),
                        "path": name.decode("utf-8", errors="replace")})
        raw = rest[20:]
    return {"tree": entries, "truncated": False}


if __name__ == "__main__":
    try:
        value = read_object(*sys.argv[1:])
    except (OSError, ValueError, subprocess.SubprocessError):
        value = None
    print(json.dumps(value))
