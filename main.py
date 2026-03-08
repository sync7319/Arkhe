"""
Arkhe — Autonomous codebase intelligence.
Usage: python main.py [repo_path]
"""
import sys
import asyncio
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from scripts.scan_codebase    import scan
from agents.parser_agent      import parse_modules
from agents.analyst_agent     import analyze_parallel
from agents.synthesizer_agent import synthesize
from agents.visualizer_agent  import visualize
from output.map_writer        import write_map

console = Console()


async def run(repo_path: str):
    console.rule("[bold cyan]Arkhe[/bold cyan] — Codebase Intelligence")

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:

        t = p.add_task("Scanning repository...", total=None)
        files = scan(repo_path)
        p.update(t, description=f"[green]Scanned {len(files)} files[/green]", completed=True)

        t = p.add_task("Parsing AST structure...", total=None)
        modules = parse_modules(files)
        p.update(t, description=f"[green]Parsed {len(modules)} modules[/green]", completed=True)

        t = p.add_task("Analyzing with AI subagents...", total=None)
        reports = await analyze_parallel(modules)
        p.update(t, description=f"[green]{len(reports)} agent report(s) complete[/green]", completed=True)

        t = p.add_task("Synthesizing final map...", total=None)
        codebase_map = synthesize(reports, files)
        p.update(t, description="[green]Map synthesized[/green]", completed=True)

        t = p.add_task("Generating dependency visualization...", total=None)
        viz_path = visualize(modules, repo_path)
        p.update(t, description=f"[green]Visualization ready[/green]", completed=True)

        t = p.add_task("Writing output...", total=None)
        map_path = write_map(codebase_map, repo_path)
        p.update(t, description=f"[green]Written to {map_path}[/green]", completed=True)

    console.rule()
    console.print(f"[bold green]Arkhe complete.[/bold green]")
    console.print(f"  📄 Codebase map  → [cyan]{map_path}[/cyan]")
    console.print(f"  🗺️  Dependency map → [cyan]{viz_path}[/cyan]")


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    asyncio.run(run(repo))
