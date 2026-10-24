import { execFileSync } from 'node:child_process';
import { appendFileSync } from 'node:fs';
import { observeDeployment } from './observe.mjs';

try {
  const { state, sha } = await observeDeployment(process.env.DEPLOYMENT_URL, {
    source: process.env.REVISION_SOURCE || 'json',
    key: process.env.REVISION_KEY || 'sha',
    cacheKey: process.env.CACHE_KEY ?? 'deployment_check',
    expectedSha: process.env.EXPECTED_SHA || '',
    timeoutMs: Number(process.env.TIMEOUT_SECONDS || 600) * 1000,
    pollMs: Number(process.env.POLL_SECONDS || 10) * 1000,
    compareCommits: process.env.COMPARE_REPOSITORY ? (base, head, timeout) => {
      return execFileSync('gh', [
        'api', `/repos/${process.env.COMPARE_REPOSITORY}/compare/${base}...${head}`, '--jq', '.status',
      ], { encoding: 'utf8', timeout, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
    } : undefined,
  });
  const output = `state=${state}\nsha=${sha}\n`;
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, output);
  if (state === 'superseded' && process.env.GITHUB_STEP_SUMMARY) {
    appendFileSync(process.env.GITHUB_STEP_SUMMARY,
      `### Smoke skipped: newer commit deployed\n\nExpected: \`${process.env.EXPECTED_SHA}\`\n\nDeployed descendant: \`${sha}\`\n\nNo smoke tests ran for this commit.\n`);
  }
  process.stdout.write(output);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
