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
  POST /context/{job_id}              — smart file ranking: task + budget → ranked files
  GET  /context/{job_id}/view         — interactive context picker UI
  GET  /impact/{job_id}?file=path     — transitive blast radius query
  GET  /impact/{job_id}/view          — interactive blast radius explorer UI
  GET  /_health                       — health check
  GET  /debug                         — inspector: list all jobs (ARKHE_DEBUG=false to disable)
  GET  /debug/{job_id}                — inspector: all outputs + graph nodes + server log tail

Run locally:
  uv run uvicorn server.app:app --reload --port 8000
"""
import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
import uuid
import zipfile
from enum import Enum
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Security
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from scripts.clone_repo import CloneError, clone_repo

# ── Debug inspector — set ARKHE_DEBUG=false to disable completely ─────────────
DEBUG_MODE = os.getenv("ARKHE_DEBUG", "true").lower() != "false"

# ── Optional API key auth — set ARKHE_API_KEY in .env to enable ───────────────
_ARKHE_API_KEY = os.getenv("ARKHE_API_KEY", "")
_api_key_header = APIKeyHeader(name="X-Arkhe-Key", auto_error=False)


def _require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Dependency: enforces API key only when ARKHE_API_KEY env var is set."""
    if _ARKHE_API_KEY and key != _ARKHE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


# ── Rate limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/hour"])

# ── Concurrent job cap ─────────────────────────────────────────────────────────
MAX_CONCURRENT_JOBS = int(os.getenv("ARKHE_MAX_CONCURRENT_JOBS", "3"))
_JOB_SEMAPHORE: asyncio.Semaphore | None = None  # initialised in lifespan

# ── Min free disk space before refusing new jobs (bytes) ──────────────────────
MIN_FREE_BYTES = int(os.getenv("ARKHE_MIN_FREE_MB", "500")) * 1024 * 1024

import sys
import structlog

_LOG_JSON = not sys.stderr.isatty()  # JSON in production, human-friendly in dev

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer() if _LOG_JSON else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(Path(__file__).parent / "server.log"), mode="w"),
    ],
)
logging.getLogger("arkhe.llm").setLevel(logging.DEBUG)
logging.getLogger("arkhe.router").setLevel(logging.DEBUG)
logging.getLogger("arkhe.analyst").setLevel(logging.DEBUG)
logging.getLogger("arkhe.dispatcher").setLevel(logging.DEBUG)

logger = logging.getLogger("arkhe.server")

@asynccontextmanager
async def _lifespan(app_: FastAPI):
    global _JOB_SEMAPHORE
    _JOB_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    asyncio.create_task(_cleanup_old_results())
    yield


app = FastAPI(
    title="Arkhe API",
    description="Autonomous codebase intelligence. Blast radius, smart context, dependency graphs.",
    version="0.3.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=_lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
    ("REFACTORED_CODE.zip",  "Refactored Code",     "zip"),
    ("GRAPH.json",           "Dependency Graph Data","json"),
    ("CONTEXT_INDEX.json",   "Context Index",        "json"),
]

# Files that are internal data (not shown in results UI as downloads)
_INTERNAL_FILES = {"GRAPH.json", "CONTEXT_INDEX.json"}


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
        "refactor":           "REFACTOR_ENABLED",
    }
    for key, attr in flag_map.items():
        if key in options:
            setattr(s, attr, bool(options[key]))


# ── Background pipeline ───────────────────────────────────────────────────────

