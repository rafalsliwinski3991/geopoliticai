"""Unit tests for `evals.helpers.run`."""

from __future__ import annotations

import importlib
import json
import re
import subprocess
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from evals.helpers import phoenix as phoenix_mod
from evals.helpers import run as run_mod
from evals.helpers.judge import JUDGE_ERROR, NOT_APPLICABLE, Judge, Results, Verdict
from shared.errors import SearchUnavailableError

FIXED_PATH_NAME = "x_fixed.json"
LIVE_PATH_NAME = "x_live.json"
RECORDED_TITLE = "Recorded summit page"
RECORDED_URL = "https://news.example/summit"
_MISSING = object()


async def _task(input: dict[str, Any]) -> dict[str, Any]:
    return {"done": True}


def _write_dataset(tmp_path: Path, name: str, document: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "name": "n",
        "description": "d",
        "input": {"query": "q"},
        "expected": {"answer": "a"},
    }
    case.update(overrides)
    return {key: value for key, value in case.items() if value is not _MISSING}


def _wrap(*cases: dict[str, Any]) -> dict[str, Any]:
    return {"description": "what the dataset is for", "cases": list(cases)}


def _set_up_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_run: Any) -> None:
    """Fake everything outside `run`: env, tracing, Phoenix, and a datasets directory."""
    monkeypatch.setattr(run_mod, "DATASETS_DIR", tmp_path)
    for name in ("orchestrator_fixed", "deep_forecaster_live", "x_fixed", "x_live"):
        case = _case() if name.endswith("_fixed") else _case(expected=_MISSING)
        _write_dataset(tmp_path, f"{name}.json", _wrap(case))
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(run_mod, "init_environment", lambda *a, **kw: None)
    monkeypatch.setattr(run_mod, "init_tracing", lambda: True)
    monkeypatch.setattr(run_mod, "build_classifiers", lambda judges: {})
    monkeypatch.setattr(phoenix_mod, "run", fake_run)


def _passing_results() -> Results:
    return Results(task_errors=[], verdicts={"b": [Verdict("pass", 1.0)]})


def _always_pass_judge() -> Judge:
    return Judge("b", "binary", lambda i, o, e: {}, check=lambda variables: True)


@pytest.mark.parametrize(
    ("eval_name", "kind"),
    [("expert_fixed", "fixed"), ("deep_forecaster_live", "live")],
    ids=["fixed", "live"],
)
def test_an_eval_name_states_its_kind(eval_name: str, kind: str) -> None:
    # Act
    result = run_mod.eval_kind(eval_name)

    # Assert
    assert result == kind


@pytest.mark.parametrize(
    "eval_name",
    ["expert", "deep_forecaster", "fixed", "expert_fixed_v2"],
    ids=["no kind", "an agent name only", "only the kind", "kind not last"],
)
def test_a_name_without_a_kind_is_refused(eval_name: str) -> None:
    # Act + Assert
    with pytest.raises(ValueError, match="ends in _fixed or _live"):
        run_mod.eval_kind(eval_name)


def test_load_examples_returns_input_expected_and_metadata(tmp_path: Path) -> None:
    # Arrange
    path = _write_dataset(
        tmp_path,
        FIXED_PATH_NAME,
        _wrap(_case(input={"query": "q"}, expected={"answer": "a"})),
    )

    # Act
    examples = run_mod.load_examples(path)

    # Assert
    assert examples == [
        {
            "input": {"query": "q"},
            "output": {"answer": "a"},
            "metadata": {"name": "n", "description": "d"},
        }
    ]


def test_a_live_case_reaches_phoenix_with_an_empty_output(tmp_path: Path) -> None:
    # Arrange
    path = _write_dataset(tmp_path, LIVE_PATH_NAME, _wrap(_case(expected=_MISSING)))

    # Act
    examples = run_mod.load_examples(path)

    # Assert
    assert examples[0]["output"] == {}


