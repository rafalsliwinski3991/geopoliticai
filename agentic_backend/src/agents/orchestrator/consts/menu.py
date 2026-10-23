"""Next steps menu and dynamic footer prompt constants."""

from __future__ import annotations

STATIC_NEXT_STEPS_MENU = (
    "**What next?**\n"
    "- Ask a follow-up (0 research turns)\n"
    "- Explore in depth with the deep research agent (4 research turns)\n"
    "- Generate a Delphi forecast (8 research turns)\n"
    "- Generate a comprehensive report (1 research turn)"
)

DYNAMIC_FOOTER_SYSTEM_PROMPT = """You are the orchestrator assistant. Based on the recent tool execution summary, output a short footer offering next steps to the user.
Follow this format:
**What next?**
- [Relevant follow-up or next action] (0 research turns)
- Explore in depth with the deep research agent (4 research turns)
- Generate a Delphi forecast (8 research turns)
- Generate a comprehensive report (1 research turn)

Keep it concise and relevant to the subject researched."""
