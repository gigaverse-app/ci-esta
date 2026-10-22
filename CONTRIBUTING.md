# Contributing

Install Python 3.11+ and Node.js 22+ (the actions run their JavaScript through GitHub's github-script runtime), then:

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
uv build
```

Tests call the actual JavaScript action scripts and Python report code. API fakes substitute the remote boundary and validate the available GitHub REST surface. New bugs need a regression that fails before the fix. Admission changes require positive and negative controls: valid proof must reuse, uncertain proof must execute.

The CI workflow uses the extracted actions and validates a report against the real GitHub API. Live reuse checks require an ordinary disposable same-repository PR: first produce a successful receipt, then change only an input deliberately excluded from that lane, and verify reuse. Rerun it explicitly and verify execution. Record tested revisions and run links; never count local fakes as deployed-system evidence.

For the JSON schema, regenerate from `CiObservabilityReportV1.model_json_schema()` with the locked environment, then run the schema test. Keep pytest-selective's explanation models authoritative. Keep credentials in process memory and never in reports or command-line arguments.
