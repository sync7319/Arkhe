# Arkhe — Sprint Plan & Go-to-Market Strategy

> Last updated: 2026-03-30
> Authors: Omar (scrum lead), Shreeyut (engineering)

---

## Where We Are Today

**Product:** Working end-to-end. Submit a GitHub URL, get AI-generated codebase documentation (narrative map, dependency graph, security report, dead code detection) in ~8 minutes.

**Infrastructure:**
- EC2 t3.micro running FastAPI + uvicorn (systemd, survives reboots)
- RDS PostgreSQL for job records
- S3 for output storage
- NVIDIA NIM (Nemotron-253B) as primary LLM
- Result caching with pre-clone API check (instant on repeat submissions)
- Gate page with developer/user mode

**What's missing before anyone outside the team can use it:**
1. No HTTPS (browsers show "Not Secure")
2. No domain (just an IP address)
3. No real user accounts
4. No landing page that explains the product
5. Output quality needs one more polish pass

---

## Sprint Cycles

### Sprint 1 — "Make It Shippable" (April 1-7, 2026)
*Goal: A stranger can visit the URL and understand + use Arkhe.*

| Task | Owner | Est | Priority |
|------|-------|-----|----------|
| HTTPS via Caddy reverse proxy on EC2 | Omar | 2 hr | P0 |
| Buy domain (arkhe.dev or tryarkhe.com) + DNS to EC2 | Omar | 1 hr | P0 |
| Rewrite landing page — hero, demo GIF, 3 value props, CTA | Both | 4 hr | P0 |
| Record 30-sec demo GIF (submit URL → results) | Omar | 1 hr | P0 |
| Output quality pass — run on 5 popular repos, fix bad outputs | Shreeyut | 4 hr | P1 |
| Add "Powered by Arkhe" watermark to all output files | Either | 30 min | P1 |

**Definition of done:** Someone can visit `https://arkhe.dev`, submit a repo, and get clean results.

---

### Sprint 2 — "Make It Sticky" (April 8-14, 2026)
*Goal: Users come back. Jobs are reliable.*

| Task | Owner | Est | Priority |
|------|-------|-----|----------|
| GitHub webhook integration — auto-run on PR | Shreeyut | 6 hr | P0 |
| Email notification when analysis completes | Omar | 2 hr | P1 |
| Job queue with retry (current: one-shot background task) | Shreeyut | 4 hr | P1 |
| Error recovery — auto-retry on LLM timeout | Shreeyut | 2 hr | P1 |
| Analytics (Plausible or PostHog) — track submits, completions | Omar | 2 hr | P1 |
| Basic user accounts (GitHub OAuth login) | Omar | 4 hr | P2 |

**Definition of done:** A user connects their GitHub repo and gets updated docs on every PR automatically.

---

### Sprint 3 — "Make It Sellable" (April 15-21, 2026)
*Goal: Free and paid tiers work. Revenue is possible.*

| Task | Owner | Est | Priority |
|------|-------|-----|----------|
| Stripe integration — Pro tier ($15/mo) | Omar | 4 hr | P0 |
| Tier enforcement — free: 3 repos, 5 analyses/day; paid: unlimited | Both | 3 hr | P0 |
| Dashboard — user's repos, analysis history, status | Shreeyut | 6 hr | P0 |
| Team features — invite collaborators, shared repos | Shreeyut | 4 hr | P2 |
| CLI `arkhe login` — tie CLI usage to web account | Either | 3 hr | P2 |

**Definition of done:** A user can upgrade to Pro and get more features.

---

### Sprint 4 — "Make It Known" (April 22-30, 2026)
*Goal: First 100 users who are not us.*

| Task | Owner | Est | Priority |
|------|-------|-----|----------|
| ProductHunt launch — listing, screenshots, demo video | Omar | 4 hr | P0 |
| Hacker News "Show HN" post | Omar | 1 hr | P0 |
| Reddit posts — r/Python, r/programming, r/devtools, r/SaaS | Omar | 2 hr | P0 |
| Twitter/X thread — show before/after of onboarding | Omar | 1 hr | P1 |
| Dev.to article — "How I built an AI codebase mapper" | Omar | 3 hr | P1 |
| Reach out to 20 dev tool newsletters | Omar | 2 hr | P1 |
| Run Arkhe on 10 popular open source repos, share results | Both | 2 hr | P1 |

**Definition of done:** 100+ signups, 50+ analyses completed by real users.

---

## When to Apply to YC

**Do NOT apply yet.** YC wants to see traction, not just a working product.

**Apply when you have:**
- [ ] 50+ weekly active users (not signups — active users running analyses)
- [ ] Revenue (even $100/mo proves willingness to pay)
- [ ] Retention signal (users coming back week over week)
- [ ] A clear growth story ("we grew X% week over week for 4 weeks")

**Realistic timeline:** Apply to YC F2026 (Fall 2026) batch.
- Application deadline: ~July 2026
- Interviews: August 2026
- Batch starts: September 2026

**What to build between now and then:**
- Sprint 1-4 above (April)
- May: iterate based on user feedback, improve output quality, add languages
- June: growth experiments (GitHub Marketplace listing, VS Code extension)
- July: YC application with 4 months of traction data

**YC application strength:**
- Two technical co-founders who built the whole thing
- Working product, live on AWS, real users
- BYOK model = near-zero marginal cost per user
- Clear market gap (CodeSee shut down, no good alternative)
- $0 infrastructure until scale (AWS free tier)

---

## What to Focus On vs. What to Skip

