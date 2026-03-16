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


class _GeminiRateLimitError(Exception):
    """Raised only for Gemini 429 / quota errors — NOT for 400 invalid-argument errors."""


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


def _get_openai_client(api_key: str):
    if "openai" not in _clients:
        from openai import OpenAI
        _clients["openai"] = OpenAI(api_key=api_key)
    return _clients["openai"]


def _get_openai_async_client(api_key: str):
    if "openai_async" not in _async_clients:
        from openai import AsyncOpenAI
        _async_clients["openai_async"] = AsyncOpenAI(api_key=api_key)
    return _async_clients["openai_async"]


def _get_nvidia_async_client(api_key: str):
    if "nvidia_async" not in _async_clients:
        from openai import AsyncOpenAI
        _async_clients["nvidia_async"] = AsyncOpenAI(
            api_key=api_key,
            base_url="https://integrate.api.nvidia.com/v1",
        )
    return _async_clients["nvidia_async"]


def llm_call(role: str, system: str, user_prompt: str, max_tokens: int = 4096) -> str:
    provider, model = get_model(role)
    api_key         = get_api_key(provider)
    logger.debug(f"[{role}] provider={provider} model={model}")

    retryable = _rate_limit_exceptions(provider) + _transient_exceptions(provider)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if provider == "groq":
                return _call_groq(api_key, model, system, user_prompt, max_tokens)
            elif provider == "gemini":
                return _call_gemini(api_key, model, system, user_prompt, max_tokens)
            elif provider == "anthropic":
                return _call_anthropic(api_key, model, system, user_prompt, max_tokens)
            elif provider == "openai":
                return _call_openai(api_key, model, system, user_prompt, max_tokens)
            else:
                raise ValueError(f"Unknown provider: '{provider}'. Valid: groq | gemini | anthropic | openai")
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
    from config.settings import get_user_chain
    from config.model_router import get_chain, is_cooling, mark_cooling

    user_chain = get_user_chain()
    if user_chain:
        # BYOK mode — user defined their own (provider, model, api_key) priority list
        return await _call_user_chain(user_chain, system, user_prompt, max_tokens, role)

    # Server / default mode — Arkhe manages model selection via hardcoded chains
    provider, preferred = get_model(role)
    api_key             = get_api_key(provider)
    chain               = get_chain(provider, preferred)
    rate_limit_exc      = _rate_limit_exceptions(provider)
    transient_exc       = _transient_exceptions(provider)

    for model in chain:
        if is_cooling(model):
            logger.debug(f"[{role}] {model} cooling — skipping")
            continue
        logger.debug(f"[{role}] provider={provider} model={model}")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await _dispatch_async(provider, model, api_key, system, user_prompt, max_tokens)
            except rate_limit_exc as e:
                mark_cooling(model, provider)
                logger.warning(f"[{role}] Rate limit on {model} — falling back")
                break  # try next model in chain
            except transient_exc as e:
                if attempt == MAX_RETRIES:
                    logger.warning(f"[{role}] {model} failed after {MAX_RETRIES} transient errors — falling back")
                    break
                wait = RETRY_BACKOFF * attempt
                logger.warning(f"[{role}] Transient error attempt {attempt}: {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
            except Exception as e:
                logger.error(f"[{role}] Non-retryable error on {model}: {e}")
                raise

    raise RuntimeError(f"[{role}] All models for '{provider}' are rate-limited or failed")


async def _call_user_chain(
    chain: list[tuple[str, str, str]],
    system: str,
    user_prompt: str,
    max_tokens: int,
    role: str,
) -> str:
    """BYOK mode — iterate user-defined (provider, model, api_key) list with cooldown fallback."""
    from config.model_router import is_cooling, mark_cooling

    for provider, model, api_key in chain:
        if is_cooling(model):
            logger.debug(f"[{role}] {model} cooling — skipping")
            continue
        logger.debug(f"[{role}] user-chain: provider={provider} model={model}")

        rate_limit_exc = _rate_limit_exceptions(provider)
        transient_exc  = _transient_exceptions(provider)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await _dispatch_async(provider, model, api_key, system, user_prompt, max_tokens)
            except rate_limit_exc:
                mark_cooling(model, provider)
                logger.warning(f"[{role}] Rate limit on {model} — trying next in ARKHE_CHAIN")
                break
            except transient_exc as e:
                if attempt == MAX_RETRIES:
                    logger.warning(f"[{role}] {model} failed after {MAX_RETRIES} transient errors — trying next")
                    break
                wait = RETRY_BACKOFF * attempt
                logger.warning(f"[{role}] Transient error attempt {attempt}: {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
            except Exception as e:
                logger.error(f"[{role}] Non-retryable error on {model}: {e}")
                raise

    raise RuntimeError(f"[{role}] All models in ARKHE_CHAIN are rate-limited or failed")


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
    # Gemma models don't support system_instruction — prepend to user prompt instead
    is_gemma = model.startswith("gemma-")
    contents = f"{system}\n\n{prompt}" if is_gemma else prompt
    config   = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=0.2,
        top_p=0.95,
        **({}  if is_gemma else {"system_instruction": system}),
    )
    client   = _get_gemini_client(api_key)
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
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


def _call_openai(api_key, model, system, prompt, max_tokens):
    client   = _get_openai_client(api_key)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    if response.choices[0].finish_reason not in ("stop", "length"):
        raise ValueError(f"OpenAI finish reason: {response.choices[0].finish_reason}")
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("OpenAI returned empty content.")
    return content


# ── Async call implementations ───────────────────────────────────────────────

async def _call_groq_async(api_key, model, system, prompt, max_tokens):
    from config.model_router import acquire_slot, record_usage

    estimated = (len(system) + len(prompt)) // 4
    try:
        await acquire_slot(model, estimated)
    except RuntimeError as e:
        from groq import RateLimitError
        raise RateLimitError(message=str(e), response=None, body=None) from e

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

    if hasattr(response, "usage") and response.usage:
        record_usage(model, response.usage.total_tokens or 0)

    return content


async def _call_gemini_async(api_key, model, system, prompt, max_tokens):
    from google.genai import types
    from config.model_router import acquire_slot, record_usage

    # Rough token estimate for throttle pre-check (chars / 4 ≈ tokens)
    estimated = (len(system) + len(prompt)) // 4
    try:
        await acquire_slot(model, estimated)
    except RuntimeError as e:
        # Daily budget exhausted — convert to rate-limit sentinel so router falls back
        raise _GeminiRateLimitError(str(e)) from e

    # Gemma models don't support system_instruction — prepend to user prompt instead
    is_gemma = model.startswith("gemma-")
    contents = f"{system}\n\n{prompt}" if is_gemma else prompt
    config   = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=0.2,
        top_p=0.95,
        **({}  if is_gemma else {"system_instruction": system}),
    )

    # The sync client exposes an async interface via .aio — no separate client needed
    client = _get_gemini_client(api_key)
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
    except Exception as e:
        # Translate Gemini quota/rate-limit errors to our sentinel so the router
        # can fall back. Any other ClientError (400 invalid arg, etc.) is re-raised
        # as-is so it surfaces as a real error rather than silently cooling the model.
        err = str(e).lower()
        if any(kw in err for kw in ("429", "quota", "rate limit", "resource exhausted")):
            raise _GeminiRateLimitError(str(e)) from e
        raise

    if not response.candidates:
        raise ValueError(f"Gemini returned no candidates. Feedback: {response.prompt_feedback}")

    candidate = response.candidates[0]
    if candidate.finish_reason.name not in ("STOP", "MAX_TOKENS"):
        raise ValueError(f"Gemini finish reason: {candidate.finish_reason.name}")

    text = response.text
    if not text or not text.strip():
        raise ValueError("Gemini returned empty text.")

    # Record actual token usage for throttle accounting
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        total = getattr(response.usage_metadata, "total_token_count", 0) or 0
        record_usage(model, total)

    return text


