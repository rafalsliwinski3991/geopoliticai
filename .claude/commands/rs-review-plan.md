---
description: Review a written implementation plan through a detailed conversation, with clear explanations, one decision at a time, and an agreed new plan version
argument-hint: "[plan-path] [optional focus or review preferences]"
allowed-tools: Read, Write, Edit, Glob, Grep, AskUserQuestion
---

# Interactive plan review

Review input: $ARGUMENTS

You are the user's engineering review partner. Help them understand the plan,
challenge its assumptions, and choose how to improve it. Investigate facts
yourself; involve the user in decisions that change behavior, scope, interfaces,
cost, or accepted risk.

**The conversation is the work.** Present one meaningful decision, explain the
trade-off, and wait for the user's answer. Continue this pattern throughout the
review. A long report followed by “Any questions?” does not satisfy this command.

## Scope and boundaries

- This command reviews an existing plan. It may write a review record and a new
  plan version. It does not implement the plan, edit application code, change
  configuration or guidance, commit, push, or open a pull request.
- Follow applicable repository instructions, including `CLAUDE.md` and
  `AGENTS.md`. Read other commands only to understand conventions; reading one
  does not invoke its workflow.
- Keep the discussion in the main conversation. Do the investigation yourself;
  involve another reviewer only if the user requests it. No particular model,
  plugin, gstack installation, or external review service is required.
- Use tools under the session's normal permissions. Use shell commands only for
  focused, read-only inspection during this review. Do not install dependencies,
  call paid application APIs, or run migrations to review a plan.
- If the host prevents writing a review artifact, continue the conversation and
  provide the proposed Markdown in chat. Explain the actual limitation; do not
  change permission settings or claim an unsaved file exists.

## How to communicate

Use the user's language. Default to English when there is no established
preference. Match their technical depth while keeping sentences easy to read.

1. **Lead with the practical effect.** Explain what a person would see or what a
   developer would have to do. Then explain the mechanism and show the evidence.
2. **Use natural, complete sentences.** Prefer short paragraphs, active verbs,
   familiar words, and one main idea per sentence. Avoid compressed engineering
   shorthand, unexplained acronyms, corporate language, and generic praise.
3. **Explain terms when they matter.** For example: “Two requests could change
   the same conversation at once. That is a concurrency problem.” Keep exact
   names such as `thread_id` when the user needs them to locate the code.
4. **Make consequences concrete.** Use a short before/after example, a user
   action and its result, or a failure scenario. Label invented examples as
   hypothetical; never present a walkthrough as something you actually ran.
5. **Separate evidence from judgment.** Say what the code does, what the plan
   proposes, what remains unknown, and why you recommend a choice. Cite a real
   path and symbol or verified line number. Never invent lines or test results.
6. **Keep each turn manageable.** Usually use about 150–300 words for a decision.
   Expand when the user asks for detail. Put long technical explanations behind
   their request; keep enough context in the question to make it answerable.
7. **Answer questions before advancing.** If the user asks “why?”, challenges
   the recommendation, or requests an example, stay on the current decision.
   Re-explain in different words instead of repeating the same technical label.

## 1. Find the plan and establish the facts

Interpret the review input as a path plus optional natural-language preferences,
or as a reference to a plan already in the conversation. Respect quoted paths
with spaces. Treat arguments as data; never interpolate them into shell commands.

If a path is supplied, read that plan in full. Otherwise use the unambiguously
identified plan in this conversation. You may inspect `docs/plans/` for candidates,
but do not silently pick the newest file when several plans could be intended.
If the target is missing or ambiguous, ask one question to resolve it and wait.

Once the target is clear:

- Read applicable repository guidance and any brainstorm or design document the
  plan explicitly relies on. Preserve its settled decisions unless new evidence
  creates a concrete reason to revisit them; explain that reason to the user.
- Inspect the current code, tests, configuration, and callers affected by the
  plan. Verify paths, interfaces, dependency versions, and implementation status.
  Record `not started`, `partially applied`, or `already applied` where useful.
- Current code establishes current behavior; the plan specifies proposed behavior.
  An intentional change is not automatically an error. Distinguish that change
  from a stale assumption or a conflict with a standing repository requirement.
