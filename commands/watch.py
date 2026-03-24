"""
arkhe watch <repo_path>

Watches a repository for file changes and automatically re-runs the Arkhe
pipeline whenever source files are modified.

Uses watchdog for filesystem events with a 3-second debounce to avoid
triggering on rapid successive saves (e.g. auto-formatters).

Usage:
    arkhe watch ./my-project
    arkhe watch .

Press Ctrl+C to stop.
"""
import asyncio
import os
import sys
import time

from rich.console import Console

console = Console()

_DEBOUNCE_SECONDS = 3.0

_SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".rb",
}


def _is_source_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in _SOURCE_EXTENSIONS


class _ChangeHandler:
    """Accumulates file-change events and triggers re-analysis after a quiet period."""

    def __init__(self, repo_path: str, loop: asyncio.AbstractEventLoop):
        self._repo_path    = repo_path
        self._loop         = loop
        self._last_event   = 0.0
        self._running      = False
        self._pending_task = None

    def on_any_event(self, event):
        if event.is_directory:
            return
        if not _is_source_file(event.src_path):
            return
        # Ignore Arkhe's own output directory
        rel = os.path.relpath(event.src_path, self._repo_path)
        if rel.startswith("docs" + os.sep) or rel.startswith("tests_generated" + os.sep):
            return

        self._last_event = time.monotonic()
        if self._pending_task is None or self._pending_task.done():
            self._pending_task = asyncio.run_coroutine_threadsafe(
                self._debounced_run(), self._loop
            )

    async def _debounced_run(self):
        """Wait for the quiet period, then trigger a re-run."""
        while True:
            await asyncio.sleep(_DEBOUNCE_SECONDS)
            if time.monotonic() - self._last_event >= _DEBOUNCE_SECONDS:
                break

        if self._running:
            return
        self._running = True
        try:
            await self._rerun()
        finally:
            self._running = False

    async def _rerun(self):
        console.rule("[bold cyan]Arkhe Watch[/bold cyan] — change detected, re-running")
        try:
            import main as arkhe_main
            await arkhe_main.run(self._repo_path, fmt="default")
        except Exception as e:
            console.print(f"[red]Run failed:[/red] {e}")


def run_watch(repo_path: str) -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        console.print(
            "[red]watchdog is not installed.[/red] "
            "Run: [bold]pip install watchdog[/bold]"
        )
        sys.exit(1)

    repo_path = os.path.abspath(repo_path)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    handler = _ChangeHandler(repo_path, loop)

    # Wrap our handler in a watchdog-compatible class
    class _WatchdogBridge(FileSystemEventHandler):
        def on_any_event(self, event):
            handler.on_any_event(event)

    observer = Observer()
    observer.schedule(_WatchdogBridge(), repo_path, recursive=True)
    observer.start()

    console.rule("[bold cyan]Arkhe Watch[/bold cyan]")
    console.print(f"  Watching: [cyan]{repo_path}[/cyan]")
    console.print("  Press [bold]Ctrl+C[/bold] to stop.\n")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping watcher...[/yellow]")
    finally:
        observer.stop()
        observer.join()
        loop.close()
