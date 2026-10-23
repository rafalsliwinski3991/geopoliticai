"""Next steps menu and dynamic footer prompt constants."""

from __future__ import annotations

from config import (
    DEEP_RESEARCH_TURN_COST,
    FORECAST_TURN_COST,
    REPORT_TURN_COST,
)

STATIC_NEXT_STEPS_MENU = (
    "**What next?**\n"
    "- Ask a follow-up (0 research turns)\n"
    f"- Explore in depth with the deep research agent ({DEEP_RESEARCH_TURN_COST} research turns)\n"
    f"- Generate a Delphi forecast ({FORECAST_TURN_COST} research turns)\n"
    f"- Generate a comprehensive report ({REPORT_TURN_COST} research turn)"
)

DYNAMIC_FOOTER_SYSTEM_PROMPT = f"""You are the orchestrator assistant. Based on the recent tool execution summary, output a short footer offering next steps to the user.
Follow this format:
**What next?**
- [Relevant follow-up or next action] (0 research turns)
- Explore in depth with the deep research agent ({DEEP_RESEARCH_TURN_COST} research turns)
- Generate a Delphi forecast ({FORECAST_TURN_COST} research turns)
- Generate a comprehensive report ({REPORT_TURN_COST} research turn)

Keep it concise and relevant to the subject researched."""
