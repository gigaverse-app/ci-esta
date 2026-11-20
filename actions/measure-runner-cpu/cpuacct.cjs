const cpuacctMount = '/sys/fs/cgroup/cpuacct';

// The slim runner mounts its assigned cgroup here. A shared VM root or
// a different container's mount also has a counter, but cannot measure this job.
function cpuacctGroup(membership, mountinfo) {
  const group = membership.split('\n').map(line => line.split(':'))
    .find(([, controllers]) => controllers?.split(',').includes('cpuacct'))?.[2];
  if (!group || group === '/') return;

  for (const line of mountinfo.split('\n')) {
    const [location, filesystem] = line.split(' - ');
    const [, , , root, mount] = location.split(' ');
    const [type, , options] = (filesystem || '').split(' ');
    if (root === group && mount === cpuacctMount && type === 'cgroup' && options?.split(',').includes('cpuacct'))
      return group;
  }
}

module.exports = { cpuacctGroup, cpuacctMount };
