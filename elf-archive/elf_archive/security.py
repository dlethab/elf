"""CSRF, security headers, safe redirects, caching policy, staff-route guards."""
import hmac
import secrets
from functools import wraps
from urllib.parse import urlparse

from flask import abort, current_app, flash, g, redirect, request, session, url_for

from .permissions import CONTRIBUTOR

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    if request.method in UNSAFE:
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("csrf") or ""
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description="Your session expired or the form was invalid. Please go back, reload, and try again.")


def safe_next(target, default="/"):
    """Only same-site relative paths; blocks open redirects such as //evil.test or https://evil.test."""
    if not target:
        return default
    u = urlparse(target)
    if u.scheme or u.netloc or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return default
    return target


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.get("user"):
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*a, **kw)
    return wrapped


def require(permission):
    """Server-side permission gate. Anonymous → login; signed in without permission → 403."""
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if not g.get("user"):
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if not g.user.can(permission):
                abort(403)
            # optional policy: staff must use two-step sign-in before using staff tools
            if current_app.config.get("REQUIRE_STAFF_MFA") and permission not in CONTRIBUTOR and not g.user.mfa_enabled:
                flash("Your role requires two-step sign-in. Please turn it on to continue.", "error")
                return redirect(url_for("dashboard.security"))
            return view(*a, **kw)
        return wrapped
    return deco


# blob: images: the map decodes its own elevation tiles in the browser (MapLibre's image fallback path)
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
       "frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'")


def build_csp(config):
    """The policy above, plus the map tile host only if an administrator configured one."""
    tile = config.get("MAP_TILE_URL") or ""
    if not tile:
        return CSP
    u = urlparse(tile.replace("{s}", "a").replace("{z}", "0").replace("{x}", "0").replace("{y}", "0").replace("{r}", ""))
    host = f"{u.scheme}://{u.netloc}".replace("://a.", "://*.") if u.scheme == "https" and u.netloc else ""
    return CSP.replace("img-src 'self' data: blob:", f"img-src 'self' data: blob: {host}") if host else CSP


PRIVATE_PREFIXES = ("/dashboard", "/editor", "/admin", "/auth", "/dev", "/contribute", "/moderation")
# The only pages another site may show in a frame: the public map and timeline, in their embedded layout (?embed=1),
# and only for the sites listed in ELF_EMBED_ORIGINS. Every other page (sign-in, forms, staff pages) refuses framing.
EMBED_PATHS = ("/explore", "/map", "/timeline")


def _embeddable():
    origins = current_app.config.get("EMBED_ORIGINS") or []
    ok = bool(origins) and request.method == "GET" and request.path in EMBED_PATHS and request.args.get("embed") == "1"
    return origins if ok else None


def apply_headers(response):
    h = response.headers
    h["Content-Security-Policy"] = current_app.config.get("CSP") or CSP
    h["X-Content-Type-Options"] = "nosniff"
    origins = _embeddable()
    if origins:            # X-Frame-Options cannot name a site; frame-ancestors is the rule browsers apply here
        h["Content-Security-Policy"] = h["Content-Security-Policy"].replace("frame-ancestors 'none'", "frame-ancestors " + " ".join(origins))
    else:
        h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    h["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    if current_app.config["ENV"] == "production":           # production is https-only (enforced in config.py)
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    h.add("Vary", "Cookie")
    # Anything personalised, or any non-GET, is never cacheable. Anonymous public GETs must revalidate,
    # so an unpublished record cannot linger in a shared cache.
    if g.get("user") or request.method != "GET" or request.path.startswith(PRIVATE_PREFIXES):
        h["Cache-Control"] = "private, no-store"
    elif request.path.startswith("/static/"):
        if request.args.get("v"):                            # versioned by content date (see static_version in __init__)
            h["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.path.startswith("/static/map/terrain/"):
            h["Cache-Control"] = "public, max-age=2592000"   # elevation tiles change only when rebuilt (tools/build_terrain.py)
        else:
            h["Cache-Control"] = "public, max-age=3600"
    elif "no-store" not in h.get("Cache-Control", ""):      # a view may make a response stricter, never looser
        h["Cache-Control"] = "public, max-age=0, must-revalidate"
    if request.path.startswith(PRIVATE_PREFIXES):
        h["X-Robots-Tag"] = "noindex, nofollow"
    return response
