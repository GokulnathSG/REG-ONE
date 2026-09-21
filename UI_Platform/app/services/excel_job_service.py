"""In-memory background job tracking for the Transformation-wise Excel export.

The extraction can run for a long time against large Oracle repositories, so
the Flask route that starts it returns immediately with a job_id; the
front-end then polls /reports/generate-excel/status/<job_id> to show a
loading screen with a live "estimated time remaining" and finally downloads
the finished workbook from /reports/generate-excel/download/<job_id>.

This is intentionally a simple in-process dict guarded by a lock -- it is not
designed to survive an app restart or to work across multiple worker
processes. That matches how the rest of this Flask app is deployed (single
process, in-memory REPORTS_DIR).
"""
import os
import threading
import time
import uuid
from datetime import datetime

from app.generators import transformation_export as te

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")

_JOBS = {}
_LOCK = threading.Lock()

# How long a finished/failed job's Excel file and status stay around before
# being swept, so repeated polling / a slow download doesn't lose the file,
# but old temp workbooks don't pile up forever either.
_RETENTION_SECONDS = 60 * 30


def _now():
    return time.time()


def _sweep_locked():
    stale = [jid for jid, j in _JOBS.items()
             if j["status"] in ("done", "error")
             and (_now() - j["finished_at"]) > _RETENTION_SECONDS]
    for jid in stale:
        job = _JOBS.pop(jid, None)
        if job and job.get("output_path") and os.path.exists(job["output_path"]):
            try:
                os.remove(job["output_path"])
            except OSError:
                pass


def start_job(params):
    """Validate params, open the Oracle connection synchronously (so a bad
    password/DSN/schema fails fast with a clear error), then hand the actual
    extraction off to a background thread. Returns (job_id, error_message).
    On validation/connection failure, job_id is None and error_message is set.
    """
    db_user = (params.get("db_user") or "").strip()
    db_password = params.get("db_password") or ""
    dsn = (params.get("dsn") or "").strip()
    schema_prefix = (params.get("schema") or "").strip()
    subject_area = (params.get("subject_area") or "").strip()
    workflow = (params.get("workflow") or "").strip()
    mapping = (params.get("mapping") or "").strip() or None
    transformation_names_raw = params.get("transformation_names") or ""
    transformation_names = [transformation_names_raw] if transformation_names_raw else []

    missing = [label for label, value in (
        ("DB_USER", db_user), ("DB_PASSWORD", db_password), ("DSN", dsn),
        ("Subject Area", subject_area), ("Workflow", workflow),
    ) if not value]
    if missing:
        return None, f"Missing required field(s): {', '.join(missing)}."

    try:
        conn = te.connect_oracle(db_user, db_password, dsn)
    except Exception as exc:  # noqa: BLE001 - surface the driver's own error message
        return None, f"Connection failed: {exc}"

    with _LOCK:
        _sweep_locked()

    job_id = uuid.uuid4().hex
    safe_wf = "".join(c if c.isalnum() or c in "._-" else "_" for c in workflow) or "workflow"
    output_path = os.path.join(REPORTS_DIR, f"Transformations_{safe_wf}_{job_id}.xlsx")

    job = {
        "status": "running",
        "label": "Starting\u2026",
        "current_step": 0,
        "total_steps": 1,
        "started_at": _now(),
        "finished_at": None,
        "step_times": [],
        "last_step_at": _now(),
        "output_path": None,
        "download_name": f"Transformation_Details_{safe_wf}.xlsx",
        "error": None,
    }
    with _LOCK:
        _JOBS[job_id] = job

    def progress_cb(label, current, total):
        with _LOCK:
            j = _JOBS.get(job_id)
            if not j:
                return
            now = _now()
            if current > j["current_step"]:
                j["step_times"].append(now - j["last_step_at"])
                j["step_times"] = j["step_times"][-10:]  # rolling average, last 10 steps
            j["current_step"] = current
            j["total_steps"] = max(total, 1)
            j["label"] = label
            j["last_step_at"] = now

    def worker():
        try:
            path, _summary = te.generate_transformation_excel(
                conn, subject_area, workflow, mapping, transformation_names,
                schema_prefix, output_path, progress_cb=progress_cb,
            )
            with _LOCK:
                j = _JOBS.get(job_id)
                if j:
                    j["status"] = "done"
                    j["output_path"] = str(path)
                    j["finished_at"] = _now()
                    j["label"] = "Done"
        except Exception as exc:  # noqa: BLE001 - surfaced to the polling UI
            with _LOCK:
                j = _JOBS.get(job_id)
                if j:
                    j["status"] = "error"
                    j["error"] = str(exc)
                    j["finished_at"] = _now()
                    j["label"] = "Failed"
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=worker, daemon=True).start()
    return job_id, None


def get_status(job_id):
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None

        elapsed = (job["finished_at"] or _now()) - job["started_at"]
        avg_step = (sum(job["step_times"]) / len(job["step_times"])) if job["step_times"] else None
        remaining_steps = max(job["total_steps"] - job["current_step"], 0)
        eta_seconds = (avg_step * remaining_steps) if avg_step is not None else None

        return {
            "status": job["status"],
            "label": job["label"],
            "current_step": job["current_step"],
            "total_steps": job["total_steps"],
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
            "download_name": job["download_name"],
            "error": job["error"],
        }


def get_output_path(job_id):
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job or job["status"] != "done":
            return None, None
        return job["output_path"], job["download_name"]
