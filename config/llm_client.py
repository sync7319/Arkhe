"""
Unified LLM client for Arkhe.
All agents call: llm_call(role, system, prompt) -> str
         or:    await llm_call_async(role, system, prompt) -> str

Provider + model are resolved from .env via config/settings.py.
Never import provider SDKs directly in agent files.
"""
import asyncio
import time
import logging
from config.settings import get_model, get_api_key

logger = logging.getLogger("arkhe.llm")

MAX_RETRIES   = 3
RETRY_BACKOFF = 2

# Cached clients — instantiated once per provider, reused across all calls
_clients: dict       = {}
_async_clients: dict = {}


def _get_groq_client(api_key: str):
    if "groq" not in _clients:
        from groq import Groq
        _clients["groq"] = Groq(api_key=api_key)
    return _clients["groq"]


def _get_groq_async_client(api_key: str):
    if "groq_async" not in _async_clients:
        from groq import AsyncGroq
        _async_clients["groq_async"] = AsyncGroq(api_key=api_key)
    return _async_clients["groq_async"]


def _get_gemini_client(api_key: str):
    if "gemini" not in _clients:
        from google import genai
        _clients["gemini"] = genai.Client(api_key=api_key)
    return _clients["gemini"]


def _get_anthropic_client(api_key: str):
    if "anthropic" not in _clients:
        import anthropic
        _clients["anthropic"] = anthropic.Anthropic(api_key=api_key)
    return _clients["anthropic"]


def _get_anthropic_async_client(api_key: str):
    if "anthropic_async" not in _async_clients:
        import anthropic
        _async_clients["anthropic_async"] = anthropic.AsyncAnthropic(api_key=api_key)
    return _async_clients["anthropic_async"]


def llm_call(role: str, system: str, user_prompt: str, max_tokens: int = 4096) -> str:
    provider, model = get_model(role)
    api_key         = get_api_key(provider)
    logger.debug(f"[{role}] provider={provider} model={model}")

    retryable = _retryable_exceptions(provider)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if provider == "groq":
                return _call_groq(api_key, model, system, user_prompt, max_tokens)
            elif provider == "gemini":
                return _call_gemini(api_key, model, system, user_prompt, max_tokens)
            elif provider == "anthropic":
                return _call_anthropic(api_key, model, system, user_prompt, max_tokens)
            else:
                raise ValueError(f"Unknown provider: '{provider}'. Valid: groq | gemini | anthropic")
        except retryable as e:
            if attempt == MAX_RETRIES:
                logger.error(f"[{role}] Failed after {MAX_RETRIES} attempts: {e}")
                raise
            wait = RETRY_BACKOFF * attempt
            logger.warning(f"[{role}] Attempt {attempt} failed ({e}). Retrying in {wait}s...")
            time.sleep(wait)
        except Exception as e:
            logger.error(f"[{role}] Non-retryable error: {e}")
            raise


async def llm_call_async(role: str, system: str, user_prompt: str, max_tokens: int = 4096) -> str:
    provider, model = get_model(role)
    api_key         = get_api_key(provider)
    logger.debug(f"[{role}] provider={provider} model={model}")

    retryable = _retryable_exceptions(provider)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if provider == "groq":
                return await _call_groq_async(api_key, model, system, user_prompt, max_tokens)
            elif provider == "gemini":
                return await _call_gemini_async(api_key, model, system, user_prompt, max_tokens)
            elif provider == "anthropic":
                return await _call_anthropic_async(api_key, model, system, user_prompt, max_tokens)
            else:
                raise ValueError(f"Unknown provider: '{provider}'. Valid: groq | gemini | anthropic")
        except retryable as e:
            if attempt == MAX_RETRIES:
                logger.error(f"[{role}] Failed after {MAX_RETRIES} attempts: {e}")
                raise
            wait = RETRY_BACKOFF * attempt
            logger.warning(f"[{role}] Attempt {attempt} failed ({e}). Retrying in {wait}s...")
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error(f"[{role}] Non-retryable error: {e}")
            raise


# ── Sync call implementations ────────────────────────────────────────────────

def _call_groq(api_key, model, system, prompt, max_tokens):
    client   = _get_groq_client(api_key)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Groq returned empty content.")
    return content


