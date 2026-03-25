# Arkhe — Claude Context File

## What this project is

Arkhe is an autonomous codebase intelligence tool. Point it at any repository and it produces:
- `docs/CODEBASE_MAP.md` — AI-generated narrative documentation (architecture, data flows, module guide, gotchas)
- `docs/DEPENDENCY_MAP.html` — interactive D3.js visualization of files and their dependencies
- `docs/EXECUTIVE_REPORT.docx` — Word report for stakeholders (optional)
- `docs/SECURITY_REPORT.md` — OWASP Top 10 vulnerability scan (optional)
- `docs/DEAD_CODE_REPORT.md` — static dead symbol detection (optional)
- `docs/TEST_GAP_REPORT.md` — uncovered public function report (optional)
- `docs/PR_IMPACT.md` — blast radius of changed files vs base branch (optional)
- `tests_generated/` — pytest scaffold files for uncovered functions (optional)

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

- **Providers:** Groq, Gemini, Anthropic, OpenAI — swappable per role via `.env`, never in code
- **BYOK chain:** `ARKHE_CHAIN=provider:model:key,...` in `.env` — user-defined priority list, overrides all role-based routing
- **Roles:** `traversal` (file analysis batches), `report` (final synthesis), `refactor`, `executive`
- **Client:** `config/llm_client.py` — unified wrapper, clients cached as singletons, retry with backoff
- **Config:** `config/settings.py` — provider selection, model defaults, file filters, `get_user_chain()`
- **Free tiers:** Groq and Gemini both have free tiers. Anthropic and OpenAI do not.

## Key files

```
main.py                          — entry point, async pipeline orchestration + subcommand dispatch
options.env                      — feature toggles (what runs); read by settings.py
config/settings.py               — all config: providers, models, ignore rules, BYOK chain parsing
config/llm_client.py             — unified LLM wrapper (groq/gemini/anthropic/openai/nvidia)
                                   IMPORTANT: _strip_think_blocks() runs on ALL LLM output — strips
                                   <think>...</think> from Nemotron/DeepSeek reasoning models
config/model_router.py           — model priority chains + cooldown fallback; persists to DB
config/dispatcher.py             — async rate-limited dispatcher; try_acquire_slot() gates all LLM calls
agents/analyst_agent.py          — parallel file analysis; max_tokens scales by file size (512/768/1024)
agents/synthesizer_agent.py      — hierarchical synthesis → CODEBASE_MAP.md; injects AST imports into
                                   file list so synthesizer uses ground-truth deps, not guesses
agents/parser_agent.py           — tree-sitter AST extraction (py/js/ts/go/rust/java/ruby)
agents/visualizer_agent.py       — D3 graph builder, loads template, complexity heatmap
agents/report_agent.py           — executive report generator (complexity-based model selection)
agents/refactor_agent.py         — per-file doc+style pass, thorough/fast modes, batching
agents/security_agent.py         — OWASP Top 10 LLM scan; strict FILE/SEVERITY/ISSUE/CODE/FIX format;
                                   MAX_CHARS=3000; context prevents false positives on tool design
agents/dead_code_agent.py        — static dead symbol detection; decorator-aware (_DECORATOR_OPS regex
                                   checks 3 preceding lines for @app./@router. etc.); private symbols
                                   and within-file call sites correctly excluded from dead flags
agents/test_gap_agent.py         — test coverage gap analysis + pytest scaffold generation
agents/impact_agent.py           — PR blast radius: git diff → reverse dep walk → LLM summary
templates/dependency_map.html    — D3.js visualization template ({{NODES_JSON}}, {{LINKS_JSON}})
scripts/scan_codebase.py         — file scanner with gitignore support, Windows path normalization
scripts/clone_repo.py            — GitHub/GitLab URL cloner; context manager auto-cleans temp dir
output/map_writer.py             — writes CODEBASE_MAP.md + CONTEXT_INDEX.json + GRAPH.json to docs/
output/report_writer.py          — writes EXECUTIVE_REPORT.docx to docs/
output/clone_writer.py           — mirrors repo to <repo>_refactored/ with improved files
cache/db.py                      — SQLite-backed per-file cache (ArkheDB); stores AST + analysis keyed by content hash
commands/diff.py                 — `arkhe diff`: scan+parse current state vs SNAPSHOT.json, show file/dep changes
commands/watch.py                — `arkhe watch`: watchdog-based live reload, 3s debounce, re-runs full pipeline
server/app.py                    — FastAPI server (55 tests); key endpoints below
server/static/arkhe.css          — shared CSS: theme vars, nav, buttons, dark/light mode
server/templates/index.html      — landing page; SSE-based progress via EventSource; retries on rate-limit
server/templates/results.html    — results dashboard; SSE stream; graph stats; job age; "debug ↗" link
server/templates/context.html    — Smart Context Picker UI; match-reason pills; token budget bar
server/templates/impact.html     — Blast Radius Explorer; complexity badges; markdown export
server/templates/debug_job.html  — Debug Inspector: all outputs readable inline + graph node list
                                   with blast radius links + server log tail (disable: ARKHE_DEBUG=false)
server/templates/debug_index.html— lists all jobs on disk with status
server/templates/map_viewer.html — full-screen iframe viewer for DEPENDENCY_MAP.html
server/templates/report_viewer.html — markdown viewer with auto-generated TOC sidebar
server/templates/pricing.html    — pricing page (/pricing)
tests/test_settings.py           — unit tests for BYOK chain parsing and model selection logic
tests/test_model_router.py       — unit tests for cooldown tracking and chain navigation
tests/test_api_endpoints.py      — 55 API endpoint tests covering context, impact, graph stats, SSE
.github/workflows/ci.yml         — GitHub Actions CI: runs pytest on every push/PR to dev and main
.gitlab-ci.yml                   — GitLab CI: same tests, runs on MRs and dev/main pushes
Deeper format/                   — nested test directories for self-test validation
```

