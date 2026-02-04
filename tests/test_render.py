import pytest

from geopoliticai.models import PipelineState, Source
from geopoliticai.render import merge_sources, render_sources


@pytest.mark.parametrize(
    ("left_urls", "right_urls", "expected_count"),
    [
        (["https://a.test"], ["https://b.test"], 2),
        (["https://dup.test"], ["https://dup.test"], 1),
    ],
)
def test_merge_sources_deduplicates(left_urls, right_urls, expected_count):
    state: PipelineState = {
        "query": "q",
        "left_claims": [],
        "centrist_claims": [],
        "right_claims": [],
        "left_sources": [
            Source(id="S1", title="L", url=left_urls[0], notes="n")
        ],
        "centrist_sources": [],
        "right_sources": [
            Source(id="S2", title="R", url=right_urls[0], notes="n")
        ],
        "fact_sources": [],
        "fact_checks": [],
        "synthesis": "",
        "final_output": "",
    }

    merged = merge_sources(state)

    assert len(merged) == expected_count


@pytest.mark.parametrize(
    "source",
    [
        Source(id="S1", title="Title", url="https://example.com", notes="note"),
        Source(id="S9", title="Other", url="https://other.com", notes="summary"),
    ],
)
def test_render_sources_outputs_expected_format(source):
    rendered = render_sources([source])

    assert source.id in rendered
    assert source.title in rendered
    assert source.url in rendered
    assert source.notes in rendered
