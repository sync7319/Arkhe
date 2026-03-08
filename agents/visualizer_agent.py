"""
Visualizer Agent — Professional left-to-right collapsible tree.
Fixes: dynamic vertical spacing, no overlap, no tokens on cards, tighter padding.
"""
import json, os


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

    links = []
    for meta in raw_links.values():
        links.append({"source": meta["source"], "target": meta["target"], "bidirectional": meta["bidirectional"]})

    return {"nodes": nodes, "links": links}


def generate_html(graph: dict) -> str:
    nodes_json = json.dumps(graph["nodes"], indent=2)
    links_json = json.dumps(graph["links"], indent=2)

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Arkhe — Architecture Map</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#080c14;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",monospace;overflow:hidden;user-select:none}

#header{
  position:fixed;top:0;left:0;right:0;height:50px;
  background:rgba(8,12,20,0.97);border-bottom:1px solid #151e2e;
  backdrop-filter:blur(16px);display:flex;align-items:center;
  padding:0 24px;gap:20px;z-index:300
}
#logo{font-size:13px;font-weight:700;letter-spacing:3px;color:#4da3ff}
#logo-sub{font-size:9px;color:#2a3a50;letter-spacing:2px;margin-top:2px}
#search{
  flex:1;max-width:240px;padding:5px 14px;
  background:#0a1020;border:1px solid #151e2e;border-radius:20px;
  color:#e6edf3;font-size:12px;outline:none;transition:border .2s
}
#search:focus{border-color:#4da3ff}
#stats{margin-left:auto;font-size:10px;color:#2a3a50;letter-spacing:1px}

