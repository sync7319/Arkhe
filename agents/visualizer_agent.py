"""
Visualizer Agent — builds the interactive D3 dependency graph.
HTML/CSS/JS lives in templates/dependency_map.html.
Graph data is injected at render time via {{NODES_JSON}} / {{LINKS_JSON}} placeholders.

Complexity scoring:
  Python files: radon cyclomatic complexity (CC) + base heuristic
  Other files:  base heuristic (tokens + imports×10 + functions×5)

Import resolution:
  Python: dotted module → file path
  JS/TS:  relative path strings (from '...', require('...'))
"""
import json
import logging
import os
import re
from importlib.resources import files

logger = logging.getLogger("arkhe.visualizer")


# ── Import resolution — Python ────────────────────────────────────────────────

def _extract_module(imp_str: str) -> str | None:
    """
    Parse a Python import statement and return the dotted module name.

      from config.llm_client import llm_call_async  ->  "config.llm_client"
      from .utils import helper                      ->  ".utils"
      from ..agents import parser                    ->  "..agents"
      import asyncio                                 ->  "asyncio"
      import os.path                                 ->  "os.path"
    """
    # from X import Y [as Z]
    m = re.match(r"^from\s+(\.+(?:\w+(?:\.\w+)*)?|\w+(?:\.\w+)*)\s+import", imp_str)
    if m:
        return m.group(1)
    # import X [as Y] [, ...]
    m = re.match(r"^import\s+(\w+(?:\.\w+)*)", imp_str)
    if m:
        return m.group(1)
    return None


def _resolve_relative(module: str, src_path: str) -> str | None:
    """
    Resolve a relative import to an absolute dotted module path.

      module=".utils",    src="agents/analyst.py"  ->  "agents.utils"
      module="..config",  src="agents/analyst.py"  ->  "config"
      module=".",         src="agents/analyst.py"  ->  "agents"
    """
    dots  = len(module) - len(module.lstrip("."))
    rest  = module[dots:]
    parts = src_path.replace("\\", "/").split("/")[:-1]  # package components

    for _ in range(dots - 1):
        if not parts:
            return None
        parts.pop()

    if rest:
        return (".".join(parts) + "." + rest) if parts else rest
    return ".".join(parts) if parts else None


def _module_to_path(module: str, known_paths: set) -> str | None:
    """
    Convert a dotted module name to a repo-relative file path.
    Tries <module>.py first, then <module>/__init__.py (package import).
    Returns None if the module doesn't map to any known file (stdlib, third-party).
    """
    base = module.replace(".", "/")
    for candidate in (base + ".py", base + "/__init__.py"):
        if candidate in known_paths:
            return candidate
    return None


# ── Import resolution — JavaScript / TypeScript ───────────────────────────────

def _extract_module_js(imp_str: str) -> str | None:
    """
    Extract the module path from a JS/TS import or require statement.

      import { foo } from './utils'      ->  "./utils"
      import React from 'react'          ->  "react"
      const x = require('../config')     ->  "../config"
      export { bar } from './helpers'    ->  "./helpers"
    """
    # from '...' (covers import and export ... from)
    m = re.search(r"""from\s+['"]([^'"]+)['"]""", imp_str)
    if m:
        return m.group(1)
    # require('...')
    m = re.search(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", imp_str)
    if m:
        return m.group(1)
    return None


def _resolve_import_js(imp_str: str, src_path: str, known_paths: set) -> str | None:
    """
    Resolve a JS/TS import to a repo-relative file path.
    Only resolves relative imports (starting with . or ..) — skips node_modules.
    """
    module = _extract_module_js(imp_str)
    if not module or not module.startswith("."):
        return None  # skip node_modules / bare specifiers

    src_dir = "/".join(src_path.replace("\\", "/").split("/")[:-1])
    # Normalize the path
    parts: list[str] = []
    for part in (src_dir + "/" + module).split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part and part != ".":
            parts.append(part)
    base = "/".join(parts)

    # Try various extensions and index file conventions
    for candidate in (
        base + ".js", base + ".ts", base + ".tsx", base + ".jsx",
        base + ".mjs", base + ".cjs",
        base + "/index.js", base + "/index.ts", base + "/index.tsx",
        base,
    ):
        if candidate in known_paths:
            return candidate
    return None


# ── Unified import resolver ───────────────────────────────────────────────────

_JS_EXTS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}


