import os
from flask import Blueprint, render_template, request, send_file

from app.services.workflow_service import require_repo
from app.analyzer import field_lineage_analyzer as fla
from app.generators.field_lineage_excel_generator import generate_field_lineage_excel

bp = Blueprint("field_lineage", __name__)

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")


@bp.route("/field-lineage", methods=["GET"])
def field_lineage_page():
    repo = require_repo()
    return render_template("field_lineage.html", repo=repo)


@bp.route("/field-lineage", methods=["POST"])
def field_lineage_submit():
    repo = require_repo()
    identifier = (request.form.get("workflow_input") or "").strip()
    target_table = (request.form.get("target_table") or "").strip()
    instance_name = (request.form.get("instance") or "").strip()

    ctx = {"repo": repo, "workflow_input": identifier, "target_table": target_table,
           "instance": instance_name}

    if not identifier or not target_table:
        ctx["error"] = "Please enter a Workflow / Session / Mapping name and a Target Table."
        return render_template("field_lineage.html", **ctx)

    candidate_mappings = fla.resolve_identifier_to_mappings(repo, identifier)
    if not candidate_mappings:
        ctx["error"] = f"'{identifier}' did not match any Workflow, Session, or Mapping in this upload."
        return render_template("field_lineage.html", **ctx)

    # Narrow multi-mapping (Workflow-level) input down to mappings that actually contain the target table.
    mappings_with_target = [m for m in candidate_mappings if fla.find_target_instances(repo, m, target_table)]
    if len(candidate_mappings) > 1 and not mappings_with_target:
        ctx["error"] = (f"Target Table '{target_table}' was not found in any mapping under '{identifier}'. "
                         "Try entering the specific Session or Mapping name instead.")
        return render_template("field_lineage.html", **ctx)
    if len(mappings_with_target) > 1:
        ctx["error"] = (f"Target Table '{target_table}' appears in multiple mappings under '{identifier}' "
                         f"({', '.join(mappings_with_target)}). Please enter the specific Session or "
                         "Mapping name instead.")
        return render_template("field_lineage.html", **ctx)

    mapping_name = mappings_with_target[0] if mappings_with_target else candidate_mappings[0]
    target_instances = fla.find_target_instances(repo, mapping_name, target_table)
    if not target_instances:
        ctx["error"] = f"Target Table '{target_table}' was not found in mapping '{mapping_name}'."
        return render_template("field_lineage.html", **ctx)

    if len(target_instances) > 1 and not instance_name:
        ctx["mapping_name"] = mapping_name
        ctx["multi_instance_warning"] = (
            "The selected Target Table appears multiple times in this mapping. "
            "Please choose the required Transformation Instance."
        )
        ctx["instance_options"] = [
            {"name": inst.name,
             "producers": ", ".join(fla.producing_transformation_names(repo, mapping_name, inst.name)) or "(none)"}
            for inst in target_instances
        ]
        return render_template("field_lineage.html", **ctx)

    if instance_name:
        chosen = next((i for i in target_instances if i.name == instance_name), None)
        if chosen is None:
            ctx["error"] = f"'{instance_name}' is not a Target Table instance in mapping '{mapping_name}'."
            return render_template("field_lineage.html", **ctx)
    else:
        chosen = target_instances[0]

    session_name = fla.session_for_mapping(repo, mapping_name)
    ctx["mapping_name"] = mapping_name
    ctx["session_name"] = session_name
    ctx["instance"] = chosen.name
    ctx["ready"] = True
    ctx["field_count"] = len(fla.target_fields_for_instance(repo, mapping_name, chosen.name))
    return render_template("field_lineage.html", **ctx)


@bp.route("/field-lineage/download")
def field_lineage_download():
    repo = require_repo()
    mapping_name = request.args.get("mapping", "")
    instance_name = request.args.get("instance", "")
    session_name = request.args.get("session") or None

    rows = fla.build_field_lineage_rows_flat(repo, mapping_name, session_name, instance_name)
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in f"{mapping_name}_{instance_name}")
    out_path = os.path.join(REPORTS_DIR, f"Field_Lineage_{safe_name}.xlsx")
    path = generate_field_lineage_excel(rows, out_path)
    return send_file(path, as_attachment=True, download_name=f"Field_Lineage_{safe_name}.xlsx")


@bp.route("/field-lineage/download-all")
def field_lineage_download_all():
    """Whole-workflow flattened Field_Lineage workbook: every Target Table
    field, across every Mapping and Mapplet in the upload -- not just a
    single selected Target Table."""
    repo = require_repo()
    rows = fla.build_full_workflow_field_lineage(repo)
    wf_name = repo.workflow.name if repo.workflow else "workflow"
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in wf_name)
    out_path = os.path.join(REPORTS_DIR, f"Field_Lineage_{safe_name}.xlsx")
    path = generate_field_lineage_excel(rows, out_path)
    return send_file(path, as_attachment=True, download_name=f"Field_Lineage_{safe_name}.xlsx")
