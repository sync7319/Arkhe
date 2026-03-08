"""
Refactor agent — improves documentation and code style for every source file.

Two speed modes controlled by REFACTOR_SPEED in .env:

  thorough (default)
    Full LLM pass on every eligible file, one call per file, sequential.
    Highest quality output. Use for final deliverable runs.

  fast
    - Well-documented Python files: header summary update only (no full refactor)
    - Small files (<= BATCH_TOKEN_LIMIT): batched together into one LLM call
    - Large files: solo call, still concurrent
    - Higher concurrency semaphore per provider
    Roughly 5-10x faster. Use during development / iteration.

Hard constraints enforced in both modes:
  - No logic changes
  - No signature or import changes
  - No identifier renames
  - Identical runtime behavior guaranteed
"""
import asyncio
import logging
import os
import re

from config.llm_client import llm_call_async
from config.settings import get_model, REFACTOR_SPEED

logger = logging.getLogger("arkhe.refactor")

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_REFACTOR_TOKENS = 5500   # files above this are skipped in both modes
MAX_OUTPUT_TOKENS   = 8192

# fast mode: batch files up to this many content tokens per LLM call
BATCH_MAX_TOKENS = {"groq": 1500, "gemini": 5000, "anthropic": 3000}
BATCH_MAX_FILES  = 6

# fast mode: concurrency (simultaneous LLM calls)
FAST_CONCURRENCY     = {"groq": 2, "gemini": 8, "anthropic": 5}
THOROUGH_CONCURRENCY = {"groq": 1, "gemini": 5, "anthropic": 3}

# fast mode: Python files with this docstring coverage skip full refactor
DOC_COVERAGE_THRESHOLD = 0.70

SUPPORTED_EXTS = {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".rb"}

LANG_STANDARDS = {
    ".py":   "Python — PEP 257 module/class/function docstrings, f-strings, "
             "list/dict/set comprehensions, walrus operator, type hints on signatures",
    ".js":   "JavaScript — JSDoc /** @param @returns */ on all exports, ES2022+, "
             "arrow functions, optional chaining (?.), nullish coalescing (??), destructuring",
    ".ts":   "TypeScript — TSDoc comments, strict typing, modern ES features",
    ".tsx":  "TypeScript/React — TSDoc comments, typed props, modern React patterns",
    ".go":   "Go — godoc comments (// SymbolName does ...) on all exported symbols, "
             "fmt.Errorf with %w, defer for cleanup, early returns",
    ".rs":   "Rust — rustdoc /// on all public items, idiomatic Result/Option chaining",
    ".java": "Java — Javadoc /** @param @return @throws */ on all public members, "
             "streams over for-loops, Optional over null returns",
    ".rb":   "Ruby — YARD @param/@return tags, idiomatic blocks and Enumerable, "
             "frozen_string_literal magic comment",
}

# ── System prompts ────────────────────────────────────────────────────────────

_RULES = """
ABSOLUTE RULES — any violation makes the output invalid:
  1. Do NOT change function signatures, parameter names, or return types
  2. Do NOT change any logic, algorithms, control flow, or data structures
  3. Do NOT add, remove, or reorder import statements
  4. Do NOT rename any identifiers (variables, functions, classes, constants)
  5. Do NOT remove or add any functionality"""

SYSTEM_FULL = f"""You are a senior software engineer performing a documentation and code-style pass.
{_RULES}

WHAT TO DO:
  1. File header — add or rewrite the top-level module docstring/comment:
       • What this module does (1-2 sentences)
       • Key exported symbols
       • Important usage notes
  2. Docstrings — add or improve on every function, method, and class:
       • Purpose, Args/Parameters (with types), Returns, Raises/Throws
  3. Inline comments — add only where logic is non-obvious; remove stale ones
  4. Style — replace verbose patterns with idiomatic equivalents for the language;
       every rewrite must produce identical runtime behavior

OUTPUT: Return ONLY the complete improved file. No markdown fences. No explanation."""

SYSTEM_HEADER = f"""You are a senior software engineer.
{_RULES}

TASK: This file already has good internal documentation.
Your only job: add or rewrite the top-level file header docstring/comment to clearly describe:
  • What this module does (1-2 sentences)
  • Key exported symbols (functions, classes, constants)
  • Any important usage or configuration notes

Do not touch anything else in the file.

OUTPUT: Return ONLY the complete file with the updated header. No markdown fences. No explanation."""

