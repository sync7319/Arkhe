"""
Extracts AST structure (functions, classes, imports, exports, calls) using tree-sitter.
Falls back gracefully for unsupported file types.

Supported languages: Python, JavaScript, TypeScript, Go, Rust, Java, Ruby.
Extend _LANG_NODE_TYPES and _get_parser() to add new languages.

New fields added to structure:
  exports: list[str]         — symbols listed in __all__ (Python only)
  calls:   dict[str, list]   — call graph: function → [called names] (Python, JS, TS, Go)
"""
import logging
from concurrent.futures import ThreadPoolExecutor
import os
from tree_sitter import Language, Parser

logger = logging.getLogger("arkhe.parser")

_PARSERS: dict = {}

# Maps file extension → (function node types, class node types, import node types)
# Import node types use node.text for their value; function/class types use
# child_by_field_name("name"). Ruby require calls are handled as a special case.
_LANG_NODE_TYPES: dict[str, tuple[set, set, set]] = {
    ".py":  (
        {"function_definition"},
        {"class_definition"},
        {"import_statement", "import_from_statement"},
    ),
    ".js":  (
        {"function_declaration", "method_definition"},
        {"class_declaration"},
        {"import_statement"},
    ),
    ".mjs": (
        {"function_declaration", "method_definition"},
        {"class_declaration"},
        {"import_statement"},
    ),
    ".cjs": (
        {"function_declaration", "method_definition"},
        {"class_declaration"},
        {"import_statement"},
    ),
    ".ts":  (
        {"function_declaration", "method_definition"},
        {"class_declaration"},
        {"import_statement"},
    ),
    ".tsx": (
        {"function_declaration", "method_definition"},
        {"class_declaration"},
        {"import_statement"},
    ),
    ".go":  (
        {"function_declaration", "method_declaration"},
        {"type_spec"},                          # inside type_declaration
        {"import_spec"},                        # inside import_declaration
    ),
    ".rs":  (
        {"function_item"},
        {"struct_item", "enum_item", "trait_item"},
        {"use_declaration"},
    ),
    ".java": (
        {"method_declaration", "constructor_declaration"},
        {"class_declaration", "interface_declaration", "enum_declaration"},
        {"import_declaration"},
    ),
    ".rb":  (
        {"method", "singleton_method"},
        {"class", "module"},
        set(),                                  # handled via _is_ruby_require()
    ),
}

# Call expression node types per language (for call graph extraction)
_CALL_NODE_TYPES: dict[str, set] = {
    ".py":  {"call"},
    ".js":  {"call_expression"},
    ".mjs": {"call_expression"},
    ".cjs": {"call_expression"},
    ".ts":  {"call_expression"},
    ".tsx": {"call_expression"},
    ".go":  {"call_expression"},
}

_RUBY_REQUIRE_METHODS = {"require", "require_relative"}

# Sentinel object used to mark function scope exit during iterative AST walk
_SCOPE_EXIT = object()


def _is_ruby_require(node) -> bool:
    """True if node is a Ruby `require`/`require_relative` call."""
    if node.type != "call":
        return False
    method = node.child_by_field_name("method")
    return method is not None and method.text.decode() in _RUBY_REQUIRE_METHODS


def _get_parser(ext: str):
    if ext in _PARSERS:
        return _PARSERS[ext]
    try:
        if ext == ".py":
            import tree_sitter_python as ts_lang
            parser = Parser(Language(ts_lang.language()))
        elif ext in (".js", ".mjs", ".cjs"):
            import tree_sitter_javascript as ts_lang
            parser = Parser(Language(ts_lang.language()))
        elif ext in (".ts", ".tsx"):
            import tree_sitter_typescript as ts_lang
            parser = Parser(Language(ts_lang.language_typescript()))
        elif ext == ".go":
            import tree_sitter_go as ts_lang
            parser = Parser(Language(ts_lang.language()))
        elif ext == ".rs":
            import tree_sitter_rust as ts_lang
            parser = Parser(Language(ts_lang.language()))
        elif ext == ".java":
            import tree_sitter_java as ts_lang
            parser = Parser(Language(ts_lang.language()))
        elif ext == ".rb":
            import tree_sitter_ruby as ts_lang
            parser = Parser(Language(ts_lang.language()))
        else:
            return None
        _PARSERS[ext] = parser
        return parser
    except Exception:
        return None