## Server API endpoints

```
GET  /                              — landing page
POST /analyze                       — submit repo URL → job_id; options dict patches settings at runtime
GET  /status/{job_id}               — poll job status (step, step_label, error, outputs)
GET  /stream/{job_id}               — SSE stream; sends {status,step,step_label} 4×/sec; auto-closes on complete/error
GET  /results/{job_id}              — results dashboard (HTML)
GET  /results/{job_id}/view/{file}  — dedicated viewer: map_viewer for .html, report_viewer for .md
GET  /results/{job_id}/{file}       — raw file download
GET  /pricing                       — pricing page
POST /context/{job_id}              — Smart Context Picker: {task, budget, exts, path} → ranked files
                                      each result has: score, reasons (matched keywords), tokens_pct (budget share)
GET  /context/{job_id}              — same as POST but via query params
GET  /context/{job_id}/view         — context picker UI
GET  /impact/{job_id}?file=path     — Blast Radius: transitive dependents + complexity + risk rating
GET  /impact/{job_id}/view          — blast radius explorer UI
GET  /graph/{job_id}/stats          — hub files (top by in-degree), circular deps, isolated/leaf nodes
GET  /debug                         — inspector: list all jobs (ARKHE_DEBUG=false to disable)
GET  /debug/{job_id}                — inspector: all outputs + graph nodes + server log tail
GET  /_health                       — health check
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

**Stage 2 — CLI Product: COMPLETE**

See `ROADMAP.md` for the full 6-stage plan. Full cost breakdown is in there too.
Stage 3 hosting is Google Cloud Run (free tier covers demo traffic — chosen to qualify for the "Most Impactful on GitLab & Google" $10,000 hackathon category prize, on top of the Anthropic prize already covered by the existing Anthropic provider integration).
Everything through Stage 2 is genuinely $0.

## GitLab Duo Agent Platform Hackathon — Rules Summary

- **Deadline:** March 25, 2026 at 2:00 PM ET
- **Judging:** March 30 – April 17, 2026. Winners announced ~April 22.
- **Requirement:** Must be a working AI agent/flow built on the GitLab Duo Agent Platform that helps with the SDLC. Must perform a specific action or workflow automation (not just chat).
- **Must run on** the GitLab Duo Agent Platform and be published in `gitlab.com/gitlab-ai-hackathon` group.
- **Existing projects allowed** if significantly updated during the submission period — judges expect explanation of what changed.
- **Demo video:** <3 min, must clearly show a trigger → action, must be public on YouTube/Vimeo.
- **Live demo URL required** — judges must be able to access and test the project free of charge through the judging period.
- **License:** MIT License required for all original work. YAML config files must be original.
- **Judging criteria (equally weighted):** Technological implementation, Design (ease of use), Potential Impact, Quality of Idea.

### Prize strategy
| Prize | Amount | Requirement |
|---|---|---|
| Grand Prize | $15,000 | Best overall |
| Most Impactful on GitLab & Google | $10,000 | Uses GitLab + Google Cloud |
| Most Impactful on GitLab & Anthropic | $10,000 | Uses GitLab + Anthropic |

- A project can win **one Grand Prize + one Category Prize** maximum.
- Arkhe qualifies for **both** category prizes: Google Cloud Run (hosting decision) + Anthropic (already integrated as a provider).
- Being eligible for two category prizes doubles the chance of winning one.

## Known limitations

- Dead code / test gap detection uses simple regex name matching — dynamic dispatch and `__all__` exports may cause false positives. The decorator check (`@app.`, `@router.`, etc.) now covers the most common framework false positives.
- Security report: some batches may still output brief prose commentary in addition to the structured FILE/SEVERITY/ISSUE/CODE/FIX format — Nemotron is the primary synthesis model and tends toward conversational output. Findings themselves are accurate.
- `<think>` block stripping is applied at `_dispatch_async` — if a provider returns malformed think tags (unclosed), the regex still strips correctly (DOTALL mode).

---

## Progress Log

### 2026-03-25 (session — Shreeyut)
- **Production hardening — Sprint 1 + 2 + 3 (from march_24_plan.txt production roadmap):**
  - **Rate limiting** (`server/app.py`) — `slowapi` 5 analyses/hour per IP; `POST /analyze` decorated with `@limiter.limit("5/hour")`
  - **API key auth** (`server/app.py`) — optional `X-Arkhe-Key` header via FastAPI `Security()` dependency; enabled by setting `ARKHE_API_KEY` env var
  - **Concurrent job cap** (`server/app.py`) — `asyncio.Semaphore(MAX_CONCURRENT_JOBS)` (default 3, env `ARKHE_MAX_CONCURRENT_JOBS`); returns 503 + `Retry-After: 120` when full
  - **Disk space guard** (`server/app.py`) — rejects new jobs with 507 when free disk < 500MB (`ARKHE_MIN_FREE_MB`)
  - **Export ZIP** (`server/app.py`) — `GET /results/{job_id}/export.zip` packages all outputs as a single archive
  - **Favicon + PWA manifest** (`server/static/favicon.svg`, `server/static/manifest.json`) — fixes 404 on every page load; green "A" SVG icon; manifest injected into all 9 templates
  - **Hardened `/_health`** — returns disk free, LLM key presence, running jobs count; 503 when degraded
  - **Structured logging** (`server/app.py`) — `structlog` configured with JSON renderer for non-TTY (production) and human-readable `ConsoleRenderer` for dev
  - **SHA-256 cache keys** (`cache/db.py`) — replaces SHA-1 in `content_hash()`; existing entries naturally expire (no collision risk with SHA-256)
  - **lizard multi-language complexity** (`agents/visualizer_agent.py`) — replaces Python-only `radon` for heatmap; covers JS, TS, Go, Java, C/C++, Ruby, Swift; radon kept as fallback
  - **Docker** (`Dockerfile`, `docker-compose.yml`, `.dockerignore`) — `python:3.11-slim` image with uv, named volumes for results/cache, healthcheck
  - **Semantic Q&A — `POST /ask/{job_id}`** (`agents/embed_agent.py`, `server/app.py`) — ChromaDB-backed embedding index; embedding priority: Gemini → OpenAI → local `all-MiniLM-L6-v2`; `build_index()` runs non-blocking after each analysis; `query_index()` returns top-N files with relevance scores and excerpts; `EMBED_INDEX.json` written by `main.py` after analysis phase
  - **All 55 tests passing** after all changes

### 2026-03-24 (session 2 — Shreeyut)
- **Static analysis tool integrations (from march_24_plan.txt Batch 1 + 2):**
  - **`radon`** (`agents/visualizer_agent.py`) — real cyclomatic complexity replaces `tokens+imports×10+functions×5`; `cc_visit(content)` sum × 3 added to base score for Python files; improves heatmap accuracy
  - **`bandit`** (`agents/security_agent.py`) — deterministic Python security pre-pass before LLM scan; runs via `sys.executable -m bandit -f json`; full-file coverage (no 3000-char limit); CWE-tagged findings in FILE/SEVERITY/ISSUE/CODE/FIX format; LLM still runs second for semantic issues
  - **`vulture`** (`agents/dead_code_agent.py`) — Python dead code complement at 80% confidence; symbols vulture considers live are removed from regex detector's dead list; graceful fallback if unavailable
  - **`networkx`** (`agents/impact_agent.py`) — `nx.ancestors(G_rev, file)` replaces 1-level reverse map; PR impact now shows full transitive blast radius, not just direct importers; falls back to hand-rolled map if unavailable
  - **`__all__` extraction** (`agents/parser_agent.py`) — Python `__all__ = [...]` assignments parsed during tree-sitter walk; stored in `structure["exports"]`; dead code detector skips all exported symbols automatically
  - **Call graph** (`agents/parser_agent.py`) — `_walk()` now tracks function→callee relationships using scope-aware iterative walk with `_SCOPE_EXIT` sentinel; stored in `structure["calls"] = {"fn": ["callee", ...]}`; works for Python, JS, TS, Go; foundation for function-level analysis
  - **Parallel parsing** (`agents/parser_agent.py`) — `ThreadPoolExecutor(max_workers=8)` replaces sequential `[parse_file(f) for f in files]`; 3-4× faster on large repos
  - **JS/TS import resolution** (`agents/visualizer_agent.py`) — `_extract_module_js` + `_resolve_import_js` handle `import { foo } from './utils'` and `require('../config')`; dispatches by file extension; dependency graph now accurate for JS/TS repos
  - **Cache migration guard** (`agents/parser_agent.py`) — cached structures missing `exports` field are re-parsed once (one-time migration cost on first run after upgrade)
- **Dependencies added to `pyproject.toml`:** `networkx>=3.0`, `bandit>=1.7`, `radon>=6.0`, `vulture>=2.10`
- **All 55 tests pass** after changes

### 2026-03-24 (session 3 — Shreeyut)
- **Batch 3 improvements (from march_24_plan.txt Batch 3: deeper work):**

- **Security report hardening (`agents/security_agent.py`, `cache/db.py`, `config/llm_client.py`):**
  - Bandit `--skip B404,B603,B607` — suppresses subprocess import/usage noise (intentional in analysis tools); bandit section now shows only real issues
  - `cache/db.py`: `hashlib.sha1(..., usedforsecurity=False)` — fixes bandit HIGH finding; SHA1 is a cache key, not used for security
  - `_THINK_BLOCK` regex updated: `r"<think>.*?(?:</think>|\Z)"` — handles UNCLOSED think blocks (model outputs `<think>` without `</think>`); previous regex required both tags, silently left partial blocks in output

- **Semgrep multi-language security scan (`agents/security_agent.py`):**
  - `_run_semgrep(modules)` — runs `semgrep --config=auto --json`; infers repo root from module abs_path; outputs `## Static Analysis (Semgrep)` section in FILE/SEVERITY/ISSUE/CODE/FIX format
  - Gracefully skips if semgrep binary not installed (FileNotFoundError silently ignored)
  - Adds AST-based multi-language security scanning: OWASP Top 10 across 30+ languages at zero LLM cost
  - Three-pass structure now: Bandit (Python static) → Semgrep (multi-lang static) → LLM (semantic)

