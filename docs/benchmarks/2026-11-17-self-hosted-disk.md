# Self-hosted runner disk writes, 2026-11-17

On self-hosted Kubernetes runners whose workspace is a separate volume, Python
setup wrote every package twice and the first Docker command afterwards waited
about 40 seconds for the disk. Starting the test service before dependency
setup and putting uv's download cache on the workspace volume removed that wait.

## What was slow

gigaverse-ai's pytest job ran on Actions Runner Controller pods (`arc-linux-16`,
a 200 GB `gp3` volume at default throughput, measured at 149 MB/s sustained).
Before its Redis service started, the job had written about 4.3 GB:

| Written | Size |
| --- | ---: |
| Python 3.14 into the tool cache | 420 MB |
| uv download cache restored from the Actions cache | 1,932 MB |
| The same 468 packages copied into `.venv` | 1,907 MB |

`setup-uv` keeps its cache in the home directory on self-hosted runners. The
pod's home directory and its workspace are different filesystems, so uv cannot
hard-link and copies each file. `docker run` and `docker rm` then block until
the dirty pages reach the disk. Pulling `redis:7-alpine` took 0.8 s and starting
it on an idle runner took 0.25 s; after the install the same start took 42 s
(median of 24 production jobs). GitHub-hosted runners took 2-4 s for that step.

## Controlled comparison

[Run 44085031667](https://github.com/gigaverse-app/gigaverse-ai/actions/runs/44085031667),
head `78b37ccff8`, five jobs per variant on `arc-linux-16`, at most four at a
time. Both variants check out the same commit, install the same locked
environment without the `.venv` archive, run the same 929 tests with four
workers, and stop Redis.

- **Before:** prefetch the image, `setup-cached-uv@v1`, start Redis, tests, stop.
- **After:** start Redis, `setup-cached-uv` with
  `uv-cache-path: ${{ runner.temp }}/setup-uv-cache`, tests, stop.

Overhead is the job's time from the first setup step to the end, minus the test
step.

| Variant | Overhead per job, seconds | Median | Dirty pages when tests start |
| --- | --- | ---: | ---: |
| Before | 67.1, 67.2, 68.3, 69.2, 85.7 | 68.3 | about 5 MB, after a 40 s wait |
| After | 26.4, 27.6, 27.9, 28.9, 29.7 | 27.9 | about 2.1 GB, flushed during tests |

The change saved a median of 40 seconds per job. Test time did not get worse
with the flush running in the background (54-73 s before, 55-67 s after), and
stopping Redis after the tests took under one second in every "after" job.

Earlier single-variable probes on the same runner type, two samples each:

| Variant | Wait on the first Docker command |
| --- | ---: |
| Today's order and cache location | 42-44 s |
| uv cache on the workspace volume only | 23 s |
| Redis first, stopped immediately after install | 39-40 s, moved to the stop |
| Redis first, stopped after 55 s of other work | 7-8 s |

Starting the service first helps only when the job then works for about a minute
before its next Docker command. Halving the writes shortens that window.

## Limits

- One repository, one runner type, one day. The disk's throughput is the cause;
  a runner with fast local storage will see little difference.
- The comparison used a 929-test slice, not the full selected suite.
- The Python tool-cache write remains until the runner image ships Python.
