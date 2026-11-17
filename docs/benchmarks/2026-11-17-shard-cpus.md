# Shard CPU placement on shared nodes, 2026-11-17

Two runner pods on one Kubernetes node pinned their test shards to the same
CPUs and ran about 60% slower than a pod with the node to itself. `run-local`
now chooses a CPU for every shard, preferring CPUs nothing else is using.

## What was slow

gigaverse-ai runs 16 pytest shards inside one Actions Runner Controller pod and
pins each shard to one CPU: "shard *i* takes the *i*-th CPU the process may use".
The pods have a CPU request and no limit, so each one sees every CPU of its node.
On a 32-CPU node holding two such pods, both pinned to CPUs 0-15 and CPUs 16-31
stayed idle.

Three full runs of the same commit, started within ten seconds of each other
with the same shard plan ([44115199578](https://github.com/gigaverse-app/gigaverse-ai/actions/runs/44115199578),
[44115208460](https://github.com/gigaverse-app/gigaverse-ai/actions/runs/44115208460),
[44115218220](https://github.com/gigaverse-app/gigaverse-ai/actions/runs/44115218220)):

| Run | Node | Mean shard | Slowest shard |
| --- | --- | ---: | ---: |
| 44115199578 | `ip-100-64-80-14`, shared with the run below | 261 s | 289 s |
| 44115218220 | `ip-100-64-80-14`, shared with the run above | 252 s | 286 s |
| 44115208460 | another node | 161 s | 176 s |

The node of the third run was not recorded; the first two were confirmed from
the cluster's scheduling events.

## Controlled comparison

[Run 44122197309](https://github.com/gigaverse-app/gigaverse-ai/actions/runs/44122197309),
one `arc-linux-16` pod on a 32-CPU node (AMD EPYC 9R14). Each "shard" pins itself
to one CPU and does a fixed amount of single-core work. A pool is 16 shards under
`ci-esta-pytest run-local`. "Old" ignores the advice and takes the *i*-th allowed
CPU; "new" pins to `CI_ESTA_SHARD_CPU`.

| Scenario | Old placement | New placement |
| --- | ---: | ---: |
| One pool alone | 17.1 s, 17.3 s | 18.6 s |
| Two pools at once, each pool's wall time | 30.0 s, 32.3 s, 32.4 s, 32.6 s | 17.0 s, 17.2 s |

With the new placement two concurrent pools finish as fast as one alone. On a
16-CPU node there is no spare CPU and nothing changes: two pools took 42-44 s
each under both placements, against 22-23 s alone.

## Limits

- Four "old" and two "new" two-pool samples: a spot interruption ended the job
  before the second "new" round. The effect is a factor of two and the mechanism
  is direct, but this is short of five runs each.
- The comparison uses CPU-bound stand-in work, not pytest. Real shards also wait
  on I/O, so the production gain is the 161 s against 252-261 s above, not 2x.
- Two pools that fill a node's CPUs share hyperthreads. Placement cannot fix a
  node with fewer CPUs than shards across its pods.
- CPUs are sampled once, for a quarter of a second, when the pool starts. A
  neighbour that starts later is not seen; random choice among idle CPUs limits
  how badly two simultaneous starts can overlap.

## Follow-up the same day: one shard per physical core

The first version chose idle CPUs at random. On a hyperthreaded node that puts
some pairs of shards on the two threads of one core, where the index rule had
given a runner alone on the node sixteen separate cores. Seven full gigaverse-ai
runs after adoption averaged 185-228 s per shard, against 161 s for the one run
that had a 32-CPU node to itself before the change; five of the seven were on
32-CPU nodes. Machines and neighbours differed between those runs, so this is
an indication, not a controlled result.

Placement now reads each CPU's core from `thread_siblings_list`. Every shard
takes one thread of a core, fully idle cores first, and second threads are used
only when cores run out. Next to a neighbour that holds one thread of every
core, shards take the idle sibling threads, as before.
