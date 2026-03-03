from __future__ import annotations

from fastapi.testclient import TestClient

import geopoliticai.api as api_module


def _make_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("TAVILY_KEY", "test-tavily-key")
    api_module._rate_limit_store.clear()
    return TestClient(api_module.app)


def test_run_pipeline_rejects_too_long_query(monkeypatch) -> None:
    with _make_client(monkeypatch) as client:
        response = client.post(
            "/run_pipeline",
            json={
                "query": "x" * (api_module.MAX_QUERY_LENGTH + 1),
                "infosphere": "english",
            },
        )

    assert response.status_code == 422


def test_run_pipeline_rejects_invalid_infosphere(monkeypatch) -> None:
    with _make_client(monkeypatch) as client:
        response = client.post(
            "/run_pipeline",
            json={"query": "test", "infosphere": "invalid"},
        )

    assert response.status_code == 422


def test_run_pipeline_normalizes_query_before_execution(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _fake_run_pipeline(query: str, infosphere: str = "english") -> str:
        captured["query"] = query
        captured["infosphere"] = infosphere
        return "ok"

    monkeypatch.setattr(api_module, "run_pipeline", _fake_run_pipeline)
    with _make_client(monkeypatch) as client:
        response = client.post(
            "/run_pipeline",
            json={"query": "   hello   world   ", "infosphere": "polish"},
        )

    assert response.status_code == 200
    assert captured == {"query": "hello world", "infosphere": "polish"}


def test_run_pipeline_rate_limit(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(api_module, "RATE_LIMIT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(api_module, "run_pipeline", lambda query, infosphere="english": "ok")

    with _make_client(monkeypatch) as client:
        first = client.post(
            "/run_pipeline", json={"query": "q1", "infosphere": "english"}
        )
        second = client.post(
            "/run_pipeline", json={"query": "q2", "infosphere": "english"}
        )
        third = client.post(
            "/run_pipeline", json={"query": "q3", "infosphere": "english"}
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert "Rate limit exceeded" in third.json()["detail"]
