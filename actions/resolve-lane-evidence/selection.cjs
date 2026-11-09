// Normalize a selector's actual execution scope before binding it into receipts.
// This consumes selector evidence; it does not compute affected tests.
function object(value) {
  try { value = typeof value === 'string' ? JSON.parse(value) : value; } catch { return {}; }
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function executionScope(keys, selection, outcome, report) {
  if (!Array.isArray(keys) || keys.some(key => typeof key !== 'string' || !key) || new Set(keys).size !== keys.length) {
    throw new Error('selection-keys must be distinct nonempty strings');
  }
  const lanes = object(selection);
  const plan = object(report);
  const selected = Object.fromEntries(keys.map(key => [key, outcome !== 'success' || lanes[key] !== false]));
  const reusable = outcome === 'success' && keys.length > 0 &&
    typeof plan.reason === 'string' && plan.reason.trim() !== '' &&
    !/fallback|explicit full-suite checkpoint/i.test(plan.reason) &&
    keys.every(key => lanes[key] === selected[key] && plan.lanes?.[key] === selected[key]);
  return { selected, context: JSON.stringify(selected), reusable };
}

function pendingMatrix(keys, reused) {
  const proof = object(reused);
  const pending = keys.filter(key => proof[key] !== true);
  // Admission skips all-proven work; GitHub still needs a nonempty matrix.
  return pending.length ? pending : keys;
}

// A planner's lane booleans after reuse: a lane becomes false only when every evidence key it
// lists is proven. A lane that lists no keys, an unknown key or partial proof keeps its plan,
// so it runs in full. `ci-esta check-workflow` verifies each lane's keys name every job the
// lane gates, matrix cells included; without that check an unlisted job could be skipped.
function admittedLanes(planned, laneKeys, reused, evidenceLanes) {
  const plan = object(planned);
  const proof = object(reused);
  const known = object(evidenceLanes);
  const admitted = {...plan};
  for (const [lane, keys] of Object.entries(object(laneKeys))) {
    if (!Array.isArray(keys) || !keys.length || keys.some(key => typeof key !== 'string' || !(key in known))) {
      throw new Error(`lane-keys.${lane} must list keys of lanes`);
    }
    if (plan[lane] === true && keys.every(key => proof[key] === true)) admitted[lane] = false;
  }
  return admitted;
}

module.exports = { executionScope, pendingMatrix, admittedLanes };
