"""
Writes Arkhe output to docs/ inside the target repo.

Default format  → CODEBASE_MAP.md  +  DEPENDENCY_MAP.html
JSON format     → CODEBASE_MAP.json (map text + graph data + metadata)
"""
import json
import os
from config.settings import OUTPUT_DIR


def write_map(content: str, repo_path: str) -> str:
    out_dir  = os.path.join(repo_path, OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "CODEBASE_MAP.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path


def write_json_map(
    codebase_map: str,
    graph: dict,
    files: list[dict],
    reports: list[dict],
    repo_path: str,
) -> str:
    """
    Write a single structured JSON file containing:
      - meta         — repo path, file count, batch count
      - codebase_map — the full markdown narrative as a string
      - dependency_graph — nodes + links from the dependency analysis
      - batch_reports — raw per-batch LLM analysis results
    """
    payload = {
        "meta": {
            "repo":    os.path.abspath(repo_path),
            "files":   len(files),
            "reports": len(reports),
        },
        "codebase_map":     codebase_map,
        "dependency_graph": graph,
        "batch_reports":    reports,
    }
    out_dir  = os.path.join(repo_path, OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "CODEBASE_MAP.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out_path
