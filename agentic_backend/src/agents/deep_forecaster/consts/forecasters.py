"""The forecasters whose own writing the scouts collect (brainstorm 2026Sep30 Q2, Q8, Q15).

From `tmp/pl/geopolitical_forecasters.md`: who they are, where they publish,
and what they cover. The list's strengths and weaknesses are the operator's
notes and reach no agent (Q8); council members never see this list at all
(Q2). Carlo Masala publishes only on X, which has no route yet (Q17), so he
is not here; the list names no X handles. Brahma Chellaney's column is at
project-syndicate.org (F9). `search_name` is prefixed to every query, so an
institution's site returns that person's pages; `language` is what the scout
queries in.
"""

from __future__ import annotations

from dataclasses import dataclass

from models import SourcePolicy

# Pages here are videos, read by `ask_video`, never by `read_sources`.
VIDEO_DOMAINS: frozenset[str] = frozenset({"youtube.com"})


@dataclass(frozen=True)
class Forecaster:
    """One forecaster, as the lead chooses them and a scout searches them."""

    id: str
    name: str
    search_name: str
    focus: str
    language: str
    domains: tuple[str, ...]


FORECASTERS: tuple[Forecaster, ...] = (
    Forecaster(
        "wojczal",
        "Krzysztof Wojczal",
        "Wojczal",
        "structural realism and Atlanticism; long-range forecasts of conflicts "
        "involving Poland, Russia, NATO, the United States and China",
        "Polish",
        ("krzysztofwojczal.pl", "youtube.com"),
    ),
    Forecaster(
        "salonius_pasternak",
        "Charly Salonius-Pasternak",
        "Salonius-Pasternak",
        "small-state survival, total defence, Nordic-Baltic and transatlantic security",
        "English",
        ("fiia.fi",),
    ),
    Forecaster(
        "aydin",
        "Mustafa Aydın",
        "Mustafa Aydın",
        "middle powers; Turkey's multi-vector, transactional foreign policy",
        "English",
        ("khas.edu.tr",),
    ),
    Forecaster(
        "inbar",
        "Efraim Inbar",
        "Efraim Inbar",
        "military deterrence and hard-realist strategy in the Middle East; Israel",
        "English",
        ("jiss.org.il",),
    ),
    Forecaster(
        "bew",
        "John Bew",
        "John Bew",
        "British statecraft, diplomatic history, nuclear policy",
        "English",
        ("belfercenter.org",),
    ),
    Forecaster(
        "gomart",
        "Thomas Gomart",
        "Thomas Gomart",
        "great-power rivalry, geoeconomics, resources and supply chains; France and Europe",
        "English",
        ("ifri.org",),
    ),
    Forecaster(
        "yan",
        "Yan Xuetong",
        "Yan Xuetong",
        "great-power theory, US-China bipolarity, moral realism",
        "English",
        ("tsinghua.edu.cn",),
    ),
    Forecaster(
        "gabuev",
        "Alexander Gabuev",
        "Gabuev",
        "Eurasian security; Russia's political and economic dependence on China",
        "English",
        ("carnegieendowment.org",),
    ),
    Forecaster(
        "chun",
        "Chaesung Chun",
        "Chaesung Chun",
        "East Asian security, nuclear deterrence, the Korean peninsula and "
        "Seoul's balance between the United States and China",
        "English",
        ("eai.or.kr",),
    ),
    Forecaster(
        "suzuki",
        "Kazuto Suzuki",
        "Kazuto Suzuki",
        "trade wars, geoeconomics, sanctions, semiconductors and resource blockades",
        "English",
        ("instituteofgeoeconomics.org",),
    ),
    Forecaster(
        "chellaney",
        "Brahma Chellaney",
        "Chellaney",
        "resource conflicts, water geopolitics, India and China",
        "English",
        ("project-syndicate.org",),
    ),
    Forecaster(
        "sidiropoulos",
        "Elizabeth Sidiropoulos",
        "Sidiropoulos",
        "the Global South, BRICS, Africa's resources and diplomacy",
        "English",
        ("saiia.org.za",),
    ),
)
FORECASTERS_BY_ID: dict[str, Forecaster] = {f.id: f for f in FORECASTERS}

# The union of every forecaster's domains. A search narrows it to one
# forecaster (`tools.forecaster_policy`); reads are checked against all of it.
FORECASTER_SOURCES = SourcePolicy(
    allowed_domains=tuple(domain for f in FORECASTERS for domain in f.domains),
    batches=tuple(f.domains for f in FORECASTERS),
    deferred_domains=frozenset(),
    max_per_domain=10,
    min_source_chars=500,
    max_source_chars=20_000,
)
