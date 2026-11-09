# Weekly full checkpoints

Keep fast, selective PR checks and run complete validation weekly. CI-esta provides
`actions/weekly-checkpoint@v1` and `ci-esta checkpoint` to dispatch your existing
validation workflows. There is no waiting runner: each target workflow reports
its own result and retains its normal artifacts and required gate.

## Adopt the defaults

Your `ci.yml` must accept `workflow_dispatch` and run the **full suite** for that
event. CI-esta and pytest-selective actions already do this with `full: auto`.
Do not allow evidence reuse on manual dispatches. Keep coverage and compatibility
checks enabled in that path.

Generate the small schedule wrapper from your repository root:

```sh
ci-esta checkpoint init
```

If CI-esta is not installed, generate it with uv without adding a project dependency:

```sh
uvx --from 'ci-esta>=1.11,<2' ci-esta checkpoint init
```

This creates `.github/workflows/weekly-checkpoint.yml` without overwriting an
existing file. Commit it to the default branch. The defaults are Monday at
03:17 UTC, `ubuntu-latest`, a five-minute dispatcher timeout, `ci.yml` on the
repository's default branch, and no target inputs. No Python setup or checkout
step is needed in an adopter's wrapper; the action owns its locked runtime.

Or create the wrapper directly:

```yaml
name: Weekly full checkpoint
on:
  schedule:
    - cron: '17 3 * * 1'
  workflow_dispatch:
permissions:
  contents: read
  actions: write
jobs:
  checkpoint:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: gigaverse-app/ci-esta/actions/weekly-checkpoint@v1
```

GitHub runs schedules from the default branch and may delay them. Ensure Actions
and scheduled workflows remain enabled. Remove old schedule triggers from target
workflows when this wrapper replaces them, so each suite runs once weekly.

## Override the behavior

```yaml
      - uses: gigaverse-app/ci-esta/actions/weekly-checkpoint@v1
        with:
          workflows: '["ci.yml", "public-actions.yml"]'
          ref: main
          workflow-inputs: '{"full": true}'
```

`workflows` contains filenames under `.github/workflows/`, not display names.
`ref` accepts a branch or tag; leave it empty to follow the default branch.
`workflow-inputs` applies to every target and must match each target's declared
inputs. Omit it for CI-esta/pytest-selective's default full-on-dispatch behavior.
Use separate action steps when workflows require different inputs.

The generator accepts the same settings, plus the schedule and output location:

```sh
ci-esta checkpoint init --cron '43 4 * * 0' \
  --workflows '["ci.yml", "public-actions.yml"]' --ref main
```

For a local preflight, use a token in the environment with `contents: read` and
`actions: write`, and set `GITHUB_REPOSITORY=owner/repo`:

```sh
ci-esta checkpoint run --dry-run
ci-esta checkpoint run --workflows '["ci.yml", "public-actions.yml"]'
```

In the action, `dry-run: 'true'` performs the same preflight. `token` defaults to
`github.token`; ordinary same-repository dispatch needs no personal token.
The dispatcher validates every workflow and its input names before submitting
any dispatch. API failures fail the step. If a later dispatch fails after an
earlier one was accepted, its log identifies the accepted target; retrying can
start it again. The action deliberately does not retry mutations automatically.

## What a green dispatcher proves

Outputs `ref` and `workflows` identify the targets. `dispatched: 'true'` means
GitHub accepted all requests, **not that tests passed**. Follow the target runs
on the repository's Actions page to verify complete test counts, coverage and
the final validation gate. This action cannot infer whether an arbitrary custom
workflow runs a full suite; that remains the target workflow's contract.

Changes to the shared dispatcher are tested with real HTTP adapter boundaries:
default branch resolution, multi-target preflight, invalid/required inputs,
dry runs and dispatch payloads. Dogfood workflows in CI-esta and pytest-selective
exercise the full-on-dispatch policy on hosted runners.
