"""
Arkhe Web Server — FastAPI demo server for the website.

Endpoints:
  GET  /                              — landing page
  POST /analyze                       — submit a repo URL, returns job_id
  GET  /status/{job_id}               — poll job status
  GET  /results/{job_id}              — results dashboard
  GET  /results/{job_id}/view/{file}  — dedicated viewer (map or report)
  GET  /results/{job_id}/{file}       — serve raw output file (for download/iframe)
  GET  /pricing                       — pricing page
  GET  /_health                       — health check

Run locally:
  uv run uvicorn server.app:app --reload --port 8000
"""
import asyncio
import hashlib
import logging
import os
import shutil
import uuid
from enum import Enum
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scripts.clone_repo import CloneError, clone_repo

logger = logging.getLogger("arkhe.server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("arkhe.llm").setLevel(logging.DEBUG)
logging.getLogger("arkhe.router").setLevel(logging.DEBUG)
logging.getLogger("arkhe.analyst").setLevel(logging.DEBUG)

app = FastAPI(title="Arkhe", docs_url=None, redoc_url=None)

# ── Paths ─────────────────────────────────────────────────────────────────────

SERVER_DIR  = Path(__file__).parent
RESULTS_DIR = SERVER_DIR / "results"
CACHE_DIR   = SERVER_DIR / "cache"
RESULTS_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)


def _repo_cache_dir(url: str) -> Path:
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    d = CACHE_DIR / url_hash
    d.mkdir(parents=True, exist_ok=True)
    return d


templates = Jinja2Templates(directory=str(SERVER_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(SERVER_DIR / "static")), name="static")


# ── Job state ─────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    COMPLETE = "complete"
    ERROR    = "error"


jobs: dict[str, dict] = {}

OUTPUT_FILES = [
    ("CODEBASE_MAP.md",      "Codebase Map",        "markdown"),
    ("DEPENDENCY_MAP.html",  "Dependency Graph",    "html"),
    ("EXECUTIVE_REPORT.docx","Executive Report",    "docx"),
    ("SECURITY_REPORT.md",   "Security Report",     "markdown"),
    ("DEAD_CODE_REPORT.md",  "Dead Code Report",    "markdown"),
    ("TEST_GAP_REPORT.md",   "Test Gap Report",     "markdown"),
    ("PR_IMPACT.md",         "PR Impact Report",    "markdown"),
]


# ── Options → settings patch ──────────────────────────────────────────────────

def _apply_options(options: dict) -> None:
    import config.settings as s
    flag_map = {
        "codebase_map":       "CODEBASE_MAP_ENABLED",
        "dependency_map":     "DEPENDENCY_MAP_ENABLED",
        "executive_report":   "EXECUTIVE_REPORT_ENABLED",
        "security_audit":     "SECURITY_AUDIT_ENABLED",
        "dead_code":          "DEAD_CODE_DETECTION_ENABLED",
        "test_gap":           "TEST_GAP_ANALYSIS_ENABLED",
        "test_scaffolding":   "TEST_SCAFFOLDING_ENABLED",
        "complexity_heatmap": "COMPLEXITY_HEATMAP_ENABLED",
        "pr_analysis":        "PR_ANALYSIS_ENABLED",
    }
    for key, attr in flag_map.items():
        if key in options:
            setattr(s, attr, bool(options[key]))


# ── Background pipeline ───────────────────────────────────────────────────────

async def _run_pipeline(job_id: str, url: str, options: dict) -> None:
    jobs[job_id]["status"] = JobStatus.RUNNING
    job_results_dir = RESULTS_DIR / job_id
    job_results_dir.mkdir(exist_ok=True)

    persistent_cache = _repo_cache_dir(url)
    _apply_options(options)

    try:
        def _step(step: int, label: str) -> None:
            if job_id in jobs:
                jobs[job_id]["step"]       = step
                jobs[job_id]["step_label"] = label

        with clone_repo(url) as repo_path:
            temp_cache = Path(repo_path) / ".arkhe_cache"
            temp_cache.mkdir(exist_ok=True)
            cached_db = persistent_cache / "arkhe.db"
            if cached_db.exists():
                shutil.copy2(cached_db, temp_cache / "arkhe.db")
                logger.info(f"[job {job_id}] restored cache from previous run")

            try:
                from main import run as arkhe_run
                await arkhe_run(repo_path, fmt="default", refactor=False, progress_cb=_step)
            finally:
                live_db = temp_cache / "arkhe.db"
                if live_db.exists():
                    shutil.copy2(live_db, cached_db)
                    logger.info(f"[job {job_id}] saved cache for future retries")

            docs_dir = Path(repo_path) / "docs"
            outputs = []
            if docs_dir.exists():
                for filename, label, kind in OUTPUT_FILES:
                    src = docs_dir / filename
                    if src.exists():
                        dst = job_results_dir / filename
                        dst.write_bytes(src.read_bytes())
                        outputs.append({"filename": filename, "label": label, "kind": kind})

            jobs[job_id]["outputs"] = outputs
            jobs[job_id]["status"]  = JobStatus.COMPLETE
            logger.info(f"[job {job_id}] complete — {len(outputs)} output(s)")

    except CloneError as e:
        jobs[job_id]["status"] = JobStatus.ERROR
        jobs[job_id]["error"]  = str(e)
        logger.error(f"[job {job_id}] clone error: {e}")
    except RuntimeError as e:
        err = str(e)
        if "rate-limited or failed" in err or "All models" in err:
            from config.model_router import COOLDOWN_SECONDS
            retry_mins = COOLDOWN_SECONDS // 60
            jobs[job_id]["status"] = JobStatus.ERROR
            jobs[job_id]["error"]  = (
                f"All AI models are currently rate-limited. "
                f"Your progress has been saved — resubmit the same URL in "
                f"~{retry_mins} minutes and it will resume from where it stopped."
            )
        else:
            jobs[job_id]["status"] = JobStatus.ERROR
            jobs[job_id]["error"]  = f"Pipeline error: {err[:300]}"
        logger.error(f"[job {job_id}] runtime error: {e}")
    except Exception as e:
        jobs[job_id]["status"] = JobStatus.ERROR
        jobs[job_id]["error"]  = f"Unexpected error: {str(e)[:300]}"
        logger.exception(f"[job {job_id}] pipeline error")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    return templates.TemplateResponse("pricing.html", {"request": request})


