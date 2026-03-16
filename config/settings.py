"""
Central config for Arkhe.
To switch ALL agents to Claude: set all *_PROVIDER=anthropic in .env.
To switch a single agent: change only that agent's *_PROVIDER.
Never touch agent code to swap models.
"""
import os
from dotenv import load_dotenv

load_dotenv()                        # .env — API keys + provider selection
load_dotenv("options.env", override=False)  # options.env — feature checklist

# ── API Keys ──────────────────────────────────────────────────
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
NVIDIA_API_KEY    = os.getenv("NVIDIA_API_KEY", "")

# ── Feature flags (from options.env) ──────────────────────────
CODEBASE_MAP_ENABLED        = os.getenv("CODEBASE_MAP_ENABLED",        "true").lower()  == "true"
DEPENDENCY_MAP_ENABLED      = os.getenv("DEPENDENCY_MAP_ENABLED",      "true").lower()  == "true"
EXECUTIVE_REPORT_ENABLED    = os.getenv("EXECUTIVE_REPORT_ENABLED",    "false").lower() == "true"
PR_ANALYSIS_ENABLED         = os.getenv("PR_ANALYSIS_ENABLED",         "false").lower() == "true"
PR_BASE_BRANCH              = os.getenv("PR_BASE_BRANCH",              "main")
SECURITY_AUDIT_ENABLED      = os.getenv("SECURITY_AUDIT_ENABLED",      "false").lower() == "true"
DEAD_CODE_DETECTION_ENABLED = os.getenv("DEAD_CODE_DETECTION_ENABLED", "false").lower() == "true"
TEST_GAP_ANALYSIS_ENABLED   = os.getenv("TEST_GAP_ANALYSIS_ENABLED",   "false").lower() == "true"
TEST_SCAFFOLDING_ENABLED    = os.getenv("TEST_SCAFFOLDING_ENABLED",    "false").lower() == "true"
COMPLEXITY_HEATMAP_ENABLED  = os.getenv("COMPLEXITY_HEATMAP_ENABLED",  "false").lower() == "true"

# ── Cost gate ─────────────────────────────────────────────────
# false (default) → all roles use cheap models — safe for testing / free-tier runs
# true            → synthesis uses Sonnet; executive report uses Opus or Sonnet by complexity
#                   traversal always stays on cheap models regardless of this flag
EXPENSIVE_MODELS_ALLOWED = os.getenv("EXPENSIVE_MODELS_ALLOWED", "false").lower() == "true"
REFACTOR_ENABLED         = os.getenv("REFACTOR_ENABLED",         "false").lower() == "true"
REFACTOR_SPEED           = os.getenv("REFACTOR_SPEED",           "thorough")  # thorough | fast

# Token count at which a repo is considered "large" (affects Opus vs Sonnet for executive report)
try:
    COMPLEXITY_THRESHOLD_TOKENS = int(os.getenv("COMPLEXITY_THRESHOLD_TOKENS", "50000"))
except (ValueError, TypeError):
    COMPLEXITY_THRESHOLD_TOKENS = 50000

# ── Provider selection per role ───────────────────────────────
TRAVERSAL_PROVIDER = os.getenv("TRAVERSAL_PROVIDER", "groq")
REPORT_PROVIDER    = os.getenv("REPORT_PROVIDER",    "gemini")
EXECUTIVE_PROVIDER = os.getenv("EXECUTIVE_PROVIDER", "anthropic")
REFACTOR_PROVIDER  = os.getenv("REFACTOR_PROVIDER",  "groq")

# ── Cheap models (used for traversal always; used for all roles when EXPENSIVE=false) ──────
CHEAP_MODELS = {
    "groq":      {"traversal": "openai/gpt-oss-20b",  "report": "llama-3.1-8b-instant", "refactor": "llama-3.1-8b-instant"},
    "gemini":    {"traversal": "gemma-3-27b-it",       "report": "gemma-3-27b-it",       "refactor": "gemma-3-27b-it"},
    "anthropic": {"traversal": "claude-haiku-4-5",     "report": "claude-haiku-4-5",     "refactor": "claude-haiku-4-5"},
}

# ── Premium models (used for report synthesis when EXPENSIVE=true) ───────────────────────
# Traversal and refactor are intentionally absent — per-file work never needs heavy models
PREMIUM_MODELS = {
    "groq":      {"report": "llama-3.3-70b-versatile"},
    "gemini":    {"report": "gemma-3-27b-it"},
    "anthropic": {"report": "claude-sonnet-4-6"},
}

