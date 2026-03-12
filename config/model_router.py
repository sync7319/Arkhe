"""
Model fallback router — persistent cooldown chain with daily reset.

When a model hits a rate limit, it is marked as cooling for COOLDOWN_SECONDS.
Cooldowns are persisted to SQLite so they survive process restarts — a model
that was rate-limited 3 minutes ago is still cooling in the next run.

Daily reset: the first run of each calendar day clears all cooldowns so the
full chain (best → worst) is available fresh at the start of every day.

Priority chains are ranked best → worst by capability + context window.
Add new models to the top of the relevant chain to try them first.

Gemma throttle: proactive RPM/TPM/TPD tracking keeps usage under 2/3 of each
limit. When a window is full the call is held until it clears. When the daily
token budget is exhausted the model is marked cooling for the rest of the day.
"""
import asyncio
import time
import logging
from datetime import date

logger = logging.getLogger("arkhe.router")

# Per-provider cooldowns:
# Groq   → 90s  (per-minute limits reset in 60s; 90s gives a safe buffer)
# Gemini → 24h  (Gemma free tier has strict daily quotas)
COOLDOWN_SECONDS: dict[str, int] = {
    "groq":      90,
    "gemini":    86400,
    "anthropic": 300,
    "openai":    300,
}
_DEFAULT_COOLDOWN = 300

# ── Per-model rate limits (RPM / TPM / optional RPD / optional TPD) ──────────
# Source: provider dashboards, free tier as of 2026-03
MODEL_LIMITS: dict[str, dict[str, int]] = {
    # Groq
    "moonshotai/kimi-k2-instruct":          {"rpm": 60,  "tpm": 10_000, "rpd": 1_000},
    "moonshotai/kimi-k2-instruct-0905":     {"rpm": 60,  "tpm": 10_000, "rpd": 1_000},
    "openai/gpt-oss-120b":                  {"rpm": 30,  "tpm":  8_000, "rpd": 1_000},
    "llama-3.3-70b-versatile":              {"rpm": 30,  "tpm": 12_000, "rpd": 1_000},
    "qwen/qwen3-32b":                       {"rpm": 60,  "tpm":  6_000, "rpd": 1_000},
    "openai/gpt-oss-20b":                   {"rpm": 30,  "tpm":  8_000, "rpd": 1_000},
    "llama-3.1-8b-instant":                 {"rpm": 30,  "tpm":  6_000, "rpd": 14_400},
    # Gemini Flash (executive report only)
    "gemini-2.5-flash":                     {"rpm":  5,  "tpm": 250_000, "rpd": 20},
    "gemini-2.5-flash-lite":                {"rpm": 10,  "tpm": 250_000, "rpd": 20},
    # Gemma (Google AI Studio free tier)
    "gemma-3-27b-it":                       {"rpm": 30,  "tpm": 15_000, "tpd": 14_400},
    "gemma-3-12b-it":                       {"rpm": 30,  "tpm": 15_000, "tpd": 14_400},
    "gemma-3-4b-it":                        {"rpm": 30,  "tpm": 15_000, "tpd": 14_400},
}

# Pause when usage hits this fraction of any limit, then recheck
_THROTTLE_THRESHOLD = 0.90
_THROTTLE_PAUSE     = 25  # seconds to wait before rechecking

# ── Per-model usage state (in-memory sliding windows) ────────────────────────
_usage: dict[str, dict] = {}


def _get_usage(model: str) -> dict:
    if model not in _usage:
        _usage[model] = {
            "requests":     [],   # list of float timestamps (last 60 s)
            "tokens":       [],   # list of (timestamp, token_count) (last 60 s)
            "daily_reqs":   0,
            "daily_tokens": 0,
            "daily_date":   date.today(),
        }
    u = _usage[model]
    if u["daily_date"] != date.today():
        u["daily_reqs"]   = 0
        u["daily_tokens"] = 0
        u["daily_date"]   = date.today()
    return u


def _prune_window(u: dict, now: float) -> None:
    cutoff = now - 60.0
    u["requests"] = [t for t in u["requests"] if t > cutoff]
    u["tokens"]   = [(t, n) for t, n in u["tokens"] if t > cutoff]


def _provider_for(model: str) -> str:
    if model.startswith("gemma-"):
        return "gemini"
    return "groq"


