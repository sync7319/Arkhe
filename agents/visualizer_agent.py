"""
Visualizer Agent — builds the interactive D3 dependency graph.
HTML/CSS/JS lives in templates/dependency_map.html.
Graph data is injected at render time via {{NODES_JSON}} / {{LINKS_JSON}} placeholders.
"""
import json
import os


def build_graph(modules: list[dict]) -> dict:
    path_to_id = {}
    nodes = []
    for i, module in enumerate(modules):
        path = module["path"].replace("\\", "/")
        path_to_id[path] = i
        parts = path.split("/")
        group = parts[0] if len(parts) > 1 else "root"
        structure = module.get("structure", {})
        nodes.append({
            "id":        i,
            "path":      path,
            "name":      parts[-1],
            "group":     group,
            "depth":     len(parts) - 1,
            "tokens":    module.get("tokens", 0),
            "functions": structure.get("functions", []),
            "classes":   structure.get("classes", []),
            "imports":   structure.get("imports", []),
        })

    raw_links = {}
    for module in modules:
        src_path = module["path"].replace("\\", "/")
        src_id   = path_to_id.get(src_path)
        if src_id is None:
            continue
        for imp in module.get("structure", {}).get("imports", []):
            for target_path, target_id in path_to_id.items():
                if target_id == src_id:
                    continue
                target_mod = target_path.replace("/", ".").replace(".py", "")
                imp_clean  = imp.replace("from ", "").replace("import ", "").split(" ")[0].strip()
                if imp_clean and (imp_clean in target_mod or target_mod.endswith(imp_clean)):
                    key = (min(src_id, target_id), max(src_id, target_id))
                    if key in raw_links:
                        raw_links[key]["bidirectional"] = True
                    else:
                        raw_links[key] = {"source": src_id, "target": target_id, "bidirectional": False}
                    break

    links = [
        {"source": m["source"], "target": m["target"], "bidirectional": m["bidirectional"]}
        for m in raw_links.values()
    ]

    return {"nodes": nodes, "links": links}


def generate_html(graph: dict) -> str:
    template_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "templates", "dependency_map.html"
    )
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    return (
        template
        .replace("{{NODES_JSON}}", json.dumps(graph["nodes"], indent=2))
        .replace("{{LINKS_JSON}}", json.dumps(graph["links"], indent=2))
    )


def write_visualizer(graph: dict, repo_path: str) -> str:
    html    = generate_html(graph)
    out_dir = os.path.join(repo_path, "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "DEPENDENCY_MAP.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def visualize(modules: list[dict], repo_path: str) -> str:
    graph = build_graph(modules)
    return write_visualizer(graph, repo_path)
