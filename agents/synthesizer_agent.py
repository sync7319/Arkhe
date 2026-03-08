"""
Master Writer agent — synthesizes all subagent reports into CODEBASE_MAP.md.
Provider + model controlled entirely from .env via llm_client.
"""
from config.llm_client import llm_call

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


def synthesize(reports: list[dict], file_tree: list[dict]) -> str:
    combined = "\n\n---\n\n".join(
        f"## Batch {r['batch_id']} — Files: {', '.join(r['files'])}\n\n{r['analysis']}"
        for r in reports
    )
    file_list = "\n".join(
        f"- {f['path']} ({f['tokens']} tokens)" for f in file_tree
    )
    prompt = (
        f"Full file list ({len(file_tree)} files):\n{file_list}\n\n"
        f"Agent reports:\n\n{combined}"
    )
    return llm_call("report", SYSTEM, prompt, max_tokens=8192)
