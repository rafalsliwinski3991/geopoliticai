from graph import graph


def test_graph_exposes_pipeline_nodes() -> None:
    node_ids = set(graph.get_graph().nodes.keys())
    assert "ingest_request" in node_ids
    assert "compose_final" in node_ids
    assert "supervisor" in node_ids
