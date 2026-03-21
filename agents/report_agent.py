"""
Report agent — generates a professional executive report from all pipeline outputs.

Model selection is automatic:
  - EXPENSIVE_MODELS_ALLOWED=false → cheap model (safe for testing)
  - EXPENSIVE_MODELS_ALLOWED=true  → Opus for large repos, Sonnet for smaller ones
    Threshold controlled by COMPLEXITY_THRESHOLD_TOKENS in .env (default 50 000 tokens)
"""
from config.llm_client import llm_call_async_explicit

SYSTEM = """You are a senior software architect writing a professional executive report
for a technical audience (engineering leads, CTOs, and stakeholders).
Be precise, concrete, and actionable. Avoid filler language.

Use exactly these section headers and no others:

# Executive Summary
[250-450 words — purpose of the codebase, overall quality, and key takeaways]

# Strengths
[Bulleted list of concrete technical and architectural strengths]

# Weaknesses
[Bulleted list of concrete weaknesses, gaps, or technical debt items]

# Security Concerns
[Bulleted list of specific security issues, missing controls, or vulnerability risks]

# Recommended Updates
[Numbered priority list — most impactful first, with a one-line justification each]

# Basic Documentation
[Entry points and how to run the project, core modules and their public APIs,
key environment variables, and any non-obvious operational requirements]"""


async def generate_report(
    codebase_map: str,
    files: list[dict],
    reports: list[dict],
    graph: dict,
    repo_path: str,
) -> tuple[str, str, str]:
    """
    Generate the executive Word report.
    Returns (report_text, provider, model) — provider/model logged by caller.
    """
    from config.settings import EXECUTIVE_PROVIDER, EXECUTIVE_MODELS, EXPENSIVE_MODELS_ALLOWED, COMPLEXITY_THRESHOLD_TOKENS
    provider = EXECUTIVE_PROVIDER
    total_tokens = sum(f.get("tokens", 0) for f in files)
    if EXPENSIVE_MODELS_ALLOWED and provider in EXECUTIVE_MODELS:
        size = "large" if total_tokens >= COMPLEXITY_THRESHOLD_TOKENS else "small"
        model = EXECUTIVE_MODELS[provider][size]
    else:
        from config.settings import CHEAP_MODELS
        model = CHEAP_MODELS.get(provider, {}).get("report", "nvidia/llama-3.1-nemotron-ultra-253b-v1")

    file_summary = "\n".join(
        f"- {f['path']} ({f.get('tokens', 0)} tokens)" for f in files
    )
    batch_summaries = "\n\n---\n\n".join(
        f"Batch {r['batch_id']}:\n{r['analysis']}" for r in reports
    )
    node_count = len(graph.get("nodes", []))
    link_count = len(graph.get("links", []))

    prompt = (
        f"Repository: {repo_path}\n"
        f"Total files: {len(files)} | Total tokens: {total_tokens:,} | "
        f"Dependency graph: {node_count} nodes, {link_count} edges\n\n"
        f"=== FILE LIST ===\n{file_summary}\n\n"
        f"=== SYNTHESIZED CODEBASE MAP ===\n{codebase_map}\n\n"
        f"=== BATCH ANALYSIS REPORTS ===\n{batch_summaries}"
    )

    report_text = await llm_call_async_explicit(
        provider, model, SYSTEM, prompt, max_tokens=4096
    )
    return report_text, provider, model
