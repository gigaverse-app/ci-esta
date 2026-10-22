"""Minimal Prometheus text-exposition parsing for build-metric artifacts."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

METRIC_PATTERN = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)\{(?P<labels>[^}]*)\}\s+(?P<value>-?[\d.]+)$")
LABEL_PATTERN = re.compile(r'(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)="(?P<value>[^"]*)"')


class MetricSample(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    labels: dict[str, str]
    value: float


def parse_prometheus(path: Path) -> list[MetricSample]:
    samples: list[MetricSample] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = METRIC_PATTERN.fullmatch(line)
        if match is None:
            continue
        labels = {label.group("name"): label.group("value") for label in LABEL_PATTERN.finditer(match.group("labels"))}
        samples.append(
            MetricSample(
                name=match.group("name"),
                labels=labels,
                value=float(match.group("value")),
            )
        )
    return samples


def sample_value(
    samples: list[MetricSample],
    metric_name: str,
    *,
    stage: str | None = None,
) -> float | None:
    return next(
        (
            sample.value
            for sample in samples
            if sample.name == metric_name and (stage is None or sample.labels.get("stage") == stage)
        ),
        None,
    )
