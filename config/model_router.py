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
    "groq":      65,    # RPM windows reset every 60s; 65s gives a safe buffer
    "gemini":    86400,
    "anthropic": 300,
    "openai":    300,
    "nvidia":    65,
}
_DEFAULT_COOLDOWN = 300

# ── Per-model rate limits (RPM / TPM / optional RPD / optional TPD) ──────────
# Source: provider dashboards, free tier as of 2026-03
MODEL_LIMITS: dict[str, dict[str, int]] = {
    # ── Groq ──────────────────────────────────────────────────────────────────
    "moonshotai/kimi-k2-instruct":                  {"rpm": 60,  "tpm": 10_000,  "rpd":  1_000, "tpd": 300_000},
    "moonshotai/kimi-k2-instruct-0905":             {"rpm": 60,  "tpm": 10_000,  "rpd":  1_000, "tpd": 300_000},
    "openai/gpt-oss-120b":                          {"rpm": 30,  "tpm":  8_000,  "rpd":  1_000, "tpd": 200_000},
    "openai/gpt-oss-20b":                           {"rpm": 30,  "tpm":  8_000,  "rpd":  1_000, "tpd": 200_000},
    "llama-3.3-70b-versatile":                      {"rpm": 30,  "tpm": 12_000,  "rpd":  1_000, "tpd": 100_000},
    "llama-3.1-8b-instant":                         {"rpm": 30,  "tpm":  6_000,  "rpd": 14_400, "tpd": 500_000},
    "qwen/qwen3-32b":                               {"rpm": 60,  "tpm":  6_000,  "rpd":  1_000, "tpd": 500_000},
    "meta-llama/llama-4-scout-17b-16e-instruct":    {"rpm": 30,  "tpm": 30_000,  "rpd":  1_000, "tpd": 500_000},
    "groq/compound":                                {"rpm": 30,  "tpm": 70_000,  "rpd":    250},
    "groq/compound-mini":                           {"rpm": 30,  "tpm": 70_000,  "rpd":    250},
    "allam-2-7b":                                   {"rpm": 30,  "tpm":  6_000,  "rpd":  7_000, "tpd": 500_000},
    # ── Gemini Flash / next-gen ────────────────────────────────────────────────
    "gemini-2.5-flash":                             {"rpm":  5,  "tpm": 250_000, "rpd":    20},
    "gemini-2.5-flash-lite":                        {"rpm": 10,  "tpm": 250_000, "rpd":    20},
    "gemini-3-flash-preview":                       {"rpm":  5,  "tpm": 250_000, "rpd":    20},
    "gemini-3.1-flash-lite-preview":                {"rpm": 15,  "tpm": 250_000, "rpd":   500},
    # ── Gemma (Google AI Studio free tier) ────────────────────────────────────
    "gemma-3-27b-it":                               {"rpm": 30,  "tpm": 15_000,  "rpd": 14_400},
    "gemma-3-12b-it":                               {"rpm": 30,  "tpm": 15_000,  "rpd": 14_400},
    "gemma-3-4b-it":                                {"rpm": 30,  "tpm": 15_000,  "rpd": 14_400},
    # ── NVIDIA NIM ────────────────────────────────────────────────────────────
    "nvidia/llama-3.1-nemotron-ultra-253b-v1":        {"rpm": 40,  "tpm": 200_000},
}

# Pause when usage hits this fraction of any limit, then recheck
_THROTTLE_THRESHOLD = 0.80
_THROTTLE_PAUSE     = 10  # seconds to wait before rechecking

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
    if model.startswith("gemma-") or model.startswith("gemini-"):
        return "gemini"
    if model.startswith("nvidia/"):
        return "nvidia"
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


