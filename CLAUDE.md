# Arkhe — Claude Context File

## What this project is

Arkhe is an autonomous codebase intelligence tool. Point it at any repository and it produces two outputs:
- `docs/CODEBASE_MAP.md` — AI-generated narrative documentation (architecture, data flows, module guide, gotchas)
- `docs/DEPENDENCY_MAP.html` — interactive D3.js visualization of files and their dependencies

**Run it:** `uv run python main.py [repo_path]`
**Self-test:** `uv run python main.py .` (Arkhe maps itself)

## The business

- **Pain point:** Developers waste hours onboarding to unfamiliar codebases. Docs rot. Nobody updates them.
- **Solution:** Arkhe regenerates documentation automatically on every PR — always current, never manual.
- **Model:** BYOK (Bring Your Own Key). Users supply their own LLM API keys. We never pay inference costs.
- **Repo:** https://github.com/sync7319/Arkhe (private)
- **Collaborators:** nshreeyut (Shreeyut), sync7319 (partner)

## Pipeline (in order)

```
scan → parse → analyze → synthesize → visualize → write
```

| Step | File | What it does |
|------|------|-------------|
| Scan | `scripts/scan_codebase.py` | Walk repo, read files, count tokens via tiktoken, respect .gitignore |
| Parse | `agents/parser_agent.py` | Extract AST (functions, classes, imports) via tree-sitter. Iterative walk. |
| Analyze | `agents/analyst_agent.py` | Batch files, call LLM sequentially (traversal role) with TPM-aware batching |
| Synthesize | `agents/synthesizer_agent.py` | Combine batch reports → CODEBASE_MAP.md (report role) |
| Visualize | `agents/visualizer_agent.py` | Build graph data, inject into `templates/dependency_map.html` |
| Write | `output/map_writer.py` | Write CODEBASE_MAP.md to `docs/` |

## LLM system

- **Providers:** Groq, Gemini, Anthropic — swappable per role via `.env`, never in code
- **Roles:** `traversal` (file analysis batches), `report` (final synthesis)
- **Client:** `config/llm_client.py` — unified wrapper, clients cached as singletons, retry with backoff
- **Config:** `config/settings.py` — provider selection, model defaults, file filters
- **Free tiers:** Groq and Gemini both have free tiers. Anthropic does not.

## Key files

```
main.py                          — entry point, async pipeline orchestration
config/settings.py               — all config: providers, models, ignore rules
config/llm_client.py             — unified LLM wrapper (groq/gemini/anthropic)
agents/analyst_agent.py          — TPM-aware batch analysis (sequential, free-tier safe)
agents/synthesizer_agent.py      — final map synthesis
agents/parser_agent.py           — tree-sitter AST extraction (py/js/ts)
agents/visualizer_agent.py       — D3 graph builder, loads template
agents/report_agent.py           — executive report generator (complexity-based model selection)
agents/refactor_agent.py         — per-file doc+style pass, thorough/fast modes, batching
templates/dependency_map.html    — D3.js visualization template ({{NODES_JSON}}, {{LINKS_JSON}})
scripts/scan_codebase.py         — file scanner with gitignore support
output/map_writer.py             — writes CODEBASE_MAP.md to docs/
output/report_writer.py          — writes EXECUTIVE_REPORT.docx to docs/
output/clone_writer.py           — mirrors repo to <repo>_refactored/ with improved files
config/model_router.py           — model priority chains + 10-min cooldown fallback system
Deeper format/                   — nested test directories for self-test validation
```

## Dev environment

- **Package manager:** UV (`uv sync` to install, `uv run` to execute)
- **Python:** >=3.11 (lockfile at `uv.lock` — ensures identical env across machines)
- **Venv:** `.venv/` — created by `uv sync`, never committed
- **API keys:** `.env` (copy from `.env.example`, never committed)

## Git workflow

```
main  ← stable releases only
  └── dev  ← all features land here first
        └── feature/name/task  ← individual sandboxes
```

- Branch off `dev`, PR back into `dev`, merge `dev` → `main` for releases
- Never push directly to `main` or `dev`
- See `CONTRIBUTING.md` for full commands and partner onboarding

## Current stage and what's done

**Stage 0 — Foundation: COMPLETE**

See `ROADMAP.md` for the full 5-stage plan. Full cost breakdown is in there too.
The first unavoidable cost is ~$7/mo at Stage 3 (always-on webhook server).
Everything through Stage 2 is genuinely $0.

## Known limitations (next to fix in Stage 1)

- `llm_call_async` still uses `run_in_executor` (thread pool) — not true async. Native async clients exist for all providers.
- Dependency graph matching in `visualizer_agent.py` is naive string matching — false positives, misses relative imports.
- No caching of intermediate results — pipeline failure means full restart.
- `analyze_sequential` processes batches one at a time — parallelism with a semaphore is possible.
- Only Python/JS/TS supported — Go, Rust, Java are Stage 1 additions.

---

## Progress Log

