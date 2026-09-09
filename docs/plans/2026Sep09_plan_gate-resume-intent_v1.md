# Plan — Move the resume-intent classifier into the `gate` node

**Implements:** `docs/brainstorming/2026Sep09_brainstorm_v1_reporter-node-boundaries.md`
(Status: Complete, approved 2026-09-09)
**Size:** standard — 3 ordered tasks, one subsystem, no migration.

## 1. Scope and non-goals

### Intended behaviour

The four-way classifier that reads a user's reply to a paused report outline
moves out of the delivery layer and into the reporter's `gate` node, below its
`interrupt()`. FastAPI stops interpreting the reply and forwards the raw text.

A reply meaning "new question" no longer bypasses the graph. `gate` ends the
subgraph with `decision == "new_question"`, and the orchestrator's `reporter`
node returns `Command(goto="classify")` carrying the question as a new
`HumanMessage`, so the same turn answers it.

### Unchanged behaviour

- Every SSE frame the browser receives, on every path, byte for byte.
- The 409 `ReportNotPendingError` and where it is raised (`api.py`).
- The `interrupt()` payload shape: `outline`, `notice`, `revisions_used`,
  `revisions_allowed`, and no `kind` key.
- `RESUME_INTENT_SYSTEM_PROMPT` and `INTENT_LLM_SETTINGS` — neither is edited
  and neither moves.
- `MAX_REVISION_ROUNDS` accounting: a `new_question` does not consume a revision.
- The frontend. `{resume, thread_id}` is still the request body and the
  clear-`paused`-only-on-409 rule still holds.
- Both `README.md` files, which describe only the request body.

### Non-goals

- **No empty-resume guard in `gate`.** The trust boundary is
  `RunPipelineRequest._normalize`, which already rejects an empty or
  whitespace-only `resume`. Only Studio can deliver an empty reply; it costs one
  classifier call and redraws the outline, which is acceptable for a dev tool.
- **No change to how the reporter subgraph is invoked.** It stays `ainvoke`d
  from `orchestrator/nodes/reporter.py`. `Command.PARENT` is therefore
  unavailable and is not used.
- **Historical plans in `docs/plans/` are not edited.** They are a record of
  what was decided then.

## 2. File responsibilities

| File | Responsibility after this change |
|---|---|
| `app/src/agents/reporter/nodes/gate.py` | Pauses with the outline, **classifies the reply**, records the decision. Owns the classifier as a private helper. |
| `app/src/agents/reporter/intent.py` | **Deleted.** |
| `app/src/agents/reporter/state.py` | `GateAction` becomes the single four-value literal. `ResumeAction` is deleted. `instruction` carries the new question on the `new_question` branch. |
| `app/src/agents/reporter/graph.py` | `_after_gate` routes `new_question` to `END`. |
| `app/src/agents/reporter/__init__.py` | Drops `classify_resume_intent` and `ResumeAction` from the public surface. Keeps `ResumeIntent`. |
| `app/src/agents/orchestrator/nodes/reporter.py` | On `new_question`, returns `Command(goto="classify")` with the question appended. Emits no notice there. |
| `app/src/api.py` | Decides only *resume vs fresh turn*, raises the 409, forwards raw text. |
| `app/tests/integration_tests/test_reporter_graph.py` | Six dict-form resumes rewritten as strings with the classifier stubbed. |
| `app/tests/integration_tests/test_orchestrator_graph.py` | Three dict-form resumes rewritten, plus the new end-to-end `new_question` cycle. |
| `CLAUDE.md` | Two sentences corrected (lines 13 and 20). |

## 3. Ordered tasks

Each task leaves the repo importable with all tests passing.

---

### Task 1 — `gate` classifies; the graph handles `new_question`

**Files:** `agents/reporter/state.py`, `agents/reporter/nodes/gate.py`,
`agents/reporter/graph.py`, `agents/orchestrator/nodes/reporter.py`,
`tests/unit_tests/agents/reporter/test_gate.py`,
`tests/unit_tests/agents/orchestrator/test_reporter.py`

`gate` keeps accepting a dict reply in this task so `api.py`, still sending
dicts, keeps working. That branch is deleted in Task 3.

- [ ] **`state.py`** — merge the two literals into one and note the overload.

