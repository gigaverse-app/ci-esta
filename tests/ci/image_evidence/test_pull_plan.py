"""Resolve immutable pull inputs before acquiring a Docker daemon or a pod."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ci_esta.image_evidence.plan import prepare_pull_plan, prepare_sequence

DIGEST = "sha256:" + "a" * 64
REPOSITORY = "123.dkr.ecr.us-east-1.amazonaws.com/probe"


def evidence(tmp_path: Path, scenarios: list[str]) -> Path:
    (tmp_path / "inputs.json").write_text(
        json.dumps(
            {
                "repository": REPOSITORY,
                "prefix": "probe-run",
                "dind": "docker@" + DIGEST,
                "pull_sequence": scenarios,
            }
        )
    )
    rows = [
        {"arm": arm, "scenario": scenario, "sample": 0, "digest": DIGEST}
        for arm in ("baseline", "candidate")
        for scenario in scenarios
    ]
    (tmp_path / "results.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    return tmp_path


def test_named_os_sequence_is_frozen_without_relabeling(tmp_path: Path) -> None:
    root = evidence(tmp_path, ["cold", "source", "os"])
    plan = prepare_pull_plan(root)
    (root / "results.jsonl").unlink()
    assert plan.sequence == ("cold", "source", "os")
    assert plan.images["baseline"]["os"] == REPOSITORY + "@" + DIGEST
    assert plan.samples == 3


def test_legacy_sequence_defaults_remain_compatible(tmp_path: Path) -> None:
    root = evidence(tmp_path, ["cold", "source", "bump"])
    path = root / "inputs.json"
    inputs = json.loads(path.read_text())
    del inputs["pull_sequence"]
    path.write_text(json.dumps(inputs))
    assert prepare_pull_plan(root).sequence == ("cold", "source", "bump")


@pytest.mark.parametrize("scenarios", [["cold", "cold"], [], ["../os"], ["os with spaces"]])
def test_invalid_sequences_fail_before_resource_acquisition(tmp_path: Path, scenarios: list[str]) -> None:
    with pytest.raises((ValueError, ValidationError)):
        prepare_pull_plan(evidence(tmp_path, scenarios))


@pytest.mark.parametrize("fault", ["missing", "duplicate", "tag"])
def test_missing_ambiguous_or_mutable_image_identity_rejects(tmp_path: Path, fault: str) -> None:
    root = evidence(tmp_path, ["cold", "os"])
    path = root / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows.append(rows[0])
    else:
        rows[0]["digest"] = "latest"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError):
        prepare_pull_plan(root)


def test_named_sequence_preserves_original_rows_and_rejects_missing_before_writing(tmp_path: Path) -> None:
    root = evidence(tmp_path, ["cold", "source", "bump", "os"])
    before = (root / "results.jsonl").read_bytes()
    output = prepare_sequence(root, "os-refresh", ("cold", "source", "os"))
    assert (output / "results.jsonl").read_bytes() == before
    assert prepare_pull_plan(output).sequence == ("cold", "source", "os")
    assert prepare_pull_plan(output).prefix == "probe-run-os-refresh"
    with pytest.raises(ValueError, match="exactly one"):
        prepare_sequence(root, "missing", ("cold", "absent"))
    assert not (root / "missing").exists()
