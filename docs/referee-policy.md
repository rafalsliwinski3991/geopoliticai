# Referee Policy

This document is the **policy specification** for the referee node
(`app/src/geopoliticai/nodes/referee.py`). The referee is a quality gate
that short-circuits the pipeline before any claim reaches synthesis or
fact-checking. Because GeopoliticAI is a politically-loaded product,
the referee's rules are effectively a policy document — any change must
go through PR review, the same as any other policy change.

> **Pinned to commit:** the constants and routing rules below are the
> source of truth. The Python module is the implementation, and tests
> in `app/tests/` lock the contract. If implementation and this doc
> ever drift, the implementation is wrong and must be fixed.

## What the referee does

1. **Iterates every claim** produced by the four ideological lanes
   (`left`, `centrist`, `right`, `people`).
2. **Marks unsupported claims** — any claim whose `source_ids` list is
   empty after the analyst pass.
3. **Detects loaded language** — claim text containing any term in the
   block-list below (substring match, case-insensitive).
4. **Strips unsupported claims** from each lane's claim list before the
   downstream stages see it.
5. **Decides whether to block** the entire output (see thresholds below).

## Blocking thresholds

The referee sets `RefereeReport.blocked = True` if **any of these are true**:

| Condition                                          | Why we block                                                                 |
| -------------------------------------------------- | ---------------------------------------------------------------------------- |
| Any claim text contains a loaded term              | Zero tolerance — these terms dehumanise and have no place in our output      |
| 100% of incoming claims are unsupported            | Nothing remains to synthesise; surfacing nothing is better than guessing     |

When blocked, the graph routes to `referee_blocked_summary` instead of
`extract_claims_lane → cross_check_facts → compose_final`. The user
receives a transparent message explaining that the answer could not be
verified, in the request's language.

## Loaded-term block-list

Defined in `geopoliticai/nodes/referee.py` as the `LOADED_TERMS` tuple:

```
traitor
vermin
subhuman
enemy of the people
scum
filth
cockroach
parasite
degenerate
infestation
```

### Selection criteria

A term is added to this list only if **all** of the following hold:

1. It is a documented historical or contemporary dehumanising term, used
   to strip out-groups of personhood (genocide research, hate-speech
   monitoring literature).
2. It has no neutral political use in the languages we support
   (English, Polish) that we want to preserve — i.e. excluding it never
   blocks legitimate analysis.
3. It would not be picked up via simpler sentiment heuristics that
   downstream models already catch.

### Adding or removing a term

- File a PR that edits `LOADED_TERMS` **and** updates this list.
- Cite the linguistic / hate-speech reference that motivated the change.
- Get approval from at least one reviewer outside the original author.
- Add a regression test in `tests/unit_tests/` covering the term.

### Known limitations

- **Substring match** flags compound words that happen to contain the
  term as a substring. Acceptable trade-off (false-positives surface as
  user-facing blocks, which can be retried with rewording) given the
  zero-tolerance posture, but worth profiling if user reports come in.
- **English-only block-list**: the list is currently English-only.
  Polish-language equivalents are deliberately deferred until we have
  a native reviewer to vet them — a half-translated list is worse than
  none.

## Output format

When blocked, the referee emits a single synthesis paragraph:

- **Polish lead:** `Krotka odpowiedz: Brak wiarygodnej odpowiedzi...`
- **English lead:** `Short answer: A reliable answer cannot be provided...`

followed by counts of unsupported and loaded-language claims so users
can see *why* the output was blocked without being shown the offending
text itself.

## Audit trail

The referee report is preserved in `PipelineState.referee_report` for
the duration of a graph run. When LangSmith tracing is enabled
(`LANGSMITH_API_KEY` set), every block decision is captured with the
full input claims — use this to retro-audit drift in the block rate.
See `docs/observability.md` for the dashboard query.
