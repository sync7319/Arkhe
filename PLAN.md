# Arkhe — Product Plan

> Working doc for Shreeyut + Om. Review together before starting any new work.
> Last updated: 2026-03-25
>
> **Active stack: Supabase + Fly.io/VPS (non-AWS)**
> AWS_PLAN.md exists as a future reference if the stack changes. Do not act on it now.

---

## What Arkhe is

Point it at any repository → AI-generated documentation, dependency graph, security
report, dead code report, test gap report, and PR impact analysis. Always current,
never manual.

**Delivery methods:**

| Method | Who | Keys | Compute | Status |
|--------|-----|------|---------|--------|
| CLI (BYOK) | Developers | Their own | Their machine | Built |
| Website | Anyone | Ours | Our server | Built, not deployed |
| GitLab Duo integration | GitLab teams | GitLab's AI Gateway | GitLab's CI compute | Built |
| MCP server (Claude plugin) | Claude Desktop / Code users | BYOK or ours | Local or our server | v2 |

---

## Part 1 — Cleanup (do first, before any new work)

### Files to delete
- `hackathon/` — entire folder. GitLab submission YAMLs + hackathon-only context docs. No product value.
- `march_24_plan.txt` — planning artifact, all 15 recommendations already implemented.
- `mirror` job in `.github/workflows/ci.yml` — was mirroring to GitLab hackathon submission repo. Remove that job block, keep the `test` job.

### Files to clean up
- `CLAUDE.md` — strip all hackathon sections: prize strategy, deadlines, registration notes,
  hackathon next steps. Keep: architecture, pipeline table, key files, LLM system,
  dev environment, git workflow, progress log entries that describe real product work.
- `ROADMAP.md` — remove hackathon roadmap and prize table. Keep the 6-stage product roadmap.

### Files to keep as-is
- `duo/` — GitLab Duo integration, a real third delivery method. Not a hackathon artifact.
- Everything else is product code.

---

## Part 2 — Delivery model

### CLI — strictly BYOK

The CLI is a developer tool. Developers have their own API keys. They want local
control, zero account friction, and no dependency on our infrastructure.

- User's own keys in `.env`
- Runs entirely locally
- SQLite cache per repo (already built — avoids re-running LLM on unchanged files)
- Outputs written to `repo/docs/`
- **Visualization:** after a run, spin up a local HTTP server on a random free port
  and auto-open `http://localhost:<port>/docs/DEPENDENCY_MAP.html` in the browser.
  Print the URL to terminal. Keep alive until Ctrl+C.
- Markdown reports: print file paths as today, user opens in editor.
- No account needed. Free forever. $0 to us.

> **Note on BYOK + account:** A user can have an Arkhe account AND run CLI in full
> BYOK mode — same as how Claude Code lets you bring your own API key even if you
> have a Claude account. The account is just for the website experience. The CLI
> never requires login.

### Website — strictly our keys

The website is for people who want to paste a URL and get a result.
They don't have API keys. They don't want to set anything up.

- Free tier: Gemini + Groq only (both have free API tiers — $0 to us)
- Paid tier: Anthropic + OpenAI, unlimited analyses, longer result retention
- Supabase Auth for accounts (see Part 3)
- Results cached in Supabase Storage — same repo + commit SHA = instant return, zero LLM cost
- Results at `arkhe.ai/results/<job_id>`, shareable link

### Why strict separation

Mixing CLI + our keys (giving developers an Arkhe API key to use in their terminal)
is a real feature — specifically for CI/CD automation. But it requires building a
terminal auth flow, API key management, a server endpoint that accepts CLI requests,
and separate code paths throughout. That is a lot of work before a single paying user
exists. Build it in v2 when someone actually asks for it.

---

## Part 3 — Supabase architecture

### What Supabase gives us
- **Auth** — email/password, GitHub OAuth, Google OAuth. Handles JWT, sessions, refresh.
- **Postgres DB** — users, jobs, cached result references.
- **Storage** — S3-compatible buckets for result files.
- **Row-level security** — users only see their own results, enforced at DB level.

### Storage size — important caveat

Each Arkhe analysis produces ~5-10MB of result files. Supabase storage limits:

| Plan | Storage | Cost |
|------|---------|------|
| Free | 1GB | $0 |
| Pro | 100GB | $25/month |

