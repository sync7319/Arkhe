"""
Central config for Arkhe.
To switch ALL agents to Claude: set all *_PROVIDER=anthropic in .env.
To switch a single agent: change only that agent's *_PROVIDER.
Never touch agent code to swap models.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Cost gate ─────────────────────────────────────────────────
# false (default) → all roles use cheap models — safe for testing / free-tier runs
# true            → synthesis uses Sonnet; executive report uses Opus or Sonnet by complexity
#                   traversal always stays on cheap models regardless of this flag
EXPENSIVE_MODELS_ALLOWED = os.getenv("EXPENSIVE_MODELS_ALLOWED", "false").lower() == "true"

# Token count at which a repo is considered "large" (affects Opus vs Sonnet for executive report)
COMPLEXITY_THRESHOLD_TOKENS = int(os.getenv("COMPLEXITY_THRESHOLD_TOKENS", "50000"))

# ── Provider selection per role ───────────────────────────────
TRAVERSAL_PROVIDER = os.getenv("TRAVERSAL_PROVIDER", "groq")
REPORT_PROVIDER    = os.getenv("REPORT_PROVIDER",    "gemini")
EXECUTIVE_PROVIDER = os.getenv("EXECUTIVE_PROVIDER", "anthropic")

# ── Cheap models (used for traversal always; used for all roles when EXPENSIVE=false) ──────
CHEAP_MODELS = {
    "groq":      {"traversal": "openai/gpt-oss-20b",   "report": "llama-3.1-8b-instant"},
    "gemini":    {"traversal": "gemini-2.0-flash",      "report": "gemini-2.0-flash"},
    "anthropic": {"traversal": "claude-haiku-4-5",      "report": "claude-haiku-4-5"},
}

# ── Premium models (used for report synthesis when EXPENSIVE=true) ───────────────────────
# Traversal is intentionally absent — file-level analysis never needs a heavy model
PREMIUM_MODELS = {
    "groq":      {"report": "llama-3.3-70b-versatile"},
    "gemini":    {"report": "gemini-2.0-flash"},
    "anthropic": {"report": "claude-sonnet-4-6"},
}

# ── Executive report models (only when EXPENSIVE=true) ───────────────────────────────────
# large = total repo tokens >= COMPLEXITY_THRESHOLD_TOKENS → use most capable model
# small = below threshold → use mid-tier
EXECUTIVE_MODELS = {
    "anthropic": {"large": "claude-opus-4-6",         "small": "claude-sonnet-4-6"},
    "groq":      {"large": "llama-3.3-70b-versatile", "small": "llama-3.3-70b-versatile"},
    "gemini":    {"large": "gemini-2.0-flash",         "small": "gemini-2.0-flash"},
}

VALID_PROVIDERS = {"groq", "gemini", "anthropic"}
VALID_ROLES     = {"traversal", "report"}


def get_model(role: str) -> tuple[str, str]:
    if role not in VALID_ROLES:
        raise ValueError(f"Unknown role: '{role}'. Valid: {VALID_ROLES}")
    provider_map = {
        "traversal": TRAVERSAL_PROVIDER,
        "report":    REPORT_PROVIDER,
    }
    provider = provider_map[role]
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider: '{provider}'. Valid: {VALID_PROVIDERS}")

    env_override = os.getenv(f"{role.upper()}_MODEL")
    if env_override:
        return provider, env_override

    # Traversal always cheap — file-level analysis doesn't need heavy models
    if role == "traversal" or not EXPENSIVE_MODELS_ALLOWED:
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


def get_api_key(provider: str) -> str:
    keys = {
        "groq":      GROQ_API_KEY,
        "gemini":    GEMINI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
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
}
