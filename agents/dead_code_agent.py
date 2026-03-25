"""
Dead Code Detector — static analysis, zero LLM cost.

Two-pass approach for Python files:
  Pass 1 (regex): Cross-file name matching + decorator awareness + within-file call sites.
                  Works for all 7 supported languages.
  Pass 2 (vulture): AST-based analysis for Python — understands __all__, attribute access,
                    and dynamic patterns the regex pass misses. Used to REMOVE false positives
                    from pass 1: if vulture says a Python symbol is live, it's removed.

For every function and class defined in the codebase, checks whether that
symbol name appears anywhere outside its own file. Symbols with no external
references are flagged as potentially dead code.

False positive note: dynamic dispatch, __all__ exports, decorator-registered
callbacks, and framework magic (Flask routes, Django signal receivers) may
cause live symbols to appear unused. Always review before deleting.

Output: docs/DEAD_CODE_REPORT.md
"""
import logging
import re
import subprocess
import sys

logger = logging.getLogger("arkhe.deadcode")

# Symbols matching these patterns are skipped — they're almost always live
_DUNDER        = re.compile(r"^__.+__$")
# Decorator prefixes that register a function with a framework — not dead code
_DECORATOR_OPS = re.compile(
    r"@(app|router|blueprint|celery|pytest|signal|admin)\."
    r"|@(staticmethod|classmethod|property|overload|abstractmethod)"
    r"|urlpatterns|admin\.register"
)


def _is_framework_magic(symbol: str, content: str) -> bool:
    if _DUNDER.match(symbol):
        return True
    # Find every definition of this symbol and check if a decorator appears
    # on the preceding 3 lines (covers @app.get / @app.post / @router.X etc.)
    for m in re.finditer(rf"\bdef {re.escape(symbol)}\b|\bclass {re.escape(symbol)}\b", content):
        # Grab up to 3 lines before the definition
        before = content[max(0, m.start() - 300):m.start()]
        last_lines = before.rsplit("\n", 3)[-3:]
        joined = "\n".join(last_lines)
        if _DECORATOR_OPS.search(joined):
            return True
    return False


def _build_reference_index(modules: list[dict]) -> dict[str, set[str]]:
    """symbol → set of file paths that reference it (outside its defining file)."""
    content_by_path = {m["path"]: m.get("content", "") for m in modules}

    definitions: list[tuple[str, str]] = []
    for m in modules:
        structure = m.get("structure", {})
        for fn in structure.get("functions", []):
            definitions.append((fn, m["path"]))
        for cls in structure.get("classes", []):
            definitions.append((cls, m["path"]))

    references: dict[str, set[str]] = {}
    for symbol, defining_path in definitions:
        pattern    = re.compile(rf"\b{re.escape(symbol)}\b")
        is_private = symbol.startswith("_") and not symbol.startswith("__")

        # Check cross-file references (always)
        cross_file_refs = {
            path for path, content in content_by_path.items()
            if path != defining_path and pattern.search(content)
        }

        if cross_file_refs:
            references[symbol] = cross_file_refs
            continue

        # No cross-file refs — check within-file usage (call site beyond definition)
        own_content   = content_by_path.get(defining_path, "")
        all_matches   = len(pattern.findall(own_content))
        # Each "def symbol" / "class symbol" counts as 1 definition occurrence
        def_count     = len(re.findall(rf"\b(?:def|class)\s+{re.escape(symbol)}\b", own_content))
        call_sites    = all_matches - def_count

        if is_private or call_sites > 0:
            # Private symbol used internally, or public symbol called within own file
            references[symbol] = {defining_path}
        else:
            references[symbol] = set()

    return references


_EXCLUDE_FROM_DEAD_CODE = re.compile(
    r"(^|[/\\])(test_|_test\.|tests?[/\\]|tests_generated[/\\]|docs[/\\])"
)


def _is_analysis_target(path: str) -> bool:
    """Exclude test files and generated output from dead code analysis."""
    return not _EXCLUDE_FROM_DEAD_CODE.search(path.replace("\\", "/"))


# ── Vulture integration (Python-only false-positive reduction) ────────────────

