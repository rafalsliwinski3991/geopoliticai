"""Graph construction for the reporter agent."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.reporter.nodes import gate, outline, write
from agents.reporter.state import ReporterState, build_initial_reporter_state
from shared.tracing import init_tracing


def _after_outline(state: ReporterState) -> str:
    """Refuse without pausing when there is nothing to approve."""
    return "gate" if state["outline"] else END


def _after_gate(state: ReporterState) -> str:
    """Read the decision `gate` already recorded; decide nothing here."""
    decision = state["decision"]
    if decision == "approve":
        return "write"
    if decision == "cancel":
        return END
    return "outline"


def build_graph(checkpointer: Any | None = None) -> Any:
    """Construct and compile the reporter subgraph.

    Production compiles this with no checkpointer, exactly like the expert: the
    orchestrator's saver carries the child's pause and resumes it in place
    (verified against langgraph 1.0.1 — the child resumes at `gate` without
    re-running `outline`). The argument exists so tests can drive the child
    alone with an `InMemorySaver`.
    """
    reporter = StateGraph(ReporterState)
    reporter.add_node("outline", outline)
    reporter.add_node("gate", gate)
    reporter.add_node("write", write)
    reporter.add_edge(START, "outline")
    reporter.add_conditional_edges(
        "outline", _after_outline, {"gate": "gate", END: END}
    )
    reporter.add_conditional_edges(
        "gate", _after_gate, {"outline": "outline", "write": "write", END: END}
    )
    reporter.add_edge("write", END)
    return reporter.compile(name="reporter", checkpointer=checkpointer)


# Same reason as the other two graph modules: `langgraph dev` imports this and
# nothing else, so module scope is Studio's only hook for Phoenix tracing.
init_tracing()
graph = build_graph()


async def report(transcript: str) -> dict[str, Any]:
    """Run the reporter on `transcript` and return the graph's final state.

    Called from the orchestrator's `run_reporter` tool, inside the orchestrator's
    run: the child graph inherits that run's checkpointer, so a pause and its
    resume work as they did when the tool called `graph.ainvoke` itself.
    """
    result: dict[str, Any] = await graph.ainvoke(
        build_initial_reporter_state(transcript)
    )
    return result
