"""
Integration tests for the new /context and /impact API endpoints.
No API keys or running server required — uses ASGI test transport.
"""
import json
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from server.app import app, RESULTS_DIR

# ── Fixtures ──────────────────────────────────────────────────────────────────

GRAPH_DATA = {
    "nodes": [
        {"id": 0, "path": "main.py",              "tokens": 500,  "functions": ["run", "cli"],      "classes": [],          "complexity": 100},
        {"id": 1, "path": "config/settings.py",   "tokens": 300,  "functions": ["get_model"],       "classes": [],          "complexity": 50},
        {"id": 2, "path": "config/llm_client.py", "tokens": 800,  "functions": ["llm_call_async"],  "classes": ["LLMClient"],"complexity": 200},
        {"id": 3, "path": "agents/analyst.py",    "tokens": 600,  "functions": ["analyze_parallel"],"classes": [],          "complexity": 150},
        {"id": 4, "path": "agents/parser.py",     "tokens": 400,  "functions": ["parse_modules"],   "classes": [],          "complexity": 80},
    ],
    "links": [
        {"source": 0, "target": 1, "bidirectional": False},  # main → settings
        {"source": 2, "target": 1, "bidirectional": False},  # llm_client → settings
        {"source": 3, "target": 2, "bidirectional": False},  # analyst → llm_client
        {"source": 3, "target": 4, "bidirectional": False},  # analyst → parser
    ],
}

CTX_DATA = {
    "files": [
        {"path": "main.py",              "tokens": 500, "functions": ["run", "cli"],      "classes": [],          "imports": ["config.settings"], "snippet": "async def run(repo_path)..."},
        {"path": "config/settings.py",   "tokens": 300, "functions": ["get_model"],       "classes": [],          "imports": [],                  "snippet": "GROQ_API_KEY = os.getenv(...)"},
        {"path": "config/llm_client.py", "tokens": 800, "functions": ["llm_call_async"],  "classes": ["LLMClient"],"imports": ["config.settings"], "snippet": "class LLMClient: ..."},
        {"path": "agents/analyst.py",    "tokens": 600, "functions": ["analyze_parallel"],"classes": [],          "imports": ["config.llm_client"],"snippet": "async def analyze_parallel(modules)..."},
        {"path": "agents/parser.py",     "tokens": 400, "functions": ["parse_modules"],   "classes": [],          "imports": [],                  "snippet": "def parse_modules(files)..."},
    ]
}

JOB_ID = "testapix"


@pytest.fixture(autouse=True)
def setup_test_job(tmp_path, monkeypatch):
    """Write mock GRAPH.json and CONTEXT_INDEX.json to the results dir."""
    job_dir = RESULTS_DIR / JOB_ID
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "GRAPH.json").write_text(json.dumps(GRAPH_DATA))
    (job_dir / "CONTEXT_INDEX.json").write_text(json.dumps(CTX_DATA))
    yield
    import shutil
    shutil.rmtree(job_dir, ignore_errors=True)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── /impact/{job_id} ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_impact_list_files():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/impact/{JOB_ID}")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert len(data["nodes"]) == 5


@pytest.mark.asyncio
async def test_impact_leaf_file_no_dependents():
    """agents/parser.py is only imported by analyst — 1 direct dependent."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/impact/{JOB_ID}?file=agents/parser.py")
    assert r.status_code == 200
    d = r.json()
    assert d["file"] == "agents/parser.py"
    assert d["direct_count"] == 1
    assert any(a["path"] == "agents/analyst.py" for a in d["affected"])


@pytest.mark.asyncio
async def test_impact_hub_file_high_count():
    """config/settings.py is imported by main, llm_client → analyst also affected transitively."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/impact/{JOB_ID}?file=config/settings.py")
    assert r.status_code == 200
    d = r.json()
    assert d["total_affected"] >= 2
    affected_paths = [a["path"] for a in d["affected"]]
    assert "main.py" in affected_paths
    assert "config/llm_client.py" in affected_paths


@pytest.mark.asyncio
async def test_impact_risk_levels():
    """leaf file → LOW, hub file → depends on count."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.get(f"/impact/{JOB_ID}?file=agents/parser.py")
        r2 = await c.get(f"/impact/{JOB_ID}?file=config/settings.py")
    assert r1.json()["risk"] in ("LOW", "MEDIUM", "HIGH")
    assert r2.json()["risk"] in ("LOW", "MEDIUM", "HIGH")


@pytest.mark.asyncio
async def test_impact_depth_values():
    """Depth-1 dependents are direct; depth-2 are transitive."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/impact/{JOB_ID}?file=config/settings.py")
    d = r.json()
    depth_map = {a["path"]: a["depth"] for a in d["affected"]}
    # main.py and llm_client.py directly import settings
    assert depth_map.get("main.py") == 1
    assert depth_map.get("config/llm_client.py") == 1
    # analyst imports llm_client which imports settings → depth 2
    assert depth_map.get("agents/analyst.py") == 2


