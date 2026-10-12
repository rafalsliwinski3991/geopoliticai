"""Score history for the harness eval: one JSON row per judged output, and
the step-summary tables that compare each run with the ones before it.
"""

import html
import json
from collections.abc import Iterable
from itertools import groupby
from pathlib import Path
from statistics import mean
from typing import Any

SUBJECTS = ("plan-opus", "impl-sonnet", "impl-glm")
LAST_RUNS = 10
# Brainstorm Q7: a single run's quality moves by about this much with no
# harness change; to be revisited once repeats measure it.
NOISE = 0.3
LEGEND = (
    "Quality is 1–4. `≈` marks a change under {noise}, within single-run noise. "
    "est. $ is each tool's own list-price estimate. ⏱ timed out; ✗ the agent crashed.\n"
)
TABLE_HEAD = (
    "| run | date | note | n | quality | tokens | est. $ | time | q/Mtok |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
)
MEANS = ("overall", "tokens_total", "est_cost_usd", "minutes", "quality_per_mtok")


def row(
    judged: dict[str, Any], *, run_id: str, date: str, sha: str, note: str, judge_version: str
) -> dict[str, Any]:
    parts = (judged["tokens_in"], judged["tokens_cached"], judged["tokens_out"])
    total = sum(parts) if None not in parts else None
    overall = judged["overall"]
    return {
        "run_id": run_id,
        "date": date,
        "sha": sha,
        "note": note,
        "judge_version": judge_version,
        "subject": judged["subject"],
        "repeat": judged["repeat"],
        "model": judged["model"],
        "overall": overall,
        "scores": {c["name"]: c["score"] for c in judged["criteria"]},
        "hard_checks": judged["hard_checks"],
        "tokens_in": judged["tokens_in"],
        "tokens_cached": judged["tokens_cached"],
        "tokens_out": judged["tokens_out"],
        "tokens_total": total,
        "est_cost_usd": judged["est_cost_usd"],
        "minutes": judged["minutes"],
        "quality_per_mtok": round(overall / (total / 1e6), 2) if total else None,
        "timed_out": judged["timed_out"],
        "agent_failed": judged["agent_failed"],
    }


def load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Skip rows already recorded, so re-running the judge job adds nothing twice."""
    seen = {(r["run_id"], r["subject"], r["repeat"]) for r in load(path)}
    with path.open("a") as f:
        for r in rows:
            key = (r["run_id"], r["subject"], r["repeat"])
            if key not in seen:
                seen.add(key)
                f.write(json.dumps(r, sort_keys=True) + "\n")


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    return mean(values) if values else None


def runs(rows: list[dict[str, Any]], subject: str) -> list[dict[str, Any]]:
    """One entry per run for a subject, repeats averaged, oldest first (file order)."""
    mine = [r for r in rows if r["subject"] == subject]
    out = []
    for run_id, group in groupby(mine, key=lambda r: r["run_id"]):
        g = list(group)
        out.append({
            "run_id": run_id,
            "date": g[0]["date"],
            "note": g[0]["note"],
            "judge_version": g[0]["judge_version"],
            "n": len({r["repeat"] for r in g}),
            "timed_out": any(r["timed_out"] for r in g),
            "agent_failed": any(r.get("agent_failed") for r in g),
            **{k: _mean(g, k) for k in MEANS},
        })
    return out


def _delta(cur: float | None, prev: float | None, fmt: str, noise: float = 0.0) -> str:
    if cur is None or prev is None:
        return ""
    d = cur - prev
    if noise and abs(d) < noise:
        return " ≈"
    if d == 0:
        return ""
    return f" {'▲' if d > 0 else '▼'}{fmt.format(abs(d))}"


def _cell(value: float | None, fmt: str) -> str:
    return "—" if value is None else fmt.format(value)


def _mtok(value: float | None) -> float | None:
    return None if value is None else value / 1e6


def _escape(text: str) -> str:
    return html.escape(text, quote=False).replace("|", "\\|").replace("\n", " ")


def render_subject(entries: list[dict[str, Any]]) -> str:
    lines = []
    prev: dict[str, Any] | None = None
    for e in entries:
        if prev is not None and e["judge_version"] != prev["judge_version"]:
            lines.append(f"| | | **judge changed → {e['judge_version']}** | | | | | | |\n")
            prev = None
        p = prev or {}
        marks = (" ⏱" if e["timed_out"] else "") + (" ✗" if e["agent_failed"] else "")
        quality = _cell(e["overall"], "{:.2f}") + _delta(e["overall"], p.get("overall"), "{:.2f}", NOISE)
        tokens = _cell(_mtok(e["tokens_total"]), "{:.2f}M") + _delta(
            _mtok(e["tokens_total"]), _mtok(p.get("tokens_total")), "{:.2f}M"
        )
        cost = _cell(e["est_cost_usd"], "${:.2f}") + _delta(e["est_cost_usd"], p.get("est_cost_usd"), "${:.2f}")
        time = _cell(e["minutes"], "{:.0f}m") + _delta(e["minutes"], p.get("minutes"), "{:.0f}m")
        lines.append(
            f"| {e['run_id']} | {e['date']} | {_escape(e['note'])} | {e['n']} "
            f"| {quality}{marks} | {tokens} | {cost} | {time} | {_cell(e['quality_per_mtok'], '{:.1f}')} |\n"
        )
        prev = e
    return TABLE_HEAD + "".join(lines)


def render(rows: list[dict[str, Any]]) -> str:
    out = ["## Harness eval history\n\n", LEGEND.format(noise=NOISE)]
    for subject in SUBJECTS:
        entries = runs(rows, subject)[-LAST_RUNS:]
        if entries:
            out.append(f"\n### {subject}\n\n{render_subject(entries)}")
    return "".join(out)


def render_reasoning(judged: list[dict[str, Any]]) -> str:
    out = ["\n## This run's verdicts\n"]
    for j in judged:
        out.append(
            f"\n<details><summary>{j['subject']} #{j['repeat']} — {j['overall']:.2f}</summary>\n\n"
        )
        out.append(f"{_escape(j['summary'])}\n\n| criterion | score | reasoning |\n|---|---|---|\n")
        for c in j["criteria"]:
            capped = f" (capped at {c['cap']})" if c["cap"] is not None else ""
            out.append(f"| {c['name']} | {c['score']}{capped} | {_escape(c['reasoning'])} |\n")
        out.append(f"\nHard checks: `{json.dumps(j['hard_checks'], sort_keys=True)}`\n\n</details>\n")
    return "".join(out)
