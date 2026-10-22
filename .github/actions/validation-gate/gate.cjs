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

module.exports = { validateGate };
