---
name: ci-esta
description: Set up CI-esta in a GitHub Actions repository from one prompt. Measure completed runs (time to the required check, runner time, critical path), make one change the data supports (pack short matrix jobs, cache environments, balance shards, fix gate gaps, route lanes), prove it with same-head controls and an unchanged test inventory, and open a pull request. Works for any application language.
license: Apache-2.0
---

# Set up CI-esta in a repository

You are a coding agent improving the GitHub Actions CI of the repository you are working in. This file is the whole
procedure. Follow it in order and open one pull request. Step 4 links one recipe per optimization: read the one you
choose, because it holds the workflow YAML. Other links are for depth only. Links into the CI-esta site point at
each page's Markdown (`.md`); the same address ending in `/` instead of `.md` is the HTML page.

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
- Offer `ci-esta checkpoint init` for a weekly full checkpoint. It generates a small adopter-owned schedule
  using `gigaverse-app/ci-esta/actions/weekly-checkpoint@v1`; configure the target workflows, ref and inputs
  as needed. Verify each target runs full validation on `workflow_dispatch` and bypasses receipt reuse.
  See [weekly checkpoints](https://github.com/gigaverse-app/ci-esta/blob/main/docs/weekly-checkpoints.md).
- If a command fails, report the command and its error. Never work around a failure with `|| true`, a hand-written
  completion receipt, a widened gate or a deleted test.
- If a job already fails on the default branch, link a failing run of the unchanged workflow as proof: a
  default-branch run, or, when the default branch has no runs (a new fork), the first run of the throwaway baseline
  pull request in step 3. Then either fix it in a separate commit that the pull request names and that the
  BEFORE/AFTER comparison leaves out, or leave it failing and report it. Never fold such a fix silently into the
  measured change.
- **Waiting for runs.** Every `gh run watch` or `gh run list` call spends GitHub API requests, and the limit (5,000
  an hour) is per token, shared with any other session using it. Poll every 30 to 60 seconds:
  `gh run watch RUN_ID --repo "$REPO" --interval 30 --exit-status`. A run of a few minutes needs a few checks, not
  hundreds. If `gh` reports a rate limit, read the reset time with `gh api rate_limit --jq .resources.core` and wait
  until then instead of retrying.

## 1. Preflight

Run these and note the answers. Every later step uses them.

```bash
REPO=OWNER/NAME     # the repository the pull request goes to: check `git remote -v`; in a fork, the fork
gh repo view "$REPO" --json defaultBranchRef,visibility,owner -q '"\(.defaultBranchRef.name) \(.visibility) \(.owner.login)"'
DEFAULT="$(gh repo view "$REPO" --json defaultBranchRef -q .defaultBranchRef.name)"
gh api "repos/$REPO/rules/branches/$DEFAULT" --jq '.[] | select(.type == "required_status_checks") | .parameters'
gh api "repos/$REPO/branches/$DEFAULT/protection/required_status_checks" --jq .contexts  # 404: no classic protection
grep -rhE '^\s*-?\s*uses:' .github/workflows | sort | uniq -c                              # how actions are pinned
grep -rnE "concurrency|paths-ignore|paths:" -A2 .github/workflows                          # cancellation, path filters
grep -rln zizmor .github .pre-commit-config.yaml 2>/dev/null                                # rejects tag references
ls .github/workflows AGENTS.md CLAUDE.md CONTRIBUTING.md AI_POLICY.md .github/AI_POLICY.md \
   .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE* uv.lock tox.ini noxfile.py pyproject.toml \
   .pre-commit-config.yaml 2>/dev/null
grep -n "requires-python" pyproject.toml 2>/dev/null
OWNER="$(gh repo view "$REPO" --json owner -q .owner.login)"
gh api "orgs/$OWNER/actions/runner-groups" --jq '.runner_groups[] | {name, visibility, allows_public_repositories}'
```

In a clone of a fork, `gh` defaults to the upstream repository, so name `$REPO` every time: `--repo "$REPO"` for
`gh run`, `gh workflow` and `gh pr`; as the argument of `gh repo view`; in the path of `gh api`.

- **Default branch** (`$DEFAULT` below). Do not assume `main`.
- **Required check** (`GATE`), decided by this one rule:
  1. A ruleset or branch protection names a check: `GATE` is that exact job name.
  2. You cannot see every setting: a lookup failed with 403, or both came back empty while
     `gh api "repos/$REPO" --jq .permissions.admin` is not `true` (branch protection is hidden from non-admins).
     Run `gh pr checks NUMBER --repo "$REPO" --required` on any open pull request. If that is empty too, ask the
     human which check is required; do not guess.
  3. Nothing is required and the main workflow has an aggregate job (`ci-esta adoption` lists it as the gate
     candidate): `GATE` is that job. Tell the human to make it required.
  4. Nothing is required and there is no aggregate job: add one named `Validation gate` in step 5, use it as `GATE`,
     and tell the human to make it required.

  A required check in a workflow with `paths-ignore` or `paths` never reports on a pull request that touches only
  the ignored files, so GitHub blocks that pull request waiting for it. Before you tell the human to make a gate
  required, make sure its workflow runs on every pull request: remove the path filter from that workflow's
  `pull_request` trigger (a `push` filter can stay; required checks gate pull requests), or select
  lanes with pytest-selective so the gate always runs and judges the skipped work.
- **Pinning policy.** Reference CI-esta actions by the major tag, `gigaverse-app/ci-esta/actions/NAME@v1`, so
  releases reach the repository without edits, even when its other actions are SHA-pinned. Use
  `@<sha> # vX.Y.Z` only when the repository's own tooling rejects tags: zizmor (its `unpinned-uses` audit) or an
  all-SHA policy enforced in CI. Resolve the sha of the latest release with
  `gh api repos/gigaverse-app/ci-esta/commits/vX.Y.Z --jq .sha`. For third-party actions (checkout, setup-python,
  upload-artifact), copy the reference the repository already uses, SHA or tag; that includes the
  `upload-artifact` line of the observer in step 5.
- **Action update tools.** A tool that rewrites action references but is not enforced in CI does not change the
  rule above: keep `@v1`, and tell the human how the tool treats it. Dependabot leaves `@v1` alone until a `v2`
  exists. Renovate pins digests only with `pinDigests` (or the `helpers:pinGitHubActionDigests` preset); add a
  `packageRules` entry with `"matchPackageNames": ["gigaverse-app/ci-esta"]` and `"pinDigests": false`. gha-update
  (`[tool.gha-update]` in `pyproject.toml`, often `tox -e update-actions`) has no exclusion: it rewrites `@v1` to a
  SHA, or with `tag-only = ["gigaverse-app/ci-esta"]` to the newest exact tag such as `@v1.13.0`. Name that choice
  for the human; do not add the setting yourself.
- **AI and attribution policy.** Read AI_POLICY.md, CONTRIBUTING and the pull request template. If they forbid
  `Co-authored-by` lines, AI attribution or AI-written PRs, follow them exactly, or stop and tell the human.
- **Project tooling.** `uv.lock` present: `setup-cached-uv` is available. No `uv.lock` (tox, nox, pip): keep the
  existing Python setup steps; `setup-cached-uv` runs `uv sync --locked` and fails without a lock.
- **Python floor.** CI-esta itself needs Python 3.11+. Actions install their own runtime, so the floor matters only
  where CI-esta runs inside your environment: the pytest completion-receipt plugin. If the project tests versions
  older than 3.11, use no receipts in those jobs (step 4).
- **Visibility and runner groups.** For a public repository, larger runners work only if their runner group has
  `allows_public_repositories: true`. A 403 means you cannot see the groups, not that there are none; a 404 means
  `$OWNER` is a user account, which has no runner groups. If larger runners are unavailable, measure
  standard-runner layouts only and record the reason.
- **Concurrency.** Note any `cancel-in-progress` group keyed by branch or workflow; step 6 must dispatch runs one
  at a time because of it.

*Check:* every bullet above has a written answer.

## 2. Install and inventory

```bash
uv tool install --upgrade --refresh 'ci-esta[selection]>=1.13,<2'   # or: pipx install --force 'ci-esta[selection]>=1.13,<2'
ci-esta --version                                                     # expect ci-esta 1.13.0 or newer
ci-esta adoption --root .
```

`--refresh` makes uv re-read the package index: without it, uv's cache can miss a release published in the last
few minutes and report that only older versions exist. `--upgrade` replaces an older installed copy. If
`ci-esta --version` prints a usage message or a version below the floor, an older copy is earlier on `PATH`
(releases before 1.11 have no `--version`): check `command -v ci-esta` against `uv tool dir --bin`, and use the
newer one. An old copy gives old advice, such as SHA-pinning CI-esta actions.

If the shell says `ci-esta: command not found`, add uv's tool directory to `PATH` for this shell:

```bash
export PATH="$(uv tool dir --bin):$PATH"                  # Linux, macOS
export PATH="$(cygpath -u "$(uv tool dir --bin)"):$PATH"  # Git Bash on Windows
$env:PATH = "$(uv tool dir --bin);$env:PATH"              # PowerShell
```

Or skip the install and prefix each command with `uvx --refresh --from 'ci-esta[selection]>=1.13,<2'`, for example
`uvx --refresh --from 'ci-esta[selection]>=1.13,<2' ci-esta adoption --root .`. The `selection` extra is required for
`ci-esta check-workflow`, `ci-esta lanes` and `ci-esta-pytest`; without it they exit and print the install command.

Expected: a pinning line, one line per workflow with its triggers, job count and aggregate gate candidate, the
matrix and test jobs, `not behind the gate: ...` when some jobs cannot fail the gate, suggestions such as
`gate-indirect` (a gate that reaches test jobs only through an `if: always()` job) or `matrix-setup`, and numbered
next steps with the exact `gh run list` and `ci-esta report` commands. It reads files only and changes nothing.
Its first line reports `timing retention`: a `history-key` keeps learned test timings between runs for
timing-balanced pytest shards. `no shared history-key found` is normal; nothing in this procedure needs one.

When adopting shared timing history, default to the last green validation of a merged PR.
Follow [merged-PR timing promotion](https://ci-esta.readthedocs.io/en/latest/docs/merged-pr-evidence/):
upgrade CI-esta in the pytest environment and use the existing learn/restore actions with one history key.
The default path stamps JUnit at execution and admits merged evidence during restore, without a new workflow.
Use the explicit collector only for custom gate/shard contracts or immediate durable publication.
Working or abandoned PRs never update shared history. Do not rerun tests on every main push merely to learn
their timings. Preserve source run/attempt timestamps, exact expected shards and the complete-file contract;
never import a duration snapshot containing inherited history. Keep full checkpoints for unobserved files,
and prove hosted publication followed by restoration under an experimental key before removing an existing
learning path. Uncertain/partial rerun provenance retains the old baseline; timing data never grants test reuse.

*Check:* the main workflow and `GATE` are identified by the rule in step 1. With a required check, it is `GATE`
even when the gate candidate differs. Without one, `GATE` is the gate candidate, or `Validation gate` when the
output says `aggregate gate: none found`.

## 3. Measure

```bash
export GH_TOKEN="$(gh auth token)"    # any token with actions:read and contents:read on the repository
BASELINE_BRANCH="$DEFAULT"            # or the throwaway branch, when you make the baseline yourself (below)
gh run list --repo "$REPO" --workflow WORKFLOW_FILE --branch "$BASELINE_BRANCH" --status success --limit 3 \
  --json databaseId,headSha,attempt
ci-esta report --repository "$REPO" --run-id RUN_ID --run-attempt 1 --gate 'GATE' --critical-path \
  --output-dir report-RUN_ID
```

Report two or three successful attempt-1 runs: one run is noise. Each writes `report-RUN_ID/ci-observability.json`,
`.md` and `.prom` and prints a one-line summary.

If the default branch has no successful run of the workflow (a new fork, or a red branch), make the baseline yourself:
open a throwaway draft pull request from `$DEFAULT` that changes one file the workflow does not ignore, and push an
empty commit (`git commit --allow-empty`) for each further run, until two or three attempt-1 runs succeed. That is
the unchanged workflow on your runners; set `BASELINE_BRANCH` to the throwaway branch to list its runs. Make the
change one the repository's own hooks accept, such as a comment line in a test file, and run its pre-commit hooks
first: a stray blank line at the end of a file can fail an `end-of-file-fixer` hook and turn the baseline red. Runs
in the upstream repository are context only, never the baseline. Close the throwaway pull request and delete its
branch afterwards.

If the unchanged workflow fails there too (the default branch is red), that first failing run is the proof the
ground rules ask for. Fix the failure in its own commit, put that same commit on both the throwaway baseline branch
and your pull request branch, and measure from there; the pull request names the commit, and the comparison leaves
it out.

If `GATE` is a `Validation gate` you have not added yet, the baseline has no gate: report each baseline run with
`--gate` naming the job that finished last in that run, which can differ from run to run:
`gh run view RUN_ID --repo "$REPO" --json jobs -q '[.jobs[] | select(.completedAt != null)] | max_by(.completedAt) | .name'`.

Expected: `"collection_status": "complete"` and the gate `"matched": true` in the JSON. `unavailable` means the
token or run ID is wrong; `matched: false` means `GATE` is not the job's exact name; `partial` lists its reasons in
`collection_errors` and in the summary line. Fix these before reading numbers. Read these fields ([all fields](https://ci-esta.readthedocs.io/en/latest/docs/github-actions-observability.md#report-json-fields)):

| Field | Use it for |
| --- | --- |
| `provenance.run_id`, `.run_attempt`, `.head_sha` | The identity to cite with every number |
| `required_gates[].elapsed_from_creation_seconds` | Time to the required check: what a PR author waits |
| `runner_cost.raw_runner_seconds` | Summed job time: what the runners spend |
| `latest_attempt_jobs[].wall_seconds` and `.steps[].wall_seconds` | Which jobs are long, and setup versus test steps |
| `critical_path.execution_path`, `.execution_seconds` | The chain that decides the gate time; only it shortens the wait |
| `workflow_job_admission_delay_seconds` | Waiting before the *first* job starts; other jobs can wait longer |
| `longest_job_queue_seconds`, `longest_job_queue_name` | The longest wait for a runner, such as a macOS job |

*Check:* a baseline table with each run's ID, attempt, head, gate time, runner seconds and job count.

## 4. Choose one optimization

Apply the first row whenever it holds; it fixes the gate, in addition to any optimization. Of the other rows,
take the first one from the top whose condition the measurements support, and say which numbers led there.

| The report shows | Do | Recipe |
| --- | --- | --- |
| `gate-indirect` or test jobs `not behind the gate` | Put those jobs in the gate's `needs`; prove with a failing probe (step 6). Do this in addition to any row below. | [Gates](https://ci-esta.readthedocs.io/en/latest/docs/selected-gates.md) |
| Many short matrix jobs; each job's setup steps take about as long as its test steps | Pack several matrix entries per runner with `plan-runner-pools` (tox, nox or uv) | [Pack matrix jobs](https://ci-esta.readthedocs.io/en/latest/docs/pack-matrix-jobs.md) |
| Dependency installation dominates, and `uv.lock` exists | Replace Python, uv and install steps with `setup-cached-uv` | [Environment cache](https://ci-esta.readthedocs.io/en/latest/docs/environment-cache.md) |
| Dependency installation dominates, no `uv.lock` | Keep the setup; enable the existing tool's cache (`astral-sh/setup-uv` `enable-cache`, `setup-python` `cache`) | [Environment cache](https://ci-esta.readthedocs.io/en/latest/docs/environment-cache.md) |
| One long pytest job on the critical path | Duration-balanced file shards with completion checks (needs Python 3.11+ in that job for receipts; otherwise split by test directory or environment and gate each job) | [Shard recipe](https://github.com/gigaverse-app/ci-esta/blob/v1/examples/pytest-shards/README.md) |
| Unrelated jobs run on documentation-only PRs | Whole-lane selection with pytest-selective; keep the existing gate name | [Skip unrelated CI](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/skip-unrelated-ci/) |
| Overlapping runs for the same PR (`overlapping_prior_runner_cost`) | Add or scope a `concurrency` group to the PR and workflow; keep full and scheduled runs | [Critical path](https://ci-esta.readthedocs.io/en/latest/docs/critical-path.md) |
| Identical declared work repeats after it already passed | Completion-evidence reuse, only with eligible and changed-input controls | [Evidence reuse](https://ci-esta.readthedocs.io/en/latest/docs/evidence-reuse.md) |
| Nothing dominates, or the critical path is a single unavoidable job | Add only the reporting observer (step 5) and report what you found | |

Runner capacity and process count are separate choices: do not turn 16 local workers into 16 hosted jobs, and
remember larger runners are billed even for public repositories.

Packing adds a `plan` job that runs before the packed tests, one after the other (about 10 s in the itsdangerous
trial), so time to `GATE` can grow by a few seconds while runner seconds fall. Packing succeeds when runner seconds
fall and the median time to `GATE` stays inside the old layout's same-head range. Report both numbers either way,
including a small gate-time cost.

*Check:* one row chosen, with the report numbers that justify it.

## 5. Implement

- Match the repository: its test runner (tox, nox, uv, pytest), its setup actions, its pinning policy, its job
  names and its workflow file extension (`.yml` or `.yaml`; name new files the same way). Copy the recipe's
  commands, not its interpreter versions, paths or environment names. For tox, list the environments with
  `tox list` and select them by their own names, for example `-e py3.13,py3.12`; `-f 3.13` matches only
  environments with a `3.13` factor, such as `3.13-tests`, not `py3.13`.
- **Packing with several operating systems.** Every runner in one packed job uses the same `runs-on`, so pack only
  entries that run on the same image. Plan one set of pools per operating system (one `plan-runner-pools` step and
  one packed job each), and keep an entry that needs a different image (a Python version only `ubuntu-24.04`
  still provides, or a single Windows or macOS entry) as its own job, for example through `matrix.include`. Every
  one of those jobs goes in the gate's `needs`.
- **Keep the existing aggregate job and its name.** If `GATE` is an aggregate job, wire new jobs into its `needs`.
  If step 1 chose a new `Validation gate`, add it to the workflow that runs the tests, needing every job that must
  pass:

```yaml
  validation-gate:
    name: Validation gate
    needs: [tests, typing]   # every validation job in this workflow
    if: ${{ !cancelled() }}
    runs-on: ubuntu-latest
    steps:
      - uses: gigaverse-app/ci-esta/actions/validation-gate@v1
        with:
          needs: ${{ toJSON(needs) }}   # every need must succeed; failed, cancelled or skipped jobs fail the gate
```
- **Same-head control.** When the change is the workflow layout itself, add a `workflow_dispatch` input that
  reproduces the old layout (for example `entries-per-runner: '1'`), so step 6 can compare both on one commit.
- **Reporting observer**, outside the gate. Save as `.github/workflows/observe-ci.yml` (`.yaml` if the
  repository uses that), with `CI` set to the workflow's `name:` and `GATE` to the required job's exact name:

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

  It checks out and runs nothing from the observed run. Write `actions/upload-artifact` with the reference the
  repository already uses for it, SHA or tag; only the CI-esta action stays `@v1`. If the repository runs zizmor, add
  `# zizmor: ignore[dangerous-triggers]` above `workflow_run` with that reason. Post PR comments
  (`post-sticky: 'true'`, `pull-requests: write`) only if the human asks for them.
- Never add a sticky comment, external telemetry, evidence reuse or selection the task did not choose.

*Check:* the repository's own workflow linters pass (`actionlint`, `zizmor` or pre-commit, whichever it uses), and
`ci-esta check-workflow --workflow .github/workflows/FILE.yml --gate 'GATE'` passes. Run it after the gate exists.
Without lanes it checks that the gate uses the shared action and that every job in the workflow reaches it
(`every job reaches the gate (no lanes)`); with lanes it also checks the lane routing.

## 6. Verify

Push the branch, then:

1. **Same head, both layouts.** Dispatch the new workflow on the PR branch with the old-layout input and with the
   new default, two or three runs each:
   `gh workflow run WORKFLOW_FILE --repo "$REPO" --ref BRANCH -f entries-per-runner=1`. Dispatched runs on one
   branch share the workflow's concurrency group, so wait for each run to finish before dispatching the next, or
   the next one cancels it.

   The old-layout input reproduces the old *job graph*, not the old workflow: each job still runs the new steps
   (the `plan` job, the gate, any `--result-json` or artifact upload). So report three rows: the unchanged
   workflow from step 3 (BEFORE, its own head), the old-layout input and the new default (both on this head).
   Credit the optimization only with the change from the old-layout input to the new default. Attribute the change
   from BEFORE to the old-layout input to the added jobs and steps plus run-to-run noise, and say so; if one job's
   steps sum to clearly more than in BEFORE, name the added step.
2. **Report every run** with `ci-esta report ... --gate 'GATE' --critical-path`, as in step 3.
3. **Inventory unchanged.** Compare what ran, entry by entry: tox environments (`--result-json`), nox sessions,
   JUnit test counts, passed and skipped totals. A shorter run that ran fewer tests is not a result.
4. **The gate still fails.** On a throwaway branch, add a test that fails in exactly one job: one CPython version
   that runs nowhere else (for example `assert sys.version_info[:2] != (3, 12)`), not PyPy and not a version that
   another operating system also runs. Confirm `GATE` fails; every extra failing job costs another rerun. Run the
   same probe on the default-branch layout if you fixed a gate gap, to show the difference. Delete the throwaway
   branches afterwards.
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

More depth: [quickstart](https://ci-esta.readthedocs.io/en/latest/docs/quickstart.md),
[action reference and pinning](https://ci-esta.readthedocs.io/en/latest/docs/actions.md),
[runner capacity](https://ci-esta.readthedocs.io/en/latest/docs/runners-and-diagnostics.md),
[selection and evidence policy](https://ci-esta.readthedocs.io/en/latest/docs/test-selection-policy.md).