def try_acquire_slot(model: str, estimated_tokens: int = 0) -> bool:
    """
    Non-blocking capacity check + request registration.
    Returns True and records the request if under limits.
    Returns False immediately (no sleep) if at capacity.

    Use in any path where fallback to the next model is possible.
    Use acquire_slot() only when there is no fallback (e.g. single-model NVIDIA path).
    """
    limits = MODEL_LIMITS.get(model)
    if limits is None:
        return True  # unknown model — no proactive throttle, always allow

    rpm_cap = int(limits["rpm"] * _THROTTLE_THRESHOLD)
    tpm_cap = int(limits["tpm"] * _THROTTLE_THRESHOLD)
    rpd_cap = int(limits["rpd"] * _THROTTLE_THRESHOLD) if "rpd" in limits else None
    tpd_cap = int(limits["tpd"] * _THROTTLE_THRESHOLD) if "tpd" in limits else None

    now = time.time()
    u   = _get_usage(model)
    _prune_window(u, now)

    current_rpm = len(u["requests"])
    current_tpm = sum(n for _, n in u["tokens"])

    if rpd_cap is not None and u["daily_reqs"] >= rpd_cap:
        return False
    if tpd_cap is not None and u["daily_tokens"] >= tpd_cap:
        return False
    if current_rpm >= rpm_cap:
        return False
    if u["tokens"] and current_tpm + estimated_tokens >= tpm_cap:
        return False

    # Under limits — claim the request slot atomically
    u["requests"].append(now)
    u["daily_reqs"] += 1
    return True


def record_usage(model: str, tokens: int) -> None:
    """Record actual token count after a successful call."""
    if model not in MODEL_LIMITS:
        return
    u = _get_usage(model)
    now = time.time()
    u["tokens"].append((now, tokens))
    u["daily_tokens"] += tokens


# ── File extensions routed to the fastest model tier ─────────────────────────
NON_CODE_EXTENSIONS = {
    # Docs / prose
    ".md", ".txt", ".rst", ".pdf", ".docx", ".log",
    # Config / infra
    ".yml", ".yaml", ".toml", ".cfg", ".ini", ".conf",
    ".env", ".env.example", ".properties",
    # Shell / scripts
    ".sh", ".bash", ".zsh", ".fish", ".bat", ".cmd", ".ps1",
    # Web / markup
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    # Data / serialization
    ".json", ".xml", ".csv", ".tsv",
    # SQL
    ".sql",
    # Dot-files / tooling
    ".gitignore", ".gitattributes", ".editorconfig",
    ".dockerignore", ".mailmap", ".npmrc", ".yarnrc",
    # Misc
    ".license", ".changelog", ".makefile",
}

# ── File tier token thresholds (applied to full-file token counts) ────────────
TIER_TINY_TOKENS   =   500   # < 500    → tier 1
TIER_SMALL_TOKENS  = 3_000   # 500-3K   → tier 2
TIER_MEDIUM_TOKENS = 8_000   # 3K-8K    → tier 3
                              # ≥ 8K    → tier 4