#legend{
  position:fixed;bottom:20px;right:20px;
  background:rgba(8,12,20,0.95);border:1px solid #151e2e;
  border-radius:10px;padding:14px 18px;z-index:300;min-width:190px
}
#legend h3{font-size:9px;color:#2a3a50;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px}
.leg-row{display:flex;align-items:center;gap:9px;margin:5px 0;font-size:11px;color:#8b949e}
.leg-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.leg-sep{border-top:1px solid #151e2e;margin:9px 0}
.leg-link{display:flex;align-items:center;gap:9px;margin:5px 0;font-size:11px;color:#8b949e}

#tooltip{
  position:fixed;pointer-events:none;
  background:rgba(8,12,20,0.97);border:1px solid #151e2e;
  border-radius:8px;padding:10px 14px;font-size:11px;
  box-shadow:0 8px 40px rgba(0,0,0,.8);z-index:400;display:none;max-width:250px
}
.tt-name{font-weight:700;color:#4da3ff;margin-bottom:5px}
.tt-row{color:#3a5070;margin:2px 0}.tt-row span{color:#c9d1d9}

#info{
  position:fixed;top:66px;left:20px;
  background:rgba(8,12,20,0.97);border:1px solid #151e2e;
  border-radius:10px;padding:16px;width:270px;z-index:300;display:none
}
.i-head{display:flex;justify-content:space-between;align-items:start;margin-bottom:12px}
.i-title{font-size:12px;font-weight:700;color:#4da3ff;word-break:break-all;line-height:1.5}
.i-close{color:#2a3a50;cursor:pointer;font-size:16px;padding-left:8px;flex-shrink:0}
.i-close:hover{color:#e6edf3}
.i-block{margin-bottom:10px}
.i-label{font-size:9px;color:#2a3a50;letter-spacing:2px;text-transform:uppercase;margin-bottom:4px}
.i-val{font-size:11px;color:#c9d1d9;line-height:1.6}
.tag{display:inline-block;background:#0a1e30;border:1px solid #152840;border-radius:3px;padding:1px 6px;font-size:10px;margin:2px;color:#79c0ff;font-family:monospace}
.mod-badge{display:inline-block;padding:2px 9px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase}

svg{cursor:grab}
svg:active{cursor:grabbing}
.col-divider{stroke:#151e2e;stroke-width:1;stroke-dasharray:3,10}
.col-label{font-size:9px;fill:#1a2535;letter-spacing:2px;text-transform:uppercase;text-anchor:middle}
.branch{stroke:#1e2e42;stroke-width:1.5;fill:none}
.file-node{cursor:pointer}
.file-rect{rx:6;ry:6;stroke-width:1}
.file-node:hover .file-rect{filter:brightness(1.5)}
.file-node.dimmed{opacity:.07}
.file-node.highlighted .file-rect{filter:drop-shadow(0 0 8px currentColor) brightness(1.6)}
.file-name{font-size:10px;font-weight:600;pointer-events:none;text-anchor:middle}
.file-meta{font-size:8px;pointer-events:none;text-anchor:middle;fill:#3a5070}
.folder-node{cursor:pointer}
.folder-rect{rx:8;ry:8;stroke-width:1.5}
.folder-node:hover .folder-rect{filter:brightness(1.4)}
.folder-name{font-size:11px;font-weight:700;pointer-events:none;text-anchor:middle;letter-spacing:1px;text-transform:uppercase}
.folder-count{font-size:9px;pointer-events:none;text-anchor:middle}
.dep-link{fill:none;stroke-width:1.5;opacity:.7}
.dep-direct{stroke:#4da3ff}
.dep-mutual{stroke:#f0883e;stroke-width:2;opacity:.85}
.dep-link.lit{opacity:1!important;stroke-width:2.5!important}
</style>
</head>
<body>

<div id="header">
  <div><div id="logo">⬡ ARKHE</div><div id="logo-sub">ARCHITECTURE MAP</div></div>
  <input id="search" type="text" placeholder="Search files…"/>
  <div id="stats"></div>
</div>

<div id="legend">
  <h3>Folders</h3>
  <div id="leg-folders"></div>
  <div class="leg-sep"></div>
  <h3>Dependencies</h3>
  <div class="leg-link">
    <svg width="30" height="10">
      <defs><marker id="ld1" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto"><path d="M0,0L5,2.5L0,5" fill="#4da3ff"/></marker></defs>
      <line x1="0" y1="5" x2="26" y2="5" stroke="#4da3ff" stroke-width="1.5" marker-end="url(#ld1)"/>
    </svg>Direct import
  </div>
  <div class="leg-link">
    <svg width="30" height="10">
      <defs>
        <marker id="ld2" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto"><path d="M0,0L5,2.5L0,5" fill="#f0883e"/></marker>
        <marker id="ld2b" markerWidth="5" markerHeight="5" refX="1" refY="2.5" orient="auto-start-reverse"><path d="M0,0L5,2.5L0,5" fill="#f0883e"/></marker>
      </defs>
      <line x1="0" y1="5" x2="26" y2="5" stroke="#f0883e" stroke-width="2" marker-end="url(#ld2)" marker-start="url(#ld2b)"/>
    </svg>Mutual
  </div>
</div>

<div id="info">
  <div class="i-head">
    <div class="i-title" id="i-title">—</div>
    <div class="i-close" onclick="closeInfo()">✕</div>
  </div>
  <div id="i-body"></div>
</div>

<div id="tooltip"></div>
<svg id="graph"></svg>

<script>
const ALL_NODES = """ + nodes_json + """;
const ALL_LINKS = """ + links_json + """;

const W = window.innerWidth, H = window.innerHeight;
const svg = d3.select("#graph").attr("width", W).attr("height", H);
const defs = svg.append("defs");

const mkM = (id, color) => {
  defs.append("marker").attr("id",id).attr("viewBox","0 -4 10 8")
    .attr("refX",9).attr("refY",0).attr("markerWidth",5).attr("markerHeight",5)
    .attr("orient","auto").append("path").attr("d","M0,-4L10,0L0,4").attr("fill",color);
};
const mkMR = (id, color) => {
  defs.append("marker").attr("id",id).attr("viewBox","0 -4 10 8")
    .attr("refX",1).attr("refY",0).attr("markerWidth",5).attr("markerHeight",5)
    .attr("orient","auto-start-reverse").append("path").attr("d","M0,-4L10,0L0,4").attr("fill",color);
};
mkM("m-direct","#4da3ff"); mkM("m-mutual","#f0883e"); mkMR("m-mutual-r","#f0883e");

const groups  = [...new Set(ALL_NODES.map(d => d.group))].sort();
const palette = ["#4da3ff","#3fb950","#f0883e","#bc8cff","#ffa657","#56d364","#ff7b72","#79c0ff","#d2a8ff","#58a6ff"];
const colorOf = d3.scaleOrdinal().domain(groups).range(palette);

document.getElementById("leg-folders").innerHTML = groups.map(g =>
  `<div class="leg-row"><div class="leg-dot" style="background:${colorOf(g)}"></div><span>${g}</span></div>`
).join("");
document.getElementById("stats").textContent = `${ALL_NODES.length} FILES  ·  ${ALL_LINKS.length} EDGES`;

// ── Layout constants ────────────────────────────────────────────
const COL0_X  = 80;
const COL1_X  = 280;
const COL2_X  = 520;
const TOP_PAD = 68;

// Node dimensions
const ROOT_W = 120, ROOT_H = 44;
const FOLD_W = 170, FOLD_H = 48;
const FILE_W = 160, FILE_H = 38;
const FILE_GAP = 10;   // gap between file nodes
const FOLD_GAP = 14;   // gap between folder nodes

// State
const folderState = {};
groups.forEach(g => { folderState[g] = false; }); // all collapsed by default

const gMain = svg.append("g");
svg.call(d3.zoom().scaleExtent([0.08,5]).on("zoom", e => gMain.attr("transform", e.transform)));

// fit to screen initially — will call after first render
const gBranches = gMain.append("g");
const gLinks    = gMain.append("g");
const gNodes    = gMain.append("g");

// ── Core layout computation ─────────────────────────────────────
// Returns the total height needed for a folder (expanded or not)
function folderHeight(g) {
  if (!folderState[g]) return FOLD_H;
  const count = ALL_NODES.filter(n => n.group === g).length;
  return Math.max(FOLD_H, count * (FILE_H + FILE_GAP) - FILE_GAP);
}

function totalLayoutHeight() {
  return groups.reduce((acc, g) => acc + folderHeight(g) + FOLD_GAP, -FOLD_GAP);
}

// Y center of each folder
function folderCenterY(g) {
  const totalH = totalLayoutHeight();
  const startY = TOP_PAD + H/2 - totalH/2;
  let y = startY;
  for (const gr of groups) {
    const h = folderHeight(gr);
    if (gr === g) return y + h/2;
    y += h + FOLD_GAP;
  }
  return y;
}

// ── Render ──────────────────────────────────────────────────────
function render() {
  gBranches.selectAll("*").remove();
  gNodes.selectAll("*").remove();

  const positions = {};

  // Root node — vertically centered on screen
  const rootCY = H / 2;
  const rootX  = COL0_X, rootY = rootCY - ROOT_H/2;
  positions["root"] = { cx: rootX + ROOT_W/2, cy: rootCY, w: ROOT_W, h: ROOT_H };

  const rootG = gNodes.append("g").attr("transform", `translate(${rootX},${rootY})`);
  rootG.append("rect").attr("width",ROOT_W).attr("height",ROOT_H).attr("rx",10)
    .attr("fill","#4da3ff").attr("fill-opacity",.12)
    .attr("stroke","#4da3ff").attr("stroke-opacity",.5).attr("stroke-width",2);
  rootG.append("text").attr("x",ROOT_W/2).attr("y",18).attr("text-anchor","middle")
    .attr("font-size","12px").attr("font-weight","700").attr("fill","#4da3ff").attr("letter-spacing","2px").text("ARKHE");
  rootG.append("text").attr("x",ROOT_W/2).attr("y",32).attr("text-anchor","middle")
    .attr("font-size","9px").attr("fill","#2a3a50").text("project root");

  // Folder nodes
  groups.forEach(g => {
    const cx   = colorOf(g);
    const fcy  = folderCenterY(g);
    const fy   = fcy - FOLD_H/2;
    const fx   = COL1_X;
    const fh   = folderHeight(g);
    const expanded = folderState[g];

    positions["folder_"+g] = { cx: fx + FOLD_W/2, cy: fcy, w: FOLD_W, h: FOLD_H };

    // Branch: root -> folder (always horizontal to folder center)
    const rp = positions["root"];
    gBranches.append("path").attr("class","branch")
      .attr("d", bezier(rp.cx + rp.w/2, rp.cy, fx, fcy));

    const fg = gNodes.append("g").attr("class","folder-node")
      .attr("transform", `translate(${fx},${fy})`)
      .on("click", () => { folderState[g] = !folderState[g]; render(); drawLinks(); });

    fg.append("rect").attr("class","folder-rect")
      .attr("width",FOLD_W).attr("height",FOLD_H)
      .attr("fill",cx).attr("fill-opacity",.1)
      .attr("stroke",cx).attr("stroke-opacity",.45).attr("stroke-width",1.5);
    fg.append("rect").attr("width",3).attr("height",FOLD_H)
      .attr("fill",cx).attr("fill-opacity",.9).attr("rx",2);
    fg.append("text").attr("class","folder-name")
      .attr("x",FOLD_W/2).attr("y",20).attr("fill",cx).text(`/ ${g}`);
    fg.append("text").attr("class","folder-count")
      .attr("x",FOLD_W/2).attr("y",35).attr("fill",cx).attr("fill-opacity",.45)
      .text(`${ALL_NODES.filter(n=>n.group===g).length} files  ${expanded?"▾":"▸"}`);

    // File nodes — if expanded, evenly spaced and CENTERED on folder cy
    if (expanded) {
      const files     = ALL_NODES.filter(n => n.group === g);
      const totalFH   = files.length * (FILE_H + FILE_GAP) - FILE_GAP;
      const startY    = fcy - totalFH/2;

      files.forEach((file, idx) => {
        const fiy  = startY + idx * (FILE_H + FILE_GAP);
        const ficy = fiy + FILE_H/2;
        const fix  = COL2_X;
        positions[file.id] = { cx: fix + FILE_W/2, cy: ficy, w: FILE_W, h: FILE_H };

        // Branch: folder -> file
        const fp = positions["folder_"+g];
        gBranches.append("path").attr("class","branch")
          .attr("d", bezier(fp.cx + fp.w/2, fp.cy, fix, ficy));

        const ng = gNodes.append("g").attr("class","file-node")
          .attr("data-id", file.id)
          .attr("transform", `translate(${fix},${fiy})`)
          .on("click",     () => showInfo(file))
          .on("mouseover", (e) => showTip(e,file))
          .on("mousemove", moveTip)
          .on("mouseout",  hideTip);

        ng.append("rect").attr("class","file-rect")
          .attr("width",FILE_W).attr("height",FILE_H)
          .attr("fill",cx).attr("fill-opacity",.08)
          .attr("stroke",cx).attr("stroke-opacity",.3).attr("stroke-width",1);
        ng.append("rect").attr("width",2.5).attr("height",FILE_H)
          .attr("fill",cx).attr("fill-opacity",.8).attr("rx",1);
        ng.append("text").attr("class","file-name")
          .attr("x",FILE_W/2).attr("y",15).attr("fill",cx)
          .text(file.name.length > 20 ? file.name.slice(0,18)+"…" : file.name);

        const fns = file.functions.length, cls = file.classes.length;
        const meta = [fns?`${fns} fn`:"", cls?`${cls} cls`:""].filter(Boolean).join(" · ") || "—";
        ng.append("text").attr("class","file-meta").attr("x",FILE_W/2).attr("y",28).text(meta);
      });
    }
  });

  // Column dividers
  [[COL1_X - 18, "FOLDERS"],[COL2_X - 18, "FILES"]].forEach(([x, label]) => {
    gBranches.append("line").attr("class","col-divider")
      .attr("x1",x).attr("y1",TOP_PAD-20).attr("x2",x).attr("y2",TOP_PAD + totalLayoutHeight() + 60);
    gBranches.append("text").attr("class","col-label")
      .attr("x",x + 90).attr("y",TOP_PAD-26).text(label);
  });

  window._positions = positions;
}

// Smooth S-curve bezier: from right edge of src to left edge of tgt
function bezier(x1, y1, x2, y2) {
  const mx = (x1 + x2) / 2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
}

// ── Dependency arrows ────────────────────────────────────────────
function drawLinks() {
  gLinks.selectAll("*").remove();
  const pos = window._positions;
  if (!pos) return;

  ALL_LINKS.forEach(link => {
    const sid = link.source?.id ?? link.source;
    const tid = link.target?.id ?? link.target;
    const sp = pos[sid], tp = pos[tid];
    if (!sp || !tp) return;

    const mutual = link.bidirectional;
    const x1 = sp.cx + sp.w/2, y1 = sp.cy;
    const x2 = tp.cx - tp.w/2, y2 = tp.cy;  // right edge -> left edge
    const mx = (x1+x2)/2, my = (y1+y2)/2;
    const curvature = (y2 - y1) * 0.4;

    gLinks.append("path")
      .attr("class", `dep-link ${mutual?"dep-mutual":"dep-direct"}`)
      .attr("data-src", sid).attr("data-tgt", tid)
      .attr("d", `M${x1},${y1} C${mx},${y1-curvature} ${mx},${y2+curvature} ${x2},${y2}`)
      .attr("marker-end",   mutual ? "url(#m-mutual)"   : "url(#m-direct)")
      .attr("marker-start", mutual ? "url(#m-mutual-r)" : null);
  });
}

render();
drawLinks();

// Initial zoom to fit
const bbox = gMain.node().getBBox();
if (bbox.width > 0) {
  const scale = Math.min((W-40)/bbox.width, (H-80)/bbox.height, 1);
  const tx = (W - bbox.width * scale) / 2 - bbox.x * scale;
  const ty = (H - bbox.height * scale) / 2 - bbox.y * scale + 25;
  gMain.attr("transform", `translate(${tx},${ty}) scale(${scale})`);
}

// ── Tooltip ──────────────────────────────────────────────────────
function showTip(e, d) {
  const t = document.getElementById("tooltip");
  t.style.display = "block";
  t.innerHTML = `<div class="tt-name">${d.name}</div>
    <div class="tt-row">Path: <span>${d.path}</span></div>
    <div class="tt-row">Tokens: <span>${(d.tokens||0).toLocaleString()}</span></div>
    <div class="tt-row">Functions: <span>${d.functions?.length}</span></div>
    <div class="tt-row">Classes: <span>${d.classes?.length}</span></div>`;
}
function moveTip(e) {
  const t = document.getElementById("tooltip");
  t.style.left=(e.clientX+16)+"px"; t.style.top=(e.clientY+16)+"px";
}
function hideTip() { document.getElementById("tooltip").style.display="none"; }

// ── Info panel ────────────────────────────────────────────────────
function showInfo(d) {
  document.getElementById("i-title").textContent = d.path;
  const fns  = (d.functions||[]).slice(0,10).map(f=>`<span class="tag">${f}()</span>`).join("")||"—";
  const cls  = (d.classes||[]).slice(0,6).map(c=>`<span class="tag">${c}</span>`).join("")||"—";
  const imps = (d.imports||[]).slice(0,6).map(i=>`<span class="tag">${i.slice(0,34)}</span>`).join("")||"—";
  const cx   = colorOf(d.group);
  document.getElementById("i-body").innerHTML = `
    <div class="i-block"><div class="i-label">Module</div>
      <div class="i-val"><span class="mod-badge" style="background:${cx}22;color:${cx};border:1px solid ${cx}44">${d.group}</span></div></div>
    <div class="i-block"><div class="i-label">Tokens</div><div class="i-val">${(d.tokens||0).toLocaleString()}</div></div>
    <div class="i-block"><div class="i-label">Functions</div><div class="i-val">${fns}</div></div>
    <div class="i-block"><div class="i-label">Classes</div><div class="i-val">${cls}</div></div>
    <div class="i-block"><div class="i-label">Imports</div><div class="i-val">${imps}</div></div>`;
  document.getElementById("info").style.display = "block";

  const conn = new Set([d.id]);
  ALL_LINKS.forEach(l => {
    const s = l.source?.id??l.source, t = l.target?.id??l.target;
    if(s===d.id) conn.add(t); if(t===d.id) conn.add(s);
  });
  d3.selectAll(".file-node").classed("dimmed", function() {
    const id = +d3.select(this).attr("data-id");
    return !conn.has(id);
  });
  gLinks.selectAll(".dep-link").classed("lit", function() {
    const s = +d3.select(this).attr("data-src"), t = +d3.select(this).attr("data-tgt");
    return s===d.id||t===d.id;
  });
}
function closeInfo() {
  document.getElementById("info").style.display="none";
  d3.selectAll(".file-node").classed("dimmed",false);
  gLinks.selectAll(".dep-link").classed("lit",false);
}

// ── Search ────────────────────────────────────────────────────────
document.getElementById("search").addEventListener("input", function() {
  const q = this.value.toLowerCase();
  if(!q) { d3.selectAll(".file-node").classed("dimmed",false); return; }
  d3.selectAll(".file-node").classed("dimmed", function() {
    const id = +d3.select(this).attr("data-id");
    const node = ALL_NODES.find(n => n.id===id);
    return !node?.path.toLowerCase().includes(q);
  });
});
</script>
</body>
</html>"""


def write_visualizer(graph: dict, repo_path: str) -> str:
    html     = generate_html(graph)
    out_dir  = os.path.join(repo_path, "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "DEPENDENCY_MAP.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def visualize(modules: list[dict], repo_path: str) -> str:
    graph    = build_graph(modules)
    out_path = write_visualizer(graph, repo_path)
    return out_path
