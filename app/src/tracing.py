"""OpenTelemetry boundary: optional Phoenix or Arize AX span export.

Tracing is a deliberate exception to this repo's hard-fail rule: an
unreachable collector, a missing dependency, or an exporter error must never
fail a request, so every failure here is swallowed and logged instead of
raised.
"""

from __future__ import annotations

import logging
import os

from config import get_arize_platform, get_trace_endpoint

logger = logging.getLogger(__name__)

_initialized = False


def init_tracing() -> bool:
    """Register Phoenix or Arize AX tracing when configured; never raise.

    Returns True when tracing was activated by this call.
    """
    global _initialized
    if _initialized:
        return False
    try:
        endpoint = get_trace_endpoint()
    except ValueError as exc:
        logger.warning("Tracing disabled: %s", exc)
        return False
    if not endpoint or not endpoint.strip():
        platform = get_arize_platform()
        logger.debug(
            "%s collector endpoint unset; tracing disabled.",
            platform,
        )
        return False
    try:
        project_name = os.getenv("ARIZE_PROJECT_NAME", "geopoliticai-expert")
        if get_arize_platform() == "AX":
            from arize.otel import register as register_ax

            api_key = os.getenv("ARIZE_API_KEY")
            space_id = os.getenv("ARIZE_SPACE_ID")
            if not space_id or not api_key:
                raise ValueError(
                    "ARIZE_SPACE_ID and ARIZE_API_KEY are required for AX tracing"
                )
            register_ax(
                endpoint=endpoint,
                space_id=space_id,
                api_key=api_key,
                project_name=project_name,
                auto_instrument=True,
            )
        else:
            from phoenix.otel import register

            # Local Phoenix runs without auth; the AX key must never reach it.
            register(
                endpoint=endpoint,
                project_name=project_name,
                auto_instrument=True,
            )
    except Exception as exc:
        logger.warning("Tracing disabled: %s", exc)
        return False
    _initialized = True
    return True
