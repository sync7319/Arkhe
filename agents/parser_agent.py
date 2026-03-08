"""
Extracts AST structure (functions, classes, imports) using tree-sitter.
Falls back gracefully for unsupported file types.

Supported languages: Python, JavaScript, TypeScript, Go, Rust, Java, Ruby.
Extend _LANG_NODE_TYPES and _get_parser() to add new languages.
"""
from tree_sitter import Language, Parser

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

_RUBY_REQUIRE_METHODS = {"require", "require_relative"}


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
    """
    fn_types, cls_types, imp_types = _LANG_NODE_TYPES.get(ext, (set(), set(), set()))
    collected = {"functions": [], "classes": [], "imports": []}
    is_ruby   = ext == ".rb"
    stack     = [root_node]

    while stack:
        node = stack.pop()

        if node.type in fn_types:
            name_node = node.child_by_field_name("name")
            if name_node:
                collected["functions"].append(name_node.text.decode())
        elif node.type in cls_types:
            name_node = node.child_by_field_name("name")
            if name_node:
                collected["classes"].append(name_node.text.decode())
        elif node.type in imp_types:
            collected["imports"].append(node.text.decode().strip())
        elif is_ruby and _is_ruby_require(node):
            collected["imports"].append(node.text.decode().strip())

        stack.extend(reversed(node.children))

    return collected


def parse_file(file: dict) -> dict:
    ext    = file["ext"]
    parser = _get_parser(ext)
    structure = {"functions": [], "classes": [], "imports": []}
    if parser:
        try:
            tree      = parser.parse(bytes(file["content"], "utf-8"))
            structure = _walk(tree.root_node, ext)
        except Exception:
            pass
    return {**file, "structure": structure}


def parse_modules(files: list[dict]) -> list[dict]:
    return [parse_file(f) for f in files]
