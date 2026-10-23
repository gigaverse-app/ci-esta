import base64
import importlib.util
import json
import runpy
import urllib.request
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
import yaml

ACTION_DIRECTORY = Path("actions/publish-prometheus-snapshot")
ACTION_PATH = ACTION_DIRECTORY / "action.yml"
SCRIPT_PATH = ACTION_DIRECTORY / "publish.py"
PUSHGATEWAY_URL = "https://pushgateway.example.test/base/"
JOB_NAME = "docker build"
REPOSITORY = "gigaverse-app/gigaverse-ai"
GROUPING_LABELS = {"env": "dev", "service": "edge/service"}
METRICS_BODY = 'docker_build_duration_seconds{service="edge_service"} 24\n'
USERNAME = "ci-user"
PASSWORD = "password:with-colon"
TIMEOUT_SECONDS = 17
EXPECTED_TARGET = (
    "https://pushgateway.example.test/base/metrics/job/docker%20build/"
    "repository@base64/Z2lnYXZlcnNlLWFwcC9naWdhdmVyc2UtYWk/env/dev/"
    "service@base64/ZWRnZS9zZXJ2aWNl"
)


def _load_publisher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publish_prometheus_snapshot", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_required_environment(
    monkeypatch: pytest.MonkeyPatch,
    metrics_file: Path,
    *,
    failure_mode: str,
) -> None:
    values = {
        "INPUT_METRICS_FILE": str(metrics_file),
        "INPUT_PUSHGATEWAY_URL": PUSHGATEWAY_URL,
        "INPUT_JOB": JOB_NAME,
        "INPUT_GROUPING_LABELS": json.dumps(GROUPING_LABELS),
        "INPUT_USERNAME": USERNAME,
        "INPUT_PASSWORD": PASSWORD,
        "INPUT_FAILURE_MODE": failure_mode,
        "INPUT_TIMEOUT_SECONDS": str(TIMEOUT_SECONDS),
        "GITHUB_REPOSITORY": REPOSITORY,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_action_runs_its_own_script_without_ephemeral_group_cleanup() -> None:
    action = ACTION_PATH.read_text()
    script = SCRIPT_PATH.read_text()

    assert "${{ github.action_path }}/publish.py" in action
    assert "metrics-file:" in action
    assert "grouping-labels:" in action
    assert "failure-mode:" in action
    assert "sleep" not in action
    assert "DELETE" not in action
    assert 'method="PUT"' in script


def test_action_metadata_exposes_safe_defaults() -> None:
    action = yaml.safe_load(ACTION_PATH.read_text())

    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["failure-mode"]["default"] == "warn"
    assert action["inputs"]["grouping-labels"]["default"] == "{}"
    assert action["inputs"]["metrics-file"]["required"] is True
    assert action["inputs"]["pushgateway-url"]["required"] is True


def test_build_target_is_repository_isolated_and_url_encoded() -> None:
    publisher = _load_publisher()

    target = publisher.build_target(
        PUSHGATEWAY_URL,
        JOB_NAME,
        REPOSITORY,
        GROUPING_LABELS,
    )

    assert target == EXPECTED_TARGET


def test_build_target_base64_encodes_job_names_containing_slashes() -> None:
    publisher = _load_publisher()

    target = publisher.build_target(
        PUSHGATEWAY_URL,
        "ci/build",
        REPOSITORY,
        {},
    )

    assert "/job@base64/Y2kvYnVpbGQ/" in target


def test_build_target_rejects_unbounded_or_reserved_grouping_dimensions() -> None:
    publisher = _load_publisher()

    with pytest.raises(ValueError, match="reserved"):
        publisher.build_target(
            PUSHGATEWAY_URL,
            JOB_NAME,
            REPOSITORY,
            {"run_id": "29980851153"},
        )

    with pytest.raises(ValueError, match="valid Prometheus label"):
        publisher.build_target(
            PUSHGATEWAY_URL,
            JOB_NAME,
            REPOSITORY,
            {"invalid-label": "value"},
        )


@pytest.mark.parametrize(
    "raw_labels",
    [
        "[]",
        '{"service": 42}',
        '{"service": ""}',
    ],
)
def test_parse_grouping_labels_requires_non_empty_string_dimensions(raw_labels: str) -> None:
    publisher = _load_publisher()

    with pytest.raises(ValueError):
        publisher.parse_grouping_labels(raw_labels)


@pytest.mark.parametrize(
    "raw_labels",
    [
        '{"invalid-label": "value"}',
        '{"run_id": "29980851153"}',
    ],
)
def test_parse_grouping_labels_rejects_invalid_or_unbounded_names(raw_labels: str) -> None:
    publisher = _load_publisher()

    with pytest.raises(ValueError):
        publisher.parse_grouping_labels(raw_labels)


@pytest.mark.parametrize(
    ("pushgateway_url", "job", "repository", "message"),
    [
        ("", JOB_NAME, REPOSITORY, "pushgateway-url"),
        (PUSHGATEWAY_URL, "", REPOSITORY, "job"),
        (PUSHGATEWAY_URL, JOB_NAME, "", "GITHUB_REPOSITORY"),
    ],
)
def test_build_target_requires_identity_dimensions(
    pushgateway_url: str,
    job: str,
    repository: str,
    message: str,
) -> None:
    publisher = _load_publisher()

    with pytest.raises(ValueError, match=message):
        publisher.build_target(pushgateway_url, job, repository, {})


def test_publish_snapshot_uses_put_with_optional_basic_auth() -> None:
    publisher = _load_publisher()
    response = MagicMock()
    response.status = 202
    response.__enter__.return_value = response
    authorization = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()

    with patch.object(urllib.request, "urlopen", return_value=response) as urlopen:
        status = publisher.publish_snapshot(
            EXPECTED_TARGET,
            METRICS_BODY,
            username=USERNAME,
            password=PASSWORD,
            timeout_seconds=TIMEOUT_SECONDS,
        )

    assert status == 202
    request = urlopen.call_args.args[0]
    assert isinstance(request, urllib.request.Request)
    assert request.full_url == EXPECTED_TARGET
    assert request.get_method() == "PUT"
    assert request.data == METRICS_BODY.encode()
    assert request.get_header("Content-type") == "text/plain; version=0.0.4"
    assert request.get_header("Authorization") == f"Basic {authorization}"
    assert urlopen.call_args.kwargs == {"timeout": TIMEOUT_SECONDS}


def test_publish_snapshot_allows_anonymous_gateway() -> None:
    publisher = _load_publisher()
    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response

    with patch.object(urllib.request, "urlopen", return_value=response) as urlopen:
        status = publisher.publish_snapshot(
            EXPECTED_TARGET,
            METRICS_BODY,
            username="",
            password="",
            timeout_seconds=TIMEOUT_SECONDS,
        )

    assert status == 200
    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") is None


def test_publish_snapshot_requires_complete_basic_auth_pair() -> None:
    publisher = _load_publisher()

    with pytest.raises(ValueError, match="both be set"):
        publisher.publish_snapshot(
            EXPECTED_TARGET,
            METRICS_BODY,
            username=USERNAME,
            password="",
            timeout_seconds=TIMEOUT_SECONDS,
        )


def test_main_publishes_the_file_using_action_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _load_publisher()
    metrics_file = tmp_path / "metrics.prom"
    metrics_file.write_text(METRICS_BODY)
    _set_required_environment(monkeypatch, metrics_file, failure_mode="fail")

    with patch.object(publisher, "publish_snapshot", return_value=202) as publish:
        exit_code = publisher.main()

    assert exit_code == 0
    assert publish.call_args.args == (EXPECTED_TARGET, METRICS_BODY)
    assert publish.call_args.kwargs == {
        "username": USERNAME,
        "password": PASSWORD,
        "timeout_seconds": TIMEOUT_SECONDS,
    }


def test_main_rejects_invalid_failure_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = _load_publisher()
    monkeypatch.setenv("INPUT_FAILURE_MODE", "ignore")

    assert publisher.main() == 1


@pytest.mark.parametrize(
    ("prepare_file", "expected_message"),
    [
        (False, "INPUT_METRICS_FILE is required"),
        (True, "is empty"),
    ],
)
def test_main_reports_missing_or_empty_metrics_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    prepare_file: bool,
    expected_message: str,
) -> None:
    publisher = _load_publisher()
    monkeypatch.setenv("INPUT_FAILURE_MODE", "fail")
    if prepare_file:
        metrics_file = tmp_path / "empty.prom"
        metrics_file.write_text("")
        monkeypatch.setenv("INPUT_METRICS_FILE", str(metrics_file))
    else:
        monkeypatch.delenv("INPUT_METRICS_FILE", raising=False)

    assert publisher.main() == 1
    assert expected_message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("failure_mode", "expected_exit_code"),
    [("warn", 0), ("fail", 1)],
)
def test_main_applies_explicit_failure_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_mode: str,
    expected_exit_code: int,
) -> None:
    publisher = _load_publisher()
    metrics_file = tmp_path / "metrics.prom"
    metrics_file.write_text(METRICS_BODY)
    _set_required_environment(
        monkeypatch,
        metrics_file,
        failure_mode=failure_mode,
    )

    with patch.object(
        publisher,
        "publish_snapshot",
        side_effect=OSError("gateway unavailable"),
    ):
        exit_code = publisher.main()

    assert exit_code == expected_exit_code
    assert "gateway unavailable" in capsys.readouterr().err


def test_script_entrypoint_exits_with_main_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INPUT_FAILURE_MODE", "invalid")

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exc_info.value.code == 1
