#!/usr/bin/env bash
set -euo pipefail
[[ ${SERVICE_NAME:-} =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]+$ ]] || { echo 'Invalid service name' >&2; exit 1; }
case "${SERVICE_PHASE:-start}" in
  warm)
    test -n "${SERVICE_IMAGE:-}"
    # This is advisory: start still pulls a missing image and fails on error.
    # No container is created until start, so cancelled setup cannot leak one.
    docker pull "$SERVICE_IMAGE" >"${RUNNER_TEMP:?}/$SERVICE_NAME-pull.log" 2>&1 </dev/null &
    disown
    ;;
  start)
    test -n "${SERVICE_IMAGE:-}"
    test -n "${SERVICE_HEALTH_COMMAND:-}"
    [[ ${SERVICE_TIMEOUT:-} =~ ^[1-9][0-9]*$ ]] || { echo 'Invalid health timeout' >&2; exit 1; }
    args=(run -d --name "$SERVICE_NAME")
    while IFS= read -r port; do
      [[ -z "$port" ]] || args+=(-p "$port")
    done <<< "${SERVICE_PORTS:-}"
    args+=(--health-cmd "$SERVICE_HEALTH_COMMAND" --health-interval 1s --health-timeout 1s --health-retries "$SERVICE_TIMEOUT")
    docker "${args[@]}" "$SERVICE_IMAGE"
    deadline=$((SECONDS + SERVICE_TIMEOUT))
    until [[ $(docker inspect --format '{{.State.Health.Status}}' "$SERVICE_NAME") == healthy ]]; do
      state=$(docker inspect --format '{{.State.Status}}' "$SERVICE_NAME")
      if [[ "$state" != running || $SECONDS -ge $deadline ]]; then
        docker logs "$SERVICE_NAME" >&2 || true
        echo "Service $SERVICE_NAME did not become healthy (state=$state)" >&2
        exit 1
      fi
      sleep 1
    done
    ;;
  stop)
    # Consumers call stop with always(), including when start was never reached.
    if docker container inspect "$SERVICE_NAME" >/dev/null 2>&1; then
      docker rm -f "$SERVICE_NAME"
    fi
    ;;
  *) echo 'Expected service phase warm, start or stop' >&2; exit 1 ;;
esac
