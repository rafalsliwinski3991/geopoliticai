---
description: Build a throwaway prototype in a loop that ends when the user's verdict answers one question
agent: build
model: opencode-go/glm-5.3-flash
---

Question: $ARGUMENTS

Build a throwaway prototype that answers one question, and loop until the user's verdict closes it. The arguments are the question, or a brainstorm path (`docs/brainstorming/*.md`) followed by the question: a settled decision or flag the prototype should test.

A prototype is throwaway code that answers a question. The question decides the shape:

- **Logic or state model** ("does this feel right?"): one self-contained HTML file or script with free-play buttons and guided cases that push the state through what is hard to reason about on paper, drivable by a non-developer.
- **Appearance** ("what should this look like?"): several radically different variants on one route, switched by a URL search param and a floating bottom bar, following the project's routing convention.

The loop file is `docs/harness_logs/opencode/<YYYYMonDD>_<slug>/loop.md` (gitignored; `<slug>` is the question in two to four kebab-case words). It holds the definition of done and one entry per round, and is exempt from `docs/harness_logs/TEMPLATE.md`: no header, no metrics table. Trust it and `git log` over your recollection. If it already exists, read it, check out the branch it records, and resume at Step 3.

---

## Step 1 — Clarify and define done

If a brainstorm path was given, read the artifact in full first, and carry its settled decisions and flags into the question, cases, and checks.

Ask before writing code. Use your harness's question tool, or a numbered chat list, and put every question in one round. Give each question a worked example and your recommended answer. If a brainstorm path was given and the file does not exist, stop and ask first.

1. **The question.** One sentence, and which shape fits it, judged from the surrounding code.
2. **Definition of done.** The verdict that closes the loop, as a checklist. Each item names its owner: an agent check you run and show (a case whose printed state equals an expected state written into this checklist), or a user check only the user can give ("you drive cases A, B, C and say each result looks right", "you pick variant 2 or 3"). Include at least one user check, since the verdict is the user's.
3. **Cases or variants.** For logic: the cases to push through. For appearance: how many variants.
4. **Budget.** Maximum rounds (recommend 4).
5. **Base and keeping it.** Ask explicitly for the base branch `prototype/<slug>` starts from (recommend the current branch). Push the throwaway branch to origin when done?

Then restate the question, the checklist as a table (item, owner, and the expected state of each agent check), the budget, and the base branch. Wait for the user's explicit approval. The approved checklist is the loop's exit; only the user changes it afterwards.

## Step 2 — Build the first version

Stop and ask if the working tree has uncommitted changes or `prototype/<slug>` already exists. Otherwise cut `prototype/<slug>` from the approved base branch. Create the loop file with the approved table, the budget, the branch name, and an empty round log. Then build:

1. Name the prototype so a casual reader sees what it is (`PROTOTYPE` in the file name and header) and place it next to the code it serves.
2. One command or a double click starts it; tell the user that line.
3. State lives in memory. A scratch file named "PROTOTYPE, wipe me" appears only when persistence is what the question checks.
4. The code is only as finished as running it requires: no tests, no abstractions, no error handling beyond what keeps it running.
5. After every action, or every variant switch, show the full relevant state.

## Step 3 — Loop

Repeat until the exit test passes:

1. Run it yourself on every agent check and quote the printed state next to the expected state.
2. Hand the user the run line and the user checks, and ask for their verdict on each in their own words.
3. Apply the user's changes with the smallest edits that satisfy them.
4. Log the round: what was shown, what the user said, what changed.

The loop exits when each agent check passed in this round and the user has confirmed each user check. Track which checklist items became satisfied in each round. When two consecutive rounds satisfy no new item, or the budget is spent, stop and ask the user to choose: extend the budget and continue; go to Step 4 with the verdict "inconclusive" and what was learned so far; or abandon, deleting the branch and recording nothing.

## Step 4 — Capture

1. Write the verdict (the question, the answer, the evidence) into the brainstorm artifact when one was given.
2. Stage only the prototype's own files, by path, and commit them to its branch, with the question and the verdict in the commit message. It stays out of the main branch.
3. Push the branch when the user asked in Step 1.
4. Report the verdict and the branch. Offer `/rs-implement-from-brainstorm-in-loop` to build the validated decision for real.
