from langgraph.pregel import Pregel

from geopoliticai.graph import graph


def test_graph_compiles() -> None:
    assert isinstance(graph, Pregel)
