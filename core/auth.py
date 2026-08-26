"""Optional token auth: signed session cookie, same-origin gate, bind guard.

Auth is active only when AUTH_TOKEN is set. Without it the app stays open, which
is the intended local single-user mode on a loopback bind — and a non-loopback
bind without a token is refused outright rather than served unprotected.
"""

from __future__ import annotations

import hmac
import ipaddress
import time
from hashlib import sha256
from typing import Callable, Optional, Tuple
from urllib.parse import urlparse

from flask import Blueprint, Response, current_app, make_response, redirect, request

from .api import fail

auth_bp = Blueprint("auth", __name__)

COOKIE_NAME = "jl_session"
SESSION_MAX_AGE = 8 * 3600
CLOCK_SKEW = 60
MUTATING_METHODS = ("POST", "PATCH", "PUT", "DELETE")
EXEMPT_PATHS = ("/login", "/logout")
LOGIN_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>janusline — sign in</title>
  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <h1 class="brand"><a class="brand-link" href="/">janus<span class="brand-em">line</span></a></h1>
    <p class="tagline">two sides of one search, on one timeline</p>
  </header>
  <main class="wrap wrap-narrow">
    <section class="panel">
      <div class="panel-head"><h2 class="panel-title">Sign in</h2></div>
      <form method="post" action="/login">
        <label class="label" for="token">Access token</label>
        <input class="input input-hero" id="token" type="password" name="token"
               autocomplete="current-password" autofocus placeholder="access token">
        <p class="helper">The token this instance was started with.</p>
        <div class="form-actions">
          <button class="btn btn-primary" type="submit">Sign in</button>
        </div>
      </form>
      {message}
    </section>
  </main>
</body>
</html>
"""


def is_loopback(host: str) -> bool:
    """True for hosts that are only reachable from this machine."""
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def check_bind(host: str, token: Optional[str], emit: Callable[[str], None] = print) -> None:
    """Refuse a non-loopback bind without a token; warn about plaintext otherwise."""
    if is_loopback(host):
        return
    if not token:
        emit(
            f"[error] refusing to bind {host} without AUTH_TOKEN — "
            "set AUTH_TOKEN=<secret> or bind 127.0.0.1"
        )
        raise SystemExit(1)
    emit(f"[warn] binding {host}: traffic is plain HTTP — put a TLS proxy in front")


def sign(token: str, ts: str) -> str:
    return hmac.new(token.encode("utf-8"), ts.encode("utf-8"), sha256).hexdigest()


def make_session(token: str, ts: Optional[int] = None) -> str:
    stamp = str(int(time.time()) if ts is None else ts)
    return f"{stamp}.{sign(token, stamp)}"


def verify_session(cookie: Optional[str], token: str, now: Optional[int] = None) -> bool:
    """Cookie is valid when the signature matches and the stamp is inside the window."""
    if not cookie or not token or "." not in cookie:
        return False
    stamp, _, signature = cookie.partition(".")
    if not stamp.isdigit():
        return False
    if not hmac.compare_digest(signature, sign(token, stamp)):
        return False
    age = (int(time.time()) if now is None else now) - int(stamp)
    return -CLOCK_SKEW <= age <= SESSION_MAX_AGE


def same_origin(header: Optional[str], host: str) -> bool:
    """Compare host:port only — a TLS proxy in front changes the scheme we observe."""
    if not header:
        return False
    return urlparse(header).netloc == host


def origin_allowed() -> bool:
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    if not origin and not referer:
        return False
    return same_origin(origin or referer, request.host)


def _login_response(message: str = "", status: int = 200) -> Response:
    block = f'<p class="notice">{message}</p>' if message else ""
    response = make_response(LOGIN_PAGE.format(message=block), status)
    response.mimetype = "text/html"
    return response


@auth_bp.get("/login")
def login_page() -> Response:
    return _login_response()


@auth_bp.post("/login")
def login_submit() -> Response:
    token = current_app.config.get("AUTH_TOKEN") or ""
    submitted = request.form.get("token") or ""
    if not token or not hmac.compare_digest(submitted, token):
        return _login_response("Invalid token.", 401)
    response = make_response(redirect("/"))
    response.set_cookie(
        COOKIE_NAME,
        make_session(token),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="Strict",
        secure=request.is_secure,
        path="/",
    )
    return response


@auth_bp.get("/logout")
def logout() -> Response:
    response = make_response(redirect("/login"))
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


def _reject(message: str, status: int):
    if request.path.startswith("/api/"):
        return fail(message, status)
    return redirect("/login") if status == 401 else _login_response(message, status)


def gate() -> Optional[Tuple]:
    """before_request hook: cookie check, then same-origin check on mutations."""
    token = current_app.config.get("AUTH_TOKEN")
    if not token:
        return None
    if request.path in EXEMPT_PATHS or request.path.startswith("/static/"):
        return None
    if not verify_session(request.cookies.get(COOKIE_NAME), token):
        return _reject("unauthorized", 401)
    if request.method in MUTATING_METHODS and not origin_allowed():
        return _reject("cross-origin request rejected", 403)
    return None


def install(app, token: Optional[str]) -> None:
    """Wire the login routes and the gate. No token means open mode."""
    app.config["AUTH_TOKEN"] = token or ""
    if not token:
        return
    app.register_blueprint(auth_bp)
    app.before_request(gate)
