import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200 MB; tune per environment/deployment gateway limits
    UPLOAD_DIR = os.path.join(BASE_DIR, "app", "uploads")
    REPORTS_DIR = os.path.join(BASE_DIR, "app", "reports")
    GRAPHS_DIR = os.path.join(BASE_DIR, "app", "static", "graphs")
    JSON_SORT_KEYS = False
