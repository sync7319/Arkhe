# Arkhe — AWS Architecture Plan

> AWS equivalent of PLAN.md. Every Supabase/third-party service replaced with an
> AWS native service. Structured for cost-efficient startup deployment.
> Last updated: 2026-03-25

---

## Service mapping at a glance

| PLAN.md (Supabase stack) | AWS equivalent |
|--------------------------|----------------|
| Supabase Auth | Amazon Cognito |
| Supabase Postgres DB | RDS PostgreSQL (or self-hosted on EC2) |
| Supabase Storage | S3 |
| Vercel (frontend) | AWS Amplify |
| Fly.io / VPS (compute) | EC2 / Lightsail |
| CDN | CloudFront |
| SSL certificates | AWS Certificate Manager (ACM) |
| DNS | Route 53 |

---

## Part 1 — Cleanup

Identical to PLAN.md. No AWS-specific changes.

- Delete `hackathon/`, `march_24_plan.txt`, remove CI mirror job
- Clean `CLAUDE.md` and `ROADMAP.md`
- Keep `duo/` as GitLab Duo delivery method

---

## Part 2 — Delivery model

Identical to PLAN.md. No changes to the model itself.

- CLI: strictly BYOK, fully local, no AWS involved
- Website: our keys, hosted on AWS
- GitLab Duo: runs on GitLab's compute, no AWS involved

---

## Part 3 — AWS data architecture

This replaces the Supabase architecture from PLAN.md Part 3.

### Auth — Amazon Cognito

Handles user sign-up, sign-in, JWT tokens, sessions, and OAuth (GitHub, Google).

- **Free tier:** 50,000 MAUs (monthly active users) forever — not just 12 months
- **After 50k MAU:** $0.0055 per MAU
- **What it gives you:** user pool, JWT access/ID tokens, hosted UI or custom UI,
  GitHub/Google social login via identity providers
- **FastAPI integration:** validate Cognito JWTs using `python-jose` — verify against
  Cognito's JWKS endpoint, no library lock-in
- **Frontend integration:** AWS Amplify JS SDK (`aws-amplify`) handles login flow,
  token storage, and refresh automatically

