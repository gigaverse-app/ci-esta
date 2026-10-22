"""
Read and validate an already-generated coverage.py XML report.
"""

from __future__ import annotations

import math
from pathlib import Path

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict


class CoverageSummary(BaseModel):
    """
    Line coverage percentage from a coverage.py XML artifact.
    """

    model_config = ConfigDict(frozen=True)

    percent: float

    def meets(self, minimum_percent: float) -> bool:
        """
        Return whether coverage satisfies the configured floor.
        """
        return self.percent >= minimum_percent


def read_coverage_summary(path: Path) -> CoverageSummary:
    """
    Parse the root line-rate without recomputing source coverage.
    """
    try:
        root = ET.parse(path).getroot()
    except (DefusedXmlException, ET.ParseError, OSError) as error:
        raise ValueError(f"invalid coverage XML: {path}") from error
    if root is None or root.tag.rsplit("}", 1)[-1] != "coverage":
        raise ValueError(f"not a coverage.py XML report: {path}")
    line_rate = root.get("line-rate")
    if line_rate is None:
        raise ValueError(f"coverage XML has no line-rate: {path}")
    try:
        parsed_line_rate = float(line_rate)
    except ValueError as error:
        raise ValueError(f"coverage XML has an invalid line-rate: {path}") from error
    if not math.isfinite(parsed_line_rate) or not 0 <= parsed_line_rate <= 1:
        raise ValueError(f"coverage XML has an invalid line-rate: {path}")
    return CoverageSummary(percent=parsed_line_rate * 100)
