"""Builds the standalone Reportability HTML deliverable.

The exported file keeps the Reportability screen interactive after download:
users can click any listed attribute, switch across Mapping-wise lineage tabs,
and click graph nodes to see the same embedded detail payload with no Flask
backend round-trip.
"""
import html as html_lib
import json
import os
from datetime import datetime


def _safe_json(obj) -> str:
    return json.dumps(obj).replace("</", "<\\/")


def _attribute_list_html(attributes) -> str:
    items = []
    for idx, attr in enumerate(attributes):
        safe_attr = html_lib.escape(attr)
        active = " active" if idx == 0 else ""
        items.append(
            f'<button type="button" class="list-group-item list-group-item-action{active} reportability-attr-link" '
            f'data-attr="{safe_attr}">{safe_attr}</button>'
        )
    return "".join(items)


def _badge_html(items, template: str) -> str:
    badges = []
    for item in items:
        badges.append(template.format(
            mapping=html_lib.escape(item["mapping"]),
            count=item["count"],
            plural="s" if item["count"] != 1 else "",
        ))
    return "".join(badges)


def _attribute_sections_html(attribute_payloads) -> str:
    sections = []
    for idx, payload in enumerate(attribute_payloads):
        attr = payload["field_name"]
        safe_attr = html_lib.escape(attr)
        section_classes = "reportability-attribute-section"
        if idx != 0:
            section_classes += " d-none"

        cycle_html = ""
        if payload["cycle_notes"]:
            cycle_html = (
                '<div class="alert alert-warning small mb-3">'
                'This chain passes through a staging table that is both written and read by more than one '
                f'mapping. {len(payload["cycle_notes"])} cross-session link(s) that would have looped back on '
                'an earlier point were skipped to keep the diagram readable.'
                '</div>'
            )

        tab_buttons = []
        tab_panes = []
        for panel_idx, panel in enumerate(payload["panels"], start=1):
            tab_id = f"attr_{idx}_tab_{panel_idx}"
            active = " active" if panel["is_final"] else ""
            selected = "true" if panel["is_final"] else "false"
            target_badge = '<span class="badge rounded-pill ms-1 bg-danger">target</span>' if panel["is_final"] else ""
            tab_buttons.append(
                '<li class="nav-item" role="presentation">'
                f'<button class="nav-link{active}" id="{tab_id}_btn" data-bs-toggle="tab" '
                f'data-bs-target="#{tab_id}_pane" type="button" role="tab" aria-selected="{selected}">'
                f'{html_lib.escape(panel["mapping"])} '
                f'<span class="badge rounded-pill ms-1" style="background-color:#DCE6F1;color:#1F3864;">{panel["node_count"]}</span>'
                f'{target_badge}'
                '</button></li>'
            )

            incoming = _badge_html(
                panel["incoming"],
                '<span class="badge text-bg-light border">&larr; from <strong>{mapping}</strong> ({count} link{plural})</span>',
            )
            outgoing = _badge_html(
                panel["outgoing"],
                '<span class="badge text-bg-light border">feeds &rarr; <strong>{mapping}</strong> ({count} link{plural})</span>',
            )
            cross_html = ""
            if incoming or outgoing:
                cross_html = f'<div class="d-flex flex-wrap gap-2 mb-2 small">{incoming}{outgoing}</div>'

            tab_panes.append(
                f'<div class="tab-pane fade{" show active" if panel["is_final"] else ""}" id="{tab_id}_pane" role="tabpanel">'
                f'{cross_html}'
                f'<iframe class="graph-frame reportability-graph-frame" data-attr="{safe_attr}" '
                f'data-mapping="{html_lib.escape(panel["mapping"])}" srcdoc="{html_lib.escape(panel["graph_srcdoc"], quote=True)}"></iframe>'
                '</div>'
            )

        sections.append(
            f'<section class="{section_classes}" data-attr-section="{safe_attr}">'
            f'<h5 class="section-navy mb-2">{safe_attr}</h5>'
            f'{cycle_html}'
            f'<ul class="nav nav-tabs" role="tablist">{"".join(tab_buttons)}</ul>'
            f'<div class="tab-content border border-top-0 rounded-bottom bg-white p-3 mb-3">{"".join(tab_panes)}</div>'
            '</section>'
        )
    return "".join(sections)


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reportability - {mapping_name}</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.3/css/bootstrap.min.css" rel="stylesheet">
<style>
  body {{ background:#f4f6f9; }}
  .app-navbar {{ background:#1F3864; }}
  .section-navy {{ color:#1F3864; }}
  .graph-frame {{ width:100%; height:70vh; border:1px solid #dee2e6; background:#fff; }}
  .detail-panel {{
    position:fixed; top:0; right:-380px; width:360px; height:100%;
    background:#fff; box-shadow:-2px 0 10px rgba(0,0,0,.15);
    padding:16px; overflow-y:auto; transition:right .2s ease; z-index:1050;
  }}
  .detail-panel.open {{ right:0; }}
  .legend-dot {{ width:.9rem; height:.9rem; display:inline-block; border-radius:50%; margin-right:.35rem; vertical-align:-.05rem; }}
  .attribute-list {{ max-height:78vh; overflow:auto; }}
  .reportability-workspace {{ min-height:78vh; }}
</style>
</head>
<body>
  <nav class="navbar navbar-dark app-navbar px-3">
    <span class="navbar-brand mb-0 h1">Reportability (Downloaded Copy)</span>
    <span class="text-white-50 small">{mapping_name} / {table_name} / {instance_name}</span>
  </nav>

  <div class="container-fluid p-3">
    <p class="text-muted small mb-3">
      Exported {generated_at}. This file stays interactive after download: click any attribute to open its
      Mapping-wise lineage view, then click graph nodes to see embedded details. The graph rendering and
      styling load from a CDN, so keep an internet connection when opening this file.
    </p>

    <div class="card mb-3">
      <div class="card-body py-2">
        <div class="small text-muted">
          Mapping: <strong>{mapping_name}</strong> &middot;
          Session: <strong>{session_name}</strong> &middot;
          Table: <strong>{table_name}</strong> &middot;
          Instance: <strong>{instance_name}</strong> &middot;
          {attribute_count} attribute(s) with wired lineage.
        </div>
      </div>
    </div>

    <div class="d-flex flex-wrap gap-3 mb-3 small">
      <span><span class="legend-dot" style="background:#2E8B57;"></span>Source</span>
      <span><span class="legend-dot" style="background:#3C8DBC;"></span>Pass-through</span>
      <span><span class="legend-dot" style="background:#E67E22;"></span>Logic applied</span>
      <span><span class="legend-dot" style="background:#8E44AD;"></span>Mapplet</span>
      <span><span class="legend-dot" style="background:#A0522D;"></span>Previous-session Target</span>
      <span><span class="legend-dot" style="background:#B22222;"></span>Final Target</span>
    </div>

    <div class="row g-3">
      <div class="col-lg-3">
        <div class="card attribute-list">
          <div class="card-body p-0">
            <div class="list-group list-group-flush" id="attributeList">{attribute_list_html}</div>
          </div>
        </div>
      </div>
      <div class="col-lg-9">
        <div class="reportability-workspace" id="attributeSections">{attribute_sections_html}</div>
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
    var REPORTABILITY_EXPORT = {reportability_json};

    function openDetailPanel() {{ document.getElementById("detailPanel").classList.add("open"); }}
    function closeDetailPanel() {{ document.getElementById("detailPanel").classList.remove("open"); }}

    function renderKeyValueList(container, obj) {{
      var html = "<dl class='row mb-0'>";
      Object.keys(obj).forEach(function (k) {{
        var v = obj[k];
        if (Array.isArray(v)) v = v.length ? v.join(", ") : "(none)";
        html += "<dt class='col-5 text-muted small'>" + k + "</dt><dd class='col-7'>" + ((v || v === 0) ? v : "(none)") + "</dd>";
      }});
      html += "</dl>";
      container.innerHTML = html;
    }}

    function showAttribute(attr) {{
      document.querySelectorAll("[data-attr-section]").forEach(function (section) {{
        section.classList.toggle("d-none", section.getAttribute("data-attr-section") !== attr);
      }});
      document.querySelectorAll(".reportability-attr-link").forEach(function (btn) {{
        btn.classList.toggle("active", btn.getAttribute("data-attr") === attr);
      }});
    }}

    function loadReportabilityPanel(attr, nodeId) {{
      var nodes = ((REPORTABILITY_EXPORT[attr] || {{}}).nodes) || {{}};
      var n = nodes[nodeId];
      if (!n) return;
      var title, fields;
      if (n.kind === "TARGET_FINAL") {{
        title = "Target Field";
        fields = {{ "Field Name": n.field }};
      }} else if (n.kind === "TARGET_INTERMEDIATE") {{
        title = "Previous Session Target: " + (n.table || n.instance);
        fields = {{
          "Next Session Name": n.next_session,
          "Next Mapping Name": n.next_mapping,
          "Session Source Table": n.next_source_table
        }};
      }} else if (n.kind === "SOURCE") {{
        title = "Source: " + (n.table || n.instance);
        fields = {{
          "Source Qualifier": n.source_qualifier,
          "Last Session Name": n.final_session,
          "Target Table Name": n.final_target_table
        }};
      }} else if (n.kind === "MAPPLET") {{
        title = "Mapplet: " + n.instance;
        fields = {{
          "Mapping": n.mapping,
          "Session": n.session,
          "Field": n.field,
          "Note": n.logic
        }};
      }} else {{
        title = "Transformation: " + n.instance;
        fields = {{
          "Mapping": n.mapping,
          "Session": n.session,
          "Type": n.ttype,
          "Classification": n.passthrough ? "Direct pass-through" : "Logic applied",
          "Logic": n.logic
        }};
        if (n.mapplet) fields["Inside Mapplet"] = n.mapplet;
      }}
      document.getElementById("detailPanelTitle").textContent = title;
      renderKeyValueList(document.getElementById("detailPanelBody"), fields);
      openDetailPanel();
    }}

    document.getElementById("attributeList").addEventListener("click", function (event) {{
      var btn = event.target.closest(".reportability-attr-link");
      if (!btn) return;
      showAttribute(btn.getAttribute("data-attr"));
    }});

    window.addEventListener("message", function (event) {{
      if (!event.data || event.data.type !== "node-click") return;
      var matched = null;
      document.querySelectorAll(".reportability-graph-frame").forEach(function (frame) {{
        if (!matched && frame.contentWindow === event.source) matched = frame;
      }});
      if (!matched) return;
      var attr = matched.getAttribute("data-attr");
      loadReportabilityPanel(attr, event.data.id);
    }});
  </script>
</body>
</html>
"""


def generate_reportability_html(mapping_name: str, table_name: str, instance_name: str,
                                session_name: str, attributes, attribute_payloads, out_path: str) -> str:
    export_payload = {
        payload["field_name"]: {"nodes": payload["nodes"]}
        for payload in attribute_payloads
    }

    page = _PAGE_TEMPLATE.format(
        mapping_name=html_lib.escape(mapping_name),
        table_name=html_lib.escape(table_name),
        instance_name=html_lib.escape(instance_name),
        session_name=html_lib.escape(session_name or "(none)"),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        attribute_count=len(attributes),
        attribute_list_html=_attribute_list_html(attributes),
        attribute_sections_html=_attribute_sections_html(attribute_payloads),
        reportability_json=_safe_json(export_payload),
    )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(page)
    return out_path