# Failure-canary planner toolchain

The action selects whole pytest files from prior JUnit failures. Planning must
preserve a caller's existing uv executable: consumers pin uv for dependency export
and test behavior. Discovery uses an executable on PATH; setup-uv runs only when
none exists. The isolated `uv run --no-project` planner still owns its Python and
small parsing dependencies, without changing the consumer's installed environment.

`canary-toolchain-smoke.yaml` exercises the real composite action on a hosted
runner with uv 0.9.1, a failed-file fixture, and path/version/SHA256 checks after
planning. `tests/testing/test_canary_toolchain.py` also exercises discovery with
and without a caller uv. Consumers should not restore uv after invoking this
action; their ordinary initial toolchain pin remains authoritative.
