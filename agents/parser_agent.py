"""
Extracts AST structure (functions, classes, imports) using tree-sitter.
Falls back gracefully for unsupported file types.
Extend _get_parser() to add new language support.
"""
from tree_sitter import Language, Parser

_PARSERS: dict = {}


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
        else:
            return None
        _PARSERS[ext] = parser
        return parser
    except Exception:
        return None


def _walk(node, collected: dict):
    if node.type == "function_definition":
        name_node = node.child_by_field_name("name")
        if name_node:
            collected["functions"].append(name_node.text.decode())
    elif node.type == "class_definition":
        name_node = node.child_by_field_name("name")
        if name_node:
            collected["classes"].append(name_node.text.decode())
    elif node.type in ("import_statement", "import_from_statement"):
        collected["imports"].append(node.text.decode().strip())
    for child in node.children:
        _walk(child, collected)


def parse_file(file: dict) -> dict:
    parser = _get_parser(file["ext"])
    structure = {"functions": [], "classes": [], "imports": []}
    if parser:
        try:
            tree = parser.parse(bytes(file["content"], "utf-8"))
            _walk(tree.root_node, structure)
        except Exception:
            pass
    return {**file, "structure": structure}


def parse_modules(files: list[dict]) -> list[dict]:
    return [parse_file(f) for f in files]
