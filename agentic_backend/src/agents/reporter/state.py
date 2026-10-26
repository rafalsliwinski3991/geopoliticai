"""The reporter agent's state and structured schemas."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field
from typing_extensions import NotRequired

from agents.reporter.config import MAX_TRANSCRIPT_CHARS
from config import FOOTER_PREFIX
from models import CleanText

GateAction = Literal["approve", "revise", "cancel"]
ResumeAction = Literal["approve", "revise", "cancel", "new_question"]


class OutlineDraft(BaseModel):
    """The outline node's structured output.

    Both fields are required with no default, which is what
    `with_structured_output(..., strict=True)` needs. `notice` carries the
    refusal text when the model declines a request; it is the empty string
    otherwise, never omitted.
    """

    sections: list[CleanText] = Field(
        description=(
            "Proposed report section headings, in order. Empty only when the "
            "conversation contains no researched material to report on."
        )
    )
    notice: CleanText = Field(
        description=(
            "A short explanation for the user when a request was declined or "
            "narrowed. Empty string when there is nothing to say."
        )
    )


class ResumeIntent(BaseModel):
    """What one line typed at a paused report gate means."""

    action: ResumeAction = Field(
        description=(
            "'approve' to write the report as outlined, 'cancel' to drop it, "
            "'revise' to change the outline, 'new_question' when the text is a "
            "new question about the subject rather than a comment on the outline."
        )
    )
    instruction: CleanText = Field(
        description=(
            "For 'revise', the change to apply, in the user's own terms. "
            "Empty string for every other action."
        )
    )


class ReporterState(TypedDict):
    """The reporter's state. Shares no key with `OrchestratorState`."""

    transcript: str
    outline: list[str]
    notice: str
    instruction: str
    revisions: int
    report: str
    decision: NotRequired[GateAction]


def build_transcript(messages: Sequence[AnyMessage]) -> str:
    """Render the whole thread, newest-first, within a character budget.

    Reads every message since the chat began (Q15) rather than the
    orchestrator's 20-message window. The budget is applied newest-first and
    silently (Q7A). A message is kept only if it fits whole, so a truncated
    thread never hands the model half a sentence.
    """
    blocks: list[str] = []
    used = 0
    for message in reversed(list(messages)):
        if isinstance(message, AIMessage):
            if message.tool_calls:
                continue
            if message.text.startswith(FOOTER_PREFIX):
                continue
            text = message.text.strip()
        elif isinstance(message, ToolMessage):
            artifact = message.artifact
            if isinstance(artifact, dict) and "text" in artifact:
                text = str(artifact["text"]).strip()
            else:
                text = str(message.content).strip()
        elif isinstance(message, HumanMessage):
            text = message.text.strip()
        else:
            text = getattr(message, "text", str(message.content)).strip()

        if not text:
            continue
        speaker = "User" if isinstance(message, HumanMessage) else "Assistant"
        block = f"{speaker}: {text}"
        if used + len(block) > MAX_TRANSCRIPT_CHARS:
            break
        blocks.append(block)
        used += len(block)
    blocks.reverse()
    return "\n\n".join(blocks)


def has_researched_material(
    messages: Sequence[AnyMessage],
    workspace_synthesis: Sequence[str] | None = None,
    workspace_forecasts: Sequence[Any] | None = None,
) -> bool:
    """Is there anything in this thread a report could be built from?

    (Q5.) A report is made of researched answers, full stop (Q3). Material is
    found three ways: the orchestrator's `expert_synthesis` channel holds an
    answer, its `forecast_data` channel holds a forecast, or a message in the
    thread carries a markdown link to http(s). The link is a deterministic
    proxy for "a specialist answered": the expert's `ANSWER_SYSTEM_PROMPT`
    rule 1 requires every factual sentence to carry an inline `[anchor](URL)`
    link, and the supervisor prompt's rule 1 forbids a chat answer from citing
    anything. For a ToolMessage the link is looked for in its artifact text,
    or in its content when it has no artifact text.

    The proxy is not a proof, and the direction it fails in is known: a chat
    answer that emits a markdown link despite its prompt (echoing a URL the
    user pasted, say) passes this gate. The consequence is bounded: the outline
    and the report are built only from transcript content, so the worst case
    is a thin report over chat material, not a fabricated one. Making this
    exact would mean marking each `AIMessage` with the branch that produced it
    and persisting that through the checkpoint, which is real scope this plan
    does not have. Recorded as a follow-up (§7 Q-F) and asserted as a known
    false positive in `test_state.py`, so it is a decision rather than an
    oversight.

    This exists because the obvious check, an empty transcript, is
    unreachable: by the time the reporter runs, `add_messages` has already
    merged the user's own request into `messages`, so the transcript always
    holds at least that turn.
    """
    if workspace_synthesis:
        return True
    if workspace_forecasts:
        return True
    for message in messages:
        if isinstance(message, AIMessage) and "](http" in message.text:
            return True
        if isinstance(message, ToolMessage):
            artifact = message.artifact
            if isinstance(artifact, dict) and "text" in artifact:
                if "](http" in str(artifact["text"]):
                    return True
            elif "](http" in str(message.content):
                return True
    return False


def build_initial_reporter_state(transcript: str) -> ReporterState:
    """Return the input for one report run.

    An empty transcript is not rejected here: it is exactly the Q5 case, and
    `outline` refuses it without a model call.
    """
    return {
        "transcript": transcript,
        "outline": [],
        "notice": "",
        "instruction": "",
        "revisions": 0,
        "report": "",
    }
