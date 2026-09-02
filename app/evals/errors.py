"""The one distinction this harness exists to keep straight.

`InvalidRunError` means the *evaluation system* failed: a missing credential,
an unreachable Phoenix, a corpus whose hash no longer matches, a judge call
that raised. An invalid run produces no score and exits nonzero.

A product failure — a `PipelineError` from the agent, or a turn routed to the
wrong branch — is not an error here. It is a valid observation that scores
zero, and the command still exits successfully (brainstorm: "Controlled
offline harness and failure attribution", "Pilot result and exit semantics").
"""

from __future__ import annotations


class InvalidRunError(RuntimeError):
    """The evaluation could not be trusted; no score may be reported."""