async def _call_openai_async(api_key, model, system, prompt, max_tokens):
    client   = _get_openai_async_client(api_key)
    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    if response.choices[0].finish_reason not in ("stop", "length"):
        raise ValueError(f"OpenAI finish reason: {response.choices[0].finish_reason}")
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("OpenAI returned empty content.")
    return content


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
    """Like llm_call_async but with explicit provider+model — also uses fallback chain.

    When all models in the chain are cooling, waits for the soonest one to recover
    and retries rather than failing immediately.
    """
    from config.model_router import get_chain, is_cooling, mark_cooling, cooling_remaining
    api_key        = get_api_key(provider)
    chain          = get_chain(provider, model)
    rate_limit_exc = _rate_limit_exceptions(provider)
    transient_exc  = _transient_exceptions(provider)

    while True:
        attempted_any = False
        for m in chain:
            if is_cooling(m):
                logger.debug(f"[explicit] {m} cooling — skipping")
                continue
            attempted_any = True
            logger.debug(f"[explicit] provider={provider} model={m}")

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    return await _dispatch_async(provider, m, api_key, system, user_prompt, max_tokens)
                except rate_limit_exc:
                    mark_cooling(m, provider)
                    logger.warning(f"[explicit] Rate limit on {m} — falling back")
                    break
                except transient_exc as e:
                    if attempt == MAX_RETRIES:
                        break
                    await asyncio.sleep(RETRY_BACKOFF * attempt)
                except Exception as e:
                    # 404 = model doesn't exist — skip it, don't crash the chain
                    if "404" in str(e) or "NOT_FOUND" in str(e):
                        logger.warning(f"[explicit] {m} not found (404) — removing from chain")
                        break
                    logger.error(f"[explicit] Non-retryable error on {m}: {e}")
                    raise

        if not attempted_any:
            # All models cooling — wait for the soonest to recover then retry
            wait = min((cooling_remaining(m) for m in chain), default=0) + 5
            logger.info(f"[explicit] All models cooling — waiting {wait}s for recovery")
            await asyncio.sleep(wait)


