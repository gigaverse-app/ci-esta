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

@pytest.mark.skipif(shutil.which('bun') is None, reason='Bun required')
def test_preloads_and_history_preserve_fresh_execution(repository, tmp_path):
    root, git, base = repository
    (root / 'setup.ts').write_text('globalThis.ready = 42;')
    (root / 'src/value.test.ts').write_text(
        "import {test,expect} from 'bun:test'; test('preload',()=>expect(globalThis.ready).toBe(42));")
    git('add', '.')
    git('commit', '-qm', 'preload fixture')
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps({'schema_version':'ci-esta/bun-inventory/v1',
                                    'files':['src/value.test.ts'], 'alwaysRunFiles':[]}))
    history = tmp_path / 'history.json'
    history.write_text(json.dumps({'files': {'src/value.test.ts': 100, 'src/old.test.ts': 500}}))
    result = run_bun_tests(RunRequest(cwd=root, base=base, full=True, inventory_file=str(inventory),
        policy_file='policy.json', output_directory=tmp_path / 'execution',
        preloads=['setup.ts'], timing_history=str(history)))
    assert result.exit_code == 0
    assert result.executed_files == ['src/value.test.ts']
    learned = json.loads(history.read_text())['files']
    assert set(learned) == {'src/value.test.ts'}
    assert learned['src/value.test.ts'] >= 0


def test_learned_batches_balance_whole_files():
    from ci_esta.testing.bun.execution import balanced_batches
    assert balanced_batches(['a', 'b', 'c', 'd'], 2, {'a': 9, 'b': 8, 'c': 2, 'd': 1}) == [['a', 'd'], ['b', 'c']]

@pytest.mark.skipif(shutil.which('bun') is None, reason='Bun required')
def test_history_never_proves_unchanged_files_or_learns_failures(repository, tmp_path):
    root, git, base = repository
    (root / 'src/other.test.ts').write_text("import {test} from 'bun:test'; test('other',()=>{});")
    git('add', '.')
    git('commit', '-qm', 'other test')
    base = git('rev-parse', 'HEAD')
    (root / 'src/value.ts').write_text('export const value = 2;')
    git('add', '.')
    git('commit', '-qm', 'failing affected test')
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps({'schema_version':'ci-esta/bun-inventory/v1',
        'files':['src/value.test.ts','src/other.test.ts'], 'alwaysRunFiles':[]}))
    history = tmp_path / 'history.json'
    original = json.dumps({'files':{'src/value.test.ts':9,'src/other.test.ts':99}})
    history.write_text(original)
    result = run_bun_tests(RunRequest(cwd=root, base=base, inventory_file=str(inventory),
        policy_file='policy.json', output_directory=tmp_path/'execution', timing_history=str(history), shards=2))
    assert result.mode == 'scoped'
    assert result.exit_code != 0
    assert result.executed_files == ['src/value.test.ts']
    assert history.read_text() == original