def _resolve_import(imp_str: str, src_path: str, known_paths: set) -> str | None:
    """Full pipeline: parse → resolve relative → map to path."""
    ext = os.path.splitext(src_path)[1].lower()
    if ext in _JS_EXTS:
        return _resolve_import_js(imp_str, src_path, known_paths)
    # Python (default): dotted module resolution
    module = _extract_module(imp_str)
    if not module:
        return None
    if module.startswith("."):
        module = _resolve_relative(module, src_path)
    if not module:
        return None
    return _module_to_path(module, known_paths)


# ── Complexity scoring ────────────────────────────────────────────────────────

def _complexity_score(module: dict) -> int:
    """
    Complexity score for a file — higher = more complex / higher risk.
    Used for the heatmap overlay in the dependency graph.

    Python: augmented with radon cyclomatic complexity (CC sum across all functions).
    Other:  base heuristic (tokens + imports×10 + functions×5).
    """
    structure = module.get("structure", {})
    base = (
        module.get("tokens", 0)
        + len(structure.get("imports",   [])) * 10
        + len(structure.get("functions", [])) * 5
    )

    if module.get("ext") == ".py":
        content = module.get("content", "")
        if content:
            try:
                from radon.complexity import cc_visit
                cc_results = cc_visit(content)
                if cc_results:
                    cc_sum = sum(r.complexity for r in cc_results)
                    return base + cc_sum * 3  # weight CC: each complexity point = 3
            except Exception:
                pass  # radon unavailable or parse error — fall through to base

    return base


# ── Graph builder ────────────────────────────────────────────────────────────

_CODE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".java", ".rb", ".c", ".cpp", ".cc",
    ".h", ".hpp", ".cs", ".swift", ".kt", ".scala", ".php",
}


def build_graph(modules: list[dict]) -> dict:
    # Only include source code files — skip configs, docs, data, CI files, etc.
    modules = [m for m in modules if os.path.splitext(m["path"])[1].lower() in _CODE_EXTENSIONS]

    path_to_id: dict[str, int] = {}
    nodes = []

    for i, module in enumerate(modules):
        path = module["path"].replace("\\", "/")
        path_to_id[path] = i
        parts     = path.split("/")
        group     = parts[0] if len(parts) > 1 else "root"
        structure = module.get("structure", {})
        nodes.append({
            "id":         i,
            "path":       path,
            "name":       parts[-1],
            "group":      group,
            "depth":      len(parts) - 1,
            "tokens":     module.get("tokens", 0),
            "functions":  structure.get("functions", []),
            "classes":    structure.get("classes", []),
            "imports":    structure.get("imports", []),
            "complexity": _complexity_score(module),
        })

    known_paths = set(path_to_id.keys())
    raw_links: dict[tuple, dict] = {}

    for module in modules:
        src_path = module["path"].replace("\\", "/")
        src_id   = path_to_id.get(src_path)
        if src_id is None:
            continue

        for imp in module.get("structure", {}).get("imports", []):
            target_path = _resolve_import(imp, src_path, known_paths)
            if target_path is None:
                continue
            target_id = path_to_id.get(target_path)
            if target_id is None or target_id == src_id:
                continue

            key = (min(src_id, target_id), max(src_id, target_id))
            if key in raw_links:
                raw_links[key]["bidirectional"] = True
            else:
                raw_links[key] = {"source": src_id, "target": target_id, "bidirectional": False}

    links = [
        {"source": m["source"], "target": m["target"], "bidirectional": m["bidirectional"]}
        for m in raw_links.values()
    ]

    return {"nodes": nodes, "links": links}


# ── HTML generation ──────────────────────────────────────────────────────────

def generate_html(graph: dict, heatmap: bool = False) -> str:
    template = files("templates").joinpath("dependency_map.html").read_text(encoding="utf-8")

    return (
        template
        .replace("{{NODES_JSON}}", json.dumps(graph["nodes"], indent=2))
        .replace("{{LINKS_JSON}}", json.dumps(graph["links"], indent=2))
        .replace("{{HEATMAP_DEFAULT}}", "true" if heatmap else "false")
    )


def write_visualizer(graph: dict, repo_path: str, heatmap: bool = False) -> str:
    html    = generate_html(graph, heatmap=heatmap)
    out_dir = os.path.join(repo_path, "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "DEPENDENCY_MAP.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def visualize(modules: list[dict], repo_path: str) -> str:
    graph = build_graph(modules)
    return write_visualizer(graph, repo_path)
