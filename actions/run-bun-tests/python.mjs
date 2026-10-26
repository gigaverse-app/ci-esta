import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { delimiter, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const localPython = join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export function invokePython(operation, input, env = process.env) {
  const python = env.CI_ESTA_PYTHON || (existsSync(localPython) ? localPython : "python3");
  const result = spawnSync(python, ["-m", "ci_esta.testing.bun.cli", operation, ...(input === undefined ? [] : ["--json-input"])], {
    input: input === undefined ? undefined : JSON.stringify(input), encoding: "utf8",
    env: { ...env, PYTHONPATH: [join(root, "src"), env.PYTHONPATH].filter(Boolean).join(delimiter) },
    stdio: ["pipe", "pipe", "inherit"],
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`CI-esta Python ${operation} failed (${result.status})`);
  return result.stdout.trim() ? JSON.parse(result.stdout) : undefined;
}

export function isEntrypoint(url) {
  return process.argv[1] && resolve(process.argv[1]) === fileURLToPath(url);
}
