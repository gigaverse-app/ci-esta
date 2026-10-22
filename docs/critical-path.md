# Find the dependency chain that determines CI completion

Enable `analyze-critical-path: true` in the [completed-run observer](github-actions-observability.md)
and configure a stable aggregate gate such as `Validation gate`. The observer
reads the run's workflow file at its reported head SHA through the GitHub API.
It parses `needs` and expands job-name patterns against observed jobs. It never
checks out or executes the observed repository's code.

```yaml
# Add under jobs.report.with in the observer:
required-gates-json: '[{"kind":"actions_job","job_name":"Validation gate"}]'
analyze-critical-path: true
```

For a local read-only report, put a GitHub read token in `GH_TOKEN` or
`GITHUB_TOKEN`, then run:

```bash
ci-esta report --repository owner/project --run-id 123456 --run-attempt 1 \
  --gate 'Validation gate' --critical-path --output-dir report
```

## What the two paths mean

The **observed dependency chain** follows the latest-finishing prerequisite
backwards from the last required gate. Each node contributes its execution time
and the delay between its dependencies finishing and its own start. Those
contributions sum to gate elapsed time from workflow creation. A short job with
a long admission delay can therefore determine the observed path.

The **execution-only critical path** uses the critical-path method on the same
DAG, weighted by observed execution durations. It calculates earliest finish,
latest finish and slack using forward and backward passes. Zero slack identifies
jobs on an execution critical path. Parallel branches with positive slack can
be optimized without shortening this execution-only lower bound. Equal-length
paths use a deterministic tie break; the slack table still identifies all
zero-slack jobs.

The Gantt highlights the observed chain in orange when analysis is complete. It
continues showing the measured job intervals. The report table separates
execution, post-prerequisite delay and execution slack. Delay can include runner
admission, environment approval, scheduling and resource contention; API timing
does not isolate those causes. CPM holds observed durations constant and does
not predict how contention changes after moving work to different runners.

For example, a 20-second root job and a one-second root job starting at second
30 feed a one-second gate starting at second 32. The observed chain goes through
the delayed job and completes at second 33; the execution-only path goes through
the 20-second job and totals 21 seconds. The longest job alone would miss the
actual delay.

## Preserve the dependency contract

Skipped jobs have zero execution cost but retain their prerequisite edges.
Only ancestors of the configured gates affect the analysis; an independent
observer does not become part of the validation critical path. Analysis of a
failed run explains time to the failed result, not successful merge readiness.

Cycles, duplicate/ambiguous names, missing jobs, inconsistent timestamps, mixed
attempts and unfinished relevant jobs make the path unavailable. Basic timing
and cost reporting remain useful. Conditional matrix cells are expanded from
observed names, including GitHub's skipped matrix representation.

Reusable workflow calls cannot be reconstructed from their outer `needs` alone.
For those, supply a complete expanded `job-dependencies-json` map. Keys are
observed job-name patterns and values are prerequisite patterns:

```yaml
job-dependencies-json: >-
  {"Plan":[],"Tests (*)":["Plan"],"Validation gate":["Plan","Tests (*)"]}
```

This is an explicit topology contract, not an invitation to omit slow edges.
Keep it synchronized with reusable workflow internals. Unknown topology is
reported as unavailable instead of inferred from timestamps. Prefer automatic
source-workflow parsing for ordinary jobs so adding a `needs` edge automatically
changes the next report.
