"""
Analyst agent — documents each file using the traversal model.

Per-file caching: files whose content hasn't changed since the last run are
loaded from SQLite and skipped entirely. Only new or modified files hit the LLM.

Unchanged files on a typical incremental PR run: ~95%+ cache hit rate.
New files are analyzed concurrently, bounded by MAX_CONCURRENT_FILES.
"""
import asyncio
import logging
from cache.db import get_db
from config.llm_client import llm_call_async_explicit

logger = logging.getLogger("arkhe.analyst")

SYSTEM = """You are a senior software engineer. Analyze this file and return:
1. Purpose (1 sentence)
2. Key functions/classes (names + 1 line each)
3. Main dependencies
4. Any gotchas
Be concise. Markdown format."""

# Free-tier safe limits per model (tokens per minute)
MODEL_TPM_LIMITS = {
    "moonshotai/kimi-k2-instruct":       8000,
    "moonshotai/kimi-k2-instruct-0905":  8000,
    "openai/gpt-oss-120b":               6000,
    "llama-3.3-70b-versatile":           5000,
    "qwen/qwen3-32b":                    5000,
    "openai/gpt-oss-20b":                6000,
    "llama-3.1-8b-instant":              5000,
}
DEFAULT_SAFE_TPM = 5000

# Max content chars sent per file in the prompt
MAX_FILE_CHARS = 800

# Max files analyzed concurrently.
# Keep at 1 for free-tier providers (Groq/Gemini) — bursting concurrent calls
# exhausts the RPM budget instantly and triggers cascading fallbacks.
# Raise to 3-5 only when using paid API keys with higher rate limits.
MAX_CONCURRENT_FILES = 1


def _safe_budget(model: str) -> int:
    for key, val in MODEL_TPM_LIMITS.items():
        if key in model:
            return val
    return DEFAULT_SAFE_TPM


def _build_prompt(file: dict) -> str:
    s    = file.get("structure", {})
    body = file["content"][:MAX_FILE_CHARS].strip()
    fns  = ", ".join(s.get("functions", [])[:6]) or "none"
    cls  = ", ".join(s.get("classes",   [])[:4]) or "none"
    imps = ", ".join(s.get("imports",   [])[:5]) or "none"
    return (
        f"### {file['path']} ({file['tokens']} tokens)\n"
        f"fn: {fns} | cls: {cls} | imports: {imps}\n"
        f"```\n{body}\n```"
    )


async def _analyze_file(file: dict, idx: int, sem: asyncio.Semaphore) -> dict:
    from config.model_router import get_groq_file_model
    async with sem:
        prompt   = _build_prompt(file)
        model    = get_groq_file_model(file["path"], file.get("tokens", 0))
        analysis = await llm_call_async_explicit("groq", model, SYSTEM, prompt, max_tokens=512)

    db = get_db()
    db.save_analysis(file["path"], file["content_hash"], analysis)

    return {"batch_id": idx, "files": [file["path"]], "analysis": analysis}


async def analyze_parallel(files: list[dict]) -> list[dict]:
    from config.model_router import get_groq_file_model
    model = "groq/multi-model"  # display label only
    db       = get_db()

    cached_results, new_files = [], []
    for file in files:
        content_hash = file.get("content_hash")
        if not content_hash:
            new_files.append(file)
            continue
        row = db.get_file(file["path"], content_hash)
        if row and row["analysis"]:
            logger.debug(f"[analyze] cache hit: {file['path']}")
            cached_results.append({
                "batch_id": len(cached_results),
                "files":    [file["path"]],
                "analysis": row["analysis"],
            })
        else:
            new_files.append(file)

    hits   = len(cached_results)
    misses = len(new_files)
    logger.info(
        f"[analyze] {hits} cached, {misses} new — model [{model}]  "
        f"(safe budget: {_safe_budget(model):,} TPM, "
        f"concurrency: {min(MAX_CONCURRENT_FILES, max(misses, 1))})"
    )

    sem = asyncio.Semaphore(MAX_CONCURRENT_FILES)
    new_results     = []
    consecutive_failures = 0
    ABORT_THRESHOLD = 3   # abort after this many consecutive all-model failures

    for i, f in enumerate(new_files):
        task   = _analyze_file(f, hits + i, sem)
        result = await asyncio.gather(task, return_exceptions=True)
        result = result[0]

        if isinstance(result, Exception):
            logger.error(f"[analyze] failed for {f['path']}: {result}")
            consecutive_failures += 1
            if consecutive_failures >= ABORT_THRESHOLD:
                logger.warning(
                    f"[analyze] {consecutive_failures} consecutive failures — "
                    f"aborting early to preserve quota. "
                    f"{len(new_results)}/{misses} new files analyzed before abort."
                )
                break
        else:
            new_results.append(result)
            consecutive_failures = 0  # reset on success

    if not new_results and misses > 0:
        raise RuntimeError(
            f"Analysis failed — all {misses} new file(s) errored. "
            "Check your API key and provider rate limits."
        )

    return sorted(cached_results + new_results, key=lambda r: r["batch_id"])
