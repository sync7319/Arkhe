# Backend Integration Implementation Plan

This is the step-by-step plan to integrate the new abstraction layer into FastAPI and switch from in-memory job state to persistent database storage.

## Current State

- `server/app.py` stores jobs in `jobs: dict = {}` (lost on restart)
- Results are stored in `server/results/` directory (not easily shareable)
- No user accounts or authentication
- No result caching by commit SHA

## Target State

- Job state lives in Supabase (dev) or AWS RDS (prod)
- Results uploaded to Supabase Storage (dev) or S3 (prod)
- User accounts with tier-based limits
- Result caching prevents duplicate expensive analyses

## Implementation Steps

### Phase 1: Initialize Backends (0.5 hours)

**File: `server/app.py`**

```python
from fastapi import FastAPI
from integrations import init_backends, get_db, get_storage
import os

app = FastAPI(...)

@app.on_event("startup")
async def startup_event():
    """Initialize database and storage backends on server start."""
    db, storage = await init_backends()
    app.state.db = db
    app.state.storage = storage

    logger.info(f"[startup] Database backend: {os.getenv('DB_BACKEND', 'supabase')}")
    logger.info(f"[startup] Storage backend: {os.getenv('STORAGE_BACKEND', 'supabase')}")
    logger.info(f"[startup] Ready to accept requests")
```

**Checklist:**
- [ ] Add imports
- [ ] Add `@app.on_event("startup")` handler
- [ ] Test with `DB_BACKEND=supabase` locally
- [ ] Verify logs show backend selected

---

### Phase 2: Create User Accounts (1 hour)

**File: `server/app.py`**

Add Supabase Auth (or Cognito for AWS) integration.

#### Option A: Supabase Auth (simpler for Supabase backend)

```python
from supabase import create_client, Client

supabase_client: Client = None

@app.on_event("startup")
async def startup_event():
    global supabase_client

    # Initialize auth client
    supabase_client = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_ANON_KEY")
    )

    # ... existing backend init ...

@app.post("/auth/signup")
async def signup(email: str, password: str):
    """Sign up a new user."""
    result = supabase_client.auth.sign_up({
        "email": email,
        "password": password,
    })
    user_id = result.user.id

    # Create user record in database
    db = get_db()
    await db.create_user(user_id, email, tier="free")

    return {"user_id": user_id, "email": email}

@app.post("/auth/login")
async def login(email: str, password: str):
    """Log in a user."""
    result = supabase_client.auth.sign_in_with_password({
        "email": email,
        "password": password,
    })
    return {"access_token": result.session.access_token}

def get_current_user(authorization: str = Header(...)) -> str:
    """Extract user_id from JWT token."""
    token = authorization.replace("Bearer ", "")
    # Verify token and extract user_id
    # For Supabase: use supabase_client.auth.get_user(token)
    user = supabase_client.auth.get_user(token)
    return user.user.id
```

#### Option B: Cognito (for AWS backend)

```python
# Use AWS Amplify JS SDK on frontend for login
# Validate JWT on backend using python-jose

from jose import jwt
from jose.exceptions import JWTError

COGNITO_KEYS = None  # Fetch from Cognito JWKS endpoint

def verify_cognito_token(token: str) -> str:
    """Verify Cognito JWT and extract user_id."""
    try:
        claims = jwt.get_unverified_claims(token)
        user_id = claims["sub"]
        # TODO: Verify signature against Cognito JWKS
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

**Checklist:**
- [ ] Add auth signup/login routes
- [ ] Add `get_current_user()` dependency
- [ ] Test signup/login flow
- [ ] Verify JWT tokens work

---

### Phase 3: Replace In-Memory Jobs Dict (2 hours)

**File: `server/app.py`**

**Before:**
```python
jobs: dict = {}

async def _run_pipeline(job_id: str, ...):
    jobs[job_id]["status"] = "running"
    # ... run pipeline ...
    jobs[job_id]["status"] = "complete"
    jobs[job_id]["outputs"] = {...}
```

**After:**
```python
async def _run_pipeline(job_id: str, ...):
    db = get_db()

    # Update status in database
    await db.update_analysis_status(job_id, "running")

    # ... run pipeline ...

    # Upload results to storage
    storage = get_storage()
    result_paths = {}

    if map_content:
        url = await storage.upload_text(cache_key, "CODEBASE_MAP.md", map_content)
        result_paths["CODEBASE_MAP.md"] = url

    if viz_content:
        url = await storage.upload_text(cache_key, "DEPENDENCY_MAP.html", viz_content)
        result_paths["DEPENDENCY_MAP.html"] = url

    # Store result URLs in database
    await db.update_analysis_results(job_id, result_paths, status="complete")

