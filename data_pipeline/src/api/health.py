"""GET /health: liveness for deploy checks. No database or other dependency."""

from flask import Blueprint, current_app, jsonify

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok", version=current_app.config["APP_VERSION"])
