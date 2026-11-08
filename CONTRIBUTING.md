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

## Conventional Commits

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
for commits you create and PR titles (the squash commit that lands on `main`):

```text
fix(parser): handle empty input
feat: add a new output format
feat(api)!: remove the deprecated argument
docs: clarify installation
```

Allowed types are `feat`, `fix`, `perf`, `revert`, `docs`, `style`,
`refactor`, `test`, `build`, `ci`, and `chore`. Scope is optional.
Use `!` before the colon for breaking changes and explain the migration in the
PR body. Choose the type for the actual change, since release tooling uses it.

The `conventional-commit` check uses
[amannn/action-semantic-pull-request](https://github.com/amannn/action-semantic-pull-request).
It reads PR metadata, including for forks, without checking out contributor code.
If it fails on a title, rename the PR; the edited event reruns the check.
Keep the existing PR and commits. Work-in-progress commits need not be rewritten.

Use **Squash and merge**, with the PR title as the commit title. Check the final
message before merging, including single-commit PRs, and preserve any
`BREAKING CHANGE:` explanation in the body. The repository's squash defaults
support this, but a maintainer can still edit the final message.
Release Please turns these commits into a release PR containing the version,
changelog, and lockfile update. Merging that PR authorizes PyPI publication after
CI. See [RELEASING.md](RELEASING.md) for the version rules and publishing.

## Shared instructions for Codex and Claude

[AGENTS.md](AGENTS.md) is the canonical repository guidance. Codex reads it
directly; Claude reads the tracked `CLAUDE.md -> AGENTS.md` symlink. Edit
`AGENTS.md` once, including commit-policy changes, so both tools receive the
same instructions.

[dallay/agentsync](https://github.com/dallay/agentsync) manages that link through
[agentsync.toml](agentsync.toml). After cloning, or to repair a
missing or stale link, run these commands from the repository root with Node.js
18+ and npm installed:

```bash
npx --yes @dallay/agentsync@1.52.3 apply
npx --yes @dallay/agentsync@1.52.3 status
```

The CLI version is pinned for reproducible setup. Review and update both commands
when upgrading AgentSync. The configuration disables managed gitignore changes
because we intentionally commit the relative link, following AgentSync's
[committed-destination workflow](https://dallay.github.io/agentsync/guides/gitignore-team-workflows/).
Ordinary instruction edits propagate immediately through the link.

On native Windows, enable Developer Mode and Git symlink support
(`git config core.symlinks true`), then run `apply` to repair a checkout that
materialized the link as plain text. Alternatively, use WSL for a checkout in
the Linux filesystem. See the
[Windows setup guide](https://dallay.github.io/agentsync/guides/windows-symlink-setup/).
If AgentSync backs up an existing `CLAUDE.md`, review and preserve any unique
guidance in `AGENTS.md`; do not commit the backup as another instruction source.

## Documentation-only CI

Documentation-only PRs execute zero tests unless a test or lane explicitly
declares that documentation as an input. This includes CI contract tests,
installed-wheel smoke and public-action smoke. Metadata/link/build checks may
still validate documentation without running runtime tests. Declare execution
workflows, selector configuration, helpers, locks and non-import inputs; missing
history or failed planning must execute the full affected lanes and fail the
required planning gate. Ordinary PRs and pushes use selection; manual/release/scheduled/full overrides
remain complete checkpoints.

[`.github/test-lanes.json`](.github/test-lanes.json) has two lanes:

| Lane | Runs | Selected by |
|---|---|---|
| `tests` | Test suite, Python compatibility, runtime contracts, public-action smoke | `src/`, `scripts/`, `tests/`, `actions/README.md` (read by action tests) and the global inputs |
| `package` | `uv build`, `twine check`, wheel and sdist smoke, the `distributions` artifact | `src/`, `scripts/ci/`, `pyproject.toml`, `uv.lock`, and the packaged `README.md` and `LICENSE` |

Both lanes also run for every global input: environment files, CI workflows,
selector configuration and every non-Markdown file under `actions/` and
`examples/`. The `*[!d]`, `*[!m]d` and `*[!.]md` patterns are fnmatch's way of
saying "not `.md`", so a new script type is an input without a list update,
while action and example READMEs are not. `graph.global_inputs` names the real
test environment (`pyproject.toml`, `uv.lock`, `.python-version`) and replaces
pytest-selective's default, which counts `documentation/requirements*.txt` as
one. The `quality` job always lints; it builds only when `package` is selected.

So a change to `docs/`, `documentation/`, `mkdocs.yml` or an action or example
README runs no tests and no build. A root `README.md` change runs only the
`package` checks, because PyPI renders it. `tests/ci/test_repository_routing.py`
pins this on real Git commits, and `tests/ci/test_execution_admission.py` fails
if a test, build or smoke command loses its lane condition or names an unknown lane.

## Duplication audit

The required `dry-lint` check accepts existing pairs recorded in `.dry-lint/baseline.json`
and fails on new blocking duplicates or incomplete judging. The weekly **dry-lint audit**
workflow publishes a read-only audit in its job summary and artifacts. Humans and agents
choose refactors and open their own PRs; dry-lint does not change application code or open PRs.

With your Anthropic credential in `ANTHROPIC_API_KEY`, install dry-lint from `main` until its v1 launch:

```bash
uv tool install 'dry-lint[anthropic] @ git+https://github.com/gigaverse-app/dry-lint@main'
dry-lint sweep --budget-usd 5 --report audit.json --output audit.md
# Review findings, refactor selected code, and run its tests before updating the baseline.
dry-lint sweep --update --budget-usd 5 --readme README.md --repository gigaverse-app/ci-esta
```

Commit the baseline, progress JSON and README with the refactor. Do not commit the raw audit
files; CI retains reports as artifacts. Cleanup counts are duplicate pairs, not lines of code.
Suppressed findings are counted as dismissed, and never credited as cleanup. See the
[dry-lint sweep guide](https://github.com/gigaverse-app/dry-lint/blob/main/docs/sweeps.md).
