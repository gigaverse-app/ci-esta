import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";

import { planAffectedTests, readTestSelection } from "../../actions/run-bun-tests/selection.mjs";
import { runBunTests, readInventory } from "../../actions/run-bun-tests/run.mjs";

const policy = { schema_version: "ci-esta/bun-policy/v1", scopedRoots: ["packages/features/", "packages/components/"],
  unaffectedPaths: ["README.md", ".github/PULL_REQUEST_TEMPLATE.md"], unaffectedRoots: ["docs/"],
  sourceExtensions: [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"],
  runtimeRoots: ["packages/"], reviewedReaders: {} };
const bun = process.env.BUN_BINARY || "bun";

function fixture(t) {
  const cwd = mkdtempSync(join(tmpdir(), "bun-selection-"));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  const git = (...args) =>
    execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  const put = (file, content) => {
    mkdirSync(dirname(join(cwd, file)), { recursive: true });
    writeFileSync(join(cwd, file), content);
  };
  const commit = () => {
    git("add", ".");
    git("commit", "-qm", "fixture");
    return git("rev-parse", "HEAD");
  };
  git("init", "-q");
  git("config", "user.email", "test@example.test");
  git("config", "user.name", "Selection tests");
  put(".github/test-selection.json", JSON.stringify(policy));
  put("package.json", JSON.stringify({ scripts: { "test:unit": "bun test ./packages --isolate" } }));
  put("tsconfig.json", JSON.stringify({ compilerOptions: { paths: { "@feature/*": ["./packages/features/*"] } } }));
  put("packages/features/value.ts", "export const value = 1;\n");
  put("packages/features/barrel.ts", "export { value } from './value';\n");
  put(
    "packages/features/value.test.ts",
    "import { test, expect } from 'bun:test'; import { value } from '@feature/barrel'; test('value', () => expect(value).toBe(1));\n",
  );
  put(
    "packages/features/dynamic.test.ts",
    "import { test, expect } from 'bun:test'; const { value } = await import('./value'); test('dynamic', () => expect(value).toBe(1));\n",
  );
  put("packages/features/unrelated.test.ts", "import { test } from 'bun:test'; test('unrelated', () => {});\n");
  const base = commit();
  const reports = mkdtempSync(join(tmpdir(), "bun-evidence-"));
  t.after(() => rmSync(reports, { recursive: true, force: true }));
  return { cwd, reports, git, put, commit, base, plan: (extra = {}) => planAffectedTests({ cwd, base, ...extra }) };
}

test("reviewed file readers retain their declared inputs and invalidate on reader changes", (t) => {
  const f = fixture(t);
  const reader = "packages/features/reader.ts";
  f.put(reader, "export const read = () => Bun.file('README.md').text();");
  const reviewed = structuredClone(policy);
  reviewed.reviewedReaders[reader] = { blob: f.git("hash-object", reader), inputs: ["README.md"] };
  f.put(".github/test-selection.json", JSON.stringify(reviewed));
  const base = f.commit();
  f.put("README.md", "Declared input"); f.commit();
  assert.equal(f.plan({ base }).mode, "full");
  const nextBase = f.git("rev-parse", "HEAD");
  f.put("packages/features/value.ts", "export const value = 1; export const added = true;"); f.commit();
  assert.equal(f.plan({ base: nextBase }).mode, "scoped");
  f.put(reader, "export const read = () => Bun.file('another.ts').text();"); f.commit();
  assert.equal(f.plan({ base: nextBase }).mode, "full");
  assert.equal(f.plan({ base: nextBase }).fallback, true);
});

function execute(f, selection, overrides = {}) {
  const planPath = join(f.reports, "plan.json");
  if (selection) writeFileSync(planPath, JSON.stringify(selection));
  const files = f.git("ls-files").split("\n").filter(file => file.endsWith(".test.ts"));
  const inventoryFile = join(f.reports, "inventory.json");
  writeFileSync(inventoryFile, JSON.stringify({ schema_version: "ci-esta/bun-inventory/v1", files, alwaysRunFiles: overrides.alwaysRunFiles || [] }));
  const result = runBunTests({ cwd: f.cwd, inventoryFile, planFile: planPath,
    outputDirectory: join(f.reports, "result"), bun, args: ["--isolate", "--parallel=1"], ...overrides });
  return { status: result.exitCode, selection: result };
}

test("the public adapter executes only affected tests and records their paths", (t) => {
  const f = fixture(t);
  f.put("packages/features/value.ts", "export const value = 1;\nexport const added = true;\n");
  f.commit();
  const result = execute(f, f.plan());
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(result.selection.executedFiles, [
    "packages/features/dynamic.test.ts",
    "packages/features/value.test.ts",
  ]);
});

for (const kind of ["missing", "stale", "malformed"]) {
  test(`${kind} execution plans run every file`, (t) => {
    const f = fixture(t);
    const stale = f.plan();
    f.put("packages/features/value.ts", "export const value = 1;\nexport const added = true;\n");
    f.commit();
    const result = execute(f, kind === "missing" ? undefined : kind === "stale" ? stale : { mode: "none" });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.selection.mode, "full");
    assert.equal(result.selection.fallback, true);
    assert.equal(result.selection.executedFiles.length, 3);
  });
}

