import os
from app.generators.excel_generator import generate_overview_workflow_excel
from app.generators.informatica_xml_downloads_generator import generate_informatica_xml_downloads_excel
from app.generators.html_visualization_generator import generate_visualization_html
from app.generators.reportability_html_generator import generate_reportability_html
from app.services import graph_service
from app.analyzer import reportability_analyzer as ra

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")


def overview_excel_path(repo) -> str:
    """The single supported document output: one .xlsx workbook with the
    Session-Mapping and Table-Transformation tabs, built purely from the
    parsed XML/JSON."""
    out = os.path.join(REPORTS_DIR, "Overview_Workflow.xlsx")
    return generate_overview_workflow_excel(repo, out)


def xml_downloads_excel_path(repo) -> str:
    """Generate the extended XML-download workbook (Field lineage,
    referenced lookup tables, eligibility rules, and summary)."""
    out = os.path.join(REPORTS_DIR, "Informatica_XML_Downloads.xlsx")
    return generate_informatica_xml_downloads_excel(repo, out)


def visualization_html_path(repo) -> str:
    """Standalone, self-contained HTML export of the Visualization page:
    Overview graph tab + Table View tab, both still interactive after
    download (no server calls needed). Table View's Mapping Name links also
    open an offline drill-down tab per mapping (its own lineage graph +
    clickable transformation detail), so every mapping's graph is
    pre-rendered here and embedded alongside the overview graph."""
    graph_html = graph_service.overview_graph_html(repo)
    mapping_graphs = {name: graph_service.mapping_graph_html(repo, name) for name in repo.mappings}
    # Minor improvement-2: Mapplets get their own Visual Link/drill-down
    # tab in the downloaded HTML too, same as Mappings.
    mapplet_graphs = {name: graph_service.mapplet_graph_html(repo, name) for name in repo.mapplets}
    out = os.path.join(REPORTS_DIR, "Workflow_Visualization.html")
    return generate_visualization_html(repo, graph_html, mapping_graphs, mapplet_graphs, out)


def reportability_html_path(repo, mapping_name: str, table_name: str, instance_name: str,
                            session_name: str, attributes) -> str:
    """Standalone Reportability HTML export for one Mapping/Table/Instance.
    Embeds every requested attribute's own Mapping-wise lineage panels and
    node-detail payloads so the file stays interactive after download."""
    attribute_payloads = []
    for attr in attributes:
        graph_data = ra.build_attribute_lineage_graph(repo, mapping_name, session_name or None, instance_name, attr)
        if graph_data is None:
            continue
        grouping = ra.group_by_mapping(repo, graph_data)
        graph_html = graph_service.reportability_graph_html_by_mapping(graph_data, grouping)
        panels = [
            {
                "mapping": panel_mapping,
                "node_count": grouping["panels"][panel_mapping]["node_count"],
                "incoming": grouping["panels"][panel_mapping]["incoming"],
                "outgoing": grouping["panels"][panel_mapping]["outgoing"],
                "is_final": panel_mapping == graph_data["final_mapping"],
                "graph_srcdoc": graph_html[panel_mapping],
            }
            for panel_mapping in grouping["order"]
        ]
        attribute_payloads.append({
            "field_name": attr,
            "nodes": graph_data["nodes"],
            "cycle_notes": graph_data.get("cycle_notes") or [],
            "panels": panels,
        })

    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in f"{mapping_name}_{instance_name}") or "Reportability"
    out = os.path.join(REPORTS_DIR, f"Reportability_{safe_name}.html")
    return generate_reportability_html(mapping_name, table_name, instance_name, session_name or "",
                                       list(attributes), attribute_payloads, out)