# ── Base pool definitions: (provider, model) ordered best → fastest ───────────
# build_available_pools() filters to only providers with valid API keys at startup.
_POOLS_BASE: dict[str, list[tuple[str, str]]] = {
    # Non-code / config files — NVIDIA leads (200K TPM, 40 RPM), then Gemini, Groq
    "tier0": [
        ("nvidia", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),     # 200K TPM, 40 RPM
        ("gemini", "gemma-3-4b-it"),
        ("gemini", "gemma-3-27b-it"),
        ("groq",   "llama-3.1-8b-instant"),
        ("groq",   "allam-2-7b"),
    ],
    # < 500 tokens — NVIDIA leads, then Groq (low latency), Gemini fallback
    "tier1": [
        ("nvidia", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),     # 200K TPM, 40 RPM
        ("groq",   "qwen/qwen3-32b"),
        ("groq",   "openai/gpt-oss-20b"),
        ("gemini", "gemma-3-4b-it"),
        ("groq",   "allam-2-7b"),
        ("groq",   "llama-3.1-8b-instant"),
    ],
    # 500–3K tokens — NVIDIA leads, then capable standard models
    "tier2": [
        ("nvidia", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),     # 200K TPM, 40 RPM
        ("groq",   "moonshotai/kimi-k2-instruct"),
        ("groq",   "moonshotai/kimi-k2-instruct-0905"),
        ("groq",   "openai/gpt-oss-120b"),
        ("groq",   "llama-3.3-70b-versatile"),
        ("groq",   "meta-llama/llama-4-scout-17b-16e-instruct"),
        ("gemini", "gemma-3-12b-it"),
    ],
    # 3K–8K tokens — NVIDIA leads, then high-context models
    "tier3": [
        ("nvidia", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),     # 200K TPM, 40 RPM
        ("groq",   "meta-llama/llama-4-scout-17b-16e-instruct"),   # 30K TPM
        ("groq",   "groq/compound"),                               # 70K TPM
        ("gemini", "gemma-3-27b-it"),                              # 15K TPM, 30 RPM
        ("gemini", "gemini-2.5-flash-lite"),                       # 250K TPM, 10 RPM
        ("gemini", "gemini-3.1-flash-lite-preview"),               # 250K TPM, 15 RPM, 500 RPD
        ("gemini", "gemini-3-flash-preview"),                      # 250K TPM, 5 RPM
        ("groq",   "moonshotai/kimi-k2-instruct"),
        ("groq",   "moonshotai/kimi-k2-instruct-0905"),
    ],
    # ≥ 8K tokens — NVIDIA leads (200K TPM, large ctx), Gemini as overflow
    "tier4": [
        ("nvidia", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),     # 200K TPM, 40 RPM
        ("gemini", "gemini-2.5-flash"),                            # 250K TPM, established
        ("gemini", "gemini-3-flash-preview"),                      # 250K TPM, 1M ctx window
        ("gemini", "gemini-3.1-flash-lite-preview"),               # 250K TPM, 15 RPM, 500 RPD
        ("gemini", "gemini-2.5-flash-lite"),                       # 250K TPM, 10 RPM
        ("groq",   "groq/compound"),                               # 70K TPM
        ("groq",   "meta-llama/llama-4-scout-17b-16e-instruct"),   # 30K TPM
        ("groq",   "groq/compound-mini"),                          # 70K TPM
        ("gemini", "gemma-3-27b-it"),                              # 15K TPM, last resort
    ],
    # Synthesis / report generation — NVIDIA 253B leads (most capable), Gemini as overflow
    "heavy": [
        ("nvidia", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),       # 253B, 40 RPM
        ("gemini", "gemini-3-flash-preview"),                        # 1M ctx, 250K TPM
        ("gemini", "gemini-2.5-flash"),                              # established, reliable
        ("gemini", "gemini-3.1-flash-lite-preview"),                 # 15 RPM, 500 RPD
        ("groq",   "moonshotai/kimi-k2-instruct"),
        ("groq",   "moonshotai/kimi-k2-instruct-0905"),
        ("groq",   "openai/gpt-oss-120b"),
        ("groq",   "llama-3.3-70b-versatile"),
    ],
}

# Active pools — populated once at startup by build_available_pools()
_POOLS: dict[str, list[tuple[str, str]]] = {}


def build_available_pools(api_keys: dict[str, str]) -> None:
    """
    Called once at startup. Checks which providers have valid API keys and
    builds filtered tier pools — models for unavailable providers are excluded.
    """
    global _POOLS
    available = {p for p, key in api_keys.items() if key and key.strip()}
    logger.info(f"[router] Active providers: {sorted(available)}")
    for tier, pool in _POOLS_BASE.items():
        _POOLS[tier] = [(p, m) for p, m in pool if p in available]
    for tier, pool in _POOLS.items():
        names = [m for _, m in pool]
        if names:
            logger.info(f"[router] {tier} pool ({len(names)}): {names}")
        else:
            logger.warning(f"[router] {tier} pool is empty — no matching API keys")


def get_file_pool(file_path: str, token_count: int) -> list[tuple[str, str]]:
    """Return the appropriate model pool for a file based on type and size."""
    ext = ("." + file_path.rsplit(".", 1)[-1].lower()) if "." in file_path else ""
    if ext in NON_CODE_EXTENSIONS:
        return _POOLS.get("tier0") or _POOLS.get("tier1") or []
    if token_count < TIER_TINY_TOKENS:
        return _POOLS.get("tier1") or []
    elif token_count < TIER_SMALL_TOKENS:
        return _POOLS.get("tier2") or []
    elif token_count < TIER_MEDIUM_TOKENS:
        return _POOLS.get("tier3") or []
    else:
        return _POOLS.get("tier4") or []


