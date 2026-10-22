"""Pin gigaverse-ai's enrichment profile, ported with its code.

The deploy tests came from gigaverse-ai's
``tests/test_ci/test_shared_ci_observability.py``; the workflow-class tests
pin the paths its four workflows exercise. The dumped JSON and signal
strings are the wire contract its dashboards and sticky already consume.
"""

import json
from pathlib import Path

from ci_esta.ci_observability.enrichment.ai import (
    WorkflowClass,
    build_deploy_extension,
    build_repository_signals,
    build_workflow_extension,
)

PYTEST_SHARD_COUNT = 3
PYTEST_WALL_TIME = "1m 34s"
PYTEST_TOTAL_TIME = "4m 21s"


def test_deploy_enrichment_parses_typed_build_snapshots(tmp_path: Path) -> None:
    service_dir = tmp_path / "ci-observability-build-actions_service"
    service_dir.mkdir()
    (service_dir / "metrics.prom").write_text(
        "\n".join(
            (
                'docker_build_duration_seconds{service="actions_service",env="dev"} 34',
                'docker_build_cache_hit_ratio{service="actions_service",env="dev"} 0.75',
                'docker_build_cached_steps_total{service="actions_service",env="dev"} 15',
                'docker_build_steps_total{service="actions_service",env="dev"} 20',
                'docker_build_image_size_bytes{service="actions_service",env="dev"} 1234',
                'uv_sync_duration_seconds{stage="main",service="actions_service",env="dev"} 4',
                'uv_cache_delta_bytes{stage="main",service="actions_service",env="dev"} 12',
                'uv_cached{stage="main",service="actions_service",env="dev"} 1',
            )
        )
        + "\n"
    )

    extension = build_deploy_extension(tmp_path)
    dumped = extension.model_dump(mode="json")

    assert dumped["ai"]["contract_version"] == "CI-OBS-AI-ENRICH-v1"
    assert dumped["ai"]["workflow_class"] == "deploy"
    assert dumped["ai"]["builds"] == [
        {
            "service": "actions_service",
            "environment": "dev",
            "build_seconds": 34.0,
            "cache_hit_ratio": 0.75,
            "cached_steps": 15,
            "total_steps": 20,
            "image_size_bytes": 1234,
            "uv_stages": [
                {
                    "stage": "main",
                    "duration_seconds": 4.0,
                    "cache_delta_bytes": 12,
                    "cached": True,
                }
            ],
        }
    ]
    signals = build_repository_signals(extension)
    assert [signal.model_dump() for signal in signals] == [
        {
            "key": "docker_builds",
            "label": "Docker builds",
            "value": "1 service image(s) observed",
        },
        {
            "key": "slowest_docker_build",
            "label": "Slowest Docker build",
            "value": "actions_service · 34s",
        },
        {
            "key": "mean_docker_cache_hit",
            "label": "Mean Docker cache hit",
            "value": "75.0%",
        },
        {
            "key": "total_image_size",
            "label": "Total image size",
            "value": "0.0 MiB",
        },
    ]
    json.dumps(dumped)


def test_missing_build_snapshots_are_explicitly_unavailable(tmp_path: Path) -> None:
    extension = build_deploy_extension(tmp_path)

    assert extension.ai.builds == []
    assert extension.ai.unavailable == ["no build metric artifacts were available"]


def test_python_tests_extension_carries_the_pytest_snapshot() -> None:
    extension = build_workflow_extension(
        WorkflowClass.PYTHON_TESTS,
        pytest_shard_count=PYTEST_SHARD_COUNT,
        pytest_wall_time=PYTEST_WALL_TIME,
        pytest_total_time=PYTEST_TOTAL_TIME,
    )

    assert extension.ai.pytest is not None
    assert extension.ai.pytest.shard_count == PYTEST_SHARD_COUNT
    assert extension.ai.pytest.wall_seconds == 94.0
    assert extension.ai.pytest.total_test_seconds == 261.0
    assert extension.ai.unavailable == []
    signals = build_repository_signals(extension)
    assert [signal.model_dump() for signal in signals] == [
        {
            "key": "pytest_parallelism",
            "label": "pytest",
            "value": "3 shards · 1m 34s wall · 4m 21s summed test time",
        }
    ]


def test_python_tests_without_shard_count_is_explicitly_unavailable() -> None:
    extension = build_workflow_extension(
        WorkflowClass.PYTHON_TESTS,
        pytest_shard_count=None,
        pytest_wall_time="",
        pytest_total_time="",
    )

    assert extension.ai.pytest is None
    assert extension.ai.unavailable == ["pytest shard count was unavailable"]


def test_non_pytest_workflow_classes_carry_no_snapshot_or_signals() -> None:
    for workflow_class in (WorkflowClass.TYPE_CHECK, WorkflowClass.NON_DEFAULT_TESTS):
        extension = build_workflow_extension(
            workflow_class,
            pytest_shard_count=None,
            pytest_wall_time="",
            pytest_total_time="",
        )

        assert extension.ai.workflow_class == workflow_class
        assert extension.ai.pytest is None
        assert extension.ai.unavailable == []
        assert build_repository_signals(extension) == []