def test_a_bare_list_dataset_is_refused(tmp_path: Path) -> None:
    # Arrange
    path = _write_dataset(tmp_path, FIXED_PATH_NAME, [_case()])

    # Act + Assert
    with pytest.raises(ValueError, match="valid dictionary or instance of Dataset"):
        run_mod.load_examples(path)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"description": "", "cases": [_case()]}, "the dataset needs a description"),
        ({"cases": [_case()]}, r"description\n\s+Field required"),
    ],
    ids=["empty description", "missing description"],
)
def test_a_dataset_without_a_description_is_refused(
    tmp_path: Path, document: dict[str, Any], message: str
) -> None:
    # Arrange
    path = _write_dataset(tmp_path, FIXED_PATH_NAME, document)

    # Act + Assert
    with pytest.raises(ValueError, match=message):
        run_mod.load_examples(path)


def test_a_case_without_a_description_is_refused(tmp_path: Path) -> None:
    # Arrange
    path = _write_dataset(tmp_path, FIXED_PATH_NAME, _wrap(_case(description=_MISSING)))

    # Act + Assert
    with pytest.raises(ValueError, match=r"cases\.0\.description\n\s+Field required"):
        run_mod.load_examples(path)


@pytest.mark.parametrize(
    ("expected", "message"),
    [
        (_MISSING, "needs a non-empty expected object"),
        ({}, "needs a non-empty expected object"),
        ([], r"cases\.0\.expected\n\s+Input should be a valid dictionary"),
    ],
    ids=["missing", "empty object", "a list"],
)
def test_a_fixed_case_without_expected_is_refused(
    tmp_path: Path, expected: object, message: str
) -> None:
    # Arrange
    path = _write_dataset(tmp_path, FIXED_PATH_NAME, _wrap(_case(expected=expected)))

    # Act + Assert
    with pytest.raises(ValueError, match=message):
        run_mod.load_examples(path)


@pytest.mark.parametrize(
    "expected", [{"answer": "a"}, {}], ids=["with keys", "empty object"]
)
def test_a_live_case_with_expected_is_refused(
    tmp_path: Path, expected: dict[str, Any]
) -> None:
    # Arrange
    path = _write_dataset(tmp_path, LIVE_PATH_NAME, _wrap(_case(expected=expected)))

    # Act + Assert
    with pytest.raises(ValueError, match="must not have expected"):
        run_mod.load_examples(path)


def test_a_live_case_without_a_query_is_refused(tmp_path: Path) -> None:
    """The live wrapper names each report row by its query, so a case must carry one."""
    # Arrange
    case = _case(
        input={"messages": [{"role": "user", "content": "q"}]}, expected=_MISSING
    )
    path = _write_dataset(tmp_path, LIVE_PATH_NAME, _wrap(case))

    # Act + Assert
    with pytest.raises(ValueError, match="needs a string query"):
        run_mod.load_examples(path)


def test_an_unknown_input_key_is_refused(tmp_path: Path) -> None:
    # Arrange
    path = _write_dataset(
        tmp_path, FIXED_PATH_NAME, _wrap(_case(input={"question": "q"}))
    )

    # Act + Assert
    with pytest.raises(
        ValueError,
        match=r"cases\.0\.input\.question\.\[key\]\n\s+Input should be 'query'",
    ):
        run_mod.load_examples(path)


def test_duplicate_case_names_are_refused(tmp_path: Path) -> None:
    # Arrange
    path = _write_dataset(tmp_path, FIXED_PATH_NAME, _wrap(_case(), _case()))

    # Act + Assert
    with pytest.raises(ValueError, match="duplicate case name"):
        run_mod.load_examples(path)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            {"description": "d", "cases": None},
            r"cases\n\s+Input should be a valid list",
        ),
        (
            {"description": "d", "cases": []},
            r"cases\n\s+List should have at least 1 item",
        ),
        (
            {"description": 1, "cases": [_case()]},
            r"description\n\s+Input should be a valid string",
        ),
        (
            {"description": "d", "cases": ["n"]},
            r"cases\.0\n\s+Input should be a valid dictionary",
        ),
        (_wrap(_case(name=_MISSING)), r"cases\.0\.name\n\s+Field required"),
        (_wrap(_case(name=1)), r"cases\.0\.name\n\s+Input should be a valid string"),
        (
            _wrap(_case(description=1)),
            r"cases\.0\.description\n\s+Input should be a valid string",
        ),
        (_wrap(_case(description="  ")), "a case needs a description"),
        (_wrap(_case(input=[])), r"cases\.0\.input\n\s+Input should be a valid dict"),
        (
            _wrap(_case(input={})),
            r"cases\.0\.input\n\s+Dictionary should have at least 1 item",
        ),
    ],
    ids=[
        "cases null",
        "no cases",
        "dataset description not a string",
        "case not an object",
        "no name",
        "name not a string",
        "case description not a string",
        "blank case description",
        "input not an object",
        "empty input",
    ],
)
def test_load_examples_rejects_malformed_files(
    tmp_path: Path, document: dict[str, Any], message: str
) -> None:
    # Arrange
    path = _write_dataset(tmp_path, FIXED_PATH_NAME, document)

    # Act + Assert
    with pytest.raises(ValueError, match=message):
        run_mod.load_examples(path)


