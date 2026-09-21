"""Builds the standalone 'Workflow Visualization' HTML deliverable.

This packages the same two tabs shown on the in-app Visualization page
(Overview graph + Table View) into a single, self-contained .html file
that a user can download and keep working with after leaving the app:

  - Overview tab: the interactive PyVis/vis-network graph (pan, zoom,
    drag, click-a-session-node-for-details) embedded via <iframe srcdoc>.
  - Table View tab: the full execution-order table with client-side
    search and column sorting (no server round-trip).
  - Clicking a session node opens the same right-side detail panel used
    in-app, populated from data embedded directly in the file (JSON),
    so it keeps working after download with no backend calls.
  - Clicking a Mapping Name link in Table View opens a new tab (created
    on the fly, closable) for that mapping -- the same drill-down view as
    the in-app Mapping page: its own Source->Target lineage graph, plus
    clicking a transformation node on that graph opens the right-side
    detail panel with business logic / ports / expressions / attributes.
    All of this is precomputed and embedded as JSON at export time, so it
    keeps working fully offline with no server calls.

Only the vis-network / Bootstrap CDN <script>/<link> tags (already used
by the in-app graph and shell) need internet access to render; everything
else -- the graph data, the table rows, the mapping drill-down graphs and
the session/transformation detail lookups -- is embedded in the file and
works fully offline.
"""
import json
import html as html_lib

from app.analyzer.workflow_analyzer import (
    build_execution_table, has_any_mapplet, build_mapping_lineage, build_mapplet_lineage,
)


def _session_details(repo) -> dict:
    """Same shape as the /session/<name> JSON endpoint, precomputed for
    every session so the exported file needs no server to populate the
    detail panel."""
    wf = repo.workflow
    details = {}
    if wf is None:
        return details
    for session in wf.sessions.values():
        mapping = repo.mappings.get(session.mapping_name)
        tables_used = sorted(set((mapping.sources if mapping else []) + (mapping.targets if mapping else [])))
        transforms_used = mapping.transformations if mapping else []
        details[session.name] = {
            "session_name": session.name,
            "mapping_name": session.mapping_name,
            "tables_used": tables_used,
            "transformations_used": transforms_used,
        }
    return details


def _transformation_detail(t) -> dict:
    """Same shape as the /transformation/<name> JSON endpoint."""
    return {
        "name": t.name,
        "type": t.type,
        "business_logic": t.business_logic or "(not applicable for this transformation type)",
        "implementation_details": t.implementation_notes,
        "input_ports": [p.to_dict() for p in t.input_ports],
        "output_ports": [p.to_dict() for p in t.output_ports],
        "variable_ports": [p.to_dict() for p in t.variable_ports],
        "expressions": t.expressions,
        "attributes": t.attributes,
    }


def _safe_json(obj) -> str:
    """json.dumps, with '</' escaped so free-text fields pulled from the
    parsed workflow (business logic notes, expressions, etc.) can never
    accidentally close the surrounding <script> tag early."""
    return json.dumps(obj).replace("</", "<\\/")


def _mapping_data(repo, mapping_graphs: dict) -> dict:
    """Precomputes everything the offline per-mapping drill-down tab needs:
    the rendered lineage graph markup, the instance->{type, ref_name} map
    (needed to resolve a clicked graph node back to a transformation, same
    as MAPPING_INSTANCES in the in-app mapping_detail.html), and every
    transformation's detail payload for that mapping so the right-side
    panel needs no server call, mirroring detail_panel.js's
    loadTransformationPanel()."""
    data = {}
    for name, mapping in repo.mappings.items():
        instances = {inst.name: {"type": inst.type, "ref_name": inst.ref_name} for inst in mapping.instances}

        transformations = {}
        t_names = set(mapping.transformations)
        for inst in mapping.instances:
            if inst.type == "TRANSFORMATION":
                t_names.add(inst.ref_name)
        for t_name in t_names:
            t = repo.transformation(name, t_name)
            if t is not None:
                transformations[t_name] = _transformation_detail(t)

        data[name] = {
            "graph_srcdoc": mapping_graphs.get(name, ""),
            "lineage": build_mapping_lineage(repo, name),
            "instances": instances,
            "transformations": transformations,
        }
    return data