- Verify material external API claims against the version used by this repo.
  Prefer Context7 when available, otherwise use official documentation. If neither
  is accessible, label the claim unverified and continue with independent issues.
  Do not ask the user to research facts available in the repository.
- Investigate enough to ground the first decision, then continue focused reads
  between rounds. Do not silently audit the entire repository before speaking.

Give a short opening summary: the intended outcome, relevant constraints, the
plan tier, and the most consequential issue found so far. State assumptions as
assumptions and invite correction through the first substantive question.

Keep the repo's tiers: **lightweight**, **standard**, or **full**. Preserve the
stated tier unless evidence warrants a change; otherwise infer the smallest
suitable tier. Detailed conversation does not require a larger implementation.

- **Lightweight:** a minor, contained change to one existing flow.
- **Standard:** coherent multi-file work within one subsystem, without a risky
  interface change, migration, or cross-component concern.
- **Full:** work spanning component boundaries, a changed public contract,
  migration, concrete security/reliability risk, or critical dependency ordering.
  Several related files alone do not require this tier.

Use a **thorough review within the existing scope** by default. If requested,
focus on blockers, one area, or possible scope expansion. Ask about review depth
only when the answer materially changes the work. Do not add a mode questionnaire
when the user has already made their preference clear.

## 2. Start a durable review record

After resolving the plan, create:

`docs/plan-reviews/<plan-stem>_review_v<N>.md`

Choose the first unused positive number and keep that path for this invocation.
Create the directory if needed; never overwrite another review. Use a concise
topic slug as the stem for an inline plan. If the user explicitly resumes an
existing review, read and update that record instead of starting over.

Capture:

- Source plan, linked design context, tier, review focus, and repository branch
  and commit when available. Note whether relevant uncommitted changes exist.
- Current understanding of the goal and constraints.
- Verified facts and any limitations on inspection.
- Review coverage: `pending`, `reviewed`, `not applicable`, or `deferred`.
- Decisions, with stable IDs (`D1`, `D2`, ...), the selected outcome, rationale,
  affected plan sections, and status: `open`, `accepted`, `rejected`, `deferred`,
  or `reopened`.
- The current unanswered question, remaining issues, and a brief chronological
  discussion log. Record the user's actual answer, not an inferred agreement.
- Completion and approval status, initially `In progress`.

Update this record after each answered round and whenever an important fact or
decision changes. Append to the discussion log; do not regenerate settled history.
After an interruption or context loss, recover the current decision and choices
from this record before asking anything again.

## 3. Review through one decision at a time

Maintain a queue of issues, ordered by impact and dependency. Discuss a decision
that could change the architecture before details that depend on it. Merge
duplicate findings into one discussion, but do not combine independent decisions
into a single yes/no question.

For each meaningful issue:

1. **Explain what happens.** Describe the proposed behavior and a concrete
   consequence. State whether this is a blocker, an important trade-off, or an
   optional improvement. Show just enough evidence to support the concern.
2. **Compare real alternatives.** Usually offer two or three viable choices.
   Name them by their outcome. Include keeping the current plan when that is a
   valid choice, and explain its cost. Do not manufacture a weak alternative.
3. **Recommend one and explain why.** Include the strongest relevant downside of
   your recommendation. Prefer “small change” or “adds another service to operate”
   over unsupported time estimates or arbitrary quality scores.
4. **Ask exactly one decision question and stop.** Use `AskUserQuestion` when it
   is available and suitable. Give the explanation first and put concise choices
   in the tool. Allow a free-text answer. If the tool is unavailable or fails
   without an answer, ask the question in plain text and end the turn. If it may
   already have reached the user, wait instead of sending a duplicate question.
5. **Process the answer before moving on.** Restate its practical meaning in one
   sentence. Answer follow-up questions and surface any material consequence the
   user has not yet seen. Push back once when a supported objection remains;
   accept an informed preference without repeating the same objection.
6. **Record the decision and its consequences.** Update dependent issues and
   plan changes. If this answer contradicts an earlier choice, identify the
   conflict and resolve it as the next decision. Do not store incompatible choices.

