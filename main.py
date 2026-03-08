"""
Arkhe — Autonomous codebase intelligence.
Usage: python main.py [repo_path] [--format json]
"""
import argparse
import asyncio
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from scripts.scan_codebase    import scan
from agents.parser_agent      import parse_modules
from agents.analyst_agent     import analyze_parallel
from agents.synthesizer_agent import synthesize
from agents.visualizer_agent  import build_graph, visualize, write_visualizer
from agents.report_agent      import generate_report
from agents.refactor_agent    import refactor_all
from output.map_writer        import write_map, write_json_map
from output.report_writer     import write_report
from output.clone_writer      import write_clone
from cache.pipeline_cache     import compute_fingerprint, load_stage, save_stage

console = Console()


async def run(repo_path: str, fmt: str, refactor: bool = False):
    from config.settings import REFACTOR_ENABLED
    refactor = refactor or REFACTOR_ENABLED
    console.rule("[bold cyan]Arkhe[/bold cyan] — Codebase Intelligence")

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:

        t = p.add_task("Computing repo fingerprint...", total=None)
        fingerprint = compute_fingerprint(repo_path)
        p.update(t, description="[green]Fingerprint ready[/green]", completed=True)

        # ── Scan ──────────────────────────────────────────────────────────────
        t = p.add_task("Scanning repository...", total=None)
        files = load_stage(repo_path, "scan", fingerprint)
        if files is None:
            files = scan(repo_path)
            save_stage(repo_path, "scan", fingerprint, files)
            p.update(t, description=f"[green]Scanned {len(files)} files[/green]", completed=True)
        else:
            p.update(t, description=f"[green]Scan loaded from cache ({len(files)} files)[/green]", completed=True)

        # ── Parse ─────────────────────────────────────────────────────────────
        t = p.add_task("Parsing AST structure...", total=None)
        modules = load_stage(repo_path, "parse", fingerprint)
        if modules is None:
            modules = parse_modules(files)
            save_stage(repo_path, "parse", fingerprint, modules)
            p.update(t, description=f"[green]Parsed {len(modules)} modules[/green]", completed=True)
        else:
            p.update(t, description=f"[green]Parse loaded from cache ({len(modules)} modules)[/green]", completed=True)

        # ── Refactor (optional) ───────────────────────────────────────────────
        if refactor:
            t = p.add_task("Refactoring files (doc + style pass)...", total=None)
            refactored = await refactor_all(modules)
            clone_path = write_clone(repo_path, refactored)
            p.update(
                t,
                description=f"[green]Refactored {len(refactored)} files → {clone_path}[/green]",
                completed=True,
            )

        # ── Analyze ───────────────────────────────────────────────────────────
        t = p.add_task("Analyzing with AI subagents...", total=None)
        reports = load_stage(repo_path, "analyze", fingerprint)
        if reports is None:
            reports = await analyze_parallel(modules)
            save_stage(repo_path, "analyze", fingerprint, reports)
            p.update(t, description=f"[green]{len(reports)} agent report(s) complete[/green]", completed=True)
        else:
            p.update(t, description=f"[green]Analysis loaded from cache ({len(reports)} report(s))[/green]", completed=True)

        # ── Synthesize ────────────────────────────────────────────────────────
        t = p.add_task("Synthesizing final map...", total=None)
        codebase_map = await synthesize(reports, files)
        p.update(t, description="[green]Map synthesized[/green]", completed=True)

        # ── Output ────────────────────────────────────────────────────────────
        graph = build_graph(modules)

        if fmt == "json":
            t = p.add_task("Writing JSON output...", total=None)
            out_path = write_json_map(codebase_map, graph, files, reports, repo_path)
            p.update(t, description=f"[green]Written to {out_path}[/green]", completed=True)

            console.rule()
            console.print(f"[bold green]Arkhe complete.[/bold green]")
            console.print(f"  JSON output -> [cyan]{out_path}[/cyan]")

        else:
            t = p.add_task("Generating dependency visualization...", total=None)
            viz_path = write_visualizer(graph, repo_path)
            p.update(t, description="[green]Visualization ready[/green]", completed=True)

            t = p.add_task("Writing output...", total=None)
            map_path = write_map(codebase_map, repo_path)
            p.update(t, description=f"[green]Written to {map_path}[/green]", completed=True)

            t = p.add_task("Generating executive report...", total=None)
            report_text, rp, rm = await generate_report(
                codebase_map, files, reports, graph, repo_path
            )
            report_path = write_report(report_text, repo_path)
            p.update(
                t,
                description=f"[green]Report written ({rp}/{rm})[/green]",
                completed=True,
            )

            console.rule()
            console.print(f"[bold green]Arkhe complete.[/bold green]")
            console.print(f"  Codebase map     -> [cyan]{map_path}[/cyan]")
            console.print(f"  Dependency map   -> [cyan]{viz_path}[/cyan]")
            console.print(f"  Executive report -> [cyan]{report_path}[/cyan]")
            if refactor:
                console.print(f"  Refactored clone -> [cyan]{clone_path}[/cyan]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="arkhe",
        description="Autonomous codebase intelligence — AI-generated maps and dependency graphs.",
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="Path to the repository to analyze (default: current directory)",
    )
    parser.add_argument(
        "--format",
        choices=["default", "json"],
        default="default",
        dest="fmt",
        help="Output format: 'default' writes CODEBASE_MAP.md + DEPENDENCY_MAP.html, "
             "'json' writes a single CODEBASE_MAP.json with all data",
    )
    parser.add_argument(
        "--refactor",
        action="store_true",
        default=False,
        help="Generate a refactored clone of the repo with improved documentation and "
             "idiomatic code style. Output written to <repo>_refactored/ sibling directory. "
             "Original files are never modified.",
    )
    args = parser.parse_args()
    asyncio.run(run(args.repo, args.fmt, args.refactor))
