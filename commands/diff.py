"""
arkhe diff <repo_path>

Compares the current state of a repo against the last saved Arkhe snapshot
(docs/SNAPSHOT.json, written automatically after every successful run).

Shows:
  - Files added / removed since last snapshot
  - Dependencies added / removed
  - Summary counts

No LLM calls — scan + AST parse only (fast, free).
"""
import json
import os
import sys
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

SNAPSHOT_FILE = "SNAPSHOT.json"


def save_snapshot(graph: dict, files: list, repo_path: str) -> None:
    """
    Persist a lightweight snapshot of the current dependency graph.
    Called automatically at the end of every successful `arkhe` run.
    """
    out_dir = os.path.join(repo_path, "docs")
    os.makedirs(out_dir, exist_ok=True)

    id_to_path = {node["id"]: node["path"] for node in graph.get("nodes", [])}
    links = [
        (id_to_path[l["source"]], id_to_path[l["target"]])
        for l in graph.get("links", [])
        if l["source"] in id_to_path and l["target"] in id_to_path
    ]

    snapshot = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "files": sorted(f["path"] for f in files),
        "links": sorted([list(pair) for pair in links]),
    }

    path = os.path.join(out_dir, SNAPSHOT_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)


def _load_snapshot(repo_path: str) -> dict | None:
    path = os.path.join(repo_path, "docs", SNAPSHOT_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_current(repo_path: str) -> dict:
    """Scan + parse the repo without any LLM calls."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts.scan_codebase import scan
    from agents.parser_agent import parse_modules
    from agents.visualizer_agent import build_graph

    files = scan(repo_path)
    modules = parse_modules(files)
    graph = build_graph(modules)

    id_to_path = {node["id"]: node["path"] for node in graph.get("nodes", [])}
    links = sorted([
        [id_to_path[l["source"]], id_to_path[l["target"]]]
        for l in graph.get("links", [])
        if l["source"] in id_to_path and l["target"] in id_to_path
    ])

    return {
        "files": sorted(f["path"] for f in files),
        "links": links,
    }


def run_diff(repo_path: str) -> None:
    repo_path = os.path.abspath(repo_path)

    console.rule("[bold cyan]Arkhe Diff[/bold cyan]")

    snapshot = _load_snapshot(repo_path)
    if snapshot is None:
        console.print(
            "[yellow]No snapshot found.[/yellow] Run [bold]arkhe[/bold] on this repo first "
            "to generate [cyan]docs/SNAPSHOT.json[/cyan]."
        )
        return

    console.print(f"  Snapshot from: [dim]{snapshot['timestamp']}[/dim]")
    console.print("  Scanning current state...\n")

    current = _build_current(repo_path)

    old_files = set(snapshot["files"])
    new_files = set(current["files"])
    added_files   = sorted(new_files - old_files)
    removed_files = sorted(old_files - new_files)

    old_links = {tuple(l) for l in snapshot["links"]}
    new_links = {tuple(l) for l in current["links"]}
    added_links   = sorted(new_links - old_links)
    removed_links = sorted(old_links - new_links)

    # ── Files table ───────────────────────────────────────────────────────────
    if added_files or removed_files:
        t = Table(title="File Changes", box=box.SIMPLE_HEAD, show_header=True)
        t.add_column("Change", style="bold", width=8)
        t.add_column("File")
        for f in added_files:
            t.add_row("[green]+[/green]", f)
        for f in removed_files:
            t.add_row("[red]-[/red]", f)
        console.print(t)
    else:
        console.print("[green]Files:[/green] no changes\n")

    # ── Dependencies table ────────────────────────────────────────────────────
    if added_links or removed_links:
        t = Table(title="Dependency Changes", box=box.SIMPLE_HEAD, show_header=True)
        t.add_column("Change", style="bold", width=8)
        t.add_column("From")
        t.add_column("To")
        for src, tgt in added_links:
            t.add_row("[green]+[/green]", src, tgt)
        for src, tgt in removed_links:
            t.add_row("[red]-[/red]", src, tgt)
        console.print(t)
    else:
        console.print("[green]Dependencies:[/green] no changes\n")

    # ── Summary ───────────────────────────────────────────────────────────────
    console.rule()
    console.print(
        f"Files: [green]+{len(added_files)}[/green] / [red]-{len(removed_files)}[/red]   "
        f"Dependencies: [green]+{len(added_links)}[/green] / [red]-{len(removed_links)}[/red]"
    )

    if not added_files and not removed_files and not added_links and not removed_links:
        console.print("[bold green]No architectural changes since last snapshot.[/bold green]")
