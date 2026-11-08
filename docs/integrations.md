# CI-esta, pytest-selective, pytest-obligation and Due

These projects address different stages of trustworthy development. They can be adopted independently.

| Project | Owns | How it fits |
| --- | --- | --- |
| [CI-esta](https://github.com/gigaverse-app/ci-esta) | CI execution evidence, admission and measurement | Reuse completed lanes and expose time/cost |
| [pytest-selective](https://github.com/gigaverse-app/pytest-selective) | Explainable Python test selection, shard planning and scope/isolation guards | Decide which test files or lanes are affected |
| [pytest-obligation](https://github.com/gigaverse-app/pytest-obligation) | Crash, retry, lost-message and competing-operation conformance tests | Exercise the application's declared durable-work obligations |
| [Due](https://github.com/gigaverse-app/due) | Durable application obligations for Django/PostgreSQL/Celery | Record and recover application work despite lost delivery or worker death |

```text
Due application behavior
  -> pytest-obligation conformance tests
  -> pytest-selective affected-test/lane plan (when inputs are modeled)
  -> CI-esta execution evidence and timing report
```

## pytest-selective: one contract, two granularities

The selector also supports local edits with `pytest-selective run --config CONFIG
-- PYTEST_OPTIONS`. Its private-index snapshot leaves staging and HEAD intact;
selection happens before pytest collection. Common dependency environment files
invalidate tests and lanes by default. CI-esta's import-boundary guards share the
selector's warning-stable source parser instead of maintaining another policy.
See the [pytest-impacted comparison](https://pytest-selective.readthedocs.io/en/latest/docs/comparison-pytest-impacted/)
for adopted ideas, measured parser improvements and limits.

CI-esta imports pytest-selective's models (`SelectionExplanation`, `LanePlan`) directly; it does not fork the selector. pytest-selective decides what runs; CI-esta measures what that decision cost and saved, keeps required checks honest when work is skipped, and explains both on the pull request. CI-esta never changes a selection decision while rendering it.

pytest-selective selects at two granularities, and the sticky has a section for each:

| | File selection (`test-impact` action) | Lane selection (`plan-lanes` action) |
| --- | --- | --- |
| Selects | Test files inside one pytest run | Whole CI jobs or matrices, run complete |
| Best for | One large suite whose time is in the tests themselves | Lanes that start services (PostgreSQL, Redis, framework checkouts) or must keep complete conformance evidence |
| Artifact the report reads | `test-impact-explanation` (`test-selection-artifact`) | `test-lane-selection` (`lane-selection-artifact`) |
| Sticky section | 🎯 Test selection: files ran, why, test time saved | 🧪 Test lanes: lanes ran, why, runner time skipped |
| "Saved" is measured against | The median of recent full-suite pytest timings, from `ci-full-suite-reference-v1` artifacts | Available matching job timings from the default branch's last green push run; an unobserved job has no measured saving |

### Plan lanes from tests and workflows

**The lane file is optional.** Without `config`, `plan-work` reads the lanes from the
workflow. The lanes are the names job conditions read (`fromJSON(needs.select-tests.outputs.lanes).unit`),
and a lane's test roots are the paths its jobs pass to `pytest`, `python -m pytest`,
`bun test` or `unittest discover -s`. A test command without paths, or a runner script
such as `scripts/run_ci_tests.py`, collects pytest's `testpaths`. A lane whose jobs run
no test command (a build, a smoke check) is selected through those jobs. The reviewed
pytest policy is the base commit's, so a pull request that changes how pytest collects
runs every lane. A test no lane claims also runs every lane, so a wrong guess costs time,
never coverage. Add a lane file when roots must be narrower than the commands show, or
when jobs read a different planner output.

**See the lanes.** `ci-esta lanes` prints every lane: its test roots, the jobs it gates, and
where it came from (the job and command a root was read from, or the lane file). Add
`--base origin/main` to see what a change would run and why; the `plan-work` step summary
shows the same table on every run.

```text
$ ci-esta lanes --base origin/main
| Lane | Runs | Why | Tests (roots) | Jobs it gates | Defined by |
| `smoke` | ✅ runs | workflow input: scripts/smoke.sh (run by .github/workflows/ci.yml#smoke) | – | smoke | no test command; selected through .github/workflows/ci.yml#smoke |
| `unit` | ⏭️ skipped | no affected tests or changed inputs | tests/unit | unit | roots tests/unit from .github/workflows/ci.yml#unit: `pytest tests/unit -q` |
```

**Change only what is wrong.** A lane file with `"extends": "workflow"` lists only the lanes
it adds or replaces; every other lane stays inferred and keeps following the workflow.
`ci-esta lanes --write .github/test-lanes.json` writes every inferred lane as a starting
point: delete the ones the workflow already gets right. For example, pytest-obligation's
jobs pick tests by marker, so inference sees whole directories; two lanes narrow them:

```json
{
  "extends": "workflow",
  "lanes": {
    "core": {"roots": ["package/tests/core", "integration_tests/core"]},
    "redis": {"roots": ["package/tests/rq", "package/tests/celery_worker", "integration_tests/rq", "integration_tests/celery_worker"]}
  }
}
```

An extending file may also set `graph` fields (merged over the inferred graph) and
`global_inputs`. A lane file without `extends` is complete and used exactly as written.

**Rules: when these files change, run that.** Anything the graphs cannot see is a rule in
the extending file. A rule names the files it watches and what it selects: `all`,
`lane:NAME`, `job:WORKFLOW#JOB` (the lanes that job runs) or `package` (the lanes of the jobs
that build the package). Patterns match like gitignore. The plan names the rule that
selected each lane (`rule schemas: schemas/user.json (loaded by name)`).

```json
{
  "extends": "workflow",
  "rules": [
    {"name": "schemas", "when": ["schemas/**"], "select": ["lane:integration"], "reason": "loaded by name"},
    {"name": "python-environment", "when": ["pyproject.toml", "uv.lock"], "select": ["all"]}
  ],
  "disable_rules": ["bun-environment"]
}
```

CI-esta's own defaults are rules too, listed by `ci-esta lanes` with origin `built-in`:

| Built-in rule | Watches | Selects |
| --- | --- | --- |
| `python-environment` | `pyproject.toml`, lockfiles, requirements and pytest configuration | every lane |
| `bun-environment` | `package.json`, `bun.lock`, `bunfig*.toml`, `tsconfig*.json` | every lane with Bun tests |

Give a rule the same name to replace a default; the example above narrows
`python-environment` so a documentation site's `requirements.txt` runs nothing. List a name in
`disable_rules` to switch one off. A lane's `inputs` keep working and select their lane.

| Repository on 2026-11-08 | Inferred from its workflow | Hand-written lane file |
| --- | --- | --- |
| dry-lint | `tests`: `tests`; `counter`, `viewer`, `package`, `dogfood`: their jobs | the same |
| pytest-selective | `tests`: `tests`; `contracts`: `contracts/selection`; `package`: its job | `contracts` root one level wider |
| pytest-quint-connect | `tests`: `tests`; `dogfood`: `dogfood`, `examples/lru_cache`; `routing`: `ci_tests`; `package`: `tests/test_release.py` | `dogfood` narrowed to one test file |
| due | `contracts`, `typecheck`, `wheel` only | `library` and `integration` read `outputs.library`, not the lane map, so it keeps its lane file |

`gigaverse-app/ci-esta/actions/plan-work@v1` takes the same lane file and inputs as
`plan-lanes` and returns the same `lanes` output and `test-lane-selection` artifact, so
job conditions, the validation gate and the report need no change. It adds CI-esta's
workflow graph to pytest-selective's affected tests:

| Change | `plan-lanes` (built-in inputs) | `plan-work` |
| --- | --- | --- |
| A job gated on a lane (`fromJSON(needs.select-tests.outputs.lanes).unit`) | every lane | that job's lanes |
| A job that gates no lane, such as lint | every lane | nothing; it always runs |
| A script, local action or reusable workflow a gated job executes | every lane under `.github/`, nothing elsewhere | that job's lanes |
| The planner job or the lane file it reads | every lane | every lane |
| Workflow triggers, `env`, `permissions`, `concurrency` | every lane | every lane the workflow runs |
| A pull-request template, `dependabot.yml`, an action's README | nothing for Markdown, every lane otherwise | nothing |
| An unreadable workflow | every lane | every lane |

Jobs depend on the repository paths they name in `run`, `with` and local `uses`,
including paths an action names through `github.action_path`. A path built at runtime
(`bash "$SCRIPTS/run.sh"`) is invisible; name it literally or declare it in a lane's
`inputs`. Explicit `global_inputs` in the lane file are kept exactly, so the graph
narrows CI changes only once you drop the `.github/` entries it replaces. Hand-written
`ci.yml#job` inputs become unnecessary.

**Package jobs.** A job that builds, checks, installs or publishes the package (`uv build`,
`python -m build`, `twine check`, `pip install .`, `npm pack`, `bun publish`, the PyPA
publish action, …) also runs when the package's inputs change, as the build tools list them:

| Package | Inputs | Read by |
| --- | --- | --- |
| `pyproject.toml` with `[project]` and `[build-system]` | every file the wheel contains, mapped back to the repository, plus the `readme` and license files its metadata embeds | `uv build --wheel` |
| `package.json` that is not `private` | every file `npm pack` would publish | `npm pack --dry-run` |

So a README the wheel embeds runs the package build, while a docs page or a test does not, and
the lane needs no hand-written inputs. A package the tools cannot build or list runs its jobs.
A deleted file beside a package input runs them too.

Bun tests get the same lane planning. A lane whose roots hold `*.test.ts` or `*.spec.tsx`
files is selected from Bun's own module graph ([Bun lanes](bun-test-selection.md#whole-lane-planning)).

Use both in a large repository: lanes decide which services start, and file selection narrows the biggest lane. gigaverse-backend plans its unit lane by file inside lane-level routing.

The report reads the lane plan on every run and the file explanation only when it posts the sticky. A PR comment is posted only when `pull-request-number` is also supplied; without it the same Markdown goes to the job summary and artifact.

### Getting the most from both in a Python project

1. **Measure first.** Add the completed-run observer with your exact gate names. Its slowest-job and slowest-step tables say whether time goes to tests, setup or services, which decides the granularity.
2. **Pick the granularity.** Many service-backed jobs: lanes. One dominant pytest suite: files. Both: lanes outside, files inside the largest lane.
3. **Declare what imports cannot show.** Data files, subprocess entry points, external checkouts and settings read at runtime belong in lane `inputs` or reader-owned declarations. Lock files stay global inputs that run everything; name workflows per job (`ci.yml#tests`) so editing a lint job does not run every lane.
4. **Keep required checks honest.** A skipped job never reports. CI-esta's `validation-gate` accepts a skip only when planning succeeded and explicitly skipped it; a failed planner runs the complete suite.
5. **Turn on the sticky.** Set `post-sticky: true`, grant `pull-requests: write`, and pass `sticky-key` when one observer reports several workflows. `plan-lanes` uploads the lane plan, so the lane section needs no extra step.
6. **Keep full checkpoints.** Manual/scheduled/release events, `test:full` in the triggering event, and conservative planner fallbacks retain full work. Ordinary PRs, pushes and their reruns remain selective. Use explicit `full: 'true'` when another workflow needs a complete checkpoint.
7. **Audit a documentation-only pull request.** Gate every build, install smoke and routing-test job on a lane too, then confirm a docs-only probe PR executes none of them. [The audit](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/skip-unrelated-ci/#audit-what-a-documentation-only-pull-request-still-runs) lists the traps.
8. **Reuse evidence last.** Selection asks "what might this change affect?"; [evidence reuse](evidence-reuse.md) asks "did this exact declared work already pass?" Keep conservative fallbacks at both layers.

Use the [selected-lane aggregate gate](selected-gates.md) to keep optional jobs
and required statuses consistent. CI-esta's own workflow now combines
pytest-selective lane planning with receipt reuse. Its quality job always lints;
routing contracts run in the `tests` lane, and distribution builds and metadata
checks run in the `package` lane, so a documentation-only change runs neither
([lane table](../CONTRIBUTING.md#documentation-only-ci)). Manual and
`test:full` runs retain complete execution; ordinary main pushes use selection.

## pytest-obligation: preserve what green means

Run generated obligation tests as ordinary CI lanes and emit the completion receipt only after the test process and any required profile-report checks pass. A selected, skipped, xfailed or merely collected obligation is not an executed guarantee. Use pytest-obligation's own reporting to distinguish those outcomes. CI-esta's lane receipt is an execution-admission signal; it is not an obligation conformance certificate.

External databases, queues and service versions can influence conformance results. Include their pinned configuration in declared inputs and retain full/scheduled runs; CI-esta cannot content-address a live service's changing state.

## Due: application reliability and CI reliability

Due's durable-work semantics belong in the application, while CI-esta handles validation workflows. CI-esta does not schedule Due obligations or replace its recovery machinery. Due projects can adopt the same observation and lane-evidence actions used by any Python or non-Python repository. The public projects adopt the shared completed-run observer separately from their validation gates; see their workflow pins for the deployed revision.