def _call_gemini(api_key, model, system, prompt, max_tokens):
    from google.genai import types
    client   = _get_gemini_client(api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=0.2,
            top_p=0.95,
        ),
    )

    if not response.candidates:
        raise ValueError(f"Gemini returned no candidates. Feedback: {response.prompt_feedback}")

    candidate = response.candidates[0]
    if candidate.finish_reason.name not in ("STOP", "MAX_TOKENS"):
        raise ValueError(f"Gemini finish reason: {candidate.finish_reason.name}")

    text = response.text
    if not text or not text.strip():
        raise ValueError("Gemini returned empty text.")
    return text


def _call_anthropic(api_key, model, system, prompt, max_tokens):
    client   = _get_anthropic_client(api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason not in ("end_turn", "max_tokens"):
        raise ValueError(f"Anthropic stop reason: {response.stop_reason}")
    content = response.content[0].text
    if not content or not content.strip():
        raise ValueError("Anthropic returned empty content.")
    return content


# ── Async call implementations ───────────────────────────────────────────────

async def _call_groq_async(api_key, model, system, prompt, max_tokens):
    client   = _get_groq_async_client(api_key)
    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Groq returned empty content.")
    return content


async def _call_gemini_async(api_key, model, system, prompt, max_tokens):
    from google.genai import types
    # The sync client exposes an async interface via .aio — no separate client needed
    client   = _get_gemini_client(api_key)
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=0.2,
            top_p=0.95,
        ),
    )

    if not response.candidates:
        raise ValueError(f"Gemini returned no candidates. Feedback: {response.prompt_feedback}")

    candidate = response.candidates[0]
    if candidate.finish_reason.name not in ("STOP", "MAX_TOKENS"):
        raise ValueError(f"Gemini finish reason: {candidate.finish_reason.name}")

    text = response.text
    if not text or not text.strip():
        raise ValueError("Gemini returned empty text.")
    return text


async def _call_anthropic_async(api_key, model, system, prompt, max_tokens):
    client   = _get_anthropic_async_client(api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason not in ("end_turn", "max_tokens"):
        raise ValueError(f"Anthropic stop reason: {response.stop_reason}")
    content = response.content[0].text
    if not content or not content.strip():
        raise ValueError("Anthropic returned empty content.")
    return content


async def llm_call_async_explicit(
    provider: str, model: str, system: str, user_prompt: str, max_tokens: int = 4096
) -> str:
    """Like llm_call_async but accepts an explicit provider+model (used for complexity-based selection)."""
    api_key   = get_api_key(provider)
    logger.debug(f"[explicit] provider={provider} model={model}")

    retryable = _retryable_exceptions(provider)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if provider == "groq":
                return await _call_groq_async(api_key, model, system, user_prompt, max_tokens)
            elif provider == "gemini":
                return await _call_gemini_async(api_key, model, system, user_prompt, max_tokens)
            elif provider == "anthropic":
                return await _call_anthropic_async(api_key, model, system, user_prompt, max_tokens)
            else:
                raise ValueError(f"Unknown provider: '{provider}'. Valid: groq | gemini | anthropic")
        except retryable as e:
            if attempt == MAX_RETRIES:
                logger.error(f"[explicit] Failed after {MAX_RETRIES} attempts: {e}")
                raise
            wait = RETRY_BACKOFF * attempt
            logger.warning(f"[explicit] Attempt {attempt} failed ({e}). Retrying in {wait}s...")
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error(f"[explicit] Non-retryable error: {e}")
            raise


# ── Retry helpers ────────────────────────────────────────────────────────────

def _retryable_exceptions(provider: str):
    if provider == "groq":
        try:
            from groq import RateLimitError, APIConnectionError, APITimeoutError
            return (RateLimitError, APIConnectionError, APITimeoutError)
        except ImportError:
            pass
    elif provider == "gemini":
        try:
            from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded
            return (ResourceExhausted, ServiceUnavailable, DeadlineExceeded)
        except ImportError:
            pass
    elif provider == "anthropic":
        try:
            from anthropic import RateLimitError, APIConnectionError, APITimeoutError
            return (RateLimitError, APIConnectionError, APITimeoutError)
        except ImportError:
            pass
    return (ConnectionError, TimeoutError)
