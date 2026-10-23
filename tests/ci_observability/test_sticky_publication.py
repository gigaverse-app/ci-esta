import json
from datetime import datetime, timezone

import httpx
import pytest

from ci_esta.ci_observability.github import GitHubActionsClient
from ci_esta.ci_observability.models import StickySnapshotV1
from ci_esta.ci_observability.report import sticky_marker

MARKER = sticky_marker("CI")
AUTHOR = {"id": 42, "login": "github-actions[bot]", "type": "Bot"}


def body(run):
    snapshot = StickySnapshotV1(run_id=run, run_attempt=1, completed_gates=1,
                                observed_at=datetime(2026, 10, 23, tzinfo=timezone.utc))
    return f"report {run}\n{MARKER}\n<!-- ci-observability-snapshot {snapshot.model_dump_json()} -->", snapshot


class Comments:
    """Mutable REST boundary; the production publisher owns every publication decision."""
    def __init__(self, *comments, rival=None, fail_patch=False):
        self.comments = {comment["id"]: comment for comment in comments}
        self.rival = rival
        self.fail_patch = fail_patch

    def request(self, request):
        if request.method == "GET":
            return httpx.Response(200, json=list(self.comments.values()))
        if request.method == "POST":
            created = {"id": 10, "user": AUTHOR, **json.loads(request.content)}
            self.comments[10] = created
            if self.rival is not None:
                self.comments[self.rival["id"]] = self.rival
            return httpx.Response(201, json=created)
        identifier = int(request.url.path.rsplit("/", 1)[1])
        if request.method == "PATCH":
            if self.fail_patch:
                return httpx.Response(503)
            self.comments[identifier].update(json.loads(request.content))
            return httpx.Response(200, json=self.comments[identifier])
        assert request.method == "DELETE"
        self.comments.pop(identifier, None)
        return httpx.Response(204)

    def publish(self, run):
        client = GitHubActionsClient("example/repo", "token", transport=httpx.MockTransport(self.request))
        try:
            content, snapshot = body(run)
            return client.upsert_sticky(7, MARKER, content, snapshot)
        finally:
            client.close()


def comment(identifier, run, **changes):
    return {"id": identifier, "body": body(run)[0], "user": AUTHOR, **changes}


def test_duplicates_preserve_oldest_permalink_and_newest_report():
    api = Comments(comment(1, 100), comment(2, 300))
    assert api.publish(200) == 1
    assert list(api.comments) == [1]
    assert api.comments[1]["body"] == body(300)[0]


def test_concurrent_first_create_is_reconciled_after_publication():
    api = Comments(rival=comment(9, 300))
    assert api.publish(200) == 9
    assert list(api.comments) == [9]
    assert api.comments[9]["body"] == body(300)[0]


def test_other_keys_and_human_quotes_are_preserved():
    other = comment(2, 100, body=body(100)[0].replace(MARKER, sticky_marker("Other")))
    human = comment(3, 100, user={"id": 99, "login": "reviewer", "type": "User"})
    api = Comments(comment(1, 100), other, human)
    api.publish(200)
    assert api.comments[2] == other
    assert api.comments[3] == human
    assert api.comments[1]["body"] == body(200)[0]


def test_failed_repair_preserves_both_original_reports():
    api = Comments(comment(1, 100), comment(2, 300), fail_patch=True)
    with pytest.raises(httpx.HTTPStatusError):
        api.publish(200)
    assert len(api.comments) == 2
    assert api.comments[2]["body"] == body(300)[0]