```python
GateAction = Literal["approve", "revise", "cancel", "new_question"]

# Transitional alias, deleted in Task 3 once `intent.py` and its test are gone.
ResumeAction = GateAction
```

  **Retype `ResumeIntent.action` to `GateAction` in this task, not in Task 3.**
  It currently reads `action: ResumeAction`. Leaving it and deleting the alias
  later does not break the import — `state.py` has `from __future__ import
  annotations`, so Pydantic defers the unresolved name — but the model is then
  permanently unusable. Reproduced against pydantic 2.12:

```text
pydantic.errors.PydanticUserError: `ResumeIntent` is not fully defined;
you should define `ResumeAction`, then call `ResumeIntent.model_rebuild()`
```

  Every resume would raise inside `ainvoke_structured`. Retyping here makes the
  alias load-bearing for nothing but `test_intent.py`'s import, which Task 3
  deletes.

  In `ReporterState`, amend the `instruction` documentation to record that it
  carries the user's verbatim question when `decision == "new_question"`, and
  that `decision` is what disambiguates the two meanings.

- [ ] **`gate.py`** — add the classifier and the new branch.

```python
from langchain_core.messages import HumanMessage

from agents.reporter.config import INTENT_LLM_SETTINGS, MAX_REVISION_ROUNDS
from agents.reporter.prompts import RESUME_INTENT_SYSTEM_PROMPT
from agents.reporter.state import GateAction, ReporterState, ResumeIntent
from llm import ainvoke_structured


async def _classify(text: str, outline: list[str]) -> tuple[GateAction, str]:
    """Sort one line typed at the paused gate.

    Called *below* `interrupt()`, so it runs once per decision rather than once
    per resume round. A failure here leaves the pause intact: measured on
    langgraph 1.0.1, a node raising below `interrupt()` keeps
    `snapshot.interrupts` populated and the retry resumes cleanly.
    """
    outline_block = "\n".join(f"{i}. {s}" for i, s in enumerate(outline, 1))
    human_prompt = (
        f"Outline awaiting a decision:\n\n{outline_block}\n\nUser typed:\n\n{text}"
    )
    decision = await ainvoke_structured(
        RESUME_INTENT_SYSTEM_PROMPT,
        [HumanMessage(human_prompt)],
        ResumeIntent,
        config={"run_name": "resume_intent"},
        settings=INTENT_LLM_SETTINGS,
    )
    instruction = " ".join(decision.instruction.split())
    if decision.action == "new_question":
        # Always the user's own words, never the model's. The prompt requires an
        # empty `instruction` for this action, and a rephrased question would be
        # answered instead of the one that was asked.
        instruction = " ".join(text.split())
    elif decision.action == "revise" and not instruction:
        # A revise with nothing to apply would redraw the same outline and burn
        # a round. The user's own words are the honest fallback.
        instruction = " ".join(text.split())
    return decision.action, instruction
```

  In `gate`, replace the `_decode(reply)` call with:

```python
    if isinstance(reply, dict):
        # Transitional: `api.py` still builds this dict until Task 2.
        action, instruction = _decode(reply)
    else:
        action, instruction = await _classify(str(reply or ""), list(state["outline"]))
    logger.info("gate: decision=%s", action)
    if action == "revise":
        return {
            "decision": "revise",
            "instruction": instruction,
            "revisions": state["revisions"] + 1,
            "notice": "",
        }
    if action == "cancel":
        return {"decision": "cancel", "instruction": "", "notice": CANCELLED_NOTICE}
    if action == "new_question":
        # Not a decision about the outline at all. The subgraph ends here and
        # the orchestrator re-routes the question; `revisions` is untouched
        # because no revision was requested.
        return {"decision": "new_question", "instruction": instruction, "notice": ""}
    return {"decision": "approve", "instruction": "", "notice": ""}
```

- [ ] **`graph.py`** — `_after_gate` gains the branch. The conditional-edge map
  already contains `END`, so it needs no change.

```python
def _after_gate(state: ReporterState) -> str:
    """Read the decision `gate` already recorded; decide nothing here."""
    decision = state["decision"]
    if decision == "approve":
        return "write"
    if decision in ("cancel", "new_question"):
        return END
    return "outline"
```

- [ ] **`orchestrator/nodes/reporter.py`** — escape before the notice logic.

