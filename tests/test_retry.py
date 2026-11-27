"""`ci-esta retry`: the commands that rerun what a log says failed."""

import subprocess

from ci_esta import cli

PYTEST = """\
tests/test_a.py:7: RuntimeError
=========================== short test summary info ============================
FAILED tests/test_a.py::test_param[a - b] - AssertionError: assert 'a - b' ==...
FAILED tests/test_a.py::TestK::test_m - RuntimeError: boom - really
ERROR tests/test_a.py::test_fixture - ValueError: setup
ERROR tests/test_collect.py
FAILED tests/test_gone.py::test_removed - AssertionError
FAILED tests/test_a.py::TestK::test_m - RuntimeError: boom - really
2 failed, 1 passed, 2 errors in 0.03s
"""

BUN = """\
bun test v1.4.2 (744846f84)

tests/broken.test.ts:

# Unhandled error between tests
-------------------------------
error: Cannot find module '../src/missing' from '/work/tests/broken.test.ts'
-------------------------------


tests/ok.test.ts:
(pass) fine [0.12ms]

tests/unit/math.test.ts:
error: expect(received).toBe(expected)
(pass) sum > adds
(fail) sum > fails here [4.26ms]
(fail) sum > fails again [0.26ms]

 2 pass
 2 fail
"""

# Trimmed from a GitHub Actions job log of a Bun suite run in parallel batches. Bun opens a log group per
# file there, and after the last file repeats every failure under `N tests failed:`.
BUN_ON_GITHUB = """\
2026-11-25T21:13:14.5590848Z bun test v1.4.2 (744846f84) 4x PARALLEL
2026-11-25T21:13:15.4041113Z ##[group]src/api/generatedZodImports.test.ts:
2026-11-25T21:13:15.4050935Z error: expect(received).toContain(expected)
2026-11-25T21:13:15.4721316Z ##[error]Expected to contain: "import * as z from 'zod/v4';"
2026-11-25T21:13:15.4731872Z (fail) %s builds on the zod/v4 subpath [1.38ms]
2026-11-25T21:13:15.4732011Z (pass) %s builds on the zod/v4 subpath [0.25ms]
2026-11-25T21:13:15.4732342Z 
2026-11-25T21:13:15.4732571Z ##[endgroup]
2026-11-25T21:13:25.9101122Z 
2026-11-25T21:13:25.9101344Z ##[group]src/mock-harness/mcp/tools/run.test.ts:
2026-11-25T21:13:25.9101822Z (pass) a command > leaves its mutation to be collected once it settled [1.41ms]
2026-11-25T21:13:25.9102059Z 
2026-11-25T21:13:25.9102263Z ##[endgroup]
2026-11-25T21:13:25.9180911Z 
2026-11-25T21:13:25.9181620Z 1 tests failed:
2026-11-25T21:13:25.9182262Z (fail) %s builds on the zod/v4 subpath [1.38ms]
2026-11-25T21:13:25.9182811Z 
2026-11-25T21:13:25.9183055Z  1 fail
2026-11-25T21:13:25.9183494Z Ran 3598 tests across 88 files. [12.34s]
2026-11-25T21:13:25.9410873Z bun test v1.4.2 (744846f84) 4x PARALLEL
2026-11-25T21:13:26.1001100Z ##[group]src/mock-harness/host/in-process.test.ts:
2026-11-25T21:13:26.1002200Z killed 1 dangling process
2026-11-25T21:13:26.1003300Z 
2026-11-25T21:13:26.1004400Z # Unhandled error between tests
2026-11-25T21:13:26.1005500Z -------------------------------
2026-11-25T21:13:26.1006600Z error: expect(received).toEqual(expected)
"""


def checkout(tmp_path, *paths):
    for path in paths:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
    return tmp_path


def test_retry_prints_pytest_ids_and_bun_files_that_failed(tmp_path, capsys):
    repo = checkout(
        tmp_path, "tests/test_a.py", "tests/test_collect.py", "tests/broken.test.ts", "tests/unit/math.test.ts"
    )
    log = tmp_path / "ci.log"
    log.write_text(PYTEST + BUN, encoding="utf-8")
    assert cli.main(["retry", str(log), "--repo", str(repo)]) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == [
        "pytest 'tests/test_a.py::test_param[a - b]' tests/test_a.py::TestK::test_m "
        "tests/test_a.py::test_fixture tests/test_collect.py",
        "bun test ./tests/broken.test.ts ./tests/unit/math.test.ts",
    ]
    assert err == "ci-esta retry: not in this checkout: tests/test_gone.py::test_removed\n"


def test_retry_reads_the_file_of_a_bun_failure_from_a_github_actions_log(tmp_path, capsys):
    files = ["src/api/generatedZodImports.test.ts", "src/mock-harness/mcp/tools/run.test.ts"]
    repo = checkout(tmp_path, *files, "src/mock-harness/host/in-process.test.ts")
    log = tmp_path / "job.log"
    log.write_text("\ufeff" + BUN_ON_GITHUB, encoding="utf-8")
    assert cli.main(["retry", str(log), "--repo", str(repo)]) == 0
    # The failure Bun repeats after the last file belongs to the first file, not to the one printed before it.
    expected = "bun test ./src/api/generatedZodImports.test.ts ./src/mock-harness/host/in-process.test.ts\n"
    assert capsys.readouterr() == (expected, "")
    # Output captured from the step itself still holds the workflow commands GitHub would have rewritten.
    captured = "".join(line.partition("Z ")[2] + "\n" for line in BUN_ON_GITHUB.splitlines())
    log.write_text(captured.replace("##[group]", "::group::").replace("##[endgroup]", "::endgroup::"), encoding="utf-8")
    assert cli.main(["retry", str(log), "--repo", str(repo)]) == 0
    assert capsys.readouterr() == (expected, "")


def test_retry_reads_github_job_logs_from_stdin(tmp_path, capsys, monkeypatch):
    repo = checkout(tmp_path, "tests/test_a.py")
    lines = "".join(
        f"\x1b[31mtest\tRun pytest\t2026-11-27T10:00:00.1234567Z {line}\x1b[0m\r\n" for line in PYTEST.splitlines()
    )
    monkeypatch.setattr("sys.stdin", iter(("﻿" + lines).splitlines(keepends=True)))
    assert cli.main(["retry", "-", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.startswith("pytest 'tests/test_a.py::test_param[a - b]' ")


def test_retry_prints_the_lake_command_next_to_the_others(tmp_path, capsys):
    repo = checkout(tmp_path, "tests/test_a.py", "Lib/Broken.lean")
    (repo / "lakefile.toml").write_text('name = "demo"\n')
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    log = tmp_path / "ci.log"
    log.write_text(PYTEST + "✖ [3/5] Building Lib.Broken (1.2s)\nerror: Lib/Broken.lean:3:2: unknown tactic\n")
    assert cli.main(["retry", str(log), "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == ["lake build +Lib.Broken"]


def test_retry_says_when_the_log_names_nothing_it_can_rerun(tmp_path, capsys):
    log = tmp_path / "ci.log"
    log.write_text("ERROR: usage: pytest [options]\nFAILED to connect - retrying\nsrc/notes.test.md:\n(fail) x\n")
    assert cli.main(["retry", str(log), "--repo", str(tmp_path)]) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert "no pytest, Bun or Lake failure" in err
    assert cli.main(["retry", str(tmp_path / "missing.log")]) == 1
    assert "missing.log" in capsys.readouterr().err