> **Cognito vs Supabase Auth:** Cognito is more complex to set up but has a much
> more generous free tier (50k MAU forever vs Supabase's 50k MAU on free plan).
> The DX is worse — expect more boilerplate. Worth it at scale.

### Database — RDS PostgreSQL

Stores users, job records, and the result cache index.

**Schema (same as PLAN.md, just on RDS instead of Supabase Postgres):**

```sql
-- user profiles (Cognito manages auth; this table stores app-level data)
users (
  id            uuid primary key,   -- matches Cognito sub claim
  email         text unique,
  tier          text default 'free', -- free | paid
  created_at    timestamptz
)

-- one row per unique repo+commit analysis
analyses (
  id            uuid primary key,
  user_id       uuid references users,
  repo_url      text,
  commit_sha    text,
  cache_key     text unique,        -- sha256(repo_url + commit_sha)
  status        text,               -- pending | running | complete | error
  result_paths  jsonb,              -- { "CODEBASE_MAP.md": "s3_url", ... }
  created_at    timestamptz,
  expires_at    timestamptz         -- free: 7 days, paid: 90 days
)

-- v2 only
api_keys (id, user_id, key_hash, created_at, last_used_at)
```

**Two options for running Postgres on AWS:**

**Option A — RDS PostgreSQL (managed)**
- Free tier: `db.t3.micro`, 20GB storage, 12 months free
- After free tier: ~$15/month for `db.t3.micro`
- Automatic backups, patches, failover
- Separate from compute — survives server restarts

**Option B — Self-hosted Postgres on EC2/Lightsail (cheaper)**
- Run Postgres inside a Docker container on the same EC2/Lightsail instance
- `docker-compose.yml` already supports this — just add a `postgres` service
- $0 extra per month — included in the compute cost
- No automatic backups (you manage this via cron + S3 dumps)
- Fine for early stage. Migrate to RDS when you need managed reliability.

> **Recommendation for startup:** Option B first (self-hosted on same instance),
> migrate to RDS Option A when you have paying users who need SLA guarantees.

### Storage — S3

Stores all result files for every analysis. Replaces Supabase Storage.

```
bucket: arkhe-results-prod
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

- **Free tier:** 5GB storage, 20,000 GET requests, 2,000 PUT requests — 12 months
- **After free tier:** $0.023/GB/month storage + $0.0004/1000 GET requests
  At startup scale (say 500 analyses/month, ~5MB each): ~$0.06/month — essentially free
- **Access:** pre-signed S3 URLs for result downloads. Public read for shared links.
  FastAPI generates the pre-signed URL and returns it — no proxying through the server.
- **Python:** `boto3` — already the standard AWS SDK, one `pip install`

### The caching flow (identical logic, different services)

```
Cache key: sha256(repo_url + latest_commit_sha)

POST /analyze flow:
  1. Clone repo (shallow, depth=1)
  2. Get latest commit SHA
  3. Build cache key
  4. Check RDS: SELECT * FROM analyses WHERE cache_key = ?
     HIT  → return existing S3 URLs instantly, zero LLM cost
     MISS → run full pipeline → upload to S3 → insert row in RDS → return job_id
```

---

## Part 4 — Hosting (compute options)

The FastAPI server runs in Docker. Same `docker-compose.yml` and `Dockerfile` as
today — just a different place for the container to run.

**One fix required regardless of choice:**
Swap `jobs: dict = {}` for the RDS `analyses` table. Server becomes stateless.

**RAM requirement:** at least 512MB, ideally 1-2GB for tree-sitter + LLM calls.

---

### Option A — AWS Lightsail (recommended starting point)

AWS's answer to Hetzner/DigitalOcean. Predictable flat monthly pricing.
Runs Docker. Always on. Simple SSH deploy.

| Plan | RAM | vCPU | Storage | Transfer | Cost |
|------|-----|------|---------|----------|------|
| $7/mo | 1GB | 2 | 40GB SSD | 2TB | $7/month |
| $10/mo | 2GB | 2 | 60GB SSD | 3TB | $10/month |

- Always on: yes
- Persistent disk: yes
- Deploy: SSH + `git pull` + `docker-compose up -d`
- SSL: Lightsail load balancer ($18/month) OR Nginx + Let's Encrypt (free)
- **Use the $10/month plan** — 2GB RAM is comfortable for Arkhe

---

### Option B — EC2 t3.small (free tier then cheap)

t2.micro is free for 12 months (1GB RAM — borderline for Arkhe).
t3.small is the next step up (2GB RAM, ~$15/month on-demand).

- Free tier: `t2.micro`, 750 hours/month, 12 months — worth using to start
- After free tier: `t3.small` ~$15/month on-demand, or ~$7/month Reserved (1-year commit)
- Persistent disk: EBS volume (~$0.10/GB/month, 8GB = $0.80/month)
- SSL: ACM certificate (free) + Application Load Balancer ($16/month) OR Nginx + Let's Encrypt
- Deploy: SSH + `git pull` + `docker-compose up -d`
- **More control than Lightsail, more complexity**

> **Note on Load Balancer:** ALB costs ~$16/month minimum. For a startup, skip it —
> run Nginx on the EC2 instance directly for SSL termination (Let's Encrypt, free).
> Add ALB when you need auto-scaling or multiple instances.

---

### Option C — ECS Fargate (serverless containers)

Run Docker containers without managing servers. Pay per task (per vCPU + memory hour).

- Cost: ~$0.04048/vCPU/hour + ~$0.004445/GB/hour
  1 vCPU, 2GB RAM running 24/7 = ~$32/month — more expensive than EC2
- Persistent volumes: EFS (Elastic File System) — adds cost and complexity
- Always on: yes (if you keep 1 task always running)
- Auto-scales: yes — spin up more tasks under load
- **Not cost-efficient for startup. Better when you need scale.**

---

### Option D — AWS App Runner

Fully managed. Push a Docker image → it runs. Auto-scales to zero when idle.
Similar to Google Cloud Run but AWS.

- Cost: $0.064/vCPU/hour + $0.007/GB/hour (active) + $0.007/GB/hour (idle provisioned)
  Keeping 1 instance warm: ~$5/month idle + usage on top
- Persistent volumes: no — S3 only (same problem as Cloud Run)
- Auto-scales: yes
- Same issue as Cloud Run: analyses run for minutes as background tasks, stateless
  model requires S3 for all file I/O
- **Not recommended until you need auto-scaling**

---

### Option E — Own Ubuntu server (talking point)

If either of you already has a personal Ubuntu server (cloud VPS or home machine),
deploy there — it's essentially free since you're already paying for it.

- Cost: $0 extra
- Deploy: SSH + `git pull` + `docker-compose up -d`
- SSL: Nginx + Let's Encrypt (free)
- RAM: depends on the machine
- Caveat: home server reliability depends on your internet and power.
  Fine for dev/staging, risky for a public product.

---

### Cost comparison

| Option | Monthly cost | RAM | Always on | Persistent disk |
|--------|-------------|-----|-----------|-----------------|
| Lightsail $10 | $10 | 2GB | Yes | Yes |
| EC2 t2.micro (free tier) | $0 (12 months) | 1GB | Yes | Yes |
| EC2 t3.small (after free tier) | ~$15 | 2GB | Yes | Yes |
| EC2 t3.small Reserved 1yr | ~$7 | 2GB | Yes | Yes |
| ECS Fargate (1 vCPU, 2GB) | ~$32 | 2GB | Yes | EFS extra |
| App Runner | ~$5+ usage | variable | Yes | No |
| Own server | $0 | depends | depends | Yes |

> **Recommendation:** Start on EC2 t2.micro free tier (12 months, $0). Self-host
> Postgres on the same instance. Use S3 for result files. After free tier expires,
> move to Lightsail $10/month or EC2 t3.small Reserved for predictable billing.

---

## Part 5 — Frontend / backend architecture

Same decision as PLAN.md Part 6, but with AWS-native frontend hosting options.

> **DECISION NEEDED — review with partner before proceeding.**

### Current state

FastAPI monolith serving Jinja2 templates + vanilla JS. No npm, no build step.

---

### Option A — Stay monolith (Jinja2 + FastAPI on EC2/Lightsail)

No frontend/backend split. FastAPI serves everything. Cognito Auth added via
Amplify JS SDK loaded from CDN in each template.

```
EC2 / Lightsail
  Nginx (SSL termination)
    └── FastAPI (uvicorn)
          ├── API routes
          └── Jinja2 templates
                └── aws-amplify loaded from CDN
                      Cognito JWT stored in localStorage
                      Authorization header on API calls
```

- Cost: just the EC2/Lightsail compute (see Part 4)
- No extra AWS services for frontend
- Works today with minimal changes

**Pros:** simple, one deployment, no build step
**Cons:** same as PLAN.md — grows painful as UI gets complex

---

### Option B — Split: Next.js on Amplify + FastAPI on EC2

Frontend lives in a Next.js app, deployed to AWS Amplify. FastAPI is a pure JSON API.

```
AWS Amplify (frontend)           EC2 / Lightsail (backend)
  Next.js                          FastAPI
    ├── app/page.tsx                 ├── POST /analyze
    ├── app/results/[id]/page.tsx    ├── GET  /status/{id}
    ├── app/dashboard/page.tsx       ├── GET  /results/{id}/files/...
    ├── Cognito Auth            →    └── GET  /_health
    │   (Amplify Auth SDK)
    └── fetches from FastAPI API
```

**AWS Amplify free tier:**
- 5GB storage
- 15GB bandwidth/month
- 1,000 build minutes/month
- Auto-deploys from GitHub on push to main
- Supports Next.js natively (SSR + SSG)
- Custom domain + SSL included

**Pros:**
- Amplify + Cognito is the native AWS pairing — best DX for auth in this stack
- Global CDN via CloudFront (built into Amplify)
- Auto-deploy on GitHub push
- FastAPI is clean pure API

**Cons:**
- Rewrite 9 HTML templates in React/TypeScript
- Two deployments (Amplify + EC2)
- npm, TypeScript, build step

---

**Questions to decide (same as PLAN.md):**
1. How complex will the UI get?
2. Does anyone know React / Next.js?
3. One deployment or two?

---

## Part 6 — Full AWS cost breakdown

### Year 1 (maximising free tiers)

| Service | Usage | Cost |
|---------|-------|------|
| EC2 t2.micro | free tier (750 hrs/month, 12 months) | $0 |
| EBS 20GB | free tier (12 months) | $0 |
| RDS t3.micro PostgreSQL | free tier (750 hrs/month, 20GB, 12 months) | $0 |
| S3 | free tier (5GB, 20k GET, 2k PUT, 12 months) | $0 |
| Cognito | free (50k MAU — permanent, not time-limited) | $0 |
| CloudFront | free tier (1TB/month, 12 months) | $0 |
| Amplify | free tier (5GB, 15GB bandwidth, 12 months) | $0 |
| ACM SSL certificate | always free | $0 |
| Route 53 hosted zone | $0.50/month | $6/year |
| Domain (.ai via Route 53) | ~$70/year or cheaper via Namecheap | ~$15/year |
| **Total Year 1** | | **~$21/year** |

> The free tiers on EC2, RDS, S3, and CloudFront all expire after 12 months.
> Cognito's 50k MAU free tier does NOT expire — it's permanent.

### After Year 1 (startup scale, low traffic)

| Service | Usage assumption | Cost |
|---------|-----------------|------|
| EC2 t3.small Reserved (1yr) | 1 instance always on | ~$7/month |
| EBS 20GB | 1 volume | ~$2/month |
| Postgres (self-hosted on EC2) | same instance, no extra cost | $0 |
| S3 | 500 analyses/month × 5MB = 2.5GB + requests | ~$0.10/month |
| Cognito | under 50k MAU | $0 |
| CloudFront | low traffic | ~$0-1/month |
| Amplify | low traffic | $0 (free tier) |
| Route 53 | 1 hosted zone | $0.50/month |
| **Total after Year 1** | | **~$10-11/month** |

> If you switch from self-hosted Postgres to RDS after Year 1:
> add ~$15/month for `db.t3.micro` → total ~$25/month.
> RDS gives you automated backups and multi-AZ failover.
> Self-hosted is fine until you have paying users who need reliability guarantees.

---

## Part 7 — Priority order

Same sequence as PLAN.md, AWS service names substituted.

### Immediate (cleanup + get live)
1. Delete `hackathon/`, `march_24_plan.txt`, remove CI mirror job
2. Clean `CLAUDE.md` and `ROADMAP.md`
3. Fix persistent job state — swap `jobs: dict` for Postgres `analyses` table
4. Spin up EC2 t2.micro (free tier), docker-compose up, Nginx + Let's Encrypt, live URL

### Short term (core features)
5. Cognito user pool — sign up, log in, JWT validation in FastAPI
6. S3 bucket — upload results after pipeline, generate pre-signed URLs
7. Cache check — `cache_key` lookup in Postgres before every pipeline run
8. User dashboard — list past analyses per account

### Medium term (polish)
9. CLI local server — auto-open `DEPENDENCY_MAP.html` after run
10. Real progress bar — emit `phase` + `pct` in pipeline, consume in frontend
11. Stripe + tier enforcement (free vs paid)
12. README update

### Later (v2)
13. CLI + Arkhe keys — Cognito machine-to-machine client credentials flow
14. Structured LLM output (Pydantic schemas)
15. Migrate Postgres to RDS when reliability matters
16. Add ALB + auto-scaling when traffic justifies it

---

## What we are not doing

- No more hackathon work
- No ECS/Fargate until traffic justifies the cost
- No App Runner until the stateless model is worth the refactor
- No ALB until you need multiple instances
- No RDS until self-hosted Postgres becomes a reliability risk
