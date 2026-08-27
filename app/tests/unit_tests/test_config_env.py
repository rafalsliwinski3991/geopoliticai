from config import DEFAULT_LLM_SETTINGS, LLMSettings


def test_default_llm_settings_values() -> None:
    assert DEFAULT_LLM_SETTINGS.model == "gpt-4o-mini"
    assert DEFAULT_LLM_SETTINGS.temperature == 0.0
    assert DEFAULT_LLM_SETTINGS.timeout_seconds == 60.0
    assert DEFAULT_LLM_SETTINGS.max_output_tokens == 16_384


def test_llm_settings_is_overridable_per_call_site() -> None:
    overridden = LLMSettings(
        model="gpt-4o", temperature=0.7, timeout_seconds=30.0, max_output_tokens=1024
    )
    assert overridden.model == "gpt-4o"
    assert overridden.temperature == 0.7
    assert overridden.timeout_seconds == 30.0
    assert overridden.max_output_tokens == 1024
    assert DEFAULT_LLM_SETTINGS.model == "gpt-4o-mini"
