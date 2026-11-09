function validateGate(needs, required) {
  const keys = Object.keys(needs).sort();
  if (!keys.length || JSON.stringify(keys) !== JSON.stringify(Object.keys(required).sort())) {
    throw new Error('Every direct prerequisite must have an explicit admission decision.');
  }
  for (const key of keys) {
    const result = needs[key]?.result;
    // An unexpected skip is not success. Failure/cancellation cannot be waived
    // even for a lane whose admission decision says it was unnecessary.
    if (typeof required[key] !== 'boolean' ||
        !(result === 'success' || (required[key] === false && result === 'skipped'))) {
      throw new Error(`Validation prerequisite ${key}: required=${required[key]}, result=${result}`);
    }
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

module.exports = { validateGate, selectedRequirements };