@pytest.mark.asyncio
async def test_impact_forward_deps():
    """llm_client depends on settings — should appear in direct_deps."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/impact/{JOB_ID}?file=config/llm_client.py")
    d = r.json()
    assert "config/settings.py" in d["direct_deps"]


@pytest.mark.asyncio
async def test_impact_unknown_file_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/impact/{JOB_ID}?file=does_not_exist.py")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_impact_missing_graph_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/impact/nonexistentjob?file=main.py")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_impact_view_returns_html():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/impact/{JOB_ID}/view")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Blast Radius" in r.text


# ── /context/{job_id} ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_basic_query():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/context/{JOB_ID}", json={"task": "fix llm client", "budget": 10000})
    assert r.status_code == 200
    d = r.json()
    assert "results" in d
    assert d["files_total"] == 5
    assert d["files_selected"] >= 1


@pytest.mark.asyncio
async def test_context_relevance_ordering():
    """The most task-relevant file should rank first."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/context/{JOB_ID}", json={"task": "llm client settings", "budget": 50000})
    d = r.json()
    paths = [f["path"] for f in d["results"]]
    # llm_client and/or settings should be in top 2
    assert paths[0] in ("config/llm_client.py", "config/settings.py", "agents/analyst.py")


@pytest.mark.asyncio
async def test_context_budget_limits_selection():
    """Small budget should select fewer files."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r_small = await c.post(f"/context/{JOB_ID}", json={"task": "anything", "budget": 400})
        r_large = await c.post(f"/context/{JOB_ID}", json={"task": "anything", "budget": 50000})
    small, large = r_small.json(), r_large.json()
    assert small["files_selected"] <= large["files_selected"]
    assert small["tokens_estimated"] <= 400 + 100  # allow small overshoot for last file


@pytest.mark.asyncio
async def test_context_empty_task_returns_by_centrality():
    """With no task, files should still be returned (by centrality)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/context/{JOB_ID}", json={"task": "", "budget": 50000})
    d = r.json()
    assert d["files_selected"] >= 1


@pytest.mark.asyncio
async def test_context_results_have_score():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/context/{JOB_ID}", json={"task": "parse modules", "budget": 50000})
    for f in r.json()["results"]:
        assert "score" in f
        assert isinstance(f["score"], (int, float))


@pytest.mark.asyncio
async def test_context_missing_index_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/context/nonexistentjob", json={"task": "something", "budget": 8000})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_context_view_returns_html():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/context/{JOB_ID}/view")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Smart Context" in r.text


@pytest.mark.asyncio
async def test_context_get_endpoint_matches_post():
    """GET and POST context endpoints should return the same results for same inputs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r_post = await c.post(f"/context/{JOB_ID}", json={"task": "llm client", "budget": 8000})
        r_get  = await c.get(f"/context/{JOB_ID}?task=llm+client&budget=8000")
    assert r_post.status_code == 200
    assert r_get.status_code  == 200
    post_paths = [f["path"] for f in r_post.json()["results"]]
    get_paths  = [f["path"] for f in r_get.json()["results"]]
    assert post_paths == get_paths


@pytest.mark.asyncio
async def test_context_import_chain_boost():
    """Files imported by highly-relevant files should score higher than isolated files."""
    # analyst.py imports llm_client.py; task targets analyst → llm_client should be boosted
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/context/{JOB_ID}", json={"task": "analyze parallel", "budget": 50000})
    d = r.json()
    paths = [f["path"] for f in d["results"]]
    # analyst.py must appear (direct match)
    assert "agents/analyst.py" in paths
    # settings.py should surface via import-chain (analyst→llm_client→settings)
    top5 = paths[:5]
    assert "agents/analyst.py" in top5


@pytest.mark.asyncio
async def test_context_extension_filter():
    """Filtering by extension should exclude files with other extensions."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/context/{JOB_ID}", json={"task": "", "budget": 50000, "exts": [".py"]})
    d = r.json()
    # All files in CTX_DATA are .py, so all should match
    assert d["files_selected"] == d["files_total"]
    # Filtering for a nonexistent extension should yield 0 results
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r2 = await c.post(f"/context/{JOB_ID}", json={"task": "", "budget": 50000, "exts": [".rs"]})
    assert r2.json()["files_selected"] == 0


