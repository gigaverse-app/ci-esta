#!/usr/bin/env bash
set -euo pipefail
tool_dir="$RUNNER_TEMP/shared-semgrep-bin"
mkdir -p "$tool_dir"
cat > "$tool_dir/semgrep" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
exec docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$PWD:/src" --workdir /src \
  --env SEMGREP_SEND_METRICS=off --env HOME=/tmp \
  semgrep/semgrep:1.185.0@sha256:67518c174185a2043fdbed16c70631b79209499b3671178e7194379b48295a0d \
  semgrep "$@"
SCRIPT
chmod +x "$tool_dir/semgrep"
echo "$tool_dir" >> "$GITHUB_PATH"
