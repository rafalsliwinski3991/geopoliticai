from __future__ import annotations

import sys

import geopoliticai.cli as cli_module


def test_cli_defaults_to_compact_report(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def _fake_init_environment(log_level=None):
        captured["log_level"] = log_level

    def _fake_run_pipeline(query: str, infosphere: str = "english", report_mode: str = "compact") -> str:
        captured["query"] = query
        captured["infosphere"] = infosphere
        captured["report_mode"] = report_mode
        return "ok"

    monkeypatch.setattr(cli_module, "init_environment", _fake_init_environment)
    monkeypatch.setattr(cli_module, "require_env", lambda: None)
    monkeypatch.setattr(cli_module, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(sys, "argv", ["main.py", "test query"])

    cli_module.main()

    assert captured == {
        "log_level": None,
        "query": "test query",
        "infosphere": "english",
        "report_mode": "compact",
    }
    assert capsys.readouterr().out.strip() == "ok"


def test_cli_accepts_report_and_log_level_flags(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def _fake_init_environment(log_level=None):
        captured["log_level"] = log_level

    def _fake_run_pipeline(query: str, infosphere: str = "english", report_mode: str = "compact") -> str:
        captured["query"] = query
        captured["infosphere"] = infosphere
        captured["report_mode"] = report_mode
        return "done"

    monkeypatch.setattr(cli_module, "init_environment", _fake_init_environment)
    monkeypatch.setattr(cli_module, "require_env", lambda: None)
    monkeypatch.setattr(cli_module, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "another query",
            "--infosphere",
            "polish",
            "--report",
            "full",
            "--log-level",
            "DEBUG",
        ],
    )

    cli_module.main()

    assert captured == {
        "log_level": "DEBUG",
        "query": "another query",
        "infosphere": "polish",
        "report_mode": "full",
    }
    assert capsys.readouterr().out.strip() == "done"
