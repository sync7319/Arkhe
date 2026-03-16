"""
Synthesizer agent — combines all batch reports into CODEBASE_MAP.md.

Uses hierarchical synthesis for large codebases:
  1. Group file reports into batches of BATCH_SIZE
  2. Mini-synthesize each batch into a short module summary (~500 tokens)
  3. Final synthesis of all summaries into the full CODEBASE_MAP.md

This keeps every LLM call well under Groq's per-minute token limits.
"""
import logging
from config.llm_client import llm_call_async_pool

logger = logging.getLogger("arkhe.synthesizer")

# Files per intermediate batch — keeps each call ~5K tokens (well under 10K TPM)
BATCH_SIZE = 10

BATCH_SYSTEM = """You are a senior software engineer. Summarize the following file analysis
reports into a concise module overview (3-6 sentences). Cover: what these files do together,
key functions/classes, dependencies, and any gotchas. Be brief."""

SYSTEM = """You are a senior software architect. You have received module summaries
from a multi-agent analysis of a codebase. Synthesize them into a comprehensive
CODEBASE_MAP.md with these sections:

# Codebase Map

## 1. System Overview
## 2. Architecture Diagram (ASCII)
## 3. Directory Structure (annotated)
## 4. Module Guide (per-module: purpose, entry points, key files, dependencies)
## 5. Data Flows
## 6. Conventions & Patterns
## 7. Gotchas & Warnings
## 8. Navigation Guide

Be thorough but scannable. Use tables where appropriate."""


async def _call(system: str, prompt: str, max_tokens: int) -> str:
    from config.model_router import get_heavy_pool
    pool = get_heavy_pool()
    logger.info(f"[synthesize] heavy pool: {[m for _, m in pool]} | prompt: {len(prompt):,} chars")
    return await llm_call_async_pool(pool, system, prompt, max_tokens=max_tokens, role="synthesize")


async def synthesize(reports: list[dict], file_tree: list[dict]) -> str:
    file_list = "\n".join(
        f"- {f['path']} ({f['tokens']} tokens)" for f in file_tree
    )

    # Small codebase — single call is fine
    if len(reports) <= BATCH_SIZE:
        combined = "\n\n---\n\n".join(
            f"## File: {', '.join(r['files'])}\n\n{r['analysis']}"
            for r in reports
        )
        prompt = f"File list ({len(file_tree)} files):\n{file_list}\n\nReports:\n\n{combined}"
        return await _call(SYSTEM, prompt, max_tokens=8192)

    # Large codebase — hierarchical: batch summaries → final synthesis
    logger.info(f"[synthesize] hierarchical mode: {len(reports)} reports → batches of {BATCH_SIZE}")

    summaries = []
    for i in range(0, len(reports), BATCH_SIZE):
        batch = reports[i:i + BATCH_SIZE]
        combined = "\n\n---\n\n".join(
            f"File: {', '.join(r['files'])}\n{r['analysis']}"
            for r in batch
        )
        summary = await _call(BATCH_SYSTEM, combined, max_tokens=2048)
        summaries.append(f"### Batch {i // BATCH_SIZE + 1} ({len(batch)} files)\n{summary}")
        logger.info(f"[synthesize] batch {i // BATCH_SIZE + 1}/{(len(reports) + BATCH_SIZE - 1) // BATCH_SIZE} done")

    all_summaries = "\n\n".join(summaries)
    prompt = f"File list ({len(file_tree)} files):\n{file_list}\n\nModule summaries:\n\n{all_summaries}"
    return await _call(SYSTEM, prompt, max_tokens=8192)
