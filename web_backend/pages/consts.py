"""Editorial constants for the public site pages (unit 11).

The source spectrum is a verbatim copy of
`agentic_backend/src/agents/expert/consts/sources.py`'s `ALLOWED_DOMAINS` —
the web_backend may not import the agent library, so the drift is guarded by
`tests/pages/test_landing.py` instead of by code.
"""

from __future__ import annotations

from pages.roster_types import Band, _Roster

# The service provider and GDPR controller named on /about/ and /privacy/.
OPERATOR = {
    "name": "Rafal Sliwinski",
    "address": "ul. Modrzewiowa 16/10, 21-040 Swidnik, Poland",
}

# The forecasters a forecast reads, copied from
# `agentic_backend/src/agents/deep_forecaster/consts/forecasters.py`'s
# `FORECASTERS` (name, focus, domains); drift is guarded by
# `tests/pages/test_landing.py`.
FORECASTERS = (
    {
        "name": "Krzysztof Wojczal",
        "focus": "structural realism and Atlanticism; long-range forecasts of conflicts "
        "involving Poland, Russia, NATO, the United States and China",
        "domains": ("krzysztofwojczal.pl", "youtube.com"),
    },
    {
        "name": "Charly Salonius-Pasternak",
        "focus": "small-state survival, total defence, Nordic-Baltic and transatlantic security",
        "domains": ("fiia.fi",),
    },
    {
        "name": "Mustafa Aydın",
        "focus": "middle powers; Turkey's multi-vector, transactional foreign policy",
        "domains": ("khas.edu.tr",),
    },
    {
        "name": "Efraim Inbar",
        "focus": "military deterrence and hard-realist strategy in the Middle East; Israel",
        "domains": ("jiss.org.il",),
    },
    {
        "name": "John Bew",
        "focus": "British statecraft, diplomatic history, nuclear policy",
        "domains": ("belfercenter.org",),
    },
    {
        "name": "Thomas Gomart",
        "focus": "great-power rivalry, geoeconomics, resources and supply chains; "
        "France and Europe",
        "domains": ("ifri.org",),
    },
    {
        "name": "Yan Xuetong",
        "focus": "great-power theory, US-China bipolarity, moral realism",
        "domains": ("tsinghua.edu.cn",),
    },
    {
        "name": "Alexander Gabuev",
        "focus": "Eurasian security; Russia's political and economic dependence on China",
        "domains": ("carnegieendowment.org",),
    },
    {
        "name": "Chaesung Chun",
        "focus": "East Asian security, nuclear deterrence, the Korean peninsula and "
        "Seoul's balance between the United States and China",
        "domains": ("eai.or.kr",),
    },
    {
        "name": "Kazuto Suzuki",
        "focus": "trade wars, geoeconomics, sanctions, semiconductors and resource blockades",
        "domains": ("instituteofgeoeconomics.org",),
    },
    {
        "name": "Brahma Chellaney",
        "focus": "resource conflicts, water geopolitics, India and China",
        "domains": ("project-syndicate.org",),
    },
    {
        "name": "Elizabeth Sidiropoulos",
        "focus": "the Global South, BRICS, Africa's resources and diplomacy",
        "domains": ("saiia.org.za",),
    },
)

LANDING_SECTIONS = _Roster(
    bands=(
        Band(
            label="Left of center",
            slot="left",
            domains=(
                "theguardian.com",
                "npr.org",
                "vox.com",
                "thenation.com",
                "motherjones.com",
                "aljazeera.com",
                "dw.com",
                "brookings.edu",
                "carnegieendowment.org",
                "ecfr.eu",
            ),
            institutes=frozenset({"brookings.edu", "carnegieendowment.org", "ecfr.eu"}),
        ),
        Band(
            label="Center",
            slot="mid",
            domains=(
                "bbc.com",
                "bloomberg.com",
                "csmonitor.com",
                "sipri.org",
                "csis.org",
                "cfr.org",
                "atlanticcouncil.org",
                "cnas.org",
                "swp-berlin.org",
                "osw.waw.pl",
                "warontherocks.com",
            ),
            institutes=frozenset(
                {
                    "sipri.org",
                    "csis.org",
                    "cfr.org",
                    "atlanticcouncil.org",
                    "cnas.org",
                    "swp-berlin.org",
                    "osw.waw.pl",
                }
            ),
        ),
        Band(
            label="Right of center",
            slot="right",
            domains=(
                "thedispatch.com",
                "reason.com",
                "foxnews.com",
                "aei.org",
                "hoover.org",
            ),
            institutes=frozenset({"aei.org", "hoover.org"}),
        ),
    ),
)
