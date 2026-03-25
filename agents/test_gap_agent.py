"""
Test Gap Agent — identifies untested public functions and optionally generates scaffolds.

Phase 1 (static, always): Cross-references function names from AST against test file
content. Reports which public functions have no test coverage.

Phase 2 (LLM, optional): Generates a pytest scaffold for each uncovered function —
correct imports, one test stub per function, TODO placeholders for assertions.

Output:
  docs/TEST_GAP_REPORT.md          — coverage gap report (phase 1)
  tests_generated/<stem>_test.py   — scaffold files (phase 2, when enabled)
"""
import asyncio
import logging
import re

from config.llm_client import llm_call_async

logger = logging.getLogger("arkhe.testgap")

SCAFFOLD_SYSTEM = """You are a senior software engineer writing unit test scaffolds.
Given a source file and a list of untested functions, generate a pytest test file.

Rules:
- Use pytest (not unittest)
- Derive the correct import path from the file path (e.g. agents/foo.py → from agents.foo import ...)
- One test function per source function: def test_<function_name>():
- Add a one-line docstring describing what the test should verify
- Use TODO comments for assertions that need real values
- Include fixture suggestions (mock, patch, tmp_path) as comments where appropriate
- Do NOT implement test logic — scaffolds only

OUTPUT: Return ONLY the complete .py test file. No markdown fences. No explanation."""

_TEST_PATTERN = re.compile(r"(^|[/\\])(test_|_test\.|tests?[/\\]).*\.(py|js|ts)$")


def _is_test_file(path: str) -> bool:
    return bool(_TEST_PATTERN.search(path.replace("\\", "/")))


def _build_transitive_callees(all_calls: dict[str, set[str]], direct: set[str]) -> set[str]:
    """
    BFS from `direct` (directly tested functions) through `all_calls` (call graph).
    Returns the full set of functions reachable — i.e. indirectly covered.
    """
    visited: set[str] = set()
    queue   = list(direct)
    while queue:
        fn = queue.pop()
        if fn in visited:
            continue
        visited.add(fn)
        for callee in all_calls.get(fn, set()):
            if callee not in visited:
                queue.append(callee)
    return visited


def find_coverage_gaps(modules: list[dict]) -> dict:
    """
    Returns:
        test_files:  [path, ...]
        gaps:        {source_path: [uncovered_fn, ...]}
        covered:     {source_path: [covered_fn, ...]}
        indirect:    {source_path: [indirectly_covered_fn, ...]}
        stats:       {total_functions, total_covered, total_indirect, total_gap, pct_covered}
    """
    test_modules   = [m for m in modules if _is_test_file(m["path"])]
    source_modules = [m for m in modules if not _is_test_file(m["path"])]

    all_test_content = "\n".join(m.get("content", "") for m in test_modules)

    # Build cross-module call graph: callee_name → set of caller names
    # We need forward direction: caller → set of callees
    all_calls: dict[str, set[str]] = {}
    for m in modules:
        calls = m.get("structure", {}).get("calls", {})
        for caller, callees in calls.items():
            all_calls.setdefault(caller, set()).update(callees)

    # Direct coverage: function names mentioned in any test file content
    directly_covered: set[str] = set()
    for m in source_modules:
        for fn in m.get("structure", {}).get("functions", []):
            if not fn.startswith("_"):
                pattern = re.compile(rf"\b{re.escape(fn)}\b")
                if pattern.search(all_test_content):
                    directly_covered.add(fn)

    # Transitive coverage: all functions reachable from directly covered ones
    transitively_covered = _build_transitive_callees(all_calls, directly_covered)
    indirectly_covered   = transitively_covered - directly_covered

    gaps:     dict[str, list[str]] = {}
    covered:  dict[str, list[str]] = {}
    indirect: dict[str, list[str]] = {}

    for m in source_modules:
        functions = [
            fn for fn in m.get("structure", {}).get("functions", [])
            if not fn.startswith("_")   # skip private functions
        ]
        if not functions:
            continue

        path_gaps     = []
        path_covered  = []
        path_indirect = []
        for fn in functions:
            if fn in directly_covered:
                path_covered.append(fn)
            elif fn in indirectly_covered:
                path_indirect.append(fn)
            else:
                path_gaps.append(fn)

        if path_gaps:
            gaps[m["path"]] = path_gaps
        if path_covered:
            covered[m["path"]] = path_covered
        if path_indirect:
            indirect[m["path"]] = path_indirect

    total_functions = (
        sum(len(v) for v in gaps.values())
        + sum(len(v) for v in covered.values())
        + sum(len(v) for v in indirect.values())
    )
    total_covered  = sum(len(v) for v in covered.values())
    total_indirect = sum(len(v) for v in indirect.values())
    total_gap      = sum(len(v) for v in gaps.values())
    pct            = int((total_covered + total_indirect) / total_functions * 100) if total_functions else 0

    return {
        "test_files": [m["path"] for m in test_modules],
        "gaps":       gaps,
        "covered":    covered,
        "indirect":   indirect,
        "stats": {
            "total_functions": total_functions,
            "total_covered":   total_covered,
            "total_indirect":  total_indirect,
            "total_gap":       total_gap,
            "pct_covered":     pct,
        },
    }


