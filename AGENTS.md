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

## Commits and pull requests

- Use Conventional Commits for commits you create and PR titles:
  `type(optional-scope): description`, for example
  `fix(parser): handle empty input`.
- Allowed types: `feat`, `fix`, `perf`, `revert`, `docs`, `style`,
  `refactor`, `test`, `build`, `ci`, and `chore`. Choose the type for the
  actual change. Mark breaking changes with `!` before the colon and explain
  the migration in the PR body.
- Repair an invalid PR title in place. Preserve useful work; do not close or
  replace the PR, or rewrite existing commits just to satisfy the title check.
- Squash merges use the checked PR title. Keep any `BREAKING CHANGE:` details
  in the body. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and
  [RELEASING.md](RELEASING.md).

## Releases

Release Please derives versions and changelogs from Conventional Commits. Let
it prepare the release PR; do not hand-edit versions for ordinary changes.
Merging a release PR authorizes PyPI publication after CI. Follow RELEASING.md.

## Shared agent instructions

Edit this root `AGENTS.md` as the single source for Codex and Claude.
`CLAUDE.md` is an AgentSync-managed relative symlink to this file, not a
separate instruction document. The configuration is
[agentsync.toml](agentsync.toml). To restore and verify the link:

```bash
npx --yes @dallay/agentsync@1.52.3 apply
npx --yes @dallay/agentsync@1.52.3 status
```

Keep the symlink tracked in Git. See CONTRIBUTING.md for platform setup.

## Documentation-only CI

Documentation-only PRs execute zero tests unless a test or lane explicitly
declares that documentation as an input. This includes CI contract tests,
installed-wheel smoke and public-action smoke. Metadata/link/build checks may
still validate documentation without running runtime tests. Declare execution
workflows, selector configuration, helpers, locks and non-import inputs; missing
history or failed planning must execute the full affected lanes and fail the
required planning gate. Ordinary PRs and pushes use selection; manual/release/scheduled/full overrides
remain complete checkpoints.