### Focus (high impact, directly grows users)
- **Output quality** — this IS the product. If the codebase map is mediocre, nothing else matters
- **GitHub Action / CI integration** — YC data is clear: workflow-embedded dev tools win, standalone dashboards die (CodeSee's lesson). A GitHub Action that runs on every PR and posts a comment with updated docs is the #1 retention mechanism
- **Landing page** — first impression. If someone can't understand Arkhe in 10 seconds, they leave
- **Speed** — if analysis takes 8 minutes, people close the tab. Target: < 3 min for repos under 50 files
- **Sell onboarding, not docs** — "new hire productive in 1 week instead of 4" is the value prop that gets budget approved. Individual devs don't pay for doc tools; engineering leads do

### Skip for now (low impact or premature)
- ~~GitLab integration~~ — GitHub has 10x the market. Do GitLab after GitHub works perfectly
- ~~VS Code extension~~ — nice-to-have, not a growth driver yet
- ~~Team features~~ — no teams are using it yet. Build when someone asks
- ~~Enterprise (SSO, SOC2)~~ — way too early. This is a post-YC conversation
- ~~Mobile/PWA~~ — developers don't analyze codebases on their phone
- ~~Multi-region deployment~~ — one EC2 in us-east-1 is fine until you have 1000+ users

### Lessons from failed competitors
- **CodeSee (shut down 2024):** sold to engineering managers, not developers. Visualization-only — pretty graphs don't retain users without workflow integration
- **Swimm ($25M+ raised):** auto-generated docs coupled to code — closest direct competitor. Survived because they embedded in the workflow
- **Sourcegraph:** code search works but $49/user/mo prices out SMBs. Pivoted to AI assistant (Cody) as core search business plateaued

---

## Key Metrics to Track

| Metric | Why it matters | Target by May 31 |
|--------|---------------|-------------------|
| Weekly active users | Core health metric | 50 |
| Analyses completed/week | Usage depth | 200 |
| Repeat usage rate | Retention / stickiness | 30% (week over week) |
| Time to first result | UX quality | < 5 min |
| GitHub repos connected | Sticky integration | 20 |
| MRR (monthly recurring revenue) | Business viability | $100 |
| Landing page → signup conversion | Marketing effectiveness | 10% |

---

## Competitive Landscape (March 2026)

| Competitor | Status | Arkhe's Advantage |
|-----------|--------|-------------------|
| **Greptile** (YC S2023) | AI codebase understanding API. Closest funded competitor. Query-based, no persistent artifacts. | Arkhe produces docs/reports/maps, not just answers. Broader analysis (security, dead code, test gaps). BYOK = different cost model. |
| **CodeSee** | Shut down (2024) | Market vacuum. Their users need a replacement. |
| **Sourcegraph / Cody** | Enterprise-only ($49+/user), pivoted to AI assistant | Arkhe is free tier + $15 Pro. Accessible to SMBs. |
| **Swimm** | $25M+ raised, auto-docs coupled to code | Closest direct competitor. Arkhe is fully automatic + includes security/dead code/dependency analysis. |
| **GitHub Copilot** | Code generation, not architecture | Different product. But **biggest risk**: Copilot adding "explain this codebase" that's "good enough" for most devs. |
| **Mintlify** | AI docs, focused on public API docs | Arkhe is internal codebase intelligence, not public docs. |

**Positioning:** "The architecture docs that write themselves."

**YC pitch angle:** "CodeSee shut down. Sourcegraph is $49/user. Greptile answers questions but doesn't produce artifacts. We auto-generate what all three tried to sell, at zero marginal cost via BYOK, integrated into CI."

### Biggest risk
Copilot or Cursor adding a built-in "explain this codebase" feature that's good enough for most developers. Mitigation: Arkhe's output is richer (security, dead code, dependency graphs, blast radius) and runs in CI (not just in-editor).

### Biggest opportunity
Enterprise onboarding and compliance. SOC2 audits require documentation — Arkhe could auto-generate it. "New hire productive in 1 week instead of 4" is the value prop that gets budget approved.

---

## Budget (Next 90 Days)

| Item | Monthly | Notes |
|------|---------|-------|
| EC2 t3.micro | $0 | Free tier (12 months from Dec 2025) |
| RDS t4g.micro | $0 | Free tier (12 months) |
| S3 (5GB) | $0 | Free tier |
| Domain (arkhe.dev) | $1-2 | Annual registration |
| Caddy (HTTPS) | $0 | Free, runs on EC2 |
| Plausible analytics | $0 | Self-hosted on EC2, or $9/mo cloud |
| NVIDIA NIM API | $0 | Free tier for dev mode |
| **Total** | **~$2/mo** | Until free tier expires (Dec 2026) |

When free tier expires (Dec 2026): ~$30-50/mo total. By then you should have revenue covering it.

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-30 | Skip phases 4-6 of old roadmap, deploy to AWS first | Only 2 users, no need for auth/caching before deployment |
| 2026-03-30 | NVIDIA NIM as primary LLM (dev mode) | Free, fast, high quality (Nemotron-253B) |
| 2026-03-30 | Skip GitLab integration for now | GitHub has 10x market share, focus there first |
| 2026-03-30 | Target YC F2026 (Fall) not S2026 (Summer) | Need 4 months of traction data first |
| 2026-03-30 | Open source the repo | Trust > secrecy for dev tools. Moat is execution. |

---

## TL;DR — The 30-Second Version

1. **April Week 1:** HTTPS + domain + landing page. Make it visitable.
2. **April Week 2:** GitHub webhook integration. Make it sticky.
3. **April Week 3:** Stripe + tiers. Make it sellable.
4. **April Week 4:** Launch on ProductHunt, HN, Reddit. Get first 100 users.
5. **May-June:** Iterate on feedback, improve quality, grow.
6. **July:** Apply to YC with traction data.

The product works. The infra works. Now it's about getting it in front of people and making the output so good that teams can't stop using it.
