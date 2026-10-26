# Publishing CI-esta

The Python distribution is `ci-esta`; imports use `ci_esta`. Package versions
come from `pyproject.toml` and must match the GitHub release tag, such as `v1.0.0`.

PyPI Trusted Publishing uses owner `gigaverse-app`, repository `ci-esta`,
workflow `release.yml`, and GitHub environment `pypi`. No API token is needed.

1. Let Release Please open or update the release PR, which updates the version,
   changelog and the root package entry in `uv.lock`. Review it and require green CI.
2. Merge the release PR when ready to publish. After successful main CI,
   Release Please creates the version-matching tag and GitHub release.
3. The publish workflow repeats the full Python test lanes without evidence
   reuse, checks metadata, and installs both wheel and source distribution.
4. Only the tested artifacts are uploaded to PyPI with attestations. The
   publishing job has no checkout or build and alone receives OIDC permission.
5. Verify a clean install of the exact version and exercise `ci-esta --help`
   and `ci-esta-pytest pools` outside the source checkout.

After successful publication, the workflow advances `v2`, the explicitly declared
Actions API major in `release.yml`. It is independent of the Python package's
version. Consumers use `gigaverse-app/ci-esta/actions/NAME@v2`.
The v1 alias remains on the compatible 1.6.2 release. V2 removes the Bun
JavaScript imports and replaces `selection-module` with `python-path`; follow
[the Bun migration recipe](docs/bun-test-selection.md) before changing pins.
Do not advance v1 to this incompatible interface.
Python consumers declare their own compatible package
range and keep exact artifacts in lockfiles.

Only canonical `actions/NAME` paths are supported by this Actions API. When
upgrading older callers, migrate `.github/actions/NAME` or top-level `NAME` to
`actions/NAME`. The initial namespace migration is deliberately included in the
1.x line. Later incompatible Actions API changes require an explicit new Actions
major; Python package version changes alone never change that alias.

Full package release tags remain immutable. Prereleases do not advance the Actions
alias. Python package fixes require a new package release and successful
validation/publication. For an Actions-only change, advance `v2` to the merged
commit after its main CI and public action smoke pass. This does not require a
GitHub release, Python version change, or PyPI publication.

## Conventional Commits to PyPI

[Release Please](https://github.com/googleapis/release-please-action) owns version
calculation and the release PR. `.github/workflows/release-please.yml` runs after
successful push CI on the current `main` head. Ordinary feature/fix merges update
the pending release PR; merging that PR is the publishing decision.

| Commit header | Version change |
| --- | --- |
| `fix:`, `perf:`, `revert:` | Patch, such as 0.1.2 to 0.1.3 |
| `feat:` | Minor, such as 0.1.2 to 0.2.0 |
| `feat!:`, `fix!:`, or a `BREAKING CHANGE:` footer | Minor below 1.0; major at 1.0 and later |
| `docs:`, `style:`, `refactor:`, `test:`, `build:`, `ci:`, `chore:` without breaking changes | No release on their own |

Squash with the checked PR title and retain breaking-change details in the body.
No automatic publishing happens just because an ordinary feature PR merges.

```text
Conventional Commit -> successful main CI -> Release Please release PR
Maintainer merges release PR -> successful main CI -> tag + GitHub release
GitHub release -> Publish -> exact-tag full CI -> tested artifacts -> PyPI OIDC
```

The Python release strategy updates `pyproject.toml` and `CHANGELOG.md`; its
standard TOML extra-file updater changes only this project's version in
`uv.lock`. Dependency versions are not upgraded. The manifest starts at the
existing published version, and `bootstrap-sha` bounds the first release's
history to that release commit.

## Release automation setup and recovery

The `release-automation` environment permits only the `main` branch. Share the
existing organization `GV_CI_CROSS_REPO_TOKEN` secret with this repository;
the credential needs Contents and Pull requests write access. It creates release
PRs and GitHub releases so their events trigger the normal CI and Publish
workflows. Do not replace it with `GITHUB_TOKEN`, which suppresses those events.
The existing `pypi` environment remains restricted to `v*` tags.

PyPI authentication remains [Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/):
no PyPI API token is stored. The publisher identity remains this repository's
`release.yml` workflow and `pypi` environment. Only its isolated upload job
receives `id-token: write`.

If release preparation fails, fix the cause and rerun the successful main CI run
to trigger Release Please again. If publication fails after a tag was created,
rerun the failed Publish run, or dispatch Publish on that exact `v<version>`
tag. It rechecks the tag/version match and full CI before uploading. Never move
an existing full release tag or reuse a published version for changed contents.
Prereleases remain a deliberate manual version/tag/release path; this automation
proposes normal SemVer releases.

To deliberately graduate to a major release, retain a `Release-As: 1.0.0`
footer in the merged commit body. Release Please prepares the version, lockfile
and changelog together; no permanent version override is needed in its config.

## Avoiding duplicate validation

Ordinary main pushes can reuse the merged PR's successful test and public-action
receipts when the complete declared inputs match. A strict version-only release
PR can reuse the same runtime proof from its validated base. Dependency, source,
test, workflow or inconsistent version changes retain full validation; so do
missing proof, newer failures, API uncertainty and explicit full reruns.

Release PRs still build and validate package metadata and install both wheel and
source distribution. The Publish workflow continues to validate the exact tag
and run full CI before uploading its distributions. See the opt-in contracts in
[the evidence reuse guide](docs/evidence-reuse.md).
