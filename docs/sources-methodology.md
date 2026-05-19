# Source Curation Methodology

GeopoliticAI restricts every analyst lane's web search to a curated
allow-list of domains per infosphere (English / Polish). That allow-list
**is the ideological frame of the product** — who counts as "left",
"centrist", "right", or "people" is the single highest-stakes editorial
decision in the codebase. This document explains how those lists are
chosen, versioned, and reviewed.

## Where the lists live

- **Code:** `app/src/geopoliticai/config.py` — `ENGLISH_INFOSPHERE_SOURCES`
  and `POLISH_INFOSPHERE_SOURCES` dicts, keyed by lane.
- **Version:** `SOURCES_VERSION` constant in the same module
  (currently `2026-Q2`). Bump whenever a list changes.
- **Changelog:** `docs/sources-changelog.md` — append-only record of
  additions, removals, and reclassifications, with date and rationale.

## Selection criteria

For a source to be added to a lane, **all** of the following must hold:

1. **Self-identifies, or is widely classified, as fitting that lane.**
   We don't try to outsmart the public reputation of an outlet — if it
   is widely understood to be a left-wing think tank, it goes in `left`,
   regardless of any single article's framing.
2. **Publishes primary or near-primary analysis** (think tanks, research
   institutes, established opinion press). Aggregators and SEO farms are
   excluded — they wash out lane signal.
3. **Has a stable URL structure** that `site:domain.com` can effectively
   constrain (Brave Search restriction). Subreddits and Twitter feeds
   are excluded for this reason.
4. **Is reasonably reachable**: produces English-language (English
   infosphere) or Polish-language (Polish infosphere) content as its
   primary output.
5. **Is not on a deny-list** for verifiable hate-speech, repeated
   fabrication, or sanctioned-entity affiliation.

## Lane definitions

| Lane       | Working definition                                                                            |
| ---------- | --------------------------------------------------------------------------------------------- |
| `left`     | Sources understood as left-of-center on the contemporary political spectrum of the country.   |
| `centrist` | Sources understood as broadly centrist, internationalist, technocratic, or institutionalist.  |
| `right`    | Sources understood as right-of-center on the contemporary political spectrum of the country.  |
| `people`   | Sources representing on-the-ground civil society, grassroots, or non-elite perspectives.      |
| `fact`     | Sources used only by the fact-check stage — neutral newswires, dedicated fact-checking orgs.  |

Lanes are **not** symmetric — the goal is not "5 sources per side" but
representative coverage of each ideological pole in each infosphere.

## Review cadence

- **Quarterly review** of both lists by the maintainer team. Open as a
  GitHub Issue tagged `sources-review` at the start of each quarter.
- **Ad-hoc reviews** triggered by:
  - A user dispute (see below).
  - A maintainer flagging a source for fabrication, ownership change,
    or shift in editorial line.
  - A new infosphere being added (e.g. a third language).

## Dispute process

If a user or contributor believes a source is mis-classified or should
be added / removed:

1. **Open a GitHub Issue** titled `[sources] <outlet>: <one-line ask>`.
2. **State the lane and outlet**, the change requested, and at least
   one published reference supporting the classification (academic
   media-bias study, peer-reviewed analysis, the outlet's own
   self-description).
3. **A maintainer responds within 14 days** with one of:
   - Accepted — PR opened, `SOURCES_VERSION` bumped, changelog updated.
   - Declined — with reasoning, suitable for future re-litigation if
     evidence changes.
   - Deferred to the next quarterly review.
4. **PRs are required**, not just issue comments, for any code change.
   Sources are part of the policy surface and ship through the same
   review process as the referee block-list.

## Versioning

- `SOURCES_VERSION` is a string of the form `YYYY-Qn` (e.g. `2026-Q2`).
- The pipeline embeds `SOURCES_VERSION` in pipeline output (footer of
  the final report) so any cited analysis can be tied back to the
  exact source list in effect at the time.
- `docs/sources-changelog.md` records every change with date, version,
  outlet, lane, action (add / remove / reclassify), and rationale.

## Known caveats

- **The Polish list is smaller than the English list.** Patches that
  expand it (with sourcing) are welcome.
- **The `centrist` label is contested.** In some traditions "centrist"
  means status-quo institutionalism; in others it means a third way
  between two named poles. We use the first sense for now.
- **No lane covers radical-fringe sources.** This is deliberate —
  including QAnon-adjacent or accelerationist outlets to "balance"
  the spectrum would normalise content that fails criterion 5.
