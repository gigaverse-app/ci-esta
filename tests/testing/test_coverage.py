from pathlib import Path

import pytest

from ci_esta.testing.coverage import read_coverage_summary


def test_reads_coverage_line_rate_as_percent(tmp_path: Path) -> None:
    report = tmp_path / "coverage.xml"
    report.write_text('<coverage line-rate="0.69851"><packages/></coverage>')

    summary = read_coverage_summary(report)

    assert summary.percent == pytest.approx(69.851)
    assert summary.meets(62.0)


@pytest.mark.parametrize(
    "xml",
    [
        "<testsuite/>",
        "<coverage/>",
        '<coverage line-rate="not-a-number"/>',
        '<coverage line-rate="nan"/>',
        '<coverage line-rate="inf"/>',
        '<coverage line-rate="-inf"/>',
        '<coverage line-rate="-0.01"/>',
        '<coverage line-rate="1.01"/>',
        "<coverage>",
        '<!DOCTYPE coverage [<!ENTITY rate "0.7">]><coverage line-rate="&rate;"/>',
    ],
)
def test_rejects_invalid_or_unsafe_coverage_xml(tmp_path: Path, xml: str) -> None:
    report = tmp_path / "coverage.xml"
    report.write_text(xml)

    with pytest.raises(ValueError):
        read_coverage_summary(report)