def _mapplet_data(repo, mapplet_graphs: dict) -> dict:
    """Same precomputation as _mapping_data, but for Mapplets (minor
    improvement-2): the rendered lineage graph markup, the
    instance->{type, ref_name} map, and every transformation's detail
    payload for that mapplet, so Table View's Mapplet column can open its
    own fully offline drill-down tab, same as a Mapping Name link.

    Mapplet transformations are stored keyed as
    "MAPPLET::<mapplet_name>::<transform_name>" (see
    tree_parser._parse_mapplet), so repo.transformation() is called with
    mapping_name="MAPPLET::<mapplet_name>" to resolve them."""
    data = {}
    for name, mapplet in repo.mapplets.items():
        instances = {inst.name: {"type": inst.type, "ref_name": inst.ref_name} for inst in mapplet.instances}

        transformations = {}
        t_names = set(mapplet.transformations)
        for inst in mapplet.instances:
            if inst.type == "TRANSFORMATION":
                t_names.add(inst.ref_name)
        for t_name in t_names:
            t = repo.transformation(f"MAPPLET::{name}", t_name)
            if t is not None:
                transformations[t_name] = _transformation_detail(t)

        data[name] = {
            "graph_srcdoc": mapplet_graphs.get(name, ""),
            "lineage": build_mapplet_lineage(repo, name),
            "instances": instances,
            "transformations": transformations,
        }
    return data