def _get_vulture_live_symbols(python_modules: list[dict]) -> set[str]:
    """
    Run vulture on Python source files and return the set of symbol names
    that vulture considers LIVE (i.e., not in vulture's unused list).
    Used to remove false positives from the regex-based pass.

    Returns empty set if vulture is unavailable.
    """
    abs_paths = [m["abs_path"] for m in python_modules if m.get("abs_path")]
    if not abs_paths:
        return set()

    try:
        result = subprocess.run(
            [sys.executable, "-m", "vulture", "--min-confidence", "80"] + abs_paths,
            capture_output=True, text=True, timeout=60,
        )
        # Vulture outputs: "path:line: unused function 'name' (confidence X%)"
        unused_names: set[str] = set()
        for line in result.stdout.splitlines():
            m = re.search(r"unused (?:function|class|variable|import|attribute) '(\w+)'", line)
            if m:
                unused_names.add(m.group(1))

        # Collect ALL defined symbols from the Python modules
        all_defined: set[str] = set()
        for mod in python_modules:
            structure = mod.get("structure", {})
            all_defined.update(structure.get("functions", []))
            all_defined.update(structure.get("classes", []))

        # Live = defined but NOT in vulture's unused list
        return all_defined - unused_names

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"[deadcode] vulture unavailable: {e}")
        return set()


def detect_dead_code(modules: list[dict]) -> dict:
    """
    Returns:
        dead_functions: list of (symbol, file_path)
        dead_classes:   list of (symbol, file_path)
        total_defined:  int
        total_dead:     int
    """
    # Only flag symbols defined in source files — exclude tests and generated output
    source_modules  = [m for m in modules if _is_analysis_target(m["path"])]
    references      = _build_reference_index(modules)  # still search ALL files for references
    content_by_path = {m["path"]: m.get("content", "") for m in modules}

    # Collect all __all__ exports — these are intentionally public API
    all_exports: set[str] = set()
    for m in source_modules:
        exports = m.get("structure", {}).get("exports", [])
        all_exports.update(exports)

    # Vulture pass: get set of symbols vulture considers live in Python files
    python_source_mods = [m for m in source_modules if m.get("ext") == ".py"]
    vulture_live = _get_vulture_live_symbols(python_source_mods)
    if vulture_live:
        logger.info(f"[deadcode] vulture confirmed {len(vulture_live)} live Python symbols")

    dead_functions: list[tuple[str, str]] = []
    dead_classes:   list[tuple[str, str]] = []
    total_defined = 0

    for m in source_modules:
        structure = m.get("structure", {})
        content   = content_by_path.get(m["path"], "")
        is_python = m.get("ext") == ".py"

        for fn in structure.get("functions", []):
            total_defined += 1
            if _is_framework_magic(fn, content):
                continue
            if fn in all_exports:
                continue  # exported via __all__ — always live
            if not references.get(fn):
                # For Python files: if vulture says it's live, skip (vulture wins)
                if is_python and vulture_live and fn in vulture_live:
                    continue
                dead_functions.append((fn, m["path"]))

        for cls in structure.get("classes", []):
            total_defined += 1
            if _is_framework_magic(cls, content):
                continue
            if cls in all_exports:
                continue  # exported via __all__ — always live
            if not references.get(cls):
                if is_python and vulture_live and cls in vulture_live:
                    continue
                dead_classes.append((cls, m["path"]))

    total_dead = len(dead_functions) + len(dead_classes)
    logger.info(f"[dead_code] {total_dead} potentially unused / {total_defined} defined")

    return {
        "dead_functions": dead_functions,
        "dead_classes":   dead_classes,
        "total_defined":  total_defined,
        "total_dead":     total_dead,
    }


def format_dead_code_report(result: dict) -> str:
    if result["total_dead"] == 0:
        return (
            "# Dead Code Report\n\n"
            f"✓ No dead code detected across {result['total_defined']} defined symbols.\n"
        )

    lines = [
        "# Dead Code Report\n",
        f"> **{result['total_dead']}** potentially unused symbols "
        f"out of **{result['total_defined']}** defined.  \n"
        "> Dynamic dispatch, framework hooks, and `__all__` exports "
        "may cause false positives — review before deleting.\n",
    ]

    if result["dead_functions"]:
        lines += [
            "\n## Unused Functions\n",
            "| Function | Defined In |",
            "|---|---|",
            *[f"| `{fn}` | `{path}` |"
              for fn, path in sorted(result["dead_functions"], key=lambda x: x[1])],
        ]

    if result["dead_classes"]:
        lines += [
            "\n## Unused Classes\n",
            "| Class | Defined In |",
            "|---|---|",
            *[f"| `{cls}` | `{path}` |"
              for cls, path in sorted(result["dead_classes"], key=lambda x: x[1])],
        ]

    return "\n".join(lines) + "\n"
