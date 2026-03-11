# Arkhe

**Autonomous codebase intelligence.** Point it at any repo and get AI-generated architecture docs, an interactive dependency graph, and optional deep analysis — in minutes.

---

## What it produces

| Output | Description |
|--------|-------------|
| `docs/CODEBASE_MAP.md` | AI narrative: architecture, data flows, module guide, gotchas |
| `docs/DEPENDENCY_MAP.html` | Interactive D3.js graph of every file and its dependencies |
| `docs/EXECUTIVE_REPORT.docx` | Word report for stakeholders *(optional)* |
| `docs/SECURITY_REPORT.md` | OWASP Top 10 vulnerability scan *(optional)* |
| `docs/DEAD_CODE_REPORT.md` | Functions and classes defined but never used *(optional)* |
| `docs/TEST_GAP_REPORT.md` | Public functions with no test coverage *(optional)* |
| `docs/PR_IMPACT.md` | Blast radius of changed files vs base branch *(optional)* |
| `tests_generated/` | pytest scaffold files for every uncovered function *(optional)* |

---

## Install

```bash
pip install arkhe
```

Requires Python 3.11+.

---

## Setup

Create a `.env` file in the directory where you run Arkhe:

```bash
cp .env.example .env
```

Then add at least one API key. **Groq and Gemini are both free:**

```
GROQ_API_KEY=your_groq_key_here       # free — https://console.groq.com
GEMINI_API_KEY=your_gemini_key_here   # free — https://aistudio.google.com
```

That's all you need to run the full core pipeline at $0.

---

## Run

```bash
arkhe ./my-project                # analyze a local repo
arkhe .                           # analyze the current directory
arkhe ./my-project --refactor     # also generate a refactored clone
arkhe ./my-project --format json  # machine-readable output
```

Outputs are written to `./my-project/docs/`.

### Other commands

```bash
arkhe diff ./my-project   # compare current state vs last snapshot (no LLM, fast)
arkhe watch ./my-project  # re-analyze automatically whenever files change
```

`arkhe diff` saves a `docs/SNAPSHOT.json` on every run and diffs against it — shows files added/removed and dependency edges added/removed.

---

## BYOK fallback chain

If you have keys from multiple providers, you can define your own fallback priority list. Arkhe tries each entry in order — if one hits a rate limit, it moves to the next automatically.

Add `ARKHE_CHAIN` to your `.env`:

```
# OpenAI first, Gemini second, Groq as last resort
ARKHE_CHAIN=openai:gpt-4o:sk-xxx,gemini:gemini-2.5-pro:AIza_yyy,groq:llama-3.3-70b-versatile:gsk_zzz
```

Format: `provider:model:api_key` — comma-separated. Mix any providers freely.

**Supported providers:** `openai` · `groq` · `gemini` · `anthropic`

When `ARKHE_CHAIN` is set, the individual `*_PROVIDER` settings are ignored — your chain takes over for all roles.

---

## Optional features

Create an `options.env` file to enable extra outputs:

```bash
# options.env

SECURITY_AUDIT_ENABLED=true       # OWASP Top 10 scan → docs/SECURITY_REPORT.md
DEAD_CODE_DETECTION_ENABLED=true  # static analysis   → docs/DEAD_CODE_REPORT.md
TEST_GAP_ANALYSIS_ENABLED=true    # coverage gaps     → docs/TEST_GAP_REPORT.md
TEST_SCAFFOLDING_ENABLED=true     # generate pytest stubs → tests_generated/
PR_ANALYSIS_ENABLED=true          # PR blast radius   → docs/PR_IMPACT.md
COMPLEXITY_HEATMAP_ENABLED=true   # color nodes by complexity in the dependency map

EXECUTIVE_REPORT_ENABLED=true     # Word report — requires ANTHROPIC_API_KEY (paid)
REFACTOR_ENABLED=true             # generate a refactored clone of the repo
```

All features are **off by default**. Enable only what you need.

---

## Supported languages

Python · JavaScript · TypeScript · Go · Rust · Java · Ruby

---

## How it works

```
scan → parse (tree-sitter AST) → analyze (LLM per file) → synthesize → visualize
```

- **Incremental:** results are cached by file content hash — only changed files hit the LLM on re-runs
- **Rate-limit resilient:** model fallback router automatically cascades to the next model if one rate-limits
- **Free-tier safe:** default config uses Groq + Gemini free tiers; concurrent calls are bounded to stay within TPM limits

---

## Self-test

```bash
arkhe .   # Arkhe maps itself
```

---

## Configuration reference

Full configuration options are documented in `.env.example` (API keys, providers, model selection) and `options.env` (feature toggles).