async def acquire_slot(model: str, estimated_tokens: int = 0) -> None:
    """
    Pause at 90% of RPM, TPM, RPD, or TPD — then recheck every 25 seconds
    until bandwidth is available. If the daily limit is fully exhausted,
    marks the model cooling for the rest of the day and raises RuntimeError
    so the caller falls back to the next model.
    """
    limits = MODEL_LIMITS.get(model)
    if limits is None:
        return  # unknown model — no proactive throttle

    rpm_cap = int(limits["rpm"] * _THROTTLE_THRESHOLD)
    tpm_cap = int(limits["tpm"] * _THROTTLE_THRESHOLD)
    rpd_cap = int(limits["rpd"] * _THROTTLE_THRESHOLD) if "rpd" in limits else None
    tpd_cap = int(limits["tpd"] * _THROTTLE_THRESHOLD) if "tpd" in limits else None
    provider = _provider_for(model)

    while True:
        now = time.time()
        u   = _get_usage(model)
        _prune_window(u, now)

        current_rpm = len(u["requests"])
        current_tpm = sum(n for _, n in u["tokens"])

        # Daily hard limits — mark cooling and bail if fully exhausted
        if rpd_cap is not None and u["daily_reqs"] >= rpd_cap:
            logger.warning(f"[throttle] {model} daily request limit reached — blocking")
            mark_cooling(model, provider)
            raise RuntimeError(f"{model} daily request limit exhausted")
        if tpd_cap is not None and u["daily_tokens"] >= tpd_cap:
            logger.warning(f"[throttle] {model} daily token limit reached — blocking")
            mark_cooling(model, provider)
            raise RuntimeError(f"{model} daily token limit exhausted")

        # RPM — pause and recheck
        if current_rpm >= rpm_cap:
            logger.info(f"[throttle] {model} RPM at {current_rpm}/{limits['rpm']} (90%) — pausing {_THROTTLE_PAUSE}s")
            await asyncio.sleep(_THROTTLE_PAUSE)
            continue

        # TPM — pause and recheck (only if we have recorded usage to compare against)
        if u["tokens"] and current_tpm + estimated_tokens >= tpm_cap:
            logger.info(f"[throttle] {model} TPM at {current_tpm}/{limits['tpm']} (90%) — pausing {_THROTTLE_PAUSE}s")
            await asyncio.sleep(_THROTTLE_PAUSE)
            continue

        # Under 90% — claim the request slot and proceed
        u["requests"].append(now)
        u["daily_reqs"] += 1
        break


def record_usage(model: str, tokens: int) -> None:
    """Record actual token count after a successful call."""
    if model not in MODEL_LIMITS:
        return
    u = _get_usage(model)
    now = time.time()
    u["tokens"].append((now, tokens))
    u["daily_tokens"] += tokens


# ── Groq multi-model groups ───────────────────────────────────────────────────
# Large files / synthesis: rotate between both kimi-k2 variants to spread RPM
GROQ_KIMI = [
    "moonshotai/kimi-k2-instruct",
    "moonshotai/kimi-k2-instruct-0905",
]
# Regular code files: rotate across three strong models
GROQ_STANDARD = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
]
# Non-code docs (README, txt, etc.) — fast, minimal analysis needed
GROQ_FAST = "llama-3.1-8b-instant"

# File extensions treated as non-code docs → fast model
NON_CODE_EXTENSIONS = {
    ".md", ".txt", ".rst", ".pdf", ".docx", ".log",
    ".license", ".changelog", ".gitignore", ".gitattributes",
    ".editorconfig", ".dockerignore", ".mailmap",
}
LARGE_FILE_TOKEN_THRESHOLD = 3_000  # tokens — route to kimi above this

# Rotation indices (in-memory, reset each process)
_kimi_idx: int = 0
_standard_idx: int = 0


def _next_available(models: list[str], idx: int) -> tuple[str, int]:
    """Return the next non-cooling model in a group and advance the index."""
    n = len(models)
    for offset in range(n):
        m = models[(idx + offset) % n]
        if not is_cooling(m):
            return m, (idx + offset + 1) % n
    # All cooling — return next anyway; the call will 429 and fall back normally
    return models[idx % n], (idx + 1) % n


def get_groq_file_model(file_path: str, token_count: int) -> str:
    """Pick the right Groq model for a file based on type and size."""
    global _kimi_idx, _standard_idx
    ext = ("." + file_path.rsplit(".", 1)[-1].lower()) if "." in file_path else ""

    if ext in NON_CODE_EXTENSIONS:
        return GROQ_FAST

    if token_count >= LARGE_FILE_TOKEN_THRESHOLD:
        model, _kimi_idx = _next_available(GROQ_KIMI, _kimi_idx)
        return model

    model, _standard_idx = _next_available(GROQ_STANDARD, _standard_idx)
    return model


def get_groq_report_model() -> str:
    """For synthesis / report generation → kimi-k2 rotation."""
    global _kimi_idx
    model, _kimi_idx = _next_available(GROQ_KIMI, _kimi_idx)
    return model


# ── Priority chains: best → worst ────────────────────────────────────────────
CHAINS: dict[str, list[str]] = {
    "groq": [
        "moonshotai/kimi-k2-instruct",
        "moonshotai/kimi-k2-instruct-0905",
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "qwen/qwen3-32b",
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
    ],
    "gemini": [
        "gemini-2.5-flash",      # executive report primary — 250K TPM, 20 RPD
        "gemini-2.5-flash-lite", # fallback if flash RPD exhausted
        "gemma-3-27b-it",        # last resort — 15K TPM, 14.4K TPD
        "gemma-3-12b-it",
        "gemma-3-4b-it",
    ],
    "anthropic": [
        "claude-opus-4-6",         # most capable
        "claude-sonnet-4-6",       # balanced
        "claude-haiku-4-5",        # fastest / cheapest
    ],
    "openai": [
        "o3",                      # most capable reasoning
        "gpt-4.5-preview",         # largest GPT
        "gpt-4o",                  # flagship multimodal
        "gpt-4o-mini",             # fast + cheap
        "o1-mini",                 # lightweight reasoning
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


def mark_cooling(model: str, provider: str = "") -> None:
    duration   = COOLDOWN_SECONDS.get(provider, _DEFAULT_COOLDOWN) if provider else _DEFAULT_COOLDOWN
    cool_until = time.time() + duration
    _cooldowns[model] = cool_until
    if duration >= 3600:
        logger.warning(f"[router] '{model}' rate-limited — cooling for {duration // 3600}h")
    else:
        logger.warning(f"[router] '{model}' rate-limited — cooling for {duration}s")

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
