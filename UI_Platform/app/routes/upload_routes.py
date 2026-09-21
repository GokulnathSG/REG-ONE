import os
from flask import Blueprint, render_template, request, redirect, url_for, current_app

from app.services.workflow_service import load_from_upload, UploadError

bp = Blueprint("upload", __name__)


@bp.route("/", methods=["GET"])
@bp.route("/upload", methods=["GET"])
def upload_page():
    return render_template("upload.html")


@bp.route("/upload", methods=["POST"])
def upload_submit():
    file_storage = request.files.get("file")
    if file_storage is None or file_storage.filename == "":
        return render_template("upload.html", error="Please choose a file to upload."), 400

    upload_dir = os.path.join(current_app.root_path, "uploads")
    try:
        load_from_upload(file_storage, upload_dir)
    except UploadError as e:
        return render_template("upload.html", error=e.message), 400

    return redirect(url_for("visualization.workflow_overview"))
