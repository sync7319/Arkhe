# Arkhe — Agent Context

Arkhe is an autonomous codebase intelligence tool. It deploys a suite of specialized AI agents against any repository and produces always-current documentation, visualizations, and analysis reports — automatically, on every run.

---

## What Arkhe produces

| Output | Description |
|--------|-------------|
| `docs/CODEBASE_MAP.md` | AI-generated architecture narrative: data flows, module guide, gotchas |
| `docs/DEPENDENCY_MAP.html` | Interactive D3.js graph of every file and its dependencies |
| `docs/EXECUTIVE_REPORT.docx` | Word report summarizing architecture for stakeholders |
| `docs/SECURITY_REPORT.md` | OWASP Top 10 vulnerability scan across all source files |
| `docs/DEAD_CODE_REPORT.md` | Functions and classes defined but never referenced |
| `docs/TEST_GAP_REPORT.md` | Public functions with no test coverage |
| `docs/PR_IMPACT.md` | Blast radius of changed files vs base branch |
| `tests_generated/` | pytest scaffold files for every uncovered function |

---

## How to trigger Arkhe

**As a GitLab Duo agent:**
- Assign Arkhe as a reviewer on any merge request
- Mention `@arkhe` in an MR or issue comment

**As a CLI tool:**
```bash
arkhe ./my-project          # full analysis
arkhe diff ./my-project     # compare vs last snapshot (no LLM)
arkhe watch ./my-project    # re-analyze on every file change
```

---

## Pipeline

```
scan → parse (tree-sitter AST) → analyze (LLM per file) → synthesize → visualize → write
```

1. **Scan** — walks the repo, reads files, counts tokens, respects `.gitignore`
2. **Parse** — extracts AST (functions, classes, imports) via tree-sitter for 7 languages
3. **Analyze** — batches files, calls LLM sequentially with TPM-aware rate limiting
4. **Synthesize** — combines batch reports into the final `CODEBASE_MAP.md`
5. **Visualize** — builds dependency graph, injects into D3.js template
6. **Write** — outputs all reports to `docs/`

---

## Supported languages

Python · JavaScript · TypeScript · Go · Rust · Java · Ruby

---

## LLM providers

Arkhe supports Anthropic, Groq, Gemini, and OpenAI. Provider and model are configured via environment variables — BYOK (Bring Your Own Key). Groq and Gemini have free tiers; the full pipeline runs at $0 with either.

A model fallback router automatically cascades to the next model on rate limits, with cooldowns persisted to SQLite across restarts.

---

## Feature toggles

All optional agents are off by default and enabled via `options.env`:

```
SECURITY_AUDIT_ENABLED=true
DEAD_CODE_DETECTION_ENABLED=true
TEST_GAP_ANALYSIS_ENABLED=true
TEST_SCAFFOLDING_ENABLED=true
PR_ANALYSIS_ENABLED=true
EXECUTIVE_REPORT_ENABLED=true
COMPLEXITY_HEATMAP_ENABLED=true
REFACTOR_ENABLED=true
```

---

## Caching

Results are cached in SQLite keyed by file content hash (`<repo>/.arkhe_cache/arkhe.db`). On a re-run, only files that changed since the last run hit the LLM. A 200-file repo with 1 changed file makes 1 LLM call.

---

## Key files

```
main.py                      — pipeline orchestration + subcommand dispatch
config/settings.py           — provider selection, model defaults, BYOK chain parsing
config/llm_client.py         — unified LLM wrapper (Anthropic, Groq, Gemini, OpenAI)
config/model_router.py       — priority chains + cooldown fallback
agents/analyst_agent.py      — TPM-aware batch file analysis
agents/synthesizer_agent.py  — final map synthesis
agents/parser_agent.py       — tree-sitter AST extraction
agents/visualizer_agent.py   — D3.js dependency graph builder
agents/security_agent.py     — OWASP Top 10 scan
agents/dead_code_agent.py    — static dead symbol detection
agents/test_gap_agent.py     — test coverage gap analysis + scaffold generation
agents/impact_agent.py       — PR blast radius analysis
agents/report_agent.py       — executive Word report generation
cache/db.py                  — SQLite cache (ArkheDB)
options.env                  — feature toggles
```