async def _run_pipeline(job_id: str, url: str, options: dict) -> None:
    await _JOB_SEMAPHORE.acquire()
    jobs[job_id]["status"] = JobStatus.RUNNING
    job_results_dir = RESULTS_DIR / job_id
    job_results_dir.mkdir(exist_ok=True)

    persistent_cache = _repo_cache_dir(url)
    _apply_options(options)

    # Ensure model pools are built before the pipeline runs
    from config.settings import GROQ_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, NVIDIA_API_KEY
    from config.model_router import build_available_pools
    logger.info(f"[pipeline] API keys present: groq={'yes' if GROQ_API_KEY else 'no'}, gemini={'yes' if GEMINI_API_KEY else 'no'}, nvidia={'yes' if NVIDIA_API_KEY else 'no'}, anthropic={'yes' if ANTHROPIC_API_KEY else 'no'}")
    build_available_pools({
        "groq":      GROQ_API_KEY,
        "gemini":    GEMINI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "openai":    OPENAI_API_KEY,
        "nvidia":    NVIDIA_API_KEY,
    })

    from config.dispatcher import start_dispatcher
    await start_dispatcher()

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

            import config.settings as _s
            refactor_enabled = _s.REFACTOR_ENABLED

            try:
                from main import run as arkhe_run
                await arkhe_run(repo_path, fmt="default", refactor=refactor_enabled, progress_cb=_step)
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
                        # Internal data files are copied but not shown in UI
                        if filename not in _INTERNAL_FILES:
                            outputs.append({"filename": filename, "label": label, "kind": kind})

            # Zip refactored code if refactor was enabled
            if refactor_enabled:
                import zipfile
                refactored_dir = Path(repo_path + "_refactored")
                if refactored_dir.exists():
                    zip_path = job_results_dir / "REFACTORED_CODE.zip"
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for file in refactored_dir.rglob("*"):
                            if file.is_file():
                                zf.write(file, file.relative_to(refactored_dir))
                    outputs.append({"filename": "REFACTORED_CODE.zip", "label": "Refactored Code", "kind": "zip"})
                    logger.info(f"[job {job_id}] zipped refactored code → {zip_path}")

            jobs[job_id]["outputs"] = outputs
            jobs[job_id]["status"]  = JobStatus.COMPLETE
            logger.info(f"[job {job_id}] complete — {len(outputs)} output(s)")

            # Persist minimal metadata so results survive server restarts
            _save_meta(job_id, url, outputs)

    except CloneError as e:
        jobs[job_id]["status"] = JobStatus.ERROR
        jobs[job_id]["error"]  = str(e)
        logger.error(f"[job {job_id}] clone error: {e}")
    except RuntimeError as e:
        import traceback
        with open(str(SERVER_DIR / "error.log"), "a") as f:
            f.write(f"\n[JOB {job_id}] RuntimeError: {e}\n")
            traceback.print_exc(file=f)
        err = str(e)
        if "rate-limited or failed" in err or "All models" in err:
            jobs[job_id]["status"] = JobStatus.ERROR
            jobs[job_id]["error"]  = (
                "All AI models are currently rate-limited. "
                "Your progress has been saved — resubmit the same URL in "
                "a few minutes and it will resume from where it stopped."
            )
        else:
            jobs[job_id]["status"] = JobStatus.ERROR
            jobs[job_id]["error"]  = f"Pipeline error: {err[:300]}"
        logger.error(f"[job {job_id}] runtime error: {e}")
    except Exception as e:
        import traceback
        with open(str(SERVER_DIR / "error.log"), "a") as f:
            f.write(f"\n[JOB {job_id}] Exception: {type(e).__name__}: {e}\n")
            traceback.print_exc(file=f)
        jobs[job_id]["status"] = JobStatus.ERROR
        jobs[job_id]["error"]  = f"Unexpected error: {str(e)[:300]}"
        logger.exception(f"[job {job_id}] pipeline error")
    finally:
        _JOB_SEMAPHORE.release()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    return FileResponse(str(SERVER_DIR / "static" / "favicon.svg"), media_type="image/svg+xml")


@app.get("/manifest.json", include_in_schema=False)
async def manifest():
    return FileResponse(str(SERVER_DIR / "static" / "manifest.json"), media_type="application/manifest+json")


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    return templates.TemplateResponse(request, "pricing.html")


@app.post("/analyze", dependencies=[Security(_require_api_key)])
@limiter.limit("5/hour")
async def analyze(request: Request, background_tasks: BackgroundTasks):
    # Disk space guard
    free = shutil.disk_usage(RESULTS_DIR).free
    if free < MIN_FREE_BYTES:
        return JSONResponse(
            {"error": f"Server storage is full ({free // 1024 // 1024} MB free). Try again later."},
            status_code=507,
        )

    # Concurrent job cap
    running = sum(1 for j in jobs.values() if j["status"] == JobStatus.RUNNING)
    if running >= MAX_CONCURRENT_JOBS:
        return JSONResponse(
            {"error": f"Server is busy ({running} jobs running). Please try again in a few minutes."},
            status_code=503,
            headers={"Retry-After": "120"},
        )

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
        "created_at": time.time(),
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