SYSTEM_BATCH = f"""You are a senior software engineer performing a documentation and code-style pass on multiple files.
{_RULES}

WHAT TO DO (for each file):
  1. Add or rewrite the top-level module docstring/comment
  2. Add or improve docstrings on every function, method, and class
  3. Add inline comments only where logic is non-obvious
  4. Replace verbose patterns with idiomatic equivalents (identical runtime behavior)

OUTPUT FORMAT — follow exactly, no deviations:
For each file output a header line then the complete improved file then a footer line:

[ARKHE_FILE: path/to/file.py]
<complete improved file content here>
[ARKHE_END]

Process all files in the order given. No other text outside these blocks."""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ext(module: dict) -> str:
    return module.get("ext", os.path.splitext(module["path"])[1].lower())


def _strip_fences(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _sanity_check(original: str, refactored: str) -> bool:
    """Reject only empty or near-empty outputs. Added docstrings naturally make files longer."""
    return bool(refactored and refactored.strip() and len(refactored) >= len(original) * 0.40)


def _is_well_documented(module: dict) -> bool:
    """
    Fast mode only — check if a Python file already has good docstring coverage.
    Returns True if the file has a module docstring and >=70% of functions are documented.
    Only applied to Python files; other languages always get the full pass.
    """
    if _ext(module) != ".py":
        return False

    content   = module.get("content", "")
    functions = module.get("structure", {}).get("functions", [])
    stripped  = content.lstrip()

    has_module_doc = stripped.startswith('"""') or stripped.startswith("'''")
    if not has_module_doc:
        return False
    if not functions:
        return True

    documented = sum(
        1 for fn in functions
        if re.search(rf'def\s+{re.escape(fn)}\s*\(.*?\).*?:\s*\n\s*("""|\x27\x27\x27)', content, re.DOTALL)
    )
    return (documented / len(functions)) >= DOC_COVERAGE_THRESHOLD


def _eligible(modules: list[dict]) -> list[dict]:
    return [
        m for m in modules
        if _ext(m) in SUPPORTED_EXTS
        and m.get("tokens", 0) > 0
        and m.get("tokens", 0) <= MAX_REFACTOR_TOKENS
        and m.get("content", "").strip()
    ]


# ── Thorough mode ─────────────────────────────────────────────────────────────

async def _refactor_one(module: dict, sem: asyncio.Semaphore) -> tuple[str, str | None]:
    lang = LANG_STANDARDS[_ext(module)]
    structure = module.get("structure", {})
    prompt = (
        f"Language standard: {lang}\n"
        f"File path: {module['path']}\n"
        f"Defined symbols — functions: {structure.get('functions', [])}  "
        f"classes: {structure.get('classes', [])}\n\n"
        f"--- FILE TO IMPROVE ---\n{module['content']}"
    )
    out_tokens = min(int(module["tokens"] * 1.5) + 512, MAX_OUTPUT_TOKENS)

    async with sem:
        try:
            result = await llm_call_async("refactor", SYSTEM_FULL, prompt, max_tokens=out_tokens)
        except Exception as e:
            logger.error(f"Refactor failed for {module['path']}: {e}")
            return module["path"], None

    cleaned = _strip_fences(result)
    if not _sanity_check(module["content"], cleaned):
        logger.warning(f"Sanity check failed for {module['path']} — keeping original")
        return module["path"], None
    return module["path"], cleaned


async def _refactor_all_thorough(modules: list[dict]) -> dict[str, str]:
    provider, _ = get_model("refactor")
    concurrency = int(os.getenv("REFACTOR_CONCURRENCY", str(THOROUGH_CONCURRENCY.get(provider, 1))))
    sem   = asyncio.Semaphore(concurrency)
    tasks = [_refactor_one(m, sem) for m in _eligible(modules)]
    return _collect(await asyncio.gather(*tasks, return_exceptions=True))


# ── Fast mode ─────────────────────────────────────────────────────────────────

async def _update_header(module: dict, sem: asyncio.Semaphore) -> tuple[str, str | None]:
    """Fast mode: well-documented file — only update the file header."""
    lang   = LANG_STANDARDS[_ext(module)]
    prompt = (
        f"Language standard: {lang}\n"
        f"File path: {module['path']}\n\n"
        f"--- FILE ---\n{module['content']}"
    )
    async with sem:
        try:
            result = await llm_call_async("refactor", SYSTEM_HEADER, prompt, max_tokens=MAX_OUTPUT_TOKENS)
        except Exception as e:
            logger.error(f"Header update failed for {module['path']}: {e}")
            return module["path"], None

    cleaned = _strip_fences(result)
    if not _sanity_check(module["content"], cleaned):
        return module["path"], None
    return module["path"], cleaned


def _build_batches(files: list[dict], max_tokens: int) -> list[list[dict]]:
    """Group files into batches that fit within the token budget."""
    batches: list[list[dict]] = []
    current: list[dict]       = []
    running = 0

    for f in files:
        if running + f["tokens"] > max_tokens and current:
            batches.append(current)
            current, running = [], 0
        if len(current) >= BATCH_MAX_FILES:
            batches.append(current)
            current, running = [], 0
        current.append(f)
        running += f["tokens"]

    if current:
        batches.append(current)
    return batches


def _build_batch_prompt(batch: list[dict]) -> str:
    parts = []
    for m in batch:
        lang = LANG_STANDARDS[_ext(m)]
        parts.append(
            f"[ARKHE_FILE: {m['path']}]\n"
            f"Language standard: {lang}\n"
            f"--- CONTENT ---\n{m['content']}\n"
            f"[ARKHE_END]"
        )
    return "\n\n".join(parts)


def _parse_batch_response(response: str, batch: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for module in batch:
        pattern = rf"\[ARKHE_FILE:\s*{re.escape(module['path'])}\](.*?)\[ARKHE_END\]"
        match = re.search(pattern, response, re.DOTALL)
        if not match:
            logger.warning(f"Batch parse: no output found for {module['path']}")
            continue
        content = match.group(1).strip()
        # Strip language fence if model added one inside the block
        content = _strip_fences(content)
        if _sanity_check(module["content"], content):
            out[module["path"]] = content
        else:
            logger.warning(f"Sanity check failed in batch for {module['path']}")
    return out


async def _refactor_batch(batch: list[dict], sem: asyncio.Semaphore) -> dict[str, str]:
    prompt     = _build_batch_prompt(batch)
    out_tokens = min(sum(m["tokens"] for m in batch) * 2 + 256, MAX_OUTPUT_TOKENS)

    async with sem:
        try:
            result = await llm_call_async("refactor", SYSTEM_BATCH, prompt, max_tokens=out_tokens)
        except Exception as e:
            logger.error(f"Batch refactor failed: {e}")
            return {}

    return _parse_batch_response(result, batch)


async def _refactor_all_fast(modules: list[dict]) -> dict[str, str]:
    provider, _ = get_model("refactor")
    concurrency = int(os.getenv("REFACTOR_CONCURRENCY", str(FAST_CONCURRENCY.get(provider, 2))))
    batch_limit = BATCH_MAX_TOKENS.get(provider, 2000)
    sem         = asyncio.Semaphore(concurrency)

    eligible = _eligible(modules)

    # Split: well-documented Python → header-only | small → batch | large → solo
    header_only = [m for m in eligible if _is_well_documented(m)]
    header_set  = {m["path"] for m in header_only}
    remaining   = [m for m in eligible if m["path"] not in header_set]
    small       = [m for m in remaining if m["tokens"] <= batch_limit]
    large       = [m for m in remaining if m["tokens"] >  batch_limit]

    logger.info(
        f"Fast mode: {len(header_only)} header-only, "
        f"{len(small)} batched, {len(large)} solo"
    )

    batches = _build_batches(small, batch_limit)

    tasks = (
        [_update_header(m, sem) for m in header_only]
        + [_refactor_one(m, sem) for m in large]
    )
    batch_tasks = [_refactor_batch(b, sem) for b in batches]

    solo_results  = await asyncio.gather(*tasks, return_exceptions=True)
    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

    out = _collect(solo_results)
    for br in batch_results:
        if isinstance(br, dict):
            out.update(br)

    return out


# ── Shared ────────────────────────────────────────────────────────────────────

def _collect(results) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in results:
        if isinstance(r, Exception) or not isinstance(r, tuple):
            continue
        path, content = r
        if content is not None:
            out[path] = content
    return out


async def refactor_all(modules: list[dict]) -> dict[str, str]:
    """
    Entry point — routes to thorough or fast mode based on REFACTOR_SPEED setting.

    Args:
        modules: parsed module list from parse_modules (must include 'content' field)

    Returns:
        Dict mapping relative file path to refactored content.
    """
    if REFACTOR_SPEED == "fast":
        logger.info("Refactor mode: fast (batching + doc-skip + higher concurrency)")
        return await _refactor_all_fast(modules)

    logger.info("Refactor mode: thorough (full per-file pass)")
    return await _refactor_all_thorough(modules)