```python
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, StreamWriter


async def reporter(
    state: OrchestratorState, writer: StreamWriter
) -> dict[str, Any] | Command[Literal["classify"]]:
    ...
    result = await reporter_graph.ainvoke(build_initial_reporter_state(transcript))
    if result.get("decision") == "new_question":
        # The reply was not about the outline. Re-enter the turn at `classify`
        # with the question appended, so it is answered on this same request.
        # `Command(goto=...)` overrides the static `add_edge("reporter", END)`
        # — measured on langgraph 1.0.1; END does not also fire. No `notice` is
        # emitted: the answer comes from `expert` or `chat` a moment later.
        logger.info("reporter: resume was a new question; re-routing to classify")
        return Command(
            goto="classify",
            update={"messages": [HumanMessage(result["instruction"])]},
        )
    report: str = result.get("report") or ""
    ...
```

  Amend the node's docstring: it no longer only returns partial state.

- [ ] **`test_gate.py`** — add cases, and **rewrite one existing test in this
      task**. `test_a_bare_string_reply_is_decoded_as_a_revise` patches only
      `interrupt` and asserts a bare string is assumed to be a revise. After
      this task a bare string reaches `_classify`, so the test would make a live
      `gpt-4o-mini` call. Rewrite it as "a bare string reaches the classifier",
      patching `ainvoke_structured` on the gate module. Deferring this to Task 3
      breaks `make test` at the Task 1 boundary.
  - Patch `ainvoke_structured` on the gate module and `interrupt` to return a
    raw string. Assert each of the four actions produces the right partial state.
  - `new_question` returns the user's verbatim text in `instruction`, sets no
    `notice`, and **does not** appear in `revisions`.
  - A `revise` whose classified `instruction` is blank falls back to the typed
    text, normalized (the case `test_intent.py` owns today).
  - A `new_question` whose classified `instruction` is non-empty still yields
    the user's text, not the model's.

- [ ] **`test_reporter.py`** (orchestrator) — a child result carrying
  `decision == "new_question"` makes the node return a `Command` whose `goto`
  is `"classify"` and whose update appends exactly one `HumanMessage` with the
  question. Assert `writer` received nothing on that path.

**Validation:** `make test` from `app/`, then `make lint`.

---

### Task 2 — `api.py` forwards the raw reply

**Files:** `app/src/api.py`, `tests/unit_tests/test_api.py`

- [ ] Delete the `from agents.reporter import classify_resume_intent` import.
- [ ] Replace `_pending_pause` with a boolean check and shrink `_turn_input`.

```python
async def _has_pending_pause(thread_id: str) -> bool:
    """Is this thread waiting on a report outline?

    Reads `snapshot.interrupts`, never `snapshot.next`. Measured on langgraph
    1.0.1: after a resume whose node raised, `next` is empty while `interrupts`
    still holds the pause, and that thread is still resumable.

    `graph.checkpointer` is None under `make test` and `langgraph dev`. Such a
    graph cannot hold a pause, so False is the true answer, and `aget_state`
    would raise `ValueError("No checkpointer set")` if asked.
    """
    if getattr(graph, "checkpointer", None) is None:
        return False
    snapshot = await graph.aget_state(build_runtime_config(thread_id=thread_id))
    return bool(snapshot.interrupts)


async def _turn_input(payload: RunPipelineRequest) -> Any:
    """Decide what this request hands the graph: a resume, or a fresh turn.

    This layer no longer reads the reply. `gate` classifies it, so a
    new question typed at an outline is re-routed inside the graph.

    The 409 stays here because it cannot be raised anywhere else: measured on
    langgraph 1.0.1, `Command(resume=...)` against a thread with no pending
    interrupt runs no nodes and raises nothing, so the turn would surface as
    `502 "The model returned an empty answer."` — a model failure blamed for a
    routing problem. A plain turn still reads no checkpoint at all.
    """
    if payload.resume is None:
        return build_initial_orchestrator_state(payload.query or "")
    if not await _has_pending_pause(payload.thread_id):
        raise ReportNotPendingError(
            "This conversation has no report waiting for a decision."
        )
    return Command(resume=payload.resume)
```

- [ ] Update the `THINKING_PROGRESS` comment block, which still describes
  `_turn_input` as the thing that can fail before the graph is touched. It can,
  but now only on the checkpoint read.

