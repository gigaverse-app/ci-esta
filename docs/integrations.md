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
| "Saved" is measured against | The median of recent full-suite pytest timings, from `ci-full-suite-reference-v1` artifacts | The skipped jobs' runner time on the default branch's last green push run, which runs every lane |

Use both in a large repository: lanes decide which services start, and file selection narrows the biggest lane. gigaverse-backend plans its unit lane by file inside lane-level routing.

The report reads the lane plan on every run and the file explanation only when it posts the sticky. A PR comment is posted only when `pull-request-number` is also supplied; without it the same Markdown goes to the job summary and artifact.

### Getting the most from both in a Python project

1. **Measure first.** Add the completed-run observer with your exact gate names. Its slowest-job and slowest-step tables say whether time goes to tests, setup or services, which decides the granularity.
2. **Pick the granularity.** Many service-backed jobs: lanes. One dominant pytest suite: files. Both: lanes outside, files inside the largest lane.
3. **Declare what imports cannot show.** Data files, subprocess entry points, external checkouts and settings read at runtime belong in lane `inputs` or reader-owned declarations. Lock files and workflows stay global inputs that run everything.
4. **Keep required checks honest.** A skipped job never reports. CI-esta's `validation-gate` accepts a skip only when planning succeeded and explicitly skipped it; a failed planner runs the complete suite.
5. **Turn on the sticky.** Set `post-sticky: true`, grant `pull-requests: write`, and pass `sticky-key` when one observer reports several workflows. `plan-lanes` uploads the lane plan, so the lane section needs no extra step.
6. **Keep full checkpoints.** Main pushes, `test:full` and planner fallbacks run every lane. They are the safety net, and they are the baseline the sticky prices skipped work against.
7. **Reuse evidence last.** Selection asks "what might this change affect?"; [evidence reuse](evidence-reuse.md) asks "did this exact declared work already pass?" Keep conservative fallbacks at both layers.

Use the [selected-lane aggregate gate](selected-gates.md) to keep optional jobs
and required statuses consistent. CI-esta's own workflow now combines
pytest-selective lane planning with receipt reuse, while its quality job always
checks routing, builds distributions and validates metadata. Main, manual and
`test:full` runs retain complete execution.

## pytest-obligation: preserve what green means

Run generated obligation tests as ordinary CI lanes and emit the completion receipt only after the test process and any required profile-report checks pass. A selected, skipped, xfailed or merely collected obligation is not an executed guarantee. Use pytest-obligation's own reporting to distinguish those outcomes. CI-esta's lane receipt is an execution-admission signal; it is not an obligation conformance certificate.

External databases, queues and service versions can influence conformance results. Include their pinned configuration in declared inputs and retain full/scheduled runs; CI-esta cannot content-address a live service's changing state.

## Due: application reliability and CI reliability

Due's durable-work semantics belong in the application, while CI-esta handles validation workflows. CI-esta does not schedule Due obligations or replace its recovery machinery. Due projects can adopt the same observation and lane-evidence actions used by any Python or non-Python repository. The public projects adopt the shared completed-run observer separately from their validation gates; see their workflow pins for the deployed revision.
