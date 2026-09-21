from flask import Blueprint, render_template, jsonify, request

from app.services.workflow_service import require_repo, get_execution_table, UploadError
from app.services import graph_service
from app.analyzer.workflow_analyzer import build_mapping_lineage, build_mapplet_lineage

bp = Blueprint("visualization", __name__)


@bp.route("/workflow")
def workflow_overview():
    repo = require_repo()
    graph_path = graph_service.render_overview_graph(repo)
    return render_template("workflow_overview.html", repo=repo, graph_path=graph_path)


@bp.route("/table-view")
def table_view():
    rows, show_mapplet = get_execution_table()
    return render_template("table_view.html", rows=rows, show_mapplet=show_mapplet)


@bp.route("/graph")
def graph_api():
    repo = require_repo()
    graph_type = request.args.get("type", "overview")
    if graph_type == "mapping":
        mapping_name = request.args.get("mapping", "")
        if mapping_name not in repo.mappings:
            return jsonify({"error": {"code": "MAPPING_NOT_FOUND", "message": f"Mapping '{mapping_name}' not found."}}), 404
        return jsonify(graph_service.mapping_graph_json(repo, mapping_name))
    if graph_type == "mapplet":
        mapplet_name = request.args.get("mapplet", "")
        if mapplet_name not in repo.mapplets:
            return jsonify({"error": {"code": "MAPPLET_NOT_FOUND", "message": f"Mapplet '{mapplet_name}' not found."}}), 404
        return jsonify(graph_service.mapplet_graph_json(repo, mapplet_name))
    return jsonify(graph_service.overview_graph_json(repo))


@bp.route("/mapping/<mapping_name>")
def mapping_detail(mapping_name):
    repo = require_repo()
    if mapping_name not in repo.mappings:
        return render_template("error.html", message=f"Mapping '{mapping_name}' not found."), 404
    graph_path = graph_service.render_mapping_graph(repo, mapping_name)
    mapping = repo.mappings[mapping_name]
    lineage = build_mapping_lineage(repo, mapping_name)
    return render_template("mapping_detail.html", mapping=mapping, graph_path=graph_path, lineage=lineage)


@bp.route("/mapplet/<mapplet_name>")
def mapplet_detail(mapplet_name):
    """Minor improvement-2: Mapplets get their own drill-down Visual Link
    in Table View, mirroring the in-app Mapping page (its own
    Source->Target lineage graph, with click-a-transformation detail)."""
    repo = require_repo()
    if mapplet_name not in repo.mapplets:
        return render_template("error.html", message=f"Mapplet '{mapplet_name}' not found."), 404
    graph_path = graph_service.render_mapplet_graph(repo, mapplet_name)
    mapplet = repo.mapplets[mapplet_name]
    lineage = build_mapplet_lineage(repo, mapplet_name)
    return render_template("mapplet_detail.html", mapplet=mapplet, graph_path=graph_path, lineage=lineage)


@bp.route("/session/<session_name>")
def session_panel(session_name):
    repo = require_repo()
    session = repo.workflow.sessions.get(session_name)
    if session is None:
        return jsonify({"error": {"code": "SESSION_NOT_FOUND", "message": f"Session '{session_name}' not found."}}), 404
    mapping = repo.mappings.get(session.mapping_name)
    tables_used = sorted(set((mapping.sources if mapping else []) + (mapping.targets if mapping else [])))
    transforms_used = mapping.transformations if mapping else []
    return jsonify({
        "session_name": session.name,
        "mapping_name": session.mapping_name,
        "tables_used": tables_used,
        "transformations_used": transforms_used,
    })


@bp.route("/transformation/<name>")
def transformation_panel(name):
    repo = require_repo()
    mapping_name = request.args.get("mapping", "")
    t = repo.transformation(mapping_name, name)
    if t is None:
        return jsonify({"error": {"code": "TRANSFORMATION_NOT_FOUND",
                                   "message": f"Transformation '{name}' not found."}}), 404
    return jsonify({
        "name": t.name, "type": t.type,
        "business_logic": t.business_logic or "(not applicable for this transformation type)",
        "implementation_details": t.implementation_notes,
        "input_ports": [p.to_dict() for p in t.input_ports],
        "output_ports": [p.to_dict() for p in t.output_ports],
        "variable_ports": [p.to_dict() for p in t.variable_ports],
        "expressions": t.expressions,
        "attributes": t.attributes,
    })
