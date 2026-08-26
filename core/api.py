"""REST API blueprint. Every response uses the {ok, data|error} envelope."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from flask import Blueprint, Response, current_app, jsonify, request

from .schema import BriefNotFound, StorageError
from .storage import Storage

api_bp = Blueprint("api", __name__, url_prefix="/api")


def ok(data: Any, status: int = 200) -> Tuple[Response, int]:
    return jsonify({"ok": True, "data": data}), status


def fail(message: str, status: int, **extra: Any) -> Tuple[Response, int]:
    payload: Dict[str, Any] = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def store() -> Storage:
    return current_app.config["STORAGE"]


def _payload() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    return body


@api_bp.get("/briefs")
def list_briefs() -> Tuple[Response, int]:
    return ok(store().list_briefs())


@api_bp.post("/briefs")
def create_brief() -> Tuple[Response, int]:
    body = _payload()
    brief = store().create_brief(
        query=body.get("query"),
        period_days=body.get("period_days"),
        lang=body.get("lang"),
    )
    return ok({"slug": brief["slug"]}, 201)


@api_bp.get("/briefs/<slug>")
def get_brief(slug: str) -> Tuple[Response, int]:
    return ok(store().load_brief(slug))


@api_bp.delete("/briefs/<slug>")
def delete_brief(slug: str) -> Tuple[Response, int]:
    trashed = store().delete_brief(slug)
    return ok({"slug": slug, "trashed": trashed})


def register_errors(app) -> None:
    """JSON envelope for API errors, including framework-raised ones."""

    @app.errorhandler(ValueError)
    def _bad_request(err: ValueError):
        return fail(str(err) or "bad request", 400)

    @app.errorhandler(BriefNotFound)
    def _not_found(err: BriefNotFound):
        return fail("brief not found", 404)

    @app.errorhandler(StorageError)
    def _storage(err: StorageError):
        return fail(str(err) or "storage error", 500)

    @app.errorhandler(404)
    def _http_404(err):
        if request.path.startswith("/api/"):
            return fail("not found", 404)
        return err

    @app.errorhandler(405)
    def _http_405(err):
        if request.path.startswith("/api/"):
            return fail("method not allowed", 405)
        return err
