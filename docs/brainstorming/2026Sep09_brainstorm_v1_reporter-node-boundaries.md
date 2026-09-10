# Reporter agent node boundaries: `intent.py` placement and shrinking `_turn_input`

**Started:** 2026-09-09
**Status:** Complete (design approved by the user, 2026-09-09)
**Mode:** single (questions are tightly coupled; batching would force guesses)

## The two stated problems

1. `app/src/agents/reporter/intent.py` is node-shaped logic sitting outside `nodes/`.
2. `_turn_input` in `app/src/api.py` holds branching that the user wants to live
   at the LangGraph level. FastAPI should call the graph and return a response.

These are one decision: `intent.py` sits outside `nodes/` *because* it is called
before the graph is invoked. Move the call into the graph and the file placement
follows; leave the call where it is and `nodes/` would be a misleading home.

## Target design

The resume-intent classifier moves **into** the `gate` node, inside `gate.py`.
FastAPI stops interpreting the user's reply. `intent.py` is deleted.

### Data flow, resume path

```text
POST {resume, thread_id}
  -> api: 409 if no pause pending (forced; see Context verified)
  -> api: graph.astream(Command(resume=<raw user text>))
  -> orchestrator.reporter (re-runs, pure) -> reporter subgraph resumes in place
  -> gate: interrupt() returns the raw text
           -> classify below interrupt(): approve | revise | cancel | new_question
  -> approve      -> write  -> report streams out
  -> revise       -> outline -> pauses again
  -> cancel       -> END, notice
  -> new_question -> END with decision="new_question"
                     -> orchestrator.reporter returns
                        Command(goto="classify", update={"messages": [HumanMessage(text)]})
                     -> classify -> expert/chat answers in the same turn
```

### Files

| File | Change |
|---|---|
| `agents/reporter/nodes/gate.py` | Absorbs the classifier as a private helper. `_decode` deleted: every caller now sends a raw string. Handles `new_question`. |
| `agents/reporter/intent.py` | **Deleted.** |
| `agents/reporter/__init__.py` | Drops the `classify_resume_intent` export. |
| `agents/reporter/state.py` | `GateAction` absorbs `"new_question"`; the now-identical `ResumeAction` is deleted. `instruction` carries the new question on that branch. |
| `agents/reporter/graph.py` | `_after_gate` routes `new_question` to `END`. |
| `agents/orchestrator/nodes/reporter.py` | Returns `Command[Literal["classify"]]` on `new_question`; emits no notice there. |
| `api.py` | `_turn_input` becomes ~6 lines. `_pending_pause` degrades to a boolean check. `classify_resume_intent` import deleted. |
| `prompts.py`, `config.py` | Unchanged. The prompt and `INTENT_LLM_SETTINGS` already live in the agent. |
| `CLAUDE.md` | Node contract line amended: one orchestrator node now returns a `Command`. |

### Approaches compared

1. **Chosen** — classifier in `gate`, `new_question` escapes via `Command(goto=...)`.
2. **Placement only** — move `intent.py` under `nodes/`, leave `api.py` alone.
   Rejected: leaves problem 2 unsolved, and makes `nodes/` hold a non-node.
3. **Maximal** — move the 409 check into the graph too.
   Rejected by probe: a resume on an unpaused thread runs zero nodes.

## Context verified

- **langgraph 1.0.1** (`app/uv.lock`), pinned `langgraph-checkpoint-postgres>=3.0.3,<3.1`.
- **`Command(resume=...)` on a thread with no pending interrupt is a silent no-op.**
  Probed locally with `InMemorySaver` on a `START -> classify -> chat -> END`
  graph: `ainvoke(Command(resume="approve"))` after a completed turn ran no
  nodes, raised nothing, returned the unchanged state, and left
  `next == ()` / `interrupts == ()`. Consequence: the existing
  `ReportNotPendingError` -> 422 cannot be produced from inside the graph,
  because there is no graph run to produce it from. Sending a stray resume
  blind would surface as `502 "The model returned an empty answer."`.
