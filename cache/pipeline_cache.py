"""
Resumable pipeline cache for Arkhe.

Each stage (scan, parse, analyze) is saved to .arkhe_cache/<stage>.json
inside the target repo. A fingerprint of the repo's file tree is stored
alongside the result. On re-run, if the fingerprint still matches the
current repo state, the cached result is loaded and the stage is skipped.

Fingerprint = MD5 of sorted (relative_path, size, mtime) for every file
in the repo, excluding generated/tooling directories. Fast — no content reads.
"""
import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("arkhe.cache")

# Directories to skip when computing the fingerprint
_SKIP_DIRS = {".arkhe_cache", ".venv", "__pycache__", ".git", "docs", "node_modules"}


def compute_fingerprint(repo_path: str) -> str:
    """Walk repo and hash (path, size, mtime) for every file — no content reads."""
    entries = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for name in sorted(files):
            full = os.path.join(root, name)
            try:
                st  = os.stat(full)
                rel = os.path.relpath(full, repo_path)
                entries.append(f"{rel}:{st.st_size}:{st.st_mtime:.3f}")
            except OSError:
                pass
    return hashlib.md5("\n".join(entries).encode()).hexdigest()


def _cache_path(repo_path: str, stage: str) -> Path:
    d = Path(repo_path) / ".arkhe_cache"
    d.mkdir(exist_ok=True)
    return d / f"{stage}.json"


def load_stage(repo_path: str, stage: str, fingerprint: str):
    """Return cached result if fingerprint matches, else None."""
    path = _cache_path(repo_path, stage)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("fingerprint") != fingerprint:
            logger.debug(f"[cache] {stage}: fingerprint mismatch — invalidated")
            return None
        logger.info(f"[cache] {stage}: hit")
        return data["result"]
    except Exception as e:
        logger.warning(f"[cache] {stage}: failed to load ({e})")
        return None


def save_stage(repo_path: str, stage: str, fingerprint: str, result) -> None:
    """Persist a stage result alongside its fingerprint."""
    path = _cache_path(repo_path, stage)
    try:
        with open(path, "w") as f:
            json.dump({"fingerprint": fingerprint, "result": result}, f)
        logger.debug(f"[cache] {stage}: saved")
    except Exception as e:
        logger.warning(f"[cache] {stage}: failed to save ({e})")
