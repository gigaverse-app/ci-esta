#!/usr/bin/env bash
set -euo pipefail

# A reusable SHA is adopted only together with a complete changed-input list.
# The selector must use the same base as this list, including on fetch failure.
base="${PR_BASE_SHA:-${BEFORE_SHA:-HEAD}}"
candidate="${PR_INCREMENTAL_BASE_SHA:-}"
reused_failures=false
if [ -z "$candidate" ] && [ -n "${FAILED_SHA:-}" ] &&
  [ "${FAILURES_COMPLETE:-}" = true ] && [ "${FAILURES_TRUNCATED:-}" = false ] &&
  [ "${FAILURES_STALE:-}" = 0 ] && [ "${FAILURES_INVALID:-}" = 0 ] &&
  [ "${FAILURES_COUNT:-0}" -gt 0 ] && [ -s "${FAILURES_FILE:-}" ]; then
  candidate="$FAILED_SHA"
  reused_failures=true
fi

# The PR base is always a sound base too. After main is merged into a validated PR, the
# tree delta above carries main's own changes and can reach every test, so the selector
# is offered both and keeps the smaller selection. Unresolved failures follow either base.
alternate=""
rm -f changed-files.txt changed-files.tmp alternate-changed-files.txt
if [ "$EVENT_NAME" = pull_request ]; then
  if [ -n "$candidate" ] && git fetch --no-tags --depth=1 origin "$candidate" &&
    git diff --no-renames --name-only "$candidate" "$CURRENT_SHA" > changed-files.tmp; then
    # INVARIANT: retain all imported changes and merge conflict resolutions;
    # intersecting this tree delta with PR paths could hide changed dependencies.
    if [ "$reused_failures" = true ]; then
      cat "$FAILURES_FILE" >> changed-files.tmp
    fi
    sort -u changed-files.tmp > changed-files.txt
    base="$candidate"
    if [ -n "${PR_BASE_SHA:-}" ] && [ "$PR_BASE_SHA" != "$candidate" ]; then
      alternate="$PR_BASE_SHA"
      {
        if [ -f complete-pr-paths.txt ]; then cat complete-pr-paths.txt; fi
        if [ "$reused_failures" = true ]; then cat "$FAILURES_FILE"; fi
      } | sort -u > alternate-changed-files.txt
    fi
    echo "::notice::Selecting from validated PR tree $candidate..$CURRENT_SHA; unresolved failures=$reused_failures"
  else
    reused_failures=false
    echo "::notice::Incremental proof unavailable; selecting from complete PR diff"
    if [ -f complete-pr-paths.txt ]; then
      cp complete-pr-paths.txt changed-files.txt
    fi
  fi
elif [ "$EVENT_NAME" = push ] && [ -n "${BEFORE_SHA:-}" ] &&
  [ "$BEFORE_SHA" != 0000000000000000000000000000000000000000 ] &&
  git fetch --no-tags --depth=1 origin "$BEFORE_SHA" &&
  git diff --no-renames --name-only "$BEFORE_SHA" "$CURRENT_SHA" > changed-files.tmp; then
  mv changed-files.tmp changed-files.txt
fi
rm -f changed-files.tmp
if [ ! -f changed-files.txt ]; then
  echo "::warning::Complete change evidence unavailable; selector will run the full suite"
fi
{
  echo "base=$base"
  echo "reused-failures=$reused_failures"
  echo "alternate-base=$alternate"
} >> "$GITHUB_OUTPUT"
