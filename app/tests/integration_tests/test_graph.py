from graph import _route_after_referee, graph
from models import RefereeReport


def test_graph_exposes_pipeline_nodes() -> None:
    node_ids = set(graph.get_graph().nodes.keys())
    assert "ingest_request" in node_ids
    assert "compose_final" in node_ids
    assert "supervisor" in node_ids
    assert "cross_check_facts" in node_ids
    assert "extract" + "_claims" not in node_ids


def test_route_after_referee_blocks_invalid_or_blocked_reports() -> None:
    assert _route_after_referee({"referee_report": RefereeReport(blocked=False)}) == "continue"  # type: ignore[arg-type]
    assert _route_after_referee({"referee_report": RefereeReport(blocked=True)}) == "blocked"  # type: ignore[arg-type]
    assert _route_after_referee({}) == "blocked"  # type: ignore[arg-type]