# ── Dispatch helper ───────────────────────────────────────────────────────────

async def _call_nvidia_async(api_key, model, system, prompt, max_tokens):
    from config.model_router import acquire_slot, record_usage

    estimated = (len(system) + len(prompt)) // 4
    try:
        await acquire_slot(model, estimated)
    except RuntimeError as e:
        from openai import RateLimitError
        raise RateLimitError(message=str(e), response=None, body=None) from e

    client   = _get_nvidia_async_client(api_key)
    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.6,
        top_p=0.95,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    )
    msg           = response.choices[0].message
    finish_reason = response.choices[0].finish_reason
    # Nemotron-Ultra always puts output in reasoning_content; content is None
    content = msg.content or getattr(msg, "reasoning_content", None) or ""
    if not content.strip():
        raise RuntimeError("NVIDIA_EMPTY_CONTENT")
    if finish_reason not in ("stop", "length", None):
        logger.warning(f"[nvidia] unusual finish_reason={finish_reason} but content present — using it")
    if hasattr(response, "usage") and response.usage:
        record_usage(model, response.usage.total_tokens or 0)
    return content


async def _dispatch_async(provider, model, api_key, system, prompt, max_tokens):
    if provider == "groq":
        return await _call_groq_async(api_key, model, system, prompt, max_tokens)
    elif provider == "gemini":
        return await _call_gemini_async(api_key, model, system, prompt, max_tokens)
    elif provider == "anthropic":
        return await _call_anthropic_async(api_key, model, system, prompt, max_tokens)
    elif provider == "openai":
        return await _call_openai_async(api_key, model, system, prompt, max_tokens)
    elif provider == "nvidia":
        return await _call_nvidia_async(api_key, model, system, prompt, max_tokens)
    raise ValueError(f"Unknown provider: '{provider}'. Valid: groq | gemini | anthropic | openai | nvidia")


# ── Exception helpers ─────────────────────────────────────────────────────────