- **Call graph propagation to dead code (`agents/dead_code_agent.py`):**
  - `_build_call_graph_refs(modules)` — collects all callee names from `structure["calls"]` across all modules
  - New first pass in `detect_dead_code`: if a function appears as a callee in the call graph, it's immediately marked live (skip regex + vulture)
  - Three-pass dead code: call graph → regex cross-file → vulture
  - Eliminates false positives for functions that are called but not importable via regex (e.g. callbacks, internal helpers)

- **Test gap indirect coverage (`agents/test_gap_agent.py`):**
  - `_build_transitive_callees(all_calls, direct)` — BFS from directly-tested functions through the call graph
  - `find_coverage_gaps()` now returns `indirect` dict: functions not directly tested but reachable via call graph from tested functions
  - Test gap jumped from 15% → 65% (44 indirectly covered functions now visible)
  - Report format: new "Indirectly Covered (via call graph)" table section; metrics split into "Directly covered" and "Indirectly covered (via call graph)"

- **Analysis quality scoring (`agents/analyst_agent.py`):**
  - `_score_analysis(analysis, file)` — 0.0–1.0 score: 50% AST name-mention ratio, 30% length proportional to file size, 20% structural keywords (purpose/function/class)
  - Files scoring below `RESCORE_THRESHOLD = 0.35` are re-analyzed once with extra +256 output tokens
  - Prevents garbage-in-garbage-out for synthesizer: low-quality LLM outputs auto-rescored