def test_experiment_name_joins_eval_commit_and_time() -> None:
    # Act
    name = run_mod.experiment_name("test-eval", commit="abc1234")

    # Assert
    assert re.fullmatch(r"test-eval-abc1234-\d{8}T\d{6}Z", name)


def test_git_commit_returns_the_short_head_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The commit that ran an experiment is how a Phoenix result is traced back to code."""

    # Arrange
    def _rev_parse(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="abc1234\n")

    monkeypatch.setattr(subprocess, "run", _rev_parse)

    # Act
    commit = run_mod.git_commit()

    # Assert
    assert commit == "abc1234"


def test_git_branch_returns_the_checked_out_branch_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The branch tells a reader of Phoenix which line of work an experiment came from."""

    # Arrange
    def _rev_parse(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="feature/x\n")

    monkeypatch.setattr(subprocess, "run", _rev_parse)

    # Act
    branch = run_mod.git_branch()

    # Assert
    assert branch == "feature/x"


def test_git_branch_falls_back_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """A checkout without git still runs the eval; the branch is nogit."""

    # Arrange
    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", _fail)

    # Act
    branch = run_mod.git_branch()

    # Assert
    assert branch == "nogit"


def test_git_commit_falls_back_when_git_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Git exits non-zero outside a repository; the eval is still named nogit."""

    # Arrange
    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "run", _fail)

    # Act
    commit = run_mod.git_commit()

    # Assert
    assert commit == "nogit"


def test_git_commit_falls_back_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """A checkout without git still runs the eval; it is named nogit."""

    # Arrange
    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", _fail)

    # Act
    commit = run_mod.git_commit()

    # Assert
    assert commit == "nogit"


def test_failures_allows_numeric_average_at_minimum() -> None:
    # Arrange
    judge = Judge("q", "numeric", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[], verdicts={"q": [Verdict("4", 0.75), Verdict("4", 0.75)]}
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == []


def test_failures_reports_numeric_average_below_minimum() -> None:
    # Arrange
    judge = Judge("q", "numeric", lambda i, o, e: {}, prompt="{x}")
    results = Results(task_errors=[], verdicts={"q": [Verdict("3", 0.5)]})

    # Act
    problems = run_mod.failures(results, [judge], example_count=1)

    # Assert
    assert problems == ["q: average 0.50 is below 0.75"]


def test_failures_allows_binary_average_at_one() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[], verdicts={"b": [Verdict("pass", 1.0), Verdict("pass", 1.0)]}
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == []


def test_failures_reports_binary_average_below_one() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[], verdicts={"b": [Verdict("pass", 1.0), Verdict("fail", 0.0)]}
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == ["b: average 0.50 is below 1.00"]


def test_failures_reports_any_judge_error() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[],
        verdicts={
            "b": [Verdict("pass", 1.0), Verdict(JUDGE_ERROR, explanation="down")]
        },
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == ["b: 1 judge error(s); first: down"]


def test_failures_allows_all_not_applicable() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[],
        verdicts={"b": [Verdict(NOT_APPLICABLE), Verdict(NOT_APPLICABLE)]},
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == []


def test_failures_reports_missing_verdicts() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(task_errors=[], verdicts={"b": [Verdict("pass", 1.0)]})

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == ["b: 1 results for 2 examples"]


def test_failures_reports_task_errors() -> None:
    # Arrange
    results = Results(task_errors=["task blew up"], verdicts={})

    # Act
    problems = run_mod.failures(results, [], example_count=1)

    # Assert
    assert problems == ["task failed: task blew up"]


@pytest.mark.anyio
async def test_run_refuses_a_name_without_a_kind_before_loading_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    def _fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the environment was loaded before the name was checked")

    monkeypatch.setattr(run_mod, "init_environment", _fail)

    # Act + Assert
    with pytest.raises(ValueError, match="ends in _fixed or _live"):
        await run_mod.run(eval_name="expert", task=_task, judges=[])


@pytest.mark.anyio
async def test_run_passes_a_fixed_eval_without_a_brave_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.delenv("BRAVE_SEARCH_KEY", raising=False)
    received: dict[str, Any] = {}

    async def _fake_run(**kwargs: Any) -> Results:
        received.update(kwargs)
        return _passing_results()

    _set_up_run(monkeypatch, tmp_path, _fake_run)
    judge = _always_pass_judge()

    # Act
    await run_mod.run(eval_name="orchestrator_fixed", task=_task, judges=[judge])

    # Assert
    assert received["dataset_name"] == "geopoliticai-orchestrator_fixed"
    assert received["judges"] == [judge]


@pytest.mark.anyio
async def test_run_passes_the_git_commit_and_branch_to_phoenix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The experiment's name and its metadata must name the same commit, and the metadata the branch."""
    # Arrange
    received: dict[str, Any] = {}

    async def _fake_run(**kwargs: Any) -> Results:
        received.update(kwargs)
        return _passing_results()

    _set_up_run(monkeypatch, tmp_path, _fake_run)
    monkeypatch.setattr(run_mod, "git_commit", lambda: "abc1234")
    monkeypatch.setattr(run_mod, "git_branch", lambda: "feature/x")

    # Act
    await run_mod.run(
        eval_name="orchestrator_fixed", task=_task, judges=[_always_pass_judge()]
    )

    # Assert
    assert received["git_commit"] == "abc1234"
    assert received["git_branch"] == "feature/x"
    assert received["experiment_name"].startswith("orchestrator_fixed-abc1234-")


