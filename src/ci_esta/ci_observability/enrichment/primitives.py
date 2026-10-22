"""Duration parsing/formatting shared by every enrichment profile.

Both consumer repos carried byte-identical copies of these helpers; this
is their single home now.
"""

from __future__ import annotations

import re
from pathlib import Path

from ci_esta.ci_observability.enrichment.models import PytestTimingMetadata


def parse_duration_seconds(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    if value.replace(".", "", 1).isdigit():
        return float(value)
    matches = re.findall(r"([\d.]+)\s*([hms])", value)
    if not matches:
        return None
    factors = {"h": 3600, "m": 60, "s": 1}
    return round(
        sum(float(amount) * factors[unit] for amount, unit in matches),
        1,
    )


def format_seconds(value: float | None) -> str:
    if value is None:
        return "unavailable"
    minutes, seconds = divmod(round(value), 60)
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


def write_pytest_metadata(
    output: Path,
    *,
    shard_count: int,
    wall_time: str,
    total_time: str,
) -> None:
    metadata = PytestTimingMetadata(
        shard_count=shard_count,
        wall_seconds=parse_duration_seconds(wall_time),
        total_test_seconds=parse_duration_seconds(total_time),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(metadata.model_dump_json(indent=2) + "\n")