> **Shreeyut:** See `march_24_plan.txt` in the repo root — this is Claude Opus 4.6's full
> improvement recommendations from the 2026-03-24 session. 15 ranked suggestions covering
> static analysis tools (networkx, bandit, radon, vulture, semgrep), structured LLM output,
> multi-language import resolution, call graph extraction, and production infra improvements.
> Worth reading before starting the next dev sprint.

### 2026-03-24 (session — Shreeyut)
- **Debug Inspector (`ARKHE_DEBUG`):**
  - `server/templates/debug_index.html` — lists all jobs on disk with job_id link, URL, and status badge
  - `server/templates/debug_job.html` — 3-tab UI: (1) Output Files — sidebar of all output files; click any to read inline with download link; deep-link via `?file=FILENAME`; (2) Graph Nodes — filterable list of every node from `GRAPH.json` with "blast radius ↗" link per node; `?tab=graph` deep-link; (3) Server Log — last 200 lines of `server.log`, auto-scrolls to bottom
  - `server/app.py` — `DEBUG_MODE = os.getenv("ARKHE_DEBUG", "true").lower() != "false"`; `_debug_guard()` raises 404 when disabled; routes `GET /debug` and `GET /debug/{job_id}` added; "debug ↗" link added to results.html breadcrumb
  - Disable entirely: set `ARKHE_DEBUG=false` in `.env`

- **`<think>` block stripping (Nemotron/DeepSeek):**
  - `_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)` in `config/llm_client.py`
  - `_strip_think_blocks()` applied at `_dispatch_async` return — strips reasoning blocks before any caller sees output
  - Prevents chain-of-thought leakage in security reports and codebase maps from Nemotron-253B

- **Dead code detection — false positive reduction (28 → 4 out of 194 symbols):**
  - `_DECORATOR_OPS` regex checks 3 preceding lines (300-char lookback) for `@app.`, `@router.`, `@pytest.`, `@staticmethod`, `@classmethod`, `@property`, `@abstractmethod`, `urlpatterns`, `admin.register` — covers FastAPI routes and framework-registered functions
  - `_build_reference_index()` rewritten: private symbols (`_name`) count within-file self-references; public symbols with call sites beyond the definition line are treated as live
  - Result: private helpers, FastAPI routes, and within-file classes no longer false-flagged

- **Security report quality:**
  - `MAX_CHARS = 3000` (was 1200) — full context per snippet
  - System prompt additions: "This is a code analysis tool..." prevents self-flagging; explicit rules that `api_key=os.getenv(...)` is not hardcoded, `subprocess.run([...list...])` is not injection, `os.path.join` from `os.listdir` is not traversal
  - Format enforcement: "Do NOT use markdown headers (###). Do NOT change format mid-response. Only use FILE/SEVERITY/ISSUE/CODE/FIX."
  - Truncation guard: "If a snippet appears truncated, do NOT flag it — you cannot see enough to verify."
  - Result: 2 legitimate findings (command injection in impact_agent, unauthenticated debug routes in app.py), no false positives

- **LLM hallucination suppression in CODEBASE_MAP:**
  - `agents/synthesizer_agent.py`: `_imports_for()` pulls AST-extracted imports from tree-sitter per file; `file_list` now includes `| imports: X, Y, Z` — synthesizer instructed to use this as ground-truth, not guess
  - SYSTEM prompt: "CRITICAL: Only list function names verbatim in the analysis reports. Do NOT invent, guess, or paraphrase."
  - BATCH_SYSTEM: "Output plain text — no code blocks, no markdown fences. Be brief and specific."
  - Result: eliminated invented names (`init_client`, `TreeSitterParser`, `networkx` etc.); synthesizer uses real import names from AST