- [ ] **`test_api.py`**:
  - `test_resume_with_no_pending_pause_is_a_409_error_frame` — patch
    `_has_pending_pause` to return False; delete the `intent` stub and its
    `monkeypatch.setattr(api, "classify_resume_intent", ...)`.
  - `test_pending_pause_returns_none_without_a_checkpointer` — rename to
    `test_has_pending_pause_is_false_without_a_checkpointer` and assert
    `await api._has_pending_pause("t-1") is False`.
  - `test_an_approve_resume_sends_a_resume_command` — drop the intent stub;
    assert `seen[0].resume == "go ahead"`, the raw string.
  - `test_a_new_question_resume_starts_a_fresh_turn` — **delete.** The delivery
    layer no longer knows this case exists. Task 3 replaces it with an
    end-to-end graph test.
  - `test_a_query_turn_never_reads_the_checkpoint` (line 407) — it does
    `monkeypatch.setattr(api, "_pending_pause", boom)`. `monkeypatch.setattr`
    raises `AttributeError` once the attribute is gone, so retarget it at
    `_has_pending_pause`. This is the only test asserting a plain query touches
    no checkpoint, so it must survive rather than be dropped.
  - Drop the now-unused `from agents.reporter import ResumeIntent` import if no
    other test in the file uses it.

**Validation:** `make test`, then `make lint`.

---

### Task 3 — Delete the old path and prove the cycle end to end

**Files:** `agents/reporter/intent.py` (delete),
`agents/reporter/__init__.py`, `agents/reporter/state.py`,
`agents/reporter/nodes/gate.py`,
`tests/unit_tests/agents/reporter/test_intent.py` (delete),
`tests/integration_tests/test_orchestrator_graph.py`, `CLAUDE.md`

- [ ] Delete `agents/reporter/intent.py` and
      `tests/unit_tests/agents/reporter/test_intent.py`.
- [ ] `agents/reporter/__init__.py` — remove the `classify_resume_intent`
      import and its `__all__` entry. `ResumeIntent` stays; it is the
      classifier's output schema and `state.py` still defines it.
- [ ] `state.py` — delete the `ResumeAction = GateAction` alias added in Task 1.
- [ ] `gate.py` — delete `_decode` and the `isinstance(reply, dict)` branch.
      Every caller now sends a string: the delivery layer forwards raw text and
      Studio's resume box types raw text. This is a net improvement for Studio,
      where typing "approve" previously always meant *revise*.
- [ ] **Rewrite nine dict-form resumes across the two integration files.**
      They currently drive `gate` with `Command(resume={"action": ...})`, which
      only works through the `_decode` branch this task deletes. Afterwards each
      would stringify the dict into `"{'action': 'approve'}"` and hand it to a
      live `gpt-4o-mini`, so `make integration_tests` would depend on the
      network and on the model's reading of a Python repr.

      Add one module-level helper per file that patches `ainvoke_structured` on
      `agents.reporter.nodes.gate` to return a chosen `ResumeIntent`, then send
      plain strings. Both files already stub `ainvoke_structured` for `outline`,
      so the pattern is established.

| File | Lines | Resume sent today |
|---|---|---|
| `tests/integration_tests/test_reporter_graph.py` | 100 | `{"action": "revise", "instruction": "add Poland"}` |
| | 120, 169 | `{"action": "approve"}` |
| | 140 | `{"action": "cancel"}` |
| | 162, 166 | two sequential revises |
| | ~197-217 | `MAX_REVISION_ROUNDS + 1` revises in a loop |
| `tests/integration_tests/test_orchestrator_graph.py` | 396, 429, 458 | `{"action": "approve"}` |

      The revision-cap loop matters most: it is the only test proving
      `MAX_REVISION_ROUNDS` ends the run, and it must keep asserting that with
      the classifier stubbed to `revise` every round.

- [ ] **`test_orchestrator_graph.py`** — add the full cycle. The file already
      imports `Command`, `InMemorySaver` and `FakeListChatModel`. Stub the
      classifier to answer `new_question`, then:

```
turn 1: {"messages": [HumanMessage("write me a report")]}
        -> classify -> reporter -> outline -> gate pauses
resume: Command(resume="actually what about Taiwan")
        -> reporter -> gate -> classify -> expert
```

  Assert all four:
  1. `outline` is called **once** across both runs — the subgraph resumed in
     place rather than restarting.
  2. The final `messages` are `Human("write me a report")`,
     `Human("actually what about Taiwan")`, `AI(<expert answer>)`, in order.
  3. `snapshot.interrupts == ()` and `snapshot.next == ()` afterwards.
  4. No `notice` custom event was emitted on that path.

  Also add the sibling case: a resume classified `approve` still reaches
  `write` and produces a report, so the escape branch did not capture it.

- [ ] **`CLAUDE.md`** — two edits, nothing else.
  - Line 13: drop `and the reporter's resume classifier`. `api.py` now imports
    only the compiled orchestrator graph from the agents package.
  - Line 20: `Nodes return partial state dictionaries without mutation` is no
    longer true of every node. Amend to record the one exception: the
    orchestrator's `reporter` node returns a `Command` when a reply at the gate
    turns out to be a new question.

