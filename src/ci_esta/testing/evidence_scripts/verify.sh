#!/usr/bin/env bash
set -euo pipefail

# Receipts must be written by ci_esta.testing.pytest_completion, not by
# a shell exit-code echo: pytest --maxfail also exits 1 without finishing.
# JUNIT_NAME_TEMPLATE and EVIDENCE_DIRECTORY adapt consumer artifact layouts.
[[ "$PLAN_SHARD_COUNT" =~ ^[1-9][0-9]*$ ]]
first="${PLAN_FIRST_SHARD:-1}"
last="${PLAN_LAST_SHARD:-$PLAN_SHARD_COUNT}"
[[ "$first" =~ ^[1-9][0-9]*$ && "$last" =~ ^[1-9][0-9]*$ ]]
(( first <= last && last <= PLAN_SHARD_COUNT ))
cd "${EVIDENCE_DIRECTORY:-.}"
template="${JUNIT_NAME_TEMPLATE:-}"
if [ -z "$template" ]; then template='junit-group-{shard}.xml'; fi
for ((shard = first; shard <= last; shard++)); do
  report="${template//\{shard\}/$shard}"
  [ -s "$report" ]
  [ -s "pytest-status-group-${shard}" ]
  status="$(< "pytest-status-group-${shard}")"
  case "$status" in
    0|1) ;;
    5) [ "$PLAN_MODE" = scoped ] ;;
    *) exit 1 ;;
  esac
done
