import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { extname, join } from "node:path";

const opaqueDependency =
  /\b(?:Bun\s*\.\s*file|readFile(?:Sync)?|import\s*\.\s*meta\s*\.\s*glob)\b|["'](?:node:)?fs(?:\/promises)?["']|\b(?:import|require)\s*\(\s*(?!\s*["'])[^\s]/;

export function planAffectedTests({ cwd = process.cwd(), base, full = false, policyFile = ".github/test-selection.json", alwaysRunFiles = [] }) {
  const git = (...args) => execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  const plan = {
    mode: "full",
    base: "",
    testedSha: "",
    changedFiles: [],
    fallback: false,
    reason: "Full checkpoint requested",
  };
  try {
    plan.testedSha = git("rev-parse", "HEAD").trim();
    if (full) return plan;
    if (!base || !/^[0-9a-f]{40}$/.test(base)) throw new Error("Missing committed selection base");
    plan.base = git("rev-parse", "--verify", `${base}^{commit}`).trim();
    git("merge-base", "--is-ancestor", plan.base, plan.testedSha);
    if (git("status", "--porcelain", "--untracked-files=no").trim())
      throw new Error("Tracked worktree differs from the planned commit");
    const policy = JSON.parse(readFileSync(join(cwd, policyFile), "utf8"));
    if (policy.schema_version !== "ci-esta/bun-policy/v1") throw new Error("Unsupported selection policy version");
    for (const key of ["scopedRoots", "unaffectedPaths", "unaffectedRoots", "sourceExtensions", "runtimeRoots"]) {
      if (!Array.isArray(policy[key]) || !policy[key].every((value) => safePath(value))) {
        throw new Error(`Invalid selection policy: ${key}`);
      }
    }
    if (!policy.reviewedReaders || Array.isArray(policy.reviewedReaders) || typeof policy.reviewedReaders !== "object")
      throw new Error("Missing reader declarations");
    if (git("ls-files", "--others", "--exclude-standard").trim())
      throw new Error("Untracked inputs are outside the committed selection contract");
    for (const root of [...policy.scopedRoots, ...policy.runtimeRoots, ...policy.unaffectedRoots]) {
      if (!root.endsWith("/")) throw new Error("Policy roots must end with /");
    }
    const entries = git("diff", "--name-status", "--no-renames", "-z", plan.base, plan.testedSha, "--")
      .split("\0")
      .filter(Boolean);
    const changes = [];
    for (let i = 0; i < entries.length; i += 2) changes.push({ status: entries[i], path: entries[i + 1] });
    plan.changedFiles = changes.map((change) => change.path);
    const source = (file) =>
      policy.scopedRoots.some((root) => file.startsWith(root)) && policy.sourceExtensions.includes(extname(file));
    const unaffected = (file) =>
      policy.unaffectedPaths.includes(file) ||
      (policy.unaffectedRoots.some((root) => file.startsWith(root)) && /\.md$/.test(file));
    const readerInputs = Object.values(policy.reviewedReaders).flatMap((reader) => {
      if (
        !/^[0-9a-f]{40}$/.test(reader.blob) ||
        !Array.isArray(reader.inputs) ||
        !reader.inputs.every((input) => safePath(input))
      )
        throw new Error("Invalid reader declaration");
      return reader.inputs;
    });
    const fullInput = changes.find(
      (change) =>
        !["A", "M"].includes(change.status) ||
        (!source(change.path) && !unaffected(change.path)) ||
        readerInputs.some((input) => (input.endsWith("/") ? change.path.startsWith(input) : change.path === input)),
    );
    if (fullInput)
      return { ...plan, reason: `Full suite for shared, non-import, deleted or unknown input: ${fullInput.path}` };
    const tracked = git("ls-files", "--stage", "-z").split("\0").filter(Boolean);
    for (const entry of tracked) {
      const [metadata, file] = entry.split("\t");
      if (alwaysRunFiles.includes(file)) continue;
      if (
        !policy.runtimeRoots.some((root) => file.startsWith(root)) ||
        !policy.sourceExtensions.includes(extname(file))
      )
        continue;
      if (!metadata.startsWith("100644 ") && !metadata.startsWith("100755 "))
        throw new Error(`Non-regular source input: ${file}`);
      if (opaqueDependency.test(readFileSync(join(cwd, file), "utf8"))) {
        if (policy.reviewedReaders[file]?.blob === metadata.split(" ")[1]) continue;
        return {
          ...plan,
          fallback: true,
          reason: `Import analysis cannot prove file-based or computed dependencies in ${file}`,
        };
      }
    }
    if (!changes.some((change) => source(change.path))) {
      return {
        ...plan,
        mode: "none",
        reason: "Only declared unaffected inputs changed; always-run tests still execute",
      };
    }
    return {
      ...plan,
      mode: "scoped",
      reason: `Bun import analysis against ${plan.base}; ${changes.filter((change) => source(change.path)).length} source/test files changed`,
    };
  } catch (error) {
    return {
      ...plan,
      fallback: true,
      reason: `Selection unavailable; run the full suite: ${String(error).split("\n")[0]}`,
    };
  }
}

export function readTestSelection(path, options = {}) {
  try {
    const saved = JSON.parse(readFileSync(path, "utf8"));
    const actual = planAffectedTests({ ...options, base: saved.base, full: saved.mode === "full" });
    if (!["full", "scoped", "none"].includes(saved.mode) || actual.testedSha !== saved.testedSha || actual.mode !== saved.mode)
      throw new Error("Plan does not match the checked-out revision and current policy");
    return actual;
  } catch (error) {
    return { ...planAffectedTests({ ...options, full: true }), fallback: true,
      reason: `Missing or invalid execution plan; run the full suite: ${String(error).split("\n")[0]}` };
  }
}

export function safePath(value) {
  return typeof value === "string" && value.length > 0 && !value.startsWith("/") &&
    !value.includes("\\") && !value.includes("\n") && !value.includes("\r") && !value.includes("\0") &&
    !value.split("/").some(part => part === ".." || part === ".") && !value.includes(":");
}
