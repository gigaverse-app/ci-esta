#!/usr/bin/env bash
# Full pull+unpack through a disposable Docker daemon, never the host image store.
set -euo pipefail
evidence=${1:?evidence directory required}
inputs="$evidence/pull-plan.json" # Validated, resolved once by the CLI before resource acquisition.
repository=$(jq -er .repository "$inputs")
registry=${repository%%/*}
prefix=$(jq -er .prefix "$inputs")
dind=$(jq -er .dind "$inputs")
samples=$(jq -er '.samples' "$inputs")
architecture=$(jq -er '.architecture // "amd64"' "$inputs")
# Each subshell owns exactly one daemon and volume. Register cleanup immediately
# after acquisition so failed starts, logins and pulls cannot leak resources.
probe_arm() (
  arm=$1
  sample=$2
  daemon="$prefix-pull-$arm-$sample"
  volume="$daemon-store"
  volume_created=false
  daemon_created=false
  cleanup() {
    status=$?
    if [[ "$daemon_created" == true ]]; then docker rm -f "$daemon" >/dev/null || status=1; fi
    if [[ "$volume_created" == true ]]; then docker volume rm "$volume" >/dev/null || status=1; fi
    exit "$status"
  }
  trap cleanup EXIT
  # Refuse to adopt an existing volume: it would invalidate the empty-store
  # control and cleanup could delete resources belonging to another drill.
  if docker volume inspect "$volume" >/dev/null 2>&1; then
    echo "Pull probe volume already exists" >&2; exit 1
  fi
  docker volume create "$volume" >/dev/null
  volume_created=true
  docker create --privileged --name "$daemon" --env DOCKER_TLS_CERTDIR= \
    --volume "$volume:/var/lib/docker" "$dind" --storage-driver=overlay2 >/dev/null
  daemon_created=true
  docker start "$daemon" >/dev/null
  ready=false
  for ((attempt=0; attempt<30; attempt++)); do
    if docker exec "$daemon" docker info >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
  done
  [[ "$ready" == true ]] || { docker logs "$daemon"; exit 1; }
  docker exec "$daemon" docker info --format '{{json .}}' > "$evidence/pull-$arm-$sample-daemon.json"
  aws ecr get-login-password | docker exec -i "$daemon" docker login --username AWS --password-stdin "$registry" >/dev/null
  # Preserve caller-specified scenario names and order in all evidence.
  # Each arm starts empty; later scenarios reuse that exact store.
  while IFS= read -r scenario; do
    image=$(jq -er --arg arm "$arm" --arg scenario "$scenario" '.images[$arm][$scenario]' "$inputs")
    begin=$(date +%s.%N)
    timeout 300 docker exec "$daemon" docker pull "$image" > "$evidence/pull-$arm-$scenario-$sample.log" 2>&1
    end=$(date +%s.%N)
    seconds=$(awk -v begin="$begin" -v end="$end" 'BEGIN {printf "%.3f", end-begin}')
    docker exec "$daemon" docker image inspect "$image" > "$evidence/pull-$arm-$scenario-$sample-inspect.json"
    if (( sample == 0 )); then
      docker buildx imagetools inspect "$image" --raw > "$evidence/$arm-$scenario-index.json"
      if jq -e '.layers' "$evidence/$arm-$scenario-index.json" >/dev/null; then
        cp "$evidence/$arm-$scenario-index.json" "$evidence/$arm-$scenario-manifest.json"
      else
        platform=$(jq -er --arg arch "$architecture" \
          '[.manifests[] | select(.platform.os=="linux" and .platform.architecture==$arch)] | select(length==1) | .[0].digest' \
          "$evidence/$arm-$scenario-index.json")
        docker buildx imagetools inspect "$repository@$platform" --raw > "$evidence/$arm-$scenario-manifest.json"
      fi
    fi
    jq -cn --arg arm "$arm" --arg scenario "$scenario" --argjson sample "$sample" --argjson seconds "$seconds" \
      --arg image "$image" '{arm:$arm,scenario:$scenario,sample:$sample,seconds:$seconds,image:$image}' \
      | tee -a "$evidence/pulls.jsonl"
  done < <(jq -r ' .sequence[]' "$inputs")
)
for ((sample=0; sample<samples; sample++)); do
  arms=(baseline candidate)
  if (( sample % 2 )); then arms=(candidate baseline); fi
  for arm in "${arms[@]}"; do
    probe_arm "$arm" "$sample"
  done
done
