"""
Arkhe — Autonomous codebase intelligence.
Usage: python main.py [repo_path] [--format json]

Feature toggles live in options.env.
API keys and provider selection live in .env.

Pipeline (optimized for minimum LLM idle time):
  Phase 1 — Scan + Parse (sequential, no choice)
  Phase 2 — Static work right after parse (graph, dead code, test gap — zero LLM cost,
             all complete in <1s. No reason to wait until after synthesis.)
  Phase 3 — Analyze (LLM, all files concurrent via dispatcher)
  Phase 4 — Synthesize + Security + PR analysis + Scaffolds (all concurrent)
  Phase 5 — Executive report (needs codebase_map from Phase 4)
  Phase 6 — Write outputs + save snapshot
"""
import argparse
import asyncio
import os
import sys

# Force UTF-8 output on Windows to avoid cp1252 encoding errors with Rich spinners
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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


def _write_json(data: dict, repo_path: str, filename: str) -> str:
    import json
    out_dir = os.path.join(repo_path, "docs")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
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


async def run(repo_path: str, fmt: str, refactor: bool = False, progress_cb=None):
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

    from config.settings import GROQ_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, NVIDIA_API_KEY
    from config.model_router import build_available_pools
    build_available_pools({
        "groq":      GROQ_API_KEY,
        "gemini":    GEMINI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "openai":    OPENAI_API_KEY,
        "nvidia":    NVIDIA_API_KEY,
    })

    from config.dispatcher import start_dispatcher
    await start_dispatcher()

    def _progress(step: int, label: str):
        if progress_cb:
            progress_cb(step, label)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:

        # ── Phase 1: Scan ─────────────────────────────────────────────────────
        _progress(1, "Scanning files...")
        t = p.add_task("Scanning repository...", total=None)
        files = scan(repo_path)
        p.update(t, description=f"[green]Scanned {len(files)} files[/green]", completed=True)

        # ── Phase 1: Parse ────────────────────────────────────────────────────
        _progress(2, "Parsing AST structure...")
        t = p.add_task("Parsing AST structure...", total=None)
        modules = parse_modules(files)
        p.update(t, description=f"[green]Parsed {len(modules)} modules[/green]", completed=True)

        # ── Refactor (optional, must happen before analysis to use refactored content) ─
        clone_path = None
        if refactor:
            t = p.add_task("Refactoring files (doc + style pass)...", total=None)
            refactored = await refactor_all(modules)
            clone_path = write_clone(repo_path, refactored)
            p.update(t, description=f"[green]Refactored {len(refactored)} files → {clone_path}[/green]", completed=True)

        # ── Phase 2: Static work — immediately after parse, zero LLM cost ────
        # build_graph, GRAPH.json, CONTEXT_INDEX.json, dead code, test gap all
        # only need `modules`. Running them NOW (before analyze) means:
        #   • blast radius / context picker are available as soon as the job ends
        #   • static reports don't queue behind the LLM analyze + synthesize wait
        _progress(3, "Building graph & static analyses...")

        t_graph = p.add_task("Building dependency graph...", total=None)
        graph = build_graph(modules)
        _write_json(graph, repo_path, "GRAPH.json")
        context_index = {
            "files": [
                {
                    "path":      m["path"].replace("\\", "/"),
                    "tokens":    m.get("tokens", 0),
                    "functions": m.get("structure", {}).get("functions", []),
                    "classes":   m.get("structure", {}).get("classes", []),
                    "imports":   m.get("structure", {}).get("imports", []),
                    "snippet":   m.get("content", "")[:1500],
                }
                for m in modules
            ]
        }
        _write_json(context_index, repo_path, "CONTEXT_INDEX.json")
        p.update(t_graph, description="[green]Dependency graph built + saved[/green]", completed=True)

        dead_code_result = test_gap_coverage = None

        if DEAD_CODE_DETECTION_ENABLED:
            t = p.add_task("Detecting dead code...", total=None)
            dead_code_result = detect_dead_code(modules)
            dead_path = _write_md(format_dead_code_report(dead_code_result), repo_path, "DEAD_CODE_REPORT.md")
            p.update(t, description=f"[green]Dead code: {dead_code_result['total_dead']} symbols flagged[/green]", completed=True)

        if TEST_GAP_ANALYSIS_ENABLED:
            t = p.add_task("Analysing test coverage gaps...", total=None)
            test_gap_coverage = find_coverage_gaps(modules)
            _write_md(format_test_gap_report(test_gap_coverage), repo_path, "TEST_GAP_REPORT.md")
            pct = test_gap_coverage["stats"]["pct_covered"]
            p.update(t, description=f"[green]Test gap: {pct}% covered[/green]", completed=True)

        # ── Phase 3: LLM analysis (main bottleneck — all files concurrent) ────
        _progress(4, "Analyzing with AI...")
        t = p.add_task("Analyzing with AI subagents...", total=None)
        reports = await analyze_parallel(modules)
        p.update(t, description=f"[green]{len(reports)} file(s) analyzed[/green]", completed=True)

        # ── JSON format exit (early, before synthesis) ────────────────────────
        if fmt == "json":
            t = p.add_task("Writing JSON output...", total=None)
            out_path = write_json_map({}, graph, files, reports, repo_path)
            p.update(t, description=f"[green]Written to {out_path}[/green]", completed=True)
            console.rule()
            console.print(f"[bold green]Arkhe complete.[/bold green]")
            console.print(f"  JSON output -> [cyan]{out_path}[/cyan]")
            return

        # ── Phase 4: Concurrent LLM tasks ─────────────────────────────────────
        # Synthesize, security audit, PR analysis, and test scaffolds all run
        # at the same time. The dispatcher shares the NVIDIA/Groq/Gemini capacity
        # across all of them — zero idle time while one waits for another.
        _progress(5, "Synthesizing + parallel analyses...")

        t_synth = p.add_task("Synthesizing codebase map...", total=None)
        t_sec   = p.add_task("Running security audit...", total=None) if SECURITY_AUDIT_ENABLED else None
        t_pr    = p.add_task(f"Analysing PR impact vs {PR_BASE_BRANCH}...", total=None) if PR_ANALYSIS_ENABLED else None
        has_scaffolds = TEST_SCAFFOLDING_ENABLED and test_gap_coverage and test_gap_coverage.get("gaps")
        t_scaf  = p.add_task("Generating test scaffolds...", total=None) if has_scaffolds else None

        async def _do_synthesize():
            return await synthesize(reports, files)

        async def _do_security():
            if not SECURITY_AUDIT_ENABLED:
                return None
            try:
                return await run_security_audit(modules)
            except Exception as e:
                return e

        async def _do_pr():
            if not PR_ANALYSIS_ENABLED:
                return None
            try:
                return await analyze_impact(modules, graph, reports, repo_path, PR_BASE_BRANCH)
            except Exception as e:
                return e

        async def _do_scaffolds():
            if not has_scaffolds:
                return {}
            try:
                return await generate_scaffolds(modules, test_gap_coverage["gaps"])
            except Exception as e:
                return e

        synth_res, sec_res, pr_res, scaf_res = await asyncio.gather(
            _do_synthesize(),
            _do_security(),
            _do_pr(),
            _do_scaffolds(),
            return_exceptions=True,
        )

        # Unpack synthesis
        if isinstance(synth_res, Exception):
            p.update(t_synth, description=f"[red]Synthesis failed — {str(synth_res)[:80]}[/red]", completed=True)
            raise synth_res
        codebase_map = synth_res
        p.update(t_synth, description="[green]Map synthesized[/green]", completed=True)

        # Unpack security
        security_path = None
        if SECURITY_AUDIT_ENABLED:
            if isinstance(sec_res, Exception):
                p.update(t_sec, description=f"[yellow]Security audit skipped — {str(sec_res)[:80]}[/yellow]", completed=True)
            elif sec_res:
                security_path = _write_md(sec_res, repo_path, "SECURITY_REPORT.md")
                p.update(t_sec, description=f"[green]Security report written[/green]", completed=True)

        # Unpack PR analysis
        impact_path = None
        if PR_ANALYSIS_ENABLED:
            if isinstance(pr_res, Exception):
                p.update(t_pr, description=f"[yellow]PR analysis skipped — {str(pr_res)[:80]}[/yellow]", completed=True)
            elif pr_res:
                impact_path = _write_md(format_impact_report(pr_res), repo_path, "PR_IMPACT.md")
                p.update(t_pr, description=f"[green]Impact: {len(pr_res['changed'])} changed[/green]", completed=True)
            else:
                if t_pr:
                    p.update(t_pr, description="[yellow]No changed files vs base branch[/yellow]", completed=True)

        # Unpack scaffolds
        if has_scaffolds:
            if isinstance(scaf_res, Exception):
                p.update(t_scaf, description=f"[yellow]Scaffolds skipped — {str(scaf_res)[:60]}[/yellow]", completed=True)
            elif scaf_res:
                scaffold_paths = _write_scaffolds(scaf_res, repo_path)
                p.update(t_scaf, description=f"[green]{len(scaffold_paths)} scaffold(s) written[/green]", completed=True)

        # ── Phase 5: Core outputs + executive report ──────────────────────────
        _progress(6, "Writing outputs...")

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
    if dead_code_result:
        console.print(f"  Dead code report  -> [cyan]{os.path.join(repo_path, 'docs', 'DEAD_CODE_REPORT.md')}[/cyan]")
    if test_gap_coverage:
        console.print(f"  Test gap report   -> [cyan]{os.path.join(repo_path, 'docs', 'TEST_GAP_REPORT.md')}[/cyan]")
    if security_path:
        console.print(f"  Security report   -> [cyan]{security_path}[/cyan]")
    if impact_path:
        console.print(f"  PR impact report  -> [cyan]{impact_path}[/cyan]")

    # ── Save snapshot for `arkhe diff` ────────────────────────────────────────
    save_snapshot(graph, files, repo_path)

    # ── Write embed index for semantic Q&A ────────────────────────────────────
    # Combines per-file analysis text with AST structure for ChromaDB indexing.
    try:
        import json as _json
        from pathlib import Path as _Path
        # reports is list[dict] with keys: files (list[str]), analysis (str)
        _path_to_analysis: dict = {}
        for batch in reports:
            for fpath in batch.get("files", []):
                _path_to_analysis[fpath] = batch.get("analysis", "")
        _embed_entries = []
        for m in modules:
            p_ = m.get("path", "")
            analysis_ = _path_to_analysis.get(p_, "")
            if analysis_:
                _embed_entries.append({
                    "path":      p_,
                    "ext":       m.get("ext", ""),
                    "tokens":    m.get("tokens", 0),
                    "analysis":  analysis_,
                    "structure": m.get("structure", {}),
                })
        if _embed_entries:
            _embed_path = _Path(repo_path) / "docs" / "EMBED_INDEX.json"
            _embed_path.write_text(_json.dumps(_embed_entries, ensure_ascii=False))
    except Exception:
        pass  # embed index is non-critical — never block main pipeline


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
