# Publishing CI-esta

The Python distribution is `ci-esta`; imports use `ci_esta`. Package versions
come from `pyproject.toml` and must match the GitHub release tag, such as `v0.1.0`.

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

After successful publication, the workflow advances the compatible Actions tag
(for example, `v0.1`). Consumers use `@v0.1` for Actions and requirements such as
`ci-esta>=0.1.0,<0.2.0` for Python. Lockfiles retain exact resolved artifacts.
Prereleases do not advance the compatible tag. Published package versions and
full release tags are never replaced; fixes require a new patch release.

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