At ~5-10MB per analysis, the free tier holds roughly 100-200 analyses before hitting
the cap. **The Pro plan ($25/month) will likely be the first paid upgrade needed**
once real users start using the site. Budget for it early.

### The caching layer (most important)

Before running any pipeline on a submitted URL, check Supabase for an existing result
at the same commit SHA. If it exists, return the stored results immediately. Zero LLM
calls, zero compute cost.

```
Cache key: sha256(repo_url + latest_commit_sha)

POST /analyze flow:
  1. Clone repo (shallow, depth=1)
  2. Get latest commit SHA
  3. Build cache key
  4. Check Supabase: SELECT * FROM analyses WHERE cache_key = ?
     HIT  → return existing result URLs instantly
     MISS → run full pipeline → upload results → insert row → return job_id
```

The second person to analyze `facebook/react` at the same commit costs us nothing.

### Supabase schema (minimal v1)

```sql
-- managed by Supabase Auth
users (id, email, created_at, tier)

-- one row per unique repo+commit analysis
analyses (
  id            uuid primary key,
  user_id       uuid references users,
  repo_url      text,
  commit_sha    text,
  cache_key     text unique,       -- sha256(repo_url + commit_sha)
  status        text,              -- pending | running | complete | error
  result_paths  jsonb,             -- { "CODEBASE_MAP.md": "storage_url", ... }
  created_at    timestamptz,
  expires_at    timestamptz        -- free tier: 7 days, paid: 90 days
)

-- v2 only, when CI/CD CLI feature is built
api_keys (id, user_id, key_hash, created_at, last_used_at)
```

### Supabase Storage structure

```
bucket: arkhe-results (public read, auth write)
  <cache_key>/
    CODEBASE_MAP.md
    DEPENDENCY_MAP.html
    SECURITY_REPORT.md
    DEAD_CODE_REPORT.md
    TEST_GAP_REPORT.md
    PR_IMPACT.md
    GRAPH.json
    CONTEXT_INDEX.json
```

Files are served directly from Supabase Storage URLs — no proxying through our server.

---

## Part 4 — Hosting (keeping the website live)

This is where the FastAPI server runs to keep `arkhe.ai` always accessible.
The Docker image is already built — this is just where it runs.

**One fix required regardless of hosting choice:**
Swap `jobs: dict = {}` (in-memory, lost on restart) for the Supabase `analyses`
table. Once results go to Supabase Storage, the server is stateless — any option works.

**RAM requirement:** at least 512MB, ideally 1GB. Arkhe runs tree-sitter parsing,
LLM calls, and concurrent file I/O.

**Recommendation:** Start on Fly.io (free, always-on). Move to a VPS (Hetzner/DO)
when you have paying users who need reliability guarantees.

---

### Option A — Fly.io (recommended to start)

Free tier includes 3 shared VMs and persistent volumes. Runs Docker. Always on —
no spin-down on idle. Simple CLI deploy.

- Cost: $0 free tier; ~$5-10/month if you need more RAM
- Persistent volumes: yes
- Always on: yes
- Deploy: `flyctl launch` + `flyctl deploy`
- RAM on free tier: 256MB shared — monitor, upgrade if needed

---

### Option B — Railway

Free tier gives $5 credit/month. Runs Docker. Auto-deploys from GitHub on push.

- Cost: $0 free tier (~$20/month if exceeded)
- Persistent volumes: yes
- Always on: yes (within credit limits)
- Deploy: connect GitHub repo, auto-deploys on push to main

---

### Option C — Koyeb

Free tier, 2 nano instances, always on, Docker support. No spin-down, no credit system.

- Cost: $0
- Persistent volumes: limited — check current plan details
- Always on: yes
- RAM: 512MB on free nano instance

---

### Option D — Render

Free tier spins down after 15 minutes of inactivity (~30s cold start to wake up).
Bad user experience — first visitor after idle waits 30 seconds before analysis starts.

- Cost: $0 free / $7/month for always-on
- **Not recommended on free tier** due to spin-down

---

### Option E — VPS (Hetzner / DigitalOcean)

Always on, full control, persistent disk, no platform restrictions. Best for
reliability once you have paying users.