- **`Command(goto=..., update=...)` is a first-class in-node routing pattern**
  in 1.0.x (Context7, `/langchain-ai/langgraph/1.0.3`, graph-api and low_level
  docs). `Command.PARENT` also exists, but is unavailable here: the reporter is
  `ainvoke`d from `orchestrator/nodes/reporter.py`, not registered with
  `add_node`, so it has no parent graph to address.
- **`gate` re-runs from its first line on every resume**, so anything placed
  *above* `interrupt()` re-fires each round. Anything placed *below* it runs
  once per decision. The intent classifier would go below.
- **Phoenix is fed by the LangChain instrumentor only.** `uv pip list` shows
  `openinference-instrumentation-langchain 0.1.72` and no FastAPI/ASGI
  instrumentor; `init_tracing` passes `auto_instrument=True`, which activates
  only instrumentors whose package is installed. There is therefore no HTTP
  request span. A model call made before the graph is invoked opens its own
  **root trace**, unlinked to the graph run of the same turn.
- **Phoenix session grouping already works for graph runs, keyed by thread id.**
  `langgraph/_internal/_config.py:311-315` (`ensure_config`) copies every scalar
  `configurable` key into `metadata`, and
  `openinference/instrumentation/langchain/_tracer.py:1459-1464` lifts
  `metadata["thread_id"]` (or `session_id` / `conversation_id`) onto the
  OpenInference `SESSION_ID` span attribute. Read from installed source, not
  measured against a live Phoenix.
  Consequence: today's pre-graph `classify_resume_intent` is the **only** model
  call in the app that carries no session and no thread id.
- **Span names come from `run.name`** (`_tracer.py:186-187`), which LangChain
  fills from `config["run_name"]`. `ainvoke_structured` already accepts a
  `config` and `intent.py` passes none, so the intent span is currently unnamed
  in any useful sense. Caveat: `with_structured_output` builds a sequence, so
  `run_name` names the wrapping span, not the inner model span.
- Current callers of the moved code: `app/src/api.py`, `agents/reporter/__init__.py`,
  `app/src/models.py` (`ReportNotPendingError`), `tests/unit_tests/agents/reporter/test_intent.py`,
  `tests/unit_tests/test_api.py`.

## Settled decisions

- **Q1 — The `gate` node classifies the resume text, not FastAPI.**
  _(rationale: the classifier belongs with the pause it answers; and it is
  currently the only model call in the app that lands in no Phoenix session.)_
  - Challenged on: a classifier failure now happens mid-resume and could eat
    the pause. -> **Held.** Probed: a node raising below `interrupt()` leaves
    `snapshot.interrupts` populated and the retry resumes cleanly. Note `next`
    empties while `interrupts` does not, so `_pending_pause` must keep reading
    `.interrupts`.
  - Consequences: `intent.py`'s reason for existing outside `nodes/` is gone.
    Resume traces become one nested trace inside the thread's Phoenix session
    instead of two unlinked root traces.

- **Q2 — A new question at the gate is answered in the same turn.**
  _(rationale: preserves shipped behaviour; making the user retype reads as a bug.)_
  - Challenged on: nothing. **Explicitly no objection** — a misclassified
    `new_question` destroys a pending report, but the current pre-graph path
    destroys it identically. Same classifier, same prompt, no regression.
  - Consequences: `orchestrator/nodes/reporter.py` returns a `Command`, which
    contradicts CLAUDE.md's "nodes return partial state dictionaries" line.
    That line needs amending.

- **Q3 — The classifier folds into `gate.py`; `intent.py` is deleted.**
  _(rationale: solves problem 1 more completely than moving the file — the logic
  reaches `nodes/`, and the "one file in nodes/ is one node" rule survives.)_
  - Challenged on: `test_intent.py` loses its isolated seam. -> **Resolved, not
    held against it.** `test_gate.py` already monkeypatches `interrupt` at module
    level and calls `gate(state)` directly, so the merge is mechanical.
  - Consequences: `test_intent.py` merges into `test_gate.py`.

- **Q4 — The 409 "no report pending" check stays in the delivery layer.**
  _(rationale: forced by the probe, not chosen.)_ Pruned rather than asked:
  every answer leads to the same work.

## Design tree

