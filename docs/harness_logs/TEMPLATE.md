---
harness: claude-code | opencode | copilot
command: rs-code-review
subject: <branch, plan stem, or stack slug>
branch: <branch the run worked on>
plan: <plan path, or none>
date: <YYYYMonDD>
status: in-progress | complete | halted
tier: <lightweight | standard | full | n/a>
started: <output of `date -Iseconds`>
ended: <output of `date -Iseconds`, written last>
---

# Run log — <subject>

One run log per run, in that run's directory under its harness. The layout for every command run is:

    docs/harness_logs/<harness>/<YYYYMonDD>_<slug>/<log-name>

`harness` is `claude-code`, `opencode`, or `copilot`; the dir is named `<YYYYMonDD>_<slug>`, the slug
being the run's topic (a branch name, plan stem, or stack slug); `<log-name>` keeps the command's own
suffix file name — `review.md`, `stack_review.md`, `stack_merge.md`, `stack_address_feedback.md`,
`loop.md` — and the two HTML outputs (`explainer.html`, `guidebook.html`) land in the same run dir.
A rerun on the same day appends a dated section inside that file; a rerun on a later day starts a new
`<YYYYMonDD>_<slug>` directory. The `rs-implement-plan` ledger is the exception: it lives in an undated
`docs/harness_logs/<harness>/<plan-filename-stem>/ledger.md` and is reused across days. This tree is
gitignored except this template.
Keep it terse: logging costs tokens.

## How to fill it in

- Write the header first. `harness` is the harness that **started** the log; later runs and other
  harnesses append, and their own headings name them.
- Every stage is one heading, exactly:
  `## <Stage> — <harness> (YYYY-MM-DD HH:MM–HH:MM)`
  Take both times from `date '+%Y-%m-%d %H:%M'`: one call when the stage starts, one when it ends.
  A model has no clock, so never guess a time. The stage name is the template section below.
- Never write token counts or cost. `scripts/log_metrics.py` reads them from the harness's own
  records and appends `## Metrics`.
- A command may add one optional section of its own, such as `## Findings`, when none of the four
  fits. Do not add more.
- The `rs-implement-plan` ledger (`docs/harness_logs/<harness>/<plan-stem>/ledger.md`) is exempt: its
  first line stays the plan path, and it has no header and no metrics table.
- The `rs-implement-loop` and `rs-prototype-loop` loop files
  (`docs/harness_logs/<harness>/<YYYYMonDD>_<slug>/loop.md`) are exempt the same way: no header and
  no metrics table.

## Pre-flight — <harness> (YYYY-MM-DD HH:MM–HH:MM)

What was checked before changing anything, and what was found.

## Actions — <harness> (YYYY-MM-DD HH:MM–HH:MM)

What was done, in order. Include the gate command and the tail of its real output.

## Outcome — <harness> (YYYY-MM-DD HH:MM–HH:MM)

The result, in a few lines.

## Follow-ups — <harness> (YYYY-MM-DD HH:MM–HH:MM)

What is left open, and why.

## Last step

Run `python3 scripts/log_metrics.py <this file>`. If it prints an error, continue.
