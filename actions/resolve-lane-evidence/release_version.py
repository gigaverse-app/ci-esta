"""Recognize only a root Python project's Release Please version transition."""
import json
import re
import subprocess
import sys
import tomllib


def git(*args):
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL)


def version_line(text, version):
    pattern = r'(?m)^(version\s*=\s*)"' + re.escape(version) + r'"(\s*(?:#.*)?)$'
    result, count = re.subn(pattern, r'\1"<project-version>"\2', text, count=1)
    if count != 1:
        raise ValueError("Unrecognized version assignment")
    return result


def project_text(text, version):
    parts = re.split(r"(?m)^(\[project\]\s*\n)", text)
    if len(parts) != 3:
        raise ValueError("Missing project section")
    section = re.split(r"(?m)(?=^\[)", parts[2], maxsplit=1)
    section[0] = version_line(section[0], version)
    return "".join(parts[:2]) + "".join(section)


def lock_text(text, name, version):
    parts = re.split(r"(?m)(?=^\[\[package\]\])", text)
    found = 0
    for index, part in enumerate(parts[1:], 1):
        package = tomllib.loads(part)["package"][0]
        if package["name"] == name:
            if package.get("source") != {"editable": "."} or package["version"] != version:
                raise ValueError("Ambiguous root package")
            parts[index] = version_line(part, version)
            found += 1
    if found != 1:
        raise ValueError("Missing or duplicate root package")
    return "".join(parts)


def classify(base, head):
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        return {"version_only": False}
    git("merge-base", "--is-ancestor", base, head)
    if git("rev-parse", "HEAD").strip() != head or git("status", "--porcelain", "--untracked-files=no").strip():
        return {"version_only": False}
    changes = git("diff", "--name-status", "--no-renames", base, head).splitlines()
    allowed = {"pyproject.toml", "uv.lock", ".release-please-manifest.json", "CHANGELOG.md"}
    if not changes:
        return {"version_only": False}
    for change in changes:
        status, name = change.split("\t")
        if status != "M" or name not in allowed:
            return {"version_only": False}
    manifests = {}
    values = []
    for ref in (base, head):
        files = {name: git("show", f"{ref}:{name}") for name in allowed - {"CHANGELOG.md"}}
        for name in files:
            if not git("ls-tree", ref, "--", name).startswith("100644 blob "):
                return {"version_only": False}
        project = tomllib.loads(files["pyproject.toml"])["project"]
        version = project["version"]
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            return {"version_only": False}
        manifest = json.loads(files[".release-please-manifest.json"])
        if manifest.get(".") != version:
            return {"version_only": False}
        manifest["."] = "<project-version>"
        values.append((version, project_text(files["pyproject.toml"], version),
                       lock_text(files["uv.lock"], project["name"], version), manifest))
        if ref == base:
            manifests = {name: files[name] for name in ("pyproject.toml", "uv.lock")}
    old, new = values
    if tuple(map(int, new[0].split("."))) <= tuple(map(int, old[0].split("."))) or old[1:] != new[1:]:
        return {"version_only": False}
    return {"version_only": True, "manifests": manifests, "version": new[0]}


if __name__ == "__main__":
    try:
        result = classify(*sys.argv[1:])
    except (ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        result = {"version_only": False}
    print(json.dumps(result))