- **Where does resume-intent classification run?** — OPEN (Q1)
  - If in `gate`: how is `new_question` returned to the orchestrator? — OPEN (Q2)
  - If in `gate`: does `intent.py` become a helper module under `nodes/`, or fold into `gate.py`? — OPEN (Q3)
  - If it stays pre-graph: where does the file honestly belong? — OPEN (Q3')
- **Does the 422 pause check stay in the delivery layer?** — OPEN (Q4), heavily constrained by the no-op probe
- **What does the `interrupt()` resume payload contract become?** — OPEN (Q5), downstream of Q1

## Current frontier (open questions)

- **Q1 — Who classifies the resume text** _(next up)_
- **Q2 — How `new_question` escapes the reporter subgraph** (downstream of Q1)
- **Q3 — Final home for the classifier module** (downstream of Q1)
- **Q4 — The 422 "no report pending" check** (sibling, largely settled by the probe)
- **Q5 — Resume payload contract and Studio's bare-string path** (downstream of Q1)

## Carried as flags, not decisions

- **F1 — Name the intent span.** Pass `config={"run_name": "resume_intent"}` to
  `ainvoke_structured` from wherever the classifier ends up. One line, improves
  Phoenix legibility under either Q1 answer. Independent of the boundary
  decision; carry it into the plan regardless.
- **F2 — `instruction` carries the new question on the `new_question` branch.**
  Reuses an existing key rather than adding one; `decision` disambiguates it.
  Revisit at implementation time if it reads badly in `state.py`.
- **F3 — CLAUDE.md needs two edits**: the node-return contract, and the `api.py`
  paragraph describing what the delivery layer decides.
- **F4 — Annotate the return type** as `Command[Literal["classify"]]` on the
  orchestrator's reporter node so graph drawing still shows the edge.

## Round log

### Round 1 — Q1: Who classifies the resume text
Posed. Option A: `gate` classifies, subgraph becomes self-contained, `intent.py`
moves under `nodes/` as a consequence. Option B: nothing moves, file is renamed
to say it is a pre-graph helper. Lean was A (weak).

**User asked** which option is more visible in Phoenix traces. Investigated
rather than guessed (see Context verified). Answer: A, decisively. Today a
revise or new-question reply produces **two unrelated root traces** — the
orphan intent call and the graph resume — with nothing linking them but
timestamps. Under A it is one trace, nested
`orchestrator -> reporter -> gate -> resume_intent`, inside the thread's
existing Phoenix session.

**User then asked** whether the new-question path's trace clarity could be
improved. **Retracted my own "muddier" claim**: under A that path traces as
`reporter -> gate -> resume_intent(new_question) -> classify -> expert`, a
legible record of an abandoned outline. Today the abandonment is invisible —
the API discards the pause silently and the deciding model call is an orphan.
It is the path that gains the most, not the least. Lean on Q1 raised to
**strong A**; the remaining objection is plumbing cost in three files, not
observability.

Spun out: **F1 — pass `run_name` to the intent call.** One line, valuable under
either option.

### Round 2 — Q2: What happens when someone asks a new question at the gate
Options: (A) keep the turn going via `Command(goto="classify")`, (B) cancel the
report and ask the user to retype. Lean was A (weak). **User answered A.**
**No push-back raised**, stated explicitly: the misclassification risk is
pre-existing and unchanged by the move.

### Round 3 — Q3: Where the classifier code lives
Options: (A) fold into `gate.py`, (B) `nodes/intent.py` beside it. Lean was A
(strong), on the grounds that every file in every `nodes/` dir in this repo is
exactly one node. **User answered A.** The one objection (losing `test_intent.py`'s
isolated seam) was investigated and dropped rather than pressed.

### Round 4 — end-to-end shape probe (no question)
Replicated the real graph shape with `InMemorySaver` and a stubbed classifier.
Measured on langgraph 1.0.1:

```text
turn1 ran: ['classify', 'reporter', 'outline']   interrupts: True
resume   : ['reporter', 'gate', 'classify', 'expert']
messages : [Human('write me a report'), Human('actually what about Taiwan'), AI('expert answer')]
next: ()   interrupts: ()
```

Three facts established: `Command(goto="classify")` **overrides** the static
`add_edge("reporter", END)` and END does not fire; `outline` does **not** re-run
on the resume, so the subgraph resumes in place; the pause clears completely.
The design is viable as specified.
