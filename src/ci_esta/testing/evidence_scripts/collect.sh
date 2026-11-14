#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.." && pwd)"
exec bash "$root/scripts/ci/tool-runtime.sh" ci_esta.testing.collect_changes
