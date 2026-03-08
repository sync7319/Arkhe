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
templates/dependency_map.html    — D3.js visualization template ({{NODES_JSON}}, {{LINKS_JSON}})
scripts/scan_codebase.py         — file scanner with gitignore support
output/map_writer.py             — writes CODEBASE_MAP.md to docs/
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
