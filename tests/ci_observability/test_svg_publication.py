import httpx
import pytest

from ci_esta.ci_observability.svg_publication import publish_headlines
from tests.ci_observability.test_headlines import report_with_work, work


@pytest.mark.parametrize("private", [True, False])
def test_assets_are_bound_to_source_repository_and_private_probe_precedes_data(private):
    uploads, probes = [], []
    def respond(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"id": 123, "full_name": "example/bun", "private": private})
        if request.method == "GET":
            assert "authorization" not in request.headers
            probes.append(str(request.url))
            return httpx.Response(404)
        assert request.url.host == "uploads.github.com"
        assert request.url.params["repository_id"] == "123"
        if private and uploads:
            assert probes
        uploads.append(request.content)
        return httpx.Response(201, json={"url": f"https://github.com/user-attachments/assets/{len(uploads):032x}"})
    report = report_with_work(work(mode="full", files=["a.test.ts"]))
    result = publish_headlines(report, "marker", repository="example/bun", token="ghp_test",
                               transport=httpx.MockTransport(respond))
    assert "img.shields.io" not in result
    assert "https://github.com/user-attachments/assets/" in result
    assert len(probes) == int(private)
    if private:
        assert b"10 / 10" not in uploads[0]
    assert b"10 / 10" in b"".join(uploads)


@pytest.mark.parametrize("failure", ["anonymous_public", "unknown_visibility", "wrong_repository", "denied"])
def test_uncertain_privacy_keeps_text_and_never_uploads_metrics(failure):
    uploads = []
    def respond(request):
        if request.url.host == "api.github.com":
            body = {"id": 123, "full_name": "elsewhere/public" if failure == "wrong_repository" else "example/bun"}
            if failure != "unknown_visibility":
                body["private"] = True
            return httpx.Response(200, json=body)
        if request.method == "GET":
            return httpx.Response(200, content=b"public image")
        uploads.append(request.content)
        return httpx.Response(403) if failure == "denied" else httpx.Response(201, json={
            "url": "https://github.com/user-attachments/assets/00000000-0000-0000-0000-000000000000"})
    result = publish_headlines(report_with_work(work()), "marker", repository="example/bun", token="ghp_test",
                               transport=httpx.MockTransport(respond))
    assert len(uploads) <= 1
    assert all(b"ci-esta privacy probe" in data for data in uploads)
    assert "<details>" in result
    assert "img.shields.io" not in result
    assert "selected: unavailable" in result


def test_source_and_destination_mismatch_cannot_upload_or_publish():
    with pytest.raises(ValueError, match="repository"):
        publish_headlines(report_with_work(work()), "marker", repository="other/public", token="ghp_test")


def test_installation_token_falls_back_without_requests():
    def reject(request):
        pytest.fail("installation tokens cannot upload attachments")
    result = publish_headlines(report_with_work(work()), "marker", repository="example/bun", token="ghs_test",
                               transport=httpx.MockTransport(reject))
    assert "img.shields.io" not in result
    assert "<details>" in result
