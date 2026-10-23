import { execFileSync, spawnSync } from "node:child_process";
import { appendFileSync, lstatSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { planAffectedTests, readTestSelection, safePath } from "./selection.mjs";

export function readInventory(path, cwd) {
  const inventory = JSON.parse(readFileSync(path, "utf8"));
  if (inventory.schema_version !== "ci-esta/bun-inventory/v1" ||
      !Array.isArray(inventory.files) || !inventory.files.length ||
      !Array.isArray(inventory.alwaysRunFiles)) throw new Error("Invalid or empty Bun inventory");
  const files = inventory.files;
  if (new Set(files).size !== files.length || new Set(inventory.alwaysRunFiles).size !== inventory.alwaysRunFiles.length)
    throw new Error("Duplicate inventory entries");
  for (const file of files) {
    if (!safePath(file) || !/[._](?:test|spec)\.[cm]?[jt]sx?$/.test(file) || !lstatSync(join(cwd, file)).isFile())
      throw new Error(`Invalid test file: ${file}`);
  }
  if (inventory.alwaysRunFiles.some(file => !files.includes(file))) throw new Error("Always-run tests must belong to the inventory");
  return { files: [...files].sort(), alwaysRunFiles: inventory.alwaysRunFiles };
}

export function runBunTests({ cwd = process.cwd(), inventoryFile, policyFile, base, full = false,
  planFile, outputDirectory, args = ["--isolate", "--parallel"], shards = 1, bun = "bun" }) {
  const { files, alwaysRunFiles } = readInventory(inventoryFile, cwd);
  if (!Number.isSafeInteger(shards) || shards < 1) throw new Error("shards must be a positive integer");
  if (!Array.isArray(args) || args.some(arg => typeof arg !== "string" ||
    !/^(?:--isolate|--parallel(?:=[1-9]\d*)?|--timeout=[1-9]\d*|--max-concurrency=[1-9]\d*|--seed=\d+|--randomize|--concurrent|--dots)$/.test(arg)))
    throw new Error("Unsupported Bun execution arguments; selection, reports and file paths are owned by the adapter");
  const version = execFileSync(bun, ["--version"], { encoding: "utf8" }).trim();
  if (!/^1\.(?:4\.(?:[2-9]|[1-9]\d+)|[5-9]\.\d+|[1-9]\d+\.\d+)$/.test(version))
    throw new Error(`Bun ${version} is outside the verified >=1.4.2 <2 runtime contract`);
  const options = { cwd, base, full, policyFile, alwaysRunFiles };
  const plan = planFile && !full ? readTestSelection(planFile, options) : planAffectedTests(options);
  const output = resolve(outputDirectory);
  mkdirSync(output, { recursive: true });
  const write = (name, value) => writeFileSync(join(output, name), JSON.stringify(value, null, 2) + "\n");
  write("test-selection.json", plan);
  let exitCode = 0;
  const executions = [];
  const started = performance.now();
  for (let index = 0; index < shards; index++) {
    const shard = files.filter((_, position) => position % shards === index);
    const groups = plan.mode === "full" ? [{ files: shard, changed: false }] : [
      { files: shard.filter(file => alwaysRunFiles.includes(file)), changed: false },
      { files: plan.mode === "none" ? [] : shard.filter(file => !alwaysRunFiles.includes(file)), changed: true },
    ];
    for (const group of groups) {
      // An empty file list would make Bun discover and execute the whole repository.
      if (!group.files.length) continue;
      const timings = join(output, `timings-${index}-${group.changed ? "affected" : "full"}.json`);
      writeFileSync(timings, '{"version":1,"files":{}}');
      const command = ["test", ...group.files.map(file => `./${file}`), ...args,
        ...(group.changed ? [`--changed=${plan.base}`] : []), `--timings=${timings}`, "--update-timings"];
      console.log(`Bun batch ${index + 1}/${shards}: ${group.changed ? "affected" : "full"}, ${group.files.length} candidate files`);
      const before = performance.now();
      const result = spawnSync(bun, command, { cwd, stdio: "inherit" });
      const status = result.status ?? 1;
      if (status !== 0) exitCode = status;
      let executedFiles = null;
      try { executedFiles = Object.keys(JSON.parse(readFileSync(timings, "utf8")).files).sort(); } catch {}
      executions.push({ shard: index + 1, affected: group.changed, exitCode: status,
        durationMs: performance.now() - before, executedFiles, error: result.error?.message ?? result.signal ?? null });
    }
  }
  const inventoryKnown = executions.every(item => item.executedFiles !== null);
  const executedFiles = inventoryKnown ? [...new Set(executions.flatMap(item => item.executedFiles))].sort() : null;
  const result = { schema_version: "ci-esta/bun-execution/v1", ...plan, bunVersion: version,
    totalFiles: files.length, alwaysRunFiles, executedFiles, executions, durationMs: performance.now() - started, exitCode };
  write("execution-selection.json", result);
  if (process.env.GITHUB_RUN_ID) {
    const reason = `${plan.reason}; ${executedFiles === null ? "execution inventory unavailable" : `executed ${executedFiles.length}/${files.length} files`}`;
    write("ci-work-selection.json", {
      schema_version: "ci-esta/work-selection/v1", provider: "Bun", run_id: Number(process.env.GITHUB_RUN_ID),
      run_attempt: Number(process.env.GITHUB_RUN_ATTEMPT), head_sha: process.env.GITHUB_SHA,
      input_identity: plan.testedSha, fallback: Boolean(plan.fallback), decisions: [
        { name: "Bun affected tests", decision: plan.mode === "none" ? "unaffected" : "run", reason: reason.slice(0, 1000) },
        ...(alwaysRunFiles.length ? [{ name: "Repository contracts", decision: "run", reason: `${alwaysRunFiles.length} explicitly always-run files; never filtered by imports` }] : []),
      ],
    });
  }
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT,
    `mode=${plan.mode}\nfallback=${plan.fallback}\nexit-code=${exitCode}\n`);
  return result;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = runBunTests({ inventoryFile: process.env.BUN_TEST_INVENTORY,
      policyFile: process.env.BUN_TEST_POLICY, base: process.env.BUN_TEST_BASE,
      full: process.env.BUN_TEST_FULL === "true", outputDirectory: process.env.BUN_TEST_OUTPUT,
      args: JSON.parse(process.env.BUN_TEST_ARGS || '["--isolate","--parallel"]'),
      shards: Number(process.env.BUN_TEST_SHARDS || "1") });
    process.exitCode = result.exitCode;
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