**Validation:** `make test`, `make integration_tests`, `make lint`,
`make format`.

## 4. Test and follow-up notes

### Tests that die

| Test | Why |
|---|---|
| `tests/unit_tests/agents/reporter/test_intent.py` (whole file) | Its subject is deleted. Its two behaviours move into `test_gate.py`. |
| `test_api.py::test_a_new_question_resume_starts_a_fresh_turn` | The delivery layer no longer classifies. Replaced by the integration cycle test. |
| `test_gate.py::test_a_bare_string_reply_is_decoded_as_a_revise` | A bare string is now classified, not assumed to be a revise. Rewrite it as "a bare string reaches the classifier", **in Task 1**. |

### Tests that survive untouched

`test_gate.py::test_the_pause_payload_has_exactly_the_pause_keys_and_a_copied_outline`
and `test_gate_takes_no_writer_parameter_because_it_would_refire_on_every_resume`
both still hold. The second is more load-bearing than before: `gate` now makes a
model call, and a `writer` in that signature would re-fire on every resume round.

### Follow-up

- Phoenix span naming (`run_name="resume_intent"`) is folded into Task 1 rather
  than deferred. It is one keyword argument on a call the task already rewrites.
- No schema, data, config, env, or Compose change. No frontend change.

## 5. Open questions and rejected objections

Self-reviewed, then reviewed by a correctness agent against the actual source.
Five findings, all accepted and folded into the tasks above.

| # | Finding | Where it is now fixed |
|---|---|---|
| 1 | Deleting the `ResumeAction` alias leaves `ResumeIntent.action` referring to a dead name | Task 1 retypes the field to `GateAction` |
| 2 | `test_reporter_graph.py` (six dict resumes) was absent from the plan entirely | Task 3 rewrite table |
| 3 | Three more dict resumes in `test_orchestrator_graph.py` | Task 3 rewrite table |
| 4 | `test_a_query_turn_never_reads_the_checkpoint` patches the renamed `_pending_pause` | Task 2 checklist |
| 5 | Task 1 said "keep the existing tests" while its own code change breaks one | Task 1 checklist |

The reviewer described finding 1 as breaking the application import. Reproduced:
it does not. `from __future__ import annotations` makes Pydantic defer the
unresolved name, so the module imports and `ResumeIntent` raises
`PydanticUserError` on first use instead. Same severity, later failure point,
same fix.

The reviewer independently re-probed the `Command(goto="classify")` mechanism
against installed langgraph 1.0.1 and confirmed it, and found no regression in
the SSE frame sequences, the `revisions` counter, the `notice` event, the
`MAX_REVISION_ROUNDS` interaction, or the frontend's clear-`paused`-only-on-409
rule.

**Rejected: keeping `_decode`'s dict branch permanently** as a test and Studio
escape hatch. It would have made findings 2 and 3 disappear at zero cost. It is
rejected because it keeps two live resume contracts for the gate, which is the
ambiguity this change exists to remove, and because it would leave nine
integration tests exercising a path no caller uses. Stubbing the classifier is
a few lines per file and tests the path production actually takes.

Self-reviewed against the settled decisions; all four are covered by Tasks 1 to 3.

- **Rejected: guarding an empty reply inside `gate`.** Input validation belongs
  at the trust boundary, which is `RunPipelineRequest._normalize`, and it
  already rejects an empty `resume`. Adding a second guard in a node would be
  unreachable from the API and would invent behaviour for Studio that nobody
  asked for. Recorded as a non-goal in §1 rather than silently omitted.
- **Rejected: keeping `nodes/intent.py` as a helper module.** Settled in the
  brainstorm (Q3). Every file in every `nodes/` directory in this repo is
  exactly one node; a helper there would be the first exception.
- **Accepted from self-review: `ResumeAction` cannot be deleted in Task 1.**
  `test_intent.py` imports it and that file survives until Task 3. Hence the
  transitional alias, which Task 3 removes.
- **Accepted from self-review: `gate` must keep decoding dicts during Task 1.**
  `api.py` still builds `{"action", "instruction"}` until Task 2, so deleting
  `_decode` in Task 1 would break every resume between the two tasks.
- **Open, low risk:** `instruction` now carries two different things,
  disambiguated by `decision`. Brainstorm flag F2 left this revisitable. If it
  reads badly in `state.py` during implementation, a dedicated `question` key is
  the alternative and costs one more line in a 7-key `TypedDict`.
