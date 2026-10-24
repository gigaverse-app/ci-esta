#!/usr/bin/env bash
# Share locked dependencies across reporting actions, never the consumer venv.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export UV_PROJECT_ENVIRONMENT="${RUNNER_TEMP:?}/ci-esta-reporting-runtime"
export PYTHONPATH="$root/src"
uv sync --project "$root" --locked --no-dev --no-install-project --extra selection --python 3.14
if [[ "${1:-}" == --prepare ]]; then
  printf '%s\n' "$UV_PROJECT_ENVIRONMENT/bin/python"
else
  exec "$UV_PROJECT_ENVIRONMENT/bin/python" -m "$@"
fi
