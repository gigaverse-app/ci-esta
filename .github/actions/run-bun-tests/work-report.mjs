// Provider-neutral reporting only. This never authorizes a test skip.
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export function workSelectionReport(execution, context) {
  const { mode, reason, fallback, testedSha, base, bunVersion, totalFiles,
    executedFiles, alwaysRunFiles = [], durationMs, exitCode, receipt } = execution;
  const reused = mode === "reused";
  const known = Array.isArray(executedFiles);
  const complete = known && (mode !== "full" || executedFiles.length === totalFiles) &&
    alwaysRunFiles.every(file => executedFiles.includes(file));
  const status = reused ? "not_run" : exitCode !== 0 ? "failed" : !complete ? "incomplete" : "passed";
  return {
    schema_version: "ci-esta/work-selection/v1", provider: "Bun",
    run_id: Number(context.runId), run_attempt: Number(context.attempt), head_sha: context.headSha,
    input_identity: testedSha, fallback: Boolean(fallback), decisions: [{
      name: "Bun tests", decision: reused ? "reused" : mode === "none" ? "unaffected" : "run",
      reason: reason.slice(0, 1000), ...(reused ? { receipt } : {}),
      execution: { mode, status, total_files: totalFiles, executed_files: known ? executedFiles : null,
        always_run_files: alwaysRunFiles, duration_seconds: Number.isFinite(durationMs) ? durationMs / 1000 : null,
        tested_sha: testedSha, base_sha: base || null, runtime: `Bun ${bunVersion}` },
    }],
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const event = process.env.GITHUB_EVENT_PATH ? JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, "utf8")) : {};
  const result = workSelectionReport(JSON.parse(readFileSync(process.env.BUN_EXECUTION_FILE, "utf8")), {
    runId: process.env.GITHUB_RUN_ID, attempt: process.env.GITHUB_RUN_ATTEMPT,
    headSha: event.pull_request?.head.sha || process.env.GITHUB_SHA,
  });
  writeFileSync(process.env.BUN_WORK_REPORT || "ci-work-selection.json", JSON.stringify(result, null, 2) + "\n");
}
