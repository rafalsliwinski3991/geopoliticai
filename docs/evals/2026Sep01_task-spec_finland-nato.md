# Finland NATO accession: offline evaluation task specification

**Status:** Review gate pending. This document records the proposed task and
evidence map; no human sign-off is claimed here.

## Task

Answer this question:

> Why did Finland abandon military non-alignment after Russia's 2022 invasion,
> and why was its NATO accession completed only in April 2023?

The case metadata is:

```text
case_id: finland_nato
expected_destination: geopolitical
rubric_version: finland-nato-usefulness-v1
evidence_cutoff: 2023-04-30
```

This is deliberately a two-part question: the first part asks for the
strategic cause of the policy shift, and the second asks for the accession
timing. The frozen evidence is an evidence map, not a golden answer. The
answer may legitimately emphasize different supported aspects while still
addressing both parts.

## Frozen corpus and provenance

The corpus contains twelve bounded, contiguous article passages. The passages
are stored under `app/evals/cases/finland_nato/corpus/` and are locked by
`corpus.lock.json`. The lock records each excerpt's SHA-256 text digest and a
corpus-level digest. `retrieved_at` is `2026-09-01` for every excerpt.

| Order | Publisher | Page-H1 title | Published | Domain | Access/provenance note |
| ---: | --- | --- | --- | --- | --- |
| 01 | Reuters | *Finland set to join NATO in historic shift while Sweden waits* | 2023-04-04 | `reuters.com` | Live Reuters was HTTP 401/bot-blocked; passage transcribed from a Wayback snapshot; canonical Reuters URL retained. |
| 02 | Associated Press | *Finland joins NATO in major blow to Russia over Ukraine war* | 2023-04-04 | `apnews.com` | Live AP exposed only navigation; passage transcribed from a Wayback snapshot; post-ceremony H1/title is intentional. |
| 03 | BBC News | *Nato's border with Russia doubles as Finland joins* | 2023-04-04 | `bbc.com` | Fetched live and fully accessible. |
| 04 | Reuters | *Finland to join NATO on Tuesday, Sweden still waiting* | 2023-04-03 | `reuters.com` | Live Reuters was HTTP 401/bot-blocked; passage transcribed from a Wayback snapshot; timing-half source. |
| 05 | Deutsche Welle | *Finland officially becomes a NATO member* | 2023-04-04 | `dw.com` | Fetched live and fully accessible. |
| 06 | Al Jazeera | *Finland joins NATO as Russia's war rages on in Ukraine* | 2023-04-04 | `aljazeera.com` | Fetched live; page H1 uses `rages on`, while the URL slug uses `grinds-on`. |
| 07 | The Christian Science Monitor | *Finland joins NATO, bolsters security across Euro-Atlantic region* | 2023-04-03 | `csmonitor.com` | Fetched live and fully accessible. |
| 08 | Vox | *Finland and Sweden's historic NATO bids, explained* | 2022-05-13 | `vox.com` | Fetched live and fully accessible; strongest strategic-cause explanation. |
| 09 | Vox | *How Turkey is ruining NATO's moment of unity* | 2023-02-04 | `vox.com` | Fetched live and fully accessible; page H1 title is intentional. |
| 10 | France 24 | *Finland joins NATO in historic shift prompted by Ukraine war* | 2023-04-04 | `france24.com` | Article body fetched live; a stray JS-rendered Page not found fragment appeared after the body; residual provenance risk. |
| 11 | Al Jazeera | *Finland's long-held neutrality is over. What next?* | 2023-04-06 | `aljazeera.com` | Fetched live and fully accessible; analytic pre/post-opinion emphasis. |
| 12 | NPR | *Finland joins NATO over Russia's objection* | 2023-04-04 | `npr.org` | Live NPR timed out; passage transcribed from a Wayback snapshot. |

No complete article is redistributed. Each JSON file contains only the supplied
bounded passage and a truncation/provenance note. The corpus is intentionally
over-full so the controlled retrieval cut is observable.

## Evidence map

### Supported claims

The frozen passages support the following claims when represented accurately
and with appropriate attribution:

- Russia's full-scale invasion of Ukraine in February 2022 changed Finland's
  security calculation and prompted its move away from decades of military
  non-alignment.
- Finland's earlier non-alignment is presented in the corpus alongside its
  history after the Soviet invasion/defeat in World War II and its effort to
  maintain relations with neighbouring Russia.
- Finland and Sweden applied for NATO membership together in May 2022, after
  fears of Russian aggression rose.
- NATO membership was framed as security under the alliance's collective
  defence umbrella; the corpus also describes Finland's long border with Russia
  and the resulting enlargement of NATO's frontier.
- Finland became NATO's 31st member in April 2023, with accession documents
  handed over and the Finnish flag raised at NATO headquarters.
- Turkey and Hungary delayed the wider accession process, while Turkey's
  ratification removed Finland's final hurdle and Sweden remained waiting.
- The accession was completed quickly, in under a year, and several passages
  describe it as the fastest process in NATO's recent or modern history. Such
  wording should retain its source attribution rather than become an
  unsupported universal claim.

### Prohibited claims

The answer and verifier context must not turn the evidence into claims it does
not establish. In particular, do not:

