import assert from "node:assert/strict";
import { test } from "node:test";
import { workSelectionReport } from "../../actions/run-bun-tests/work-report.mjs";

const context = { runId: 123, attempt: 2, headSha: "a".repeat(40) };
const execution = { mode: "scoped", reason: "Affected imports", fallback: false,
  testedSha: "b".repeat(40), base: "c".repeat(40), bunVersion: "1.4.2", totalFiles: 657,
  executedFiles: ["src/value.test.ts"], alwaysRunFiles: [], durationMs: 22000, exitCode: 0 };

test("Bun report preserves source versus tested commit and measured counts", () => {
  const result = workSelectionReport(execution, context);
  assert.equal(result.head_sha, context.headSha);
  const observed = result.decisions[0].execution;
  assert.equal(observed.tested_sha, execution.testedSha);
  assert.equal(observed.status, "passed");
  assert.equal(observed.duration_seconds, 22);
  assert.equal(observed.total_files, 657);
  assert.deepEqual(observed.executed_files, execution.executedFiles);
});

test("missing inventory and missing full or always-run tests cannot report passed", () => {
  for (const changes of [{executedFiles:null}, {mode:"full"}, {alwaysRunFiles:["missing.test.ts"]}]) {
    assert.equal(workSelectionReport({...execution, ...changes}, context).decisions[0].execution.status, "incomplete");
  }
  assert.equal(workSelectionReport({...execution, exitCode:1}, context).decisions[0].execution.status, "failed");
});

test("reuse describes prior proof and never executed tests", () => {
  const result = workSelectionReport({...execution, mode:"reused", executedFiles:[], receipt:"proof", durationMs:undefined}, context);
  assert.equal(result.decisions[0].receipt, "proof");
  assert.equal(result.decisions[0].execution.status, "not_run");
  assert.equal(result.decisions[0].execution.duration_seconds, null);
});