# ── Executive report models (only when EXPENSIVE=true) ───────────────────────────────────
# large = total repo tokens >= COMPLEXITY_THRESHOLD_TOKENS → use most capable model
# small = below threshold → use mid-tier
EXECUTIVE_MODELS = {
    "anthropic": {"large": "claude-opus-4-6",         "small": "claude-sonnet-4-6"},
    "groq":      {"large": "llama-3.3-70b-versatile", "small": "llama-3.3-70b-versatile"},
    "gemini":    {"large": "gemma-3-27b-it",           "small": "gemma-3-27b-it"},
}

VALID_PROVIDERS = {"groq", "gemini", "anthropic", "openai", "nvidia"}
VALID_ROLES     = {"traversal", "report", "refactor"}


def get_model(role: str) -> tuple[str, str]:
    if role not in VALID_ROLES:
        raise ValueError(f"Unknown role: '{role}'. Valid: {VALID_ROLES}")
    provider_map = {
        "traversal": TRAVERSAL_PROVIDER,
        "report":    REPORT_PROVIDER,
        "refactor":  REFACTOR_PROVIDER,
    }
    provider = provider_map[role]
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider: '{provider}'. Valid: {VALID_PROVIDERS}")

    env_override = os.getenv(f"{role.upper()}_MODEL")
    if env_override:
        return provider, env_override

    # Traversal and refactor always cheap — per-file work never needs heavy models
    if role in ("traversal", "refactor") or not EXPENSIVE_MODELS_ALLOWED:
        return provider, CHEAP_MODELS[provider][role]

    return provider, PREMIUM_MODELS[provider][role]


def get_executive_model(total_tokens: int) -> tuple[str, str]:
    """Select provider+model for the executive Word report based on repo complexity and cost gate."""
    provider = EXECUTIVE_PROVIDER
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider: '{provider}'. Valid: {VALID_PROVIDERS}")

    env_override = os.getenv("EXECUTIVE_MODEL")
    if env_override:
        return provider, env_override

    if not EXPENSIVE_MODELS_ALLOWED:
        return provider, CHEAP_MODELS[provider]["report"]

    size = "large" if total_tokens >= COMPLEXITY_THRESHOLD_TOKENS else "small"
    return provider, EXECUTIVE_MODELS[provider][size]


_user_chain_cache: "list[tuple[str, str, str]] | None | bool" = False  # False = unparsed


def get_user_chain() -> "list[tuple[str, str, str]] | None":
    """
    BYOK fallback chain — user-defined priority list of (provider, model, api_key).

    Set ARKHE_CHAIN in .env:
        ARKHE_CHAIN=groq:moonshotai/kimi-k2-instruct:gsk_xxx,gemini:gemini-2.5-pro:AIza_yyy

    Each entry is  provider:model:api_key  separated by commas.
    When set, ALL roles use this chain — Arkhe's hardcoded chains are ignored.
    When not set (default / server mode), Arkhe manages model selection itself.

    Returns a list of (provider, model, api_key) tuples, or None if not configured.
    """
    global _user_chain_cache
    if _user_chain_cache is not False:
        return _user_chain_cache  # type: ignore[return-value]

    raw = os.getenv("ARKHE_CHAIN", "").strip()
    if not raw:
        _user_chain_cache = None
        return None

    entries: list[tuple[str, str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        pieces = part.split(":", 2)
        if len(pieces) != 3:
            continue
        provider, model, key = (p.strip() for p in pieces)
        if provider in VALID_PROVIDERS and model and key:
            entries.append((provider, model, key))

    _user_chain_cache = entries if entries else None
    return _user_chain_cache


def get_api_key(provider: str) -> str:
    keys = {
        "groq":      GROQ_API_KEY,
        "gemini":    GEMINI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "openai":    OPENAI_API_KEY,
        "nvidia":    NVIDIA_API_KEY,
    }
    key = keys.get(provider, "")
    if not key:
        raise ValueError(
            f"No API key found for provider '{provider}'. "
            f"Set {provider.upper()}_API_KEY in your .env file."
        )
    return key


# ── Scanner settings ──────────────────────────────────────────
OUTPUT_DIR           = os.getenv("OUTPUT_DIR", "docs")
MAX_FILE_SIZE_BYTES  = 1_000_000
MAX_FILE_TOKENS      = 50_000

IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "coverage", ".pytest_cache",
}
IGNORE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3",
    ".zip", ".tar", ".gz", ".lock", ".bin", ".exe", ".pyc",
    ".docx", ".xlsx", ".pdf", ".env",
}
