"""Fixed user-facing copy for the reporter branch.

`config.py` holds tunable settings; this holds product surface. The refusal in
particular is what most users will see first (brainstorm Q5), so it teaches the
two-step workflow rather than only reporting a failure.
"""

NO_MATERIAL_NOTICE = (
    "I can only build a report from research already in this conversation, and "
    "there is none here yet. Ask me about the subject first — for example "
    "\"What is happening on NATO's eastern flank?\" — and once I've answered "
    "with sources, ask me for the report."
)

CANCELLED_NOTICE = "Dropped the report. The conversation is unchanged."

REVISION_CAP_NOTICE = (
    "That's as many outline revisions as I'll make in one go, so I've stopped "
    "here without writing the report. Ask me for the report again and I'll "
    "start from a fresh outline."
)
