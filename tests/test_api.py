import json
from pathlib import Path

import pytest

from app import create_app
from core.storage import Storage


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JANUSLINE_DATA", str(tmp_path / "data"))
    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def store(app) -> Storage:
    return app.config["STORAGE"]


def body(res) -> dict:
    return json.loads(res.data)


def make_brief(client, query: str = "Samsung Electronics", **extra) -> str:
    res = client.post("/api/briefs", json={"query": query, **extra})
    assert res.status_code == 201
    return body(res)["data"]["slug"]


def test_env_data_dir_used(app, tmp_path: Path) -> None:
    assert app.config["STORAGE"].root == (tmp_path / "data").resolve()


def test_explicit_data_dir_wins(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path / "explicit")
    assert app.config["STORAGE"].root == (tmp_path / "explicit").resolve()


def test_index_serves_shell(client) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert b"janusline" in res.data
    assert "default-src 'self'" in res.headers["Content-Security-Policy"]
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_list_empty_envelope(client) -> None:
    res = client.get("/api/briefs")
    assert res.status_code == 200
    assert body(res) == {"ok": True, "data": []}


def test_create_and_get(client) -> None:
    slug = make_brief(client, "Samsung Electronics", period_days=30, lang=["en"])
    assert slug == "samsung-electronics"

    res = client.get(f"/api/briefs/{slug}")
    assert res.status_code == 200
    data = body(res)["data"]
    assert data["schema"] == 1 and data["status"] == "empty"
    assert data["articles"] == [] and data["synthesis"] is None
    assert data["period_days"] == 30 and data["lang"] == ["en"]

    listed = body(client.get("/api/briefs"))["data"]
    assert len(listed) == 1 and listed[0]["slug"] == slug
    assert listed[0]["article_count"] == 0 and "articles" not in listed[0]


def test_create_defaults(client) -> None:
    slug = make_brief(client, "Default Shape")
    data = body(client.get(f"/api/briefs/{slug}"))["data"]
    assert data["period_days"] == 90 and data["lang"] == ["ko", "en"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 201},
        {"query": 12},
        {"query": "ok", "period_days": 45},
        {"query": "ok", "period_days": 0},
        {"query": "ok", "lang": ["jp"]},
        {"query": "ok", "lang": []},
    ],
)
def test_create_bad_request(client, payload: dict) -> None:
    res = client.post("/api/briefs", json=payload)
    assert res.status_code == 400
    assert body(res)["ok"] is False and body(res)["error"]


def test_query_length_boundary(client) -> None:
    assert client.post("/api/briefs", json={"query": "x" * 200}).status_code == 201
    assert client.post("/api/briefs", json={"query": "x" * 201}).status_code == 400


def test_create_rejects_non_object_body(client) -> None:
    assert client.post("/api/briefs", json=["nope"]).status_code == 400


@pytest.mark.parametrize("slug", ["..", "Upper", "x" * 65, "sp ace"])
def test_bad_slug_is_400(client, slug: str) -> None:
    assert client.get(f"/api/briefs/{slug}").status_code == 400


def test_path_traversal_rejected(client, tmp_path: Path) -> None:
    # encoded separators never reach the handler (routing 404), plain ones fail validation
    for path in ("/api/briefs/../../etc", "/api/briefs/a/b", "/api/briefs/..%2Fx"):
        assert client.get(path).status_code in (400, 404)
    assert client.get("/api/briefs/..").status_code == 400
    assert client.delete("/api/briefs/..").status_code == 400
    assert list((tmp_path / "data" / "briefs").iterdir()) == []


def test_missing_brief_404(client) -> None:
    res = client.get("/api/briefs/ghost")
    assert res.status_code == 404
    assert body(res) == {"ok": False, "error": "brief not found"}
    assert client.delete("/api/briefs/ghost").status_code == 404


def test_unknown_api_route_and_method(client) -> None:
    assert client.get("/api/nope").status_code == 404
    assert body(client.get("/api/nope"))["ok"] is False
    res = client.put("/api/briefs")
    assert res.status_code == 405 and body(res)["ok"] is False


def test_delete_moves_to_trash(client, store: Storage) -> None:
    slug = make_brief(client)
    res = client.delete(f"/api/briefs/{slug}")
    assert res.status_code == 200 and body(res)["data"]["slug"] == slug
    assert body(client.get("/api/briefs"))["data"] == []
    trashed = list(store.trash_dir.iterdir())
    assert len(trashed) == 1 and trashed[0].name.startswith(f"{slug}-")


def test_dedupe_slugs_via_api(client) -> None:
    assert make_brief(client, "Same Name") == "same-name"
    assert make_brief(client, "Same Name") == "same-name-2"
