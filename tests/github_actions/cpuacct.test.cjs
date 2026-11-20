const assert = require('node:assert/strict');
const test = require('node:test');
const { cpuacctGroup } = require('../../actions/measure-runner-cpu/cpuacct.cjs');

test('only the cpuacct mount rooted at the current job measures the slim worker', () => {
  const own = '/containers/job';
  const mount = '51 40 0:33 /containers/job /sys/fs/cgroup/cpuacct ro - cgroup cgroup rw,cpuacct';
  const membership = '4:memory:/containers/other\n3:cpuacct:/containers/job\n2:cpu:/containers/job';
  assert.equal(cpuacctGroup(membership, mount), own);
  assert.equal(cpuacctGroup(membership, mount.replace(own, '/')), undefined);
  assert.equal(cpuacctGroup(membership, mount.replace(own, '/containers/job-sibling')), undefined);
  assert.equal(cpuacctGroup(membership, mount.replace('rw,cpuacct', 'rw,cpu')), undefined);
  assert.equal(cpuacctGroup('3:cpuacct:/', mount.replace(own, '/')), undefined);
});
