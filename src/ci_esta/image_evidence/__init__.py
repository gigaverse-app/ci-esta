"""Service-independent image evidence; application invariants belong to consumers."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

_DIGEST = r"sha256:[a-f0-9]{64}"
_GITHUB_TOKEN = re.compile(rb"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})")


class Layer(BaseModel):
    """The OCI descriptor fields needed to measure compressed blob reuse."""

    digest: str = Field(pattern=rf"^{_DIGEST}$")
    size: int = Field(ge=0)


class LayerComparison(BaseModel):
    layers: int
    compressed_bytes: int
    new_compressed_bytes: int
    new_layers: int
    common_prefix_layers: int


def compare_layers(seed: list[Layer], changed: list[Layer]) -> LayerComparison:
    """
    Count unique transferred blobs separately from ordered parent-chain reuse.

    Descriptor bytes exclude manifests/config and do not predict decompression or
    container readiness. Consumers must measure actual pulls as a separate drill.
    """
    seed_digests = {layer.digest for layer in seed}
    new = {layer.digest: layer for layer in changed if layer.digest not in seed_digests}
    prefix = 0
    for before, after in zip(seed, changed, strict=False):
        if before.digest != after.digest:
            break
        prefix += 1
    return LayerComparison(
        layers=len(changed),
        compressed_bytes=sum(layer.size for layer in changed),
        new_compressed_bytes=sum(layer.size for layer in new.values()),
        new_layers=len(new),
        common_prefix_layers=prefix,
    )


def parse_digest(report: str) -> str:
    """
    Read Buildx's top-level identity; .Manifest.Digest is absent in Buildx 0.28.

    Reject ambiguous output instead of accidentally accepting a platform child
    digest or silently recording an empty image identity in benchmark evidence.
    """
    values = re.findall(r"^Digest:\s*(\S+)\s*$", report, flags=re.MULTILINE)
    if len(values) != 1 or re.fullmatch(_DIGEST, values[0]) is None:
        raise ValueError("Buildx returned no unique manifest digest")
    return values[0]


def redact(data: bytes, secrets: list[bytes]) -> bytes:
    """Redact exact in-process secrets and recognizable GitHub tokens."""
    # Longest first prevents a shorter credential from exposing a longer one's
    # suffix. No secret values are accepted as CLI arguments or printed.
    for secret in sorted(set(secrets) - {b""}, key=len, reverse=True):
        data = data.replace(secret, b"***")
    return _GITHUB_TOKEN.sub(b"***", data)


def sanitize(directory: Path, secrets: list[bytes]) -> int:
    """
    Sanitize known evidence formats recursively; callers gate upload on success.

    Refuse symlinks rather than rewriting or publishing files outside the owned
    artifact tree. This is a publication defense, not permission to trace secrets.
    """
    if not directory.is_dir():
        raise FileNotFoundError("Evidence directory does not exist")
    count = 0
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Evidence must not contain a symlink")
        if path.is_file() and path.suffix in {".log", ".json", ".jsonl", ".sha256"}:
            data = path.read_bytes()
            clean = redact(data, secrets)
            if clean != data:
                path.write_bytes(clean)
                count += 1
    return count
