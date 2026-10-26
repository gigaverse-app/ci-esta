import { appendFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { invokePython, isEntrypoint } from "./python.mjs";

export const readInventory = (path, cwd) => invokePython("inventory", { path, cwd });
export function runBunTests(options) {
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT,
    `selection-module=${fileURLToPath(new URL("./selection.mjs", import.meta.url))}\n`);
  return invokePython("run", options);
}

if (isEntrypoint(import.meta.url)) {
  try { invokePython("run"); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
