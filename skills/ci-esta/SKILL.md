---
name: ci-esta
description: Set up CI-esta in a GitHub Actions repository from one prompt. Measure completed runs (time to the required check, runner time, critical path), make one change the data supports (pack short matrix jobs, cache environments, balance shards, fix gate gaps, route lanes), prove it with same-head controls and an unchanged test inventory, and open a pull request. Works for any application language.
license: Apache-2.0
---

# Set up CI-esta in a repository

You are a coding agent improving the GitHub Actions CI of the repository you are working in. This file is the whole
procedure. Follow it in order and open one pull request. Links are for depth only; you should not need them.

CI-esta reads completed runs as data and reports the time to the required check, summed runner time, per-job and
per-step timings and the dependency critical path. Its public actions then shorten CI without weakening it. The
human keeps merging, required-check settings, runner groups and secrets.

**Ground rules**

- Work on a new branch and open a draft pull request. The repository's AGENTS.md, CONTRIBUTING, pull request
  template and AI or attribution policy win over this file on style, commit format and attribution.
- Never print, log or commit a token. Credentials go in environment variables, never in arguments.
- Never change repository settings, rulesets, required checks, runner groups or secrets. Stop and tell the human,
  with the exact step, when the next move needs one.
- Make **one** optimization (plus a gate fix if step 2 finds a gap). Keep every existing test, required check,
  coverage threshold and full or scheduled run.
- If a command fails, report the command and its error. Never work around a failure with `|| true`, a hand-written
  completion receipt, a widened gate or a deleted test.

## 1. Preflight

Run these and note the answers. Every later step uses them.

```bash
REPO=OWNER/NAME     # the repository the pull request goes to: check `git remote -v`; in a fork, the fork
gh repo view --repo "$REPO" --json defaultBranchRef,visibility,owner -q '"\(.defaultBranchRef.name) \(.visibility) \(.owner.login)"'
gh api "repos/$REPO/rules/branches/DEFAULT" --jq '.[] | select(.type == "required_status_checks") | .parameters'
gh api "repos/$REPO/branches/DEFAULT/protection/required_status_checks" --jq .contexts   # 404: no classic protection
grep -rhE '^\s*-?\s*uses:' .github/workflows | sort | uniq -c                              # how actions are pinned
grep -rn "concurrency" -A2 .github/workflows                                                # cancel-in-progress groups
ls AGENTS.md CLAUDE.md CONTRIBUTING.md AI_POLICY.md .github/AI_POLICY.md .github/pull_request_template.md \
   .github/PULL_REQUEST_TEMPLATE* uv.lock tox.ini noxfile.py pyproject.toml .pre-commit-config.yaml 2>/dev/null
grep -n "requires-python" pyproject.toml 2>/dev/null
gh api "orgs/OWNER/actions/runner-groups" --jq '.runner_groups[] | {name, visibility, allows_public_repositories}'
```

Pass `--repo "$REPO"` to every `gh` command. In a clone of a fork, `gh` otherwise picks the upstream repository.

- **Default branch** (`DEFAULT` below). Do not assume `main`.
- **Required check.** The exact job name branch protection or a ruleset requires. Call it `GATE`. If both lookups
  are empty or 403, ask the human which check is required; do not guess.
- **Pinning policy.** If the workflows pin actions to 40-character commit SHAs (often because zizmor or an
  organization policy requires it), pin every action you add the same way, with the release tag as a comment:
  `uses: gigaverse-app/ci-esta/actions/plan-runner-pools@<sha> # v1.8.0`. Resolve a tag with
  `gh api repos/OWNER/REPO/commits/TAG --jq .sha` (this returns the commit for annotated tags too). Pin a release
  tag such as `v1.8.0`, not the moving `v1`. For an action the repository already uses, copy its existing pin.
  Otherwise use `@v1` for CI-esta actions and the tags shown in this file.
- **AI and attribution policy.** Read AI_POLICY.md, CONTRIBUTING and the pull request template. If they forbid
  `Co-authored-by` lines, AI attribution or AI-written PRs, follow them exactly, or stop and tell the human.
