import json
import time
from pathlib import Path

import pytest
from support import StubCollector

from app import create_app
from core import auth
from core.fake_llm import FakeText

TOKEN = "example-auth-token-0000"  # placeholder fixture value, not a real credential
QUERY = {"query": "Samsung Electronics"}


def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str = ""):
    monkeypatch.setenv("JANUSLINE_DATA", str(tmp_path / "data"))
    if token:
        monkeypatch.setenv("AUTH_TOKEN", token)
    else:
        monkeypatch.delenv("AUTH_TOKEN", raising=False)
    application = create_app(collector=StubCollector(), llm=FakeText())
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture()
def open_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    return build(tmp_path, monkeypatch)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    return build(tmp_path, monkeypatch, TOKEN)


def body(res) -> dict:
    return json.loads(res.data)


def login(client, token: str = TOKEN):
    return client.post("/login", data={"token": token})


def brief_slug(client) -> str:
    res = client.post("/api/briefs", json=QUERY, headers={"Origin": "http://localhost"})
    assert res.status_code == 201
    return body(res)["data"]["slug"]


# --- open mode -------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/api/briefs"])
def test_open_mode_needs_no_cookie(open_client, path: str) -> None:
    assert open_client.get(path).status_code == 200


def test_open_mode_mutation_without_origin_header(open_client) -> None:
    assert open_client.post("/api/briefs", json=QUERY).status_code == 201


def test_open_mode_has_no_login_route(open_client) -> None:
    assert open_client.get("/login").status_code == 404


# --- gate ------------------------------------------------------------------


def test_api_without_cookie_is_401_envelope(client) -> None:
    res = client.get("/api/briefs")
    assert res.status_code == 401
    assert body(res) == {"ok": False, "error": "unauthorized"}


def test_ui_without_cookie_redirects_to_login(client) -> None:
    res = client.get("/")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/login")


@pytest.mark.parametrize("path", ["/login", "/static/style.css"])
def test_exempt_paths_reachable_without_cookie(client, path: str) -> None:
    assert client.get(path).status_code == 200


def test_wrong_token_is_401_and_sets_no_cookie(client) -> None:
    res = login(client, "nope")
    assert res.status_code == 401
    assert b"Invalid token" in res.data
    assert auth.COOKIE_NAME not in res.headers.get("Set-Cookie", "")


def test_correct_token_sets_cookie_and_grants_access(client) -> None:
    res = login(client)
    assert res.status_code == 302
    cookie = res.headers["Set-Cookie"]
    assert cookie.startswith(f"{auth.COOKIE_NAME}=")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert client.get("/api/briefs").status_code == 200


def test_logout_clears_cookie(client) -> None:
    login(client)
    res = client.get("/logout")
    assert res.status_code == 302
    assert client.get("/api/briefs").status_code == 401


@pytest.mark.parametrize(
    "cookie",
    [
        "notatoken",
        "1700000000.deadbeef",
        "abc.{sig}",
        "{ts}.{sig}x",
    ],
)
def test_tampered_cookie_rejected(client, cookie: str) -> None:
    ts = str(int(time.time()))
    client.set_cookie(auth.COOKIE_NAME, cookie.format(ts=ts, sig=auth.sign(TOKEN, ts)))
    assert client.get("/api/briefs").status_code == 401


def test_expired_session_rejected(client) -> None:
    stale = int(time.time()) - 9 * 3600
    client.set_cookie(auth.COOKIE_NAME, auth.make_session(TOKEN, stale))
    assert client.get("/api/briefs").status_code == 401


def test_session_inside_window_accepted(client) -> None:
    fresh = int(time.time()) - 7 * 3600
    client.set_cookie(auth.COOKIE_NAME, auth.make_session(TOKEN, fresh))
    assert client.get("/api/briefs").status_code == 200


def test_clock_skew_is_tolerated_but_the_future_is_not(client) -> None:
    client.set_cookie(auth.COOKIE_NAME, auth.make_session(TOKEN, int(time.time()) + 30))
    assert client.get("/api/briefs").status_code == 200
    client.set_cookie(auth.COOKIE_NAME, auth.make_session(TOKEN, int(time.time()) + 600))
    assert client.get("/api/briefs").status_code == 401


# --- origin gate -----------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://evil.example"},
        {"Referer": "http://evil.example/x"},
        {},
    ],
)
def test_mutation_with_bad_origin_is_403(client, headers: dict) -> None:
    login(client)
    res = client.post("/api/briefs", json=QUERY, headers=headers)
    assert res.status_code == 403
    assert body(res)["error"] == "cross-origin request rejected"


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://localhost"},
        {"Referer": "http://localhost/"},
    ],
)
def test_mutation_with_matching_origin_passes(client, headers: dict) -> None:
    login(client)
    assert client.post("/api/briefs", json=QUERY, headers=headers).status_code == 201


@pytest.mark.parametrize("action", ["collect", "analyze"])
def test_pipeline_mutations_need_an_origin(client, action: str) -> None:
    login(client)
    slug = brief_slug(client)
    assert client.post(f"/api/briefs/{slug}/{action}").status_code == 403


def test_pipeline_runs_with_a_matching_origin(client) -> None:
    login(client)
    slug = brief_slug(client)
    same = {"Origin": "http://localhost"}
    assert client.post(f"/api/briefs/{slug}/collect", headers=same).status_code == 200
    assert client.post(f"/api/briefs/{slug}/analyze", headers=same).status_code == 200


def test_delete_requires_origin(client) -> None:
    login(client)
    slug = brief_slug(client)
    assert client.delete(f"/api/briefs/{slug}").status_code == 403
    same = {"Origin": "http://localhost"}
    assert client.delete(f"/api/briefs/{slug}", headers=same).status_code == 200


def test_get_needs_no_origin_header(client) -> None:
    login(client)
    assert client.get("/api/briefs").status_code == 200


def test_unauthenticated_mutation_is_401_before_403(client) -> None:
    res = client.post("/api/briefs", json=QUERY, headers={"Origin": "http://evil.example"})
    assert res.status_code == 401


# --- bind guard ------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
def test_loopback_bind_needs_no_token(host: str) -> None:
    lines: list[str] = []
    auth.check_bind(host, None, lines.append)
    assert lines == []


def test_external_bind_without_token_exits(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        auth.check_bind("0.0.0.0", None)
    assert exc.value.code == 1
    assert "AUTH_TOKEN" in capsys.readouterr().out


def test_external_bind_with_token_warns() -> None:
    lines: list[str] = []
    auth.check_bind("0.0.0.0", TOKEN, lines.append)
    assert len(lines) == 1 and "TLS proxy" in lines[0]


# --- helpers ---------------------------------------------------------------


def test_signature_depends_on_token() -> None:
    ts = "1700000000"
    assert auth.sign(TOKEN, ts) != auth.sign("other", ts)
    assert not auth.verify_session(auth.make_session("other"), TOKEN)


@pytest.mark.parametrize(
    "header,expected",
    [
        ("http://localhost", True),
        ("https://localhost", True),
        ("http://localhost:6181", False),
        ("http://other", False),
        (None, False),
    ],
)
def test_same_origin_compares_host_and_port(header, expected: bool) -> None:
    assert auth.same_origin(header, "localhost") is expected


def test_login_page_reuses_the_global_stylesheet(client) -> None:
    page = client.get("/login").data.decode("utf-8")
    assert '<link rel="stylesheet" href="/static/style.css">' in page
    assert 'class="input input-hero"' in page and "style=" not in page
