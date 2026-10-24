import { setTimeout } from 'node:timers/promises';

const SHA = /^[0-9a-f]{40}$/;

// HTTP representation is an adapter. The polling/ancestry lifecycle below also
// works with a cluster API or an artifact registry supplying observe(signal).
export function revisionReader({ source = 'json', key = 'sha' } = {}) {
  if (!['json', 'header', 'pattern'].includes(source) || typeof key !== 'string' || !key) {
    throw new Error('Revision source must be json, header, or pattern, with a nonempty key');
  }
  const pattern = source === 'pattern' ? new RegExp(key) : null;
  return async response => {
    let sha;
    if (source === 'header') sha = response.headers.get(key);
    else if (source === 'pattern') sha = (await response.text()).match(pattern)?.[1];
    else {
      let value = await response.json();
      for (const part of key.split('.')) value = value?.[part];
      sha = value;
    }
    if (typeof sha !== 'string' || !SHA.test(sha)) throw new Error('Deployed revision missing or invalid');
    return sha;
  };
}

export async function waitForRevision(observe, {
  expectedSha = '', timeoutMs = 600000, pollMs = 10000, compareCommits,
} = {}) {
  if ((expectedSha && !SHA.test(expectedSha)) || !Number.isFinite(timeoutMs) || timeoutMs <= 0 ||
      !Number.isFinite(pollMs) || pollMs <= 0) throw new Error('Invalid revision or polling budget');
  const deadline = Date.now() + timeoutMs;
  const comparisons = new Map();
  let lastObservation = 'no response';
  do {
    let sha;
    try {
      const observed = await observe(AbortSignal.timeout(Math.max(1, Math.min(15000, deadline - Date.now()))));
      if (typeof observed !== 'string' || !SHA.test(observed)) throw new Error('Deployed revision missing or invalid');
      sha = observed;
      if (!expectedSha || sha === expectedSha) return { state: 'ready', sha };
    } catch (error) {
      if (!expectedSha) throw error;
      const cutOffByDeadline = error.name === 'TimeoutError' && Date.now() >= deadline;
      if (!cutOffByDeadline || lastObservation === 'no response') lastObservation = error.message;
    }
    if (sha && compareCommits) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) break;
      if (!comparisons.has(sha)) {
        try {
          comparisons.set(sha, await compareCommits(expectedSha, sha, Math.min(15000, remaining)));
        } catch (error) {
          lastObservation = `served ${sha}; commit comparison failed: ${error.message}`;
        }
      }
      const status = comparisons.get(sha);
      if (comparisons.has(sha) && !['ahead', 'behind', 'diverged', 'identical'].includes(status)) {
        throw new Error(`Unknown commit comparison: ${status}`);
      }
      if (status === 'ahead') return { state: 'superseded', sha };
      if (comparisons.has(sha)) lastObservation = `served ${sha}`;
    } else if (sha) lastObservation = `served ${sha}`;
    const remaining = deadline - Date.now();
    if (remaining <= 0) break;
    await setTimeout(Math.min(pollMs, remaining));
  } while (Date.now() < deadline);
  throw new Error(`Commit ${expectedSha} was not deployed within ${timeoutMs / 1000}s; ${lastObservation}`);
}

export function observeDeployment(url, { source, key, cacheKey = 'deployment_check', ...options } = {}) {
  const target = new URL(url);
  if (!['https:', 'http:'].includes(target.protocol)) throw new Error('Deployment URL must use HTTP or HTTPS');
  const read = revisionReader({ source, key });
  return waitForRevision(async signal => {
    if (cacheKey) target.searchParams.set(cacheKey, `${options.expectedSha || 'e2e'}-${Date.now()}`);
    const response = await fetch(target, { headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' }, signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return read(response);
  }, options);
}