@app.post("/analyze")
async def analyze(request: AnalyzeRequest, user_id: str = Depends(get_current_user)):
    db = get_db()

    # Create analysis record
    analysis = await db.create_analysis(
        user_id=user_id,
        repo_url=request.repo_url,
        commit_sha=commit_sha,
        cache_key=cache_key,
        status="pending"
    )

    # Enqueue background task
    background_tasks.add_task(_run_pipeline, analysis.id, ...)

    return {"job_id": analysis.id}

@app.get("/status/{job_id}")
async def status(job_id: str):
    db = get_db()
    analysis = await db.get_analysis(job_id)

    return {
        "job_id": analysis.id,
        "status": analysis.status,
        "outputs": analysis.result_paths,
    }
```

**Checklist:**
- [ ] Remove `jobs: dict = {}`
- [ ] Update `_run_pipeline()` to use db + storage
- [ ] Update `/analyze` to create DB record
- [ ] Update `/status/{job_id}` to read from DB
- [ ] Update `/results/{job_id}` to return stored URLs
- [ ] Test pipeline runs end-to-end
- [ ] Verify results persist after server restart

---

### Phase 4: Add Result Caching (1 hour)

**File: `server/app.py`**

```python
@app.post("/analyze")
async def analyze(request: AnalyzeRequest, user_id: str = Depends(get_current_user)):
    db = get_db()

    # ... get commit_sha and build cache_key ...
    cache_key = hashlib.sha256((request.repo_url + commit_sha).encode()).hexdigest()

    # CHECK CACHE BEFORE RUNNING PIPELINE
    cached = await db.get_analysis_by_cache_key(cache_key)
    if cached and cached.status == "complete":
        logger.info(f"[analyze] Cache hit for {request.repo_url}@{commit_sha}")
        return {"job_id": cached.id, "cached": True}

    # Cache miss — create new analysis record
    analysis = await db.create_analysis(
        user_id=user_id,
        repo_url=request.repo_url,
        commit_sha=commit_sha,
        cache_key=cache_key,
    )

    # Run pipeline...
```

**Checklist:**
- [ ] Add cache check before pipeline
- [ ] Test: analyze same repo@commit twice
- [ ] Second request should return immediately with cached results
- [ ] Verify zero LLM cost on cache hit

---

### Phase 5: Add User Tiers & Rate Limiting (1.5 hours)

**File: `server/app.py`**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/analyze")
@limiter.limit("5/hour")  # Free tier: 5 analyses/hour
async def analyze(request: AnalyzeRequest, user_id: str = Depends(get_current_user)):
    db = get_db()
    user = await db.get_user(user_id)

    # Check tier limits
    if user.tier == "free":
        # Enforce free tier limits
        recent = await db.list_user_analyses(user_id, limit=100)
        recent_24h = [a for a in recent if (datetime.utcnow() - a.created_at).days < 1]
        if len(recent_24h) >= 5:
            raise HTTPException(status_code=429, detail="Rate limit: 5 analyses per day on free tier")

    # ... rest of analyze ...
```

**Checklist:**
- [ ] Add tier column to user table (done in schema)
- [ ] Implement tier checks in `/analyze`
- [ ] Test rate limiting
- [ ] Add pricing page with tier info

---

### Phase 6: Update Frontend Templates (2 hours)

**File: `server/templates/*.html`**

Update all templates to:
- Add auth UI (login/signup forms)
- Show user dashboard with past analyses
- Display cached results badge
- Link to stored result files

**Checklist:**
- [ ] Update `index.html` — add login form
- [ ] Update `results.html` — fetch URLs from `result_paths` (now stored in DB)
- [ ] Add `dashboard.html` — list user's past analyses
- [ ] Update nav to show user email + logout button

---

## Dependencies to Add

In `pyproject.toml`:

```toml
[project]
dependencies = [
    # ... existing ...
    "supabase>=0.7.0",  # For Supabase backend
    "asyncpg>=0.28.0",  # For AWS RDS PostgreSQL
    "aioboto3>=12.0.0", # For AWS S3
    "slowapi>=0.1.8",   # For rate limiting
    "python-jose[cryptography]>=3.3.0",  # For JWT validation
]
```

## Testing Strategy

### Local (Supabase)
```bash
export DB_BACKEND=supabase
export STORAGE_BACKEND=supabase
# ... set Supabase env vars ...
uv run uvicorn server.app:app --reload
```

### Local (AWS — mock)
```bash
# Use localstack or moto for local S3/RDS testing
export DB_BACKEND=aws
export STORAGE_BACKEND=aws
# ... point to local mock services ...
```

### Production (AWS)
```bash
export DB_BACKEND=aws
export STORAGE_BACKEND=aws
# ... point to real RDS + S3 ...
git push main  # GitHub Actions deploys
```

## Timeline

- **Day 1:** Phase 1-2 (init + auth)
- **Day 2:** Phase 3-4 (job state + caching)
- **Day 3:** Phase 5-6 (tiers + frontend)
- **Total:** 3 days to full integration

After that: deploy to EC2 (free tier) with AWS backend, use Supabase for local dev.
