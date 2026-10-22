# Source provenance

Extracted from Gigaverse backend-common at `d4da0ef72199a73eabc8ca1d90e5bcd956955832` with repository-owner authorization to publish. No source repository history is included. CI-esta is licensed under Apache-2.0.

`tests/ci/test_incremental_evidence.py` additionally preserves the resolver tests and shared harness from `tests/ci/test_security_workflow.py` at that same revision. Consumer-specific tests remain with their source workflows. New portable-input, CLI and gate-selection regressions were added during extraction. Selection explanation models are imported from pytest-selective at the immutable revision in `pyproject.toml` rather than copied here.

Name check on 2026-10-22: the `ci-esta` PyPI and npm JSON endpoints returned HTTP 404, the target GitHub repository did not exist, and searches found no CI product under that spelling. The unhyphenated name has unrelated GitHub users/projects. These checks establish observed availability, not trademark clearance or a guarantee that a registry will accept a future publication. No package was published merely to reserve a name.

Initial source paths:

- `.github/actions/ci-observability/action.yml`
- `.github/actions/ci-observability/ci-observability-v1.schema.json`
- `.github/actions/collect-pr-changes/action.yml`
- `.github/actions/publish-prometheus-snapshot/action.yml`
- `.github/actions/publish-prometheus-snapshot/publish.py`
- `.github/actions/resolve-incremental-pr-base/action.yml`
- `.github/actions/resolve-incremental-pr-base/resolve.cjs`
- `.github/actions/resolve-lane-evidence/action.yml`
- `.github/actions/resolve-lane-evidence/inputs.cjs`
- `.github/actions/validation-gate/action.yml`
- `.github/actions/validation-gate/gate.cjs`
- `src/backend_common/ci_observability/__init__.py`
- `src/backend_common/ci_observability/action.py`
- `src/backend_common/ci_observability/enrichment/__init__.py`
- `src/backend_common/ci_observability/enrichment/__main__.py`
- `src/backend_common/ci_observability/enrichment/ai.py`
- `src/backend_common/ci_observability/enrichment/backend/__init__.py`
- `src/backend_common/ci_observability/enrichment/backend/artifacts.py`
- `src/backend_common/ci_observability/enrichment/backend/github.py`
- `src/backend_common/ci_observability/enrichment/backend/legacy.py`
- `src/backend_common/ci_observability/enrichment/backend/models.py`
- `src/backend_common/ci_observability/enrichment/cli.py`
- `src/backend_common/ci_observability/enrichment/models.py`
- `src/backend_common/ci_observability/enrichment/primitives.py`
- `src/backend_common/ci_observability/enrichment/profiles.py`
- `src/backend_common/ci_observability/enrichment/prometheus.py`
- `src/backend_common/ci_observability/github.py`
- `src/backend_common/ci_observability/markdown.py`
- `src/backend_common/ci_observability/models.py`
- `src/backend_common/ci_observability/report.py`
- `src/backend_common/ci_observability/ruff.toml`
- `src/backend_common/ci_observability/selection.py`
- `tests/ci/github_rest_fake.cjs`
- `tests/ci/github_script_rest_surface.json`
- `tests/ci/test_pr_change_evidence.py`
- `tests/ci/test_validation_gate.py`
- `tests/ci_observability/__init__.py`
- `tests/ci_observability/builders.py`
- `tests/ci_observability/test_action.py`
- `tests/ci_observability/test_action_metadata.py`
- `tests/ci_observability/test_enrichment_ai.py`
- `tests/ci_observability/test_enrichment_backend.py`
- `tests/ci_observability/test_enrichment_cli.py`
- `tests/ci_observability/test_enrichment_profiles.py`
- `tests/ci_observability/test_github.py`
- `tests/ci_observability/test_report.py`
- `tests/ci_observability/test_selection.py`
- `tests/github_actions/test_publish_prometheus_snapshot_action.py`

The complete-toolkit extraction uses backend-common revision `b6a2de0f58f18b78e544568d9ebd7371c8c30370`; `docs/migration-inventory.json` maps the additional source files. Original Apache-2.0 ownership and notices are retained.
