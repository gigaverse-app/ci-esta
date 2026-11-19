from datetime import UTC, datetime

import pytest

from ci_esta.ci_observability import allocation
from ci_esta.ci_observability.models import GitHubJobV1, RunnerCpuAllocation, RunnerSkuRateV1
from ci_esta.ci_observability.report import _observe_job


def test_accounting_clips_scrapes_and_keeps_bursts_above_reservation():
    a = RunnerCpuAllocation(pool="light", cores=2, occupied_seconds=20)
    allocation.measure(allocation.CounterSeries(values=[(5, 0), (15, 30), (25, 60), (35, 90)]), 10, 30, a)
    assert (a.covered_seconds, a.used_core_seconds, a.unused_core_seconds, a.peak_sampled_cores) == (20, 60, -20, 3)


def test_unobserved_edges_resets_and_scrape_outages_cannot_be_counted_as_idle():
    a = RunnerCpuAllocation(pool="light", cores=2, occupied_seconds=150)
    allocation.measure(allocation.CounterSeries(values=[(10, 20), (20, 25), (30, 1), (130, 10)]), 0, 150, a)
    assert (a.allocated_core_seconds, a.covered_seconds, a.used_core_seconds, a.unused_core_seconds) == (300, 10, 5, 15)


@pytest.mark.parametrize("series", [[], [{"values": [[100, "0"], [115, "0"]]}] * 2])
def test_absent_or_ambiguous_pod_data_preserves_reservation_without_claiming_zero_use(monkeypatch, series):
    import httpx

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": {"result": series}}))
    client = httpx.Client(transport=transport)
    monkeypatch.setattr(allocation.httpx, "Client", lambda **options: client)
    start, end = [datetime.fromtimestamp(t, UTC) for t in (100, 115)]
    job = _observe_job(GitHubJobV1(id=2, name="build", labels=["light"], runner_name="pod-123", status="completed",
                                   started_at=start, completed_at=end), start, end)
    rate = RunnerSkuRateV1(sku="light", runner_label="light", allocated_cores=2)
    rows = allocation.collect([job], [rate], "http://prometheus", "runners")
    assert "unknown" in allocation.section(rows)[0]
    assert allocation.metrics(rows) == ['ci_runner_cpu_allocated_core_seconds{pool="light"} 30',
                                       'ci_runner_cpu_covered_core_seconds{pool="light"} 0']
