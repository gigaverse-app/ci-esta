"""Execution-input projection and complete-range evidence, through real Git/CLI."""

import copy
import json
import subprocess
import sys

import pytest
import yaml

from ci_esta.workflow_inputs import git, selection_proof, workflow_inputs


@pytest.mark.parametrize(
    "expression", ["${{ needs.prepare.outputs.x }}", "${{ needs ['prepare'].outputs.x }}", "${{ toJSON(needs) }}"]
)
def test_execution_data_tracks_transitive_dependencies_but_not_admission(expression):
    before = {
        "env": {"LANG": "C"},
        "jobs": {
            "web": {"needs": "prepare", "steps": [{"run": expression}]},
            "prepare": {"needs": "image", "env": {"IMAGE": "${{ needs.image.outputs.tag }}"}},
            "image": {"runs-on": "linux"},
            "python": {"runs-on": "linux"},
        },
    }
    after = copy.deepcopy(before)
    after["jobs"]["python"]["runs-on"] = "windows"
    assert workflow_inputs(before, "web") == workflow_inputs(after, "web")
    after["jobs"]["image"]["runs-on"] = "windows"
    assert workflow_inputs(before, "web") != workflow_inputs(after, "web")
    before["jobs"]["web"]["steps"] = [{"if": expression, "run": "echo fixed-inputs"}]
    after["jobs"]["web"] = before["jobs"]["web"]
    assert workflow_inputs(before, "web") == workflow_inputs(after, "web")
    after["env"] = {"LANG": "other"}
    assert workflow_inputs(before, "web") != workflow_inputs(after, "web")


@pytest.mark.parametrize(
    "update",
    [
        {"base": "incremental"},
        {"head": "stale"},
        {"mode": "full"},
        {"selected": None},
        {"selected": [False]},
        {"selected": "test.py"},
    ],
)
def test_unverifiable_selection_cannot_discharge_any_trigger(update):
    report = {"base": "base", "head": "head", "mode": "scoped", "selected": [], "dependencies_unchanged": True}
    assert selection_proof(report | update, base_tree="base", head_tree="head", tests={"integration": ["test.py"]}) == {
        "dependencies-unchanged": False,
        "integration-unaffected": False,
    }


def test_exact_test_groups_and_literal_dependency_proof():
    report = {
        "base": "base",
        "head": "head",
        "mode": "scoped",
        "selected": ["tests/one.py"],
        "dependencies_unchanged": "true",
    }
    assert selection_proof(
        report,
        base_tree="base",
        head_tree="head",
        tests={
            "one": ["tests/one.py", "tests/two.py"],
            "other": ["tests/other.py"],
            "empty": [],
        },
    ) == {"dependencies-unchanged": False, "one-unaffected": False, "other-unaffected": True, "empty-unaffected": False}


def test_cli_compares_real_git_and_refuses_incremental_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git("init", "-q")
    git("config", "user.name", "Tests")
    git("config", "user.email", "test@example.invalid")
    workflow = {"jobs": {"browser": {"runs-on": "linux"}, "python": {"runs-on": "linux"}}}
    source = tmp_path / "ci.yml"
    source.write_text(yaml.safe_dump(workflow))
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    workflow["jobs"]["browser"]["runs-on"] = "macos"
    source.write_text(yaml.safe_dump(workflow))
    git("add", ".")
    git("commit", "-qm", "change browser only")
    report = {
        "base": git("rev-parse", f"{base}^{{tree}}"),
        "head": git("rev-parse", "HEAD^{tree}"),
        "mode": "none",
        "selected": [],
        "dependencies_unchanged": True,
    }
    command = [
        sys.executable,
        "-m",
        "ci_esta.workflow_inputs",
        "--base",
        base,
        "--workflow",
        "ci.yml",
        "--lanes",
        '{"frontend":"browser","backend":"python"}',
        "--tests",
        '{"api":["tests/api.py"]}',
    ]

    def run():
        (tmp_path / "test-impact-report.json").write_text(json.dumps(report))
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return dict(line.split("=", 1) for line in result.stdout.splitlines())

    assert run() == {"frontend": "true", "backend": "false", "dependencies-unchanged": "true", "api-unaffected": "true"}
    report["base"] = report["head"]
    assert run() == {
        "frontend": "true",
        "backend": "false",
        "dependencies-unchanged": "false",
        "api-unaffected": "false",
    }
    command[command.index(base)] = "missing-ref"
    assert run() == {
        "frontend": "true",
        "backend": "true",
        "dependencies-unchanged": "false",
        "api-unaffected": "false",
    }
