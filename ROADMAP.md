# Arkhe — Product Roadmap

> Point it at any repo — GitHub or GitLab — get a living AI-generated map of the entire codebase, automatically kept current on every PR.

## Business Model

**CLI (`pip install arkhe`) — BYOK, unlimited.**
Users bring their own API keys. Groq and Gemini are free tiers, so most CLI users pay $0. We never pay their inference costs.

**Website — our keys, rate-limited by tier.**
Users paste a repo URL and get results instantly. No install, no API keys. Free tier is capped; paid tiers remove limits. The model fallback router handles rate limits automatically on the backend.

---

## Python App / CLI / Web

### Stage 0 — Foundation ✅
- [x] `pyproject.toml` + UV venv
- [x] `.gitignore`, git branch strategy (`main` → `dev` → `feature/name/task`)
- [x] Bug fixes: async fixes, LLM client caching, iterative AST walk, D3 template extraction, dead code removal

---

### Stage 1 — Robust Core ✅
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

### Stage 2 — CLI Product ✅
*A developer installs it in 30 seconds and uses it daily.*

```bash
pip install arkhe
arkhe ./my-project
arkhe ./my-project --refactor
arkhe ./my-project --format json
arkhe diff ./my-project
arkhe watch ./my-project
```

- [x] `[project.scripts]` entry point + `py-modules` — `arkhe` command works after pip install
- [x] Windows path normalization — forward-slash everywhere
- [x] Template packaged via `importlib.resources`
- [x] OpenAI added as fourth provider
- [x] BYOK fallback chain — `ARKHE_CHAIN=openai:gpt-4o:sk-xxx,gemini:gemini-2.5-pro:AIza_yyy`
- [x] `README.md` — install, setup, BYOK chain, optional features
- [x] GitHub Actions CI — `.github/workflows/ci.yml` — tests on every push to `dev`
- [x] `arkhe diff` — compare current state vs snapshot, surface added/removed files and deps
- [x] `arkhe watch` — live-reload map as files change (via `watchdog`)

### Cost
| Item | Cost |
|------|------|
| PyPI publishing | Free |
| GitHub Actions CI | Free (public repo) |
| `arkhe.dev` domain | ~$1/mo |

---

### Stage 3 — Website + Platform Integrations
*The website converts. The platform integrations retain.*

**Website:** User pastes a GitHub or GitLab URL → Arkhe clones, runs pipeline, serves results.
Free tier capped; paid tiers unlock larger repos and more outputs.

**Hosting: Google Cloud Run** — qualifies for "Most Impactful on GitLab & Google" $10,000 hackathon category prize on top of the Anthropic prize.

**Model strategy:**
| Tier | Models | Cost to us |
|------|--------|------------|
| Free (everyone) | Gemini 2.5 Pro / 2.5 Flash across all roles | ~$0 free tier |
| Pro (paying users) | Anthropic Sonnet/Opus for synthesis + executive report | We pay, covered by subscription |

*Core infrastructure:*
- [x] `scripts/clone_repo.py` — clone from GitHub or GitLab URL to temp dir, clean up after
- [x] FastAPI server — accept URL, detect platform, enqueue job, return results link
- [x] Warm-up endpoint (`/_health`) — keep Cloud Run instance warm
- [ ] Token optimization — filter non-code files before LLM; hierarchical synthesis; persistent GCS cache keyed by repo URL + commit SHA
- [ ] Google Cloud Tasks job queue
- [ ] Per-request API key injection — server keys passed at runtime, not from `.env`
- [ ] Rate limiting + abuse protection — per-IP and per-user limits by tier
- [ ] Google Cloud Storage (GCS) output storage — upload `docs/`, serve via URL
- [ ] `Dockerfile` — containerize FastAPI app for Cloud Run deployment
- [ ] Landing page — hero, demo, install command, free vs Pro tier comparison
- [ ] Feature toggle UI — checkboxes for optional agents passed per-job at runtime
- [ ] Analytics — Plausible or Umami

*GitHub:*
- [ ] GitHub App — webhook receiver, PR comment poster
- [ ] `arkhe-action` — GitHub Marketplace listing
- [ ] Parse `X-GitHub-Event` webhook payload format

*GitLab (shared with Track 1 post-hackathon):*
- [ ] GitLab OAuth — user connects once, auto-register webhooks on selected repos
- [ ] GitLab webhook receiver — parse `X-Gitlab-Event` MR payload
- [ ] Post MR comments + commit `docs/` via GitLab Notes API
- [ ] Web server toggle — Quick (Duo flow) vs Full (Cloud Run pipeline) per repo