- **Project tooling.** `uv.lock` present: `setup-cached-uv` is available. No `uv.lock` (tox, nox, pip): keep the
  existing Python setup steps; `setup-cached-uv` runs `uv sync --locked` and fails without a lock.
- **Python floor.** CI-esta itself needs Python 3.11+. Actions install their own runtime, so the floor matters only
  where CI-esta runs inside your environment: the pytest completion-receipt plugin. If the project tests versions
  older than 3.11, use no receipts in those jobs (step 4).
- **Visibility and runner groups.** For a public repository, larger runners work only if their runner group has
  `allows_public_repositories: true`. A 403 means you cannot see the groups, not that there are none. If larger
  runners are unavailable, measure standard-runner layouts only and record the reason.
- **Concurrency.** Note any `cancel-in-progress` group keyed by branch or workflow; step 6 must dispatch runs one
  at a time because of it.

*Check:* every bullet above has a written answer.

## 2. Install and inventory

```bash
uv tool install 'ci-esta[selection]>=1.8,<2'   # or: pipx install 'ci-esta[selection]>=1.8,<2'
ci-esta adoption --root .
```

If the shell says `ci-esta: command not found`, run `export PATH="$(uv tool dir --bin):$PATH"`. The `selection`
extra is required for `ci-esta check-workflow`, `ci-esta lanes` and `ci-esta-pytest`; without it they exit and
print this install command.

Expected: a pinning line, one line per workflow with its triggers, job count and aggregate gate candidate, the
matrix and test jobs, `not behind the gate: ...` when some jobs cannot fail the gate, suggestions such as
`gate-indirect` (a gate that reaches test jobs only through an `if: always()` job) or `matrix-setup`, and numbered
next steps with the exact `gh run list` and `ci-esta report` commands. It reads files only and changes nothing.

*Check:* the main workflow and `GATE` are identified, and the gate candidate matches `GATE`. If they differ, the
required check is the authority; ask the human when unsure.

## 3. Measure

```bash
export GH_TOKEN="$(gh auth token)"    # any token with actions:read and contents:read on the repository
gh run list --repo "$REPO" --workflow WORKFLOW_FILE --branch DEFAULT --status success --limit 3 \
  --json databaseId,headSha,attempt
ci-esta report --repository "$REPO" --run-id RUN_ID --run-attempt 1 --gate 'GATE' --critical-path \
  --output-dir report-RUN_ID
```

Report two or three successful attempt-1 runs: one run is noise. Each writes `report-RUN_ID/ci-observability.json`,
`.md` and `.prom` and prints a one-line summary.

