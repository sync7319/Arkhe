"""
Writes the final CODEBASE_MAP.md to docs/ inside the target repo.
"""
import os
from config.settings import OUTPUT_DIR


def write_map(content: str, repo_path: str) -> str:
    out_dir  = os.path.join(repo_path, OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "CODEBASE_MAP.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path
