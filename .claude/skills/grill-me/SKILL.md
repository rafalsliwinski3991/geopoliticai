---
name: grill-me
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.

## Saving progress

The design tree is a durable artifact, not just conversation scrollback — persist it as you go so a session that gets interrupted isn't lost.

**Every fresh session starts a brand new file.** "Session" means one invocation of this skill: even if it's the same day, same topic, or resuming a conversation that grilled something else earlier, a new call into this skill always creates its own new file rather than resuming, appending to, or overwriting a previous session's file. Within a single session, though, there is exactly **one** file — round after round updates it in place.

**Resolve the save path once, at the start of the session** (this is a fact to find, not something to ask the user): run `git rev-parse --show-toplevel` to get the repo root; if that fails (not inside a git repo), fall back to the current working directory. The target file lives at:

```
<repo_root>/brainstorming/<YYYYMonDD>_brainstorm_v<N>.md
```

- Date format matches `2026Aug24` (4-digit year, 3-letter capitalized month abbreviation, 2-digit day) — today's date.
- `<N>` picks out *this* session's file: list `<repo_root>/brainstorming/` for files already matching today's date prefix, and use one past the highest number found (start at `v1` if none exist today). Do this exactly once, at session start, so this session claims its own number even if other sessions ran earlier the same day.
- Create the `brainstorming/` directory if it doesn't exist.
- For the rest of *this* session, keep writing to that same claimed file — updated in place round over round, never advancing to `v<N+1>` mid-session. The version only advances again when the *next* fresh session starts.

**Write an initial version of the file** as soon as the first round is posed (don't wait for an answer to exist before the topic and open questions are captured), then **overwrite it again after every round the user answers**, before computing and asking the next round. Structure the file as:

```markdown
# <Topic / one-line description of what's being grilled>

**Started:** <date>
**Status:** In progress | Complete

## Settled decisions

- **<Decision title>** — <the answer the user gave, in their own terms> _(rationale: <why, if it matters>)_
- ...

## Design tree

<nested list mirroring the branches explored so far — each settled decision, and the
sub-decisions it opened up, whether those are settled or still open>

## Current frontier (open questions)

- **Q<n> — <question title>**: <question body>
  - Recommended: <your recommended answer>
- ...

## Round log

### Round 1
<questions asked, and the user's answers, once given>

### Round 2
...
```

When the frontier empties and the user confirms shared understanding, do one final overwrite: move the last frontier into **Settled decisions**, clear **Current frontier**, and flip **Status** to `Complete`.
