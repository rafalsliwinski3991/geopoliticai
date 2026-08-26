---
name: grill-me
description: Grill the user relentlessly about a plan, decision, or idea - stress-test the thinking, not just collect requirements. Use when the user says "grill me", "grill this", "poke holes in", "stress-test", "challenge this plan", "interrogate this idea", or otherwise asks to have their reasoning attacked before they commit to it.
---

Interrogate the user until you reach a shared understanding they have *defended*, not merely stated. Map the space as a **design tree**: every decision branches into the decisions that hang off it.

This is not requirements gathering. A requirements interview asks, records, and moves on. You ask, **push back**, and only then record. An answer the user gave without resistance is not a settled decision — it is an untested one.

## Rounds and the frontier

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet.

Ask the whole frontier in one round, then wait for the user's answers before the next. Each round they answer reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round.

**The frontier should be wide.** A tree where every decision has exactly one child is a queue, not a tree, and it means you are inventing dependencies that aren't there. Before deferring a question to a later round, apply the dependency test: *would a different answer to the open question actually change this question's wording or its options?* If not, it belongs in **this** round as a sibling. Deferring on vague thematic relatedness is the most common way this skill degrades.

### Batch mode and single mode

Default to batch: the whole frontier per round. If the user asks for one question at a time — some people think better that way — switch to **single mode**: still compute the full frontier, still keep it in the file under Current frontier, but pose only the highest-leverage one per round. Record the mode in the artifact so a resumed session doesn't flip cadence mid-stream. You may offer to switch modes if the frontier gets unwieldy (roughly 6+ open questions), but the user's stated preference wins.

## What to grill on

Frontier questions come from the tree's structure. The *pressure* comes from these axes — draw on whichever bite for a given decision, and skip the ones that don't:

- **Failure** — what breaks first when this is wrong, and how would you find out?
- **Cost** — what does this cost to build, to run, and to maintain, and who pays it?
- **Reversibility** — one-way door or two-way? Price the exit before entering.
- **Evidence** — what is this belief actually based on? Measurement, or an assumption inherited from an earlier design?
- **Rejected alternatives** — what else was considered, and what specifically killed it? "We just didn't" is an open question, not an answer.
- **Falsification** — what would have to be true for you to change your mind? An answer with no such condition is a preference, so mark it as one.
- **Scope** — what is deliberately *not* being solved here, and is that stated anywhere?

## Round format

```
❓ **Q1** - **<question title>**: <question body, possibly multiple paragraphs, including any multiple-choice options>

➡️ **Lean:** <your recommended answer> _(<confidence: strong / weak / coin-flip>)_
⚔️ **Against it:** <the strongest case against your own lean>

---

❓ **Q2** - ...
```

Always give both lines. A recommendation offered alone anchors the user onto it, and a skill that anchors and never challenges is a confirmation machine. Stating your own lean's weakest point is what keeps the question honest. When your lean is weak or a coin-flip, say so plainly rather than manufacturing confidence.

## The challenge step

When the user answers, do **not** write it straight into Settled decisions. For each answer:

1. **Restate** it in one line, in their terms, so a misread surfaces now rather than three rounds later.
2. **Push back once.** Name the strongest objection you have — the failure it invites, the cost it hides, the assumption it rests on. Use the pressure axes above.
3. If they hold their position, it is **settled**. Record it with their rationale. If they revise, the revision is the answer — and check whether it invalidates anything already settled.

Push back once per answer, not indefinitely. You are stress-testing a decision, not filibustering it. Skip step 2 only when you genuinely have no objection — and when you skip it, say so explicitly ("no objection to this one") so silence is never mistaken for a challenge that happened.

**Watch for contradictions.** Every few rounds, re-read Settled decisions against the newest answers. When a new answer undermines an earlier one, say so and re-open the earlier decision rather than letting the artifact hold two incompatible commitments. Re-opened decisions go back on the frontier.

## Facts are your job, decisions are theirs

Finding *facts* is never the user's job. When a frontier question needs a fact from the environment — filesystem, git history, dependency versions, an API's actual limits — go find it yourself. Read the code, run the command, search the web. If the search is broad enough to be worth parallelizing and sub-agents are available in this session, dispatch one; otherwise just do it inline.

Don't block on it. A running lookup is an unsettled prerequisite, so only the questions downstream of it wait; ask the rest of the frontier now. Record what you verified in the artifact's **Context verified** section — the facts you established are half the value of the session, and they are what makes the settled decisions auditable later.