@app.get("/stream/{job_id}", tags=["jobs"])
async def stream_status(job_id: str):
    """
    Server-Sent Events stream for real-time job progress.
    Connect with EventSource('/stream/{job_id}').
    Events: {status, step, step_label, error?, outputs?}
    Stream closes automatically when job reaches 'complete' or 'error'.
    """
    async def _gen():
        last_step = -1
        last_status = ""
        while True:
            job = jobs.get(job_id)
            if not job:
                payload = json.dumps({"status": "error", "error": "Job not found", "step": 0, "step_label": ""})
                yield f"data: {payload}\n\n"
                return

            status     = job["status"]
            step       = job.get("step", 0)
            step_label = job.get("step_label", "")

            # Send update when step or status changes
            if step != last_step or status != last_status:
                last_step   = step
                last_status = status
                payload = {"status": status, "step": step, "step_label": step_label, "error": job.get("error")}
                if status == "complete":
                    payload["outputs"] = job.get("outputs", [])
                yield f"data: {json.dumps(payload)}\n\n"

            if status in ("complete", "error"):
                return

            await asyncio.sleep(0.25)  # check 4× per second

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx/proxy buffering
            "Connection":       "keep-alive",
        },
    )


def _save_meta(job_id: str, url: str, outputs: list) -> None:
    """Persist job metadata to disk so results survive server restarts."""
    meta = {
        "job_id":     job_id,
        "url":        url,
        "status":     "complete",
        "outputs":    outputs,
        "created_at": time.time(),
    }
    try:
        (RESULTS_DIR / job_id / "meta.json").write_text(json.dumps(meta))
    except Exception as e:
        logger.warning(f"[job {job_id}] could not save meta.json: {e}")


def _reconstruct_job_from_disk(job_id: str) -> dict | None:
    """Rebuild a job dict from disk — reads meta.json if available, falls back to file scan."""
    job_dir = RESULTS_DIR / job_id
    if not job_dir.exists():
        return None

    # Fast path: use persisted metadata
    meta_path = job_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            return {
                "status":     meta.get("status", "complete"),
                "url":        meta.get("url", ""),
                "outputs":    meta.get("outputs", []),
                "error":      meta.get("error"),
                "created_at": meta.get("created_at", 0),
            }
        except Exception:
            pass  # fall through to file scan

    # Fallback: scan disk (legacy jobs without meta.json)
    outputs = []
    for filename, label, kind in OUTPUT_FILES:
        if (job_dir / filename).exists() and filename not in _INTERNAL_FILES:
            outputs.append({"filename": filename, "label": label, "kind": kind})
    return {"status": "complete", "url": "", "outputs": outputs, "error": None, "created_at": 0}


# ── Result cleanup — delete jobs older than TTL ───────────────────────────────

RESULT_TTL_HOURS = 48  # auto-delete results after 48 hours


async def _cleanup_old_results() -> None:
    """Background task: delete result directories older than RESULT_TTL_HOURS."""
    while True:
        await asyncio.sleep(3600)  # run every hour
        cutoff = time.time() - RESULT_TTL_HOURS * 3600
        deleted = 0
        for job_dir in RESULTS_DIR.iterdir():
            if not job_dir.is_dir():
                continue
            meta_path = job_dir / "meta.json"
            try:
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text())
                    created_at = meta.get("created_at", 0)
                else:
                    # Use directory mtime as fallback
                    created_at = job_dir.stat().st_mtime
                if created_at < cutoff:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    jobs.pop(job_dir.name, None)
                    deleted += 1
            except Exception:
                pass
        if deleted:
            logger.info(f"[cleanup] Deleted {deleted} expired job(s) (older than {RESULT_TTL_HOURS}h)")




