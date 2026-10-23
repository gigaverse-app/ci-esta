# Publishing CI-esta

The Python distribution is `ci-esta`; imports use `ci_esta`. Package versions
come from `pyproject.toml` and must match the GitHub release tag, such as `v0.1.0`.

PyPI Trusted Publishing uses owner `gigaverse-app`, repository `ci-esta`,
workflow `release.yml`, and GitHub environment `pypi`. No API token is needed.

1. Update the version, changelog and lockfile in a PR; require green CI.
2. Merge and publish a GitHub release at its version-matching tag. Normal
   versions are regular releases; alpha, beta and release candidates are prereleases.
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