test("a none plan never accidentally launches the full test command", (t) => {
  const f = fixture(t);
  f.put("README.md", "Docs\n");
  f.commit();
  const result = execute(f, f.plan());
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.selection.mode, "none");
  assert.deepEqual(result.selection.executedFiles, []);
});

test("execution preserves an affected test failure", (t) => {
  const f = fixture(t);
  f.put("packages/features/value.ts", "export const value = 2;\n");
  f.commit();
  const result = execute(f, f.plan());
  assert.equal(result.status, 1);
  assert.equal(result.selection.mode, "scoped");
  assert.equal(result.selection.executedFiles.length, 2);
});

test("worktree changes after planning invalidate a scoped plan", (t) => {
  const f = fixture(t);
  f.put("packages/features/value.ts", "export const value = 1;\nexport const added = true;\n");
  f.commit();
  const path = join(f.reports, "test-selection.json");
  writeFileSync(path, JSON.stringify(f.plan()));
  f.put("packages/features/barrel.ts", "export const value = 2;");
  assert.equal(readTestSelection(path, { cwd: f.cwd }).mode, "full");
});

for (const path of ["docs/guide.md", "README.md", ".github/PULL_REQUEST_TEMPLATE.md"]) {
  test(`${path} needs no unit tests`, (t) => {
    const f = fixture(t);
    f.put(path, "Documentation\n");
    f.commit();
    assert.equal(f.plan().mode, "none");
  });
}

for (const path of [
  "bun.lock",
  "package.json",
  "bunfig.toml",
  "tsconfig.json",
  "setupTests.ts",
  "setupTestMocks.ts",
  "packages/services/Brand/tapin.ts",
  "packages/mock-harness/shared.ts",
  "apps/app/src/main.tsx",
  "packages/features/fixture.json",
  "packages/components/assets/icon.svg",
  ".github/workflows/checks.yml",
  ".github/scripts/test-selection.mjs",
  ".claude/skills/perf-audit/references/signal-registry.md",
  "unknown-input.txt",
]) {
  test(`${path} preserves the full suite`, (t) => {
    const f = fixture(t);
    f.put(path, "changed\n");
    f.commit();
    assert.equal(f.plan().mode, "full");
  });
}

