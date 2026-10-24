#!/usr/bin/env bash
# Keep the consumer cwd for relative report paths, and its environment untouched.
set -euo pipefail
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/reporting-runtime.sh" "$@"