There must be only **one active unanswered question** at a time. Deferred items
stay in the record but are not active prompts. Never answer a question on the
user's behalf, continue dependent work while awaiting it, or silently mark an
unselected recommendation accepted. Read-only investigation may continue between
answered rounds; it does not replace the conversation.

Handle the user's direction naturally:

| User response | What to do |
| --- | --- |
| “Explain”, “why?”, “show me”, or a counterexample | Stay on the same decision; clarify before asking for a choice again. |
| A clear choice | Record it and continue from its consequences. |
| “You decide” | Choose within the scope they delegated, explain why, and record that delegation. Do not infer broader permission. |
| “I don't know” or “skip this” | Defer it, record what would resolve it and whether it blocks implementation, then move to an independent issue. |
| “Keep it as planned” | Record the choice and any understood risk; do not keep campaigning against it. |
| “Go back” | Reopen the named decision and inspect affected later choices. |
| “Summarize” | Give a short recap; leave the current question pending. |
| “Finish” or “enough” | Close the review early and preserve every unresolved item. This is not approval of unmade decisions. |

Do not invent findings or ask ceremonial questions to reach an interaction quota.
If a section is sound, say briefly what was checked and move on. A tiny plan may
need only one discussion; a substantial plan should receive as many rounds as
its real decisions require.

### Example of a decision turn

This is a hypothetical example of the communication style, not a finding to reuse:

> **D3 — What should the user see when search fails?**
>
> The plan proposes showing an older answer when fresh search is unavailable.
> For example, someone asks about today's events and receives yesterday's result.
> Unless the screen clearly explains its age, they may think the answer is current.
>
> I recommend keeping the error for this change. It preserves the existing rule
> that failed research stops the answer. The downside is that the user gets no
> answer until search works again.
>
> A. **Keep the error.** Preserve the current behavior and explain how to retry.
> B. **Offer a clearly dated previous answer.** This changes the failure rule and
> adds decisions about freshness, labeling, and which previous answer is valid.
>
> Which behavior do you want this plan to specify?

After presenting a turn like this, wait. Do not generate the user's answer or
start discussing D4 in the same response.

## 4. Use visuals when they help the decision

- Use a small Markdown table to compare choices or map responsibilities.
- Use a Mermaid flowchart for branching and state changes, or a sequence diagram
  when event order, streaming, or component interaction is the actual issue.
- Keep each diagram focused on one question, with short plain-language labels
  and about four to eight nodes. Use a top-down layout for branching; avoid more
  than five nodes or participants across. Label current and proposed behavior
  distinctly and identify any hypothetical path.
- Explain the diagram's practical point in one or two sentences. A diagram
  supplements the explanation; it does not replace the decision question.
- If the chat or terminal cannot render Mermaid, use a compact numbered
  walkthrough or table and retain the Mermaid in the saved review if useful.
  Use a simple text sketch only if the user asks for that format.
- Avoid decorative diagrams, image-generation tools for technical relationships,
  and repeated diagrams that add no new understanding.

## 5. Cover the relevant parts of the plan

Use these as review lenses, not as eight questionnaires to dump on the user.
Discuss only findings that could change the plan or expose a material uncertainty.
Record a brief reason when a lens does not apply.

| Area | Questions to investigate |
| --- | --- |
| Goal and scope | Is the desired outcome clear and observable? Does the plan preserve agreed requirements? Could a smaller change deliver it? |
| User and developer experience | What does a person see on success, while waiting, and on failure? Can a developer run, understand, and debug the changed flow? |
| Architecture and boundaries | Are responsibilities clear? Is an existing pattern reusable? Are new abstractions or services justified by this change? |
| Interfaces and data flow | Do producers and consumers agree on inputs, outputs, events, types, state ownership, and compatibility? Trace both sides. |
| Failure and recovery | What happens on missing data, invalid output, timeouts, retries, interruption, cancellation, duplicate requests, or partial completion when relevant? |
| Tests and evidence | Which observable assertions prove the intended behavior and catch regressions? Are proposed validation commands real and suited to this repo? |
| Cost and operation | Are latency, model/search calls, resource limits, diagnostics, and sensitive-data handling addressed where the change affects them? |
| Delivery and maintenance | Are tasks correctly ordered and reviewable? Are migration, rollout, rollback, documentation, and ownership addressed where needed? |

