# Debugging Guide — Error Handling & Logging

When deployed to AWS, any error will include structured logging with context. This guide shows how to interpret logs and diagnose issues.

## Architecture

Every operation is logged with:
- **Operation name** — what's happening
- **Start timestamp** — when it began
- **Duration** — how long it took
- **Context** — relevant IDs and data
- **Error details** — type, message, and context

```
[aws-rds] → create_analysis {"user_id": "abc...", "repo_url": "...", "cache_key": "..."}
[aws-rds] ✓ create_analysis {"duration_ms": 12.5, "analysis_id": "xyz..."}

[aws-s3] → upload_file {"cache_key": "xyz...", "filename": "CODEBASE_MAP.md", "size_bytes": 15240}
[aws-s3] ✓ upload_file {"duration_ms": 345.2, "cache_key": "xyz...", "filename": "CODEBASE_MAP.md"}

[aws-rds] ❌ update_analysis_results {"analysis_id": "..."}
[aws-rds] Error: BackendQueryError: UPDATE analyses SET status = 'complete' failed
```

## Common Issues & Solutions

### 1. Connection Errors

**Error:** `BackendConnectionError: [aws-rds] Connection error: Failed to create connection pool`

**Likely causes:**
- RDS instance not running
- Security group doesn't allow port 5432 inbound
- Invalid credentials (AWS_RDS_HOST, AWS_RDS_PASSWORD)
- RDS endpoint is wrong (copy exactly from AWS console)

**Debug steps:**
```bash
# Test RDS connection manually
psql -h your-instance.xxx.us-east-1.rds.amazonaws.com \
     -U postgres \
     -d arkhe \
     -c "SELECT 1"

# Verify security group allows inbound on port 5432
# Check in AWS console → RDS → your-instance → Security group rules
```

### 2. S3 Bucket Access Errors

**Error:** `BackendConnectionError: [aws-s3] Failed to access bucket 'arkhe-results-prod'`

**Likely causes:**
- Bucket doesn't exist
- IAM role / credentials don't have s3:GetBucketLocation permission
- Wrong AWS_REGION (bucket is in different region)
- Wrong AWS_S3_BUCKET name

**Debug steps:**
```bash
# List all S3 buckets to verify it exists
aws s3 ls

# Test upload
aws s3 cp test.txt s3://arkhe-results-prod/test.txt

# If using IAM role on EC2, verify:
aws sts get-caller-identity
```

### 3. Table Not Found Errors

**Error:** `BackendQueryError: [aws-rds] UPDATE analyses SET status = 'complete' ... ERROR: relation "analyses" does not exist`

**Likely causes:**
- `init()` didn't run, or schema creation failed
- Running code against wrong database
- Table was deleted

**Debug steps:**
```bash
# Check tables exist
psql -h your-instance.xxx.us-east-1.rds.amazonaws.com \
     -U postgres \
     -d arkhe \
     -c "\dt"  # List tables

# If tables missing, manually create:
psql -h your-instance.xxx.us-east-1.rds.amazonaws.com \
     -U postgres \
     -d arkhe \
     -f /path/to/schema.sql
```

### 4. Rate Limiting / Timeout Errors

**Error:** `BackendQueryError: timeout expired`

**Likely causes:**
- Too many concurrent connections
- RDS instance is too small (t3.micro)
- Long-running queries blocking others
- Network latency from EC2 to RDS

**Debug steps:**
```bash
# Check connection pool size in aws_db.py
# min_size=5, max_size=20
# Consider reducing max_size if frequently hitting limits

# Check RDS metrics in AWS console
# Look for high CPU, high connections, slow queries

# If t3.micro is bottleneck, upgrade to t3.small
```

### 5. Permission Errors on Upload

**Error:** `BackendStorageError: [aws-s3] upload failed ... Access Denied`

**Likely causes:**
- IAM policy missing s3:PutObject permission
- Bucket doesn't allow public-read ACL
- Credentials expired or invalid

**Debug steps:**
```bash
# Test S3 upload manually
echo "test" | aws s3 cp - s3://arkhe-results-prod/test.txt

# Verify IAM permissions (if using explicit keys)
# Policy must include:
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::arkhe-results-prod",
        "arn:aws:s3:::arkhe-results-prod/*"
      ]
    }
  ]
}
```

### 6. Validation Errors

**Error:** `BackendValidationError: Validation error: cache_key = None, expected non-empty string`

**Likely causes:**
- Code is passing None or empty string as cache_key
- Analysis/User object not fully initialized

**Debug steps:**
```python
# Check cache_key generation
from hashlib import sha256
cache_key = sha256((repo_url + commit_sha).encode()).hexdigest()
print(f"Cache key: {cache_key}")  # Should be 64-char hex string

# Check user_id is UUID
from uuid import uuid4
user_id = str(uuid4())
print(f"User ID: {user_id}")  # Should be UUID format
```

---

## Log Levels

### DEBUG
Details of every operation start/finish. Too noisy for production but useful for debugging.

```
[backend] → get_user {"user_id": "abc..."}
[backend] → create_analysis {"repo_url": "..."}
[backend] - not found (cache miss)
```

### INFO
Successful operations with timing. Good for production monitoring.

```
[aws-rds] ✓ init {"duration_ms": 125.5}
[aws-rds] ✓ create_analysis {"duration_ms": 12.5, "analysis_id": "xyz..."}
[aws-s3] ✓ upload_file {"duration_ms": 345.2, "filename": "CODEBASE_MAP.md"}
```

### WARNING
Transient issues that were recovered from. Monitor these.