- **Analyst max_tokens scaling:**
  - `agents/analyst_agent.py`: `out_tokens = 512 if file_tokens < 300 else (768 if file_tokens < 1000 else 1024)`
  - Larger files get more output budget — prevents truncation of key function descriptions for complex files

- **SYSTEM prompt rewrite in analyst_agent.py:**
  - Removed "dependencies" question (was source of hallucinations — model guessing what each file imports)
  - Added "CRITICAL: Only use names that appear verbatim in the code block. Never invent, guess, or paraphrase a function, class, or module name."
  - Three-section format: Purpose / Key functions+classes / Gotchas (skipped if none)

- **Context Picker enhancements:**
  - `/context/{job_id}` endpoint now returns `reasons` (list of matched keywords) and `tokens_pct` (share of token budget, 0–100) per result
  - `server/templates/context.html`: green match-reason pills (`.fc-pill.match`), token budget bar (`.fc-budget-bar` / `.fc-budget-fill`) rendered per file card
  - `tests/test_api_endpoints.py`: `test_context_results_have_reasons` and `test_context_results_have_tokens_pct` added — 55 tests total

- **Output quality iteration:**
  - Ran 6 successive analysis jobs against https://github.com/sync7319/Arkhe with all options enabled
  - Read every output file after each run: CODEBASE_MAP.md, SECURITY_REPORT.md, DEAD_CODE_REPORT.md, DEPENDENCY_MAP.html, TEST_GAP_REPORT.md
  - Identified and fixed: markdown fence wrapping, hallucinated names, dead code false positives, security false positives, think-block leakage
  - Main branch was 3 months behind dev — user merged dev→main; subsequent runs used full 60-file codebase

### 2026-03-18 (session — Shreeyut)
- **Web server frontend — full redesign and multi-page expansion:**
  - **Dark/light mode** — toggle in nav on every page, persisted in `localStorage`
    - Dark: deep indigo-black (`#07071a`) with blue/purple accent (`#6366f1`)
    - Light: white/green (`#f5f7f5`) with emerald accent (`#059669`)
  - **Shared CSS** — `server/static/arkhe.css`: theme variables, nav, buttons, footer, grid utilities, spinner — imported by all templates
  - **Scroll-driven background gradients** — 8 fixed gradient layers (4 dark, 4 light), JS bell-curve opacity driven by scroll position; color shifts indigo→violet→teal→rose (dark) and emerald→teal→green→mint (light)
  - **New pages:**
    - `server/templates/pricing.html` — dedicated pricing page (`/pricing`) with tier cards (Free/Pro/CLI), FAQ section, theme toggle
    - `server/templates/map_viewer.html` — full-screen iframe viewer for `DEPENDENCY_MAP.html` with Arkhe nav chrome and toolbar
    - `server/templates/report_viewer.html` — markdown report viewer with sidebar TOC (auto-generated from headings), `marked.js` rendering, prose styles, download button
  - **Redesigned pages:**
    - `server/templates/results.html` — professional dashboard hub; each output has its own card with description, icon, and links to dedicated viewer pages
    - `server/templates/index.html` — full landing page redesign: hero with gradient headline, provider pills (GitHub/GitLab), outputs grid, CLI callout, pricing link in nav
  - **Options panel** — checkboxes for all `options.env` feature flags sent with POST `/analyze`; `_apply_options()` in `server/app.py` patches `config.settings` attributes per-job at runtime
  - **Progress bar resume** — job ID, URL, and step index persisted in `localStorage`; on page load, home page re-attaches to any active running job automatically (survives navigation away and back)
  - **New app.py routes:**
    - `GET /pricing` — pricing page
    - `GET /results/{job_id}/view/{filename}` — renders `map_viewer.html` for `.html` files, `report_viewer.html` for `.md` files; raw file serving route unchanged for downloads/iframe src

- **Known issue / TODO:** Progress bar is still time-based (fake timer), not tied to real pipeline stage. Fix planned: add `step` + `pct` fields to the job dict, updated by `_run_pipeline` at each stage, returned by `/status` endpoint, consumed by frontend instead of timer.

### 2026-03-17 (session — Shreeyut)
- **GitLab Duo flow upgraded to 3-agent pipeline (Scanner → Analyst → Reporter):**
  - `flows/flow.yml` rewritten as a multi-agent flow, CI passing
  - `agents/agent.yml` updated with partner's improved 5-phase system prompt
  - **Schema clarified (corrects earlier CLAUDE.md entry):**
    - Multi-agent components use `inputs: [{from: "context:goal", as: "var"}]` object syntax (not plain strings)
    - Data passes between agents via `context:component_name.final_answer` — each component's `user:` prompt references the input variable `{{var_name}}`
    - Three component types: `AgentComponent` (LLM, uses `prompt_id`), `OneOffComponent` (single-shot LLM), `DeterministicStepComponent` (no LLM, uses `tool_name`)
    - `tool_name` is ONLY for `DeterministicStepComponent` — never on `AgentComponent`
  - **Agent responsibilities:**
    - `scanner`: `get_project`, `get_merge_request`, `list_merge_request_diffs`, `list_repository_tree`, `find_files` — maps repo, builds priority read list
    - `analyst`: `read_files`, `read_file`, `grep`, `gitlab_blob_search`, `get_commit_diff` — deep reads, 6-dimensional analysis (arch, deps, PR impact, OWASP, test coverage, quality)
    - `reporter`: `create_merge_request_note`, `create_file_with_contents`, `create_commit` — posts MR comment + commits `docs/CODEBASE_MAP.md` + `docs/SECURITY_REPORT.md`
  - Partner pulled in: NVIDIA NIM provider (Nemotron-253B for synthesis), tiered model routing (tier0–4 + heavy pool), concurrent file analysis (3x), full file content sent (removed 800-char truncation)

