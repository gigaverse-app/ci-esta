import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


INCREMENTAL_BASE_RESOLVER = ROOT / "actions/resolve-incremental-pr-base/resolve.cjs"


SECURITY_TRIGGER_ACTION = ROOT / "actions/resolve-security-trigger/action.yml"


STRICT_FAKE = ROOT / "tests/ci/github_rest_fake.cjs"


CURRENT_HEAD_SHA = "f" * 40


FALLBACK_BASE_SHA = "0" * 40


SUCCESSFUL_ANCESTOR_SHA = "a" * 40


FAILED_ANCESTOR_SHA = "b" * 40


UNRELATED_PR_SHA = "c" * 40


DIVERGED_SHA = "d" * 40


OLDER_ANCESTOR_SHA = "e" * 40


PULL_REQUEST_NUMBER = 42


WORKFLOW_ID = 1234


CURRENT_TIME = "2026-09-02T12:00:00Z"


RECENT_SUCCESS_TIME = "2026-09-01T12:00:00Z"


STALE_SUCCESS_TIME = "2026-08-20T12:00:00Z"


def _resolve_incremental_base(test_input: dict[str, object]) -> dict[str, object]:
    node_script = r"""
const input = JSON.parse(process.env.RESOLVER_TEST_INPUT);
const { resolveIncrementalPrBase } = require(process.argv[1]);
const warnings = [];
const calls = { commitRefs: [], checkRefs: [], runIds: [] };
const reads = [];
const { strictGithub } = require(process.env.GITHUB_REST_FAKE);
const github = strictGithub({
    actions: {
      getWorkflowRun: async ({ run_id }) => {
        reads.push(`run:${run_id}`);
        if (input.failAt === "current-run") throw new Error("workflow API unavailable");
        if (run_id === 9999) return { data: { id: run_id, workflow_id: input.workflowId } };
        calls.runIds.push(run_id);
        const run = input.runs.find((candidate) => candidate.id === run_id);
        if (!run) throw new Error(`missing run ${run_id}`);
        return { data: { ...run, workflow_id: input.workflowId } };
      },
      listWorkflowRuns: async () => (reads.push("runs"), {
        data: {
          workflow_runs: (input.indexedRuns ?? input.runs).map((run) => ({
            ...run,
            workflow_id: input.workflowId,
          })),
        },
      }),
      listJobsForWorkflowRun: async ({ run_id }) => {
        reads.push(`jobs:${run_id}`);
        if (input.failAt === "jobs") throw new Error("jobs API unavailable");
        return { data: {
          jobs: input.jobsByRun?.[run_id] ?? [
            { name: "Security evidence", conclusion: "success" },
          ],
        }};
      },
    },
    checks: {
      listForRef: async ({ ref }) => {
        calls.checkRefs.push(ref);
        reads.push(`checks:${ref}`);
        return { data: { check_runs: input.checkRuns?.[ref] ?? [] } };
      },
    },
    repos: {
      listCommitStatusesForRef: async () => ({ data: input.commitStatuses ?? [] }),
      getCommit: async ({ ref }) => {
        calls.commitRefs.push(ref);
        return { data: {
          parents: (input.commitParents?.[ref] ??
            (ref === input.headSha ? input.firstParentSha : undefined))
            ? [{ sha: input.commitParents?.[ref] ?? input.firstParentSha }]
            : [],
        } };
      },
      compareCommitsWithBasehead: async ({ basehead }) => {
        const comparison = input.comparisons[basehead];
        if (!comparison && basehead.endsWith(`...${input.fallbackBaseSha}`)) {
          return { data: { status: "diverged" } };
        }
        if (!comparison) throw new Error(`missing comparison for ${basehead}`);
        return { data: comparison };
      },
    },
});
const context = {
  serverUrl: "https://github.com",
  repo: { owner: "gigaverse-app", repo: "example" },
  runId: 9999,
  payload: { before: input.previousHeadSha },
};
const infos = [];
const proofs = [];
const core = { warning: (message) => warnings.push(message), info: (message) => infos.push(message) };
(async () => {
  const evidenceCache = new Map();
  const results = [];
  for (const evidenceJobName of input.lanes ?? [input.evidenceJobName ?? "Security evidence"]) {
  results.push(await resolveIncrementalPrBase({
    evidenceCache,
    onReuse: ({run, jobs}) => {
      if (input.failTelemetry) throw Error('telemetry unavailable');
      proofs.push({run: run.id, jobs: jobs.map(job => job.name)});
    },
    github,
    context,
    core,
    fallbackBaseSha: input.fallbackBaseSha,
    headSha: input.headSha,
    headRef: "feature/security-ci",
    pullRequestNumber: input.pullRequestNumber,
    evidenceJobName,
    evidenceStepName: input.evidenceStepName ?? "",
    pytestEvidence: input.pytestEvidence,
    validationEvidence: input.validationEvidence ?? false,
    sameHeadOnly: input.sameHeadOnly ?? false,
    conservativeFailures: input.conservativeFailures ?? false,
    cancelledRunEvidenceJobPatterns: input.cancelledRunEvidenceJobPatterns ?? [],
    maxAgeHours: 168,
    nowMs: Date.parse(input.currentTime),
  }));
  }
  const result = input.lanes ? results : results[0];
  process.stdout.write(JSON.stringify({ result, warnings, calls, infos, reads, proofs }));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    completed = subprocess.run(
        ["node", "-e", node_script, str(INCREMENTAL_BASE_RESOLVER)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "RESOLVER_TEST_INPUT": json.dumps(test_input), "GITHUB_REST_FAKE": str(STRICT_FAKE)},
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize("workflow_conclusion", ["success", "failure", "cancelled"])
@pytest.mark.parametrize(
    "variant", ["valid", "ancestor", "missing-receipt", "failed", "skipped", "rerun", "other-pr", "stale"]
)
def test_same_head_lane_requires_its_own_fresh_success(workflow_conclusion: str, variant: str) -> None:
    """
    A sibling failure does not erase proof; a changed tested tree does.

    The receipt, not the head commit, names what was tested. An earlier head whose run
    carries the same receipt tested the same inputs: that is how a retag commit, which only
    moves a first-party pin to an identical tree, reuses every lane.
    """
    result = _resolve_incremental_base(_same_head_lane_scenario(workflow_conclusion, variant))["result"]
    proven = variant in {"valid", "ancestor"}
    assert result == {"baseSha": CURRENT_HEAD_SHA if proven else FALLBACK_BASE_SHA, "reused": proven}


@pytest.mark.parametrize("variant", ["valid", "ancestor", "failed", "missing-receipt", "rerun"])
def test_reuse_measurement_names_only_the_admitted_proof(variant):
    observed = _resolve_incremental_base(_same_head_lane_scenario("success", variant))
    assert observed["proofs"] == ([{"run": 1, "jobs": ["Search validation"]}]
                                  if variant in {"valid", "ancestor"} else [])


def test_measurement_sink_failure_cannot_change_admission():
    scenario = _same_head_lane_scenario("success", "valid")
    scenario["failTelemetry"] = True
    observed = _resolve_incremental_base(scenario)
    assert observed["result"]["reused"] is True
    assert any("telemetry unavailable" in message for message in observed["warnings"])


SAME_HEAD_REJECTION = {
    "missing-receipt": "no successful step 'Validated inputs merge-tree-sha'",
    "failed": "'Search validation' concluded failure",
    "skipped": "'Search validation' concluded skipped",
    "rerun": "attempt 2",
    "other-pr": f"not associated with PR #{PULL_REQUEST_NUMBER}",
    "stale": "completed before",
}


@pytest.mark.parametrize("variant", sorted(SAME_HEAD_REJECTION))
def test_every_rejected_same_head_candidate_is_logged_with_its_reason(variant: str) -> None:
    """A silent fallback hid that same-head reuse never fired; each rejection now says why."""
    infos = _resolver_infos(_resolve_incremental_base(_same_head_lane_scenario("success", variant)))

    assert any("run 1" in line and SAME_HEAD_REJECTION[variant] in line for line in infos), infos


def test_a_reused_same_head_candidate_logs_no_rejection() -> None:
    """CONTROL: valid evidence is reused and not reported as rejected."""
    outcome = _resolve_incremental_base(_same_head_lane_scenario("success", "valid"))

    assert outcome["result"] == {"baseSha": CURRENT_HEAD_SHA, "reused": True}
    assert not [line for line in _resolver_infos(outcome) if "rejected" in line]


def _resolver_infos(outcome: dict[str, object]) -> list[str]:
    infos = outcome["infos"]
    assert isinstance(infos, list)
    return [str(line) for line in infos]


def _same_head_lane_scenario(workflow_conclusion: str, variant: str) -> dict[str, object]:
    receipt = "Validated inputs merge-tree-sha"
    return {
        "workflowId": WORKFLOW_ID,
        "runs": [
            {
                "id": 1,
                "status": "completed",
                "conclusion": workflow_conclusion,
                "head_sha": SUCCESSFUL_ANCESTOR_SHA if variant == "ancestor" else CURRENT_HEAD_SHA,
                "run_attempt": 2 if variant == "rerun" else 1,
                "updated_at": STALE_SUCCESS_TIME if variant == "stale" else RECENT_SUCCESS_TIME,
                "pull_requests": [{"number": 999 if variant == "other-pr" else PULL_REQUEST_NUMBER}],
            }
        ],
        "jobsByRun": {
            "1": [
                {
                    "name": "Search validation",
                    "conclusion": {"failed": "failure", "skipped": "skipped"}.get(variant, "success"),
                    "steps": [
                        {
                            "name": "Validated inputs other-tree" if variant == "missing-receipt" else receipt,
                            "conclusion": "success",
                        }
                    ],
                }
            ]
        },
        "comparisons": {
            f"{CURRENT_HEAD_SHA}...{CURRENT_HEAD_SHA}": {"status": "identical"},
            f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"},
        },
        "fallbackBaseSha": FALLBACK_BASE_SHA,
        "headSha": CURRENT_HEAD_SHA,
        "pullRequestNumber": PULL_REQUEST_NUMBER,
        "currentTime": CURRENT_TIME,
        "evidenceJobName": "Search validation",
        "evidenceStepName": receipt,
        "sameHeadOnly": True,
    }


@pytest.mark.parametrize("attempt", [1, 2])
@pytest.mark.parametrize("latest", ["failure", "skipped"])
def test_newer_lane_failure_revokes_older_same_head_success(attempt: int, latest: str) -> None:
    receipt = "Validated inputs same-tree"
    runs = [
        {
            "id": number,
            "status": "completed",
            "conclusion": "failure",
            "head_sha": CURRENT_HEAD_SHA,
            "run_attempt": attempt if number == 2 else 1,
            "updated_at": RECENT_SUCCESS_TIME,
            "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
        }
        for number in [1, 2]
    ]
    result = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": runs,
            "jobsByRun": {
                "1": [
                    {
                        "name": "Search validation",
                        "conclusion": "success",
                        "steps": [{"name": receipt, "conclusion": "success"}],
                    }
                ],
                "2": [{"name": "Search validation", "conclusion": latest, "steps": []}],
            },
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
            "evidenceJobName": "Search validation",
            "evidenceStepName": receipt,
            "sameHeadOnly": True,
        }
    )["result"]
    assert result == {
        "baseSha": CURRENT_HEAD_SHA if latest == "skipped" else FALLBACK_BASE_SHA,
        "reused": latest == "skipped",
    }


@pytest.mark.parametrize("tested_head", [SUCCESSFUL_ANCESTOR_SHA, CURRENT_HEAD_SHA])
@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
@pytest.mark.parametrize("variant", ["valid", "wrong-run", "wrong-context", "wrong-description", "failed", "rerun"])
def test_successful_pytest_gate_is_bound_to_its_first_workflow_attempt(
    conclusion: str, variant: str, tested_head: str
) -> None:
    """
    A completed zero-test gate survives cancellation; another run's status is not evidence.

    Same-head reruns are admitted as candidates so their failures can revoke older evidence, and
    every attempt of a run shares one URL, so the status must not let a rerun prove success.
    """
    status = {
        "context": "ci-observability/python-tests",
        "state": "success",
        "target_url": "https://github.com/gigaverse-app/example/actions/runs/1",
        "description": f"Default gate passed; base={FALLBACK_BASE_SHA}",
    }
    replacements = {
        "wrong-run": ("target_url", "https://github.com/gigaverse-app/example/actions/runs/2"),
        "wrong-context": ("context", "ci-observability/type-check"),
        "wrong-description": ("description", "Default gate passed"),
        "failed": ("state", "failure"),
    }
    if variant in replacements:
        key, value = replacements[variant]
        status[key] = value
    result = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": 1,
                    "status": "completed",
                    "conclusion": conclusion,
                    "head_sha": tested_head,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "run_attempt": 2 if variant == "rerun" else 1,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "commitStatuses": [status],
            "jobsByRun": {"1": []},
            "comparisons": {
                f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"},
                f"{CURRENT_HEAD_SHA}...{CURRENT_HEAD_SHA}": {"status": "identical"},
            },
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
            "evidenceJobName": "Run pytest (* concurrent shards)",
            "pytestEvidence": {
                "planJobName": "Plan tests",
                "completionStepName": "Record reusable pytest completion",
                "successStatusContext": "ci-observability/python-tests",
            },
        }
    )["result"]
    assert result == {
        "baseSha": tested_head if variant == "valid" else FALLBACK_BASE_SHA,
        "reused": variant == "valid",
    }


@pytest.mark.parametrize("workflow_conclusion", ["success", "failure", "cancelled"])
@pytest.mark.parametrize("test_conclusion", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("receipt", ["success", "failure", "skipped"])
@pytest.mark.parametrize("attempt", [1, 2])
def test_pytest_evidence_is_independent_but_requires_complete_first_attempt(
    workflow_conclusion: str, test_conclusion: str, receipt: str, attempt: int
) -> None:
    """Other jobs cannot erase completed tests or turn incomplete tests into proof."""
    result = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": 1,
                    "status": "completed",
                    "conclusion": workflow_conclusion,
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "run_attempt": attempt,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "jobsByRun": {
                "1": [
                    {"name": "Plan tests", "conclusion": "success"},
                    {
                        "name": "Run pytest (2 concurrent shards)",
                        "conclusion": test_conclusion,
                        "steps": [{"name": "Record reusable pytest completion", "conclusion": receipt}],
                    },
                ]
            },
            "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
            "evidenceJobName": "Run pytest (* concurrent shards)",
            "pytestEvidence": {"planJobName": "Plan tests", "completionStepName": "Record reusable pytest completion"},
        }
    )["result"]
    proven = attempt == 1 and receipt == "success" and test_conclusion in {"success", "failure"}
    if not proven:
        assert result == {"baseSha": FALLBACK_BASE_SHA, "reused": False}
    elif test_conclusion == "success":
        assert result == {"baseSha": SUCCESSFUL_ANCESTOR_SHA, "reused": True}
    else:
        # A failed candidate is NOT a reusable base until all failure artifacts validate.
        assert result == {
            "baseSha": FALLBACK_BASE_SHA,
            "reused": False,
            "failedSha": SUCCESSFUL_ANCESTOR_SHA,
            "failedRunId": 1,
            "failedShardCount": 2,
        }


def test_incremental_pr_base_reuses_only_a_successful_same_pr_ancestor():
    """INVARIANT: prior work is reusable only when this workflow proved that exact PR head."""
    runs = [
        {
            "id": 1,
            "status": "completed",
            "conclusion": "success",
            "head_sha": DIVERGED_SHA,
            "updated_at": RECENT_SUCCESS_TIME,
            "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
        },
        {
            "id": 2,
            "status": "completed",
            "conclusion": "failure",
            "head_sha": FAILED_ANCESTOR_SHA,
            "updated_at": RECENT_SUCCESS_TIME,
            "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
        },
        {
            "id": 3,
            "status": "completed",
            "conclusion": "success",
            "head_sha": UNRELATED_PR_SHA,
            "updated_at": RECENT_SUCCESS_TIME,
            "pull_requests": [{"number": PULL_REQUEST_NUMBER + 1}],
        },
        {
            "id": 4,
            "status": "completed",
            "conclusion": "success",
            "head_sha": SUCCESSFUL_ANCESTOR_SHA,
            "updated_at": RECENT_SUCCESS_TIME,
            "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
        },
    ]
    comparisons = {
        f"{DIVERGED_SHA}...{CURRENT_HEAD_SHA}": {"status": "diverged"},
        f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"},
    }

    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": runs,
            "comparisons": comparisons,
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )

    assert resolved["result"] == {"baseSha": SUCCESSFUL_ANCESTOR_SHA, "reused": True}
    assert resolved["warnings"] == []


def test_incremental_pr_base_rejects_a_recycled_branch_head_already_merged_into_base():
    """INVARIANT: a new PR cannot reuse evidence from an earlier PR on the same branch."""
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": 4,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    # GitHub dynamically re-associates old same-branch runs with
                    # the currently open PR, so this metadata alone is not proof.
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "comparisons": {
                f"{SUCCESSFUL_ANCESTOR_SHA}...{FALLBACK_BASE_SHA}": {"status": "ahead"},
                f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"},
            },
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )

    assert resolved["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}
    assert resolved["warnings"] == []


def test_incremental_pr_base_matches_evidence_below_any_reusable_workflow_caller():
    """INVARIANT: a caller job prefix cannot turn proven work into a full-PR rescan."""
    successful_run_id = 4
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": successful_run_id,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "jobsByRun": {
                str(successful_run_id): [{"name": "validate / Detect and validate CI code", "conclusion": "success"}]
            },
            "evidenceJobName": "Detect and validate CI code",
            "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )

    assert resolved["result"] == {"baseSha": SUCCESSFUL_ANCESTOR_SHA, "reused": True}


def test_incremental_pr_base_reuses_cancelled_run_only_when_every_scanner_succeeded():
    """INVARIANT: cancellation metadata cannot discard complete scanner proof or hide missing proof."""
    cancelled_run_id = 4
    base_input: dict[str, object] = {
        "workflowId": WORKFLOW_ID,
        "runs": [
            {
                "id": cancelled_run_id,
                "status": "completed",
                "conclusion": "cancelled",
                "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                "updated_at": RECENT_SUCCESS_TIME,
                "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
            }
        ],
        "evidenceJobName": "semgrep-oss/scan",
        "cancelledRunEvidenceJobPatterns": ["*Semgrep*", "*Trivy*"],
        "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
        "fallbackBaseSha": FALLBACK_BASE_SHA,
        "headSha": CURRENT_HEAD_SHA,
        "pullRequestNumber": PULL_REQUEST_NUMBER,
        "currentTime": CURRENT_TIME,
    }
    complete = {
        **base_input,
        "jobsByRun": {
            str(cancelled_run_id): [
                {"name": "Scan code · Semgrep / semgrep-oss/scan", "conclusion": "success"},
                {"name": "Scan Python + OS inventories · Trivy", "conclusion": "success"},
            ]
        },
    }
    incomplete = {
        **base_input,
        "jobsByRun": {
            str(cancelled_run_id): [
                {"name": "Semgrep source scan / semgrep-oss/scan", "conclusion": "success"},
                {"name": "Trivy Python + OS inventories", "conclusion": "cancelled"},
            ]
        },
    }

    assert _resolve_incremental_base(complete)["result"] == {
        "baseSha": SUCCESSFUL_ANCESTOR_SHA,
        "reused": True,
    }
    assert _resolve_incremental_base(incomplete)["result"] == {
        "baseSha": FALLBACK_BASE_SHA,
        "reused": False,
    }


def test_incremental_pr_base_fails_open_to_the_pull_request_base():
    """INVARIANT: API uncertainty expands the scan to the whole PR; it never suppresses work."""
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [],
            "comparisons": {},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
            "failAt": "current-run",
        }
    )

    assert resolved["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}
    warnings = resolved["warnings"]
    assert isinstance(warnings, list)
    assert any(isinstance(warning, str) and "falling back" in warning.lower() for warning in warnings)


def test_incremental_pr_base_rejects_a_successful_workflow_without_scan_evidence():
    """INVARIANT: an all-skipped workflow is not proof that security checks passed."""
    successful_run_id = 4
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": successful_run_id,
                    "workflow_id": WORKFLOW_ID,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "jobsByRun": {str(successful_run_id): []},
            "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )

    assert resolved["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}


def test_incremental_pr_base_does_not_reuse_stale_security_evidence():
    """INVARIANT: the weekly full-scan cadence bounds how long prior scan evidence is reusable."""
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": 4,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": STALE_SUCCESS_TIME,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "comparisons": {},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )

    assert resolved["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}


def test_incremental_pr_base_chooses_the_newest_reusable_success():
    """INVARIANT: API response ordering cannot make the resolver repeat already-proven work."""
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": 4,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": OLDER_ANCESTOR_SHA,
                    "updated_at": "2026-08-31T12:00:00Z",
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                },
                {
                    "id": 5,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                },
            ],
            "comparisons": {
                f"{OLDER_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"},
                f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"},
            },
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )

    assert resolved["result"] == {"baseSha": SUCCESSFUL_ANCESTOR_SHA, "reused": True}


def test_incremental_pr_base_discovers_a_success_before_the_workflow_index_catches_up():
    """INVARIANT: eventual consistency cannot force routine pushes to repeat completed scans."""
    prior_run_id = 55
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": prior_run_id,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "indexedRuns": [],
            "firstParentSha": SUCCESSFUL_ANCESTOR_SHA,
            "checkRuns": {
                SUCCESSFUL_ANCESTOR_SHA: [
                    {"details_url": (f"https://github.com/gigaverse-app/example/actions/runs/{prior_run_id}/job/123")}
                ]
            },
            "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )

    assert resolved["result"] == {"baseSha": SUCCESSFUL_ANCESTOR_SHA, "reused": True}


def test_incremental_pr_base_walks_past_a_cancelled_previous_head():
    """INVARIANT: rapid pushes can cancel the immediate parent without hiding an older proven head."""
    cancelled_run_id = 54
    successful_run_id = 55
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": cancelled_run_id,
                    "status": "completed",
                    "conclusion": "cancelled",
                    "head_sha": FAILED_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                },
                {
                    "id": successful_run_id,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                },
            ],
            "indexedRuns": [],
            "commitParents": {
                CURRENT_HEAD_SHA: FAILED_ANCESTOR_SHA,
                FAILED_ANCESTOR_SHA: SUCCESSFUL_ANCESTOR_SHA,
            },
            "checkRuns": {
                FAILED_ANCESTOR_SHA: [
                    {
                        "details_url": (
                            f"https://github.com/gigaverse-app/example/actions/runs/{cancelled_run_id}/job/123"
                        )
                    }
                ],
                SUCCESSFUL_ANCESTOR_SHA: [
                    {
                        "details_url": (
                            f"https://github.com/gigaverse-app/example/actions/runs/{successful_run_id}/job/123"
                        )
                    }
                ],
            },
            "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )

    assert resolved["result"] == {"baseSha": SUCCESSFUL_ANCESTOR_SHA, "reused": True}
    assert resolved["calls"] == {
        "commitRefs": [CURRENT_HEAD_SHA, FAILED_ANCESTOR_SHA],
        "checkRefs": [FAILED_ANCESTOR_SHA, SUCCESSFUL_ANCESTOR_SHA],
        "runIds": [cancelled_run_id, successful_run_id],
    }


@pytest.mark.parametrize("step_result", ["success", "skipped", "failure", "missing"])
def test_combined_planner_success_does_not_substitute_for_scan_evidence(step_result: str) -> None:
    """A draft/no-op planner success must not hide source files on ready-for-review."""
    resolved = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": 4,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": SUCCESSFUL_ANCESTOR_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "jobsByRun": {
                "4": [
                    {
                        "name": "Security evidence",
                        "conclusion": "success",
                        "steps": []
                        if step_result == "missing"
                        else [{"name": "Record successful source scan", "conclusion": step_result}],
                    }
                ]
            },
            "evidenceStepName": "Record successful source scan",
            "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
        }
    )
    assert resolved["result"] == {
        "baseSha": SUCCESSFUL_ANCESTOR_SHA if step_result == "success" else FALLBACK_BASE_SHA,
        "reused": step_result == "success",
    }


@pytest.mark.parametrize("plan_conclusion", ["success", "failure"])
@pytest.mark.parametrize("test_conclusion", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("receipt", ["success", "failure", "skipped"])
@pytest.mark.parametrize("attempt", [1, 2])
def test_pytest_evidence_from_the_same_head_is_reused_only_when_it_passed(
    plan_conclusion: str, test_conclusion: str, receipt: str, attempt: int
) -> None:
    """
    INVARIANT: a completed, passing run of this exact head proves the identical tree passed.

    A `ready_for_review` event re-runs the workflow for an unchanged head, usually minutes
    after the draft run validated that same head. The shards test the head's own tree, so
    same head means byte-identical tested tree, which is stronger evidence than the ancestor
    reuse already accepted. Excluding it re-ran the whole suite on every ready event.

    A same-head FAILURE must never become a reuse candidate, though. With an identical tree
    the delta is empty, so failure-candidate reuse would re-run only the files that failed
    and could turn a red commit green on a single flaky pass. Reopening a red commit must
    still mean re-validating it in full.
    """
    result = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                {
                    "id": 1,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": CURRENT_HEAD_SHA,
                    "updated_at": RECENT_SUCCESS_TIME,
                    "run_attempt": attempt,
                    "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
                }
            ],
            "jobsByRun": {
                "1": [
                    {"name": "Plan tests", "conclusion": plan_conclusion},
                    {
                        "name": "Run pytest (2 concurrent shards)",
                        "conclusion": test_conclusion,
                        "steps": [{"name": "Record reusable pytest completion", "conclusion": receipt}],
                    },
                ]
            },
            "comparisons": {f"{CURRENT_HEAD_SHA}...{CURRENT_HEAD_SHA}": {"status": "identical"}},
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
            "evidenceJobName": "Run pytest (* concurrent shards)",
            "pytestEvidence": {"planJobName": "Plan tests", "completionStepName": "Record reusable pytest completion"},
        }
    )["result"]
    passed_here = (
        attempt == 1 and plan_conclusion == "success" and receipt == "success" and test_conclusion == "success"
    )
    if passed_here:
        assert result == {"baseSha": CURRENT_HEAD_SHA, "reused": True}
    else:
        # Never a failure candidate for the same head: no `failedSha` may appear.
        assert result == {"baseSha": FALLBACK_BASE_SHA, "reused": False}


@pytest.mark.parametrize("latest_attempt", [1, 2])
@pytest.mark.parametrize("latest_test", ["failure", "cancelled", "skipped"])
def test_newer_same_head_pytest_failure_revokes_the_older_same_head_success(
    latest_attempt: int, latest_test: str
) -> None:
    """
    INVARIANT: the newest pytest verdict on this exact tree wins over any older same-head pass.

    Run 1 passed this head; run 2, newer, ran the same tree again. If run 2's pytest job failed,
    even as an explicit rerun, the tree is at best flaky, and reaching back to run 1 would publish
    green over a red result. A cancelled or skipped job carries no verdict and does not revoke.
    Revocation only removes same-head proof: an ancestor pass still supports incremental
    selection, as it did before same-head reuse existed.
    """

    def pytest_jobs(test_conclusion: str) -> list[dict[str, object]]:
        return [
            {"name": "Plan tests", "conclusion": "success"},
            {
                "name": "Run pytest (2 concurrent shards)",
                "conclusion": test_conclusion,
                "steps": [{"name": "Record reusable pytest completion", "conclusion": "success"}],
            },
        ]

    def run(number: int, head_sha: str, attempt: int, updated_at: str) -> dict[str, object]:
        return {
            "id": number,
            "status": "completed",
            "conclusion": "success",
            "head_sha": head_sha,
            "updated_at": updated_at,
            "run_attempt": attempt,
            "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
        }

    result = _resolve_incremental_base(
        {
            "workflowId": WORKFLOW_ID,
            "runs": [
                run(0, SUCCESSFUL_ANCESTOR_SHA, 1, "2026-09-01T10:00:00Z"),
                run(1, CURRENT_HEAD_SHA, 1, "2026-09-01T11:00:00Z"),
                run(2, CURRENT_HEAD_SHA, latest_attempt, RECENT_SUCCESS_TIME),
            ],
            "jobsByRun": {"0": pytest_jobs("success"), "1": pytest_jobs("success"), "2": pytest_jobs(latest_test)},
            "comparisons": {
                f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"},
                f"{CURRENT_HEAD_SHA}...{CURRENT_HEAD_SHA}": {"status": "identical"},
            },
            "fallbackBaseSha": FALLBACK_BASE_SHA,
            "headSha": CURRENT_HEAD_SHA,
            "pullRequestNumber": PULL_REQUEST_NUMBER,
            "currentTime": CURRENT_TIME,
            "evidenceJobName": "Run pytest (* concurrent shards)",
            "pytestEvidence": {"planJobName": "Plan tests", "completionStepName": "Record reusable pytest completion"},
        }
    )["result"]
    revoked = latest_test == "failure"
    assert result == {"baseSha": SUCCESSFUL_ANCESTOR_SHA if revoked else CURRENT_HEAD_SHA, "reused": True}


REAL_RECEIPT = "Validated inputs 6d7abb4871e897880b5c7f2f3fcbaa7cc25c2566eb5331edbbd71defa083619d"


def _lane_with_step(step_name: str) -> dict[str, object]:
    scenario = _same_head_lane_scenario("success", "valid")
    scenario["evidenceStepName"] = REAL_RECEIPT
    scenario["jobsByRun"] = {
        "1": [
            {
                "name": "Search validation",
                "conclusion": "success",
                "steps": [{"name": step_name, "conclusion": "success"}],
            }
        ]
    }
    return scenario


@pytest.mark.parametrize(
    ("step_name", "reused"),
    [
        (REAL_RECEIPT.replace("33", "***"), True),
        (REAL_RECEIPT.replace("33", "***").replace("6d7abb", "6d7abc"), False),
        ("Validated inputs 6d7abb***", False),
        ("Validated inputs ***", False),
    ],
    ids=["masked-secret", "masked-but-different", "mostly-masked", "fully-masked"],
)
def test_a_receipt_masked_by_a_secret_still_proves_the_lane(step_name: str, reused: bool) -> None:
    """INVARIANT: masking hides characters, never changes the rest; an unmasked mismatch or a mostly hidden receipt never proves."""
    result = _resolve_incremental_base(_lane_with_step(step_name))["result"]

    assert result == {"baseSha": CURRENT_HEAD_SHA if reused else FALLBACK_BASE_SHA, "reused": reused}


def test_a_lagging_listing_is_covered_by_the_head_commits_own_check_runs() -> None:
    """
    The run listing can omit a just-completed run; the head commit's check runs record it directly.

    backend-common#216's drill: a re-triggered run's python lane got no candidate from the listing,
    fell back without a word, and re-ran, while later lanes of the same plan found the run.
    """
    scenario = _same_head_lane_scenario("success", "valid")
    scenario["indexedRuns"] = []
    scenario["checkRuns"] = {
        CURRENT_HEAD_SHA: [{"details_url": "https://github.com/gigaverse-app/example/actions/runs/1/job/5"}]
    }

    outcome = _resolve_incremental_base(scenario)

    assert outcome["result"] == {"baseSha": CURRENT_HEAD_SHA, "reused": True}


def test_a_check_run_of_another_head_does_not_prove_the_lane() -> None:
    """CONTROL: the head's check runs only admit a run of this exact head."""
    scenario = _same_head_lane_scenario("success", "ancestor")
    scenario["indexedRuns"] = []
    scenario["checkRuns"] = {
        CURRENT_HEAD_SHA: [{"details_url": "https://github.com/gigaverse-app/example/actions/runs/1/job/5"}]
    }

    outcome = _resolve_incremental_base(scenario)

    assert outcome["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}
    assert any("different head" in line for line in _resolver_infos(outcome))


def test_finding_no_candidate_at_all_is_logged() -> None:
    scenario = _same_head_lane_scenario("success", "valid")
    scenario["indexedRuns"] = []

    outcome = _resolve_incremental_base(scenario)

    assert outcome["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}
    assert any("No completed run" in line for line in _resolver_infos(outcome)), _resolver_infos(outcome)


def _calls(resolved: dict[str, object]) -> dict[str, list[object]]:
    calls = resolved["calls"]
    assert isinstance(calls, dict)
    return calls


def _walk_scenario(listed_status: str) -> dict[str, object]:
    """
    The backend image gate: every run of this workflow lacks the evidence job, so the listing
    rejects them all, and each ancestor's check runs name those same runs.
    """
    runs = [
        {
            "id": run_id,
            "status": "completed",
            "conclusion": "success",
            "head_sha": sha,
            "updated_at": RECENT_SUCCESS_TIME,
            "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
        }
        for run_id, sha in ((54, FAILED_ANCESTOR_SHA), (55, SUCCESSFUL_ANCESTOR_SHA))
    ]
    return {
        "workflowId": WORKFLOW_ID,
        "runs": runs,
        # The listing's copy of the newest run may lag: GitHub lists it before its final status.
        "indexedRuns": [{**runs[0], "status": listed_status, "conclusion": None}, runs[1]]
        if listed_status != "completed"
        else runs,
        "jobsByRun": {"54": [{"name": "Unrelated", "conclusion": "success"}], "55": []},
        "commitParents": {
            CURRENT_HEAD_SHA: FAILED_ANCESTOR_SHA,
            FAILED_ANCESTOR_SHA: SUCCESSFUL_ANCESTOR_SHA,
            SUCCESSFUL_ANCESTOR_SHA: OLDER_ANCESTOR_SHA,
        },
        "checkRuns": {
            sha: [{"details_url": f"https://github.com/gigaverse-app/example/actions/runs/{run_id}/job/1"}]
            for run_id, sha in ((54, FAILED_ANCESTOR_SHA), (55, SUCCESSFUL_ANCESTOR_SHA))
        },
        "comparisons": {},
        "fallbackBaseSha": FALLBACK_BASE_SHA,
        "headSha": CURRENT_HEAD_SHA,
        "pullRequestNumber": PULL_REQUEST_NUMBER,
        "currentTime": CURRENT_TIME,
    }


def test_the_ancestor_walk_stops_at_runs_the_listing_already_judged() -> None:
    """
    INVARIANT: the walk only looks for runs the listing has not caught up with.

    A completed run the listing returned was already judged, and every older ancestor's run is
    older still, so it is listed too. Re-fetching them cost backend's image gate 31s per plan
    job (backend-common#217) for a proof that could never succeed.
    """
    resolved = _resolve_incremental_base(_walk_scenario("completed"))
    assert resolved["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}
    assert _calls(resolved)["checkRefs"] == [FAILED_ANCESTOR_SHA], "stop at the first already-listed ancestor"
    assert _calls(resolved)["runIds"] == [], "a listed completed run is never fetched again"


def test_a_run_listed_before_it_finished_is_still_fetched_fresh() -> None:
    """CONTROL: the listing lag the walk exists for shows as a run listed as still in progress."""
    scenario = _walk_scenario("in_progress")
    scenario["jobsByRun"] = {"54": [{"name": "Security evidence", "conclusion": "success"}], "55": []}
    scenario["comparisons"] = {f"{FAILED_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}}
    resolved = _resolve_incremental_base(scenario)
    assert resolved["result"] == {"baseSha": FAILED_ANCESTOR_SHA, "reused": True}
    assert _calls(resolved)["runIds"] == [54]


def _foreign_ancestor_scenario(parent_runs: list[int]) -> dict[str, object]:
    """
    A PR's first run: its first parent is another branch's commit (main, or the bump branch a
    drill PR is cut from), whose runs belong to other PRs or to no PR at all.
    """
    foreign = {
        "id": 70,
        "status": "completed",
        "conclusion": "success",
        "head_sha": FAILED_ANCESTOR_SHA,
        "updated_at": RECENT_SUCCESS_TIME,
        "pull_requests": [{"number": PULL_REQUEST_NUMBER + 1}],
    }
    own = {
        "id": 71,
        "status": "completed",
        "conclusion": "success",
        "head_sha": SUCCESSFUL_ANCESTOR_SHA,
        "updated_at": RECENT_SUCCESS_TIME,
        "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
    }
    return {
        "workflowId": WORKFLOW_ID,
        "runs": [foreign, own],
        "indexedRuns": [],
        "commitParents": {
            CURRENT_HEAD_SHA: FAILED_ANCESTOR_SHA,
            FAILED_ANCESTOR_SHA: SUCCESSFUL_ANCESTOR_SHA,
            SUCCESSFUL_ANCESTOR_SHA: OLDER_ANCESTOR_SHA,
        },
        "checkRuns": {
            FAILED_ANCESTOR_SHA: [
                {"details_url": f"https://github.com/gigaverse-app/example/actions/runs/{run_id}/job/1"}
                for run_id in parent_runs
            ],
            SUCCESSFUL_ANCESTOR_SHA: [
                {"details_url": "https://github.com/gigaverse-app/example/actions/runs/71/job/1"}
            ],
        },
        "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
        "fallbackBaseSha": FALLBACK_BASE_SHA,
        "headSha": CURRENT_HEAD_SHA,
        "pullRequestNumber": PULL_REQUEST_NUMBER,
        "currentTime": CURRENT_TIME,
    }


def test_the_ancestor_walk_stops_where_this_pull_request_history_ends() -> None:
    """
    INVARIANT: the walk never inspects runs past an ancestor whose runs all belong to other PRs.

    Runs of other PRs are never reusable, and every older ancestor is further outside this PR.
    Walking on fetched every run of ten main (or bump-branch) commits on each PR's first run:
    ai's security admission took 10s against 2s in the backend-common#217 drill.
    """
    resolved = _resolve_incremental_base(_foreign_ancestor_scenario([70]))
    assert resolved["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}
    assert _calls(resolved)["checkRefs"] == [FAILED_ANCESTOR_SHA]


def test_an_ancestor_with_no_runs_is_walked_past() -> None:
    """CONTROL: commits pushed together get no runs of their own; the proven head behind them counts."""
    resolved = _resolve_incremental_base(_foreign_ancestor_scenario([]))
    assert resolved["result"] == {"baseSha": SUCCESSFUL_ANCESTOR_SHA, "reused": True}


def _two_head_lane_scenario(older: str, newer: str, earlier_head_finishes_last: bool = False) -> dict[str, object]:
    """An earlier head's run and the current head's run, of one lane and one receipt."""
    scenario = _same_head_lane_scenario("success", "valid")
    receipt = scenario["evidenceStepName"]
    heads = {1: SUCCESSFUL_ANCESTOR_SHA, 2: CURRENT_HEAD_SHA}
    scenario["runs"] = [
        {
            "id": run_id,
            "status": "completed",
            "conclusion": conclusion,
            "head_sha": heads[run_id],
            "run_attempt": 1,
            "updated_at": time,
            "pull_requests": [{"number": PULL_REQUEST_NUMBER}],
        }
        for run_id, conclusion, time in (
            (1, older, "2026-09-02T12:00:00Z" if earlier_head_finishes_last else "2026-09-02T10:00:00Z"),
            (2, newer, "2026-09-02T11:00:00Z"),
        )
    ]
    scenario["jobsByRun"] = {
        str(run_id): [
            {
                "name": "Search validation",
                "conclusion": conclusion,
                "steps": [{"name": receipt, "conclusion": "success"}] if conclusion == "success" else [],
            }
        ]
        for run_id, conclusion in ((1, older), (2, newer))
    }
    return scenario


def test_only_a_failure_of_this_head_revokes_an_equivalent_earlier_proof() -> None:
    """
    INVARIANT: a failure revokes only the head it failed on.

    A failed run carries no receipt, so nothing says what another head's failure tested. A
    failure of the current head is new information about these inputs, as before.
    """
    revoked = _resolve_incremental_base(_two_head_lane_scenario(older="success", newer="failure"))
    assert revoked["result"] == {"baseSha": FALLBACK_BASE_SHA, "reused": False}
    # An earlier head's failure says nothing about the current head's proof, even when that
    # slower run finishes last and is inspected first.
    for last in (False, True):
        kept = _resolve_incremental_base(
            _two_head_lane_scenario(older="failure", newer="success", earlier_head_finishes_last=last)
        )
        assert kept["result"] == {"baseSha": CURRENT_HEAD_SHA, "reused": True}, last


@pytest.mark.parametrize("listing_lag", [False, True])
@pytest.mark.parametrize("variant", ["valid", "missing-receipt", "failed", "skipped", "rerun"])
def test_lanes_share_api_reads_but_never_share_verdicts(listing_lag: bool, variant: str) -> None:
    """Every API resource is read once; a sibling's proof never admits another lane."""
    scenario = _same_head_lane_scenario("success", variant)
    jobs_by_run = scenario["jobsByRun"]
    assert isinstance(jobs_by_run, dict)
    jobs = jobs_by_run["1"]
    assert isinstance(jobs, list)
    jobs.append(
        {
            "name": "Python validation",
            "conclusion": "success",
            "steps": [{"name": scenario["evidenceStepName"], "conclusion": "success"}],
        }
    )
    scenario["lanes"] = ["Search validation", "Python validation", "Missing validation"]
    if listing_lag:
        scenario["indexedRuns"] = []
        scenario["checkRuns"] = {
            CURRENT_HEAD_SHA: [{"details_url": "https://github.com/gigaverse-app/example/actions/runs/1/job/2"}]
        }
    outcome = _resolve_incremental_base(scenario)
    results = outcome["result"]
    assert isinstance(results, list)
    assert [result["reused"] for result in results] == [variant == "valid", variant != "rerun", False]
    reads = outcome["reads"]
    assert isinstance(reads, list)
    assert len(reads) == len(set(reads)), reads


@pytest.mark.parametrize("variant", ["valid", "missing", "wrong-pr", "wrong-head", "skipped", "push", "other-branch"])
def test_missing_api_association_requires_run_bound_pr_ownership(variant: str) -> None:
    """Missing PR metadata may reuse explicit ownership, never a branch-name guess."""
    scenario = _same_head_lane_scenario("success", "valid")
    runs = scenario["runs"]
    assert isinstance(runs, list)
    run = runs[0]
    run.update(
        pull_requests=[],
        event="push" if variant == "push" else "pull_request",
        head_branch="other" if variant == "other-branch" else "feature/security-ci",
    )
    jobs = scenario["jobsByRun"]
    assert isinstance(jobs, dict)
    if variant != "missing":
        owner = PULL_REQUEST_NUMBER + 1 if variant == "wrong-pr" else PULL_REQUEST_NUMBER
        head = SUCCESSFUL_ANCESTOR_SHA if variant == "wrong-head" else CURRENT_HEAD_SHA
        jobs["1"].append(
            {
                "name": "Plan",
                "conclusion": "success",
                "steps": [
                    {
                        "name": f"PR evidence #{owner} head {head}",
                        "conclusion": "skipped" if variant == "skipped" else "success",
                    }
                ],
            }
        )
    result = _resolve_incremental_base(scenario)["result"]
    assert result == {
        "baseSha": CURRENT_HEAD_SHA if variant == "valid" else FALLBACK_BASE_SHA,
        "reused": variant == "valid",
    }


@pytest.mark.parametrize("same_inputs", [True, False])
def test_other_head_failed_inventory_revokes_only_matching_input_receipt(same_inputs: bool) -> None:
    scenario = _two_head_lane_scenario(older="success", newer="failure")
    scenario["headSha"] = "e" * 40
    jobs = scenario["jobsByRun"]
    assert isinstance(jobs, dict)
    jobs["2"][0]["steps"] = [
        {"name": scenario["evidenceStepName"] if same_inputs else "other inputs", "conclusion": "skipped"}
    ]
    result = _resolve_incremental_base(scenario)["result"]
    assert isinstance(result, dict)
    assert result["reused"] is (not same_inputs)


def test_inventory_cannot_reach_back_past_an_unidentified_failed_scan() -> None:
    scenario = _two_head_lane_scenario(older="success", newer="failure")
    scenario["headSha"] = "e" * 40
    scenario["conservativeFailures"] = True
    # An API outage prevented the failed scan from recording its input identity.
    # Its missing receipt is uncertainty, not permission to resurrect an older green.
    result = _resolve_incremental_base(scenario)["result"]
    assert isinstance(result, dict)
    assert result["reused"] is False


@pytest.mark.parametrize("failed_read", ["current-run", "jobs"])
@pytest.mark.parametrize("listing_lag", [False, True])
def test_unavailable_evidence_is_read_once_and_keeps_every_lane_required(failed_read: str, listing_lag: bool) -> None:
    scenario = _same_head_lane_scenario("success", "valid")
    scenario["lanes"] = ["Search validation", "Python validation", "Missing validation"]
    scenario["failAt"] = failed_read
    if listing_lag:
        scenario["indexedRuns"] = []
        scenario["checkRuns"] = {
            CURRENT_HEAD_SHA: [{"details_url": "https://github.com/gigaverse-app/example/actions/runs/1/job/2"}]
        }
    outcome = _resolve_incremental_base(scenario)
    assert outcome["result"] == [{"baseSha": FALLBACK_BASE_SHA, "reused": False}] * 3
    reads = outcome["reads"]
    assert isinstance(reads, list)
    assert len(reads) == len(set(reads)), reads
    # A new planner invocation must retry; an outage is never persisted as proof.
    fresh = _resolve_incremental_base(_same_head_lane_scenario("success", "valid"))
    assert fresh["result"] == {"baseSha": CURRENT_HEAD_SHA, "reused": True}


@pytest.mark.parametrize("variant", ["valid", "missing-marker", "failed-marker", "newer-failure", "newer-cancelled", "newer-timed_out", "jobs-unavailable"])
def test_validation_base_requires_completion_and_does_not_cross_newer_failure(variant):
    run = {"id": 1, "status": "completed", "conclusion": "success", "head_sha": SUCCESSFUL_ANCESTOR_SHA,
           "updated_at": RECENT_SUCCESS_TIME, "pull_requests": [{"number": PULL_REQUEST_NUMBER}]}
    runs = [run]
    jobs = {1: [{"name": "checks", "conclusion": "success", "steps": [
        {"name": "Validated Bun v1", "conclusion": "failure" if variant == "failed-marker" else "success"}
    ] if variant != "missing-marker" else []}]}
    if variant.startswith("newer-"):
        runs.append({**run, "id": 2, "head_sha": CURRENT_HEAD_SHA,
                     "updated_at": CURRENT_TIME, "conclusion": variant.removeprefix("newer-")})
    resolved = _resolve_incremental_base({
        "workflowId": WORKFLOW_ID, "runs": runs, "jobsByRun": jobs,
        "comparisons": {f"{SUCCESSFUL_ANCESTOR_SHA}...{CURRENT_HEAD_SHA}": {"status": "ahead"}},
        "fallbackBaseSha": FALLBACK_BASE_SHA, "headSha": CURRENT_HEAD_SHA,
        "pullRequestNumber": PULL_REQUEST_NUMBER, "currentTime": CURRENT_TIME,
        "evidenceJobName": "checks", "evidenceStepName": "Validated Bun v1", "validationEvidence": True,
        "failAt": "jobs" if variant == "jobs-unavailable" else None,
    })["result"]
    assert resolved == {"baseSha": SUCCESSFUL_ANCESTOR_SHA if variant == "valid" else FALLBACK_BASE_SHA,
                        "reused": variant == "valid"}
