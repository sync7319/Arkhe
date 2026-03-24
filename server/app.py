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
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(Path(__file__).parent / "server.log"), mode="w"),
    ],
)
logging.getLogger("arkhe.llm").setLevel(logging.DEBUG)
logging.getLogger("arkhe.router").setLevel(logging.DEBUG)
logging.getLogger("arkhe.analyst").setLevel(logging.DEBUG)
logging.getLogger("arkhe.dispatcher").setLevel(logging.DEBUG)

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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    return templates.TemplateResponse(request, "pricing.html")


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
    return templates.TemplateResponse(request, "results.html", {
        "job_id": job_id,
        "job":    job,
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

    def score_file(f: dict) -> float:
        sym_words = _symbol_words(f)
        snippet   = (f.get("snippet") or "").lower()

        if task_words:
            exact     = len(task_words & sym_words) * 3.0
            # Partial: for each task word, credit 0.5 if it partially matches ANY symbol word
            # (capped at 1 match per task word to prevent inflation from files with many symbols)
            partial   = sum(0.5 for tw in task_words if any(tw in w or w in tw for w in sym_words))
            phrase    = sum(2.0 for bg in task_bigrams if bg in (f["path"].lower() + " " + snippet))
            snip_hits = sum(1 for tw in task_words if tw in snippet) * 1.0
            kw_score  = exact + partial + phrase + snip_hits
        else:
            kw_score = 0.0

        central = math.log1p(centrality.get(f["path"], 0)) * 2.0
        return kw_score + central

    raw_scores = {f["path"]: score_file(f) for f in files}

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
    selected   = []
    tokens_used = 0
    for score, f in scored:
        if tokens_used >= budget:
            break
        ft = max(f.get("tokens", 100), 1)
        tokens_used += ft
        selected.append({"score": round(score, 2), **f})

    # Truncate snippets proportionally if over budget
    total_tokens = sum(max(f.get("tokens", 100), 1) for f in selected)
    if total_tokens > budget and selected:
        scale = budget / total_tokens
        for f in selected:
            snippet = f.get("snippet", "")
            f["snippet"] = snippet[:int(len(snippet) * scale)]

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
    return {"status": "ok"}
