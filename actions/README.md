# CI-esta actions

Use `gigaverse-app/ci-esta/actions/NAME@REF` for individual actions, such as
`gigaverse-app/ci-esta/actions/plan-pytest-shards@main`.
The root `gigaverse-app/ci-esta@REF` action produces CI reports.

See the [action reference and version availability](../docs/actions.md) for
inputs, outputs and compatible pins, or start with the
[complete quickstart workflows](../docs/quickstart.md).

These entry points are generated from the canonical implementations in
`.github/actions/`. Run `uv run python scripts/public_actions.py` after changing
an action's metadata. Existing top-level named paths remain compatibility aliases.
