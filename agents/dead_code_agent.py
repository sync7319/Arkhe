"""
Dead Code Detector — purely static analysis, zero LLM cost.

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

logger = logging.getLogger("arkhe.deadcode")

# Symbols matching these patterns are skipped — they're almost always live
_DUNDER        = re.compile(r"^__.+__$")
_FRAMEWORK_OPS = ["@app.", "@router.", "urlpatterns", "signals.", "admin.register"]


def _is_framework_magic(symbol: str, content: str) -> bool:
    if _DUNDER.match(symbol):
        return True
    snippet = re.search(
        rf"[@(]\S*{re.escape(symbol)}|{re.escape(symbol)}\s*=\s*",
        content,
    )
    if snippet:
        surrounding = content[max(0, snippet.start() - 20):snippet.start()]
        for op in _FRAMEWORK_OPS:
            if op in surrounding:
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
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        refs = {
            path for path, content in content_by_path.items()
            if path != defining_path and pattern.search(content)
        }
        references[symbol] = refs

    return references


_EXCLUDE_FROM_DEAD_CODE = re.compile(
    r"(^|[/\\])(test_|_test\.|tests?[/\\]|tests_generated[/\\]|docs[/\\])"
)


def _is_analysis_target(path: str) -> bool:
    """Exclude test files and generated output from dead code analysis."""
    return not _EXCLUDE_FROM_DEAD_CODE.search(path.replace("\\", "/"))


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

    dead_functions: list[tuple[str, str]] = []
    dead_classes:   list[tuple[str, str]] = []
    total_defined = 0

    for m in source_modules:
        structure = m.get("structure", {})
        content   = content_by_path.get(m["path"], "")

        for fn in structure.get("functions", []):
            total_defined += 1
            if _is_framework_magic(fn, content):
                continue
            if not references.get(fn):
                dead_functions.append((fn, m["path"]))

        for cls in structure.get("classes", []):
            total_defined += 1
            if _is_framework_magic(cls, content):
                continue
            if not references.get(cls):
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
