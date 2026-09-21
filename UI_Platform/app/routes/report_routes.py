from flask import Blueprint, render_template, request, jsonify, send_file

from app.services import excel_job_service
from app.generators import transformation_export as _te

bp = Blueprint("report", __name__)


@bp.route("/reports")
def reports_page():
    """Informatica ORACLE DB Connector page (previously 'Printable Reports').
    The Overview Workflow Excel and Workflow Visualization HTML downloads
    that used to live here now live under Informatica XML Downloads.

    Minor improvement-1: this page is independent of whether an Informatica
    XML/JSON export has been uploaded yet - the Oracle credentials form
    should always be reachable, so no require_repo() gate here."""
    return render_template("reports.html")


@bp.route("/reports/db-connect", methods=["POST"])
def db_connect():
    """Attempt an Oracle DB connection with the submitted credentials.
    Uses python-oracledb in thin mode (no Oracle client install required)."""
    data = request.get_json(silent=True) or {}
    db_user = (data.get("db_user") or "").strip()
    db_password = data.get("db_password") or ""
    dsn = (data.get("dsn") or "").strip()
    schema = (data.get("schema") or "").strip()

    if not db_user or not db_password or not dsn:
        return jsonify({"ok": False, "message": "DB_USER, DB_PASSWORD and DSN are all required."}), 400

    # Normalize the schema the way the UI displays it: "schema_name."
    schema_qualifier = f"{schema}." if schema and not schema.endswith(".") else schema

    try:
        connection = _te.connect_oracle(db_user, db_password, dsn)
        connection.close()
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 500
    except Exception as exc:  # noqa: BLE001 - surface the driver's own error message
        return jsonify({"ok": False, "message": f"Connection failed: {exc}"}), 400

    return jsonify({
        "ok": True,
        "message": f"Connected to {dsn} as {db_user}"
                   + (f" (schema: {schema_qualifier})" if schema_qualifier else "") + "."
    })


@bp.route("/reports/generate-excel/start", methods=["POST"])
def generate_excel_start():
    """Kick off the Transformation-wise Excel export as a background job.
    Re-uses the same Oracle credentials the person already validated on this
    page, plus the Subject Area / Workflow / Mapping / Transformation-name(s)
    typed into the query form. Returns immediately with a job_id that the
    front-end polls for progress and a final download link."""
    data = request.get_json(silent=True) or {}
    job_id, error = excel_job_service.start_job(data)
    if error:
        return jsonify({"ok": False, "message": error}), 400
    return jsonify({"ok": True, "job_id": job_id})


@bp.route("/reports/generate-excel/status/<job_id>")
def generate_excel_status(job_id):
    status = excel_job_service.get_status(job_id)
    if not status:
        return jsonify({"ok": False, "message": "Unknown or expired job."}), 404
    return jsonify({"ok": True, **status})


@bp.route("/reports/generate-excel/download/<job_id>")
def generate_excel_download(job_id):
    path, download_name = excel_job_service.get_output_path(job_id)
    if not path:
        return jsonify({"ok": False, "message": "File not ready yet."}), 400
    return send_file(path, as_attachment=True, download_name=download_name)
