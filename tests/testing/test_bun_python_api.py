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
@pytest.mark.parametrize('reader', [
    "import {readFileSync} from 'node:fs'; export const value = Number(readFileSync(new URL('./input.ts', import.meta.url), 'utf8'));",
    "const name = './input'; export const {value} = await import(name);",
])
@pytest.mark.parametrize('declared', [False, True])
def test_portable_readers_retain_source_only_regressions(repository, tmp_path, reader, declared):
    root, git, _ = repository
    content = "1" if 'readFileSync' in reader else 'export const value = 1;'
    (root / 'src/input.ts').write_text(content)
    (root / 'src/value.ts').write_text(reader)
    (root / 'src/unrelated.test.ts').write_text("import {test} from 'bun:test'; test('unrelated',()=>{});")
    if declared:
        kind = 'content' if 'readFileSync' in reader else 'import'
        (root / 'src/value.ts.gv-dependency.yaml').write_text(
            f'dependencies:\n  - inputs: [input.ts]\n    kind: {kind}\n')
    git('add', '.')
    git('commit', '-qm', 'reader')
    base = git('rev-parse', 'HEAD')
    (root / 'src/input.ts').write_text(content.replace('1', '0'))
    git('add', '.')
    git('commit', '-qm', 'break reader input')
    inventory = tmp_path / 'inventory.json'
    files = ['src/unrelated.test.ts', 'src/value.test.ts']
    inventory.write_text(json.dumps({'schema_version': 'ci-esta/bun-inventory/v1', 'files': files,
                                     'alwaysRunFiles': []}))
    result = run_bun_tests(RunRequest(cwd=root, base=base, inventory_file=str(inventory),
                                     output_directory=tmp_path / 'execution'))
    assert result.mode == ('scoped' if declared else 'full')
    assert result.fallback is not declared
    assert result.executed_files == (['src/value.test.ts'] if declared else files)
    assert result.exit_code != 0

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


@pytest.mark.parametrize('source,opaque', [
    ("import {mkdtempSync, writeFileSync, rmSync} from 'node:fs'; writeFileSync('out.json', '{}');", False),
    ("import * as fs from 'node:fs/promises'; await fs.appendFile(process.env.GITHUB_OUTPUT, 'x');", False),
    ("import {readFileSync} from 'node:fs'; readFileSync('data.json');", True),
    ("import {existsSync} from 'node:fs'; existsSync('data.json');", True),
    ("import {copyFileSync} from 'node:fs'; copyFileSync('a', 'b');", True),
    ("const files = new Bun.Glob('*.json').scanSync('.');", True),
    ("import {spawnSync} from 'node:child_process'; spawnSync('node', [new URL('./run.mjs', import.meta.url)]);", True),
    ("const script = fileURLToPath(new URL('run.sh', import.meta.url));", True),
    ("if (process.argv[1] === fileURLToPath(import.meta.url)) main();", False),
    ("import {join} from 'node:path'; Bun.spawn(['bun', join(import.meta.dir, 'run.ts')]);", True),
    ("const run = require('path').join(__dirname, 'run.js');", True),
])
def test_only_reads_and_module_relative_paths_need_a_declaration(source, opaque):
    from ci_esta.testing.bun.graph import OPAQUE_DEPENDENCY
    assert bool(OPAQUE_DEPENDENCY.search(source)) is opaque


@pytest.mark.skipif(shutil.which('bun') is None, reason='Bun required')
def test_a_write_only_helper_keeps_selection_without_a_declaration(repository):
    root, git, _ = repository
    (root / 'src/report.ts').write_text(
        "import {writeFileSync} from 'node:fs'; export const report = (v: number) => writeFileSync('out.json', String(v));")
    (root / 'src/report.test.ts').write_text(
        "import {test} from 'bun:test'; import {report} from './report'; test('report',()=>report(1));")
    git('add', '.')
    git('commit', '-qm', 'write-only helper')
    base = git('rev-parse', 'HEAD')
    (root / 'src/report.ts').write_text((root / 'src/report.ts').read_text() + '\n')
    git('add', '.')
    git('commit', '-qm', 'touch helper')
    plan = plan_affected_tests(SelectionRequest(cwd=root, base=base,
                                                test_files=['src/report.test.ts', 'src/value.test.ts']))
    assert not plan.fallback
    assert plan.selected_files == ['src/report.test.ts']


@pytest.mark.skipif(shutil.which('bun') is None, reason='Bun required')
@pytest.mark.parametrize('declared', [False, True])
def test_a_test_running_its_sibling_script_needs_an_import_declaration(repository, declared):
    root, git, _ = repository
    (root / 'src/leaf.ts').write_text('export const leaf = 1;')
    (root / 'src/run.ts').write_text("import {leaf} from './leaf'; console.log(leaf);")
    (root / 'src/run.test.ts').write_text(
        "import {test} from 'bun:test'; "
        "test('run',()=>{Bun.spawnSync(['bun', new URL('./run.ts', import.meta.url).pathname]);});")
    if declared:
        (root / 'src/run.test.ts.gv-dependency.yaml').write_text(
            'dependencies:\n  - inputs: ["run.ts"]\n    kind: import\n')
    git('add', '.')
    git('commit', '-qm', 'subprocess test')
    base = git('rev-parse', 'HEAD')
    (root / 'src/leaf.ts').write_text('export const leaf = 2;')
    git('add', '.')
    git('commit', '-qm', 'change what the script imports')
    plan = plan_affected_tests(SelectionRequest(cwd=root, base=base,
                                                test_files=['src/run.test.ts', 'src/value.test.ts']))
    assert plan.fallback is not declared
    if declared:
        assert plan.selected_files == ['src/run.test.ts']
