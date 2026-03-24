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
from config.llm_client import llm_call_async_explicit, llm_call_async_pool

logger = logging.getLogger("arkhe.analyst")

SYSTEM = """You are a senior software engineer. Analyze this file and return:
1. Purpose (1 sentence — be specific about what this file actually does, not generic)
2. Key functions/classes (list each by its exact name, one line description each)
3. Main dependencies (exact import names)
4. Gotchas or non-obvious behaviors (name specific functions/variables involved)

Be specific: use actual names from the code. Do not write generic descriptions.
Output raw Markdown — no code fences wrapping the response."""

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

# No artificial concurrency cap — try_acquire_slot() in model_router is the real gate.
# It tracks RPM/TPM sliding windows and blocks when at capacity, so all files can
# queue up and fire as soon as a slot opens. Maximizes throughput automatically.
MAX_CONCURRENT_FILES = 200


def _safe_budget(model: str) -> int:
    for key, val in MODEL_TPM_LIMITS.items():
        if key in model:
            return val
    return DEFAULT_SAFE_TPM


def _build_prompt(file: dict) -> str:
    s    = file.get("structure", {})
    body = file["content"].strip()
    fns  = ", ".join(s.get("functions", [])[:6]) or "none"
    cls  = ", ".join(s.get("classes",   [])[:4]) or "none"
    imps = ", ".join(s.get("imports",   [])[:5]) or "none"
    return (
        f"### {file['path']} ({file['tokens']} tokens)\n"
        f"fn: {fns} | cls: {cls} | imports: {imps}\n"
        f"```\n{body}\n```"
    )


async def _analyze_file(file: dict, idx: int, sem: asyncio.Semaphore) -> dict:
    from config.model_router import get_file_pool_cascade
    async with sem:
        prompt = _build_prompt(file)
        pool   = get_file_pool_cascade(file["path"], file.get("tokens", 0))
        print(f"[ANALYST] {file['path']}: pool has {len(pool)} models → {[m for _,m in pool[:3]]}", flush=True)
        if not pool:
            raise RuntimeError(f"Empty pool for {file['path']}")
        # Scale output budget with file size: small files get 512, large get up to 1024
        file_tokens = file.get("tokens", 0)
        out_tokens = 512 if file_tokens < 300 else (768 if file_tokens < 1000 else 1024)
        try:
            analysis = await llm_call_async_pool(pool, SYSTEM, prompt, max_tokens=out_tokens, role="analyst")
        except Exception as e:
            import traceback
            with open("server/error.log", "a") as f:
                f.write(f"\n[ANALYST] {file['path']}: {type(e).__name__}: {e}\n")
                f.write(f"  pool: {[(p,m) for p,m in pool[:3]]}\n")
                traceback.print_exc(file=f)
            raise

    db = get_db()
    db.save_analysis(file["path"], file["content_hash"], analysis)

    return {"batch_id": idx, "files": [file["path"]], "analysis": analysis}


async def analyze_parallel(files: list[dict]) -> list[dict]:
    model = "multi-provider/tiered"  # display label only
    db    = get_db()

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

    sem   = asyncio.Semaphore(MAX_CONCURRENT_FILES)
    tasks = [_analyze_file(f, hits + i, sem) for i, f in enumerate(new_files)]
    raw   = await asyncio.gather(*tasks, return_exceptions=True)

    new_results = []
    failures    = 0
    for result in raw:
        if isinstance(result, Exception):
            logger.error(f"[analyze] failed: {result}")
            failures += 1
        else:
            new_results.append(result)

    if failures:
        logger.warning(f"[analyze] {failures}/{misses} new file(s) failed — continuing with {len(new_results)} results")

    if not new_results and misses > 0:
        raise RuntimeError(
            f"Analysis failed — all {misses} new file(s) errored. "
            "Check your API key and provider rate limits."
        )

    return sorted(cached_results + new_results, key=lambda r: r["batch_id"])
