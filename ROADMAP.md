# Arkhe — Product Roadmap

> Point it at any repo — GitHub or GitLab — get a living AI-generated map of the entire codebase, automatically kept current on every PR.

## Business Model

**CLI (`pip install arkhe`) — BYOK, unlimited.**
Users bring their own API keys. Groq and Gemini are free tiers, so most CLI users pay $0. We never pay their inference costs.

**Website — our keys, rate-limited by tier.**
Users paste a repo URL and get results instantly. No install, no API keys. Free tier is capped; paid tiers remove limits. The model fallback router handles rate limits automatically on the backend.

**The CLI is the acquisition channel. The website is the conversion funnel.**
Both run the same pipeline — the web server is a thin job wrapper that calls `main.run()`. Never fork the logic.

---

## Stage 0 — Foundation ✅
- [x] `pyproject.toml` + UV venv
- [x] `.gitignore`, git branch strategy (`main` → `dev` → `feature/name/task`)
- [x] Bug fixes: async fixes, LLM client caching, iterative AST walk, D3 template extraction, dead code removal

---

## Stage 1 — Robust Core ✅
- [x] SQLite cache — keyed by content hash; only changed files hit the LLM on reruns
- [x] Native async clients — Groq, Gemini, Anthropic, OpenAI
- [x] Parallel batching — `asyncio.Semaphore` + `asyncio.gather`
- [x] Dependency graph — proper import resolution (relative, `__init__.py`, dotted module paths)
- [x] Language support — Python, JavaScript, TypeScript, Go, Rust, Java, Ruby
- [x] `--format json` structured output
- [x] Model fallback router — priority chains + 10-min cooldown, persisted across restarts
- [x] Security audit agent — OWASP Top 10 LLM scan
- [x] Dead code detection — static analysis, zero LLM cost
- [x] Test gap analysis — coverage gaps + pytest scaffold generation
- [x] PR impact analysis — git diff → reverse dep walk → LLM summary
- [x] Feature toggle system — `options.env` controls which agents run

---

## Stage 2 — CLI Product ✅
*A developer installs it in 30 seconds and uses it daily.*

```bash
pip install arkhe
arkhe ./my-project
arkhe ./my-project --refactor
arkhe ./my-project --format json
arkhe diff ./my-project
arkhe watch ./my-project
```

**Tasks:**
- [x] `[project.scripts]` entry point + `py-modules` — `arkhe` command works after pip install
- [x] Windows path normalization — forward-slash everywhere
- [x] Template packaged via `importlib.resources`
- [x] OpenAI added as fourth provider
- [x] BYOK fallback chain — `ARKHE_CHAIN=openai:gpt-4o:sk-xxx,gemini:gemini-2.5-pro:AIza_yyy`
- [x] `README.md` — install, setup, BYOK chain, optional features
- [x] GitHub Actions CI — `.github/workflows/ci.yml` — tests on every push to `dev`
- [x] GitLab CI — `.gitlab-ci.yml` — same tests, runs on GitLab pipelines (needed for hackathon)
- [x] `arkhe diff` — compare current state vs snapshot, surface added/removed files and deps
- [x] `arkhe watch` — live-reload map as files change (via `watchdog`)

### Cost
| Item | Cost |
|------|------|
| PyPI publishing | Free |
| GitHub Actions CI | Free (public repo) |
| `arkhe.dev` domain | ~$1/mo |

---

## Stage 3 — Website + Platform Integrations
*The website converts. The platform integrations retain.*

**Website:** User pastes a GitHub or GitLab URL → Arkhe clones, runs pipeline, serves results.
Free tier capped; paid tiers unlock larger repos and more outputs.

**GitHub App:** Install on any repo → every PR gets an automatic architectural diff comment.
Publish `arkhe-action` to GitHub Marketplace for 3-line YAML integration.

**GitLab Integration:** Same behaviour for merge requests. GitLab CI template users can drop into any `.gitlab-ci.yml` in 3 lines. Also enables GitLab Hackathon submission.

```
User pastes GitHub or GitLab URL
        ↓
FastAPI (Google Cloud Run) → detect platform → Cloud Tasks job queue
        ↓
Worker: git clone → main.run() → upload docs/ to GCS → cleanup
        ↓
User gets shareable results link

GitHub webhook  ┐
GitLab webhook  ┘→ same worker pool → post PR/MR comment
```

**Hosting: Google Cloud Run** — chosen for hackathon eligibility (qualifies for "Most Impactful on GitLab & Google" $10,000 category prize on top of the Anthropic prize already covered by the existing Anthropic provider integration).