# Cascade order per primary tier: try primary first, then adjacent tiers in order.
# If all models in the primary tier are throttled/cooling, the pool naturally
# falls through to the next tier's models without any extra waiting.
_TIER_CASCADE: dict[str, list[str]] = {
    "tier0": ["tier0", "tier1", "tier2", "tier3"],
    "tier1": ["tier1", "tier0", "tier2", "tier3"],
    "tier2": ["tier2", "tier1", "tier3", "tier0"],
    "tier3": ["tier3", "tier4", "tier2", "tier1", "tier0"],
    "tier4": ["tier4", "tier3", "tier2", "tier1"],
}


def get_file_pool_cascade(file_path: str, token_count: int) -> list[tuple[str, str]]:
    """
    Return a cascaded pool for a file — primary tier first, then fallback tiers
    in order. Deduplicates entries while preserving priority order.

    This means if all tier0 models are cooling/throttled, the pool immediately
    falls through to tier1 models, then tier2, etc. — no waiting, no wasted time.
    """
    ext = ("." + file_path.rsplit(".", 1)[-1].lower()) if "." in file_path else ""
    if ext in NON_CODE_EXTENSIONS:
        primary = "tier0"
    elif token_count < TIER_TINY_TOKENS:
        primary = "tier1"
    elif token_count < TIER_SMALL_TOKENS:
        primary = "tier2"
    elif token_count < TIER_MEDIUM_TOKENS:
        primary = "tier3"
    else:
        primary = "tier4"

    seen:   set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for tier in _TIER_CASCADE.get(primary, [primary]):
        for entry in _POOLS.get(tier, []):
            if entry not in seen:
                seen.add(entry)
                result.append(entry)
    return result


def get_heavy_pool() -> list[tuple[str, str]]:
    """Return the heavy-task pool for synthesis and report generation."""
    return _POOLS.get("heavy") or []


# ── Priority chains: best → worst ────────────────────────────────────────────
CHAINS: dict[str, list[str]] = {
    "groq": [
        "moonshotai/kimi-k2-instruct",
        "moonshotai/kimi-k2-instruct-0905",
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "groq/compound",
        "qwen/qwen3-32b",
        "openai/gpt-oss-20b",
        "groq/compound-mini",
        "allam-2-7b",
        "llama-3.1-8b-instant",
    ],
    "gemini": [
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite-preview",
        "gemini-2.5-flash-lite",
        "gemma-3-27b-it",
        "gemma-3-12b-it",
        "gemma-3-4b-it",
    ],
    "anthropic": [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ],
    "openai": [
        "o3",
        "gpt-4.5-preview",
        "gpt-4o",
        "gpt-4o-mini",
        "o1-mini",
    ],
    "nvidia": [
        "nvidia/llama-3.1-nemotron-ultra-253b-v1",
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


def is_at_capacity(model: str, estimated_tokens: int = 0) -> bool:
    """
    Non-blocking capacity check — returns True if acquire_slot would pause right now.
    Used by llm_call_async_pool to skip throttled models and fall through to the next.
    """
    limits = MODEL_LIMITS.get(model)
    if limits is None:
        return False

    rpm_cap = int(limits["rpm"] * _THROTTLE_THRESHOLD)
    tpm_cap = int(limits["tpm"] * _THROTTLE_THRESHOLD)
    rpd_cap = int(limits["rpd"] * _THROTTLE_THRESHOLD) if "rpd" in limits else None
    tpd_cap = int(limits["tpd"] * _THROTTLE_THRESHOLD) if "tpd" in limits else None

    now = time.time()
    u   = _get_usage(model)
    _prune_window(u, now)

    current_rpm = len(u["requests"])
    current_tpm = sum(n for _, n in u["tokens"])

    if rpd_cap is not None and u["daily_reqs"] >= rpd_cap:
        return True
    if tpd_cap is not None and u["daily_tokens"] >= tpd_cap:
        return True
    if current_rpm >= rpm_cap:
        return True
    if u["tokens"] and current_tpm + estimated_tokens >= tpm_cap:
        return True
    return False


def status() -> dict[str, list[dict]]:
    """Return current cooldown status of all models (for debugging)."""
    out = {}
    for provider, models in CHAINS.items():
        out[provider] = [
            {"model": m, "cooling": is_cooling(m), "remaining_s": cooling_remaining(m)}
            for m in models
        ]
    return out
