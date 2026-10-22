"""Contracts shared by the backend and AI image drills."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ci_esta.image_evidence import Layer, cli, compare_layers, parse_digest, redact, sanitize

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def test_digest_accepts_buildx_report_without_confusing_child_manifests() -> None:
    assert parse_digest(f"Name: example\nDigest: {DIGEST}\nManifests:\n  Name: example@{OTHER_DIGEST}\n") == DIGEST


@pytest.mark.parametrize(
    "report", ["", "Digest: nope", f"Digest: {DIGEST}\nDigest: {OTHER_DIGEST}", f"Digest: {DIGEST} extra"]
)
def test_digest_rejects_missing_invalid_or_ambiguous_identity(report: str) -> None:
    with pytest.raises(ValueError, match="unique manifest digest"):
        parse_digest(report)


def test_layer_comparison_distinguishes_transfer_reuse_from_parent_chain_reuse() -> None:
    first = Layer(digest=DIGEST, size=10)
    second = Layer(digest=OTHER_DIGEST, size=20)
    result = compare_layers([first], [second, first, second])
    assert result.layers == 3
    assert result.compressed_bytes == 50
    assert result.new_compressed_bytes == 20  # A repeated blob transfers once.
    assert result.new_layers == 1
    assert result.common_prefix_layers == 0
    assert compare_layers([first], [first, second]).common_prefix_layers == 1
    assert compare_layers([], []).compressed_bytes == 0


def test_layer_descriptors_validate_external_boundary() -> None:
    with pytest.raises(ValidationError):
        Layer(digest="not-a-digest", size=-1)


def test_redaction_covers_overlapping_values_and_token_patterns() -> None:
    data = b"short-long short ghp_" + b"x" * 30 + b" github_pat_" + b"y" * 30
    assert redact(data, [b"short", b"short-long", b""]) == b"*** *** *** ***"


def test_sanitizer_visits_nested_evidence_and_refuses_symlinks(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    log = nested / "build.log"
    log.write_bytes(b"credential secret")
    unrelated = tmp_path / "image.tar"
    unrelated.write_bytes(b"secret")
    assert sanitize(tmp_path, [b"secret"]) == 1
    assert log.read_bytes() == b"credential ***"
    assert unrelated.read_bytes() == b"secret"
    assert sanitize(tmp_path, [b"secret"]) == 0
    (tmp_path / "link.log").symlink_to(log)
    with pytest.raises(ValueError, match="symlink"):
        sanitize(tmp_path, [b"secret"])


def test_sanitizer_requires_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sanitize(tmp_path / "missing", [b"secret"])


def test_cli_digest_uses_real_command_boundary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def inspect_image(command: list[str], *, text: bool) -> str:
        assert command == ["docker", "buildx", "imagetools", "inspect", "example:tag"]
        assert text
        return f"Digest: {DIGEST}"

    monkeypatch.setattr(cli.subprocess, "check_output", inspect_image)
    cli.main(["digest", "example:tag"])
    assert capsys.readouterr().out.strip() == DIGEST


def test_cli_requires_secret_and_redacts_without_printing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("IMAGE_TEST_SECRET", raising=False)
    args = ["sanitize", str(tmp_path), "--required-secret-env", "IMAGE_TEST_SECRET"]
    with pytest.raises(SystemExit):
        cli.main(args)
    monkeypatch.setenv("IMAGE_TEST_SECRET", "private-value")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "aws-test-value")
    (tmp_path / "build.log").write_text("private-value aws-test-value")
    cli.main(args)
    assert (tmp_path / "build.log").read_text() == "*** ***"
    captured = capsys.readouterr()
    assert "private-value" not in captured.out + captured.err
    assert "Sanitized 1" in captured.out


def test_cli_pull_uses_packaged_driver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def run_driver(command: list[str], *, check: bool) -> None:
        assert command[0] == "bash"
        assert Path(command[1]).is_file()
        assert command[2] == str(tmp_path)
        assert check

    monkeypatch.setattr(cli.subprocess, "run", run_driver)
    (tmp_path / "inputs.json").write_text(
        json.dumps(
            {
                "repository": "registry.example/repo",
                "prefix": "test",
                "dind": "docker@" + DIGEST,
            }
        )
    )
    (tmp_path / "results.jsonl").write_text(
        "\n".join(
            json.dumps({"arm": arm, "scenario": scenario, "sample": 0, "digest": DIGEST})
            for arm in ("baseline", "candidate")
            for scenario in ("cold", "source", "bump")
        )
    )
    cli.main(["pulls", str(tmp_path)])
    assert json.loads((tmp_path / "pull-plan.json").read_text())["sequence"] == ["cold", "source", "bump"]
