"""
Model fallback router — automatic downgrade chain with 10-minute cooldown.

When a model hits a rate limit or quota error, it is marked as cooling down
for COOLDOWN_SECONDS. The next call for that provider automatically tries
the next model in the priority chain (best → worst). After the cooldown
expires the model is eligible again.

Priority chains are ranked best → worst by capability.
Chains are defined here; providers/roles remain configured via .env.
"""
import time
import logging

logger = logging.getLogger("arkhe.router")

COOLDOWN_SECONDS = 600  # 10 minutes

# ── Priority chains: best → worst ────────────────────────────────────────────
CHAINS: dict[str, list[str]] = {
    "groq": [
        "moonshotai/kimi-k2-instruct",          # 671B MoE — most capable
        "qwen/qwen3-32b",                        # Qwen 3 32B
        "openai/gpt-oss-120b",                   # 120B
        "llama-3.3-70b-versatile",               # reliable 70B
        "meta-llama/llama-4-maverick-17b-128e-instruct",  # Llama 4 MoE
        "meta-llama/llama-4-scout-17b-16e-instruct",      # lighter MoE
        "openai/gpt-oss-20b",                    # 20B
        "llama-3.1-8b-instant",                  # smallest / fastest fallback
    ],
    "gemini": [
        "gemini-2.5-pro",                        # most capable
        "gemini-2.5-flash",                      # fast + strong
        "gemini-2.0-flash",                      # reliable baseline
        "gemini-2.5-flash-lite",                 # lighter
        "gemini-2.0-flash-lite",                 # lightest fallback
    ],
    "anthropic": [
        "claude-opus-4-6",                       # most capable
        "claude-sonnet-4-6",                     # balanced
        "claude-haiku-4-5",                      # fastest / cheapest
    ],
}

# ── In-memory cooldown state ──────────────────────────────────────────────────
_cooldowns: dict[str, float] = {}  # model → unix timestamp when cooldown expires


def is_cooling(model: str) -> bool:
    return time.time() < _cooldowns.get(model, 0)


def cooling_remaining(model: str) -> int:
    """Seconds remaining in cooldown, 0 if not cooling."""
    return max(0, int(_cooldowns.get(model, 0) - time.time()))


def mark_cooling(model: str) -> None:
    _cooldowns[model] = time.time() + COOLDOWN_SECONDS
    logger.warning(
        f"[router] '{model}' rate-limited — cooling for {COOLDOWN_SECONDS // 60} min"
    )


def get_chain(provider: str, preferred: str) -> list[str]:
    """
    Return the fallback chain for a provider starting from the preferred model.
    If the preferred model is not in the chain (e.g. a custom .env override),
    it is prepended so it is still tried first.

    Args:
        provider:  Provider name (groq | gemini | anthropic)
        preferred: Model to start from

    Returns:
        Ordered list of models to try, best first.
    """
    chain = CHAINS.get(provider, [])
    if preferred in chain:
        idx = chain.index(preferred)
        return chain[idx:]      # start from preferred, fall down the list
    return [preferred] + chain  # custom model first, then standard chain


def status() -> dict[str, list[dict]]:
    """Return current status of all models (for debugging)."""
    out = {}
    for provider, models in CHAINS.items():
        out[provider] = [
            {"model": m, "cooling": is_cooling(m), "remaining_s": cooling_remaining(m)}
            for m in models
        ]
    return out
