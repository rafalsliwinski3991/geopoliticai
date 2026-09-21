"""Editorial constants for the public site pages (unit 11).

The source spectrum is a verbatim copy of
`agentic_backend/src/agents/expert/consts/sources.py`'s `ALLOWED_DOMAINS` —
the web_backend may not import the agent library, so the drift is guarded by
`tests/pages/test_landing.py` instead of by code.
"""

from __future__ import annotations

from pages.roster_types import Band, _Roster

LANDING_SECTIONS = _Roster(
    bands=(
        Band(
            label="Left of center",
            slot="left",
            domains=(
                "theguardian.com",
                "nytimes.com",
                "washingtonpost.com",
                "npr.org",
                "vox.com",
                "thenation.com",
                "motherjones.com",
                "aljazeera.com",
                "dw.com",
                "brookings.edu",
            ),
            institutes=frozenset({"brookings.edu"}),
        ),
        Band(
            label="Center",
            slot="mid",
            domains=(
                "reuters.com",
                "apnews.com",
                "bbc.com",
                "bloomberg.com",
                "ft.com",
                "axios.com",
                "politico.com",
                "csmonitor.com",
                "france24.com",
            ),
            institutes=frozenset(),
        ),
        Band(
            label="Right of center",
            slot="right",
            domains=(
                "wsj.com",
                "economist.com",
                "nationalreview.com",
                "thedispatch.com",
                "washingtonexaminer.com",
                "reason.com",
                "foxnews.com",
                "aei.org",
                "hoover.org",
            ),
            institutes=frozenset({"aei.org", "hoover.org"}),
        ),
    ),
)
