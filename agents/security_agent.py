"""
Security Audit Agent — static + LLM scan for common vulnerabilities.

Two-pass approach:
  Pass 1 (static, free): Bandit for Python files — deterministic, CWE-mapped,
          full-file coverage (no truncation). Zero LLM cost.
  Pass 2 (LLM): Semantic scan for all files — catches auth issues, SSRF, logic
          flaws, and patterns Bandit can't detect statically.

Covers OWASP Top 10 patterns: hardcoded secrets, injection risks,
unvalidated inputs, insecure deserialization, missing auth, weak crypto.

Output: docs/SECURITY_REPORT.md
"""
import asyncio
import logging
import os
import subprocess
import sys
import json

from config.llm_client import llm_call_async

logger = logging.getLogger("arkhe.security")

SYSTEM = """You are a security engineer doing a focused code security review.
For each file, identify ONLY real security issues — not style, not performance.

Context: This codebase is a code analysis tool that intentionally reads repository files
and sends their contents to LLM APIs. Do NOT flag the tool's core design (passing file
contents to an LLM) as prompt injection — that is the tool's intended purpose.

Look for:
- Hardcoded credentials: literal string values assigned directly (e.g. api_key="sk-abc123"). Do NOT flag api_key=variable patterns where the variable comes from os.getenv() or a function parameter — those are NOT hardcoded.
- SQL injection (string concatenation or f-strings in queries)
- Command injection (shell=True, os.system, subprocess with user-controlled input, eval, exec on user input)
- Path traversal (user-supplied paths reaching os.path.join/open without validation against a safe root)
- Unvalidated inputs from HTTP requests reaching dangerous sinks (file system, shell, DB)
- Missing authentication or authorization on sensitive HTTP routes
- Insecure deserialization (pickle.loads, yaml.load without Loader=)
- Sensitive data (API keys, tokens, PII) written to logs or error messages
- Weak or broken cryptography (MD5/SHA1 for passwords, hardcoded IV/salt/key)
- Open redirects, SSRF (user-controlled URLs passed to requests/httpx without allow-list)

Output format — use EXACTLY this structure for every file, no exceptions:
  FILE: <path> — CLEAN
  or:
  FILE: <path>
  SEVERITY: CRITICAL | HIGH | MEDIUM | LOW
  ISSUE: <one-line description>
  CODE: <relevant snippet, max 1 line>
  FIX: <one-line recommendation>

Rules:
- Do NOT use markdown headers (###), numbered lists, or prose paragraphs — only the FILE/SEVERITY/ISSUE/CODE/FIX format.
- Do NOT change format mid-response.
- If a snippet appears truncated or ends mid-token, do NOT flag it — you cannot assess what you cannot see.
- subprocess.run() called with a list (not shell=True) is NOT command injection.
- os.path.join() on filenames from os.listdir() or a validated allowlist is NOT path traversal.
- Passing api_key from a variable (not a hardcoded string) to a client constructor is NOT a hardcoded credential.
Be concise. Flag real, exploitable issues only — not theoretical or intentional design choices."""

BATCH_SIZE  = 4
MAX_CHARS   = 3000
_SKIP_PATHS = {"test", "docs", ".arkhe_cache", "_refactored", "tests_generated"}

# Bandit severity → our severity label
_BANDIT_SEVERITY = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}


def _should_audit(path: str) -> bool:
    return not any(seg in path for seg in _SKIP_PATHS)


# ── Bandit static scan (Python files, pass 1) ─────────────────────────────────

def _run_bandit(python_modules: list[dict]) -> str:
    """
    Run Bandit on Python files via subprocess.
    Returns formatted findings in FILE/SEVERITY/ISSUE/CODE/FIX format,
    or empty string if Bandit is unavailable / no issues found.
    """
    abs_paths = [m["abs_path"] for m in python_modules if m.get("abs_path")]
    if not abs_paths:
        return ""

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "bandit", "-f", "json", "-q", "--exit-zero",
                "--skip", "B404,B603,B607",  # subprocess import/usage noise — intentional in analysis tools
            ] + abs_paths,
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, Exception) as e:
        logger.warning(f"[security] bandit unavailable: {e}")
        return ""

    issues: list[dict] = data.get("results", [])
    if not issues:
        return ""

    # Group issues by file path for report formatting
    by_file: dict[str, list[dict]] = {}
    for issue in issues:
        fname = issue.get("filename", "")
        by_file.setdefault(fname, []).append(issue)

    # Build abs_path → rel_path mapping
    abs_to_rel = {m.get("abs_path", ""): m["path"] for m in python_modules if m.get("abs_path")}

    lines = ["## Static Analysis (Bandit)\n"]
    for abs_path, file_issues in sorted(by_file.items()):
        rel_path = abs_to_rel.get(abs_path, abs_path)
        for issue in file_issues:
            sev   = _BANDIT_SEVERITY.get(issue.get("issue_severity", "LOW"), "LOW")
            text  = issue.get("issue_text", "").strip()
            code  = issue.get("code", "").strip().splitlines()[0][:120] if issue.get("code") else ""
            cwe   = issue.get("issue_cwe", {}).get("id", "")
            cwe_s = f" (CWE-{cwe})" if cwe else ""
            lines.append(
                f"FILE: {rel_path}\n"
                f"SEVERITY: {sev}\n"
                f"ISSUE: {text}{cwe_s}\n"
                f"CODE: {code}\n"
                f"FIX: Refer to Bandit rule {issue.get('test_id', '')} and CWE documentation.\n"
            )

    return "\n".join(lines)


