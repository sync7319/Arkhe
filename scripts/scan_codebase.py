"""
Recursively scans a repo, counts tokens per file, respects .gitignore.
Returns a structured file tree with metadata.
"""
import os
import sys
import pathlib
import pathspec
import tiktoken

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    IGNORE_DIRS, IGNORE_EXTENSIONS,
    MAX_FILE_SIZE_BYTES, MAX_FILE_TOKENS,
)

encoder = tiktoken.get_encoding("cl100k_base")


def load_gitignore(root: str) -> pathspec.PathSpec:
    gitignore_path = os.path.join(root, ".gitignore")
    patterns = []
    if os.path.exists(gitignore_path):
        with open(gitignore_path) as f:
            patterns = f.read().splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


def count_tokens(content: str) -> int:
    return len(encoder.encode(content))


def scan(repo_path: str) -> list:
    repo_path = os.path.abspath(repo_path)
    spec      = load_gitignore(repo_path)
    results   = []

    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS
            and not d.startswith(".")
            and not spec.match_file(os.path.relpath(os.path.join(dirpath, d), repo_path))
        ]

        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, repo_path).replace("\\", "/")
            ext      = pathlib.Path(filename).suffix.lower()

            if ext in IGNORE_EXTENSIONS:
                continue
            if spec.match_file(rel_path):
                continue
            if os.path.getsize(abs_path) > MAX_FILE_SIZE_BYTES:
                continue

            try:
                with open(abs_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            tokens = count_tokens(content)
            if tokens > MAX_FILE_TOKENS:
                continue

            results.append({
                "path":     rel_path,
                "abs_path": abs_path,
                "ext":      ext,
                "tokens":   tokens,
                "content":  content,
            })

    return results


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    scanned = scan(repo)
    total = sum(f["tokens"] for f in scanned)
    print(f"Scanned {len(scanned)} files | {total:,} total tokens")
    for f in scanned[:10]:
        print(f"  {f['path']:60s} {f['tokens']:>6} tokens")
