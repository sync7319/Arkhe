"""
Arkhe — Autonomous codebase intelligence.
Usage: python main.py [repo_path] [--format json]

Feature toggles live in options.env.
API keys and provider selection live in .env.
"""
import argparse
import asyncio
import os
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from scripts.scan_codebase    import scan
from agents.parser_agent      import parse_modules
from agents.analyst_agent     import analyze_parallel
from agents.synthesizer_agent import synthesize
from agents.visualizer_agent  import build_graph, write_visualizer
from agents.report_agent      import generate_report
from agents.refactor_agent    import refactor_all
from agents.impact_agent      import analyze_impact, format_impact_report
from agents.security_agent    import run_security_audit
from agents.dead_code_agent   import detect_dead_code, format_dead_code_report
from agents.test_gap_agent    import find_coverage_gaps, format_test_gap_report, generate_scaffolds
from output.map_writer        import write_map, write_json_map
from output.report_writer     import write_report
from output.clone_writer      import write_clone
from cache.db                 import init_db
from config.model_router      import restore_from_db
from commands.diff            import save_snapshot

console = Console()


def _write_md(content: str, repo_path: str, filename: str) -> str:
    out_dir = os.path.join(repo_path, "docs")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _write_scaffolds(scaffolds: dict[str, str], repo_path: str) -> list[str]:
    out_dir = os.path.join(repo_path, "tests_generated")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for source_path, content in scaffolds.items():
        stem     = os.path.splitext(os.path.basename(source_path))[0]
        out_path = os.path.join(out_dir, f"test_{stem}.py")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        written.append(out_path)
    return written


