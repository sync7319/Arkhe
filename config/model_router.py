"""
Model fallback router — persistent cooldown chain with daily reset.

When a model hits a rate limit, it is marked as cooling for COOLDOWN_SECONDS.
Cooldowns are persisted to SQLite so they survive process restarts — a model
that was rate-limited 3 minutes ago is still cooling in the next run.

Daily reset: the first run of each calendar day clears all cooldowns so the
full chain (best → worst) is available fresh at the start of every day.

Priority chains are ranked best → worst by capability + context window.
Add new models to the top of the relevant chain to try them first.
"""
import time
import logging
from datetime import date

logger = logging.getLogger("arkhe.router")

COOLDOWN_SECONDS = 600  # 10 minutes

# ── Priority chains: best → worst ────────────────────────────────────────────
CHAINS: dict[str, list[str]] = {
    "groq": [
        "moonshotai/kimi-k2-instruct",                    # 671B MoE — most capable
        "qwen/qwen3-32b",                                  # Qwen 3 32B
        "openai/gpt-oss-120b",                             # 120B
        "llama-3.3-70b-versatile",                         # reliable 70B
        "meta-llama/llama-4-maverick-17b-128e-instruct",  # Llama 4 MoE
        "meta-llama/llama-4-scout-17b-16e-instruct",      # lighter MoE
        "openai/gpt-oss-20b",                              # 20B
        "llama-3.1-8b-instant",                            # smallest / fastest fallback
    ],
    "gemini": [
        "gemini-3.0-flash",        # newest — highest capability, 250K TPM
        "gemini-2.5-pro",          # most capable 2.5
        "gemini-2.5-flash",        # fast + strong, 250K TPM
        "gemini-2.0-flash",        # reliable baseline
        "gemini-2.5-flash-lite",   # lighter
        "gemini-2.0-flash-lite",   # lightest text model
        "gemma-3-27b-it",          # largest Gemma 3 — 15K TPM
        "gemma-3-12b-it",          # good quality Gemma
        "gemma-3-4b-it",           # medium Gemma
        "gemma-3-2b-it",           # small Gemma
        "gemma-3-1b-it",           # smallest / last resort
    ],
    "anthropic": [
        "claude-opus-4-6",         # most capable
        "claude-sonnet-4-6",       # balanced
        "claude-haiku-4-5",        # fastest / cheapest
    ],
}

# ── In-memory cooldown state (populated from DB on startup) ──────────────────
_cooldowns: dict[str, float] = {}   # model → unix timestamp when cooldown expires


# ── DB-backed persistence ─────────────────────────────────────────────────────

def restore_from_db(db) -> int:
    """
    Load persisted cooldowns from DB into in-memory state.
    Also triggers the daily reset if it's a new calendar day.
    Returns number of cooling models restored.
    Call this once from main.py after init_db().
    """
    reset = db.reset_daily_if_needed()
    if reset:
        logger.info("[router] New day — all model cooldowns reset")
        _cooldowns.clear()
        return 0

    rows = db.get_all_cooldowns()
    now  = time.time()
    restored = 0
    for model, cool_until in rows:
        if cool_until > now:
            _cooldowns[model] = cool_until
            restored += 1
        # expired entries are ignored — they'll be cleaned up next save

    if restored:
        logger.info(f"[router] Restored {restored} cooling model(s) from DB")
    return restored


# ── Cooldown operations ───────────────────────────────────────────────────────

def is_cooling(model: str) -> bool:
    return time.time() < _cooldowns.get(model, 0)


def cooling_remaining(model: str) -> int:
    """Seconds remaining in cooldown, 0 if not cooling."""
    return max(0, int(_cooldowns.get(model, 0) - time.time()))


def mark_cooling(model: str) -> None:
    cool_until = time.time() + COOLDOWN_SECONDS
    _cooldowns[model] = cool_until
    logger.warning(f"[router] '{model}' rate-limited — cooling for {COOLDOWN_SECONDS // 60} min")

    # Persist to DB if available
    try:
        from cache.db import get_db
        get_db().set_cooling(model, cool_until)
    except RuntimeError:
        pass  # DB not yet initialized (e.g. during early startup)


# ── Chain navigation ──────────────────────────────────────────────────────────

def get_chain(provider: str, preferred: str) -> list[str]:
    """
    Return the full fallback chain for a provider, always starting from the
    best available model (index 0).

    If `preferred` is a custom model not in the chain (e.g. a manual .env
    override), it is prepended so it is tried before the standard chain.
    Otherwise the full chain is returned as-is — new, better models added
    to the top of CHAINS will always be tried before falling down to cheaper
    ones, regardless of what CHEAP_MODELS is configured to.
    """
    chain = CHAINS.get(provider, [])
    if preferred in chain:
        return chain          # start from best (index 0), not from preferred
    return [preferred] + chain  # custom override: try it first, then full chain


def status() -> dict[str, list[dict]]:
    """Return current cooldown status of all models (for debugging)."""
    out = {}
    for provider, models in CHAINS.items():
        out[provider] = [
            {"model": m, "cooling": is_cooling(m), "remaining_s": cooling_remaining(m)}
            for m in models
        ]
    return out