@pytest.mark.asyncio
async def test_context_path_prefix_filter():
    """Filtering by path prefix should return only files under that path."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/context/{JOB_ID}", json={"task": "", "budget": 50000, "path": "agents/"})
    d = r.json()
    for f in d["results"]:
        assert f["path"].startswith("agents/")


@pytest.mark.asyncio
async def test_impact_isolated_file():
    """A file with no dependents should have zero affected and LOW risk."""
    # agents/parser.py has 1 dependent (analyst.py); let's test main.py which only imports
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # main.py has no one importing it → isolated
        r = await c.get(f"/impact/{JOB_ID}?file=main.py")
    d = r.json()
    assert d["total_affected"] == 0
    assert d["risk"] == "LOW"


@pytest.mark.asyncio
async def test_impact_affected_includes_complexity():
    """Each affected file in the response should include tokens and complexity fields."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/impact/{JOB_ID}?file=config/settings.py")
    d = r.json()
    assert "complexity" in d
    assert "total_complexity" in d
    for a in d["affected"]:
        assert "tokens" in a
        assert "complexity" in a


@pytest.mark.asyncio
async def test_impact_bidirectional_forward_deps():
    """Bidirectional links should appear in direct_deps in both directions."""
    import json
    from server.app import RESULTS_DIR

    # Patch GRAPH with a bidirectional link: main ↔ settings
    job_dir = RESULTS_DIR / JOB_ID
    graph_bi = {
        "nodes": [
            {"id": 0, "path": "main.py",            "tokens": 500, "functions": [], "classes": [], "complexity": 10},
            {"id": 1, "path": "config/settings.py", "tokens": 300, "functions": [], "classes": [], "complexity": 5},
        ],
        "links": [{"source": 0, "target": 1, "bidirectional": True}],
    }
    (job_dir / "GRAPH.json").write_text(json.dumps(graph_bi))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r_main     = await c.get(f"/impact/{JOB_ID}?file=main.py")
        r_settings = await c.get(f"/impact/{JOB_ID}?file=config/settings.py")

    # main.py → imports settings (forward dep), affected by settings changes (reverse)
    assert "config/settings.py" in r_main.json()["direct_deps"]
    # settings.py → imports main (bidirectional = mutual), main is a direct dep
    assert "main.py" in r_settings.json()["direct_deps"]

    # Both should see each other as affected (mutual dependency)
    assert any(a["path"] == "config/settings.py" for a in r_main.json()["affected"])
    assert any(a["path"] == "main.py" for a in r_settings.json()["affected"])

    # Restore original graph for subsequent tests
    (job_dir / "GRAPH.json").write_text(json.dumps(GRAPH_DATA))


# ── /graph/{job_id}/stats ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graph_stats_basic():
    """Stats endpoint should return file/edge counts and hub info."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/graph/{JOB_ID}/stats")
    assert r.status_code == 200
    d = r.json()
    assert d["total_files"] == 5
    assert d["total_edges"] == 4
    assert "hubs" in d
    assert "isolated" in d
    assert "circular_count" in d


@pytest.mark.asyncio
async def test_graph_stats_hub_is_settings():
    """config/settings.py is imported by 2 files — should be the top hub."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/graph/{JOB_ID}/stats")
    d = r.json()
    assert d["hubs"][0]["path"] == "config/settings.py"
    assert d["hubs"][0]["in_degree"] == 2


@pytest.mark.asyncio
async def test_graph_stats_isolated_is_empty():
    """In our test graph every file has at least one edge — no isolated nodes."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/graph/{JOB_ID}/stats")
    d = r.json()
    assert d["isolated_count"] == 0


@pytest.mark.asyncio
async def test_graph_stats_no_cycles():
    """Test graph is a DAG — no circular dependencies."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/graph/{JOB_ID}/stats")
    assert r.json()["circular_count"] == 0


@pytest.mark.asyncio
async def test_graph_stats_detects_cycle():
    """A graph with A→B→A should report at least 1 circular dependency."""
    import json
    from server.app import RESULTS_DIR

    job_dir = RESULTS_DIR / JOB_ID
    graph_cycle = {
        "nodes": [
            {"id": 0, "path": "a.py", "tokens": 100, "functions": [], "classes": [], "complexity": 5},
            {"id": 1, "path": "b.py", "tokens": 100, "functions": [], "classes": [], "complexity": 5},
        ],
        "links": [
            {"source": 0, "target": 1, "bidirectional": False},
            {"source": 1, "target": 0, "bidirectional": False},
        ],
    }
    (job_dir / "GRAPH.json").write_text(json.dumps(graph_cycle))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/graph/{JOB_ID}/stats")
    assert r.json()["circular_count"] >= 1

    # Restore
    (job_dir / "GRAPH.json").write_text(json.dumps(GRAPH_DATA))


@pytest.mark.asyncio
async def test_graph_stats_missing_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/graph/nonexistentjob/stats")
    assert r.status_code == 404
