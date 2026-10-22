#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <command> [args...]" >&2
  exit 2
fi

if [ "${CI_TEST_RESOURCE_OBSERVABILITY:-false}" != "true" ]; then
  exec "$@"
fi

interval_seconds="${CI_TEST_RESOURCE_OBSERVABILITY_INTERVAL_SECONDS:-20}"
if ! [[ "$interval_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "CI_TEST_RESOURCE_OBSERVABILITY_INTERVAL_SECONDS must be a positive integer" >&2
  exit 2
fi

echo "[ci-test-resource] runner capacity"
echo "[ci-test-resource] nproc=$(nproc) getconf=$(getconf _NPROCESSORS_ONLN)"
lscpu | sed -n \
  '/^CPU(s):/p; /^Model name:/p; /^Thread(s) per core:/p; /^Core(s) per socket:/p'
for resource_file in cpu.max cpu.stat memory.max memory.current memory.events; do
  if [ -r "/sys/fs/cgroup/$resource_file" ]; then
    echo "[ci-test-resource] initial $resource_file"
    sed 's/^/[ci-test-resource]   /' "/sys/fs/cgroup/$resource_file"
  fi
done

resource_monitor() {
  while true; do
    echo "[ci-test-resource] snapshot utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) load=$(cat /proc/loadavg)"
    for resource_file in cpu.stat memory.current memory.events; do
      if [ -r "/sys/fs/cgroup/$resource_file" ]; then
        tr '\n' ' ' < "/sys/fs/cgroup/$resource_file" \
          | sed "s/^/[ci-test-resource] $resource_file /"
        echo
      fi
    done
    echo "[ci-test-resource] top processes"
    ps -eo pid,ppid,comm,%cpu,%mem,rss,etime --sort=-%cpu | head -10 || true
    if command -v docker >/dev/null 2>&1; then
      echo "[ci-test-resource] service containers"
      docker stats --no-stream \
        --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' || true
    fi
    sleep "$interval_seconds"
  done
}

# Separate process groups let cleanup reach sleep/docker children as well as
# their shell. Waiting on the command in the background lets Bash run signal
# traps immediately, instead of waiting for a stuck foreground command.
export -f resource_monitor
export interval_seconds
setsid bash -c resource_monitor &
resource_monitor_pid=$!
command_pid=
cleanup() {
  kill -- -"$resource_monitor_pid" 2>/dev/null || true
  wait "$resource_monitor_pid" 2>/dev/null || true
  if [ -n "$command_pid" ]; then
    kill -- -"$command_pid" 2>/dev/null || true
    wait "$command_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

set +e
setsid /usr/bin/time -v "$@" &
command_pid=$!
wait "$command_pid"
command_status=$?
set -e
command_pid=
cleanup
trap - EXIT

if [ -r /sys/fs/cgroup/cpu.stat ]; then
  echo "[ci-test-resource] final cpu.stat"
  sed 's/^/[ci-test-resource]   /' /sys/fs/cgroup/cpu.stat
fi
echo "[ci-test-resource] command status=$command_status"
exit "$command_status"
