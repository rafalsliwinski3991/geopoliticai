---
description: Build a throwaway prototype in a loop that ends when the user's verdict answers one question
argument-hint: "[brainstorm-path] <question>"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

Question: $ARGUMENTS

Build a throwaway prototype that answers one question, and loop until the user's verdict closes it. The arguments are the question, or a brainstorm path (`docs/brainstorming/*.md`) followed by the question: a settled decision or flag the prototype should test.

A prototype is throwaway code that answers a question. The question decides the shape:

- **Logic or state model** ("does this feel right?"): one self-contained HTML file or script with free-play buttons and guided cases that push the state through what is hard to reason about on paper, drivable by a non-developer.
- **Appearance** ("what should this look like?"): several radically different variants on one route, switched by a URL search param and a floating bottom bar, following the project's routing convention.

The loop file is `docs/harness_logs/<slug>-prototype/loop.md` (gitignored; `<slug>` is the question in two to four kebab-case words). It holds the definition of done and one entry per round. Trust it and `git log` over your recollection. If it already exists, read it and resume at Step 3.

---

## Step 1 — Clarify and define done

Ask before writing code. Use your harness's question tool, or a numbered chat list, and put every question in one round. Give each question a worked example and your recommended answer.

1. **The question.** One sentence, and which shape fits it, judged from the surrounding code.
2. **Definition of done.** The verdict that closes the loop, as a checklist. Each item names its owner: an agent check you run and show (a case whose printed state equals the expected state), or a user check only the user can give ("you drive cases A, B, C and say each result looks right", "you pick variant 2 or 3"). Include at least one user check, since the verdict is the user's.
3. **Cases or variants.** For logic: the cases to push through. For appearance: how many variants.
4. **Budget.** Maximum rounds (recommend 4).
5. **Keeping it.** Push the throwaway branch to origin when done?

Then restate the question, the checklist as a table (item, owner), and the budget. Wait for the user's explicit approval. The approved checklist is the loop's exit; only the user changes it afterwards.

If your harness has a goal or stop-condition feature (Claude Code: `/goal <condition>`), give the user the one-line condition to set, so the harness itself holds the loop open.

## Step 2 — Build the first version

Cut `prototype/<slug>` from the current branch. Then build:

1. Name the prototype so a casual reader sees what it is (`PROTOTYPE` in the file name and header) and place it next to the code it serves.
2. One command or a double click starts it; tell the user that line.
3. State lives in memory. A scratch file named "PROTOTYPE, wipe me" appears only when persistence is what the question checks.
4. The code is only as finished as running it requires: no tests, no abstractions, no error handling beyond what keeps it running.
5. After every action, or every variant switch, show the full relevant state.

## Step 3 — Loop

Repeat until the exit test passes:

1. Run it yourself on every agent check and quote the printed state.
2. Hand the user the run line and the user checks, and ask for their verdict on each in their own words.
3. Apply the user's changes with the smallest edits that satisfy them.
4. Log the round: what was shown, what the user said, what changed.

The loop exits when each agent check passed in this round and the user has confirmed each user check. Stop and ask the user when the budget is spent.

## Step 4 — Capture

1. Commit the prototype to its branch, with the question and the verdict in the commit message. It stays out of the main branch.
2. Write the verdict (the question, the answer, the evidence) into the brainstorm artifact when one was given.
3. Push the branch when the user asked in Step 1.
4. Report the verdict and the branch. Offer `/rs-implement-loop` to build the validated decision for real.
