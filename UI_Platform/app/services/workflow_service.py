"""Orchestration layer. Owns the (single-process, in-memory) cache of the
most recently uploaded workflow. Good enough for the no-DB, small-team
release described in the TDD; swap `_CACHE` for a session- or DB-backed
store if multi-user isolation is needed later.
"""
import os
import uuid
from werkzeug.utils import secure_filename

from app.parsers.json_parser import parse_json_file, JsonParseError
from app.parsers.xml_parser import parse_xml_file
from app.parsers.tree_utils import XmlParseError
from app.analyzer.workflow_analyzer import (
    compute_execution_order, build_execution_table, has_any_mapplet,
    build_mapping_lineage, all_mapping_lineages,
)

_CACHE = {"repo": None, "filename": None}

ALLOWED_EXTENSIONS = {"xml", "json"}


class UploadError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def load_from_upload(file_storage, upload_dir: str):
    filename = secure_filename(file_storage.filename or "")
    if not filename or not allowed_file(filename):
        raise UploadError("UNSUPPORTED_FORMAT", "Only .xml and .json files are supported.")

    ext = filename.rsplit(".", 1)[1].lower()
    os.makedirs(upload_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    path = os.path.join(upload_dir, unique_name)
    file_storage.save(path)

    try:
        if ext == "json":
            repo = parse_json_file(path, source_file=filename)
        else:
            repo = parse_xml_file(path, source_file=filename)
    except (JsonParseError, XmlParseError) as e:
        raise UploadError("INVALID_XML" if ext == "xml" else "INVALID_JSON", str(e))

    if repo.workflow is None:
        raise UploadError("VALIDATION_FAILED", "No <WORKFLOW> element was found in the uploaded export.")

    compute_execution_order(repo)
    _CACHE["repo"] = repo
    _CACHE["filename"] = filename
    return repo


def get_repo():
    return _CACHE["repo"]


def get_filename():
    return _CACHE["filename"]


def require_repo():
    repo = get_repo()
    if repo is None:
        raise UploadError("NO_WORKFLOW_LOADED", "No workflow has been uploaded yet.")
    return repo


def get_execution_table():
    repo = require_repo()
    return build_execution_table(repo), has_any_mapplet(repo)


def get_mapping_lineage_table():
    repo = require_repo()
    return all_mapping_lineages(repo)