- Cost: Hetzner CX22 ~€4/month, DigitalOcean Basic ~$6/month
- RAM: 4GB on Hetzner CX22 — no memory concerns
- Deploy: SSH + `git pull` + `docker-compose up -d`
- SSL: Nginx + Let's Encrypt (free)

---

### Option F — Own Ubuntu server (talking point)

If either of you already runs a personal Ubuntu server, deploy there for free.

- Cost: $0 (already paying for it)
- Deploy: SSH + `git pull` + `docker-compose up -d`
- SSL: Nginx + Let's Encrypt
- Caveat: home server reliability depends on internet/power. Fine for dev/staging,
  risky for a public product.

---

## Part 5 — GitLab Duo integration (duo/)

Keep `duo/` as-is. This is a real third delivery method.

**What it does:** A GitLab-native AI agent triggered by mentioning it in any MR
comment. Reads the repo using GitLab's own tools, runs a 5-phase analysis
(architecture, dependencies, PR impact, OWASP security, test coverage, code quality),
and posts a complete report as an MR comment. No Python, no our server, no API keys
required from the user.

**Key facts:**
- GitLab repos only — uses GitLab's built-in tools
- No file outputs — posts a markdown comment to the MR thread only
- No Python pipeline — prompt-driven, runs on GitLab's AI Gateway compute
- On-demand only — someone must explicitly mention it; does not auto-run
- Completely independent from our Python app — complementary, not redundant
- Requires GitLab Premium or Ultimate tier

---

## Part 6 — MCP server (Claude plugin) [v2]

A fourth delivery method. Claude Desktop and Claude Code both support MCP
(Model Context Protocol). An Arkhe MCP server exposes the analysis pipeline
as tools Claude can call during any conversation.

**What it enables:**
Developer asks Claude "what breaks if I change `analyst_agent.py`?" — Claude
calls Arkhe tools, gets pre-computed blast radius, answers accurately without
hallucinating from raw file reads.

**Two flavours:**

**Local MCP (BYOK):**
Runs Arkhe pipeline locally. No account needed. Natural fit for CLI users.
```
Claude Desktop / Claude Code
  └── Arkhe MCP server (local Python process)
        └── runs full pipeline on the repo
```

**Remote MCP (Arkhe account):**
Calls the hosted Arkhe API. User needs an Arkhe account.
Natural upsell from the web product.
```
Claude Desktop / Claude Code
  └── Arkhe MCP server
        └── calls arkhe.ai API → returns cached results
```

**Tools exposed:**
```
analyze_repo(repo_url_or_path)     → run pipeline, return job_id
get_codebase_map(job_id)           → CODEBASE_MAP.md content
get_dependency_graph(job_id)       → GRAPH.json
query_codebase(job_id, question)   → semantic search via embed_agent
get_security_report(job_id)        → SECURITY_REPORT.md content
get_blast_radius(job_id, file)     → transitive impact for a file
get_dead_code(job_id)              → dead code report
get_test_gaps(job_id)              → test gap report
```

**Product loop:**
1. Run `arkhe analyze` on a repo (or use the website)
2. Install the Arkhe MCP server in Claude Desktop or Claude Code
3. Every Claude question about that codebase uses Arkhe's pre-computed data
4. Accurate, grounded answers — no hallucination from raw file reads

**Build this in v2** — after website is live and has users.

---

## Part 7 — Multi-person development workflow

How Shreeyut and Om work together without stepping on each other.

### Supabase — shared project, no coordination needed

One Supabase project. Both of you log in via the Supabase dashboard. You can both
see all users, all analyses, all stored files. The only thing to coordinate is
**schema changes** — tell each other before running a migration.

Both `.env` files point at the same Supabase URL + anon key.

### Local development — independent

```
Shreeyut's machine              Om's machine
  .env (own LLM keys)             .env (own LLM keys)
  local FastAPI server            local FastAPI server
  local SQLite cache              local SQLite cache
  ↓                               ↓
  shared Supabase project ←───────┘
```

Each person develops locally with their own LLM API keys. You both point at the
same Supabase project so auth and DB are consistent. No shared local state.

### Deployment — automated, nobody SSHes manually

GitHub Actions deploys to the server on every push to `main`. Neither person
needs to SSH in to deploy.

```
push to main branch
  → GitHub Actions: run tests
  → tests pass → SSH into server → git pull → docker-compose up -d
  → site is updated
```

