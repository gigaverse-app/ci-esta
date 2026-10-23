import xml.etree.ElementTree as ET

import pytest

from ci_esta.ci_observability import brand
from ci_esta.ci_observability.report import render_markdown
from ci_esta.ci_observability.svg_headlines import SvgHeadlines
from tests.ci_observability.test_headlines import report_with_work, work


def test_svg_and_text_keep_the_same_evidence_and_expandable_details():
    report = report_with_work(work(mode="full", status="failed", files=["a.test.ts"]))
    images = SvgHeadlines()
    rendered = render_markdown(report, headlines=images)
    assert "<picture>" in rendered
    assert "img.shields.io" not in rendered
    assert rendered.count("<details>") == render_markdown(report).count("<details>")
    assert "10 / 10 files selected" in rendered
    assert "1 / 10 files executed" in rendered
    assert "unavailable est. cost" in rendered
    assert "a.test.ts" in rendered
    assert len(images.assets) >= 8
    assert all(ET.fromstring(svg).tag.endswith("svg") for svg in images.assets.values())


def test_untrusted_text_cannot_create_svg_markup_or_external_requests():
    images = SvgHeadlines()
    text = '\"><script>alert(1)</script><image href="https://evil.test"/>'
    images.row([brand.Badge(text, text, "red")], "test")
    for svg in images.assets.values():
        root = ET.fromstring(svg)
        assert all(node.tag.split("}")[-1] in {"svg", "title", "rect", "text", "tspan", "line"} for node in root.iter())
        assert all("href" not in key for node in root.iter() for key in node.attrib)
        assert text in "".join(root.itertext())


def test_safe_text_fallback_never_sends_metrics_to_an_image_service():
    output = render_markdown(report_with_work(work()), private_metrics=True)
    assert "img.shields.io" not in output
    assert "selected: unavailable" in output
    assert "<details>" in output


@pytest.mark.parametrize("value", ["unavailable", "1,234 / 99,999 files", "0 / 1 work units"])
def test_rows_are_deterministic_and_have_theme_pairs(value):
    a, b = SvgHeadlines(), SvgHeadlines()
    metrics = [brand.Badge("selected", value, brand.BLUE)]
    assert a.row(metrics, "selection") == b.row(metrics, "selection")
    assert a.assets == b.assets
    assert len(a.assets) == 2
