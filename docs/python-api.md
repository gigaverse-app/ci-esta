# Supported Python API

Prefer the CLI and the published actions. When a repository's own CI checks need
Python, import only the names below. They are the adopter contract: each one is
imported by at least one adopting repository, and `tests/test_python_api.py`
imports every name in this table, so removing or renaming one fails CI.
Any other module or name, including module constants and regular expressions,
is internal and can change in any release.

## Stability rules

- Removing or renaming a name below is a breaking change (`feat!`). Keep the old
  name as an alias for at least one minor release first, and list it under
  **Deprecated** with its replacement.
- Changing what a command or function reports for the same repository is a
  `feat`, never a `fix`, even when the old answer was wrong. For example,
  when the Bun reader check starts flagging more files, an adopter's selection
  can fall back to the full suite until it adds declarations. The release notes
  must say what to run, such as `ci-esta bun-declarations`.
- Adding a name here requires an adopter that imports it, so the list stays the
  real contract rather than a wish list.

## Bun test selection

| Module | Names |
| --- | --- |
| `ci_esta.testing.bun.models` | `SelectionRequest`, `RunRequest`, `BunExecution`, `ReportContext` |
| `ci_esta.testing.bun.selection` | `plan_affected_tests`, `read_inventory` |
| `ci_esta.testing.bun.execution` | `run_bun_tests` |
| `ci_esta.testing.bun.report` | `work_selection_report` |
| `ci_esta.testing.work_plan` | `plan_work` |

Check Bun dependency declarations with `ci-esta bun-declarations --strict`
rather than re-implementing the reader scan; see
[dependency declarations](dependency-declarations.md#start-with-the-audit).

## Workflow and policy checks

| Module | Names |
| --- | --- |
| `ci_esta.testing.gha_expressions` | `Context`, `evaluate`, `evaluate_value`, `pull_request_event`, `schedule_event`, `workflow_dispatch_event` |
| `ci_esta.testing.test_policy` | `plan_workflow` |
| `ci_esta.testing.workflow_policy` | `assert_no_cancel_immune_jobs`, `assert_pr_triggers_ignore_base_branch` |
| `ci_esta.testing.import_boundary_config` | `ImportBoundaryConfig`, `discover_services`, `load_import_boundary_layout` |
| `ci_esta.testing.canary_action` | `CanaryConfig`, `build_canary` |
| `ci_esta.testing.cli` | `main` |
| `ci_esta.policy` | `ExecutionPlan`, `Policy`, `Request`, `plan` |
| `ci_esta.policy.defaults` | `profile_for_run` |
| `ci_esta.policy.models` | `Occasion` |
| `ci_esta.policy.pytest_metadata` | `marker_expr_matches` |
| `ci_esta.workflow_inputs` | (module) |
| `ci_esta.resources` | `source_root` |

## Reports and evidence

| Module | Names |
| --- | --- |
| `ci_esta.ci_observability.work_selection` | `WorkSelectionV1` |
| `ci_esta.ci_observability.workflow_graph` | `dependencies` |
| `ci_esta.image_evidence` | `Layer`, `LayerComparison`, `compare_layers`, `parse_digest`, `redact`, `sanitize` |
| `ci_esta.image_evidence.nodes` | `NodeProbeConfig`, `run_node_probes` |
| `ci_esta.image_evidence.observer` | `write_observer` |
| `ci_esta.image_evidence.plan` | `prepare_pull_plan` |
| `ci_esta.image_evidence.runtime` | `FileFingerprint`, `file_inventory`, `validate_bytecode` |

## Module commands

These run with `python -m`, as well as through the `ci-esta` entry point:
`ci_esta.cli`, `ci_esta.workflow_inputs`, `ci_esta.diagnostics` and
`ci_esta.ci_observability.enrichment`.

## Deprecated

None.
