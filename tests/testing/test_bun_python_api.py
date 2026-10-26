"""Native Python consumers use the same Git admission and execution contracts."""

import json
import shutil
import subprocess

import pytest

from ci_esta.testing.bun.execution import run_bun_tests
from ci_esta.testing.bun.models import RunRequest, SelectionRequest
from ci_esta.testing.bun.selection import plan_affected_tests, read_test_selection


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "test@example.test")
    git("config", "user.name", "Test")
    (root / "src").mkdir()
    (root / "src/value.ts").write_text("export const value = 1;")
    (root / "src/value.test.ts").write_text(
        "import {test,expect} from 'bun:test'; import {value} from './value'; test('value',()=>expect(value).toBe(1));")
    (root / "policy.json").write_text(json.dumps({
        "schema_version": "ci-esta/bun-policy/v1", "scopedRoots": ["src/"], "runtimeRoots": ["src/"],
        "sourceExtensions": [".ts"], "unaffectedPaths": ["README.md"], "unaffectedRoots": ["docs/"],
        "reviewedReaders": {},
    }))
    git("add", ".")
    git("commit", "-qm", "initial")
    return root, git, git("rev-parse", "HEAD")


@pytest.mark.parametrize("path,content,mode", [
    ("README.md", "docs", "none"),
    ("src/value.ts", "export const value = 2;", "scoped"),
    ("package.json", "{}", "full"),
])
def test_python_api_selects_from_real_git_inputs(repository, tmp_path, path, content, mode):
    root, git, base = repository
    (root / path).write_text(content)
    git("add", ".")
    git("commit", "-qm", "change")
    request = SelectionRequest(cwd=root, base=base, policy_file="policy.json")
    plan = plan_affected_tests(request)
    assert plan.mode == mode
    assert not plan.fallback
    saved = tmp_path / "plan.json"
    saved.write_text(plan.model_dump_json(by_alias=True))
    assert read_test_selection(saved, request).mode == mode
    assert plan_affected_tests(request.model_copy(update={"full": True})).mode == "full"
    if mode != "full":
        (root / "src/value.ts").write_text("export const uncommitted = true;")
        assert read_test_selection(saved, request).fallback


@pytest.mark.skipif(shutil.which("bun") is None, reason="native Bun execution runs in the required Runtime contracts job")
def test_python_executor_retains_a_real_bun_failure(repository, tmp_path):
    version = subprocess.run(["bun", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if tuple(map(int, version.split("."))) < (1, 4, 2):
        pytest.skip("requires Bun >=1.4.2; required Runtime contracts job installs it")
    root, git, base = repository
    (root / "src/value.ts").write_text("export const value = 2;")
    git("add", ".")
    git("commit", "-qm", "break")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"schema_version": "ci-esta/bun-inventory/v1",
                                     "files": ["src/value.test.ts"], "alwaysRunFiles": []}))
    result = run_bun_tests(RunRequest(cwd=root, base=base, inventory_file=str(inventory),
                                     policy_file="policy.json", output_directory=tmp_path / "output"))
    assert result.mode == "scoped"
    assert result.exit_code != 0
    assert result.executed_files == ["src/value.test.ts"]
