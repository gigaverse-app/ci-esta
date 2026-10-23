#!/usr/bin/env bash
set -euo pipefail
[[ "${RUNNER_OS:?}" == Linux ]] || { echo 'postgres-client requires a Linux Docker runner' >&2; exit 1; }
[[ -n "${CLIENT_IMAGE:-}" && "$CLIENT_IMAGE" != -* && "$CLIENT_IMAGE" != *$'\n'* ]] || exit 1
directory="$(mktemp -d "$RUNNER_TEMP/ci-esta-postgres.XXXXXX")"
printf '%s' "$CLIENT_IMAGE" > "$directory/image"
for client in pg_dump pg_restore psql; do
  cp "$CLIENT_ACTION/client.sh" "$directory/$client"
  chmod +x "$directory/$client"
done
printf '%s\n' "$directory" >> "$GITHUB_PATH"