```
[aws-s3] ⚠️  Health check failed
[backend] ⚠️  Schema creation may have failed (might already exist)
```

### ERROR
Permanent failures that require intervention.

```
[aws-rds] ❌ init
[aws-rds] Error: BackendConnectionError: Failed to create connection pool
```

---

## Health Check Endpoint

Both backends expose `health_check()` method:

```python
@app.get("/_health")
async def health():
    db = get_db()
    storage = get_storage()

    db_healthy = await db.health_check()
    storage_healthy = await storage.health_check()

    if db_healthy and storage_healthy:
        return {"status": "ok"}

    return {"status": "degraded", "db": db_healthy, "storage": storage_healthy}, 503
```

Use this in:
- **Load balancer health checks** — ALB / Lightsail will auto-restart if unhealthy
- **Monitoring dashboards** — CloudWatch can alert if /health returns 503
- **Deployment validation** — Check health after deploying to EC2

---

## Example: Complete Error Trace

### User submits analysis, something fails:

**Logs in order:**
```
[supabase-storage] → init {"bucket": "arkhe-results"}
[supabase-storage] ✓ init {"duration_ms": 245.3, "bucket": "arkhe-results"}

[supabase] → create_user {"user_id": "abc...", "email": "user@example.com"}
[supabase] ✓ create_user {"duration_ms": 18.2, "user_id": "abc..."}

[supabase] → create_analysis {"user_id": "abc...", "repo_url": "https://github.com/...", "cache_key": "..."}
[supabase] ✓ create_analysis {"duration_ms": 15.7, "analysis_id": "xyz..."}

[supabase] → get_analysis_by_cache_key {"cache_key": "..."}
[supabase] - not found (first time, cache miss - expected)

# Pipeline runs...
[pipeline] Analyzing 47 files...
[pipeline] Running security audit...
[pipeline] Generating CODEBASE_MAP.md...

# Results upload
[supabase-storage] → upload_text {"cache_key": "xyz...", "filename": "CODEBASE_MAP.md", "size_bytes": 15240}
[supabase-storage] ✓ upload_text {"duration_ms": 312.5, "cache_key": "xyz...", "filename": "CODEBASE_MAP.md"}

# Store result URLs
[supabase] → update_analysis_results {"analysis_id": "xyz...", "status": "complete", "files": 2}
[supabase] ✓ update_analysis_results {"duration_ms": 22.1, "analysis_id": "xyz..."}
```

### Debugging: If upload fails mid-pipeline:

```
[supabase-storage] → upload_text {"cache_key": "xyz...", "filename": "CODEBASE_MAP.md", "size_bytes": 15240}
[supabase-storage] ❌ upload_text

BackendStorageError: [supabase-storage] Storage upload failed for CODEBASE_MAP.md
  Error: 413 Payload Too Large
  Context: {"cache_key": "xyz...", "size_bytes": 15240}
```

**Solution:** Supabase Storage has per-file size limit. Split large files or upgrade plan.

---

## Testing Locally

Before deploying to AWS, test both backends:

```bash
# Test Supabase (dev)
export DB_BACKEND=supabase
export STORAGE_BACKEND=supabase
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_ANON_KEY=your-key
pytest tests/test_backends.py -v

# Test AWS (needs credentials)
export DB_BACKEND=aws
export STORAGE_BACKEND=aws
export AWS_RDS_HOST=your-instance.xxx.us-east-1.rds.amazonaws.com
export AWS_RDS_PASSWORD=your-password
export AWS_S3_BUCKET=arkhe-results-prod
pytest tests/test_backends.py -v
```

Tests will skip if credentials are missing (not a failure).

---

## AWS CloudWatch Integration

Logs are written to stdout (file descriptor 1).

On EC2, capture logs with:

```bash
# Follow live logs
tail -f /var/log/arkhe.log

# Search for errors
grep "❌" /var/log/arkhe.log | head -20

# Filter by backend
grep "aws-rds" /var/log/arkhe.log | grep "Error"

# Count operations by type
grep "✓ create_analysis" /var/log/arkhe.log | wc -l
```

Configure CloudWatch agent to ingest `/var/log/arkhe.log`:

```json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/arkhe.log",
            "log_group_name": "/aws/ec2/arkhe",
            "log_stream_name": "{instance_id}"
          }
        ]
      }
    }
  }
}
```

Then search in CloudWatch Logs Insights:

```
fields @timestamp, @message
| filter @message like /❌/
| stats count() by @message
```

---

## Checklist Before AWS Deployment

- [ ] Run `pytest tests/test_backends.py -v` locally with AWS credentials
- [ ] All 55+ tests pass
- [ ] Created RDS instance (t3.micro free tier) with:
  - Database name: `arkhe`
  - User: `postgres`
  - Password: stored in AWS Secrets Manager
  - Security group: allows port 5432 from EC2
- [ ] Created S3 bucket `arkhe-results-prod` with:
  - Public read ACL enabled (or use presigned URLs)
  - Region matches `AWS_REGION` env var
- [ ] Tested RDS connection: `psql -h <endpoint> -U postgres -d arkhe -c "SELECT 1"`
- [ ] Tested S3 access: `aws s3 ls s3://arkhe-results-prod`
- [ ] Set environment variables on EC2:
  - `DB_BACKEND=aws`
  - `STORAGE_BACKEND=aws`
  - `AWS_RDS_HOST=...`
  - `AWS_RDS_PASSWORD=...`
  - `AWS_S3_BUCKET=arkhe-results-prod`
- [ ] Check `/health` endpoint returns 200 OK
- [ ] Submit a test analysis end-to-end
- [ ] Check CloudWatch Logs for any errors
