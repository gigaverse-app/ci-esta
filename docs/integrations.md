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

## pytest-selective: share the contract

CI-esta imports pytest-selective's `SelectionExplanation` and related models directly; it does not fork the selector. Upload the explanation JSON as a single-file artifact and pass its name through the report action's `test-selection-artifact`. Supply measured timings through the generic `pytest` extension. The report can explain why tests ran and compare against eligible full-suite references. CI-esta never changes the selection decision while rendering it.

The inherited alpha reporter reads selection artifacts only when `post-sticky: 'true'`. A PR comment is posted only when `pull-request-number` is also supplied; leaving that input empty allows a summary/artifact report without posting. The basic observability examples disable this optional section explicitly.

Selection and evidence reuse answer different questions: “what might this change affect?” and “was this exact declared work already completed successfully?” Keep conservative fallbacks at both layers.

## pytest-obligation: preserve what green means

Run generated obligation tests as ordinary CI lanes and emit the completion receipt only after the test process and any required profile-report checks pass. A selected, skipped, xfailed or merely collected obligation is not an executed guarantee. Use pytest-obligation's own reporting to distinguish those outcomes. CI-esta's lane receipt is an execution-admission signal; it is not an obligation conformance certificate.

External databases, queues and service versions can influence conformance results. Include their pinned configuration in declared inputs and retain full/scheduled runs; CI-esta cannot content-address a live service's changing state.

## Due: application reliability and CI reliability

Due's durable-work semantics belong in the application, while CI-esta handles validation workflows. CI-esta does not schedule Due obligations or replace its recovery machinery. Due projects can adopt the same observation and lane-evidence actions used by any Python or non-Python repository. The public projects adopt the shared completed-run observer separately from their validation gates; see their workflow pins for the deployed revision.