**Model strategy:**
| Tier | Models | Cost to us |
|------|--------|------------|
| Free (everyone) | Gemini 2.5 Pro / 2.5 Flash across all roles | ~$0 free tier |
| Pro (paying users) | Anthropic Sonnet/Opus for synthesis + executive report | We pay, covered by subscription |

Backend shell for Anthropic is already built — just needs a payment gate in front of it. Nothing in the pipeline changes when a user upgrades.

**Tasks:**

*Core infrastructure (platform-agnostic):*
- [x] `scripts/clone_repo.py` — clone from GitHub or GitLab URL to temp dir, clean up after
- [x] FastAPI server — accept URL, detect platform, enqueue job, return results link
- [ ] Google Cloud Tasks job queue (replaces Redis/ARQ)
- [ ] Per-request API key injection — server keys passed at runtime, not from `.env`
- [ ] Rate limiting + abuse protection — per-IP and per-user limits by tier
- [ ] Google Cloud Storage (GCS) output storage — upload `docs/`, serve via URL
- [ ] Landing page — hero, demo, install command, works for both platforms
  - Clear free vs Pro tier comparison on the landing page
  - Free web tier: runs on Gemini (best free model) — great for trying Arkhe instantly
  - Pro tier (future): Anthropic Sonnet/Opus for synthesis + executive report — locked behind payment, visible in UI as an upgrade prompt
  - CLI callout: "Install locally, bring your own Anthropic key, run on any repo, unlimited" — power users who want full Anthropic on everything use the CLI, no tier restrictions
  - Web UI shows Anthropic-powered toggle/badge that is visibly locked for free users — demonstrates the business model to judges without us spending anything
- [ ] Analytics — Plausible or Umami
- [ ] `Dockerfile` — containerize FastAPI app for Cloud Run deployment
- [x] Warm-up endpoint (`/_health`) — keep Cloud Run instance warm to avoid cold starts during demos
- [ ] Token optimization — filter non-code files (certs, docs, configs, CI) before LLM; AST handles deps for all files at zero cost; hierarchical synthesis; persistent cache keyed by repo URL + commit SHA
- [ ] Feature toggle UI — checkboxes on landing page for optional agents (security audit, dead code, test gap, executive report, complexity heatmap); passed per-job at runtime instead of reading from options.env
- [ ] GCS-backed cache for Cloud Run — before each run download `{url_hash}/arkhe.db` from GCS into temp repo; after run (success or failure) upload back; replaces local `server/cache/` which is wiped on container restart; same SQLite file, just stored in GCS instead of disk

*GitHub:*
- [ ] GitHub App — webhook receiver, PR comment poster
- [ ] `arkhe-action` — GitHub Marketplace listing
- [ ] Parse `X-GitHub-Event` webhook payload format

*GitLab:*
- [ ] GitLab webhook receiver — parse `X-Gitlab-Event` MR payload (different format to GitHub)
- [ ] GitLab CI template — `arkhe` job snippet users drop into `.gitlab-ci.yml`
- [ ] Post MR comments via GitLab Notes API

### Cost
| Item | Cost |
|------|------|
| Google Cloud Run | Free tier: 2M requests/mo, ~$0 for demo traffic |
| Google Cloud Storage | Free tier: 5GB |
| Google Cloud Tasks | Free tier: 1M tasks/mo |
| GitHub App, Marketplace | Free |
| GitLab webhooks, CI templates | Free |
| Sentry error tracking | Free tier |

---

## Stage 4 — Web Dashboard
*Persistent, team-facing UI. This is where Arkhe becomes a SaaS product.*

- Sign in with GitHub **or GitLab** OAuth
- All your repos from either platform with live Arkhe maps
- History timeline — see how architecture evolved
- Shareable links to specific files or modules
- Team annotations on the map
- Auto-update on every PR (GitHub) or MR (GitLab)

### Stack
| Layer | Technology |
|-------|-----------|
| Frontend | React + existing D3 visualization |
| Backend | FastAPI (Google Cloud Run) |
| Database | Firebase Firestore — user records, repo history, analyses |
| Auth | Firebase Auth — GitHub OAuth + GitLab OAuth (built-in, no Authlib needed) |
| Job queue | Google Cloud Tasks (already used in Stage 3) |
| File storage | Google Cloud Storage — generated `docs/` outputs |

All Google ecosystem — pairs naturally with Cloud Run, stays free at early scale, and strengthens the Google category prize case for the hackathon.

### Dual-platform auth design (decide in Stage 3, build in Stage 4)
One user account, multiple connected platform identities. Designed this way from day one to avoid identity collisions and billing splits when a user has both GitHub and GitLab accounts.

```
Firestore collections:

users/{uid}
  email, created_at, tier (free|pro)

connected_accounts/{uid}/platforms/{github|gitlab}
  platform_user_id, username, access_token

repos/{repo_id}
  user_id, platform (github|gitlab), platform_repo_id, full_name

analyses/{analysis_id}
  repo_id, run_at, status, outputs_gcs_path
```

