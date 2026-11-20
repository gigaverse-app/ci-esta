from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from ci_esta.ci_observability import allocation
from ci_esta.ci_observability.models import GitHubJobV1, GitHubStepV1, RunnerSkuRateV1
from ci_esta.ci_observability.report import _observe_job


@pytest.mark.parametrize(("sku", "steps", "expected_reads"), [
    ("linux_16_core", {"Test"}, 1),
    ("linux_16_core", {"Another step"}, 0),
    ("self_hosted", {"Test"}, 0),
    ("actions_linux_slim", {"Test"}, 0),
])
def test_only_measured_work_on_a_declared_dedicated_vm_counts(sku, steps, expected_reads):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(seconds=60)
    job = _observe_job(GitHubJobV1(
        id=2, name="build", labels=["configured"], runner_name="worker",
        status="completed", started_at=start, completed_at=end,
        steps=[GitHubStepV1(number=1, name="Test", status="completed", started_at=start,
                            completed_at=start + timedelta(seconds=30))]), start, end)
    log = "\n".join(f"2026-01-01T00:00:{sec:02}.0000000Z [ci-test-resource] {line}" for sec, line in [
        (2, "initial cpu.stat"), (2, "  usage_usec 1000000"), (2, "cpu.stat usage_usec 1100000"),
        (12, "cpu.stat usage_usec 31000000 user_usec 191"), (16, "final cpu.stat"),
        (16, "  usage_usec 35000000"), (20, "initial cpu.stat"), (20, "  usage_usec 40000000"),
        (25, "final cpu.stat"), (25, "  usage_usec 45000000"), (36, "initial cpu.stat"),
        (36, "  usage_usec 90000000"), (55, "final cpu.stat"), (55, "  usage_usec 95000000")])
    read = Mock(return_value=log)
    row, = allocation.collect([job], [RunnerSkuRateV1(runner_label="configured", sku=sku, allocated_cores=16)],
                              None, "", resource_steps=steps, read_job_log=read)
    assert read.call_count == expected_reads
    a = row.cpu_allocation
    assert a.allocated_core_seconds == 960
    if expected_reads:
        assert (a.covered_seconds, a.used_core_seconds, a.unused_core_seconds, a.peak_sampled_cores) == (19, 39, 265, 3)
    else:
        assert a.covered_seconds == 0 and a.used_core_seconds is None

def test_log_limit_counts_streamed_bytes_and_preserves_existing_readers():
    import httpx

    from ci_esta.ci_observability.github import GitHubActionsClient

    client = GitHubActionsClient("org/repo", "test", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * 65537)))
    try:
        assert len(client.job_log(1)) == 65537
        assert len(client.job_log(1, max_bytes=65537)) == 65537
        with pytest.raises(ValueError, match="size limit"):
            client.job_log(1, max_bytes=65536)
    finally:
        client.close()


@pytest.mark.parametrize(("post", "end_offset", "sku", "measured"), [
    ("Post Measure runner CPU", 181, "linux_8_core", True),
    ("Post another action", 181, "linux_8_core", False),
    ("Post Measure runner CPU", 100, "linux_8_core", False),
    ("Post Measure runner CPU", 181, "self_hosted", False),
    ("Post Measure runner CPU", 181, "actions_linux_slim", False),
])
def test_job_counter_requires_a_matched_action_and_cleanup(post, end_offset, sku, measured):
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def step(number, name, first, last):
        return GitHubStepV1(number=number, name=name, status="completed", started_at=start+timedelta(seconds=first),
                            completed_at=start+timedelta(seconds=last))

    end = start + timedelta(seconds=185)
    job = _observe_job(GitHubJobV1(id=7, name="build", labels=["configured"], runner_name="worker",
                       status="completed", started_at=start, completed_at=end,
                       steps=[step(1, "Measure runner CPU", 2, 3), step(2, "Payload", 10, 100),
                              step(3, post, 180, 181)]), start, end)
    epoch_ms = int(start.timestamp()*1000)
    log = (f"2026-01-01T00:03:01.200Z [ci-esta-job-cpu] start_ms={epoch_ms+2500} "
           f"end_ms={epoch_ms+end_offset*1000} used_usec=350000000\n")
    if measured:
        # The named payload is inside the job span. Its sampled peak survives
        # without adding its CPU a second time.
        log += ("2026-01-01T00:00:11.000Z [ci-test-resource] initial cpu.stat\n"
                "2026-01-01T00:00:11.001Z [ci-test-resource]   usage_usec 0\n"
                "2026-01-01T00:00:21.000Z [ci-test-resource] final cpu.stat\n"
                "2026-01-01T00:00:21.001Z [ci-test-resource]   usage_usec 40000000\n")
    read = Mock(return_value=log)
    row, = allocation.collect([job], [RunnerSkuRateV1(runner_label="configured", sku=sku, allocated_cores=8)],
                              None, "", resource_steps={"Measure runner CPU", "Payload"}, read_job_log=read)
    observed = row.cpu_allocation
    assert observed.covered_seconds == (178.5 if measured else 0)
    assert observed.used_core_seconds == (350 if measured else None)
    assert observed.peak_sampled_cores == (4 if measured else None)