Expected: `"collection_status": "complete"` and the gate `"matched": true` in the JSON. `unavailable` means the
token or run ID is wrong; `matched: false` means `GATE` is not the job's exact name. Fix either before reading
numbers. Read these fields ([all fields](https://ci-esta.readthedocs.io/en/latest/docs/github-actions-observability/#report-json-fields)):

| Field | Use it for |
| --- | --- |
| `provenance.run_id`, `.run_attempt`, `.head_sha` | The identity to cite with every number |
| `required_gates[].elapsed_from_creation_seconds` | Time to the required check: what a PR author waits |
| `runner_cost.raw_runner_seconds` | Summed job time: what the runners spend |
| `latest_attempt_jobs[].wall_seconds` and `.steps[].wall_seconds` | Which jobs are long, and setup versus test steps |
| `critical_path.execution_path`, `.execution_seconds` | The chain that decides the gate time; only it shortens the wait |
| `workflow_job_admission_delay_seconds` | Waiting before jobs start, including runner queueing |

*Check:* a baseline table with each run's ID, attempt, head, gate time, runner seconds and job count.

## 4. Choose one optimization

Pick the first row the measurements support, and say which numbers led there.

| The report shows | Do | Recipe |
| --- | --- | --- |
| `gate-indirect` or test jobs `not behind the gate` | Put those jobs in the gate's `needs`; prove with a failing probe (step 6). Do this in addition to any row below. | [Gates](https://ci-esta.readthedocs.io/en/latest/docs/selected-gates/) |
| Many short matrix jobs; each job's setup steps take about as long as its test steps | Pack several matrix entries per runner with `plan-runner-pools` (tox, nox or uv) | [Pack matrix jobs](https://ci-esta.readthedocs.io/en/latest/docs/pack-matrix-jobs/) |
| Dependency installation dominates, and `uv.lock` exists | Replace Python, uv and install steps with `setup-cached-uv` | [Environment cache](https://ci-esta.readthedocs.io/en/latest/docs/environment-cache/) |
| Dependency installation dominates, no `uv.lock` | Keep the setup; enable the existing tool's cache (`astral-sh/setup-uv` `enable-cache`, `setup-python` `cache`) | [Environment cache](https://ci-esta.readthedocs.io/en/latest/docs/environment-cache/) |
| One long pytest job on the critical path | Duration-balanced file shards with completion checks (needs Python 3.11+ in that job for receipts; otherwise split by test directory or environment and gate each job) | [Shard recipe](https://github.com/gigaverse-app/ci-esta/blob/main/examples/pytest-shards/README.md) |
| Unrelated jobs run on documentation-only PRs | Whole-lane selection with pytest-selective; keep the existing gate name | [Skip unrelated CI](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/skip-unrelated-ci/) |
| Overlapping runs for the same PR (`overlapping_prior_runner_cost`) | Add or scope a `concurrency` group to the PR and workflow; keep full and scheduled runs | [Critical path](https://ci-esta.readthedocs.io/en/latest/docs/critical-path/) |
| Identical declared work repeats after it already passed | Completion-evidence reuse, only with eligible and changed-input controls | [Evidence reuse](https://ci-esta.readthedocs.io/en/latest/docs/evidence-reuse/) |
| Nothing dominates, or the critical path is a single unavoidable job | Add only the reporting observer (step 5) and report what you found | |

Runner capacity and process count are separate choices: do not turn 16 local workers into 16 hosted jobs, and
remember larger runners are billed even for public repositories.

*Check:* one row chosen, with the report numbers that justify it.

## 5. Implement

- Match the repository: its test runner (tox, nox, uv, pytest), its setup actions, its pinning policy, its job
  names. Copy the recipe's commands, not its interpreter versions or paths.
- **Keep the existing aggregate job and its name.** If the repository already has a required aggregate job, wire
  new jobs into its `needs` and point the reporter at it. Add a new aggregate job (`validation-gate`) only when there
  is none, and tell the human its name must become the required check.
- **Same-head control.** When the change is the workflow layout itself, add a `workflow_dispatch` input that
  reproduces the old layout (for example `entries-per-runner: '1'`), so step 6 can compare both on one commit.
- **Reporting observer**, outside the gate. Save as `.github/workflows/observe-ci.yml`, with `CI` set to the
  workflow's `name:` and `GATE` to the required job's exact name:

```yaml
name: CI report
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
permissions: {}
concurrency:
  group: ${{ github.workflow }}-${{ github.event.workflow_run.id }}
  cancel-in-progress: true
jobs:
  report:
    runs-on: ubuntu-latest
    permissions:
      actions: read        # the observed run's jobs, steps and artifacts
      checks: read         # check runs for the required gate
      contents: read       # the observed workflow file, for its needs graph
      pull-requests: read  # resolve the run's PR; no comment is posted
    steps:
      - uses: gigaverse-app/ci-esta/actions/ci-observability@v1
        with:
          github-token: ${{ github.token }}
          run-id: ${{ github.event.workflow_run.id }}
          run-attempt: ${{ github.event.workflow_run.run_attempt }}
          commit-sha: ${{ github.event.workflow_run.head_sha }}
          required-gates-json: '[{"kind":"actions_job","job_name":"GATE"}]'
          analyze-critical-path: 'true'
          post-sticky: 'false'
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: ci-report-${{ github.event.workflow_run.id }}-${{ github.event.workflow_run.run_attempt }}
          path: |
            ci-observability.json
            ci-observability.md
            ci-observability.prom
          if-no-files-found: error
```

  It checks out and runs nothing from the observed run. If the repository runs zizmor, add
  `# zizmor: ignore[dangerous-triggers]` above `workflow_run` with that reason. Post PR comments
  (`post-sticky: 'true'`, `pull-requests: write`) only if the human asks for them.
- Never add a sticky comment, external telemetry, evidence reuse or selection the task did not choose.

*Check:* the repository's own workflow linters pass (`actionlint`, `zizmor` or pre-commit, whichever it uses), and
`ci-esta check-workflow --workflow .github/workflows/FILE.yml --gate 'GATE'` passes if you added lanes.

## 6. Verify

Push the branch, then:

1. **Same head, both layouts.** Dispatch the new workflow on the PR branch with the old-layout input and with the
   new default, two or three runs each:
   `gh workflow run WORKFLOW_FILE --repo "$REPO" --ref BRANCH -f entries-per-runner=1`. Dispatched runs on one
   branch share the workflow's concurrency group, so wait for each run to finish before dispatching the next, or
   the next one cancels it. Use the recent default-branch runs from step 3 for context; they ran a different head.
2. **Report every run** with `ci-esta report ... --gate 'GATE' --critical-path`, as in step 3.
3. **Inventory unchanged.** Compare what ran, entry by entry: tox environments (`--result-json`), nox sessions,
   JUnit test counts, passed and skipped totals. A shorter run that ran fewer tests is not a result.
4. **The gate still fails.** On a throwaway branch, add a test that fails in one job only (one Python version, one
   shard) and confirm `GATE` fails. Run the same probe on the default-branch layout if you fixed a gate gap, to show
   the difference. Delete the throwaway branches afterwards.
5. **Ignore cancelled and rerun attempts** in the comparison; mention them when discussing total cost.

The reporter itself runs only from the default branch (`workflow_run` uses the default branch's copy), so it does
not run on this PR. The CLI produces the same report meanwhile.

*Check:* a BEFORE/AFTER table with run links for every layout, an inventory table that matches, and the probe
result.

## 7. Open the pull request and stop

Use the repository's pull request template and attribution rules. The body states what changed and why (BEFORE/AFTER
of the job layout), the measured table, the inventory comparison, the probe, and what was not measured.

Then stop and hand these to the human, by name:

- Merge the pull request. The observer starts reporting only after it reaches `DEFAULT`.
- Make the new aggregate job a required check, if you added one.
- Runner-group or larger-runner changes, if larger runners were blocked.
- PR comment permissions, if they want sticky reports.

Never merge it yourself.

## 8. Final report

Reply with exactly these fields:

```text
Pull request: URL (draft)
Change: one sentence; recipe used
Baseline runs: RUN_ID/attempt/head ... (default branch, before)
Candidate runs: RUN_ID/attempt/head ... per layout (same head)
Time to GATE: before median (range) -> after median (range)
Runner seconds: before median -> after median (raw_runner_seconds); rounded minutes before -> after
Jobs: before -> after
Inventory: unchanged / differences
Gate probe: run link, result
Not measured: item and why (for example larger runners blocked by runner-group policy)
Human actions: merge; required check; settings
```

## Rules that keep the numbers honest

- Keep the reporter outside the validation gate's dependencies; its runner time is still reported separately.
- Never equate selected with executed, skipped tests with saved time, or a green old run with proof for new work.
- Test selection and completion-receipt reuse are different savings; attribute each to what produced it.
- Unknown timings and unknown prices stay unknown, never zero. Rounded minutes and dollars are estimates, not
  invoices; use `runner-sku-rates-json` with real rates for larger runners.
- Completion receipts are written by the pytest plugin after every required test, never by `echo $?`. An aggregate
  gate fails on missing, failed, cancelled or unexpectedly skipped prerequisites.
- If API access is unavailable, prepare the change and the exact `ci-esta report` commands and mark live impact
  unmeasured. Do not substitute test counts for measured time.

More depth: [quickstart](https://ci-esta.readthedocs.io/en/latest/docs/quickstart/),
[action reference and pinning](https://ci-esta.readthedocs.io/en/latest/docs/actions/),
[runner capacity](https://ci-esta.readthedocs.io/en/latest/docs/runners-and-diagnostics/),
[selection and evidence policy](https://ci-esta.readthedocs.io/en/latest/docs/test-selection-policy/).
