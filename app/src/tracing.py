"""OpenTelemetry boundary: optional Phoenix span export.

Tracing is a deliberate exception to this repo's hard-fail rule: an
unreachable collector, a missing dependency, or an exporter error must never
fail a request, so every failure here is swallowed and logged instead of
raised.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_initialized = False


def init_tracing() -> bool:
    """Register Phoenix tracing when configured; never raise.

    Returns True when tracing was activated by this call.
    """
    global _initialized
    if _initialized:
        return False
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
    if not endpoint or not endpoint.strip():
        logger.debug("PHOENIX_COLLECTOR_ENDPOINT unset; tracing disabled.")
        return False
    try:
        from phoenix.otel import register  # type: ignore[import-not-found]

        register(
            endpoint=endpoint,
            project_name=os.getenv("PHOENIX_PROJECT_NAME", "geopoliticai-expert"),
            auto_instrument=True,
        )
    except Exception as exc:
        logger.warning("Tracing disabled: %s", exc)
        return False
    _initialized = True
    return True