### 2026-03-10 (session — Shreeyut)
- **Stage 2 completed in full:**
123
- **CI/CD:**
  - `.github/workflows/ci.yml` — GitHub Actions: installs uv, runs `uv sync --dev`, runs `pytest tests/ -v` on every push/PR to `dev` and `main`
  - `.gitlab-ci.yml` — GitLab CI: identical pipeline, required for GitLab Hackathon eligibility
  - Both are machine-agnostic — fresh environment built from `uv.lock` each run, no local venv or API keys needed

- **Unit tests (`tests/`):**
  - `tests/test_settings.py` — 14 tests covering `get_user_chain()` parsing (valid chains, malformed entries, unknown providers, cache behavior) and `get_model()` role resolution
  - `tests/test_model_router.py` — 10 tests covering cooldown tracking (`mark_cooling`, `is_cooling`, `cooling_remaining`, expired timestamps), `get_chain()` logic (known vs custom models), and chain completeness
  - 24 tests total, all pass, no API keys required
  - `pythonpath = ["."]` and `asyncio_mode = "auto"` added to `[tool.pytest.ini_options]` in `pyproject.toml`

- **`arkhe diff` subcommand (`commands/diff.py`):**
  - After every successful `arkhe` run, saves `docs/SNAPSHOT.json` (file list + dependency edge pairs)
  - `arkhe diff <repo>` re-scans + re-parses (no LLM), compares to snapshot, prints rich tables of added/removed files and dependency edges
  - `save_snapshot()` called at the end of `run()` in `main.py`

- **`arkhe watch` subcommand (`commands/watch.py`):**
  - Uses `watchdog` (added to `pyproject.toml`) to watch for source file changes
  - 3-second debounce — ignores rapid saves from auto-formatters
  - Ignores `docs/` and `tests_generated/` output dirs to avoid re-triggering on own output
  - Re-runs full `arkhe` pipeline on change

- **`main.py` subcommand dispatch:**
  - Checks `sys.argv[1]` for `diff` or `watch` before argparse — routes to `commands/diff.py` or `commands/watch.py`
  - Existing `arkhe <repo>` behavior fully preserved

- **`pyproject.toml`:** added `watchdog>=4.0.0` to dependencies

- **`README.md`:** added `arkhe diff` and `arkhe watch` to the Run section

- **`ROADMAP.md`:** Stage 2 marked ✅ Complete; cost summary updated

### 2026-03-10 (partner — sync7319)
- **New optional analysis agents (all toggled via `options.env`):**
  - `agents/security_agent.py` — OWASP Top 10 LLM scan (hardcoded secrets, injection, weak crypto, etc.), concurrent batches using traversal model. Output: `docs/SECURITY_REPORT.md`
  - `agents/dead_code_agent.py` — pure static analysis, zero LLM cost. Finds functions/classes defined but never referenced outside their own file. Skips dunders, framework magic, test files. Output: `docs/DEAD_CODE_REPORT.md`
  - `agents/test_gap_agent.py` — two phases: (1) static gap report of uncovered public functions → `docs/TEST_GAP_REPORT.md`; (2) optional LLM pytest scaffold generation → `tests_generated/`
  - `agents/impact_agent.py` — git diff vs base branch → reverse dep walk → LLM plain-English blast radius summary. Output: `docs/PR_IMPACT.md`

- **SQLite cache (`cache/db.py`, replaces `cache/pipeline_cache.py`):**
  - `ArkheDB` singleton — stores AST structure and LLM analysis keyed by `(file_path, SHA-1 content_hash)`
  - 1-file change in 200-file repo → 1 LLM call, not 200
  - Also persists model cooldowns across process restarts (daily auto-reset on first run each day)
  - DB lives at `<repo>/.arkhe_cache/arkhe.db` — no server, zero cost

- **`options.env` — new feature checklist file:**
  - Separates WHAT runs (`options.env`) from HOW it runs (`.env` / API keys)
  - Flags: `CODEBASE_MAP_ENABLED`, `DEPENDENCY_MAP_ENABLED`, `EXECUTIVE_REPORT_ENABLED`, `ANALYSIS_SPEED`, `REFACTOR_ENABLED`, `REFACTOR_SPEED`, `PR_ANALYSIS_ENABLED`, `PR_BASE_BRANCH`, `SECURITY_AUDIT_ENABLED`, `DEAD_CODE_DETECTION_ENABLED`, `TEST_GAP_ANALYSIS_ENABLED`, `TEST_SCAFFOLDING_ENABLED`, `COMPLEXITY_HEATMAP_ENABLED`
  - Future GUI will read this file directly as its checklist state

