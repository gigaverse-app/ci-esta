"""Execute the service lifecycle, replacing only the Docker daemon boundary."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def service_env(tmp_path):
    docker = tmp_path / "docker"
    docker.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if args[0] == 'run' and os.environ.get('FAIL_RUN'):
    sys.exit(1)
if args[0] == 'inspect':
    print(os.environ.get('HEALTH', 'healthy') if 'Health' in args[2] else os.environ.get('STATE', 'running'))
if args[:2] == ['container', 'inspect'] and os.environ.get('ABSENT'):
    sys.exit(1)
''')
    docker.chmod(0o755)
    return dict(os.environ, PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}", CALLS=str(tmp_path / "calls"),
                RUNNER_TEMP=str(tmp_path), SERVICE_NAME="test-service", SERVICE_IMAGE="redis:7-alpine",
                SERVICE_HEALTH_COMMAND="redis-cli ping", SERVICE_PORTS="6379:6379\n6380:6380",
                SERVICE_TIMEOUT="1")


def run(env, phase):
    return subprocess.run(["bash", str(ROOT / "actions/service-container/service.sh")],
                          env=dict(env, SERVICE_PHASE=phase), text=True, capture_output=True)


def calls(env):
    return [json.loads(line) for line in Path(env["CALLS"]).read_text().splitlines()]


def test_health_required_before_return_and_cleanup(service_env):
    assert run(service_env, "start").returncode == 0
    assert calls(service_env)[0] == ["run", "-d", "--name", "test-service", "-p", "6379:6379",
                                   "-p", "6380:6380", "--health-cmd", "redis-cli ping", "--health-interval",
                                   "1s", "--health-timeout", "1s", "--health-retries", "1", "redis:7-alpine"]
    assert calls(service_env)[-1][0] == "inspect"
    assert run(service_env, "stop").returncode == 0
    assert calls(service_env)[-1] == ["rm", "-f", "test-service"]


@pytest.mark.parametrize("override", [{"FAIL_RUN": "1"}, {"HEALTH": "starting"},
                                     {"HEALTH": "unhealthy", "STATE": "exited"}])
def test_missing_or_unhealthy_service_never_permits_tests(service_env, override):
    assert run(dict(service_env, **override), "start").returncode != 0


def test_cleanup_before_start_is_safe(service_env):
    assert run(dict(service_env, ABSENT="1"), "stop").returncode == 0
    assert not any(call[0] == "rm" for call in calls(service_env))


def test_prefetch_never_starts_a_container(service_env):
    assert run(service_env, "warm").returncode == 0
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if Path(service_env["CALLS"]).exists() and calls(service_env):
            break
        time.sleep(0.01)
    assert calls(service_env) == [["pull", "redis:7-alpine"]]