def format_test_gap_report(coverage: dict) -> str:
    stats      = coverage["stats"]
    gaps       = coverage["gaps"]
    indirect   = coverage.get("indirect", {})
    test_files = coverage["test_files"]

    total_indirect = stats.get("total_indirect", 0)
    indirect_note  = f" + {total_indirect} indirect" if total_indirect else ""

    lines = [
        "# Test Gap Report\n",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Test files found | {len(test_files)} |",
        f"| Public functions | {stats['total_functions']} |",
        f"| Directly covered | {stats['total_covered']} |",
        f"| Indirectly covered (via call graph) | {total_indirect} |",
        f"| Total coverage | {stats['pct_covered']}%{indirect_note} |",
        f"| Uncovered | {stats['total_gap']} |",
        "",
    ]

    if not gaps and not indirect:
        lines.append("✓ All public functions have test coverage.\n")
        return "\n".join(lines)

    if gaps:
        lines += [
            "## Coverage Gaps\n",
            "| File | Uncovered Functions |",
            "|---|---|",
            *[
                f"| `{path}` | {', '.join(f'`{f}`' for f in fns)} |"
                for path, fns in sorted(gaps.items())
            ],
        ]

    if indirect:
        lines += [
            "\n## Indirectly Covered (via call graph)\n",
            "> These functions are not directly tested but are called by tested functions.\n",
            "| File | Functions |",
            "|---|---|",
            *[
                f"| `{path}` | {', '.join(f'`{f}`' for f in fns)} |"
                for path, fns in sorted(indirect.items())
            ],
        ]

    return "\n".join(lines) + "\n"


async def _scaffold_file(
    module: dict, uncovered: list[str], sem: asyncio.Semaphore
) -> "tuple[str, str]":
    import_path = module["path"].replace("\\", "/").replace("/", ".").removesuffix(".py")
    prompt = (
        f"Source file: {module['path']}\n"
        f"Import path: `from {import_path} import ...`\n"
        f"Untested public functions: {', '.join(uncovered)}\n\n"
        f"--- SOURCE (first 2000 chars) ---\n{module['content'][:2000]}"
    )
    async with sem:
        result = await llm_call_async("traversal", SCAFFOLD_SYSTEM, prompt, max_tokens=1024)
    return module["path"], result


async def generate_scaffolds(modules: list[dict], gaps: dict) -> dict[str, str]:
    """Returns {source_path: scaffold_content} for each file with uncovered functions."""
    path_to_module = {m["path"]: m for m in modules}
    sem   = asyncio.Semaphore(3)
    tasks = [
        _scaffold_file(path_to_module[path], uncovered, sem)
        for path, uncovered in gaps.items()
        if path in path_to_module
    ]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    scaffolds = {}
    for r in raw:
        if isinstance(r, Exception):
            logger.error(f"[testgap] scaffold failed: {r}")
        else:
            source_path, content = r
            scaffolds[source_path] = content

    return scaffolds
