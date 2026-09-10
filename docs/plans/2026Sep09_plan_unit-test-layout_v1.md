# Plan — Unit test layout and AAA markers

Implements the unit-test half of
`docs/brainstorming/2026Sep09_brainstorm_v2_tests-and-openrouter-evals.md`.
Depth: **lightweight**. Mechanical, contained to `app/tests/unit_tests/`, no
source change, no behaviour change.

The eval half of that brainstorm is a separate plan,
`docs/plans/2026Sep09_plan_eval-suite_v1.md`. The two share no files and can
land in either order.

## Scope and non-goals

**In scope.** Move the nine node test files into `nodes/` subdirectories so the
test tree mirrors `src/agents/<name>/` exactly, and add `# Arrange`, `# Act`,
`# Assert` comment markers to all 23 unit test files.

**Not in scope.** No test is added, deleted, renamed, or changed in what it
asserts. No source file changes. Integration tests are untouched. The AAA
sweep does not extend to `app/tests/integration_tests/`, because the brainstorm
settled the sweep over the unit suite only.

**Verified against the code.** No file under `tests/unit_tests/agents/` uses
`__file__` or a `parents[...]` path, so moving them breaks no path assumption.
The node tests reach their subjects through
`importlib.import_module("agents.<agent>.nodes.<node>")` on absolute module
paths, which are unaffected by the test file's own location.

## Change steps

Land as two commits so the structural change is not buried in the comment
diff.

### Commit 1 — move node tests into `nodes/`

Nine `git mv` operations, plus three new empty `__init__.py` files. Every
other test directory already has its `__init__.py`.

| From | To |
| --- | --- |
| `agents/expert/test_answer.py` | `agents/expert/nodes/test_answer.py` |
| `agents/expert/test_search_and_fetch.py` | `agents/expert/nodes/test_search_and_fetch.py` |
| `agents/orchestrator/test_chat.py` | `agents/orchestrator/nodes/test_chat.py` |
| `agents/orchestrator/test_classify.py` | `agents/orchestrator/nodes/test_classify.py` |
| `agents/orchestrator/test_expert.py` | `agents/orchestrator/nodes/test_expert.py` |
| `agents/orchestrator/test_reporter.py` | `agents/orchestrator/nodes/test_reporter.py` |
| `agents/reporter/test_gate.py` | `agents/reporter/nodes/test_gate.py` |
| `agents/reporter/test_outline.py` | `agents/reporter/nodes/test_outline.py` |
| `agents/reporter/test_write.py` | `agents/reporter/nodes/test_write.py` |

New files, each empty:

- `tests/unit_tests/agents/expert/nodes/__init__.py`
- `tests/unit_tests/agents/orchestrator/nodes/__init__.py`
- `tests/unit_tests/agents/reporter/nodes/__init__.py`

Deliberately **not** moved, because they mirror modules that sit at the agent
level in `src/`, not under `nodes/`:

- `agents/orchestrator/test_state.py` → `src/agents/orchestrator/state.py`
- `agents/reporter/test_state.py` → `src/agents/reporter/state.py`
- `agents/reporter/test_intent.py` → `src/agents/reporter/intent.py`

`agents/expert/consts/test_sources.py` already mirrors `src/` and stays put.

### Commit 2 — AAA comment markers across all 23 files

Insert `# Arrange`, `# Act`, `# Assert` comments into every test function in
every file under `tests/unit_tests/`. Comments only: no statement is added,
removed, reordered, or reindented.

Placement rules, so the sweep is consistent rather than per-file taste:

- `# Arrange` above the first setup statement. Omit the section entirely when a
  test has no setup, rather than labelling an empty section.
- `# Act` above the single call to the code under test.
- `# Assert` above the first `assert`, or above the `with pytest.raises(...)`
  block when the assertion *is* the raise. Where the act and the assertion are
  one statement, as in `with pytest.raises(...): await node(...)`, use a single
  `# Act + Assert` marker rather than splitting a statement in two.
- Module-level helpers such as `_state()` and `_patch_interrupt()` get no
  markers. They are fixtures, not tests.

Worked example, `tests/unit_tests/agents/reporter/nodes/test_gate.py`:

```python
@pytest.mark.anyio
async def test_an_approve_decision_keeps_the_revision_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _patch_interrupt(monkeypatch, {"action": "approve"})

    # Act
    result = await node_module.gate(_state())

    # Assert
    assert result == {"decision": "approve", "instruction": "", "notice": ""}
```

## Validation

Run from `app/`. Both commits must pass both commands.

```bash
make test
make lint
```

`make test` must report the same number of passing tests before and after each
commit. Record the count from a run on the current branch before starting, and
compare. A changed count means a file was lost in the move or a comment landed
inside a statement.

`make lint` runs `ruff format --diff` over the repo, which fails on a comment
indented inconsistently with the block it sits in. That is the check that
catches a bad marker insertion.

## Required follow-up

None. `CLAUDE.md` documents the application and explicitly does not require
updating for test-harness layout. No configuration, migration, or rollout work
follows from this change.
