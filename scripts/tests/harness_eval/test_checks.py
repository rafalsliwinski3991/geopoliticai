from harness_eval import checks

FILES = ["agentic_backend/src/config.py", "requirements.txt", "agentic_backend/src/agents/x/other.py"]

PLAN = """# Plan
**Tier:** full

### Unit 01: one
### Unit 02: two
### Unit 03: three

- Edit `src/config.py` and `../requirements.txt`.
- Add `src/nope.py` to the app.
- Create the new file `src/agents/x/new_tool.py`.
- Later, call `new_tool.py` again.
- See `docs/plans/p.md`.
"""


def test_plan_checks_reads_tier_units_and_paths():
    c = checks.plan_checks(PLAN, FILES)
    assert c.tier == "full"
    assert c.unit_headings == 3
    assert c.cited == 6
    assert c.unresolved == ("src/nope.py",)


def test_new_file_exempts_only_its_bare_name():
    plan = "- Create `src/a/tool.py`.\n- Call `tool.py`, then `src/b/tool.py`."
    assert checks.plan_checks(plan, []).unresolved == ("src/b/tool.py",)


def test_tier_needs_the_word_tier_or_plan():
    assert checks.plan_checks("read the plan in full", []).tier is None
    assert checks.plan_checks("Standard plan", []).tier == "standard"


def _pc(units=1, tier="full", cited=10, unresolved=0):
    return checks.PlanChecks(tier, units, cited, tuple("p" * i for i in range(unresolved)))


def test_plan_caps():
    assert checks.plan_caps(_pc(units=0)) == {"units": 1}
    assert checks.plan_caps(_pc(tier=None)) == {"right_sized": 2}
    assert checks.plan_caps(_pc(unresolved=2)) == {"grounded": 2}
    assert checks.plan_caps(_pc(unresolved=0)) == {}


def test_implement_caps():
    ok = {"tests_before": 0, "tests_after": 0, "lint": 0}
    assert checks.implement_caps({**ok, "tests_after": 1}, [], []) == {"does_the_unit": 1}
    assert checks.implement_caps({**ok, "tests_before": 1, "tests_after": 1}, [], []) == {}
    assert checks.implement_caps({**ok, "lint": 1}, [], []) == {"repo_style": 2}
    assert checks.implement_caps(None, [], []) == {}
    assert checks.implement_caps(ok, ["a.py", "b.py"], ["a.py"]) == {"in_scope": 2}
