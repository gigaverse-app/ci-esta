#!/usr/bin/env bash
# Share locked dependencies across CI-esta actions, never the consumer venv.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export UV_PROJECT_ENVIRONMENT="${RUNNER_TEMP:?}/ci-esta-reporting-runtime"
export PYTHONPATH="$root/src"
uv sync --project "$root" --locked --no-dev --no-install-project --extra selection --python 3.14
# Let uv resolve the platform's interpreter layout from the environment it owns.
runtime=(uv run --project "$root" --no-sync --no-env-file python)
if [[ "${1:-}" == --prepare ]]; then
  "${runtime[@]}" -c 'import sys; print(sys.executable)'
else
  exec "${runtime[@]}" -m "$@"
fi
