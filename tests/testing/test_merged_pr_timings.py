from datetime import timedelta

import pytest

from ci_esta.testing.merged_pr_timings import MergedPRTimingCollector, measurement_name, publish_promotion
from ci_esta.testing.timing_history import Observation
from ci_esta.testing.timing_store import TimingHistory, combine_histories, observation_stamp
from tests.testing.merged_pr_server import NOW, POLICY, MergedPRServer


@pytest.fixture
def remote():
    server = MergedPRServer()
    try:
        yield server
    finally:
        server.close()


def test_real_api_to_history_preserves_source_and_unobserved_files(remote):
    remote.ready()
    decision = MergedPRTimingCollector(remote.client, POLICY).stage(7)
    assert decision.status == "ready"
    assert decision.promotion is not None
    original = TimingHistory(key="unit", observations={"test_b.py": Observation(5, "seed")},
                             tracked_files={"test_a.py", "test_b.py"}, inventory_at=NOW,
                             producer_run_id=99, producer_attempt=2)
    published = publish_promotion(original, decision.promotion)
    assert published.observations["test_a.py"].seconds == 1
    assert published.observations["test_b.py"].seconds == 5
    assert published.producer_run_id == 99
    assert "test_a.py" not in original.observations
    assert publish_promotion(published, decision.promotion) == published
    newer = published.model_copy(deep=True)
    newer.observations["test_a.py"] = Observation(20, observation_stamp(NOW + timedelta(days=1), 100, 1))
    combined = combine_histories([newer, published], "unit", NOW + timedelta(days=2))
    assert combined.observations["test_a.py"].seconds == 20
    assert combined.observations["test_b.py"].seconds == 5


@pytest.mark.parametrize("fault", ["open", "fork", "wrong_branch", "red", "gate_late", "marker", "missing",
                                  "invalid", "expired", "foreign", "wrong_attempt", "partial", "key", "newer_red"])
def test_uncertain_or_ineligible_evidence_never_changes_history(remote, fault):
    remote.ready()
    if fault == "open":
        remote.pr["merged_at"] = None
    elif fault == "fork":
        remote.pr["head"]["repo"]["full_name"] = "foreign/repo"
    elif fault == "wrong_branch":
        remote.pr["base"]["ref"] = "other"
    elif fault == "red":
        remote.finish(1, "failure")
    elif fault == "gate_late":
        remote.jobs[1][0]["completed_at"] = remote.time()
    elif fault == "marker":
        remote.jobs[1][0]["steps"] = []
    elif fault == "missing":
        remote.artifacts.clear()
    elif fault == "invalid":
        remote.payloads[1]["head_sha"] = "d" * 40
    elif fault == "expired":
        remote.expire(1)
    elif fault == "foreign":
        remote.artifacts[1]["workflow_run"]["head_repository_id"] = 2
    elif fault == "wrong_attempt":
        remote.payloads[1]["attempt"] = 2
    elif fault == "partial":
        remote.payloads[1]["report_count"] = 2
    elif fault == "key":
        remote.payloads[1]["key"] = "different-environment"
    else:
        remote.start()
        remote.finish(2, "failure")
        remote.merge()
    assert MergedPRTimingCollector(remote.client, POLICY).stage(7).promotion is None


def test_merge_before_upload_recovers_without_retesting(remote):
    remote.start()
    remote.pass_gate(1)
    remote.merge()
    collector = MergedPRTimingCollector(remote.client, POLICY)
    assert collector.stage(7).status == "pending"
    remote.finish(1, "success")
    assert collector.stage(7).status == "pending"
    remote.upload(1)
    promotion = collector.stage(7).promotion
    assert promotion is not None
    remote.expire(1)
    assert publish_promotion(TimingHistory(key="unit"), promotion).observations["test_a.py"].seconds == 1


@pytest.mark.parametrize("name,value", [("../secret.py", 2), ("test.py", float("nan")), ("x.py", -1)])
def test_invalid_untrusted_measurements_rejected(remote, name, value):
    remote.ready()
    remote.payloads[1]["durations"] = {name: value}
    with pytest.raises(ValueError):
        MergedPRTimingCollector(remote.client, POLICY).stage(7)


@pytest.mark.parametrize("result", ["success", "failure", "cancelled"])
def test_last_attempt_before_merge_replaces_selection_without_older_green_fallback(remote, result):
    remote.ready()
    remote.pr["merged_at"] = None
    remote.rerun(1)
    remote.pass_gate(1)
    remote.finish(1, result)
    remote.upload(1)
    remote.merge()
    decision = MergedPRTimingCollector(remote.client, POLICY).stage(7)
    if result == "success":
        assert decision.promotion is not None
        assert decision.promotion.source.run_attempt == 2
        assert decision.promotion.measurements[0].attempt == 2
    else:
        assert decision.status == "rejected"
        assert decision.promotion is None


def test_cross_merge_rerun_admission_is_uncertain_and_cannot_fall_back(remote):
    remote.ready()
    remote.rerun(1)
    with pytest.raises(ValueError, match="queued admission"):
        MergedPRTimingCollector(remote.client, POLICY).stage(7)


def test_post_merge_new_run_cannot_replace_the_sealed_source(remote):
    remote.ready()
    remote.start()
    remote.pass_gate(2)
    remote.finish(2, "success")
    remote.upload(2)
    decision = MergedPRTimingCollector(remote.client, POLICY).stage(7)
    assert decision.promotion is not None
    assert decision.promotion.source.id == 1


@pytest.mark.parametrize("second", ["valid", "missing", "overlapping"])
def test_every_expected_shard_must_supply_disjoint_complete_files(remote, second):
    remote.ready()
    policy = POLICY.model_copy(update={"shards": {"all": 1, "second": 1}})
    if second != "missing":
        remote.artifacts[2] = {**remote.artifacts[1], "id": 2,
                               "name": measurement_name("unit", "second", 1, 1)}
        remote.payloads[2] = {**remote.payloads[1], "shard": "second",
                              "durations": {"test_b.py" if second == "valid" else "test_a.py": 7}}
    decision = MergedPRTimingCollector(remote.client, policy).stage(7)
    if second == "valid":
        assert decision.promotion is not None
        state = publish_promotion(TimingHistory(key="unit"), decision.promotion)
        assert {file: observation.seconds for file, observation in state.observations.items()} == {
            "test_a.py": 1, "test_b.py": 7}
    else:
        assert decision.promotion is None
