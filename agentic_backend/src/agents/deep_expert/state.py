"""What one deep research turn has spent and seen.

The graph is built per call (see `graph.py`), so each turn's tools and grader
callback are closures over their own `ResearchRun`. No context variable and no
shared mutable state. The general-purpose subagent receives the same tool
objects, so it spends from the same budget.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from deepagents.middleware import RubricEvaluation
from langgraph.types import StreamWriter

from agents.deep_expert.config import LIMITS
from agents.deep_expert.consts.progress import PROGRESS_NODE, REVISION_PROGRESS_LABEL
from models import Candidate, Source


@dataclass
class ResearchRun:
    """One turn's budget, sources, and grader verdicts."""

    writer: StreamWriter
    searches: int = 0
    candidates: dict[str, Candidate] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    verdicts: list[str] = field(default_factory=list)
    # One in-flight read per URL (review thread, #129 c4142559750): concurrent
    # `read_source` calls for the same URL serialize on this lock; the second
    # arrival finds the source cached and skips the fetch.
    read_locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def lock_for(self, url: str) -> asyncio.Lock:
        """Return the read lock for `url`, creating it on first use."""
        return self.read_locks.setdefault(url, asyncio.Lock())

    def progress(self, label: str) -> None:
        """Emit one progress frame; `label` must be code-produced (see consts)."""
        self.writer({"type": "progress", "node": PROGRESS_NODE, "label": label})

    def record_evaluation(self, evaluation: RubricEvaluation) -> None:
        """RubricMiddleware's `on_evaluation`: keep the verdict, announce a revision.

        The only way to read the outcome. `_rubric_status` is a private state
        attribute and is absent from the agent's returned state. The middleware
        logs and suppresses exceptions raised here, so `research()` acts on
        `verdicts` after the run instead of raising from this method.
        """
        self.verdicts.append(evaluation["result"])
        if evaluation["result"] == "needs_revision":
            self.progress(
                REVISION_PROGRESS_LABEL.format(
                    round=evaluation["iteration"] + 1, cap=LIMITS.max_grader_rounds - 1
                )
            )
