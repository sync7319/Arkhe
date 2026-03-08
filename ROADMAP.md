# Arkhe — Product Roadmap

> **Core premise:** Developers spend hours onboarding to unfamiliar codebases.
> Arkhe eliminates that. Point it at any repo, get a living, AI-generated map of
> the entire codebase — automatically kept current on every PR.
>
> **Business model:** Bring Your Own Key (BYOK). Users supply their own LLM API
> keys. Arkhe never touches their tokens or pays their inference costs. We provide
> the intelligence layer; they provide the keys.

---

## Stage 0 — Foundation (Now)
*Get the project to a professional standard before building on top of it.*

### Tasks
- [ ] Set up `pyproject.toml` + UV venv (replace `requirements.txt`)
- [ ] Add `.gitignore` (protect `.env`, `__pycache__`, `.venv`, `docs/` outputs)
- [ ] Establish Git branch strategy: `main` → `dev` → `feature/name/description`
- [ ] Fix critical bugs (see `docs/CODEBASE_MAP.md` issue log)
  - [ ] Rename `analyze_parallel` → `analyze_sequential` (it is not parallel)
  - [ ] Cache LLM clients instead of reinstantiating on every call
  - [ ] Fix `asyncio.get_event_loop()` → `asyncio.get_running_loop()`
  - [ ] Move `_retryable_exceptions()` call outside retry loop
  - [ ] Make `synthesize()` use async LLM call (currently blocks event loop)
- [ ] Move inline D3 HTML out of Python string → `templates/dependency_map.html`
- [ ] Remove dead code (`MAPPING_PROVIDER`, unused `MAX_TOKENS_PER_BATCH` import)

### Cost
| Item | Free | Paid |
|------|------|------|
| UV, Python, all libraries | ✅ Free | — |
| GitHub (private repo) | ✅ Free | — |
| LLM APIs for development | ✅ Groq + Gemini free tiers | — |

**Stage 0 total: $0**

---

## Stage 1 — Robust Core (Weeks 1–3)
*Make the pipeline production-grade before anyone depends on it.*

### Tasks
- [ ] **Resumable pipeline** — save scan/parse/analyze results to `.arkhe_cache/`
  so reruns after failures skip already-completed work
- [ ] **Real async** — replace `run_in_executor` thread-pool hack with native async
  clients (Groq, Gemini, Anthropic all have async SDKs)
- [ ] **Actual parallel batching** — use `asyncio.Semaphore` to run multiple
  batches concurrently up to the model's TPM limit
- [ ] **Fix dependency graph** — replace naive string matching with proper
  import resolution (handle relative imports, `__init__.py`, aliased imports)
- [ ] **Expand language support** — add Go, Rust, Java, Ruby via tree-sitter grammars
- [ ] **Replace recursive AST walk** with iterative stack to avoid recursion limit
- [ ] **Structured output** — add `--format json` flag so maps can be consumed
  programmatically by other tools

### Cost
| Item | Free | Paid | Paid benefit |
|------|------|------|--------------|
| All development | ✅ Free | — | — |
| Groq / Gemini API (testing) | ✅ Free tiers | — | — |
| Anthropic API (testing) | ❌ No free tier | ~$5–10/mo at low volume | Adds Claude support |

**Stage 1 total: $0–$10/mo**

---

## Stage 2 — CLI Product (Weeks 3–6)
*Something a developer installs in 30 seconds and uses daily.*

### What it looks like
```bash
pip install arkhe

arkhe map ./my-project            # generate docs/
arkhe map ./my-project --open     # generate + open HTML in browser
arkhe map ./my-project --format json   # machine-readable output
arkhe diff HEAD~1                 # re-map and highlight what changed
arkhe watch ./my-project          # live-update map as files change
```

### Tasks
- [ ] Add `[project.scripts]` entry point in `pyproject.toml` → `arkhe` CLI command
- [ ] Implement `arkhe diff` — compare two maps, surface architectural changes
- [ ] Implement `arkhe watch` — use `watchdog` library for file-change detection
- [ ] Write a proper `README.md` with GIF demo (critical for PyPI / GitHub traction)
- [ ] Publish to PyPI via `uv publish`
- [ ] Set up GitHub Actions CI — run tests on every push

### Cost
| Item | Free | Paid | Paid benefit |
|------|------|------|--------------|
| PyPI publishing | ✅ Free | — | — |
| GitHub Actions CI (public repo) | ✅ Free | — | — |
| GitHub Actions CI (private repo) | 2000 min/mo free | $4/mo for more minutes | More CI runs |
| `arkhe.dev` domain | ❌ | ~$12/year (~$1/mo) | Professional presence |

**Stage 2 total: $0–$13/mo**

---

## Stage 3 — GitHub App + Actions (Weeks 6–12)
*This is the pain-point killer. Arkhe runs automatically on every PR.*

### What it looks like
- Install the Arkhe GitHub App on your repo (one click)
- Every PR gets an automatic comment:
  ```
  🗺️ Arkhe Map Updated

  +2 new dependencies detected (auth → billing, user → cache)
  3 files changed architectural role

  [View full map] [View diff]
  ```
- Publish `arkhe-action` to the GitHub Marketplace so teams can add it to
  their own CI pipeline in 3 lines of YAML

### Tasks
- [ ] Build GitHub App (webhook receiver, PR comment poster)
- [ ] Build `arkhe diff` into the App — show what changed architecturally per PR
- [ ] Publish `arkhe-action` to GitHub Marketplace
- [ ] Build a minimal landing page (can be GitHub Pages — free)
- [ ] Set up basic analytics (Plausible or Umami — both self-hostable for free)

