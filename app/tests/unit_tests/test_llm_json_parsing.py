from types import SimpleNamespace

import llm


class _FakeBadRequestError(Exception):
    pass


class _FakeResponses:
    def __init__(self, impl):
        self._impl = impl
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._impl(**kwargs)


class _FakeChatCompletions:
    def __init__(self, impl):
        self._impl = impl
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._impl(**kwargs)


def test_extract_text_from_responses_response_uses_output_text() -> None:
    response = SimpleNamespace(output_text='{"synthesis":"ok"}', output=[])

    text = llm._extract_text_from_responses_response(response)

    assert text == '{"synthesis":"ok"}'


def test_extract_text_from_responses_response_uses_content_parts() -> None:
    response = SimpleNamespace(
        output_text="",
        output=[
            SimpleNamespace(
                content=[
                    SimpleNamespace(text='{"synthesis":"ok"}'),
                ]
            )
        ],
    )

    text = llm._extract_text_from_responses_response(response)

    assert text == '{"synthesis":"ok"}'


def test_extract_text_from_chat_completions_response_handles_parts() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[
                        {"type": "text", "text": '{"synthesis":"ok"}'},
                    ]
                )
            )
        ]
    )

    text = llm._extract_text_from_chat_completions_response(response)

    assert text == '{"synthesis":"ok"}'


def test_loads_json_object_accepts_code_fence() -> None:
    payload = '```json\n{"synthesis":"ok"}\n```'

    parsed = llm._loads_json_object(payload)

    assert parsed == {"synthesis": "ok"}


def test_invoke_openai_json_object_retries_responses_without_temperature(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llm, "BadRequestError", _FakeBadRequestError)

    def _responses_impl(**kwargs):
        if "temperature" in kwargs:
            raise _FakeBadRequestError(
                "Unsupported value: 'temperature' does not support 0.0 with this model. "
                "Only the default (1) value is supported."
            )
        return SimpleNamespace(output_text='{"synthesis":"ok"}', output=[])

    fake_responses = _FakeResponses(_responses_impl)
    fake_client = SimpleNamespace(
        responses=fake_responses,
        chat=SimpleNamespace(completions=_FakeChatCompletions(lambda **_: None)),
    )

    payload = llm.invoke_openai_json_object(
        client=fake_client,
        model="gpt-5",
        system_content="sys",
        user_content="usr",
        temperature=0.0,
    )

    assert payload == {"synthesis": "ok"}
    assert len(fake_responses.calls) == 2
    assert "temperature" in fake_responses.calls[0]
    assert "temperature" not in fake_responses.calls[1]


def test_invoke_openai_json_object_retries_chat_without_temperature(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llm, "BadRequestError", _FakeBadRequestError)

    fake_responses = _FakeResponses(
        lambda **_: (_ for _ in ()).throw(TypeError("fallback"))
    )

    def _chat_impl(**kwargs):
        if "temperature" in kwargs:
            raise _FakeBadRequestError(
                "Unsupported value: 'temperature' does not support 0.0 with this model. "
                "Only the default (1) value is supported."
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"synthesis":"ok"}'))
            ]
        )

    fake_completions = _FakeChatCompletions(_chat_impl)
    fake_client = SimpleNamespace(
        responses=fake_responses,
        chat=SimpleNamespace(completions=fake_completions),
    )

    payload = llm.invoke_openai_json_object(
        client=fake_client,
        model="gpt-5",
        system_content="sys",
        user_content="usr",
        temperature=0.0,
    )

    assert payload == {"synthesis": "ok"}
    assert len(fake_completions.calls) == 2
    assert "temperature" in fake_completions.calls[0]
    assert "temperature" not in fake_completions.calls[1]


def test_invoke_openai_json_object_retries_chat_without_response_format(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llm, "BadRequestError", _FakeBadRequestError)

    fake_responses = _FakeResponses(
        lambda **_: (_ for _ in ()).throw(TypeError("fallback"))
    )

    def _chat_impl(**kwargs):
        if "response_format" in kwargs:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=""))]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"synthesis":"ok"}'))
            ]
        )

    fake_completions = _FakeChatCompletions(_chat_impl)
    fake_client = SimpleNamespace(
        responses=fake_responses,
        chat=SimpleNamespace(completions=fake_completions),
    )

    payload = llm.invoke_openai_json_object(
        client=fake_client,
        model="gpt-5",
        system_content="sys",
        user_content="usr",
        temperature=0.0,
    )

    assert payload == {"synthesis": "ok"}
    assert len(fake_completions.calls) == 2
    assert "response_format" in fake_completions.calls[0]
    assert "response_format" not in fake_completions.calls[1]