@app.post("/analyze")
async def analyze(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    url  = (body.get("url") or "").strip()

    if not url:
        return JSONResponse({"error": "URL is required"}, status_code=400)

    try:
        from scripts.clone_repo import parse_repo_url
        parse_repo_url(url)
    except CloneError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    options = body.get("options") or {}
    job_id  = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status":     JobStatus.PENDING,
        "url":        url,
        "outputs":    [],
        "error":      None,
        "step":       0,
        "step_label": "Cloning repository...",
    }

    background_tasks.add_task(_run_pipeline, job_id, url, options)
    logger.info(f"[job {job_id}] queued: {url}")
    return JSONResponse({"job_id": job_id})


@app.get("/status/{job_id}")
async def status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse({
        "status":     job["status"],
        "outputs":    job["outputs"],
        "error":      job["error"],
        "step":       job.get("step", 0),
        "step_label": job.get("step_label", ""),
    })


def _reconstruct_job_from_disk(job_id: str) -> dict | None:
    """Rebuild a minimal job dict from on-disk results when the in-memory job is gone (e.g. after server reload)."""
    job_dir = RESULTS_DIR / job_id
    if not job_dir.exists():
        return None
    outputs = []
    for filename, label, kind in OUTPUT_FILES:
        if (job_dir / filename).exists():
            outputs.append({"filename": filename, "label": label, "kind": kind})
    return {"status": "complete", "url": "", "outputs": outputs, "error": None}


@app.get("/results/{job_id}", response_class=HTMLResponse)
async def results(request: Request, job_id: str):
    job = jobs.get(job_id) or _reconstruct_job_from_disk(job_id)
    if not job:
        return HTMLResponse("<h2>Job not found.</h2>", status_code=404)
    return templates.TemplateResponse("results.html", {
        "request": request,
        "job_id":  job_id,
        "job":     job,
    })


@app.get("/results/{job_id}/view/{filename}", response_class=HTMLResponse)
async def view_output(request: Request, job_id: str, filename: str):
    allowed = {f for f, _, _ in OUTPUT_FILES}
    if filename not in allowed:
        return HTMLResponse("<h2>File not found.</h2>", status_code=404)

    path = RESULTS_DIR / job_id / filename
    if not path.exists():
        return HTMLResponse("<h2>Output not yet generated.</h2>", status_code=404)

    job     = jobs.get(job_id) or {}
    job_url = job.get("url", "")
    label   = next((l for f, l, _ in OUTPUT_FILES if f == filename), filename)

    if filename.endswith(".html"):
        # Dependency map — full-screen iframe viewer
        return templates.TemplateResponse("map_viewer.html", {
            "request": request,
            "job_id":  job_id,
            "job_url": job_url,
        })

    if filename.endswith(".md"):
        content = path.read_text(encoding="utf-8", errors="replace")
        return templates.TemplateResponse("report_viewer.html", {
            "request": request,
            "job_id":  job_id,
            "filename": filename,
            "label":   label,
            "content": content,
            "job_url": job_url,
        })

    # Fallback for any other type — serve directly
    return FileResponse(str(path))


@app.get("/results/{job_id}/{filename}")
async def serve_file(job_id: str, filename: str):
    allowed = {f for f, _, _ in OUTPUT_FILES}
    if filename not in allowed:
        return JSONResponse({"error": "File not found"}, status_code=404)
    path = RESULTS_DIR / job_id / filename
    if not path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(str(path))


@app.get("/_health")
async def health():
    return {"status": "ok"}
