#!/usr/bin/env bash
set -euo pipefail
client="$(basename "$0")"
case "$client" in pg_dump|pg_restore|psql) ;; *) exit 1 ;; esac
image="$(cat "$(dirname "$0")/image")"
arguments=(run --rm -i --network host --user "$(id -u):$(id -g)"
  --volume "${GITHUB_WORKSPACE:?}:$GITHUB_WORKSPACE"
  --volume "${RUNNER_TEMP:?}:$RUNNER_TEMP" --workdir "$PWD")
# Forward names only. Passwords stay in the environment, never in Docker argv.
for variable in ${!PG@}; do
  arguments+=(--env "$variable")
done
exec docker "${arguments[@]}" --entrypoint "$client" "$image" "$@"
