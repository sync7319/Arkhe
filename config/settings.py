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

# ── Provider selection per role ───────────────────────────────
TRAVERSAL_PROVIDER = os.getenv("TRAVERSAL_PROVIDER", "groq")
REPORT_PROVIDER    = os.getenv("REPORT_PROVIDER",    "gemini")

# ── Default models per provider ───────────────────────────────
DEFAULT_MODELS = {
    "groq": {
        "traversal": "openai/gpt-oss-20b",
        "report":    "llama-3.3-70b-versatile",
    },
    "gemini": {
        "traversal": "gemini-2.0-flash",
        "report":    "gemini-2.0-flash",
    },
    "anthropic": {
        "traversal": "claude-haiku-4-5",
        "report":    "claude-sonnet-4-5",
    },
}

VALID_PROVIDERS = {"groq", "gemini", "anthropic"}
VALID_ROLES     = {"traversal", "report"}


def get_model(role: str) -> tuple:
    if role not in VALID_ROLES:
        raise ValueError(f"Unknown role: '{role}'. Valid: {VALID_ROLES}")
    provider_map = {
        "traversal": TRAVERSAL_PROVIDER,
        "report":    REPORT_PROVIDER,
    }
    provider = provider_map[role]
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider: '{provider}'. Valid: {VALID_PROVIDERS}")
    env_override_key = f"{role.upper()}_MODEL"
    model = os.getenv(env_override_key) or DEFAULT_MODELS[provider][role]
    return provider, model


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
