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
  semgrep/semgrep:latest@sha256:98c2572fced2474539fd27cab3207ebd8e95e4e7aab4c3b381fdc5e2641d9941 \
  semgrep "$@"
SCRIPT
chmod +x "$tool_dir/semgrep"
echo "$tool_dir" >> "$GITHUB_PATH"
