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
config/llm_client.py             — unified LLM wrapper (groq/gemini/anthropic/openai)
config/model_router.py           — model priority chains + cooldown fallback; persists to DB
agents/analyst_agent.py          — TPM-aware batch analysis (sequential, free-tier safe)
agents/synthesizer_agent.py      — final map synthesis
agents/parser_agent.py           — tree-sitter AST extraction (py/js/ts/go/rust/java/ruby)
agents/visualizer_agent.py       — D3 graph builder, loads template, complexity heatmap
agents/report_agent.py           — executive report generator (complexity-based model selection)
agents/refactor_agent.py         — per-file doc+style pass, thorough/fast modes, batching
agents/security_agent.py         — OWASP Top 10 LLM scan, concurrent batches (traversal model)
agents/dead_code_agent.py        — static dead symbol detection, zero LLM cost
agents/test_gap_agent.py         — test coverage gap analysis + pytest scaffold generation
agents/impact_agent.py           — PR blast radius: git diff → reverse dep walk → LLM summary
templates/dependency_map.html    — D3.js visualization template ({{NODES_JSON}}, {{LINKS_JSON}})
scripts/scan_codebase.py         — file scanner with gitignore support, Windows path normalization
output/map_writer.py             — writes CODEBASE_MAP.md to docs/
output/report_writer.py          — writes EXECUTIVE_REPORT.docx to docs/
output/clone_writer.py           — mirrors repo to <repo>_refactored/ with improved files
cache/db.py                      — SQLite-backed per-file cache (ArkheDB); stores AST + analysis keyed by content hash
commands/diff.py                 — `arkhe diff`: scan+parse current state vs SNAPSHOT.json, show file/dep changes
commands/watch.py                — `arkhe watch`: watchdog-based live reload, 3s debounce, re-runs full pipeline
tests/test_settings.py           — unit tests for BYOK chain parsing and model selection logic
tests/test_model_router.py       — unit tests for cooldown tracking and chain navigation
.github/workflows/ci.yml         — GitHub Actions CI: runs pytest on every push/PR to dev and main
.gitlab-ci.yml                   — GitLab CI: same tests, runs on MRs and dev/main pushes
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

- Dead code / test gap detection uses simple regex name matching — dynamic dispatch and `__all__` exports cause false positives.

---

## Progress Log

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
