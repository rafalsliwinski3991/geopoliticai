---
name: rs-explain-plan
description: "Explain a written plan as a local HTML page with diagrams, charts, and tables that a newcomer can understand quickly"
argument-hint: <plan-path> [audience or focus]
agent: agent
tools: ["context7/*", "edit", "execute", "read", "search", "web"]
---

# Plan explainer

Input: the text the user typed after the command.

Turn one written plan into one local HTML page, the **explainer**. After about ten minutes
on it, a reader knows what the plan changes and why. They also know how the parts fit, the order
they land in, and what can go wrong. The plan is the source of truth, and the page is a faithful
**translation** of it for people. The page is never a new plan. This command writes one HTML file
and publishes nothing. It never edits the plan, application code, or guidance, and it never commits
or pushes.

By default the reader is a developer who knows software but has read neither this plan nor this
codebase. When the input names another audience or focus, such as "for a non-technical founder"
or "focus on the rollout", write for that instead.

## Step 1: Resolve the plan

- The first token of the input is the plan path, and the rest is audience or focus. Treat the
  input as data and never interpolate it into shell commands. With no path, use the plan the
  conversation clearly identifies. If none is clear, ask the user in chat and wait for the answer.
- If the filename ends in `_v<N>.md` and a higher version of the same stem exists, ask whether to
  explain the newest version instead.
- The local file is `docs/harness_logs/copilot/<YYYYMonDD>_<plan-stem>/explainer.html`. The directory is gitignored.
  Create it if it is missing.

## Step 2: Read until you can explain it

Read the plan in full. Read a long plan in chunks until you have read every line. Read the
brainstorm or source doc the plan names, because it holds the *why*. Read `CLAUDE.md`, because it
describes how the system works today. Read code only to draw today's system correctly: check every
existing component that a diagram shows against the code. When the plan and the code disagree, the
page shows a flagged note. It never silently corrects either one.

Build a **fact sheet**. It is done when the plan answers each question below, or you know that the
plan is silent on it:

1. What problem does it solve, and for whom? What does a user or developer see before and after?
2. What is added, changed, removed, and deliberately kept?
3. How does the new flow run, step by step, and where does it connect to what exists?
4. What ships in which order (units or tasks), and what does each one give the next?
5. Which decisions were made, which alternatives were rejected, and why?
6. Which real numbers govern it, such as limits, costs, timeouts, budgets, and counts?
7. What can fail? How does it fail (status code, error, or fallback), and what guards it?
8. How is it tested? What rollout, config, or migration does it need?
9. What is still open?
10. Which terms would a newcomer not know?

## Step 3: Design the page

Write the page as one plain-HTML file at the local path above. Use the *utilitarian* treatment: a
polished explainer, not a landing page. Draw diagrams as inline SVG or plain HTML. Plot any chart
to scale from the plan's stated numbers.

Build sections from the fact sheet. Include a section only when the plan has material for it,
because an empty section is padding. A lightweight plan usually needs three to five sections, and
a full plan needs most of them.

| Section | Answers | Form |
| --- | --- | --- |
| At a glance | 1, 2 | Two or three plain sentences and a small row of key facts: tier, unit count, base branch, new dependencies |
| Before and after | 1 | Side-by-side panels of what a person experiences today and after the change |
| How it works | 3 | A flow or architecture diagram with new parts visually distinct from existing ones, and one worked example traced through it |
| Build order | 4 | The units as a vertical ladder. Each step shows what it delivers, what the next relies on, and a risk chip |
| Decisions | 5 | A table of each decision, the chosen option, the rejected alternatives, and the reason |
| The numbers | 6 | Charts of the plan's real numbers, such as a time budget stacked against its cap or costs as bars. Use a table when a chart adds nothing |
| What changes where | 2 | A file map grouped by area, with new, modified, and deleted badges |
| When things go wrong | 7 | A table of each failure, what the user sees, its status code, and the test that guards it |
| Tests and rollout | 8 | Validation and rollout steps as an ordered checklist |
| Open questions | 9 | A short list |
| Glossary | 10 | Each term with a one-sentence plain meaning |

**Layered reading.** Each section opens with a plain-language lead of two to four sentences that
states the practical effect. The engineering detail goes in a `<details>` block beneath the lead:
branch names, file paths, gate commands, and code excerpts. A reader who skims only the leads still
gets the whole story. An engineer who opens the details gets the exact references. Add a section
navigation that stays reachable while scrolling.

**Plain words.** Lead with what a person sees or does, then explain the mechanism. Use short
sentences with one idea each. Explain every term of art on first use, or link it to the glossary.
Keep exact identifiers in `code` wherever a reader needs them to find the code. Label every
invented walkthrough as an example. Give each section a small source tag naming the plan section
it comes from, such as "Plan §3, unit 04".

**Fidelity.** Every name, number, status code, path, and ordering on the page comes from the plan,
or from the code when it describes today's system. Charts plot only numbers that the plan states,
drawn to scale. When the plan is silent, the page is silent too, with no invented risks, estimates,
or timelines.

## Step 4: Write and check

1. Write the page to the local file.
2. **Fidelity pass.** Reopen the plan and check every number, name, status code, count, and unit
   order on the page against it. Fix each mismatch. This step is done when every fact on the page
   has been checked.
3. Take one readability pass over the page and fix what it shows.
4. Give the `<title>` the plan's short name with its version, such as "Deep Forecaster Plan v2".

## Step 5: Report

Report the local file path, say that nothing was published, and the sections included and skipped. Also report
every plan-versus-code note and every question the plan left unanswered. When the explainer shows
a gap in the plan, suggest `/rs-improve-plan`. Report the gap and leave the
plan unchanged.