@app.get("/results/{job_id}", response_class=HTMLResponse)
async def results(request: Request, job_id: str):
    job = jobs.get(job_id) or _reconstruct_job_from_disk(job_id)
    if not job:
        return HTMLResponse("<h2>Job not found.</h2>", status_code=404)
    return templates.TemplateResponse(request, "results.html", {
        "job_id":     job_id,
        "job":        job,
        "created_at": job.get("created_at", 0),
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
        return templates.TemplateResponse(request, "map_viewer.html", {
            "job_id":  job_id,
            "job_url": job_url,
        })

    if filename.endswith(".md"):
        content = path.read_text(encoding="utf-8", errors="replace")
        return templates.TemplateResponse(request, "report_viewer.html", {
            "job_id":   job_id,
            "filename": filename,
            "label":    label,
            "content":  content,
            "job_url":  job_url,
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


# ── Context endpoint — smart file ranking for AI agents ──────────────────────

@app.post("/context/{job_id}")
async def context_query(job_id: str, request: Request):
    import json
    import math

    body   = await request.json()
    task   = (body.get("task") or "").strip().lower()
    budget = int(body.get("budget") or 8000)
    # Optional: filter by file extension(s), e.g. ["py", ".py"] or ".py,.ts"
    exts_raw = body.get("exts") or body.get("extensions") or ""
    if isinstance(exts_raw, list):
        filter_exts = {("." + e.lstrip(".").lower()) for e in exts_raw if e}
    elif exts_raw:
        filter_exts = {("." + e.strip().lstrip(".").lower()) for e in str(exts_raw).split(",") if e.strip()}
    else:
        filter_exts = set()
    # Optional: filter by path prefix, e.g. "agents/" or "src/components"
    path_prefix = (body.get("path") or "").strip().rstrip("/")

    job_dir  = RESULTS_DIR / job_id
    ctx_path = job_dir / "CONTEXT_INDEX.json"
    grp_path = job_dir / "GRAPH.json"

    if not ctx_path.exists():
        return JSONResponse({"error": "Context index not available — run analysis first"}, status_code=404)

    ctx   = json.loads(ctx_path.read_text())
    files = ctx["files"]

    # Apply extension and path filters
    if filter_exts:
        files = [f for f in files if any(f["path"].lower().endswith(e) for e in filter_exts)]
    if path_prefix:
        files = [f for f in files if f["path"].startswith(path_prefix)]

    # Load graph once; used for both centrality and import-chain boost
    graph_data: dict = {}
    if grp_path.exists():
        graph_data = json.loads(grp_path.read_text())

    # Build reverse dep count (in-degree centrality) from graph
    centrality: dict[str, int] = {}
    _id_to_path: dict[int, str] = {}
    _path_to_id: dict[str, int] = {}
    _forward:    dict[int, list[int]] = {}
    if graph_data:
        _id_to_path = {n["id"]: n["path"] for n in graph_data.get("nodes", [])}
        _path_to_id = {n["path"]: n["id"] for n in graph_data.get("nodes", [])}
        for link in graph_data.get("links", []):
            tgt = _id_to_path.get(link["target"], "")
            if tgt:
                centrality[tgt] = centrality.get(tgt, 0) + 1
            if link.get("bidirectional"):
                src = _id_to_path.get(link["source"], "")
                if src:
                    centrality[src] = centrality.get(src, 0) + 1
            _forward.setdefault(link["source"], []).append(link["target"])

    # Score each file by relevance to task
    task_words = set(task.split()) if task else set()
    task_list  = task.split()
    task_bigrams = {f"{task_list[i]} {task_list[i+1]}" for i in range(len(task_list) - 1)}

    def _symbol_words(f: dict) -> set[str]:
        path_lower = f["path"].replace("/", " ").replace("_", " ").replace(".", " ").lower()
        fn_text    = " ".join(f.get("functions", [])).replace("_", " ").lower()
        cls_text   = " ".join(f.get("classes",   [])).replace("_", " ").lower()
        return set((path_lower + " " + fn_text + " " + cls_text).split())

    def score_file(f: dict) -> tuple[float, list[str]]:
        """Returns (score, match_reasons) — reasons are the matched keywords/phrases."""
        sym_words = _symbol_words(f)
        snippet   = (f.get("snippet") or "").lower()
        reasons: list[str] = []

        if task_words:
            exact_hits = task_words & sym_words
            exact      = len(exact_hits) * 3.0
            reasons.extend(sorted(exact_hits)[:4])

            partial_hits = {tw for tw in task_words if tw not in exact_hits and any(tw in w or w in tw for w in sym_words)}
            partial      = len(partial_hits) * 0.5

            phrase_hits = {bg for bg in task_bigrams if bg in (f["path"].lower() + " " + snippet)}
            phrase       = len(phrase_hits) * 2.0
            reasons.extend(sorted(phrase_hits)[:2])

            snip_hits = {tw for tw in task_words if tw not in exact_hits and tw in snippet}
            snip_score = len(snip_hits) * 1.0
            reasons.extend(sorted(snip_hits - partial_hits)[:2])

            kw_score  = exact + partial + phrase + snip_score
        else:
            kw_score = 0.0

        central = math.log1p(centrality.get(f["path"], 0)) * 2.0
        return kw_score + central, list(dict.fromkeys(reasons))  # dedup, preserve order

    score_results = {f["path"]: score_file(f) for f in files}
    raw_scores    = {path: s for path, (s, _) in score_results.items()}
    raw_reasons   = {path: r for path, (_, r) in score_results.items()}

    # Import-chain boost: high-scoring file's dependencies get a 25% score bump
    # so the files a relevant file depends on also surface (they're needed to understand it)
    if task_words and graph_data:
        for f in files:
            fid = _path_to_id.get(f["path"])
            if fid is None:
                continue
            parent_score = raw_scores.get(f["path"], 0)
            if parent_score > 1.0:
                for dep_id in _forward.get(fid, []):
                    dep_path = _id_to_path.get(dep_id, "")
                    if dep_path and dep_path in raw_scores:
                        raw_scores[dep_path] += parent_score * 0.25

    scored = [(raw_scores[f["path"]], f) for f in files]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Greedily select files within budget
    selected    = []
    tokens_used = 0
    for score, f in scored:
        if tokens_used >= budget:
            break
        ft = max(f.get("tokens", 100), 1)
        tokens_used += ft
        selected.append({
            "score":   round(score, 2),
            "reasons": raw_reasons.get(f["path"], []),
            **f,
        })

    # Truncate snippets proportionally if over budget
    total_tokens = sum(max(f.get("tokens", 100), 1) for f in selected)
    if total_tokens > budget and selected:
        scale = budget / total_tokens
        for f in selected:
            snippet = f.get("snippet", "")
            f["snippet"] = snippet[:int(len(snippet) * scale)]

    # Annotate each file with its share of the budget (for UI visualisation)
    effective_total = max(total_tokens, 1)
    for f in selected:
        f["tokens_pct"] = round(max(f.get("tokens", 100), 1) / effective_total * 100, 1)

    return JSONResponse({
        "task":            task,
        "budget":          budget,
        "files_total":     len(files),
        "files_selected":  len(selected),
        "tokens_estimated": min(tokens_used, budget),
        "results":         selected,
    })


@app.get("/context/{job_id}", response_class=JSONResponse)
async def context_query_get(
    job_id: str,
    task: str = "",
    budget: int = 8000,
    exts: str = "",
    path: str = "",
    request: Request = None,
):
    """GET version of context query — same logic, accepts query params instead of JSON body.
    Usage: GET /context/{job_id}?task=fix+auth+bug&budget=16000&exts=.py,.ts&path=agents/
    """
    class _FakeRequest:
        async def json(self_):
            return {"task": task, "budget": budget, "exts": exts, "path": path}
    return await context_query(job_id, _FakeRequest())


@app.get("/context/{job_id}/view", response_class=HTMLResponse)
async def context_view(request: Request, job_id: str):
    job = jobs.get(job_id) or _reconstruct_job_from_disk(job_id)
    if not job:
        return HTMLResponse("<h2>Job not found.</h2>", status_code=404)
    return templates.TemplateResponse(request, "context.html", {
        "job_id":  job_id,
        "job_url": job.get("url", ""),
    })


# ── Impact endpoint — transitive blast radius ────────────────────────────────

@app.get("/impact/{job_id}", response_class=JSONResponse)
async def impact_query(job_id: str, file: str = ""):
    import json

    job_dir  = RESULTS_DIR / job_id
    grp_path = job_dir / "GRAPH.json"

    if not grp_path.exists():
        return JSONResponse({"error": "Graph data not available — run analysis first"}, status_code=404)

    graph = json.loads(grp_path.read_text())
    nodes = graph.get("nodes", [])
    links = graph.get("links", [])

    if not file:
        return JSONResponse({
            "nodes": [{"id": n["id"], "path": n["path"], "tokens": n.get("tokens", 0)} for n in nodes]
        })

    id_to_path = {n["id"]: n["path"] for n in nodes}
    path_to_id = {n["path"]: n["id"] for n in nodes}

    # Fuzzy path match
    target_path = file
    if target_path not in path_to_id:
        matches = [p for p in path_to_id if file in p or p.endswith(file)]
        if matches:
            target_path = matches[0]
        else:
            return JSONResponse({"error": f"File not found: {file}"}, status_code=404)

    target_id = path_to_id[target_path]

    # Build reverse map: id → list of ids that import it
    reverse: dict[int, list[int]] = {}
    for link in links:
        src, tgt = link["source"], link["target"]
        reverse.setdefault(tgt, []).append(src)
        if link.get("bidirectional"):
            reverse.setdefault(src, []).append(tgt)

    # BFS for transitive dependents
    visited: set[int]       = set()
    depth_map: dict[int, int] = {target_id: 0}
    queue                   = [target_id]

    while queue:
        current = queue.pop(0)
        for importer_id in reverse.get(current, []):
            if importer_id not in visited and importer_id != target_id:
                visited.add(importer_id)
                depth_map[importer_id] = depth_map[current] + 1
                queue.append(importer_id)

    # Forward deps (what this file imports), including bidirectional links
    forward: dict[int, list[int]] = {}
    for link in links:
        forward.setdefault(link["source"], []).append(link["target"])
        if link.get("bidirectional"):
            forward.setdefault(link["target"], []).append(link["source"])
    direct_deps = [id_to_path[i] for i in forward.get(target_id, []) if i in id_to_path]

    # Build per-node metadata (complexity, tokens) for affected file details
    id_to_node = {n["id"]: n for n in nodes}

    affected = sorted(
        [
            {
                "path":       id_to_path[i],
                "depth":      depth_map[i],
                "direct":     depth_map[i] == 1,
                "tokens":     id_to_node.get(i, {}).get("tokens", 0),
                "complexity": id_to_node.get(i, {}).get("complexity", 0),
            }
            for i in visited
        ],
        key=lambda x: (x["depth"], x["path"]),
    )

    direct_count     = sum(1 for a in affected if a["direct"])
    transitive_count = len(affected) - direct_count

    # Risk: count-based + complexity-weighted
    total_complexity = sum(a.get("complexity", 0) for a in affected)
    target_complexity = id_to_node.get(target_id, {}).get("complexity", 0)
    complexity_score = (total_complexity + target_complexity) / 100.0

    if not affected:
        risk, risk_reason = "LOW", "No other files depend on this one — isolated change."
    elif len(affected) <= 3 and complexity_score < 5:
        risk, risk_reason = "LOW", f"{len(affected)} file(s) affected — small blast radius."
    elif len(affected) <= 10 and complexity_score < 20:
        risk, risk_reason = "MEDIUM", f"{len(affected)} file(s) affected including {transitive_count} transitive."
    else:
        risk, risk_reason = "HIGH", (
            f"{len(affected)} file(s) affected — this is a central hub. "
            f"Complexity score: {round(complexity_score, 1)}."
        )

    target_node = id_to_node.get(target_id, {})

    return JSONResponse({
        "file":             target_path,
        "functions":        target_node.get("functions", []),
        "classes":          target_node.get("classes", []),
        "tokens":           target_node.get("tokens", 0),
        "complexity":       target_node.get("complexity", 0),
        "direct_deps":      direct_deps,
        "affected":         affected,
        "direct_count":     direct_count,
        "transitive_count": transitive_count,
        "total_affected":   len(affected),
        "total_complexity": total_complexity,
        "risk":             risk,
        "risk_reason":      risk_reason,
    })


@app.get("/impact/{job_id}/view", response_class=HTMLResponse)
async def impact_view(request: Request, job_id: str):
    job = jobs.get(job_id) or _reconstruct_job_from_disk(job_id)
    if not job:
        return HTMLResponse("<h2>Job not found.</h2>", status_code=404)
    return templates.TemplateResponse(request, "impact.html", {
        "job_id":  job_id,
        "job_url": job.get("url", ""),
    })


@app.get("/graph/{job_id}/stats", response_class=JSONResponse)
async def graph_stats(job_id: str):
    """Return high-level graph analytics: hub files, isolated nodes, circular deps, degree distribution."""
    import json

    grp_path = RESULTS_DIR / job_id / "GRAPH.json"
    if not grp_path.exists():
        return JSONResponse({"error": "Graph data not available"}, status_code=404)

    graph = json.loads(grp_path.read_text())
    nodes = graph.get("nodes", [])
    links = graph.get("links", [])

    id_to_path = {n["id"]: n["path"] for n in nodes}

    # Degree counts
    in_degree:  dict[int, int] = {n["id"]: 0 for n in nodes}
    out_degree: dict[int, int] = {n["id"]: 0 for n in nodes}
    adjacency:  dict[int, list[int]] = {n["id"]: [] for n in nodes}  # forward edges for cycle detection

    for link in links:
        src, tgt = link["source"], link["target"]
        out_degree[src] = out_degree.get(src, 0) + 1
        in_degree[tgt]  = in_degree.get(tgt, 0) + 1
        adjacency.setdefault(src, []).append(tgt)
        if link.get("bidirectional"):
            out_degree[tgt] = out_degree.get(tgt, 0) + 1
            in_degree[src]  = in_degree.get(src, 0) + 1
            adjacency.setdefault(tgt, []).append(src)

    # Hub files — top 5 by in-degree (most imported)
    sorted_by_indegree = sorted(nodes, key=lambda n: in_degree.get(n["id"], 0), reverse=True)
    hubs = [
        {
            "path":       n["path"],
            "in_degree":  in_degree.get(n["id"], 0),
            "out_degree": out_degree.get(n["id"], 0),
            "tokens":     n.get("tokens", 0),
            "complexity": n.get("complexity", 0),
        }
        for n in sorted_by_indegree[:5]
        if in_degree.get(n["id"], 0) > 0
    ]

    # Isolated files — neither imports nor imported
    isolated = [
        n["path"] for n in nodes
        if in_degree.get(n["id"], 0) == 0 and out_degree.get(n["id"], 0) == 0
    ]

    # Leaf files — import nothing (out_degree == 0) but are imported
    leaves = [
        n["path"] for n in nodes
        if out_degree.get(n["id"], 0) == 0 and in_degree.get(n["id"], 0) > 0
    ]

    # Circular dependency detection via DFS
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n["id"]: WHITE for n in nodes}
    cycles_found = 0
    cycle_examples: list[str] = []

    def _dfs(v: int, path: list[int]) -> None:
        nonlocal cycles_found
        color[v] = GRAY
        for w in adjacency.get(v, []):
            if color[w] == GRAY:
                cycles_found += 1
                if len(cycle_examples) < 3:
                    loop_start = path.index(w)
                    cycle_path = [id_to_path.get(x, str(x)) for x in path[loop_start:]] + [id_to_path.get(w, str(w))]
                    cycle_examples.append(" → ".join(cycle_path))
            elif color[w] == WHITE:
                _dfs(w, path + [w])
        color[v] = BLACK

    for n in nodes:
        if color[n["id"]] == WHITE:
            _dfs(n["id"], [n["id"]])

    total_tokens     = sum(n.get("tokens", 0) for n in nodes)
    total_complexity = sum(n.get("complexity", 0) for n in nodes)
    avg_in_degree    = round(sum(in_degree.values()) / max(len(nodes), 1), 2)

    return JSONResponse({
        "total_files":      len(nodes),
        "total_edges":      len(links),
        "avg_in_degree":    avg_in_degree,
        "total_tokens":     total_tokens,
        "total_complexity": total_complexity,
        "hub_count":        len(hubs),
        "hubs":             hubs,
        "isolated_count":   len(isolated),
        "isolated":         isolated[:10],
        "leaf_count":       len(leaves),
        "circular_count":   cycles_found,
        "cycle_examples":   cycle_examples,
    })


@app.get("/_health")
async def health():
    disk     = shutil.disk_usage(RESULTS_DIR)
    free_mb  = disk.free // 1024 // 1024
    total_mb = disk.total // 1024 // 1024
    has_key  = bool(
        os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY") or
        os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY") or
        os.getenv("NVIDIA_API_KEY")
    )
    running  = sum(1 for j in jobs.values() if j["status"] == JobStatus.RUNNING)
    ok = free_mb > 100 and has_key
    return JSONResponse(
        {
            "status":          "ok" if ok else "degraded",
            "disk_free_mb":    free_mb,
            "disk_total_mb":   total_mb,
            "llm_key_present": has_key,
            "jobs_running":    running,
            "jobs_queued":     len(jobs),
        },
        status_code=200 if ok else 503,
    )


@app.get("/results/{job_id}/export.zip")
async def export_zip(job_id: str):
    """Download all output files for a job as a single ZIP archive."""
    job_dir = RESULTS_DIR / job_id
    if not job_dir.exists():
        return JSONResponse({"error": "Job not found"}, status_code=404)

    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in job_dir.iterdir():
            if f.is_file() and f.name != "meta.json":
                zf.write(f, f.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="arkhe-{job_id}.zip"'},
    )


# ── Debug inspector routes (ARKHE_DEBUG=false to remove) ─────────────────────

def _debug_guard():
    if not DEBUG_MODE:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")


@app.get("/debug", response_class=HTMLResponse)
async def debug_index(request: Request):
    """List all jobs currently on disk."""
    _debug_guard()
    all_jobs = []
    for job_dir in sorted(RESULTS_DIR.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
        if not job_dir.is_dir():
            continue
        job_id = job_dir.name
        job = jobs.get(job_id) or _reconstruct_job_from_disk(job_id)
        if job:
            all_jobs.append({"job_id": job_id, "url": job.get("url", ""), "status": job.get("status", "?")})
    return templates.TemplateResponse(request, "debug_index.html", {"jobs": all_jobs})


@app.get("/debug/{job_id}", response_class=HTMLResponse)
async def debug_job(request: Request, job_id: str):
    """Full inspector: all output files + every graph node with blast radius link."""
    _debug_guard()
    job_dir = RESULTS_DIR / job_id
    if not job_dir.exists():
        return HTMLResponse("<h2>Job not found.</h2>", status_code=404)

    job = jobs.get(job_id) or _reconstruct_job_from_disk(job_id)

    # Collect all readable output files
    output_sections = []
    for filename, label, kind in OUTPUT_FILES:
        path = job_dir / filename
        if not path.exists():
            continue
        if kind in ("markdown", "json"):
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = "(unreadable)"
        elif kind == "html":
            content = f"[HTML file — open /results/{job_id}/view/{filename}]"
        elif kind == "docx":
            content = f"[DOCX file — download at /results/{job_id}/{filename}]"
        else:
            content = f"[Binary file — {kind}]"
        output_sections.append({"filename": filename, "label": label, "kind": kind, "content": content})

    # Load graph nodes for blast-radius list
    graph_nodes = []
    grp_path = job_dir / "GRAPH.json"
    if grp_path.exists():
        try:
            g = json.loads(grp_path.read_text())
            graph_nodes = sorted(
                [{"path": n["path"], "tokens": n.get("tokens", 0), "complexity": n.get("complexity", 0)}
                 for n in g.get("nodes", [])],
                key=lambda n: n["path"]
            )
        except Exception:
            pass

    # Read server.log tail (last 200 lines)
    log_tail = ""
    log_path = SERVER_DIR / "server.log"
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            log_tail = "\n".join(lines[-200:])
        except Exception:
            log_tail = "(unreadable)"

    return templates.TemplateResponse(request, "debug_job.html", {
        "job_id":        job_id,
        "job_url":       (job or {}).get("url", ""),
        "output_sections": output_sections,
        "graph_nodes":   graph_nodes,
        "log_tail":      log_tail,
    })
