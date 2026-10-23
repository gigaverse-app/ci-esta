#!/usr/bin/env bash
# Every path that cannot prove a narrower scope writes mode=full: the full check is always
# correct, only slower. The step itself never fails the job.
set -uo pipefail

full() {
  echo "::notice::Type-check scope: full; $1"
  {
    echo "mode=full"
    echo "reason=$1"
    echo "paths="
  } >> "$GITHUB_OUTPUT"
  exit 0
}

[ "${SCOPE_PROVEN:-false}" = true ] || full "base ${SCOPE_BASE:-?} has no successful clean-base check run"
git fetch --no-tags --depth=1 origin "$SCOPE_BASE" >/dev/null 2>&1 || full "could not fetch base $SCOPE_BASE"

args=(typecheck-scope --config "$SCOPE_CONFIG" --base "$SCOPE_BASE" --head "$SCOPE_HEAD"
      --checker-config "$SCOPE_CHECKER_CONFIG" --max-fraction "$SCOPE_MAX_FRACTION"
      --output typecheck-scope.txt --github-output typecheck-scope.env)
for pattern in $SCOPE_GLOBAL_INPUTS; do args+=(--global-input "$pattern"); done
rm -f typecheck-scope.txt typecheck-scope.env
export PYTHONPATH="$SHARED_ACTION_PATH/../../src${PYTHONPATH:+:$PYTHONPATH}"
# The same isolated parser runtime as test-impact, so both read the graph cache identically.
uv run --no-project --python 3.14 --with pydantic==2.13.4 --with pyyaml==6.0.3 --with "$(python3 "$SHARED_ACTION_PATH/../../scripts/ci/pytest_selective_requirement.py")" \
  python -m pytest_selective.impact_cli "${args[@]}" || full "scope computation failed"
[ -f typecheck-scope.env ] || full "scope computation wrote no result"

mode=$(sed -n 's/^mode=//p' typecheck-scope.env)
reason=$(sed -n 's/^reason=//p' typecheck-scope.env)
case "$mode" in
  scoped | none) ;;
  *) full "${reason:-no scope}" ;;
esac
delimiter="SCOPE_$(date +%s%N)"
{
  echo "mode=$mode"
  echo "reason=$reason"
  echo "paths<<$delimiter"
  cat typecheck-scope.txt 2>/dev/null
  echo "$delimiter"
} >> "$GITHUB_OUTPUT"
echo "::notice::Type-check scope: $mode; $reason"
