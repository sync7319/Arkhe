# Arkhe Project Status

## Live Server
- **URL:** http://18.208.132.250:8000
- **Branch:** `dev`
- **Stack:** EC2 t3.micro (Ubuntu 24.04) + RDS PostgreSQL + S3

## AWS Infrastructure
| Resource | Details |
|----------|---------|
| EC2 | t3.micro, `18.208.132.250`, key in `GITIGNOREKEYS/` |
| RDS | PostgreSQL t4g.micro, `arkhe-db.cyhssyqwmu5w.us-east-1.rds.amazonaws.com` |
| S3 | `arkhe-results-528564298697-us-east-1-an` |
| IAM | `arkhe-app` user, AmazonS3FullAccess |

## What's Done
- Full pipeline end-to-end on EC2 (clone → analyze → synthesize → results page)
- Gate page: Developer mode (password) / User mode (NVIDIA key)
- RDS stores job records, S3 stores output files
- NVIDIA NIM (Nemotron-253B) as LLM provider
- Results page with working View Report / Download per output

## Known Limitations
- No result caching (same repo re-runs the full pipeline)
- No real user auth (hardcoded demo user UUID)
- No HTTPS / domain (IP only for now)
- Semantic search (`/ask`) disabled (no embedding backend on EC2)

## Restart Server on EC2
```bash
ssh -i GITIGNOREKEYS/arkhe-key.pem ubuntu@18.208.132.250
fuser -k 8000/tcp; cd ~/Arkhe && git pull origin dev
nohup /home/ubuntu/.local/bin/uv run uvicorn server.app:app --host 0.0.0.0 --port 8000 > ~/arkhe.log 2>&1 &
```

## Next Up
See ROADMAP.md. Logical next priorities:
1. **HTTPS + domain** — Caddy reverse proxy on EC2, point domain at it
2. **Result caching** — skip pipeline if same repo+commit already analyzed
3. **Persistent server** — systemd service so it survives EC2 reboots
