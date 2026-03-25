"""
PR Impact Agent — traces the blast radius of changed files.

Diffs HEAD against a base branch to find changed files, then walks the
dependency graph in REVERSE (transitively, via NetworkX) to find every file
that directly or indirectly imports them.
An LLM then writes a plain-English summary of what changed and why it matters.

Output: docs/PR_IMPACT.md
Requires: git history in the target repo.
"""
import logging
import os
import subprocess

from config.llm_client import llm_call_async

logger = logging.getLogger("arkhe.impact")

SYSTEM = """You are a senior software engineer reviewing a pull request.
Given changed files and their downstream dependents, write a concise impact summary:

1. **What changed** — 1-2 sentences per changed file based on the analysis provided
2. **Downstream impact** — which modules depend on the changed files and could be affected
3. **Risk level** — LOW / MEDIUM / HIGH with a one-line justification

Be specific and concrete. No filler. Use markdown."""


def _get_changed_files(repo_path: str, base_branch: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_branch, "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            logger.warning(f"[impact] git diff failed: {result.stderr.strip()}")
            return []
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except Exception as e:
        logger.warning(f"[impact] could not get changed files: {e}")
        return []


def _build_nx_graph(graph: dict):
    """
    Build a NetworkX DiGraph from Arkhe's graph dict.
    Edge direction: source → target (source imports target).
    Returns (G, id_to_path) or (None, {}) if networkx is unavailable.
    """
    try:
        import networkx as nx
    except ImportError:
        return None, {}

    id_to_path = {n["id"]: n["path"] for n in graph.get("nodes", [])}
    G = nx.DiGraph()

    for n in graph.get("nodes", []):
        G.add_node(n["path"])

    for link in graph.get("links", []):
        src = id_to_path.get(link["source"], "")
        tgt = id_to_path.get(link["target"], "")
        if src and tgt:
            G.add_edge(src, tgt)
            if link.get("bidirectional"):
                G.add_edge(tgt, src)

    return G, id_to_path


def _build_reverse_map(graph: dict) -> dict[str, list[str]]:
    """Fallback: hand-rolled 1-level reverse map (used if networkx unavailable)."""
    id_to_path = {n["id"]: n["path"] for n in graph.get("nodes", [])}
    reverse: dict[str, list[str]] = {}
    for link in graph.get("links", []):
        target = id_to_path.get(link["target"], "")
        source = id_to_path.get(link["source"], "")
        if target and source:
            reverse.setdefault(target, []).append(source)
    return reverse


async def analyze_impact(
    modules: list[dict],
    graph: dict,
    reports: list[dict],
    repo_path: str,
    base_branch: str = "main",
) -> "dict | None":
    changed = _get_changed_files(repo_path, base_branch)
    if not changed:
        logger.info("[impact] no changed files detected — skipping")
        return None

    # Build NetworkX graph for transitive dependency traversal
    G, _ = _build_nx_graph(graph)

    if G is not None:
        import networkx as nx
        # Reverse graph: edges point from dependency → importer
        G_rev = G.reverse()
        affected: dict[str, list[str]] = {}
        for f in changed:
            if f in G_rev:
                # nx.descendants = all transitively reachable nodes (full blast radius)
                dependents = list(nx.descendants(G_rev, f))
            else:
                dependents = []
            affected[f] = dependents
        logger.info(f"[impact] NetworkX transitive walk: {sum(len(v) for v in affected.values())} total affected")
    else:
        # Fallback: 1-level reverse map
        logger.warning("[impact] networkx not available — using 1-level reverse map")
        reverse  = _build_reverse_map(graph)
        affected = {f: reverse.get(f, []) for f in changed}

    path_to_analysis = {p: r["analysis"] for r in reports for p in r.get("files", [])}

    context_parts = []
    for f in changed:
        analysis    = path_to_analysis.get(f, "No analysis available.")
        importers   = affected.get(f, [])
        importer_str = ", ".join(importers[:10]) if importers else "none"
        if len(importers) > 10:
            importer_str += f" (+{len(importers) - 10} more)"
        context_parts.append(
            f"**{f}** (imported by {len(importers)} file(s): {importer_str})\n{analysis[:500]}"
        )

    prompt = (
        f"Repository: {os.path.basename(repo_path)}\n"
        f"Base branch: {base_branch}\n"
        f"Changed files ({len(changed)}): {', '.join(changed)}\n\n"
        + "\n\n---\n\n".join(context_parts)
    )

    summary = await llm_call_async("report", SYSTEM, prompt, max_tokens=1024)
    return {"changed": changed, "affected": affected, "summary": summary}


def format_impact_report(result: dict) -> str:
    changed  = result["changed"]
    affected = result["affected"]
    summary  = result["summary"]

    all_affected = sorted({f for fns in affected.values() for f in fns} - set(changed))

    lines = [
        "# PR Impact Analysis\n",
        f"**Changed files:** {len(changed)}  ",
        f"**Downstream files affected:** {len(all_affected)}\n",
        "## Changed Files\n",
        *[f"- `{f}`" for f in changed],
        "\n## Downstream Impact\n",
    ]

    if all_affected:
        lines += [f"- `{f}`" for f in all_affected]
    else:
        lines.append("_No downstream dependents — isolated change._")

    lines += ["\n## Analysis\n", summary]
    return "\n".join(lines) + "\n"