- First login creates the user document via Firebase Auth
- Subsequent logins from either platform link to the same account via `connected_accounts`
- Every repo is keyed by `(platform, platform_repo_id)` — no namespace collisions
- Webhooks are routed by `(platform, repo_id)` — no ambiguity
- Billing (Pro tier) is per user, not per connected account

**This schema must be established in Stage 3** before any auth code is written. Migrating away from a simple one-OAuth-one-account model after real users exist is painful.

### Cost
| Users | Monthly |
|-------|---------|
| Early stage (<100) | ~$0 (Firebase + Cloud Run free tiers) |
| Growth (1,000+) | ~$20–40/mo |

At 1,000 users on $15/mo Pro: **$15,000 MRR vs ~$40 infra.**

---

## Stage 5 — Go-to-Market Launch
*The full product is live — CLI, website, dashboard, GitHub App, GitLab integration. One launch, one narrative, maximum impact.*

### Pre-launch
- [ ] Demo GIF — `arkhe .` in terminal + dependency map pan. 15–30s. Into `assets/demo.gif` + README.
- [ ] Clean install test — Windows VM + Mac: `pip install arkhe`, fresh `.env`, real repo
- [ ] `git tag v0.1.0` + GitHub Release with changelog
- [ ] `uv build` — install the `.whl` locally and run it end-to-end
- [ ] Website + dashboard tested — 3 different repos, all outputs verified
- [ ] `arkhe.dev` domain live, pointing to landing page
- [ ] All launch content written in advance

### Launch Day
- [ ] `uv publish` to PyPI
- [ ] GitHub repo made public + mirrored to GitLab
- [ ] ProductHunt — submit at 12:01am PST for full-day visibility
- [ ] Hacker News — *"Show HN: Arkhe – AI-generated architecture docs for any repo"*
- [ ] Reddit — r/Python, r/programming, r/devtools
- [ ] Twitter/X — demo GIF in first tweet, thread on the problem + solution
- [ ] LinkedIn
- [ ] Dev.to / Hashnode — technical article on how it was built
- [ ] GitLab community forums + GitLab Hackathon submission (if open)

### Post-launch (first 72 hours)
- [ ] Respond to every GitHub issue, HN comment, Reddit reply within hours
- [ ] Same-day hotfixes — `hotfix/` branch on standby
- [ ] Screenshot positive feedback for website testimonials
- [ ] Track: PyPI downloads, GitHub stars, ProductHunt votes, website visitors

### Week-1 Targets
| Metric | Target |
|--------|--------|
| PyPI downloads | 500+ |
| GitHub stars | 200+ |
| ProductHunt upvotes | 100+ |
| Website visitors | 1,000+ |

---

## Stage 6 — Monetization
*Already in market. Now convert.*

| Tier | Price | CLI | Website |
|------|-------|-----|---------|
| **Free** | $0 | Unlimited, BYOK | Rate-limited |
| **Pro** | $15/mo | Unlimited, BYOK | Larger repos, all outputs, faster queue |
| **Team** | $49/mo | Unlimited, BYOK | Org dashboard, Slack alerts, 10 seats |
| **Enterprise** | Custom | Self-hosted option | SSO/SAML, SOC2, SLA |

Revenue priorities: Pro tier first → GitHub Marketplace discovery → GitLab CI template adoption → Enterprise waitlist.

---

## Competitive Landscape

| Tool | Gap Arkhe fills |
|------|----------------|
| CodeSee (shut down) | Left a vacuum — their users need something |
| Sourcegraph | Too expensive and complex for most teams |
| GitHub Copilot | Code generation focused, not architecture/docs |
| Mermaid / Swimlane | Static diagrams — Arkhe is auto-generated and always current |
| GitLab native docs | Manual, no AI narrative, no dependency graph |

**Key differentiator:** Arkhe generates *narrative* documentation — prose that explains *why* the architecture is shaped the way it is, not just a graph of what exists.

---

## Cost Summary

| Stage | Status | Monthly Cost |
|-------|--------|-------------|
| 0 — Foundation | ✅ Complete | $0 |
| 1 — Robust Core | ✅ Complete | $0 |
| 2 — CLI Product | ✅ Complete | $0–1 |
| 3 — Website + Platform Integrations | Upcoming | $7–23 |
| 4 — Web Dashboard | Upcoming | $8–88 |
| 5 — Launch | Upcoming | $0 |
| 6 — Monetization | Future | Self-funded |

First unavoidable cost: always-on hosting at Stage 3 (~$7/mo). Everything before that is $0.
