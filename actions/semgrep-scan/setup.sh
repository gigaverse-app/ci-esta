#!/usr/bin/env bash
set -euo pipefail
tool_dir="$RUNNER_TEMP/shared-semgrep-bin"
mkdir -p "$tool_dir"
cp "$(dirname "$0")/credential-rule-exclusions.txt" "$tool_dir/credential-rule-exclusions.txt"
cat > "$tool_dir/semgrep" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
# Insert exact credential rule exclusions before any end-of-options marker.
if [ "${1:-}" = scan ]; then
  shift
  args=(scan)
  while IFS= read -r rule; do
    [ -z "$rule" ] || args+=(--exclude-rule "$rule")
  done < "$(dirname "$0")/credential-rule-exclusions.txt"
  set -- "${args[@]}" "$@"
fi
exec docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD:/src" --workdir /src \
  --env SEMGREP_SEND_METRICS=off --env HOME=/tmp \
  semgrep/semgrep:1.185.0@sha256:67518c174185a2043fdbed16c70631b79209499b3671178e7194379b48295a0d \
  semgrep "$@"
SCRIPT
chmod +x "$tool_dir/semgrep"
echo "$tool_dir" >> "$GITHUB_PATH"