### 2026-03-09 (session 2)
- **Dependency map visual overhaul:**
  - Full light theme redesign (white cards on `#f1f5f9` canvas — no more navy)
  - Professional color palette (blue, emerald, amber, violet, etc.)
  - All dependency arrows now route through a dedicated right-side bypass lane — never overlap nodes
  - Mutual deps drawn as two separate offset paths, each with own arrowhead
  - Info panel redesigned: Defines (fn/class badges), Imports (local resolved + external separated), Imported By (reverse deps), all clickable to jump to that file
  - `focusNode()` auto-expands folder when clicking linked file in panel

- **Refactored clone output (`--refactor` / `REFACTOR_ENABLED`):**
  - New `agents/refactor_agent.py` — per-file doc+style pass, no logic changes
  - Two speed modes via `REFACTOR_SPEED` in `.env`:
    - `thorough` — full LLM pass per file, one call each
    - `fast` — well-documented Python files get header-only update; small files batched together; higher concurrency semaphore per provider
  - New `output/clone_writer.py` — mirrors full repo to `<repo>_refactored/`, originals untouched
  - `REFACTOR_ENABLED=true/false` in `.env` — controls whether refactor runs automatically
  - Sanity check only rejects empty/near-empty outputs (no upper length bound — docs naturally make files longer)

- **Model fallback router (`config/model_router.py`):**
  - Priority chains best→worst for groq, gemini, anthropic
  - Groq: kimi-k2 → qwen3-32b → gpt-oss-120b → llama-3.3-70b → llama-4-maverick → llama-4-scout → gpt-oss-20b → llama-3.1-8b
  - Gemini: 2.5-pro → 2.5-flash → 2.0-flash → 2.5-flash-lite → 2.0-flash-lite
  - Anthropic: opus-4-6 → sonnet-4-6 → haiku-4-5
  - Rate limit → mark model cooling 10 min, auto-fallback to next
  - Transient errors (connection/timeout) → retry same model
  - `llm_client.py` split `_retryable_exceptions` into `_rate_limit_exceptions` + `_transient_exceptions`

- **Settings additions:**
  - `REFACTOR_ENABLED`, `REFACTOR_SPEED`, `REFACTOR_PROVIDER`, `REFACTOR_CONCURRENCY`
  - `refactor` role added to `VALID_ROLES`, always uses cheap models

### 2026-03-09
- **Executive Word report node (merged to dev):**
  - New `agents/report_agent.py` — final pipeline node that consumes all outputs (codebase map, batch reports, dependency graph) and generates a professional executive report: 1-page summary (250-450 words), strengths, weaknesses, security concerns, recommended updates, basic documentation
  - New `output/report_writer.py` — renders report as `docs/EXECUTIVE_REPORT.docx` using `python-docx` with proper Word heading styles, bullet/numbered lists, margins
  - Added `llm_call_async_explicit()` to `config/llm_client.py` — bypasses role resolution for runtime model selection
  - **Cost-gated model tiers in `config/settings.py`:**
    - `EXPENSIVE_MODELS_ALLOWED=false` (default) — all roles use cheap models (safe for testing / free tier)
    - `EXPENSIVE_MODELS_ALLOWED=true` — synthesis uses Sonnet; executive report uses Opus (large repo, ≥50k tokens) or Sonnet (small repo); traversal always stays cheap
    - `COMPLEXITY_THRESHOLD_TOKENS` controls large/small cutoff (default 50 000)
    - `EXECUTIVE_PROVIDER` controls which provider handles the Word report (default: anthropic)
  - Added `python-docx>=1.1.0` to `pyproject.toml`
  - Updated `.env.example` with all new vars: `EXECUTIVE_PROVIDER`, `EXPENSIVE_MODELS_ALLOWED`, `COMPLEXITY_THRESHOLD_TOKENS`, `EXECUTIVE_MODEL`
  - Installed `gh` CLI and authenticated — git push now works via `gh auth setup-git`
  - Self-tested (`uv run python main.py .`) — all three outputs generated successfully

### 2026-03-08
- Audited full codebase, identified all bugs and design issues
- Created `ROADMAP.md` — 5-stage plan from CLI tool to SaaS with full cost breakdown
- Set up UV: `pyproject.toml`, `uv.lock`, `.gitignore` — partner can `uv sync` and be running in minutes
- Created `CONTRIBUTING.md` — full onboarding + git workflow guide for both collaborators
- Initialized local git repo, connected to GitHub, established `main` and `dev` branches
- **Stage 0 bug fixes (all merged to main):**
  - Renamed `analyze_parallel` → `analyze_sequential` (it was never parallel)
  - Cached LLM clients as singletons — no more reinstantiation per call
  - Fixed `asyncio.get_event_loop()` → `asyncio.get_running_loop()`
  - Moved `_retryable_exceptions()` outside retry loop
  - Made `synthesize()` async — was blocking the event loop
  - Replaced recursive AST walk with iterative stack — no more recursion limit risk
  - Extracted 420-line inline D3 HTML into `templates/dependency_map.html`
  - Removed dead `MAPPING_PROVIDER` role and its config
  - Removed unused `MAX_TOKENS_PER_BATCH` import and unused `model` param
  - Deleted `requirements.txt` — replaced by `pyproject.toml` + `uv.lock`