def _table_rows_html(rows, show_mapplet: bool, known_mappings: set, known_mapplets: set) -> str:
    head_cols = ["Workflow Name", "Session Name", "Mapping Name"]
    if show_mapplet:
        head_cols.append("Mapplet")
    head_cols.append("Transformation Name")
    thead = "".join(f"<th>{html_lib.escape(c)}</th>" for c in head_cols)

    body_rows = []
    for row in rows:
        workflow_cell = f"<td>{html_lib.escape(str(row.get('workflow', '')))}</td>"
        session_cell = f"<td>{html_lib.escape(str(row.get('session', '')))}</td>"

        mapping_name = str(row.get("mapping", ""))
        mapping_escaped = html_lib.escape(mapping_name)
        if mapping_name in known_mappings:
            mapping_cell = (
                f'<td><a href="javascript:void(0)" class="mapping-link" '
                f'data-mapping="{mapping_escaped}">{mapping_escaped}</a></td>'
            )
        else:
            mapping_cell = f"<td>{mapping_escaped}</td>"

        cells = [workflow_cell, session_cell, mapping_cell]
        if show_mapplet:
            mapplet_name = str(row.get("mapplet", ""))
            mapplet_escaped = html_lib.escape(mapplet_name)
            if mapplet_name and mapplet_name in known_mapplets:
                mapplet_cell = (
                    f'<td><a href="javascript:void(0)" class="mapplet-link" '
                    f'data-mapplet="{mapplet_escaped}">{mapplet_escaped}</a></td>'
                )
            else:
                mapplet_cell = f"<td>{mapplet_escaped}</td>"
            cells.append(mapplet_cell)
        cells.append(f"<td>{html_lib.escape(str(row.get('transformation', '')))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"""
<table class="table table-sm table-hover align-middle" id="exportTable">
  <thead><tr class="table-light">{thead}</tr></thead>
  <tbody>{''.join(body_rows)}</tbody>
</table>
<p class="text-muted small" id="exportTableCount">{len(rows)} row(s), in execution order.</p>
"""


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Workflow Visualization - {workflow_name}</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.3/css/bootstrap.min.css" rel="stylesheet">
<style>
  body {{ background:#f4f6f9; }}
  .app-navbar {{ background:#1F3864; }}
  .section-navy {{ color:#1F3864; }}
  .graph-frame {{ width:100%; height:75vh; border:1px solid #dee2e6; background:#fff; }}
  .detail-panel {{
    position:fixed; top:0; right:-380px; width:360px; height:100%;
    background:#fff; box-shadow:-2px 0 10px rgba(0,0,0,.15);
    padding:16px; overflow-y:auto; transition:right .2s ease; z-index:1050;
  }}
  .detail-panel.open {{ right:0; }}
  th[data-sort] {{ cursor:pointer; user-select:none; white-space:nowrap; }}
  th[data-sort]:after {{ content:" \\21C5"; color:#adb5bd; font-size:.75em; }}
  .export-note {{ font-size:.8rem; color:#6c757d; }}
  #vizTabs {{ flex-wrap:wrap; }}
  .mapping-link, .mapplet-link {{ text-decoration:underline; }}
  .tab-close {{ margin-left:.4rem; color:#adb5bd; font-weight:bold; }}
  .tab-close:hover {{ color:#dc3545; }}
  .lineage-table {{ word-break:break-word; }}
</style>
</head>
<body>
  <nav class="navbar navbar-dark app-navbar px-3">
    <span class="navbar-brand mb-0 h1">Workflow Visualization (Downloaded Copy)</span>
    <span class="text-white-50 small">{workflow_name}</span>
  </nav>

  <div class="container-fluid p-3">
    <p class="export-note mb-3">
      Exported {generated_at}. All tabs stay interactive offline -- pan/zoom/click the graphs,
      search/sort the table, and click a Mapping Name to open its own lineage-graph tab -- only
      the graph and page styling load from a CDN, so keep an internet connection when you open
      this file.
    </p>

    <ul class="nav nav-tabs" id="vizTabs" role="tablist">
      <li class="nav-item" role="presentation">
        <button class="nav-link active" id="overview-tab" data-bs-toggle="tab" data-bs-target="#overview-pane" type="button">Overview</button>
      </li>
      <li class="nav-item" role="presentation">
        <button class="nav-link" id="table-tab" data-bs-toggle="tab" data-bs-target="#table-pane" type="button">Table View</button>
      </li>
    </ul>

    <div class="tab-content border border-top-0 p-3 bg-white" id="vizTabContent">
      <div class="tab-pane fade show active" id="overview-pane" role="tabpanel">
        <p class="text-muted small">Nodes are sessions; edges show execution flow. Click a session to view details. Zoom/pan/drag are built in.</p>
        <iframe class="graph-frame" id="graphFrame" srcdoc="{graph_srcdoc}"></iframe>
      </div>
      <div class="tab-pane fade" id="table-pane" role="tabpanel">
        <input type="text" class="form-control form-control-sm mb-2" id="tableSearch" placeholder="Search all columns...">
        <div id="tableViewContainer">{table_html}</div>
      </div>
    </div>
  </div>

  <div class="detail-panel" id="detailPanel">
    <div class="d-flex justify-content-between align-items-start mb-2">
      <h5 id="detailPanelTitle">Details</h5>
      <button type="button" class="btn-close" onclick="closeDetailPanel()"></button>
    </div>
    <div id="detailPanelBody"></div>
  </div>

  <script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.3/js/bootstrap.bundle.min.js"></script>
  <script>
    // Session detail data (Overview tab) and per-mapping drill-down data
    // (Table View tab's Mapping Name links) embedded at export time --
    // no server needed for either.
    var SESSION_DETAILS = {session_details_json};
    var MAPPING_DATA = {mapping_data_json};
    var MAPPLET_DATA = {mapplet_data_json};
    var DATA_BY_KIND = {{ mapping: MAPPING_DATA, mapplet: MAPPLET_DATA }};

    // Tracks which iframe element belongs to which dynamically-opened
    // mapping/mapplet tab, so a node-click message can be routed to the
    // right drill-down's instance/transformation data (see the "message"
    // listener below). Keyed by tabId -> {{kind, name, iframe}}. The static
    // Overview iframe is intentionally never added here -- a click that
    // doesn't match any entry falls back to treating the id as a session
    // name, same as before this feature existed.
    var DRILL_FRAMES = {{}};

    function openDetailPanel() {{ document.getElementById("detailPanel").classList.add("open"); }}
    function closeDetailPanel() {{ document.getElementById("detailPanel").classList.remove("open"); }}

    function renderKeyValueList(container, obj) {{
      var out = "<dl class='row mb-0'>";
      Object.keys(obj).forEach(function (k) {{
        var v = obj[k];
        if (Array.isArray(v)) v = v.length ? v.join(", ") : "(none)";
        var safeV = (v === null || v === undefined || v === "") ? "(none)" : String(v);
        out += "<dt class='col-5 text-muted small'>" + k + "</dt><dd class='col-7'>" + safeV + "</dd>";
      }});
      out += "</dl>";
      container.innerHTML = out;
    }}

    function showSessionDetail(sessionName) {{
      var data = SESSION_DETAILS[sessionName];
      if (!data) return;
      document.getElementById("detailPanelTitle").textContent = "Session: " + data.session_name;
      renderKeyValueList(document.getElementById("detailPanelBody"), {{
        "Session Name": data.session_name,
        "Mapping Name": data.mapping_name,
        "Tables Used": data.tables_used,
        "Transformations Used": data.transformations_used
      }});
      openDetailPanel();
    }}

    function showTransformationDetail(kind, name, instanceId) {{
      var mdata = (DATA_BY_KIND[kind] || {{}})[name];
      if (!mdata) return;
      var inst = mdata.instances[instanceId];
      // SOURCE/TARGET nodes intentionally have no detail panel, matching in-app behavior.
      if (!inst || inst.type !== "TRANSFORMATION") return;
      var t = mdata.transformations[inst.ref_name];
      if (!t) return;
      document.getElementById("detailPanelTitle").textContent = "Transformation: " + t.name;
      var portNames = function (ports) {{ return ports.map(function (p) {{ return p.name; }}); }};
      var exprText = t.expressions.map(function (e) {{ return e.port + " = " + e.expression; }}).join(" | ") || "(none)";
      var attrText = Object.keys(t.attributes).map(function (k) {{ return k + "=" + t.attributes[k]; }}).join(", ") || "(none)";
      renderKeyValueList(document.getElementById("detailPanelBody"), {{
        "Type": t.type,
        "Business Logic": t.business_logic,
        "Implementation Details": t.implementation_details,
        "Input Ports": portNames(t.input_ports),
        "Output Ports": portNames(t.output_ports),
        "Variable Ports": portNames(t.variable_ports),
        "Expressions": exprText,
        "Attributes": attrText
      }});
      openDetailPanel();
    }}

    // The embedded graphs (Overview + every mapping/mapplet drill-down)
    // each post a "node-click" message (same bridge used in-app); we
    // resolve it locally instead of hitting the server. event.source tells
    // us which iframe it came from, so drill-down graph clicks and the
    // Overview graph's session clicks are routed correctly even with
    // several graphs open at once.
    window.addEventListener("message", function (event) {{
      if (!event.data || event.data.type !== "node-click") return;
      var match = null;
      Object.keys(DRILL_FRAMES).forEach(function (tabId) {{
        var entry = DRILL_FRAMES[tabId];
        if (entry && entry.iframe && entry.iframe.contentWindow === event.source) match = entry;
      }});
      if (match) {{
        showTransformationDetail(match.kind, match.name, event.data.id);
      }} else {{
        showSessionDetail(event.data.id);
      }}
    }});

    // --- Table View: client-side search + column sort ---
    (function () {{
      var searchBox = document.getElementById("tableSearch");
      var table = document.getElementById("exportTable");
      if (!table) return;
      var tbody = table.querySelector("tbody");
      var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
      var countEl = document.getElementById("exportTableCount");
      var totalCount = rows.length;

      searchBox.addEventListener("input", function () {{
        var q = searchBox.value.trim().toLowerCase();
        var shown = 0;
        rows.forEach(function (r) {{
          var match = !q || r.textContent.toLowerCase().indexOf(q) !== -1;
          r.style.display = match ? "" : "none";
          if (match) shown++;
        }});
        countEl.textContent = shown + " of " + totalCount + " row(s) shown.";
      }});

      table.querySelectorAll("thead th").forEach(function (th, colIdx) {{
        th.setAttribute("data-sort", "1");
        var asc = true;
        th.addEventListener("click", function () {{
          var sorted = rows.slice().sort(function (a, b) {{
            var av = a.children[colIdx].textContent.trim().toLowerCase();
            var bv = b.children[colIdx].textContent.trim().toLowerCase();
            if (av < bv) return asc ? -1 : 1;
            if (av > bv) return asc ? 1 : -1;
            return 0;
          }});
          asc = !asc;
          sorted.forEach(function (r) {{ tbody.appendChild(r); }});
          rows = sorted;
        }});
      }});

      // Event delegation so Mapping Name / Mapplet links keep working after
      // search/sort reorders or hides rows.
      document.getElementById("tableViewContainer").addEventListener("click", function (ev) {{
        var mappingLink = ev.target.closest(".mapping-link");
        if (mappingLink) {{
          openDrillTab("mapping", mappingLink.getAttribute("data-mapping"));
          return;
        }}
        var mappletLink = ev.target.closest(".mapplet-link");
        if (mappletLink) {{
          openDrillTab("mapplet", mappletLink.getAttribute("data-mapplet"));
        }}
      }});
    }})();

    // --- Per-mapping/per-mapplet drill-down tabs, opened on demand from a
    // Mapping Name or Mapplet link. Generalized over "kind" so Mapplets get
    // the exact same offline drill-down tab (own lineage graph + clickable
    // transformation detail) that Mappings already had (minor
    // improvement-2). ---
    var _KIND_LABEL = {{ mapping: "Mapping", mapplet: "Mapplet" }};
    var _KIND_PREFIX = {{ mapping: "mtab_", mapplet: "pltab_" }};

    function _tabIdFor(kind, name) {{
      return _KIND_PREFIX[kind] + name.replace(/[^a-zA-Z0-9]/g, "_");
    }}

    function openDrillTab(kind, name) {{
      var tabId = _tabIdFor(kind, name);
      var existingBtn = document.getElementById(tabId + "_btn");
      if (existingBtn) {{
        new bootstrap.Tab(existingBtn).show();
        return;
      }}
      var mdata = (DATA_BY_KIND[kind] || {{}})[name];
      if (!mdata) return;

      var li = document.createElement("li");
      li.className = "nav-item";
      li.setAttribute("role", "presentation");

      var btn = document.createElement("button");
      btn.className = "nav-link";
      btn.id = tabId + "_btn";
      btn.type = "button";
      btn.setAttribute("data-bs-toggle", "tab");
      btn.setAttribute("data-bs-target", "#" + tabId + "_pane");

      var labelSpan = document.createElement("span");
      labelSpan.textContent = name;
      btn.appendChild(labelSpan);

      var closeSpan = document.createElement("span");
      closeSpan.textContent = "\\u00d7";
      closeSpan.className = "tab-close";
      closeSpan.title = "Close tab";
      closeSpan.addEventListener("click", function (ev) {{
        ev.stopPropagation();
        closeDrillTab(tabId, kind, name);
      }});
      btn.appendChild(closeSpan);

      li.appendChild(btn);
      document.getElementById("vizTabs").appendChild(li);

      var pane = document.createElement("div");
      pane.className = "tab-pane fade";
      pane.id = tabId + "_pane";
      pane.setAttribute("role", "tabpanel");

      var hint = document.createElement("p");
      hint.className = "text-muted small";
      hint.textContent = "Source -> Transformation(s) -> Target lineage for " + _KIND_LABEL[kind] + " \\u201c" + name + "\\u201d. Click a transformation node for details.";
      pane.appendChild(hint);

      var iframe = document.createElement("iframe");
      iframe.className = "graph-frame";
      iframe.id = tabId + "_frame";
      iframe.srcdoc = mdata.graph_srcdoc;
      pane.appendChild(iframe);

      var lineageCard = document.createElement("div");
      lineageCard.className = "card mt-3";
      var cardBody = document.createElement("div");
      cardBody.className = "card-body";
      var cardTitle = document.createElement("h6");
      cardTitle.className = "section-navy";
      cardTitle.textContent = "Transformation Data Lineage";
      var lineageP = document.createElement("p");
      lineageP.className = "lineage-table";
      lineageP.textContent = mdata.lineage.join(" \\u2192 ");
      cardBody.appendChild(cardTitle);
      cardBody.appendChild(lineageP);
      lineageCard.appendChild(cardBody);
      pane.appendChild(lineageCard);

      document.getElementById("vizTabContent").appendChild(pane);

      DRILL_FRAMES[tabId] = {{ kind: kind, name: name, iframe: iframe }};

      new bootstrap.Tab(btn).show();
    }}

    function closeDrillTab(tabId, kind, name) {{
      var btn = document.getElementById(tabId + "_btn");
      var pane = document.getElementById(tabId + "_pane");
      var wasActive = !!(btn && btn.classList.contains("active"));
      delete DRILL_FRAMES[tabId];
      if (btn && btn.closest("li")) btn.closest("li").remove();
      if (pane) pane.remove();
      if (wasActive) {{
        new bootstrap.Tab(document.getElementById("overview-tab")).show();
      }}
    }}
  </script>
</body>
</html>
"""


def generate_visualization_html(repo, graph_html: str, mapping_graphs: dict, mapplet_graphs: dict, out_path: str) -> str:
    """Builds the single standalone visualization HTML file.

    graph_html: the already-rendered PyVis overview graph markup (from
    graph_service.render_overview_graph), embedded verbatim as an
    <iframe srcdoc> so its pan/zoom/drag/click behaviour is unchanged.

    mapping_graphs: {mapping_name: rendered PyVis lineage-graph markup}
    for every mapping in the repo (from graph_service.mapping_graph_html),
    embedded so Table View's Mapping Name links can open a fully offline,
    interactive drill-down tab per mapping with no server calls.

    mapplet_graphs: {mapplet_name: rendered PyVis lineage-graph markup}
    for every mapplet in the repo (from graph_service.mapplet_graph_html) --
    minor improvement-2: Mapplets get the exact same offline drill-down
    tab as Mappings, embedded so Table View's Mapplet links also work
    with no server calls after download.
    """
    import os
    from datetime import datetime

    wf = repo.workflow
    workflow_name = wf.name if wf else "Workflow"
    rows = build_execution_table(repo)
    show_mapplet = has_any_mapplet(repo)

    page = _PAGE_TEMPLATE.format(
        workflow_name=html_lib.escape(workflow_name),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        graph_srcdoc=html_lib.escape(graph_html, quote=True),
        table_html=_table_rows_html(rows, show_mapplet, set(repo.mappings.keys()), set(repo.mapplets.keys())),
        session_details_json=_safe_json(_session_details(repo)),
        mapping_data_json=_safe_json(_mapping_data(repo, mapping_graphs)),
        mapplet_data_json=_safe_json(_mapplet_data(repo, mapplet_graphs)),
    )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path
