"""Pipeline errors: each carries the HTTP status a delivery layer reports."""

from __future__ import annotations

from typing import ClassVar


class PipelineError(RuntimeError):
    """A failure the client must see, never a degraded answer.

    `status` is the HTTP code a delivery layer reports for this failure.
    It lives on the class so adding an error type cannot leave a lookup
    table behind.
    """

    status: ClassVar[int] = 500


class SearchUnavailableError(PipelineError):
    """Every Brave request attempted for this run failed."""

    status: ClassVar[int] = 503


class NoSourcesError(PipelineError):
    """No allow-listed page survived search, fetch, and extraction."""

    status: ClassVar[int] = 422


class LLMInvocationError(PipelineError):
    """The model call failed or returned nothing usable."""

    status: ClassVar[int] = 502


class ReportNotPendingError(PipelineError):
    """A resume arrived for a thread with no report awaiting a decision.

    Probe finding: `Command(resume=...)` on an un-paused thread emits nothing at
    all, which the empty-output branch would report as `502 "The model returned
    an empty answer."` — a model failure blamed for a routing problem.
    """

    status: ClassVar[int] = 409


class ResearchLimitError(PipelineError):
    """A deep research turn or a forecast ran past a wall-time cap.

    A hard error, never a degraded answer (brainstorm 2026Sep28). The search
    cap is a soft stop instead (plan review): it returns a message to the model
    and never raises.
    """

    status: ClassVar[int] = 504


class QuotaExceededError(PipelineError):
    """A research turn the user's or the site's daily quota cannot pay for."""

    status: ClassVar[int] = 429
