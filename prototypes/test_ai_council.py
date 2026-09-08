import asyncio
import json
from types import SimpleNamespace

import httpx

from prototypes.ai_council import configured_models
from prototypes import ai_council


def test_configured_models_use_compatible_free_router_by_default(monkeypatch):
    for name in (
        "MEMBER_A_MODEL",
        "MEMBER_B_MODEL",
        "MEMBER_C_MODEL",
        "GPT_MODEL",
        "CLAUDE_MODEL",
        "GEMINI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert configured_models() == {
        "member_a": "openrouter/free",
        "member_b": "openrouter/free",
        "member_c": "openrouter/free",
    }


def test_tracing_uses_a_dedicated_phoenix_project(monkeypatch):
    calls = []
    provider = object()
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
    monkeypatch.delenv("AI_COUNCIL_PHOENIX_PROJECT", raising=False)
    monkeypatch.setattr(
        ai_council,
        "register",
        lambda **kwargs: calls.append(kwargs) or provider,
        raising=False,
    )

    init_council_tracing = getattr(ai_council, "init_council_tracing", lambda: None)

    assert init_council_tracing() is provider
    assert calls == [{
        "endpoint": "http://localhost:6006/v1/traces",
        "project_name": "ai-council-prototype",
        "auto_instrument": True,
        "batch": False,
        "verbose": False,
    }]


def test_ask_json_creates_safe_llm_span(monkeypatch):
    spans = []

    class FakeSpan:
        def __init__(self):
            self.attributes = {}

        def set_attribute(self, name, value):
            self.attributes[name] = value

    class SpanContext:
        def __init__(self, span):
            self.span = span

        def __enter__(self):
            return self.span

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeTracer:
        def start_as_current_span(self, name, **kwargs):
            span = FakeSpan()
            spans.append((name, kwargs, span))
            return SpanContext(span)

    class FakeClient:
        async def post(self, *args, **kwargs):
            return httpx.Response(
                200,
                request=httpx.Request("POST", args[0]),
                json={
                    "model": "selected/free-model",
                    "provider": "ExampleProvider",
                    "choices": [{
                        "finish_reason": "stop",
                        "message": {"content": '{"claims":["supported"]}'},
                    }],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                    },
                },
            )

    monkeypatch.setattr(
        ai_council,
        "trace",
        SimpleNamespace(get_tracer=lambda _name: FakeTracer()),
        raising=False,
    )

    result = asyncio.run(ai_council.ask_json(
        FakeClient(),
        "secret-key-must-not-be-traced",
        "openrouter/free",
        ai_council.Draft,
        "Draft claims.",
        {"query": "test"},
    ))

    assert result.claims == ["supported"]
    assert len(spans) == 1
    name, options, span = spans[0]
    assert name == "openrouter.chat.completions"
    assert options == {"openinference_span_kind": "llm"}
    assert span.attributes["llm.model_name"] == "selected/free-model"
    assert span.attributes["llm.provider"] == "ExampleProvider"
    assert span.attributes["llm.token_count.total"] == 14
    assert "test" in span.attributes["input.value"]
    assert "supported" in span.attributes["output.value"]
    assert "secret-key-must-not-be-traced" not in json.dumps(span.attributes)
