function outcome(name, result, required) {
  // An unexpected skip is not success. Failure/cancellation cannot be waived
  // even for a lane whose admission decision says it was unnecessary.
  if (result === 'success' || (required === false && result === 'skipped')) {
    return '';
  }
  if (result === 'failure') {
    return `${name} failed`;
  }
  if (result === 'cancelled') {
    return `${name} was cancelled`;
  }
  if (result === 'skipped') {
    return `${name} was skipped but is required`;
  }
  return result ? `${name} ended with result '${result}'` : `${name} has no result`;
}

function gateFailures(needs, required) {
  const keys = Object.keys(needs).sort();
  if (!keys.length || JSON.stringify(keys) !== JSON.stringify(Object.keys(required).sort())) {
    throw new Error('Every direct prerequisite must have an explicit admission decision.');
  }
  const untyped = keys.filter(key => typeof required[key] !== 'boolean');
  if (untyped.length) {
    throw new Error(`Admission decisions must be true or false: ${untyped.join(', ')}`);
  }
  return keys.map(key => outcome(key, needs[key]?.result, required[key])).filter(Boolean);
}

function failureMessage(failures, total) {
  return `Validation gate failed: ${failures.length} of ${total} prerequisite jobs did not pass: ` +
    `${failures.join('; ')}.`;
}

function validateGate(needs, required) {
  const failures = gateFailures(needs, required);
  if (failures.length) {
    throw new Error(failureMessage(failures, Object.keys(needs).length));
  }
}

function selectedRequirements(needs, planner, lanes, laneJobs) {
  if (!lanes || typeof lanes !== 'object' || Array.isArray(lanes) ||
      !laneJobs || typeof laneJobs !== 'object' || Array.isArray(laneJobs)) {
    throw new Error('Lane and job maps must be JSON objects.');
  }
  // Without lane-jobs no job is optional: every direct prerequisite must succeed,
  // and no planner is involved. A lane mapping makes skips possible, so it needs one.
  const required = Object.fromEntries(Object.keys(needs).map(name => [name, true]));
  if (!Object.keys(laneJobs).length) {
    return required;
  }
  if (!needs[planner]) {
    throw new Error(`lane-jobs needs the planner '${planner}' as a direct prerequisite; set the planner input to the job that produced the lanes.`);
  }
  for (const [job, inputs] of Object.entries(laneJobs)) {
    if (!(job in needs) || job === planner || !Array.isArray(inputs) || !inputs.length ||
        inputs.some(lane => typeof lane !== 'string' || !lane)) {
      throw new Error(`Invalid lane mapping for ${job}`);
    }
    required[job] = !(needs[planner].result === 'success' && inputs.every(lane => lanes[lane] === false));
  }
  return required;
}

/**
 * The action's entry point. A failing prerequisite is the gate's expected verdict, not an error in the action:
 * report every job that did not pass through `core.setFailed`, so the log and annotation name them plainly
 * instead of github-script's "Unhandled error" wrapper around a thrown exception.
 */
function run(env, core) {
  let needs;
  let required;
  let failures;
  try {
    needs = JSON.parse(env.VALIDATION_NEEDS);
    required = (env.VALIDATION_REQUIRED || '').trim()
      ? JSON.parse(env.VALIDATION_REQUIRED)
      : selectedRequirements(needs, env.VALIDATION_PLANNER,
          JSON.parse(env.VALIDATION_LANES || '{}'), JSON.parse(env.VALIDATION_LANE_JOBS || '{}'));
    failures = gateFailures(needs, required);
  } catch (error) {
    core.setFailed(`Validation gate configuration error: ${error.message}`);
    return;
  }
  const total = Object.keys(needs).length;
  if (failures.length) {
    core.setFailed(failureMessage(failures, total));
    return;
  }
  const waived = Object.keys(needs).filter(key => needs[key].result === 'skipped').sort();
  core.info(`Validation gate passed: ${total - waived.length} prerequisite jobs succeeded` +
    (waived.length ? `; skipped as not needed by the plan: ${waived.join(', ')}.` : '.'));
}

module.exports = { validateGate, selectedRequirements, gateFailures, run };
