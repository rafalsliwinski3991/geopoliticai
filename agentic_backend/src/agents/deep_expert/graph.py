"""Graph construction for the deep expert agent.

Unlike the other agents there is no module-level `graph`. `ChatOpenAI` refuses
to construct without `OPENAI_API_KEY`, and `make test` and CI run without one.
Each turn's tools are also closures over that turn's `ResearchRun`.
`research()` builds the agent per call. Compilation costs milliseconds against
a turn that takes minutes.

The other agents keep the entity the orchestrator-facing entry point needs on
`graph.py`, so the shared shape lives here too: `SHIPPABLE_VERDICTS` (the
grader outcomes that ship, which `research._checked_deep_answer` acts on) and
`NO_CHECKPOINTER_CONFIG` (the invocation config that runs the whole tree
without the parent's saver).
"""

from __future__ import annotations

from typing import Any

from deepagents import RubricMiddleware, create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.constants import CONFIG_KEY_CHECKPOINTER

from agents.deep_expert.config import AGENT_LLM_SETTINGS, GRADER_LLM_SETTINGS, LIMITS
from agents.deep_expert.prompts import (
    DEEP_SUBAGENT_DESCRIPTION,
    DEEP_SUBAGENT_PROMPT,
    DEEP_SYSTEM_PROMPT,
    GRADER_ANSWER_PART,
)
from agents.deep_expert.state import ResearchRun
from agents.deep_expert.tools import build_tools
from llm import build_chat_model

# deepagents' own name for the auto-added subagent; supplying a spec under this
# name replaces the default, whose generic prompt lacks our rule 0 and budget.
GENERAL_PURPOSE_SUBAGENT_NAME = "general-purpose"
# RubricMiddleware cuts every transcript message to 4,000 characters and keeps
# the last 30 (deepagents 0.7.19 `rubric.py` `_MAX_TRANSCRIPT_*`, private).
# A part plus its `GRADER_ANSWER_PART` label stays under the first; 29 parts
# hold ~113,000 characters, more than 16,384 output tokens can produce.
GRADER_PART_CHARS = 3_900

# `max_iterations_reached` ships the last draft (brainstorm Q7A); `failed` and
# `grader_error` are hard errors; no verdict at all means the grader never ran.
SHIPPABLE_VERDICTS = frozenset({"satisfied", "max_iterations_reached"})
# Invoked inside the orchestrator's node, every nested run would inherit its
# Postgres saver: `checkpointer=False` covers only the agent's own loop, while
# its tasks still pass the parent saver down (langgraph 1.2.12
# `pregel/_algo.py:737-740`) to the `task` subagent and the rubric grader. A
# None under this key reaches the whole tree and disables all of it.
# `langgraph.constants` keeps the name public through 1.x; the pin is <1.3.
NO_CHECKPOINTER_CONFIG: RunnableConfig = {
    "configurable": {CONFIG_KEY_CHECKPOINTER: None}
}


def grader_view(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Return what the grader reads: the question and the whole final draft.

    RubricMiddleware's `prepare_messages_for_grader` hook. Unfiltered, the
    grader would see the draft cut to its first 4,000 characters, and its
    prompt fails every criterion it cannot confirm, so a long analysis would be
    sent back for revision on every round. The draft is handed over in
    labelled parts that each survive the cut. Tool traffic is dropped: the
    rubric grades the answer, and which sources it cites is checked in code
    (`research._checked_deep_answer`).
    """
    question = next((m for m in messages if isinstance(m, HumanMessage)), None)
    draft = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if question is None or draft is None:
        return messages
    text = draft.text
    parts = [
        text[start : start + GRADER_PART_CHARS]
        for start in range(0, len(text), GRADER_PART_CHARS)
    ] or [""]
    return [
        question,
        *(
            AIMessage(GRADER_ANSWER_PART.format(index=index, total=len(parts)) + part)
            for index, part in enumerate(parts, start=1)
        ),
    ]


def build_graph(run: ResearchRun) -> Any:
    """Construct and compile the deep agent for one turn.

    `TodoListMiddleware` is explicit: deepagents 0.7.19 no longer adds
    `write_todos` by default (only its Codex and Nemotron harness profiles do).

    `checkpointer=False` stops this agent's own loop from inheriting the
    orchestrator's Postgres saver. It does not reach the `task` subagent or the
    rubric grader, which compile with no checkpointer and would still inherit
    it; `research()` switches the saver off for the whole tree at invocation
    (`NO_CHECKPOINTER_CONFIG`). The run has no interrupt and is never resumed,
    so checkpoint writes would buy nothing.
    """
    # The installed middleware classes are invariant on their state parameter
    # (`RubricState` vs `PlanningState[ResponseT]`), so the heterogeneous list
    # cannot type as `Sequence[AgentMiddleware[StateT, ...]]` directly.
    middleware: list[Any] = [
        TodoListMiddleware(),
        RubricMiddleware(
            model=build_chat_model(GRADER_LLM_SETTINGS),
            max_iterations=LIMITS.max_grader_rounds,
            on_evaluation=run.record_evaluation,
            prepare_messages_for_grader=grader_view,
        ),
    ]
    model = build_chat_model(AGENT_LLM_SETTINGS)
    tools = build_tools(run)
    return create_deep_agent(
        model,
        tools,
        system_prompt=DEEP_SYSTEM_PROMPT.format(max_searches=LIMITS.max_searches),
        subagents=[
            {
                "name": GENERAL_PURPOSE_SUBAGENT_NAME,
                "description": DEEP_SUBAGENT_DESCRIPTION,
                "system_prompt": DEEP_SUBAGENT_PROMPT,
                "tools": tools,
                "model": model,
            }
        ],
        middleware=middleware,
        checkpointer=False,
        name="deep_expert",
    )