@pytest.mark.skipif(shutil.which('bun') is None, reason='Bun required')
@pytest.mark.parametrize('directory_manifest', [False, True])
def test_shared_declarations_select_and_execute_only_the_bun_reader(repository, tmp_path, directory_manifest):
    """A non-import input reaches its reader through pytest-selective's real format."""
    from ci_esta.testing.bun.graph import test_inputs

    root, git, _ = repository
    (root / 'fixtures').mkdir()
    (root / 'fixtures/value.txt').write_text('one')
    (root / 'src/value.ts').write_text(
        "import {readFileSync} from 'node:fs'; "
        "export const value = readFileSync(new URL('../fixtures/value.txt', import.meta.url), 'utf8');")
    (root / 'src/value.test.ts').write_text(
        "import {test,expect} from 'bun:test'; import {value} from './value'; test('read',()=>expect(value).toBeTruthy());")
    (root / 'src/other.test.ts').write_text("import {test} from 'bun:test'; test('unrelated',()=>{});")
    manifest = 'src/.gv-dependencies.yaml' if directory_manifest else 'src/value.ts.gv-dependency.yaml'
    (root / manifest).write_text(
        'dependencies:\n  - inputs: ["//fixtures/*.txt"]\n    kind: content\n'
        + ('    readers: ["value.ts"]\n' if directory_manifest else ''))
    git('add', '.')
    git('commit', '-qm', 'declared reader')
    base = git('rev-parse', 'HEAD')
    (root / 'fixtures/value.txt').write_text('two')
    git('add', '.')
    git('commit', '-qm', 'change content')
    files = git('ls-files').splitlines()
    graph = test_inputs(root, ['src/value.test.ts', 'src/other.test.ts'], 'bun', set(files))
    assert 'fixtures/value.txt' in graph['src/value.test.ts']
    assert 'fixtures/value.txt' not in graph['src/other.test.ts']
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps({'schema_version': 'ci-esta/bun-inventory/v1',
                                    'files': ['src/value.test.ts', 'src/other.test.ts'], 'alwaysRunFiles': []}))
    result = run_bun_tests(RunRequest(cwd=root, base=base, inventory_file=str(inventory),
                                    output_directory=tmp_path / 'execution', args=['--isolate']))
    assert result.mode == 'scoped' and not result.fallback
    assert result.exit_code == 0 and result.complete
    assert result.executed_files == ['src/value.test.ts']


@pytest.mark.skipif(shutil.which('bun') is None, reason='Bun required')
def test_invalid_shared_declaration_fails_instead_of_becoming_a_successful_fallback(repository):
    from selective_deps import DependencyDeclarationError

    root, git, base = repository
    (root / 'src/value.ts.gv-dependency.yaml').write_text('dependencies:\n  - inputs: ["//missing.txt"]\n')
    git('add', '.')
    git('commit', '-qm', 'invalid declaration')
    with pytest.raises(DependencyDeclarationError, match='matches no tracked files'):
        plan_affected_tests(SelectionRequest(cwd=root, base=base))


@pytest.mark.skipif(shutil.which('bun') is None, reason='Bun required')
@pytest.mark.parametrize('kind,selected', [('content', []), ('import', ['src/reader.test.ts'])])
def test_portable_content_edges_do_not_follow_the_read_files_imports(repository, kind, selected):
    root, git, _ = repository
    (root / 'src/leaf.ts').write_text('export const leaf = 1;')
    (root / 'src/value.ts').write_text("export {leaf as value} from './leaf';")
    (root / 'src/reader.test.ts').write_text("import {test} from 'bun:test'; test('reader',()=>{});")
    (root / 'src/reader.test.ts.gv-dependency.yaml').write_text(
        f'dependencies:\n  - inputs: [value.ts]\n    kind: {kind}\n')
    git('add', '.')
    git('commit', '-qm', 'content and import fixture')
    base = git('rev-parse', 'HEAD')
    (root / 'src/leaf.ts').write_text('export const leaf = 2;')
    git('add', '.')
    git('commit', '-qm', 'change transitive import')
    plan = plan_affected_tests(SelectionRequest(cwd=root, base=base, test_files=['src/reader.test.ts']))
    assert not plan.fallback
    assert plan.selected_files == selected


@pytest.mark.skipif(shutil.which('bun') is None, reason='Bun required')
def test_declared_preload_dependencies_expand_the_full_suite(repository):
    root, git, _ = repository
    (root / 'setup.ts').write_text("import './src/value';")
    git('add', '.')
    git('commit', '-qm', 'preload')
    base = git('rev-parse', 'HEAD')
    (root / 'src/value.ts').write_text('export const value = 2;')
    git('add', '.')
    git('commit', '-qm', 'change preload dependency')
    plan = plan_affected_tests(SelectionRequest(cwd=root, base=base, preloads=['setup.ts']))
    assert plan.mode == 'full' and 'preload' in plan.reason