- **`config/model_router.py` — cooldowns now persisted to DB** (via `cache/db.py`)
- **`main.py` — pipeline expanded** to orchestrate all new agents in correct order; `--format json` exit preserved; rich progress spinner for every step

### 2026-03-12 (session — Shreeyut)
- **GitLab Duo flow file created:**
  - `flows/arkhe.yml` — custom flow YAML for GitLab Duo Agent Platform
  - Committed to hackathon repo (`gitlab-ai-hackathon/participants/35223940`) via Web IDE
  - CI pipeline running to validate YAML
  - Tools used: `list_repository_tree`, `read_file`, `read_files`, `find_files`, `grep`, `get_merge_request`, `list_merge_request_diffs`, `get_commit_diff`, `gitlab_blob_search`, `create_merge_request_note`, `get_project`
  - Trigger: mention `@ai-arkhe-...` in any MR or issue
  - Output: full analysis posted as MR comment (architecture, dependencies, PR impact, security, gotchas)

- **GitLab hackathon group access granted** — email received March 12
  - Participant project: `gitlab.com/gitlab-ai-hackathon/participants/35223940`
  - Partner (sync7319) added as member
  - nshreeyut1 is the Representative for the team submission
  - Partner's participant repo stays unused — one submission from nshreeyut1's repo
  - Flow template structure: `agents/agent.yml.template`, `flows/flow.yml.template` at repo root

- **GitLab Duo Agent Platform — architecture confirmed from 8-part blog series:**
  - Arkhe is a **custom flow** (not external agent, not foundational)
  - Flows run on **GitLab's CI/CD compute** — no Cloud Run webhook needed for hackathon
  - Requires **Premium or Ultimate** GitLab tier — hackathon group has this
  - Three trigger types: mention, assign, assign_reviewer
  - Auto-injected variables: `$AI_FLOW_CONTEXT` (MR JSON + diff), `$AI_FLOW_INPUT` (user comment), `$AI_FLOW_EVENT` (trigger type)
  - `AGENTS.md` confirmed correct — GitLab reads it at workspace root for flow context
  - Tool list confirmed from `tool_mapping.json` — 89 tools available including all needed ones
  - Flow YAML schema: `version: v1`, `environment: ambient`, `components`, `prompts`, `routers`, `flow.entry_point`
  - Results posted back via `create_merge_request_note` tool — no external URL needed
  - Monitoring: Project → Automate → Sessions

