// The base is proven clean only by a successful check run of the configured checker on that
// exact commit. A skipped, cancelled, neutral or missing run proves nothing, and neither does
// a later rerun that failed: the newest completed run of each name decides.
function provenClean(checkRuns, names) {
  const newest = new Map();
  for (const run of checkRuns) {
    if (!names.includes(run.name) || run.status !== 'completed') continue;
    const current = newest.get(run.name);
    if (!current || Date.parse(run.completed_at) > Date.parse(current.completed_at)) newest.set(run.name, run);
  }
  return [...newest.values()].some((run) => run.conclusion === 'success');
}

// Check-run names contain spaces ("type-check / basedpyright"): one name per line.
function checkNames(text) {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

module.exports = { provenClean, checkNames };
