"""Exercise the installed clients; only the Docker daemon boundary is recorded."""

import json
import os
import subprocess
from pathlib import Path

ACTION = Path(__file__).resolve().parents[2] / ".github/actions/postgres-client"


def test_clients_preserve_paths_arguments_and_secret_environment(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    path_file = tmp_path / "github-path"
    record = tmp_path / "docker.json"
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['RECORD']).write_text(json.dumps(sys.argv[1:]))\n"
        "assert os.environ['PGPASSWORD'] == 'secret-value'\n"
    )
    docker.chmod(0o755)
    env = dict(
        os.environ,
        RUNNER_OS="Linux",
        RUNNER_TEMP=str(tmp_path),
        GITHUB_WORKSPACE=str(workspace),
        GITHUB_PATH=str(path_file),
        CLIENT_IMAGE="postgres:16",
        CLIENT_ACTION=str(ACTION),
        PGPASSWORD="secret-value",
        RECORD=str(record),
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    subprocess.run(["bash", str(ACTION / "setup.sh")], env=env, check=True)
    directory = Path(path_file.read_text().strip())
    for client in ("pg_dump", "pg_restore", "psql"):
        subprocess.run(
            [str(directory / client), "--file", str(workspace / "db dump")], cwd=workspace, env=env, check=True
        )
        args = json.loads(record.read_text())
        assert args[-5:] == ["--entrypoint", client, "postgres:16", "--file", str(workspace / "db dump")]
        assert f"{workspace}:{workspace}" in args
        assert "PGPASSWORD" in args
        assert "secret-value" not in args
        assert args[args.index("--workdir") + 1] == str(workspace)


def test_non_linux_runner_fails_before_installing(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(ACTION / "setup.sh")], env=dict(os.environ, RUNNER_OS="Windows"), capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "Linux Docker runner" in result.stderr
