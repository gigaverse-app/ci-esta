#!/usr/bin/env bash
# Decide whether planning needs Bun installed, and which version file pins it.
#
# Writes `install=true|false` and, when installing, `version-file=PATH` (empty for the latest Bun) to
# GITHUB_OUTPUT. Bun is needed when the repository tracks Bun-style test files (the names CI-esta's Bun
# graph plans: `*.test.ts`, `*_spec.mjs`, ...) and no `bun` is on PATH.
set -euo pipefail

output="${GITHUB_OUTPUT:-/dev/stdout}"
if command -v bun >/dev/null 2>&1; then
  echo "install=false" >> "$output"
  exit 0
fi
if ! git ls-files -z | tr '\0' '\n' | grep -Eq '[._](test|spec)[.][cm]?[jt]sx?$'; then
  echo "install=false" >> "$output"
  exit 0
fi
version_file=""
if [[ -f .bun-version ]]; then
  version_file=.bun-version
elif [[ -f .tool-versions ]] && grep -Eq '^bun[[:space:]]' .tool-versions; then
  version_file=.tool-versions
elif [[ -f package.json ]] && grep -Eq '"packageManager"[[:space:]]*:[[:space:]]*"bun@' package.json; then
  version_file=package.json
fi
echo "install=true" >> "$output"
echo "version-file=$version_file" >> "$output"