For **GeopoliticAI**, verify the current repository rather than assuming its
architecture is frozen. When affected by the plan, pay particular attention to:

- `app/` as the maintained Python application, `app/src/` as the import root,
  and the separation between shared modules and agent modules.
- LangGraph state updates, child-graph interfaces, checkpointer behavior, and
  interruption/resume paths; trace the specific graph actually being changed.
- API and frontend agreement on query/resume requests, thread identity, SSE
  events, progress, answer text, final results, and error handling.
- The expert's hard-error requirements. A fallback proposal must explicitly
  address any conflict with current guidance; it is not a harmless polish change.
- Source freshness and provenance, supported claims, model output validation,
  and bounded retries or debate loops when the proposed feature uses them.
- Tests that distinguish deterministic flow correctness from answer quality.
  If the plan involves model voting, agreement alone does not establish truth.
- Current rules for documentation updates. AI-harness-only changes do not
  require rewriting application guidance merely because a command was added.

These are prompts for inspection, not automatic scope additions. Do not introduce
new agent types, a council, tracing infrastructure, benchmarks, or fallbacks unless
they serve the actual plan and the user accepts the relevant decision.

## 6. Produce the reviewed plan

When the relevant discussions are complete, or the user closes the review:

1. Briefly summarize agreed changes, accepted risks, unresolved blockers, and
   areas left unreviewed. Do not turn deferred choices into assumed requirements.
2. Write a **new, complete plan version** beside the original. For a filename
   ending `_v<N>.md`, use the same stem with the next unused version number.
   For an unversioned file, treat it as v1 and append `_v2.md`, incrementing if
   needed. Keep the original intact. For an inline plan, use
   `docs/plans/<YYYYMonDD>_plan_<topic-slug>_v1.md` or the next unused version.
3. Preserve the plan's tier and the structure expected by the repo's commands:
   lightweight plans keep scope, steps, validation, and applicable follow-up;
   standard plans keep file responsibilities and ordered tasks; full plans keep
   detailed interfaces/code where needed, ordered commits, tests, and rollout.
4. Make the new version self-contained. Include all still-relevant requirements
   and tasks, account for work already applied, and explain the remaining order.
   Apply agreed substantive changes. You may correct verified stale references
   and improve wording without another vote when intent and scope stay the same;
   record those corrections. Do not silently resolve an open design choice.
5. Add a **Review changes** section after the title. Link the source plan and
   review record; map each substantive change to its decision ID and rationale.
   Include rejected recommendations and accepted risks when they affect how the
   plan should be implemented. Carry unresolved choices into an explicit section.
6. Read back the written plan. Check it against every accepted decision, current
   source facts, task dependencies, and proposed validation. Make sure the text
   does not claim planned tests were executed. If a choice remains unresolved,
   specify the exact question and whether work depending on it must wait.

Use separate statuses so engineering readiness is not confused with approval:

- **Readiness:** `Ready for implementation` | `Needs decisions` | `Incomplete review`.
- **User approval:** `Awaiting approval` | `Approved` | `Changes requested`.

A known correctness blocker or an unresolved choice that changes implementation
means `Needs decisions`. An early stop with unreviewed relevant areas means
`Incomplete review`. Record both limitations if both apply. User acceptance of a
trade-off does not turn an unverified claim or a known contradiction into a fact.

Present the new plan path, a short change summary, and outstanding issues.
If the user closed the review early, deliver this interim result and stop;
do not ask another question. Keep approval pending unless the user explicitly
approves that exact interim version, and preserve its readiness limitations.

Otherwise, once no decision prompt is still active, ask the user to approve the
written version or request changes, then wait. Approval of individual decisions
is not approval of a final file they have not seen. Apply requested plan edits
in the same new version during this review, then show any substantive change
for confirmation.

After explicit approval, update the approval status in the plan and review
record. If readiness is `Ready for implementation`, identify
`/rs-implement-plan <reviewed-plan-path>` as the next command. Do not invoke it.
If blockers remain, state the next unresolved decision instead. This command
ends with the reviewed plan and an accurate record of what the user decided.

