from datetime import timedelta

import pytest
from merged_pr_contract_driver import MergedPrEvidenceDriver, Observed

from ci_esta.ci_observability.models import GitHubPRDetailsV1, GitHubRunV1
from ci_esta.testing.merged_pr_timings import MergedPRTimingCollector, TimingPromotion, publish_promotion
from ci_esta.testing.timing_store import TimingHistory
from tests.testing.merged_pr_server import NOW, POLICY, MergedPRServer


class OpenAdmission(MergedPRTimingCollector):
    def select_source(self, pr: GitHubPRDetailsV1) -> GitHubRunV1 | None:
        # Planted fault: substitute a fictitious merge boundary for an open PR.
        if pr.merged_at is None:
            object.__setattr__(pr, "merged_at", NOW + timedelta(days=1))
            object.__setattr__(pr, "merge_commit_sha", "c" * 40)
        return super().select_source(pr)


class OlderGreen(MergedPRTimingCollector):
    def select_source(self, pr: GitHubPRDetailsV1) -> GitHubRunV1 | None:
        source = super().select_source(pr)
        if source is None:
            return None
        older = [run for run in self.client.runs_for_head(self.policy.workflow, pr.head.sha)
                 if run.conclusion == "success" and run.created_at <= source.created_at]
        return min(older, key=lambda run: run.created_at, default=source)


class CollectorDriver(MergedPrEvidenceDriver):
    def __init__(self, mutant: str | None):
        self.remote = MergedPRServer()
        collector = {"open-admission": OpenAdmission, "older-green": OlderGreen}.get(mutant, MergedPRTimingCollector)
        self.collector = collector(self.remote.client, POLICY)
        self.staged: TimingPromotion | None = None
        self.history = TimingHistory(key="unit")
        self.drop_publication = mutant == "dropped-publication"

    def init(self) -> None:
        pass

    def push(self) -> None:
        self.remote.push()

    def start(self) -> None:
        self.remote.start()

    def pass_gate(self, r: int) -> None:
        self.remote.pass_gate(r)

    def finish(self, r: int, value: str) -> None:
        self.remote.finish(r, value)

    def upload(self, r: int, value: str) -> None:
        self.remote.upload(r, value)

    def expire(self, r: int) -> None:
        self.remote.expire(r)

    def close_pr(self) -> None:
        self.remote.pr["state"] = "closed"

    def merge(self) -> None:
        self.remote.merge()

    def stage(self) -> None:
        decision = self.collector.stage(7)
        if decision.promotion is not None:
            self.staged = decision.promotion

    def publish(self) -> None:
        if self.staged is not None and not self.drop_publication:
            self.history = publish_promotion(self.history, self.staged)

    def crash(self) -> None:
        self.staged = None

    def inspect(self) -> None:
        pass

    def observe(self) -> Observed:
        return {"staged": self.staged.source.id if self.staged is not None else 0,
                "published": {int(value.seconds) for value in self.history.observations.values()}}

    def close(self) -> None:
        self.remote.close()


@pytest.fixture
def merged_pr_driver():
    return lambda context: CollectorDriver(context.mutant)
