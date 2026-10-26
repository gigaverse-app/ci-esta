import { readFileSync } from "node:fs";

// Keep the Node-only adapter aligned with pytest-selective's public checkpoint API.
// Cross-runtime conformance tests exercise both implementations with the same events.
export function fullCheckpointReason(value, env = process.env) {
  if (value === "true") return "full suite explicitly requested (--full true)";
  if (value === "false") return null;
  if (value !== "auto") throw new Error("full must be auto, true, or false");
  const event = env.GITHUB_EVENT_NAME;
  if (event === "push") return null;
  if (["workflow_dispatch", "workflow_call", "schedule", "release"].includes(event))
    return `full suite required by ${event} checkpoint`;
  if (event !== "pull_request") return "full suite fallback: unsupported or missing event metadata";
  try {
    const labels = JSON.parse(readFileSync(env.GITHUB_EVENT_PATH, "utf8")).pull_request.labels;
    if (!Array.isArray(labels) || labels.some(label => !label || typeof label.name !== "string"))
      throw new Error("Invalid PR labels");
    return labels.some(label => label.name === "test:full") ? "full suite requested by test:full label" : null;
  } catch {
    return "full suite fallback: pull request event metadata unavailable or invalid";
  }
}