def _walk(root_node, ext: str) -> dict:
    """
    Iterative tree walk — avoids Python recursion limit on deep ASTs.
    Uses _LANG_NODE_TYPES to dispatch by file extension.

    Collects:
      functions: defined function/method names
      classes:   defined class names
      imports:   raw import statement text
      exports:   names listed in __all__ (Python only)
      calls:     call graph — {fn_name: [callee, ...]} (Python, JS, TS, Go)
    """
    fn_types, cls_types, imp_types = _LANG_NODE_TYPES.get(ext, (set(), set(), set()))
    call_types = _CALL_NODE_TYPES.get(ext, set())
    collected  = {"functions": [], "classes": [], "imports": [], "exports": [], "calls": {}}
    is_ruby    = ext == ".rb"
    is_py      = ext == ".py"
    scope_stack: list[str] = []   # names of enclosing functions for call graph
    stack      = [root_node]

    while stack:
        node = stack.pop()

        # Scope exit marker — pop the current function scope
        if node is _SCOPE_EXIT:
            if scope_stack:
                scope_stack.pop()
            continue

        if node.type in fn_types:
            name_node = node.child_by_field_name("name")
            if name_node:
                fn_name = name_node.text.decode()
                collected["functions"].append(fn_name)
                collected["calls"].setdefault(fn_name, [])
                scope_stack.append(fn_name)
                # Push sentinel so we pop scope after all descendants are processed
                stack.append(_SCOPE_EXIT)
        elif node.type in cls_types:
            name_node = node.child_by_field_name("name")
            if name_node:
                collected["classes"].append(name_node.text.decode())
        elif node.type in imp_types:
            collected["imports"].append(node.text.decode().strip())
        elif is_ruby and _is_ruby_require(node):
            collected["imports"].append(node.text.decode().strip())

        # Call graph: record calls made within the current function scope
        if scope_stack and call_types and node.type in call_types:
            func_node = node.child_by_field_name("function")
            if func_node:
                callee_text = func_node.text.decode().strip()
                # Strip attribute prefix (e.g. "self.foo" → "foo", "obj.method" → "method")
                callee = callee_text.split(".")[-1]
                if callee and callee.isidentifier():
                    collected["calls"][scope_stack[-1]].append(callee)

        # Python __all__ = [...] detection (module-level public API exports)
        if is_py and node.type == "assignment":
            left  = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left and left.text.decode().strip() == "__all__" and right:
                if right.type in ("list", "tuple"):
                    for child in right.named_children:
                        if child.type == "string":
                            val = child.text.decode().strip("'\"")
                            if val:
                                collected["exports"].append(val)

        stack.extend(reversed(node.children))

    return collected


def parse_file(file: dict) -> dict:
    from cache.db import get_db
    db           = get_db()
    content_hash = db.content_hash(file["content"])

    cached = db.get_file(file["path"], content_hash)
    if cached and cached["structure"] is not None:
        # Migrate: if cached structure lacks new fields (exports/calls), re-parse once
        if "exports" in cached["structure"]:
            logger.debug(f"[parse] cache hit: {file['path']}")
            return {**file, "content_hash": content_hash, "structure": cached["structure"]}

    ext       = file["ext"]
    parser    = _get_parser(ext)
    structure = {"functions": [], "classes": [], "imports": [], "exports": [], "calls": {}}
    if parser:
        try:
            tree      = parser.parse(bytes(file["content"], "utf-8"))
            structure = _walk(tree.root_node, ext)
        except Exception as e:
            logger.warning(f"[parse] AST parse failed for {file['path']}: {e}")

    db.save_structure(file["path"], content_hash, file["tokens"], structure)
    return {**file, "content_hash": content_hash, "structure": structure}


def parse_modules(files: list[dict]) -> list[dict]:
    workers = min(8, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(parse_file, files))