The *decisions* are the user's. Put each to them and wait.

## Pruning and stopping

A design tree spawns questions indefinitely, so an "empty frontier" needs discipline to ever arrive.

- **Prune branches that can't change the outcome.** If a question's answers all lead to the same work, say so and drop it. Note the pruned branch in the artifact so it doesn't look forgotten.
- **"I don't know" is a valid answer.** Don't re-ask it. Move it to **Carried as flags** with the fact that would resolve it, and continue.
- **Deliberate deferrals are not open questions.** "Decide at implementation time" is a settled decision to defer; record it as a flag.
- **The user can call it.** If they say it's enough, close the session with the frontier non-empty and mark the remaining questions as such under Status.

The session is done when the frontier is empty or the user closes it: every live branch visited, nothing silently assumed. Do not act on the outcome until the user confirms you have reached a shared understanding.

## Saving progress

The design tree is a durable artifact, not just conversation scrollback — persist it as you go so an interrupted session isn't lost.

**Every fresh session starts a brand new file.** "Session" means one invocation of this skill: even if it's the same day, same topic, or a conversation that grilled something else earlier, a new call into this skill always creates its own file rather than resuming, appending to, or overwriting a previous session's. Within a single session there is exactly **one** file — round after round updates it in place.

**Resolve the save path once, at the start of the session** (a fact to find, not to ask about): run `git rev-parse --show-toplevel` for the repo root; if that fails, fall back to the current working directory. The target file is:

```
<repo_root>/docs/brainstorming/<YYYYMonDD>_brainstorm_v<N>.md
```

- Date format matches `2026Aug24` (4-digit year, 3-letter capitalized month abbreviation, 2-digit day) — today's date.
- `<N>` picks out *this* session's file: list `<repo_root>/docs/brainstorming/` for files already matching today's date prefix and use one past the highest number found (start at `v1` if none exist today). Do this exactly once, at session start, so this session claims its own number even if others ran earlier the same day.
- Create the `docs/brainstorming/` directory if it doesn't exist.
- For the rest of *this* session keep writing to that claimed file, never advancing to `v<N+1>` mid-session.

**Write the file as soon as the first round is posed** — don't wait for answers before capturing the topic and the open questions — then update it after every round the user answers, before computing the next round.

Rewrite the sections above the round log in place; **append** to the round log rather than reconstructing it. By round fifteen the log is most of the file, and regenerating it every round wastes effort and invites drift in entries that are already final.

### File structure

```markdown
# <Topic / one-line description of what's being grilled>

**Started:** <date>
**Status:** In progress | Complete | Closed early (<n> questions left open)
**Mode:** batch | one question at a time

## Target design

<The current best statement of what's being built, once enough is settled to state one.
Rewritten as it firms up. Omit this section until it would say something.>

## Context verified

<Facts you established from the environment rather than from the user - code read,
commands run, versions checked, docs contradicted. Each one auditable later.>

## Settled decisions

- **<Decision title>** — <the answer, in the user's own terms> _(rationale: <why>)_
  - Challenged on: <the objection you raised> → <how it held or was revised>
  - <Consequences: what this deletes, adds, or forecloses>

## Design tree

<Nested list mirroring the branches explored - each decision, and the sub-decisions it
opened, marked SETTLED / OPEN / PRUNED.>

## Current frontier (open questions)

- **Q<n> — <title>**: <body>
  - Lean: <recommendation> (<confidence>) — Against: <counter-case>

## Carried as flags, not decisions

<Deliberate deferrals, "I don't know"s with the fact that would resolve them, things to
verify before implementation, and known accepted risks. These are not open questions;
they are decisions to decide later, and they must survive into whatever plan follows.>

## Round log

### Round 1
**Q1 — <title>.** <what you asked and the case you made>
Lean was <X>. **User answered:** <Y>. **Pushed back on** <objection> → <held / revised to Z>.
```

When the session closes, do a final pass: move the last frontier into **Settled decisions** (or into **Carried as flags** if the user closed early), empty **Current frontier**, set **Status**, and make sure **Target design** states the whole outcome standalone — someone should be able to act on the artifact without reading the round log.

Then hand off: the artifact is the input to a plan, not the plan itself. Offer to write one, and don't start implementing until the user confirms.