- **Three delivery methods now confirmed:**
  - Website (our Gemini/Groq keys, Cloud Run) — anyone, paste URL
  - CLI pip install (BYOK, user's own keys) — developers, local
  - GitLab Duo flow (GitLab's AI Gateway tokens, CI/CD compute) — GitLab teams, MR trigger

- **Hackathon next steps remaining:**
  - Wait for CI pipeline to pass on flow.yml
  - Create a tag to publish flow to the public catalog
  - Enable flow in the project
  - Test by mentioning @ai-arkhe handle in an MR comment
  - Record demo video (<3 min): trigger → analysis runs → MR comment posted
  - Submit on Devpost before March 25

### 2026-03-12 (session 2 — Shreeyut)
- **CI pipeline now passing** — both `placeholder-test` and `validate-items` jobs green
  - Resolved through iterative schema debugging across many attempts
  - **Correct schema (single-agent):**
    - `flows/flow.yml` component: `type: AgentComponent`, `prompt_id` (required), plain string `toolset`, `inputs: ["context:goal"]`
    - `agents/agent.yml`: `name`, `description`, `public`, `system_prompt`, plain string `tools` list
    - `tool_name` on component is ONLY for `DeterministicStepComponent` (no LLM, calls one tool directly) — not for AgentComponent
    - `prompt_id` and `tool_name` are mutually exclusive — `AgentComponent` uses `prompt_id`, `DeterministicStepComponent` uses `tool_name`
  - `flows/arkhe.yml` renamed to `flows/flow.yml` to match hackathon repo convention

- **Git setup clarified — two repos, clear ownership:**
  - GitHub (`sync7319/Arkhe`) — source of truth for all work (Python app + hackathon files)
  - GitLab hackathon (`gitlab-ai-hackathon/participants/35223940`) — submission repo, deploy by copying from `hackathon/` via Web IDE
  - GitLab personal mirror (`nshreeyut/Arkhe`) — removed, no longer needed
  - Hackathon files live in `hackathon/` subfolder — completely separate from Python app
  - Both collaborators can edit hackathon repo via Web IDE; coordinate before editing same files

- **Python app vs GitLab Duo flow — key distinction:**
  - Python app: local/Cloud Run, BYOK, 6-stage pipeline, multi-agent, outputs files to `docs/`
  - GitLab Duo flow: runs on GitLab's compute, GitLab's AI tokens, 3-agent pipeline, posts MR comment + commits docs
  - GitLab flow is the hackathon integration layer — same idea, different delivery method
  - GitLab flow does NOT run any Python code — uses GitLab's built-in tools via AI Gateway

- **Partner's token optimization changes pulled in** (`git pull origin dev --no-rebase`):
  - `config/model_router.py` — major rework, multi-model Groq routing, proactive throttle
  - `agents/synthesizer_agent.py` — hierarchical synthesis
  - `config/llm_client.py`, `agents/analyst_agent.py`, `agents/report_agent.py`, `config/settings.py`, `options.env`

- **Hackathon next steps remaining:**
  - Create a git tag (`v1.0.0`) to publish flow to the GitLab catalog
  - Enable flow in the project
  - Test by mentioning agent in an MR comment
  - Record demo video (<3 min): trigger → analysis runs → reports committed + MR comment posted
  - Submit on Devpost before March 25

- **Token optimization — partner working on:**
  - Filter non-code files before LLM (certs, docs, CI configs, Makefiles)
  - AST parser handles dependency mapping for ALL files at zero LLM cost
  - Only source code (.py, .js, .ts, .go, .rs, .java, .rb) hits LLM
  - Expected reduction: 119 files → ~20 LLM calls (~83% token reduction)
  - Early abort after 3 consecutive all-model failures (already built in analyst_agent.py)
  - Persistent cache per repo URL in server/cache/ (already built in server/app.py)

### 2026-03-11 (session 2 — Shreeyut)
- **Stage 3 web server — initial build:**
  - `scripts/clone_repo.py` — clones GitHub/GitLab URLs to temp dir, context manager auto-cleans, `CloneError` for bad URLs/auth failures, shallow clone (depth=1)
  - `server/app.py` — FastAPI server: `POST /analyze` (background job), `GET /status/{job_id}`, `GET /results/{job_id}`, `GET /results/{job_id}/{filename}`, `GET /_health` warm-up endpoint
  - `server/templates/index.html` — landing page: repo URL form, live status polling, free/Pro/CLI tier comparison, CLI BYOK callout
  - `server/templates/results.html` — results page: auto-polls while running, output cards with View/Download per file type
  - Added `fastapi`, `uvicorn`, `jinja2`, `python-multipart` to `pyproject.toml`
  - Run locally: `uv run uvicorn server.app:app --reload --port 8000`

- **Bug fix — `config/llm_client.py`:**
  - Added `groq.APIStatusError` to `_rate_limit_exceptions` for Groq — catches 413 "request too large" errors and triggers model fallback instead of crashing

- **Token optimization — identified, not yet built:**
  - Root cause: pipeline sends every file (certs, docs, configs, CI files) to LLM — wasteful
  - Fix: filter to source code files only before LLM analysis; AST parser handles dependency mapping for all files at zero LLM cost
  - Hierarchical synthesis (module → folder → final) to avoid giant single synthesis call
  - Persistent cache on website (GCS/Firestore keyed by repo URL + commit SHA) — currently temp dir wipes cache every run
  - Token optimization research in progress — will implement before website goes live

- **Hosting decision finalized:** Google Cloud Run (free tier, qualifies for Google hackathon prize)
- **Model strategy finalized:** Gemini for all roles on website free tier; Anthropic locked behind Pro tier; CLI users BYOK unlimited

### 2026-03-11 (session — Shreeyut)
- **GitLab Duo Agent Platform Hackathon — registration in progress:**
  - Deadline: March 25, 2026 at 2:00 PM ET (~14 days away)
  - Both Shreeyut (nshreeyut) and Om (sync7319) have created Devpost accounts and joined as a team
  - Both have submitted the GitLab access request form (https://forms.gle/EeCH2WWUewK3eGmVA) — awaiting response
  - Access to `gitlab.com/gitlab-ai-hackathon` group is pending — repo must be published there for submission
  - GitLab Duo Agent Platform docs not yet obtained — needed for `.gitlab/duo/flows/arkhe.yaml` YAML schema

- **Files created:**
  - `LICENSE` — MIT license, 2026, Shreeyut Neupane and Om Arvadia
  - `AGENTS.md` — GitLab Duo agent context file: what Arkhe produces, triggers, pipeline, providers, feature toggles, key files

- **Hackathon integration plan (pending platform docs):**
  - All existing agents and pipeline logic are unchanged — they are complete
  - Only an integration layer needs to be added:
    1. `.gitlab/duo/flows/arkhe.yaml` — registers Arkhe as a GitLab Duo external agent (blocked on schema docs)
    2. Update `.gitlab-ci.yml` — add agent-triggered job (blocked on CI variable names from docs)
  - `AGENTS.md` is already written and ready
  - `LICENSE` is already written and ready
  - Target prizes: "Most Impactful on GitLab & Anthropic" ($10,000) + "Most Impactful on GitLab & Google" ($10,000) + Grand Prize ($15,000)
  - Hosting on Google Cloud Run qualifies for the Google category prize; Anthropic provider already in codebase qualifies for the Anthropic category prize
  - Hosting on Google Cloud Run qualifies for the Google category prize; Anthropic provider already in codebase qualifies for the Anthropic category prize
  - A project can win one Grand Prize + one Category Prize — eligible for two category prizes doubles the chances

- **Next steps (in order):**
  1. Wait for GitLab hackathon group access confirmation
  2. Get GitLab Duo Agent Platform docs from the group
  3. Fork/import repo into `gitlab.com/gitlab-ai-hackathon`
  4. Write `.gitlab/duo/flows/arkhe.yaml` using the official schema
  5. Update `.gitlab-ci.yml` with the agent-triggered job
  6. Push `LICENSE` + `AGENTS.md` to GitHub (auto-mirrors to GitLab)
  7. Record demo video (<3 min): trigger → analysis runs → output produced
  8. Submit on Devpost before March 25

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