def _rate_limit_exceptions(provider: str) -> tuple:
    """Quota/rate-limit errors → trigger model fallback to next in chain.
    Returns empty tuple on import failure — unknown exceptions are never silently
    treated as rate limits, which would mask bugs and retry API key errors."""
    if provider == "groq":
        try:
            from groq import RateLimitError, APIStatusError
            return (RateLimitError, APIStatusError)
        except ImportError:
            logger.error("groq package not importable — rate-limit detection disabled")
    elif provider == "gemini":
        return (_GeminiRateLimitError,)
    elif provider == "anthropic":
        try:
            from anthropic import RateLimitError
            return (RateLimitError,)
        except ImportError:
            logger.error("anthropic package not importable — rate-limit detection disabled")
    elif provider == "openai":
        try:
            from openai import RateLimitError
            return (RateLimitError,)
        except ImportError:
            logger.error("openai package not importable — rate-limit detection disabled")
    elif provider == "nvidia":
        try:
            from openai import RateLimitError
            return (RateLimitError,)
        except ImportError:
            logger.error("openai package not importable — nvidia rate-limit detection disabled")
    return ()


def _transient_exceptions(provider: str) -> tuple:
    """Connection/timeout errors → retry same model."""
    if provider == "groq":
        try:
            from groq import APIConnectionError, APITimeoutError
            return (APIConnectionError, APITimeoutError)
        except ImportError:
            pass
    elif provider == "gemini":
        try:
            from google.genai.errors import ServerError
            return (ServerError,)
        except ImportError:
            pass
    elif provider == "anthropic":
        try:
            from anthropic import APIConnectionError, APITimeoutError
            return (APIConnectionError, APITimeoutError)
        except ImportError:
            pass
    elif provider == "openai":
        try:
            from openai import APIConnectionError, APITimeoutError
            return (APIConnectionError, APITimeoutError)
        except ImportError:
            pass
    elif provider == "nvidia":
        try:
            from openai import APIConnectionError, APITimeoutError
            return (APIConnectionError, APITimeoutError)
        except ImportError:
            pass
    return (ConnectionError, TimeoutError)


async def llm_call_async_pool(
    pool: list[tuple[str, str]],
    system: str,
    user_prompt: str,
    max_tokens: int = 4096,
    role: str = "pool",
) -> str:
    """
    Try models from a cross-provider pool in priority order.
    Skips cooling models, falls back on rate limits, waits if all are cooling.
    Pool entries are (provider, model) tuples pre-built by model_router.
    """
    from config.model_router import is_cooling, mark_cooling, cooling_remaining

    if not pool:
        raise RuntimeError("Empty model pool — no API keys configured for this tier. Check your .env.")

    while True:
        attempted_any = False
        for provider, model in pool:
            if is_cooling(model):
                logger.debug(f"[{role}] {model} cooling — skipping")
                continue
            try:
                api_key = get_api_key(provider)
            except ValueError:
                logger.warning(f"[{role}] No API key for {provider} — skipping {model}")
                continue

            rate_limit_exc = _rate_limit_exceptions(provider)
            transient_exc  = _transient_exceptions(provider)
            attempted_any  = True
            logger.debug(f"[{role}] provider={provider} model={model}")

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    return await _dispatch_async(provider, model, api_key, system, user_prompt, max_tokens)
                except rate_limit_exc:
                    mark_cooling(model, provider)
                    logger.warning(f"[{role}] Rate limit on {model} — falling back")
                    break
                except transient_exc as e:
                    if attempt == MAX_RETRIES:
                        logger.warning(f"[{role}] {model} failed after {MAX_RETRIES} retries — falling back")
                        break
                    await asyncio.sleep(RETRY_BACKOFF * attempt)
                except Exception as e:
                    err = str(e)
                    if "404" in err or "NOT_FOUND" in err:
                        logger.warning(f"[{role}] {model} not found (404) — skipping")
                        break
                    if "NVIDIA_EMPTY_CONTENT" in err:
                        logger.warning(f"[{role}] {model} returned empty — falling back")
                        break
                    logger.error(f"[{role}] Non-retryable error on {model}: {e}")
                    raise

        if not attempted_any:
            wait = min((cooling_remaining(m) for _, m in pool), default=0) + 5
            logger.info(f"[{role}] All models cooling — waiting {wait}s for recovery")
            await asyncio.sleep(wait)
