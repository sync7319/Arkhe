"""
Unit tests for config/settings.py — no API keys required.
Tests cover: get_user_chain() parsing, get_model() role resolution.
"""
import pytest
import config.settings as settings_module


def _reset_chain_cache():
    """Reset the module-level BYOK chain cache between tests."""
    settings_module._user_chain_cache = False


# ── get_user_chain() ──────────────────────────────────────────────────────────

def test_chain_empty_string(monkeypatch):
    _reset_chain_cache()
    monkeypatch.setenv("ARKHE_CHAIN", "")
    assert settings_module.get_user_chain() is None


def test_chain_not_set(monkeypatch):
    _reset_chain_cache()
    monkeypatch.delenv("ARKHE_CHAIN", raising=False)
    assert settings_module.get_user_chain() is None


def test_chain_single_valid_entry(monkeypatch):
    _reset_chain_cache()
    monkeypatch.setenv("ARKHE_CHAIN", "groq:llama-3.3-70b-versatile:gsk_abc123")
    result = settings_module.get_user_chain()
    assert result == [("groq", "llama-3.3-70b-versatile", "gsk_abc123")]


def test_chain_multiple_entries(monkeypatch):
    _reset_chain_cache()
    monkeypatch.setenv(
        "ARKHE_CHAIN",
        "openai:gpt-4o:sk-xxx,gemini:gemini-2.5-pro:AIza_yyy,groq:llama-3.3-70b-versatile:gsk_zzz"
    )
    result = settings_module.get_user_chain()
    assert result == [
        ("openai", "gpt-4o", "sk-xxx"),
        ("gemini", "gemini-2.5-pro", "AIza_yyy"),
        ("groq", "llama-3.3-70b-versatile", "gsk_zzz"),
    ]


def test_chain_skips_unknown_provider(monkeypatch):
    _reset_chain_cache()
    monkeypatch.setenv("ARKHE_CHAIN", "unknown:model:key,groq:llama-3.1-8b-instant:gsk_abc")
    result = settings_module.get_user_chain()
    assert result == [("groq", "llama-3.1-8b-instant", "gsk_abc")]


def test_chain_skips_malformed_entry(monkeypatch):
    _reset_chain_cache()
    monkeypatch.setenv("ARKHE_CHAIN", "groq:llama-3.1-8b-instant:gsk_abc,badentry,groq:llama-3.3-70b-versatile:gsk_def")
    result = settings_module.get_user_chain()
    assert result == [
        ("groq", "llama-3.1-8b-instant", "gsk_abc"),
        ("groq", "llama-3.3-70b-versatile", "gsk_def"),
    ]


def test_chain_all_invalid_returns_none(monkeypatch):
    _reset_chain_cache()
    monkeypatch.setenv("ARKHE_CHAIN", "badentry,alsobad")
    assert settings_module.get_user_chain() is None


def test_chain_cached_after_first_call(monkeypatch):
    _reset_chain_cache()
    monkeypatch.setenv("ARKHE_CHAIN", "groq:llama-3.1-8b-instant:gsk_abc")
    result1 = settings_module.get_user_chain()
    # Change env — should still return cached value
    monkeypatch.setenv("ARKHE_CHAIN", "openai:gpt-4o:sk-xxx")
    result2 = settings_module.get_user_chain()
    assert result1 == result2


# ── get_model() ───────────────────────────────────────────────────────────────

def test_get_model_invalid_role(monkeypatch):
    monkeypatch.setenv("EXPENSIVE_MODELS_ALLOWED", "false")
    with pytest.raises(ValueError, match="Unknown role"):
        settings_module.get_model("nonexistent")


def test_get_model_invalid_provider(monkeypatch):
    monkeypatch.setenv("TRAVERSAL_PROVIDER", "badprovider")
    monkeypatch.setenv("EXPENSIVE_MODELS_ALLOWED", "false")
    # Need to reload the module-level provider vars
    import importlib
    importlib.reload(settings_module)
    with pytest.raises(ValueError, match="Unknown provider"):
        settings_module.get_model("traversal")
    # Restore
    monkeypatch.setenv("TRAVERSAL_PROVIDER", "groq")
    importlib.reload(settings_module)


def test_get_model_traversal_always_cheap(monkeypatch):
    monkeypatch.setenv("EXPENSIVE_MODELS_ALLOWED", "true")
    monkeypatch.setenv("TRAVERSAL_PROVIDER", "groq")
    monkeypatch.delenv("TRAVERSAL_MODEL", raising=False)
    import importlib
    importlib.reload(settings_module)
    provider, model = settings_module.get_model("traversal")
    assert provider == "groq"
    assert model == settings_module.CHEAP_MODELS["groq"]["traversal"]


def test_get_model_env_override(monkeypatch):
    monkeypatch.setenv("TRAVERSAL_PROVIDER", "groq")
    monkeypatch.setenv("TRAVERSAL_MODEL", "custom-model-override")
    monkeypatch.setenv("EXPENSIVE_MODELS_ALLOWED", "false")
    import importlib
    importlib.reload(settings_module)
    provider, model = settings_module.get_model("traversal")
    assert model == "custom-model-override"
    monkeypatch.delenv("TRAVERSAL_MODEL")
    importlib.reload(settings_module)
