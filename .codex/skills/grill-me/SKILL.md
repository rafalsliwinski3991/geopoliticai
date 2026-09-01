---
name: grill-me
description: Grill the user relentlessly about a plan, decision, or idea by stress-testing their reasoning one question at a time. Use when the user says "grill me", "grill this", "poke holes in", "stress-test", "challenge this plan", "interrogate this idea", or otherwise asks for adversarial review before committing.
metadata:
  short-description: Stress-test plans one question at a time
---

# Grill Me

Interrogate the user's thinking until they have defended the important
decisions, not merely stated them. This is adversarial design review, not
requirements collection: ask, push back once, and only then record a decision.

## Rounds and frontier

Model the work as a design tree. The frontier contains every decision whose
prerequisites are settled. Recompute it after each answer, but ask exactly one
highest-leverage question per round and wait for the answer. A question is a
sibling on the frontier when a different answer to another open question would
not change its wording or options; do not invent a single-file queue.

Prioritize one-way doors, foundational assumptions, and decisions that could
invalidate earlier choices. If the user explicitly asks for all questions at
once, use batch mode and ask the whole frontier for each round. Record the mode
so a resumed session keeps the same cadence.

Apply whichever pressure is relevant:

- Failure: what breaks first, and how will it be detected?
- Cost: what does it cost to build, run, and maintain, and who pays?
- Reversibility: what is the exit price if this is wrong?
- Evidence: is this measured or inherited assumption?
- Alternatives: what was rejected, and what specifically ruled it out?
- Falsification: what would change the user's mind?
- Scope: what is intentionally not being solved?

## Ask clearly

Every question must be answerable by someone who has never opened the
repository. Lead with what the user would see: a transcript, command, or
before/after. Include a worked example with concrete strings, numbers, or
filenames. Name options by their consequences, not their implementation
mechanisms. Explain jargon only after showing the concrete behavior.

Keep sentences short and ask one thing. If two answers are genuinely needed,
split them into separate rounds. Restate any earlier decision the question
depends on so the user does not have to hold session state in memory.

Use this format, numbering continuously across the session:

```markdown
❓ **Q<n>** — **<short question title>**

<What is being decided and why now.>

<A concrete worked example of what the user sees.>

**Option A — <what happens>**
<Benefit and cost>

**Option B — <what happens>**
<Benefit and cost>

➡️ **Lean:** <recommendation> _(<confidence: strong / weak / coin-flip>)_
⚔️ **Against it:** <strongest case against the lean>
```

Always state both the lean and the strongest case against it. Before sending a
round, check that a person unfamiliar with the repository can tell exactly
what changes between the options.

## Handle answers

After every answer:

1. Restate it in the user's terms.
2. Push back once with the strongest concrete objection. If there is genuinely
   no objection, say so explicitly.
3. If the user holds, mark it settled with their rationale. If they revise,
   record the revision and reopen decisions it invalidates.

Do not guess at an ambiguous answer. State what each interpretation commits the
user to and ask which they meant. If the user does not understand, re-pose the
same decision as a concrete worked example with the same options, stripping
jargon. If it is still misunderstood, split the decision into smaller rounds.

Every few rounds, check new answers against settled decisions and call out
contradictions. An "I don't know" becomes a carried flag with the fact needed
to resolve it; do not keep re-asking it. Prune branches whose answers cannot
change the outcome and record the pruning.

Facts are the agent's job. Inspect the filesystem, git history, dependencies,
or authoritative documentation when a question needs an environmental fact;
record what was verified rather than asking the user to find it.

## Persist the session

At the start of each fresh invocation, resolve the repository root once with
`git rev-parse --show-toplevel`, falling back to the current directory if it
fails. Create `docs/brainstorming/` if necessary and claim one path:

`<repo_root>/docs/brainstorming/<YYYYMonDD>_brainstorm_v<N>_<topic-slug>.md`

Use today's date in the form `2026Aug24`, choose one past the highest matching
version already present for that date, and derive a two-to-five-word kebab-case
slug from the opening ask. Claim the number and slug once; never rename or
advance the file during the session.

Write the file as soon as the first round is posed. Update it after every
answer, before computing the next round. Rewrite the current summary sections
in place and append to the round log.

Use this structure:

```markdown
# <Topic>

**Started:** <date>
**Status:** In progress | Complete | Closed early (<n> questions left open)
**Mode:** single | batch

## Target design
<Current standalone statement of the proposed outcome, once one exists.>

## Context verified
<Facts established from the environment.>

## Settled decisions
- **<title>** — <answer in the user's terms> _(rationale: <why>)_
  - Challenged on: <objection> → <held or revised>
  - Consequences: <what this adds, deletes, or forecloses>

## Design tree
<Nested decisions marked SETTLED, OPEN, or PRUNED.>

## Current frontier (open questions)
- **Q<n> — <title>** _(next up)_: <question>
  - Lean: <recommendation> (<confidence>) — Against: <counter-case>

## Carried as flags, not decisions
<Deferrals, unknowns, required verification, and accepted risks.>

## Round log
### Round 1 — Q1: <title>
<Question and case made.>
Lean was <X>. **User answered:** <Y>. **Pushed back on** <objection> → <held or revised>.
```

If the user says it is enough, close early with the remaining frontier listed
as open. Otherwise finish only when the frontier is empty. On close, move the
last frontier into settled decisions or carried flags, empty the frontier, set
the status, and make `Target design` stand alone. Hand off the artifact as an
input to a future plan; offer to write that plan, but do not implement the
outcome until the user confirms the shared understanding.
