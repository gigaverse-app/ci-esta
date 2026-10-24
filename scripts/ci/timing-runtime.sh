#!/usr/bin/env bash
# Keep the consumer cwd for relative report paths, and its environment untouched.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export UV_PROJECT_ENVIRONMENT="${RUNNER_TEMP:?}/ci-esta-timing-runtime"
export PYTHONPATH="$root/src"
uv sync --project "$root" --locked --no-dev --no-install-project --python 3.14
exec uv run --project "$root" --no-sync python -m "$@"