@pytest.mark.anyio
async def test_a_live_run_needs_the_brave_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.delenv("BRAVE_SEARCH_KEY", raising=False)
    calls: list[dict[str, Any]] = []

    async def _fake_run(**kwargs: Any) -> Results:
        calls.append(kwargs)
        return _passing_results()

    _set_up_run(monkeypatch, tmp_path, _fake_run)

    # Act + Assert
    with pytest.raises(ValueError, match="BRAVE_SEARCH_KEY"):
        await run_mod.run(eval_name="deep_forecaster_live", task=_task, judges=[])
    assert calls == []


@pytest.mark.anyio
async def test_an_eval_checks_its_extra_keys_before_any_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    calls: list[dict[str, Any]] = []

    async def _fake_run(**kwargs: Any) -> Results:
        calls.append(kwargs)
        return _passing_results()

    _set_up_run(monkeypatch, tmp_path, _fake_run)

    # Act + Assert
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        await run_mod.run(
            eval_name="deep_forecaster_live",
            task=_task,
            judges=[],
            extra_env_vars=("GEMINI_API_KEY",),
        )
    assert calls == []


@pytest.mark.anyio
async def test_run_exits_nonzero_on_failing_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    async def _fake_run(**kwargs: Any) -> Results:
        return Results(task_errors=[], verdicts={"b": [Verdict("fail", 0.0)]})

    _set_up_run(monkeypatch, tmp_path, _fake_run)
    judge = Judge("b", "binary", lambda i, o, e: {}, check=lambda variables: False)

    # Act + Assert
    with pytest.raises(SystemExit) as exc:
        await run_mod.run(eval_name="orchestrator_fixed", task=_task, judges=[judge])
    assert exc.value.code == 1