test("native selection follows aliases, barrels and literal dynamic imports", (t) => {
  const f = fixture(t);
  f.put("packages/features/value.ts", "export const value = 1;\nexport const added = true;\n");
  f.commit();
  const plan = f.plan();
  assert.equal(plan.mode, "scoped");
  const timings = join(f.reports, "timings.json");
  const result = spawnSync(
    bun,
    ["test", "./packages", `--changed=${plan.base}`, `--timings=${timings}`, "--update-timings"],
    { cwd: f.cwd, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(Object.keys(JSON.parse(readFileSync(timings, "utf8")).files).sort(), [
    "packages/features/dynamic.test.ts",
    "packages/features/value.test.ts",
  ]);
});

test("new tests are selected and an affected failure remains a failure", (t) => {
  const f = fixture(t);
  f.put(
    "packages/features/new.test.ts",
    "import { test, expect } from 'bun:test'; test('new', () => expect(1).toBe(2));\n",
  );
  f.commit();
  assert.equal(f.plan().mode, "scoped");
  const result = spawnSync(bun, ["test", "./packages", `--changed=${f.base}`], { cwd: f.cwd, encoding: "utf8" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /new\.test\.ts/);
  assert.doesNotMatch(result.stderr, /unrelated\.test\.ts:/);
});

for (const file of ["packages/features/value.ts", "packages/features/value.test.ts"]) {
  test(`deleting ${file} runs the full suite`, (t) => {
    const f = fixture(t);
    f.git("rm", file);
    f.commit();
    assert.equal(f.plan().mode, "full");
  });
}

test("renames retain the full suite", (t) => {
  const f = fixture(t);
  f.git("mv", "packages/features/value.ts", "packages/features/renamed.ts");
  f.commit();
  assert.equal(f.plan().mode, "full");
});

for (const source of [
  "const file = './value'; import(file);",
  "const data = Bun.file('./value.ts');",
  "import { readFile } from 'node:fs/promises';",
  "const files = import.meta.glob('./*.ts');",
]) {
  test(`opaque dependencies fall back: ${source}`, (t) => {
    const f = fixture(t);
    f.put("packages/features/opaque.ts", source);
    f.commit();
    assert.equal(f.plan().mode, "full");
    const base = f.git("rev-parse", "HEAD");
    f.put("packages/features/value.ts", "export const value = 2;");
    f.commit();
    assert.equal(f.plan({ base }).mode, "full");
  });
}

for (const reason of ["missing history", "full override", "dirty tree", "invalid policy"]) {
  test(`${reason} falls back without consuming a stale plan`, (t) => {
    const f = fixture(t);
    if (reason === "dirty tree") f.put("packages/features/value.ts", "export const value = 2;");
    if (reason === "invalid policy") {
      f.put(".github/test-selection.json", "broken");
      f.commit();
    }
    const plan = f.plan({
      base: reason === "missing history" ? "f".repeat(40) : f.base,
      full: reason === "full override",
    });
    assert.equal(plan.mode, "full");
    if (reason !== "full override") assert.equal(plan.fallback, true);
  });
}

test("always-run readers execute even for unaffected docs and empty affected shards", t => {
  const f = fixture(t);
  f.put("packages/features/contract.test.ts", "import {readFileSync} from 'node:fs'; import {test,expect} from 'bun:test'; test('contract',()=>expect(readFileSync('README.md','utf8')).toBe('docs'));");
  f.put("README.md", "docs"); const base = f.commit();
  f.put("docs/new.md", "docs"); f.commit();
  const alwaysRunFiles = ["packages/features/contract.test.ts"];
  const plan = f.plan({ base, alwaysRunFiles });
  assert.equal(plan.mode, "none");
  const result = execute(f, plan, { alwaysRunFiles, shards: 8 });
  assert.equal(result.status, 0);
  assert.deepEqual(result.selection.executedFiles, alwaysRunFiles);
});

test("an always-run contract failure cannot be hidden by an empty affected selection", t => {
  const f = fixture(t);
  f.put("README.md", "docs"); f.commit();
  const result = execute(f, f.plan(), { alwaysRunFiles: ["packages/features/unrelated.test.ts"], shards: 8 });
  assert.equal(result.selection.executedFiles.length, 1);
  f.put("packages/features/unrelated.test.ts", "import {test,expect} from 'bun:test';test('contract',()=>expect(1).toBe(2));"); f.commit();
  const failing = execute(f, f.plan(), { alwaysRunFiles: ["packages/features/unrelated.test.ts"], shards: 8 });
  assert.equal(failing.status, 1);
});

test("missing inventory fails rather than guessing a smaller full suite", t => {
  const f = fixture(t);
  assert.throws(() => readInventory(join(f.reports, "missing.json"), f.cwd));
  const path = join(f.reports, "inventory.json");
  for (const files of [[], ["../escape.test.ts"], ["packages/features/value.test.ts", "packages/features/value.test.ts"]]) {
    writeFileSync(path, JSON.stringify({schema_version:"ci-esta/bun-inventory/v1",files,alwaysRunFiles:[]}));
    assert.throws(() => readInventory(path, f.cwd));
  }
});

test("untracked source forces execution and forged reuse plans cannot skip", t => {
  const f = fixture(t);
  f.put("packages/features/new.ts", "export const value = 2;");
  assert.equal(f.plan().mode, "full");
  const result = execute(f, { mode: "reused", testedSha: f.git("rev-parse", "HEAD"), receipt: "not proof" });
  assert.equal(result.selection.mode, "full");
  assert.equal(result.selection.executedFiles.length, 3);
});

test("an explicit full override supersedes even a valid none plan", t => {
  const f = fixture(t);
  f.put("README.md", "docs"); f.commit();
  assert.equal(f.plan().mode, "none");
  const result = execute(f, f.plan(), { full: true, shards: 2 });
  assert.equal(result.selection.mode, "full");
  assert.equal(result.selection.executedFiles.length, 3);
});

test("an unchanged extensionless symlink in a runtime root forces full execution", t => {
  const f = fixture(t);
  symlinkSync("features", join(f.cwd, "packages/linked"));
  const base = f.commit();
  f.put("packages/features/value.ts", "export const value = 2;"); f.commit();
  assert.equal(f.plan({ base }).mode, "full");
  assert.equal(f.plan({ base }).fallback, true);
});

test("the action exports its real planner path for subsequent consumer controls", t => {
  const f = fixture(t);
  const output = join(f.reports, "github-output");
  const previous = process.env.GITHUB_OUTPUT;
  process.env.GITHUB_OUTPUT = output;
  try { execute(f, f.plan({ full: true })); }
  finally { if (previous === undefined) delete process.env.GITHUB_OUTPUT; else process.env.GITHUB_OUTPUT = previous; }
  const values = Object.fromEntries(readFileSync(output, "utf8").trim().split("\n").map(line => line.split("=")));
  assert.equal(values["selection-module"], new URL("../../actions/run-bun-tests/selection.mjs", import.meta.url).pathname);
});
