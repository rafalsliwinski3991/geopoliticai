"""Progress copy the orchestrator's own nodes emit.

`config.py` holds tunable settings; this holds product surface, per the repo's
`consts/` rule. It lives beside the node that emits it rather than in `api.py`,
because the delivery layer no longer decides which label a branch deserves — it
forwards what the node said.

The payload is written whole, `"type"` included, because `api._generate` yields
it into an SSE frame verbatim. Everything here must therefore stay a hardcoded
literal: nothing model-produced or user-produced may ever reach this channel.
"""

SEARCH_PROGRESS = {
    "type": "progress",
    "node": "search_and_fetch",
    "label": "Searching and reading sources...",
}
