import { invokePython, isEntrypoint } from "./python.mjs";

export const workSelectionReport = (execution, context) => invokePython("report", { execution, context });

if (isEntrypoint(import.meta.url)) {
  try { invokePython("report"); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