### Architecture
```
GitHub webhook → Arkhe server → clone repo → run pipeline → post PR comment
```
The server needs to be always-on (no sleeping). This is the first real hosting cost.

### Cost
| Item | Free | Paid | Paid benefit |
|------|------|------|--------------|
| GitHub App (creating) | ✅ Free | — | — |
| GitHub Marketplace listing | ✅ Free | — | — |
| GitHub Pages (landing page) | ✅ Free | — | — |
| **Hosting the webhook server** | Fly.io free tier (limited) | **$7–14/mo** (Fly.io hobby) | Always-on, no cold starts |
| Plausible analytics | Self-host free | $9/mo cloud | Easier managed option |
| Sentry (error tracking) | ✅ Free tier (5k errors/mo) | $26/mo | Higher volume |

> **Note on hosting:** Fly.io free tier spins down after inactivity — fine for
> development, bad for a GitHub webhook receiver (GitHub will time out).
> The $7/mo paid tier keeps it always on. This is the first unavoidable cost.

**Stage 3 total: $0 dev / $7–23/mo production**

---

## Stage 4 — Web Dashboard (Months 3–6)
*Persistent, team-facing UI. This is where Arkhe becomes a SaaS product.*

### What it looks like
- Sign in with GitHub (OAuth)
- See all your repos with live Arkhe maps
- Interactive dependency graph (the D3 visualization, properly hosted)
- History timeline — see how your architecture evolved over time
- Share links to specific modules or files
- Team annotations — leave notes on the map

### Stack
| Layer | Technology | Cost |
|-------|-----------|------|
| Frontend | React + your existing D3 viz | Free |
| Backend | FastAPI (Python — consistent with existing codebase) | Free |
| Database | PostgreSQL | Free tier → paid |
| Job queue | Redis + ARQ (async job queue) | Free tier → paid |
| Auth | GitHub OAuth (via Authlib) | Free |
| File storage | Cloudflare R2 (store map outputs) | Free up to 10GB |

### Hosting options
| Option | Free Tier | Paid | Notes |
|--------|-----------|------|-------|
| **Fly.io** (backend) | 3 shared VMs | $7–14/mo | Best free tier for FastAPI |
| **Supabase** (Postgres) | 500MB, 2 projects | $25/mo | Easiest managed Postgres |
| **Vercel** (frontend) | ✅ Generous free | $20/mo pro | Best for React |
| **Upstash** (Redis) | 10k commands/day free | $10/mo | Serverless Redis, easy |
| **Cloudflare R2** (storage) | 10GB free | $0.015/GB | Cheapest object storage |

### Realistic monthly cost at early stage (< 100 users)
```
Fly.io (backend, always-on):   $7/mo
Supabase (free tier):          $0/mo
Vercel (free tier):            $0/mo
Upstash (free tier):           $0/mo
Cloudflare R2 (free tier):     $0/mo
Domain:                        $1/mo (amortized)
─────────────────────────────────────
Total:                         ~$8/mo
```

### Realistic monthly cost at growth stage (1000+ users)
```
Fly.io (2x instances):        $28/mo
Supabase (pro):               $25/mo
Vercel (pro):                 $20/mo
Upstash (pay-as-you-go):      ~$10/mo
Cloudflare R2:                ~$5/mo
─────────────────────────────────────
Total:                        ~$88/mo
```
At 1000 users on a $15/mo Pro plan: **$15,000 MRR vs $88 infra = 99.4% margin.**

**Stage 4 total: $8/mo early / ~$88/mo at scale**

---

## Stage 5 — Monetization (Month 6+)

### Pricing tiers
| Tier | Price | Features |
|------|-------|---------|
| **Free** | $0 | CLI tool, public repos, BYOK, community support |
| **Pro** | $15/mo | Private repos, web dashboard, PR comments, map history |
| **Team** | $49/mo per team | Everything in Pro + org dashboard, Slack alerts, 10 seats |
| **Enterprise** | Custom | Self-hosted, SSO/SAML, SOC2, SLA, custom model support |

> The free CLI tier is permanent and intentional — it drives adoption and
> word-of-mouth. The GitHub App PR comments are the upgrade trigger.

### What to prioritize for early revenue
1. **Pro tier first** — lowest friction, individual developers pay themselves
2. **GitHub Marketplace** — discovery channel, no sales required
3. **Enterprise waitlist** — collect interest early, even before the product is ready

---

## Competitive Landscape

| Tool | Status | Gap Arkhe fills |
|------|--------|----------------|
| CodeSee | Acquired + shut down | Left a vacuum — their users need something |
| Sourcegraph | Expensive, complex | Arkhe is lightweight and LLM-native |
| GitHub Copilot workspace | Code gen focused | Arkhe is documentation + architecture focused |
| Swimlane / Mermaid | Static diagrams | Arkhe is auto-generated and always current |

**The key differentiator:** Arkhe generates *narrative* documentation — not just
a graph, but prose that explains *why* the architecture is shaped the way it is.
No other tool does this automatically.

---

## Total Cost Summary

| Stage | Timeline | Monthly Cost |
|-------|----------|-------------|
| Stage 0 — Foundation | Now | $0 |
| Stage 1 — Robust Core | Weeks 1–3 | $0–10 |
| Stage 2 — CLI + PyPI | Weeks 3–6 | $0–13 |
| Stage 3 — GitHub App | Weeks 6–12 | $7–23 |
| Stage 4 — Web Dashboard | Months 3–6 | $8–88 |
| Stage 5 — Monetization | Month 6+ | Self-funding from revenue |

**To get to a deployed, monetizable product: under $25/month total.**
The first unavoidable cost is always-on hosting at Stage 3 (~$7/mo).
Everything before that is genuinely free.
