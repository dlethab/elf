"""ELF Digital Historical Archive — application factory."""
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, g, render_template, request, session

from . import db as dbm
from . import i18n, queries, security
from .config import load_config
from .services import accounts
from .services.records import CONSENT_LABELS
from .vocab import EVIDENCE, ITEM_TYPE_LABELS, KIND_LABELS, RIGHTS_LABELS, STATUS_LABELS


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(load_config(overrides))
    app.config["CSP"] = security.build_csp(app.config)
    app.config.update(
        SESSION_COOKIE_NAME="elf_session", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=app.config["ENV"] == "production",
        PERMANENT_SESSION_LIFETIME=app.config["SESSION_LIFETIME_SECONDS"],
    )
    path = app.config["DATABASE_PATH"]
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    if app.config["AUTO_MIGRATE"] and not app.config.get("_SHARED_CONNECTION"):
        conn = dbm.connect(path)
        dbm.migrate(conn)
        conn.close()
    elif path != ":memory:" and Path(path).exists():
        pending = dbm.pending_migrations(path)
        if pending:                       # pages that need the new tables would fail: say so where an administrator looks
            app.logger.error("The database needs %d update(s) (%s). Back it up, then run: flask --app elf_archive migrate",
                             len(pending), ", ".join(pending))
    app.teardown_appcontext(dbm.close_db)

    @app.url_defaults
    def static_version(endpoint, values):
        """url_for('static', filename=...) gets ?v=<modification time>, so files can be cached for a year and a
        deployment that changes a file changes its address. Folders (the terrain tile root) are left as they are."""
        if endpoint == "static" and "v" not in values:
            f = Path(app.static_folder) / values.get("filename", "")
            if f.is_file():
                values["v"] = format(int(f.stat().st_mtime), "x")
    if app.config["TRUSTED_PROXIES"]:
        # Behind nginx/Caddy: take the visitor's address and scheme from the proxy's headers, trusting only
        # as many hops as configured, so rate limits and lockouts apply per visitor, not to the proxy.
        from werkzeug.middleware.proxy_fix import ProxyFix
        n = app.config["TRUSTED_PROXIES"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    @app.before_request
    def _load_user_and_csrf():
        i18n.select_language()
        g.user = None
        if request.endpoint == "static":
            return None
        raw = session.get("sid")
        if raw:
            g.user = accounts.load_session(dbm.get_db(), raw)
            if g.user is None:
                session.pop("sid", None)
        security.check_csrf()

    app.after_request(security.apply_headers)

    # Stateless helpers are Jinja globals so imported macros can use them too.
    _ = i18n.gettext
    app.jinja_env.globals.update(
        _=_, csrf_token=security.csrf_token, fdate=i18n.fdate, precision_note=i18n.precision_note,
        record_url=queries.record_url, media_url=queries.media_url,
        status_label=lambda s: (_(STATUS_LABELS[s][0]), STATUS_LABELS[s][1]) if s in STATUS_LABELS else (s, "•"),
        kind_label=lambda k: _(KIND_LABELS.get(k, k)), rights_label=lambda r: _(RIGHTS_LABELS.get(r, r)),
        item_type_label=lambda t: _(ITEM_TYPE_LABELS.get(t, t)), ITEM_TYPES=list(ITEM_TYPE_LABELS),
        CONSENT_LABELS=CONSENT_LABELS,
        EVIDENCE=EVIDENCE, page_url=_page_url, languages=i18n.LANGUAGES,
        site_name=app.config["SITE_NAME"], contact_email=app.config["CONTACT_EMAIL"],
        base_url=app.config["BASE_URL"], is_dev=app.config["ENV"] in ("development", "testing"),
    )

    @app.context_processor
    def _inject():
        unread = 0
        if g.get("user"):
            unread = dbm.get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL",
                                          (g.user.id,)).fetchone()[0]
        lang = i18n.current()
        return {"current_user": g.get("user"), "can": lambda perm: bool(g.get("user") and g.user.can(perm)),
                "unread_notifications": unread, "lang": lang, "lang_dir": i18n.LANGUAGES[lang]["dir"],
                "english_only": i18n.is_english_only(request.endpoint, request.view_args),
                "translation_draft": lang != i18n.DEFAULT and i18n.is_draft(lang)}

    from .web import admin, auth, community, dashboard, editor, public
    for bp in (public.bp, auth.bp, dashboard.bp, editor.bp, admin.bp, community.bp):
        app.register_blueprint(bp)
    if app.config["ENV"] in ("development", "testing"):
        app.register_blueprint(auth.dev_bp)   # never registered in production

    from . import cli
    cli.register(app)

    def _err(code, title, text):
        def handler(e):
            desc = getattr(e, "description", None) if code == 400 else None
            return render_template("errors/error.html", code=code, title=title, text=desc or text), code
        return handler

    app.register_error_handler(400, _err(400, "Request could not be processed", "Please go back and try again."))
    app.register_error_handler(403, _err(403, "Not permitted", "You do not have permission to do this."))
    app.register_error_handler(404, _err(404, "Not found", "This page does not exist or is not publicly available."))
    app.register_error_handler(405, _err(405, "Method not allowed", "That action is not available here."))
    app.register_error_handler(413, _err(413, "Too large", "The submitted content is too large."))
    app.register_error_handler(429, _err(429, "Too many requests", "Please wait a little and try again."))

    @app.errorhandler(500)
    def _500(e):
        app.logger.exception("Unhandled error")      # details go to the server log only
        return render_template("errors/error.html", code=500, title="Something went wrong",
                               text="The error has been logged. Please try again later."), 500

    return app


def _page_url(n):
    args = request.args.to_dict()
    args["page"] = n
    return f"{request.path}?{urlencode(args)}"