# ── Semgrep multi-language scan (pass 2, optional) ───────────────────────────

def _run_semgrep(modules: list[dict]) -> str:
    """
    Run Semgrep with community rules for multi-language security scanning.
    Infers the repo root from the first module's abs_path and relative path.
    Returns formatted findings or empty string if Semgrep is unavailable.
    """
    # Derive repo absolute path from first module that has abs_path
    repo_root = None
    for m in modules:
        abs_p = m.get("abs_path", "")
        rel_p = m.get("path", "")
        if abs_p and rel_p and abs_p.endswith(rel_p.replace("\\", "/")):
            repo_root = abs_p[: -len(rel_p)].rstrip("/")
            break
    if not repo_root:
        return ""

    try:
        result = subprocess.run(
            [
                "semgrep", "--config=auto", "--json",
                "--no-git-ignore", "--timeout", "30",
                repo_root,
            ],
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except FileNotFoundError:
        logger.debug("[security] semgrep not installed — skipping")
        return ""
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.warning(f"[security] semgrep failed: {e}")
        return ""

    findings = data.get("results", [])
    if not findings:
        return ""

    sev_map = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
    lines   = ["## Static Analysis (Semgrep)\n"]
    for f in findings:
        rel_path = os.path.relpath(f.get("path", ""), repo_root)
        sev      = sev_map.get(f.get("extra", {}).get("severity", "WARNING").upper(), "LOW")
        message  = f.get("extra", {}).get("message", "").split("\n")[0][:120]
        check_id = f.get("check_id", "")
        line     = f.get("start", {}).get("line", "")
        lines.append(
            f"FILE: {rel_path}\n"
            f"SEVERITY: {sev}\n"
            f"ISSUE: {message}\n"
            f"CODE: line {line}\n"
            f"FIX: See semgrep rule {check_id}\n"
        )

    logger.info(f"[security] semgrep found {len(findings)} issues")
    return "\n".join(lines)


# ── LLM scan (all files, pass 3) ─────────────────────────────────────────────

def _build_prompt(batch: list[dict]) -> str:
    parts = []
    for f in batch:
        preview = f["content"][:MAX_CHARS]
        parts.append(f"### {f['path']}\n```\n{preview}\n```")
    return "\n\n".join(parts)


async def _audit_batch(batch: list[dict], idx: int, sem: asyncio.Semaphore) -> str:
    async with sem:
        prompt = _build_prompt(batch)
        return await llm_call_async("traversal", SYSTEM, prompt, max_tokens=1024)


# ── Main entry point ─────────────────────────────────────────────────────────

async def run_security_audit(modules: list[dict]) -> str:
    source = [m for m in modules if _should_audit(m["path"]) and m.get("content", "").strip()]

    # Pass 1: Bandit static scan on Python files (free, deterministic, full coverage)
    python_modules = [m for m in source if m.get("ext") == ".py"]
    bandit_section = _run_bandit(python_modules)
    if bandit_section:
        logger.info(f"[security] bandit scanned {len(python_modules)} Python files")

    # Pass 2: Semgrep multi-language scan (free, AST-based, requires semgrep binary)
    semgrep_section = _run_semgrep(source)

    # Pass 3: LLM semantic scan on all files
    batches = [source[i:i + BATCH_SIZE] for i in range(0, len(source), BATCH_SIZE)]
    sem     = asyncio.Semaphore(3)
    tasks   = [_audit_batch(b, i, sem) for i, b in enumerate(batches)]
    raw     = await asyncio.gather(*tasks, return_exceptions=True)

    sections = []
    for r in raw:
        if isinstance(r, Exception):
            logger.error(f"[security] batch failed: {r}")
        else:
            sections.append(r)

    if not sections and not bandit_section and not semgrep_section:
        return "# Security Report\n\nAll batches failed — check your API key and rate limits.\n"

    llm_section = "\n\n---\n\n".join(sections) if sections else ""

    parts = [
        "# Security Audit Report\n",
        "> Generated by Arkhe. Treat all findings as leads — "
        "verify manually before acting on them.\n",
    ]
    if bandit_section:
        parts.append(bandit_section)
    if semgrep_section:
        parts.append(semgrep_section)
    if llm_section:
        if bandit_section or semgrep_section:
            parts.append("\n## LLM Semantic Scan\n")
        parts.append(llm_section)

    return "\n".join(parts) + "\n"
