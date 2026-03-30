# Backend Abstraction Layer — Integration Guide

This guide shows how to use the new database and storage abstraction layer to support both Supabase and AWS.

## Quick Start

### Environment Variables

Choose your backend via `.env`:

```bash
# For Supabase development
DB_BACKEND=supabase
STORAGE_BACKEND=supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_STORAGE_BUCKET=arkhe-results

# For AWS production
DB_BACKEND=aws
STORAGE_BACKEND=aws
AWS_RDS_HOST=your-instance.c9akciq32.us-east-1.rds.amazonaws.com
AWS_RDS_PORT=5432
AWS_RDS_USER=postgres
AWS_RDS_PASSWORD=your-password
AWS_RDS_DATABASE=arkhe
AWS_REGION=us-east-1
AWS_S3_BUCKET=arkhe-results-prod
# AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY optional (uses IAM role on EC2)
```

## Using in FastAPI

### Startup

In `server/app.py`, initialize backends at startup:

```python
from fastapi import FastAPI
from integrations import init_backends, get_db, get_storage

app = FastAPI()

@app.on_event("startup")
async def startup():
    db, storage = await init_backends()
    app.state.db = db
    app.state.storage = storage
    logger.info(f"[startup] DB backend: {os.getenv('DB_BACKEND', 'supabase')}")
    logger.info(f"[startup] Storage backend: {os.getenv('STORAGE_BACKEND', 'supabase')}")
```

### Using in Routes

In any route handler, access the backends:

```python
from integrations import get_db, get_storage

@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    db = get_db()
    storage = get_storage()

    # Create analysis record (same code, different backend)
    analysis = await db.create_analysis(
        user_id=user_id,
        repo_url=repo_url,
        commit_sha=commit_sha,
        cache_key=cache_key,
    )

    # After pipeline runs, upload results
    map_url = await storage.upload_text(cache_key, "CODEBASE_MAP.md", map_content)
    results = await db.update_analysis_results(
        analysis.id,
        {"CODEBASE_MAP.md": map_url},
        status="complete"
    )

    return results
```

### Caching (Before Running Pipeline)

```python
@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    db = get_db()

    # Check cache before running expensive pipeline
    cache_key = sha256(repo_url + commit_sha).hex()
    cached = await db.get_analysis_by_cache_key(cache_key)

    if cached and cached.status == "complete":
        logger.info(f"[analyze] Cache hit for {repo_url}@{commit_sha}")
        return cached  # Return immediately, zero cost

    # Cache miss — run full pipeline
    analysis = await db.create_analysis(...)
    # ... run pipeline ...
```

## Schema

Both backends use the same schema:

```sql
-- Users table
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  tier TEXT DEFAULT 'free',  -- free | paid
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Analyses table (one row per codebase analysis)
CREATE TABLE analyses (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  repo_url TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  cache_key TEXT UNIQUE NOT NULL,
  status TEXT DEFAULT 'pending',  -- pending | running | complete | error
  result_paths JSONB DEFAULT '{}'::jsonb,  -- {"CODEBASE_MAP.md": "url", ...}
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP  -- for free tier: 7 days, paid: 90 days
);

-- Indexes for common queries
CREATE INDEX idx_analyses_user_id ON analyses(user_id);
CREATE INDEX idx_analyses_cache_key ON analyses(cache_key);
CREATE INDEX idx_analyses_status ON analyses(status);
```

## Supabase Setup (Development)

1. Create a Supabase project: https://supabase.com
2. Get the `URL` and `anon key` from Settings → API
3. Create tables using the Supabase dashboard SQL editor (paste the schema above)
4. Create a storage bucket named `arkhe-results` in Storage → Buckets
5. Add to `.env`:
   ```
   SUPABASE_URL=https://xxx.supabase.co
   SUPABASE_ANON_KEY=eyJ...
   SUPABASE_STORAGE_BUCKET=arkhe-results
   ```

## AWS Setup (Production)

### RDS PostgreSQL

1. Create an RDS instance (t3.micro free tier for 12 months)
2. Get the endpoint: `xxx.c9akciq32.us-east-1.rds.amazonaws.com`
3. Create a database named `arkhe`
4. Connect with `psql` and run the schema above
5. Add to `.env`:
   ```
   AWS_RDS_HOST=xxx.c9akciq32.us-east-1.rds.amazonaws.com
   AWS_RDS_USER=postgres
   AWS_RDS_PASSWORD=your-password
   AWS_RDS_DATABASE=arkhe
   ```

### S3

1. Create an S3 bucket: `arkhe-results-prod`
2. Make it publicly readable (or use presigned URLs)
3. Get IAM credentials or use an EC2 IAM role
4. Add to `.env`:
   ```
   AWS_S3_BUCKET=arkhe-results-prod
   AWS_REGION=us-east-1
   AWS_ACCESS_KEY_ID=your-key
   AWS_SECRET_ACCESS_KEY=your-secret
   ```

## Switching Backends

To switch from Supabase to AWS (or vice versa), just change one line in `.env`:

```bash
# Development (Supabase)
DB_BACKEND=supabase
STORAGE_BACKEND=supabase

# Production (AWS)
DB_BACKEND=aws
STORAGE_BACKEND=aws
```

No code changes needed. The entire backend swaps automatically.

## Testing Both

```bash
# Test with Supabase
export DB_BACKEND=supabase
export STORAGE_BACKEND=supabase
uv run uvicorn server.app:app --reload

# Test with AWS
export DB_BACKEND=aws
export STORAGE_BACKEND=aws
uv run uvicorn server.app:app --reload
```

## Migration Path

1. **Now:** Build everything against Supabase (fast, local development)
2. **Later:** Deploy to AWS (production, cost-effective at scale)
3. **Anytime:** Switch back for debugging

The abstraction means you're never locked into one backend.

## Troubleshooting

### "Database client not initialized"
→ Make sure `await init_backends()` is called in your FastAPI startup event.

### Supabase connection fails
→ Check `SUPABASE_URL` and `SUPABASE_ANON_KEY` are correct.
→ Verify tables exist in Supabase dashboard.

### AWS RDS connection fails
→ Check security group allows inbound on port 5432.
→ Check `AWS_RDS_HOST`, `AWS_RDS_USER`, `AWS_RDS_PASSWORD` are correct.
→ Verify database `arkhe` exists: `psql -h host -U postgres -d arkhe`

### S3 upload fails
→ Verify bucket exists and is accessible.
→ Check IAM permissions or use `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`.
→ Verify `AWS_REGION` matches bucket region.
