"""
clone_repo.py — Clone a GitHub or GitLab repo URL to a temp directory.

Usage (programmatic):
    from scripts.clone_repo import clone_repo, CloneError

    with clone_repo("https://github.com/user/repo") as repo_path:
        # repo_path is a temp dir — use it, then it auto-cleans on exit

Usage (CLI):
    uv run python scripts/clone_repo.py https://github.com/user/repo
"""
import os
import re
import shutil
import subprocess
import tempfile
import logging
from contextlib import contextmanager
from urllib.parse import urlparse

logger = logging.getLogger("arkhe.clone")


class CloneError(Exception):
    """Raised when a repo cannot be cloned."""


# Supported hosts
_SUPPORTED_HOSTS = {"github.com", "gitlab.com"}

# Regex: owner/repo with optional .git suffix
_REPO_PATH_RE = re.compile(r"^/([^/]+/[^/]+?)(?:\.git)?$")


def parse_repo_url(url: str) -> tuple[str, str]:
    """
    Validate and normalise a GitHub or GitLab repo URL.

    Returns (clean_url, repo_name) where:
      clean_url  — https URL without trailing .git, ready for display
      repo_name  — "owner/repo" slug, used as the clone directory name

    Raises CloneError on unsupported host or malformed path.
    """
    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https"):
        raise CloneError(f"URL must start with https://: {url}")

    host = parsed.netloc.lower().removeprefix("www.")
    if host not in _SUPPORTED_HOSTS:
        raise CloneError(
            f"Unsupported host '{host}'. Supported: {', '.join(sorted(_SUPPORTED_HOSTS))}"
        )

    m = _REPO_PATH_RE.match(parsed.path)
    if not m:
        raise CloneError(
            f"Cannot parse repo path from URL: {url}\n"
            f"Expected format: https://{host}/owner/repo"
        )

    repo_name = m.group(1)           # e.g. "sync7319/Arkhe"
    clean_url = f"https://{host}/{repo_name}"
    return clean_url, repo_name


def _run_git_clone(url: str, dest: str, depth: int = 1) -> None:
    """
    Run git clone into dest. Raises CloneError on failure.
    depth=1 (shallow clone) — faster, only latest snapshot needed.
    """
    cmd = ["git", "clone", "--depth", str(depth), "--quiet", url, dest]
    logger.info(f"[clone] git clone {url} → {dest}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Surface the most useful part of git's error output
        raise CloneError(f"git clone failed for {url}:\n{stderr}")


def clone(url: str, base_dir: str | None = None, depth: int = 1) -> str:
    """
    Clone a repo URL into a new subdirectory of base_dir (or a system temp dir).

    Returns the absolute path to the cloned repo directory.
    Caller is responsible for cleanup (use clone_repo() context manager instead).

    Raises CloneError on invalid URL or git failure.
    """
    clean_url, repo_name = parse_repo_url(url)

    # Use a flat name: "owner__repo" to avoid nested dirs
    dir_name = repo_name.replace("/", "__")

    if base_dir is None:
        base_dir = tempfile.mkdtemp(prefix="arkhe_")

    dest = os.path.join(base_dir, dir_name)

    if os.path.exists(dest):
        logger.info(f"[clone] Destination already exists, removing: {dest}")
        shutil.rmtree(dest)

    _run_git_clone(clean_url, dest, depth=depth)
    return dest


@contextmanager
def clone_repo(url: str, depth: int = 1):
    """
    Context manager — clones repo to a temp dir, yields the path, then cleans up.

    Usage:
        with clone_repo("https://github.com/user/repo") as repo_path:
            run_pipeline(repo_path)
        # temp dir is deleted here automatically
    """
    base_dir = tempfile.mkdtemp(prefix="arkhe_")
    repo_path = None
    try:
        repo_path = clone(url, base_dir=base_dir, depth=depth)
        yield repo_path
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
        logger.info(f"[clone] Cleaned up temp dir: {base_dir}")


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/clone_repo.py <github-or-gitlab-url>")
        sys.exit(1)

    url = sys.argv[1]
    try:
        with clone_repo(url) as path:
            print(f"Cloned to: {path}")
            print("(press Enter to clean up and exit)")
            input()
    except CloneError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
