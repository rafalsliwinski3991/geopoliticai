"""The reporter agent's state and structured schemas."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from pydantic import BaseModel, Field
from typing_extensions import NotRequired

from agents.reporter.config import MAX_TRANSCRIPT_CHARS

GateAction = Literal["approve", "revise", "cancel"]
ResumeAction = Literal["approve", "revise", "cancel", "new_question"]


class OutlineDraft(BaseModel):
    """The outline node's structured output.

    Both fields are required with no default, which is what
    `with_structured_output(..., strict=True)` needs. `notice` carries the
    refusal text when the model declines a request; it is the empty string
    otherwise, never omitted.
    """

    sections: list[str] = Field(
        description=(
            "Proposed report section headings, in order. Empty only when the "
            "conversation contains no researched material to report on."
        )
    )
    notice: str = Field(
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
    instruction: str = Field(
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
        text = message.text().strip()
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


def has_researched_material(messages: Sequence[AnyMessage]) -> bool:
    """Is there anything in this thread a report could be built from?

    (Q5.) A report is made of researched answers, full stop (Q3). The expert's
    `ANSWER_SYSTEM_PROMPT` rule 1 requires every factual sentence to carry an
    inline `[anchor](URL)` link, and the orchestrator's `CHAT_SYSTEM_PROMPT`
    rule 1 forbids the chat branch from citing anything. So "an assistant turn
    containing a markdown link to http(s)" is a deterministic proxy for "the
    expert has answered in this thread" — no model call, no coin flip.

    It is a *proxy*, not a proof, and the direction it fails in is known: a
    chat answer that emits a markdown link despite its prompt — echoing a URL
    the user pasted, say — passes this gate. `CHAT_SYSTEM_PROMPT` rule 1 is a
    prompt, and prompts are not guarantees. The consequence is bounded: the
    outline and the report are built only from transcript content, so the worst
    case is a thin report over chat material, not a fabricated one. Making this
    exact would mean marking each `AIMessage` with the branch that produced it
    and persisting that through the checkpoint — a change to the expert and chat
    nodes and to what the thread stores, which is real scope this plan does not
    have. Recorded as a follow-up (§7 Q-F) and asserted as a known false
    positive in `test_state.py`, so it is a decision rather than an oversight.

    This exists because the obvious check — an empty transcript — is
    unreachable: by the time the reporter node runs, `add_messages` has already
    merged the user's own request into `messages`, so the transcript always
    holds at least that turn.
    """
    return any(
        isinstance(message, AIMessage) and "](http" in message.text()
        for message in messages
    )


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
