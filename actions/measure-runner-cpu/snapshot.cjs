const { appendFileSync, existsSync, readFileSync } = require('node:fs');
const { cpuacctGroup, cpuacctMount } = require('./cpuacct.cjs');

function counter() {
  const vmStat = '/sys/fs/cgroup/cpu.stat';
  if (existsSync(vmStat)) {
    if (existsSync('/run/.containerenv')) return;
    const match = /^usage_usec (\d+)$/m.exec(readFileSync(vmStat, 'utf8'));
    return match && { id: 'vm', usec: BigInt(match[1]) };
  }

  const id = cpuacctGroup(readFileSync('/proc/self/cgroup', 'utf8'), readFileSync('/proc/self/mountinfo', 'utf8'));
  if (!id) return;
  const ns = readFileSync(cpuacctMount + '/cpuacct.usage', 'utf8').trim();
  if (/^\d+$/.test(ns)) return { id, usec: BigInt(ns) / 1000n };
}

function sample() {
  if (process.platform !== 'linux' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || existsSync('/.dockerenv')) return;

  const reading = counter();
  if (!reading) return;
  const now = Date.now();
  const previous = process.env.STATE_ci_esta_cpu_start;
  if (!previous) {
    appendFileSync(process.env.GITHUB_STATE, `ci_esta_cpu_start=${now} ${reading.usec} ${reading.id}\n`);
    return;
  }

  const [start, initial, id] = previous.split(' ');
  if (reading.id !== id) return;
  const used = reading.usec - BigInt(initial);
  if (now > Number(start) && used >= 0n) {
    const scope = id === 'vm' ? '' : ' scope=job-cgroup';
    console.log(`[ci-esta-job-cpu] start_ms=${start} end_ms=${now} used_usec=${used}${scope}`);
  }
}

try {
  sample();
} catch {
  console.log('Runner CPU counter unavailable.');
}