```yaml
# .github/workflows/deploy.yml (to be written)
- name: Deploy
  uses: appleboy/ssh-action@v1
  with:
    host: ${{ secrets.SERVER_HOST }}
    username: ${{ secrets.SERVER_USER }}
    key: ${{ secrets.SERVER_SSH_KEY }}
    script: |
      cd /app/arkhe
      git pull origin main
      docker-compose up -d --build
```

### Secrets — GitHub repo settings, not Slack

All secrets live in GitHub repo settings → both of you manage them via GitHub UI.
Never share `.env` files directly.

```
GitHub repo secrets:
  SERVER_HOST         → IP or hostname of the production server
  SERVER_USER         → SSH username
  SERVER_SSH_KEY      → private SSH key for deploy
  SUPABASE_URL        → Supabase project URL
  SUPABASE_ANON_KEY   → Supabase anon key
  SUPABASE_SERVICE_KEY→ Supabase service role key (server-side only)
  GEMINI_API_KEY      → our Gemini key (website free tier)
  GROQ_API_KEY        → our Groq key (website free tier)
  ANTHROPIC_API_KEY   → our Anthropic key (paid tier)
```

### Git workflow — unchanged from CONTRIBUTING.md

```
main  ← auto-deploys to production on merge
  └── dev  ← integration branch
        ├── feature/shreeyut/thing
        └── feature/om/thing
```

PRs: `feature → dev`. When dev is stable: `dev → main` → triggers deploy.

---

## Part 8 — Frontend / backend architecture

> **DECIDED: Next.js on Vercel + FastAPI as pure JSON API.**

### Architecture

```
Vercel (free)                    Hosting (Part 4 choice)
Next.js                          FastAPI (Python)
  ├── app/page.tsx                 ├── POST /analyze
  ├── app/results/[id]/page.tsx    ├── GET  /status/{id}
  ├── app/dashboard/page.tsx       ├── GET  /results/{id}/files/...
  ├── Supabase Auth (SSR)    →     └── GET  /_health
  └── fetches from FastAPI API
```

- Supabase Auth SSR helpers work natively with Next.js
- Vercel auto-deploys on push to `main` — free tier
- FastAPI becomes a clean pure JSON API (strip all Jinja2 templates)
- Two deployments: Vercel (frontend) + Fly.io/VPS (backend)
- npm + TypeScript + build step required

### What this means for the existing server

- `server/templates/` — all 9 Jinja2 templates get replaced by Next.js pages
- `server/static/` — CSS/assets move to Next.js `public/` or Tailwind
- `server/app.py` — keep all API routes, remove template rendering routes

---

## Part 9 — Priority order

### Immediate (cleanup + get live)
1. Delete `hackathon/`, `march_24_plan.txt`, remove CI mirror job from `ci.yml`
2. Clean `CLAUDE.md` and `ROADMAP.md` (strip hackathon content)
3. Fix persistent job state — swap `jobs: dict` for Supabase `analyses` table
4. Pick hosting option (Part 4), get server running
5. Write `deploy.yml` — GitHub Actions auto-deploy on push to main
6. Add all secrets to GitHub repo settings
7. Get a live URL

### Short term (core website features)
8. Supabase Auth — sign up, log in, sessions
9. Supabase Storage — upload results after pipeline, serve from storage URLs
10. Result caching — `cache_key` check before every pipeline run
11. User dashboard — list of past analyses per account

### Medium term (polish)
12. CLI local server — auto-open `DEPENDENCY_MAP.html` in browser after run
13. Real progress bar — emit `phase` + `pct` at each pipeline stage, consume
    in frontend instead of fake timer
14. Pricing page + Stripe (free vs paid tier enforcement)
15. README update — three delivery methods, live URL

### Later (v2)
16. MCP server — local and remote flavors (see Part 6)
17. CLI + Arkhe keys — terminal auth flow, CI/CD use case
18. Structured LLM output (Pydantic schemas per provider)
19. Migrate to VPS when traffic justifies reliability upgrade

---

## What we are not doing

- No more hackathon work
- No Devpost submission
- No GitLab hackathon group repo maintenance
- No GitHub → GitLab mirror in CI
- No AWS (see AWS_PLAN.md for future reference)
- No Cloud Run