async def run(repo_path: str, fmt: str, refactor: bool = False):
    from config.settings import (
        REFACTOR_ENABLED,
        CODEBASE_MAP_ENABLED, DEPENDENCY_MAP_ENABLED, EXECUTIVE_REPORT_ENABLED,
        PR_ANALYSIS_ENABLED, PR_BASE_BRANCH,
        SECURITY_AUDIT_ENABLED, DEAD_CODE_DETECTION_ENABLED,
        TEST_GAP_ANALYSIS_ENABLED, TEST_SCAFFOLDING_ENABLED,
        COMPLEXITY_HEATMAP_ENABLED,
    )
    refactor = refactor or REFACTOR_ENABLED
    console.rule("[bold cyan]Arkhe[/bold cyan] — Codebase Intelligence")

    db = init_db(repo_path)
    restore_from_db(db)   # load persisted cooldowns; reset if new calendar day

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:

        # ── Scan ──────────────────────────────────────────────────────────────
        t = p.add_task("Scanning repository...", total=None)
        files = scan(repo_path)
        p.update(t, description=f"[green]Scanned {len(files)} files[/green]", completed=True)

        # ── Parse ─────────────────────────────────────────────────────────────
        t = p.add_task("Parsing AST structure...", total=None)
        modules = parse_modules(files)
        p.update(t, description=f"[green]Parsed {len(modules)} modules[/green]", completed=True)

        # ── Refactor (optional) ───────────────────────────────────────────────
        clone_path = None
        if refactor:
            t = p.add_task("Refactoring files (doc + style pass)...", total=None)
            refactored = await refactor_all(modules)
            clone_path = write_clone(repo_path, refactored)
            p.update(t, description=f"[green]Refactored {len(refactored)} files → {clone_path}[/green]", completed=True)

        # ── Analyze ───────────────────────────────────────────────────────────
        t = p.add_task("Analyzing with AI subagents...", total=None)
        reports = await analyze_parallel(modules)
        p.update(t, description=f"[green]{len(reports)} file(s) analyzed[/green]", completed=True)

        # ── Synthesize ────────────────────────────────────────────────────────
        t = p.add_task("Synthesizing final map...", total=None)
        codebase_map = await synthesize(reports, files)
        p.update(t, description="[green]Map synthesized[/green]", completed=True)

        # ── Build dependency graph ────────────────────────────────────────────
        graph = build_graph(modules)

        # ── JSON format exit ─────────────────────────────────────────────────
        if fmt == "json":
            t = p.add_task("Writing JSON output...", total=None)
            out_path = write_json_map(codebase_map, graph, files, reports, repo_path)
            p.update(t, description=f"[green]Written to {out_path}[/green]", completed=True)
            console.rule()
            console.print(f"[bold green]Arkhe complete.[/bold green]")
            console.print(f"  JSON output -> [cyan]{out_path}[/cyan]")
            return

        # ── Static analyses (zero LLM cost) ──────────────────────────────────
        dead_code_report = test_gap_coverage = None

        if DEAD_CODE_DETECTION_ENABLED:
            t = p.add_task("Detecting dead code...", total=None)
            result      = detect_dead_code(modules)
            dead_path   = _write_md(format_dead_code_report(result), repo_path, "DEAD_CODE_REPORT.md")
            dead_code_report = dead_path
            p.update(t, description=f"[green]Dead code: {result['total_dead']} symbols flagged → {dead_path}[/green]", completed=True)

        if TEST_GAP_ANALYSIS_ENABLED:
            t = p.add_task("Analysing test coverage gaps...", total=None)
            coverage         = find_coverage_gaps(modules)
            gap_path         = _write_md(format_test_gap_report(coverage), repo_path, "TEST_GAP_REPORT.md")
            test_gap_coverage = coverage
            pct = coverage["stats"]["pct_covered"]
            p.update(t, description=f"[green]Test gap: {pct}% covered → {gap_path}[/green]", completed=True)

            if TEST_SCAFFOLDING_ENABLED and coverage["gaps"]:
                t = p.add_task("Generating test scaffolds...", total=None)
                scaffolds   = await generate_scaffolds(modules, coverage["gaps"])
                scaffold_paths = _write_scaffolds(scaffolds, repo_path)
                p.update(t, description=f"[green]{len(scaffold_paths)} scaffold(s) written → tests_generated/[/green]", completed=True)

        # ── LLM-powered optional analyses ─────────────────────────────────────
        security_path = impact_path = None

        if SECURITY_AUDIT_ENABLED:
            t = p.add_task("Running security audit...", total=None)
            try:
                audit_text  = await run_security_audit(modules)
                security_path = _write_md(audit_text, repo_path, "SECURITY_REPORT.md")
                p.update(t, description=f"[green]Security report → {security_path}[/green]", completed=True)
            except Exception as e:
                p.update(t, description=f"[yellow]Security audit skipped — {str(e)[:80]}[/yellow]", completed=True)

        if PR_ANALYSIS_ENABLED:
            t = p.add_task(f"Analysing PR impact vs {PR_BASE_BRANCH}...", total=None)
            try:
                impact = await analyze_impact(modules, graph, reports, repo_path, PR_BASE_BRANCH)
                if impact:
                    impact_path = _write_md(format_impact_report(impact), repo_path, "PR_IMPACT.md")
                    p.update(t, description=f"[green]Impact: {len(impact['changed'])} changed, {sum(len(v) for v in impact['affected'].values())} affected → {impact_path}[/green]", completed=True)
                else:
                    p.update(t, description="[yellow]No changed files detected vs base branch[/yellow]", completed=True)
            except Exception as e:
                p.update(t, description=f"[yellow]PR analysis skipped — {str(e)[:80]}[/yellow]", completed=True)

        # ── Core outputs ──────────────────────────────────────────────────────
        map_path = viz_path = report_path = None

        if CODEBASE_MAP_ENABLED:
            t = p.add_task("Writing codebase map...", total=None)
            map_path = write_map(codebase_map, repo_path)
            p.update(t, description=f"[green]Written to {map_path}[/green]", completed=True)

        if DEPENDENCY_MAP_ENABLED:
            t = p.add_task("Generating dependency visualization...", total=None)
            viz_path = write_visualizer(graph, repo_path, heatmap=COMPLEXITY_HEATMAP_ENABLED)
            heat_tag = " + heatmap" if COMPLEXITY_HEATMAP_ENABLED else ""
            p.update(t, description=f"[green]Visualization ready{heat_tag}[/green]", completed=True)

        if EXECUTIVE_REPORT_ENABLED:
            t = p.add_task("Generating executive report...", total=None)
            try:
                report_text, rp, rm = await generate_report(codebase_map, files, reports, graph, repo_path)
                report_path = write_report(report_text, repo_path)
                p.update(t, description=f"[green]Report written ({rp}/{rm})[/green]", completed=True)
            except Exception as e:
                msg = str(e).split("\n")[0][:120]
                p.update(t, description=f"[yellow]Report skipped — {msg}[/yellow]", completed=True)

    # ── Summary ───────────────────────────────────────────────────────────────
    console.rule()
    console.print(f"[bold green]Arkhe complete.[/bold green]")
    if map_path:
        console.print(f"  Codebase map      -> [cyan]{map_path}[/cyan]")
    if viz_path:
        console.print(f"  Dependency map    -> [cyan]{viz_path}[/cyan]")
    if report_path:
        console.print(f"  Executive report  -> [cyan]{report_path}[/cyan]")
    if clone_path:
        console.print(f"  Refactored clone  -> [cyan]{clone_path}[/cyan]")
    if dead_code_report:
        console.print(f"  Dead code report  -> [cyan]{dead_code_report}[/cyan]")
    if test_gap_coverage:
        console.print(f"  Test gap report   -> [cyan]{os.path.join(repo_path, 'docs', 'TEST_GAP_REPORT.md')}[/cyan]")
    if security_path:
        console.print(f"  Security report   -> [cyan]{security_path}[/cyan]")
    if impact_path:
        console.print(f"  PR impact report  -> [cyan]{impact_path}[/cyan]")

    # ── Save snapshot for `arkhe diff` ────────────────────────────────────────
    save_snapshot(graph, files, repo_path)


def cli():
    """Entry point for `arkhe` CLI command (installed via pip)."""
    _main()


def _main():
    import sys

    # ── Subcommand dispatch ───────────────────────────────────────────────────
    if len(sys.argv) > 1 and sys.argv[1] in ("diff", "watch"):
        subcmd = sys.argv[1]
        sub_args = sys.argv[2:]
        repo = sub_args[0] if sub_args else "."

        if subcmd == "diff":
            from commands.diff import run_diff
            run_diff(repo)
        elif subcmd == "watch":
            from commands.watch import run_watch
            run_watch(repo)
        return

    # ── Default: analyze ──────────────────────────────────────────────────────
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


if __name__ == "__main__":
    _main()
