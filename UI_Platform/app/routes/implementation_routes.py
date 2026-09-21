from flask import Blueprint, render_template, send_file

from app.services.workflow_service import require_repo
from app.services import document_service

bp = Blueprint("implementation", __name__)


@bp.route("/implementation")
def implementation_page():
    repo = require_repo()
    return render_template("implementation.html", repo=repo)


@bp.route("/implementation/overview-workflow/download")
def download_overview_workflow():
    repo = require_repo()
    path = document_service.overview_excel_path(repo)
    return send_file(path, as_attachment=True, download_name="Overview_Workflow.xlsx")


@bp.route("/implementation/xml-downloads/download")
def download_xml_downloads_workbook():
    repo = require_repo()
    path = document_service.xml_downloads_excel_path(repo)
    return send_file(path, as_attachment=True, download_name="Informatica_XML_Downloads.xlsx")


@bp.route("/implementation/visualization/download")
def download_visualization_html():
    """Workflow Visualization (HTML) download -- moved here from the old
    Printable Reports section (now the Informatica ORACLE DB Connector page)."""
    repo = require_repo()
    path = document_service.visualization_html_path(repo)
    return send_file(path, as_attachment=True, download_name="Workflow_Visualization.html")
