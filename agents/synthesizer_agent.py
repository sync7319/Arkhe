"""
Synthesizer agent — combines all batch reports into CODEBASE_MAP.md.
Provider + model controlled entirely from .env via llm_client.
"""
import logging
from config.llm_client import llm_call_async

logger = logging.getLogger("arkhe.synthesizer")

# ~100k tokens — safe ceiling for all supported providers (Groq 131k, Anthropic 200k, Gemini 1M)
MAX_PROMPT_CHARS = 400_000

SYSTEM = """You are a senior software architect. You have received analysis reports
from multiple agents, each covering a different module of the same codebase.
Synthesize them into a single, comprehensive CODEBASE_MAP.md with these sections:

# Arkhe — Codebase Map

## 1. System Overview
## 2. Architecture Diagram (ASCII)
## 3. Directory Structure (annotated)
## 4. Module Guide (per-module: purpose, entry points, key files, dependencies)
## 5. Data Flows
## 6. Conventions & Patterns
## 7. Gotchas & Warnings
## 8. Navigation Guide

Be thorough but scannable. Use tables where appropriate."""


async def synthesize(reports: list[dict], file_tree: list[dict]) -> str:
    combined = "\n\n---\n\n".join(
        f"## File: {', '.join(r['files'])}\n\n{r['analysis']}"
        for r in reports
    )
    file_list = "\n".join(
        f"- {f['path']} ({f['tokens']} tokens)" for f in file_tree
    )
    header = f"Full file list ({len(file_tree)} files):\n{file_list}\n\nAgent reports:\n\n"
    prompt = header + combined

    if len(prompt) > MAX_PROMPT_CHARS:
        available = MAX_PROMPT_CHARS - len(header) - 60
        combined  = combined[:available] + "\n\n[... reports truncated to fit context limit ...]"
        prompt    = header + combined
        logger.warning(
            f"Synthesis prompt truncated to {MAX_PROMPT_CHARS:,} chars "
            f"({len(reports)} reports, {len(file_tree)} files)"
        )

    return await llm_call_async("report", SYSTEM, prompt, max_tokens=8192)
