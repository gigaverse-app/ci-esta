# Overlap image download with test setup

Use this on a Linux runner with Docker when a test service's image pull delays
dependency setup. `warm` starts an advisory background pull. `start` still
requires a running, healthy container before tests can execute, even if prefetch
failed or was omitted. Keep service eligibility in your repository; uncertain
or full test selections should retain their services.

```yaml
- uses: gigaverse-app/ci-esta/actions/service-container@v1
  with:
    phase: warm
    name: pytest-redis
    image: redis:7-alpine
- uses: gigaverse-app/ci-esta/actions/setup-cached-uv@v1
- uses: gigaverse-app/ci-esta/actions/service-container@v1
  with:
    name: pytest-redis
    image: redis:7-alpine
    ports: '6379:6379'
    health-command: redis-cli ping
- run: uv run pytest
- uses: gigaverse-app/ci-esta/actions/service-container@v1
  if: always()
  with:
    phase: stop
    name: pytest-redis
```

Use a unique name per service on each runner. Additional port mappings go on
separate lines. `timeout-seconds` overrides the 30-second health wait after
Docker finishes pulling and starting the container. The job timeout still
bounds the image pull. Call `stop` with `always()` to clean up failed starts and
failed tests. Cancellation before `start` leaves no container to remove.

On runners with slow disks, skip `warm` and call `start` before dependency
setup. `docker run` waits for pending disk writes, so a start that follows a
multi-gigabyte install can block for tens of seconds while the pull itself takes
one. Started first, the container is healthy in about a second and the writes
flush while tests run. See the
[2026-11-17 measurement](../../docs/benchmarks/2026-11-17-self-hosted-disk.md).

For existing images on a warm runner, prefetch can add overhead; measure the
whole job and the health wait on representative selections. This action does
not infer whether a selected test needs Redis or remove any validation gate.