### Cost
| Item | Cost |
|------|------|
| Google Cloud Run | Free tier: 2M requests/mo |
| Google Cloud Storage | Free tier: 5GB |
| Google Cloud Tasks | Free tier: 1M tasks/mo |
| GitHub App, Marketplace | Free |
| GitLab webhooks | Free |

---

### Stage 4 — Web Dashboard
*Persistent, team-facing UI. This is where Arkhe becomes a SaaS product.*

- Sign in with GitHub **or GitLab** OAuth
- All your repos from either platform with live Arkhe maps
- History timeline — see how architecture evolved
- Shareable links to specific files or modules
- Team annotations on the map
- Auto-update on every PR (GitHub) or MR (GitLab)
- Toggle per repo: Quick (GitLab Duo) vs Full (Cloud Run pipeline)

### Stack
| Layer | Technology |
|-------|-----------|
| Frontend | React + existing D3 visualization |
| Backend | FastAPI (Google Cloud Run) |
| Database | Firebase Firestore — user records, repo history, analyses |
| Auth | Firebase Auth — GitHub OAuth + GitLab OAuth |
| Job queue | Google Cloud Tasks |
| File storage | Google Cloud Storage |

### Cost
| Users | Monthly |
|-------|---------|
| Early stage (<100) | ~$0 (Firebase + Cloud Run free tiers) |
| Growth (1,000+) | ~$20–40/mo |

At 1,000 users on $15/mo Pro: **$15,000 MRR vs ~$40 infra.**

---

### Stage 5 — Go-to-Market Launch

**Pre-launch:**
- [ ] Demo GIF — `arkhe .` in terminal + dependency map pan
- [ ] Clean install test — Windows VM + Mac: `pip install arkhe`, fresh `.env`, real repo
- [ ] `git tag v0.1.0` + GitHub Release with changelog
- [ ] Website + dashboard tested on 3 different repos
- [ ] `arkhe.dev` domain live

**Launch Day:**
- [ ] `uv publish` to PyPI
- [ ] GitHub repo made public + mirrored to GitLab
- [ ] ProductHunt — submit at 12:01am PST
- [ ] Hacker News — *"Show HN: Arkhe – AI-generated architecture docs for any repo"*
- [ ] Reddit — r/Python, r/programming, r/devtools
- [ ] Twitter/X, LinkedIn, Dev.to

**Week-1 Targets:**
| Metric | Target |
|--------|--------|
| PyPI downloads | 500+ |
| GitHub stars | 200+ |
| ProductHunt upvotes | 100+ |
| Website visitors | 1,000+ |

---

### Stage 6 — Monetization

| Tier | Price | CLI | Website |
|------|-------|-----|---------|
| **Free** | $0 | Unlimited, BYOK | Rate-limited |
| **Pro** | $15/mo | Unlimited, BYOK | Larger repos, all outputs, faster queue |
| **Team** | $49/mo | Unlimited, BYOK | Org dashboard, Slack alerts, 10 seats |
| **Enterprise** | Custom | Self-hosted option | SSO/SAML, SOC2, SLA |

---

## Competitive Landscape

| Tool | Gap Arkhe fills |
|------|----------------|
| CodeSee (shut down) | Left a vacuum — their users need something |
| Sourcegraph | Too expensive and complex for most teams |
| GitHub Copilot | Code generation focused, not architecture/docs |
| GitLab Duo Chat prompts | Manual — user has to paste prompts themselves. Arkhe is automatic, triggered on every MR |
| Mermaid / Swimlane | Static diagrams — Arkhe is auto-generated and always current |
| GitLab native docs | Manual, no AI narrative, no dependency graph |

**Key differentiator:** Arkhe generates *narrative* documentation — prose that explains *why* the architecture is shaped the way it is, not just a graph of what exists. And it runs automatically — zero prompting required.

---

## Cost Summary

| Stage | Status | Monthly Cost |
|-------|--------|-------------|
| Stage 0 — Foundation | ✅ Complete | $0 |
| Stage 1 — Robust Core | ✅ Complete | $0 |
| Stage 2 — CLI Product | ✅ Complete | $0–1 |
| Stage 3 — Website + Platform Integrations | ✅ Live on AWS (http://18.208.132.250:8000) | $7–23 |
| Stage 4 — Web Dashboard | Upcoming | $8–88 |
| Stage 5 — Launch | Upcoming | $0 |
| Stage 6 — Monetization | Future | Self-funded |

First unavoidable cost: always-on hosting at Stage 3 (~$7/mo). Everything before that is $0.