@pytest.mark.anyio
async def test_run_stops_before_phoenix_when_tracing_cannot_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An eval whose traces would go nowhere must fail, not run untraced."""
    # Arrange
    calls: list[dict[str, Any]] = []

    async def _fake_run(**kwargs: Any) -> Results:
        calls.append(kwargs)
        return _passing_results()

    _set_up_run(monkeypatch, tmp_path, _fake_run)
    monkeypatch.setattr(run_mod, "init_tracing", lambda: False)

    # Act + Assert
    with pytest.raises(RuntimeError, match="Phoenix tracing"):
        await run_mod.run(
            eval_name="orchestrator_fixed", task=_task, judges=[_always_pass_judge()]
        )
    assert calls == []


async def _run_wrapped_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    eval_name: str,
    case: dict[str, Any],
    task: run_mod.Task,
) -> dict[str, Any]:
    """Run `run_mod.run` with a fake Phoenix that awaits the wrapped task on the case's input."""
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "k")
    outputs: list[dict[str, Any]] = []

    async def _fake_run(**kwargs: Any) -> Results:
        example = kwargs["examples"][0]
        outputs.append(await kwargs["task"](example["input"]))
        return _passing_results()

    _set_up_run(monkeypatch, tmp_path, _fake_run)
    _write_dataset(tmp_path, f"{eval_name}.json", _wrap(case))
    await run_mod.run(eval_name=eval_name, task=task, judges=[_always_pass_judge()])
    return outputs[0]


@pytest.mark.anyio
async def test_a_fixed_case_replays_its_recorded_pages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    search_node: Any = importlib.import_module("agents.expert.nodes.search_and_fetch")
    case = _case(
        input={
            "query": "q",
            "sources": [{"title": RECORDED_TITLE, "url": RECORDED_URL, "text": "t"}],
        }
    )

    async def _search_task(input: dict[str, Any]) -> dict[str, Any]:
        candidates = await search_node.search_allowlisted("q", None)
        fetched = await search_node.fetch_sources(candidates, None)
        return {"titles": [source.title for source in fetched]}

    # Act
    output = await _run_wrapped_task(
        monkeypatch, tmp_path, eval_name="x_fixed", case=case, task=_search_task
    )

    # Assert
    assert output == {"titles": [RECORDED_TITLE]}


@pytest.mark.anyio
async def test_a_fixed_case_without_pages_cannot_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    search_node: Any = importlib.import_module("agents.expert.nodes.search_and_fetch")

    async def _search_task(input: dict[str, Any]) -> dict[str, Any]:
        await search_node.search_allowlisted("q", None)
        return {}

    # Act + Assert
    with pytest.raises(RuntimeError, match="no recorded sources"):
        await _run_wrapped_task(
            monkeypatch,
            tmp_path,
            eval_name="x_fixed",
            case=_case(),
            task=_search_task,
        )


@pytest.mark.anyio
async def test_a_live_run_that_fails_becomes_a_report_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    async def _failing_task(input: dict[str, Any]) -> dict[str, Any]:
        raise SearchUnavailableError("every search failed")

    # Act
    output = await _run_wrapped_task(
        monkeypatch,
        tmp_path,
        eval_name="x_live",
        case=_case(expected=_MISSING),
        task=_failing_task,
    )

    # Assert
    assert output["finished"] is False
    assert output["side"] == "outside"
    assert output["cause"].startswith("SearchUnavailableError:")


@pytest.mark.anyio
async def test_a_live_run_that_finishes_is_marked_finished(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    async def _finishing_task(input: dict[str, Any]) -> dict[str, Any]:
        return {"answer": "a"}

    # Act
    output = await _run_wrapped_task(
        monkeypatch,
        tmp_path,
        eval_name="x_live",
        case=_case(expected=_MISSING),
        task=_finishing_task,
    )

    # Assert
    assert output == {
        "finished": True,
        "side": "",
        "cause": "",
        "step_seconds": {},
        "answer": "a",
    }


@pytest.mark.anyio
async def test_a_live_run_prints_one_row_named_by_its_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    async def _finishing_task(input: dict[str, Any]) -> dict[str, Any]:
        return {"answer": "a"}

    # Act
    await _run_wrapped_task(
        monkeypatch,
        tmp_path,
        eval_name="x_live",
        case=_case(input={"query": "What did the summit agree?"}, expected=_MISSING),
        task=_finishing_task,
    )

    # Assert
    rows = capsys.readouterr().out.splitlines()
    assert len(rows) == 1
    assert rows[0].startswith("finished ")
    assert "| What did the summit agree? |" in rows[0]


def test_task_alias_is_a_coroutine_factory() -> None:
    # Assert
    coroutine = _task({})
    assert isinstance(coroutine, Coroutine)
    coroutine.close()
