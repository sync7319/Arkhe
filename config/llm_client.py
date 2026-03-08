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


def llm_call(role: str, system: str, user_prompt: str, max_tokens: int = 4096) -> str:
    provider, model = get_model(role)
    api_key         = get_api_key(provider)
    logger.debug(f"[{role}] provider={provider} model={model}")

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
        except _retryable_exceptions(provider) as e:
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
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: llm_call(role, system, user_prompt, max_tokens),
    )


def _call_groq(api_key, model, system, prompt, max_tokens):
    from groq import Groq
    client   = Groq(api_key=api_key)
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
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
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
    import anthropic
    client   = anthropic.Anthropic(api_key=api_key)
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
