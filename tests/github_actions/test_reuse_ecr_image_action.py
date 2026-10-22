import os
import subprocess
from pathlib import Path

import pytest
import yaml

ACTION_DIRECTORY = Path(".github/actions/reuse-ecr-image")
ACTION_PATH = ACTION_DIRECTORY / "action.yml"
SCRIPT_PATH = ACTION_DIRECTORY / "reuse_ecr_image.sh"
SOURCE_IMAGE = "249422357769.dkr.ecr.us-east-1.amazonaws.com/dev-app:ci-tree-source"
TARGET_IMAGE = "249422357769.dkr.ecr.us-east-1.amazonaws.com/dev-app:deploy-target"
OTHER_REPOSITORY_IMAGE = "249422357769.dkr.ecr.us-east-1.amazonaws.com/other-app:deploy-target"
SOURCE_DIGEST = "sha256:source"
OTHER_DIGEST = "sha256:other"


def _write_fake_aws(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aws = fake_bin / "aws"
    fake_aws.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$AWS_CALLS"

operation="$1 $2"
if [ "$operation" = "ecr batch-get-image" ]; then
  tag=""
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--image-ids" ]; then
      tag="${2#imageTag=}"
      break
    fi
    shift
  done

  if [ "$tag" = "ci-tree-source" ]; then
    if [ "$AWS_SCENARIO" = "source-lookup-failure" ]; then
      exit 42
    fi
    if [ "$AWS_SCENARIO" = "source-response-invalid" ]; then
      printf '%s\n' 'not-json'
      exit 0
    fi
    if [ "$AWS_SCENARIO" = "source-missing" ]; then
      printf '%s\n' '{"images":[]}'
      exit 0
    fi
    printf '%s\n' '{"images":[{"imageId":{"imageDigest":"sha256:source"},"imageManifest":"{\\"schemaVersion\\":2}","imageManifestMediaType":"application/vnd.oci.image.manifest.v1+json"}]}'
    exit 0
  fi

  if [ "$AWS_SCENARIO" = "target-lookup-failure" ]; then
    exit 43
  fi
  if [ "$AWS_SCENARIO" = "target-response-invalid" ]; then
    printf '%s\n' 'not-json'
    exit 0
  fi
  if [ "$AWS_SCENARIO" = "target-same" ]; then
    printf '%s\n' '{"images":[{"imageId":{"imageDigest":"sha256:source"}}]}'
    exit 0
  fi
  if [ "$AWS_SCENARIO" = "target-conflict" ]; then
    printf '%s\n' '{"images":[{"imageId":{"imageDigest":"sha256:other"}}]}'
    exit 0
  fi
  printf '%s\n' '{"images":[]}'
  exit 0
fi

if [ "$operation" = "ecr put-image" ]; then
  if [ "$AWS_SCENARIO" = "promotion-failure" ]; then
    exit 44
  fi
  if [ "$AWS_SCENARIO" = "promotion-digest-mismatch" ]; then
    printf 'sha256:other\n'
    exit 0
  fi
  printf 'sha256:source\n'
  exit 0
fi

exit 45
""",
    )
    fake_aws.chmod(0o755)
    return fake_bin


def _run_action(
    tmp_path: Path,
    *,
    scenario: str,
    source_image: str = SOURCE_IMAGE,
    target_image: str = TARGET_IMAGE,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], list[str]]:
    fake_bin = _write_fake_aws(tmp_path)
    output_file = tmp_path / "github-output"
    calls_file = tmp_path / "aws-calls"
    result = subprocess.run(
        [SCRIPT_PATH],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "SOURCE_IMAGE_TAG": source_image,
            "TARGET_IMAGE_TAG": target_image,
            "AWS_SCENARIO": scenario,
            "AWS_CALLS": str(calls_file),
            "GITHUB_OUTPUT": str(output_file),
        },
        capture_output=True,
        text=True,
    )
    outputs: dict[str, str] = {}
    for line in output_file.read_text().splitlines():
        name, separator, value = line.partition("=")
        assert separator, f"malformed GitHub output: {line}"
        outputs[name] = value
    calls = calls_file.read_text().splitlines() if calls_file.exists() else []
    return result, outputs, calls


def test_action_metadata_exposes_the_fail_safe_reuse_contract() -> None:
    action = yaml.safe_load(ACTION_PATH.read_text())

    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["source-image"]["required"] is True
    assert action["inputs"]["target-image"]["required"] is True
    assert set(action["outputs"]) == {"reused", "reason", "digest", "source-digest"}
    assert "${{ github.action_path }}/reuse_ecr_image.sh" in ACTION_PATH.read_text()


@pytest.mark.parametrize(
    ("scenario", "expected_reason"),
    [
        ("source-lookup-failure", "source-lookup-failed"),
        ("source-response-invalid", "source-response-invalid"),
        ("source-missing", "source-missing"),
        ("target-lookup-failure", "target-lookup-failed"),
        ("target-response-invalid", "target-response-invalid"),
        ("target-conflict", "target-conflict"),
        ("promotion-failure", "promotion-failed"),
        ("promotion-digest-mismatch", "digest-mismatch"),
    ],
)
def test_registry_or_promotion_failures_return_a_build_fallback(
    tmp_path: Path,
    scenario: str,
    expected_reason: str,
) -> None:
    result, outputs, _ = _run_action(tmp_path, scenario=scenario)

    assert result.returncode == 0
    assert outputs["reused"] == "false"
    assert outputs["reason"] == expected_reason
    assert outputs["digest"] == ""


@pytest.mark.parametrize(
    ("source_image", "target_image", "expected_reason"),
    [
        ("not-an-ecr-image", TARGET_IMAGE, "invalid-source-ref"),
        (SOURCE_IMAGE, "not-an-ecr-image", "invalid-target-ref"),
        (SOURCE_IMAGE, OTHER_REPOSITORY_IMAGE, "repository-mismatch"),
    ],
)
def test_invalid_or_cross_repository_refs_never_call_aws(
    tmp_path: Path,
    source_image: str,
    target_image: str,
    expected_reason: str,
) -> None:
    result, outputs, calls = _run_action(
        tmp_path,
        scenario="promote-success",
        source_image=source_image,
        target_image=target_image,
    )

    assert result.returncode == 0
    assert outputs["reused"] == "false"
    assert outputs["reason"] == expected_reason
    assert calls == []


@pytest.mark.parametrize(
    ("scenario", "expected_reason", "expected_put_calls"),
    [
        ("target-same", "target-exists", 0),
        ("promote-success", "promoted", 1),
    ],
)
def test_only_digest_identical_images_are_reused(
    tmp_path: Path,
    scenario: str,
    expected_reason: str,
    expected_put_calls: int,
) -> None:
    result, outputs, calls = _run_action(tmp_path, scenario=scenario)

    assert result.returncode == 0
    assert outputs == {
        "reused": "true",
        "reason": expected_reason,
        "digest": SOURCE_DIGEST,
        "source-digest": SOURCE_DIGEST,
    }
    assert len([call for call in calls if call.startswith("ecr put-image")]) == expected_put_calls


def test_target_conflict_does_not_overwrite_the_existing_tag(tmp_path: Path) -> None:
    _, outputs, calls = _run_action(tmp_path, scenario="target-conflict")

    assert outputs["digest"] == ""
    assert outputs["source-digest"] == SOURCE_DIGEST
    assert not any(call.startswith("ecr put-image") for call in calls)
    assert OTHER_DIGEST not in outputs.values()
