"""
Unit tests for config/model_router.py — no API keys required.
Tests cover: cooldown tracking, chain navigation.
"""
import time
import pytest
import config.model_router as router


def _clear_cooldowns():
    router._cooldowns.clear()


# ── is_cooling / mark_cooling ─────────────────────────────────────────────────

def test_not_cooling_by_default():
    _clear_cooldowns()
    assert router.is_cooling("llama-3.3-70b-versatile") is False


def test_mark_cooling_sets_state(monkeypatch):
    _clear_cooldowns()
    # Prevent DB write during test
    monkeypatch.setattr(router, "_cooldowns", {})
    try:
        router.mark_cooling("llama-3.3-70b-versatile")
    except Exception:
        pass  # DB not initialized in test env — that's expected
    assert router.is_cooling("llama-3.3-70b-versatile") is True


def test_cooling_remaining_positive_after_mark(monkeypatch):
    _clear_cooldowns()
    monkeypatch.setattr(router, "_cooldowns", {})
    try:
        router.mark_cooling("gemini-2.0-flash")
    except Exception:
        pass
    remaining = router.cooling_remaining("gemini-2.0-flash")
    assert remaining > 0
    assert remaining <= router.COOLDOWN_SECONDS.get("gemini", router._DEFAULT_COOLDOWN)


def test_cooling_remaining_zero_when_not_cooling():
    _clear_cooldowns()
    assert router.cooling_remaining("some-unknown-model") == 0


def test_expired_cooldown_not_cooling():
    _clear_cooldowns()
    # Manually set an expired timestamp
    router._cooldowns["expired-model"] = time.time() - 1
    assert router.is_cooling("expired-model") is False
    assert router.cooling_remaining("expired-model") == 0


# ── get_chain ─────────────────────────────────────────────────────────────────

def test_get_chain_known_model_starts_from_best():
    chain = router.get_chain("groq", "llama-3.3-70b-versatile")
    # Known model → full chain from best (index 0)
    assert chain[0] == router.CHAINS["groq"][0]
    assert "llama-3.3-70b-versatile" in chain


def test_get_chain_custom_model_prepended():
    chain = router.get_chain("groq", "my-custom-model")
    assert chain[0] == "my-custom-model"
    # Standard chain follows
    assert chain[1:] == router.CHAINS["groq"]


def test_get_chain_unknown_provider_returns_custom_only():
    chain = router.get_chain("unknown_provider", "some-model")
    assert chain == ["some-model"]


def test_get_chain_gemini_full_chain():
    chain = router.get_chain("gemini", router.CHAINS["gemini"][0])
    assert chain == router.CHAINS["gemini"]


def test_get_chain_anthropic_full_chain():
    chain = router.get_chain("anthropic", "claude-haiku-4-5")
    assert chain == router.CHAINS["anthropic"]


# ── CHAINS completeness ───────────────────────────────────────────────────────

def test_all_providers_have_chains():
    for provider in ("groq", "gemini", "anthropic", "openai"):
        assert provider in router.CHAINS
        assert len(router.CHAINS[provider]) > 0


def test_chains_have_no_duplicates():
    for provider, models in router.CHAINS.items():
        assert len(models) == len(set(models)), f"Duplicate in {provider} chain"
