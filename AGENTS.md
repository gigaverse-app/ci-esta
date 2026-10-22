# Working on CI-esta

For adopting CI-esta in another repository, use
[the portable skill](skills/ci-esta/SKILL.md). This file covers contributions to
the toolkit itself.

- Use [CONTRIBUTING.md](CONTRIBUTING.md): Python 3.11+, Node.js 22+,
  `uv sync --locked`, `uv run ruff check .`, `uv run pytest -q -n 4`, `uv build`.
  Some source-parser tests also need Python 3.14 installed, as in CI.
- Preserve conservative execution on missing/uncertain proof. Admission changes
  need positive reuse and negative execution controls using the actual action
  code; mock the remote API boundary rather than the decision under test.
- Completion receipts belong after all required work. Aggregate gates must fail
  on missing, failed, cancelled and unexpectedly skipped prerequisites. Reporting
  should not become a prerequisite of the validation it measures.
- pytest-selective owns dependency graphs, explanation models, pytest expansion
  and isolation guards. Reuse its public contracts rather than copying them.
- Keep report source run/attempt/head identities correct. Unknown timings are
  not zero; runner estimates are not billing. Preserve raw evidence and state
  attribution when publishing [performance claims](docs/benchmarks/2026-10-22.md).
- Skills are portable instructions, not an application dependency. Validate
  referenced commands and adoption examples; avoid prose-matching tests.
