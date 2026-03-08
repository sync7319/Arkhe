"""
File Searcher agent — documents each file batch using the traversal model.
Optimized for free tier limits: small batches, trimmed prompts.
"""
import asyncio
from config.llm_client import llm_call_async
from config.settings import MAX_TOKENS_PER_BATCH

SYSTEM = """You are a senior software engineer. Analyze each file and return:
1. Purpose (1 sentence)
2. Key functions/classes (names + 1 line each)
3. Main dependencies
4. Any gotchas
Be concise. Markdown format."""

# Free tier safe limits per model
MODEL_TPM_LIMITS = {
    "openai/gpt-oss-20b":        6000,   # 8k limit, leave headroom
    "openai/gpt-oss-120b":       6000,
    "llama-3.1-8b-instant":      5000,
    "llama-3.3-70b-versatile":   5000,
    "gemini-2.0-flash":         50000,
}
DEFAULT_SAFE_TPM = 5000

# Max content chars per file in prompt (controls token usage)
MAX_FILE_CHARS = 800


def _safe_budget(model: str) -> int:
    for key, val in MODEL_TPM_LIMITS.items():
        if key in model:
            return val
    return DEFAULT_SAFE_TPM


def _build_prompt(batch: list[dict]) -> str:
    parts = []
    for f in batch:
        s = f.get("structure", {})
        # Trim content aggressively to stay under token limits
        content_preview = f["content"][:MAX_FILE_CHARS].strip()
        fns  = ", ".join(s.get("functions", [])[:6]) or "none"
        cls  = ", ".join(s.get("classes",   [])[:4]) or "none"
        imps = ", ".join(s.get("imports",   [])[:5]) or "none"
        parts.append(
            f"### {f['path']} ({f['tokens']} tokens)\n"
            f"fn: {fns} | cls: {cls} | imports: {imps}\n"
            f"```\n{content_preview}\n```"
        )
    return "\n\n".join(parts)


def _group_batches(files: list[dict], model: str) -> list[list[dict]]:
    """
    Split files into batches that fit within the model's safe TPM budget.
    Each file's estimated prompt tokens = tokens * 0.4 (content trimmed).
    System prompt ~= 80 tokens. Max output = 1024 tokens.
    """
    safe_budget    = _safe_budget(model)
    max_input_toks = safe_budget - 1024 - 80  # reserve for output + system
    batches, current, running = [], [], 0

    for f in files:
        est = min(f["tokens"], MAX_FILE_CHARS // 4) + 40  # estimated prompt tokens per file
        if running + est > max_input_toks and current:
            batches.append(current)
            current, running = [], 0
        current.append(f)
        running += est

    if current:
        batches.append(current)
    return batches


async def _analyze_batch(batch: list[dict], batch_id: int, model: str) -> dict:
    prompt = _build_prompt(batch)
    result = await llm_call_async("traversal", SYSTEM, prompt, max_tokens=1024)
    return {
        "batch_id": batch_id,
        "files":    [f["path"] for f in batch],
        "analysis": result,
    }


async def analyze_parallel(files: list[dict]) -> list[dict]:
    from config.settings import get_model
    _, model = get_model("traversal")

    batches = _group_batches(files, model)
    print(f"  -> {len(batches)} batch(es) for model [{model}]  "
          f"(safe budget: {_safe_budget(model):,} TPM)")

    # Process batches sequentially to avoid TPM burst on free tier
    results = []
    for i, batch in enumerate(batches):
        result = await _analyze_batch(batch, i, model)
        results.append(result)
        if i < len(batches) - 1:
            await asyncio.sleep(1.5)  # brief pause between batches

    return results