- invent a polling percentage, a Cabinet vote, a private agreement, or a
  military deployment that is not in the supplied passages;
- present one stated motive as the sole proven motive when the corpus supports
  security, historical, strategic, and diplomatic emphases;
- assert that Finland's accession guaranteed a particular later military
  outcome, or state when Sweden joined or will join;
- treat statements by Putin, Blinken, Stoltenberg, Biden, Russian officials, or
  other quoted actors as independently verified facts without attribution;
- resolve differences between descriptions such as “fastest in NATO's
  history” and “fastest in recent/modern history” by adding facts from outside
  the cutoff;
- fabricate article text, citations, URLs, excerpt identifiers, or source
  provenance, or imply that a bounded excerpt represents the remainder of its
  article.

### Legitimate disagreements

Multiple answers can be useful and faithful if they cover both parts. The
following emphases are legitimate alternatives rather than contradictions:

- the immediate security shock and deterrence rationale;
- the historical end of Finland's long-standing non-alignment and its
  relationship with Russia;
- the joint Finnish-Swedish application and the alliance-wide significance of
  the shift;
- the procedural explanation: ratification by all allies, Turkey's objections
  and eventual ratification, Hungary's delay, and the contrast with Sweden;
- the formal April 2023 ceremony and the speed of the accession process.

The answer may weigh Turkey's role, Hungary's role, or the Russian invasion
differently where the passages support that emphasis. It must not omit the
accession-timing half merely because it gives a stronger strategic explanation.

## Controlled adapter mapping

The controlled adapter maps the twelve frozen excerpts to `Candidate` records
in the exact corpus order 01 through 12. Each candidate carries the excerpt's
title, canonical URL, and bare domain. The adapter does not search, fetch, or
rewrite the text, and it does not change the order.

The intended sizing path is:

```text
12 frozen candidates, in corpus order
  -> RETRIEVAL.fetch_candidates = 10
  -> candidates 01–10 requested from the node
  -> RETRIEVAL.keep_sources = 8
  -> candidates/sources 01–08 retained
```

Candidates 09 and 10 are intentionally requested but dropped at the
`keep_sources` cut. Candidates 11 and 12 are outside the candidate cut and
must not be requested. The full twelve-excerpt corpus remains the judge's
combined context; the eight retrieved sources are the agent's observed
selection.

## Expected execution evidence

A valid successful run should make the following observable:

- `destination == "geopolitical"`;
- a non-empty rewritten/standalone query;
- at least one retrieved source, with retrieved URLs drawn from the frozen
  corpus and respecting the adapter cut;
- a non-empty answer addressing both question parts.

An agent failure, an empty answer, or a wrong route is a product observation for
the later evaluators; it is not silently converted into a corpus or evaluation
system failure.

## Verifier contract

The usefulness judge emits four criterion scores and an independently judged
overall verdict in one structured call. The four criteria are:

1. `answers_both_parts` — addresses both the strategic cause and April 2023
   accession timing;
2. `general_reader_clarity` — understandable without specialist knowledge;
3. `prioritization` — leads with the important causes and timing constraints;
4. `concision` — remains focused despite the over-full evidence map.

The overall verdict is the judge's `meets_usefulness_rubric` or
`does_not_meet_usefulness_rubric` label. It is not recomputed from the four
criteria. The grounding evaluator receives the answer and the complete
`combined_context(case)` string and reports the score named
`faithful_to_combined_context`. The route evaluator compares the observed
destination with `expected_route`, whose case value is `geopolitical`.

The following are evaluation-system outputs, not claims that the answer has
valid citations: usefulness criterion/verdict scores, faithfulness to the
combined frozen context, and expected-route agreement.

## Claim boundary

Validates the evaluation system, not GeopoliticAI's general geopolitical quality. Usefulness labels are the pinned judge's rubric verdicts, self-calibrated for repeatability only — not validated against human preference. The grounding score is faithfulness to the combined frozen context, not citation validity.

## Review checklist and maintainer sign-off

The following eight items are the required pre-implementation review. They are
intentionally unchecked until a maintainer reviews the task specification and
the complete corpus together:

- [ ] 1. Every excerpt is on an allow-listed domain and is real, transcribed,
      and bounded.
- [ ] 2. The corpus supports both halves of the question and supports more than
      one legitimate emphasis; it is an evidence map, not a golden answer.
- [ ] 3. The corpus is genuinely over-full; information overload is the chosen
      difficulty.
- [ ] 4. Supported claims, prohibited claims, and legitimate disagreements are
      enumerated in this specification for review and judge context, not code.
- [ ] 5. The controlled-adapter mapping is stated, including the exact order,
      `fetch_candidates = 10`, `keep_sources = 8`, and the 09–10 versus 11–12
      cuts.
- [ ] 6. Expected execution evidence is stated: geopolitical destination,
      non-empty rewrite, at least one retrieved source, and non-empty answer.
- [ ] 7. The verifier contract is stated: four usefulness criteria, overall
      verdict, `faithful_to_combined_context`, and `expected_route`.
- [ ] 8. The claim boundary is stated verbatim and limits the report to the
      evaluation system rather than general geopolitical quality.

**Maintainer:** ____________________
**Date:** ____________________
**Decision:** Pending review; no sign-off has occurred in this artifact.
