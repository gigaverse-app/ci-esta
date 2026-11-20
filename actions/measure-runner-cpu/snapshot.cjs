const { appendFileSync, existsSync, readFileSync } = require('node:fs');

function sample() {
  if (process.platform !== 'linux' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || existsSync('/.dockerenv') || existsSync('/run/.containerenv')) return;

  const match = /^usage_usec (\d+)$/m.exec(readFileSync('/sys/fs/cgroup/cpu.stat', 'utf8'));
  if (!match) return;
  const now = Date.now();
  const usage = BigInt(match[1]);
  const previous = process.env.STATE_ci_esta_cpu_start;
  if (!previous) {
    appendFileSync(process.env.GITHUB_STATE, `ci_esta_cpu_start=${now} ${usage}\n`);
    return;
  }

  const [start, initial] = previous.split(' ');
  const used = usage - BigInt(initial);
  if (now > Number(start) && used >= 0n) {
    console.log(`[ci-esta-job-cpu] start_ms=${start} end_ms=${now} used_usec=${used}`);
  }
}

try {
  sample();
} catch {
  console.log('Runner CPU counter unavailable.');
}
