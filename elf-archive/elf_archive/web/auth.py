"""Registration, sign-in (with optional two-step), sign-out, email verification, password reset.
All state changes are POST + CSRF."""
import time

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for

from ..db import get_db, tx
from ..security import login_required, safe_next
from ..services import accounts, mfa

bp = Blueprint("auth", __name__, url_prefix="/auth")
dev_bp = Blueprint("dev", __name__, url_prefix="/dev")


def _ip():
    return request.remote_addr or "?"


def start_session(user_id):
    """Fresh session on every login (prevents session fixation)."""
    db = get_db()
    raw = accounts.create_session(db, user_id, _ip(), request.headers.get("User-Agent"),
                                  current_app.config["SESSION_LIFETIME_SECONDS"])
    session.clear()
    session.permanent = True
    session["sid"] = raw


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard.home"))
    errors, values = {}, {"email": "", "username": "", "display_name": ""}
    if request.method == "POST":
        values = {k: request.form.get(k, "") for k in values}
        if request.form.get("website"):                  # honeypot
            abort(400)
        if request.form.get("password") != request.form.get("password2"):
            errors["password2"] = "The passwords do not match."
        else:
            db = get_db()
            try:
                with tx(db):
                    uid = accounts.register(db, password=request.form.get("password", ""), ip=_ip(),
                                            base_url=current_app.config["BASE_URL"], **values)
                start_session(uid)
                flash("Your account has been created. Check your email for a link to verify your address; you can browse and save drafts meanwhile.", "ok")
                return redirect(url_for("dashboard.home"))
            except accounts.AccountError as e:
                errors = e.errors
    return render_template("auth/register.html", errors=errors, values=values), (400 if errors else 200)


@bp.route("/login", methods=["GET", "POST"])
def login():
    nxt = safe_next(request.values.get("next"), url_for("dashboard.home"))
    if g.user:
        return redirect(nxt)
    errors, identifier = {}, ""
    if request.method == "POST":
        identifier = request.form.get("identifier", "")
        db = get_db()
        with tx(db):
            result = accounts.authenticate(db, identifier, request.form.get("password", ""), _ip())
        if result == "locked":
            errors["form"] = "Too many failed attempts. Please wait 15 minutes, or reset your password."
        elif result is None:
            errors["form"] = "That email or username and password do not match an active account."
        else:
            if db.execute("SELECT totp_enabled_at FROM users WHERE id=?", (result,)).fetchone()[0]:
                # password correct; the session is created only after the second step
                session.clear()
                session["mfa_pending"] = {"uid": result, "exp": int(time.time()) + 300, "next": nxt}
                return redirect(url_for("auth.two_step"))
            with tx(db):
                start_session(result)
            return redirect(nxt)
    return render_template("auth/login.html", errors=errors, identifier=identifier, next=nxt), (400 if errors else 200)


@bp.route("/two-step", methods=["GET", "POST"])
def two_step():
    pending = session.get("mfa_pending")
    if not pending or pending.get("exp", 0) < time.time():
        session.pop("mfa_pending", None)
        flash("Please sign in again.", "error")
        return redirect(url_for("auth.login"))
    error = None
    if request.method == "POST":
        db = get_db()
        with tx(db):
            ok = mfa.verify(db, pending["uid"], request.form.get("code"), _ip())
        if ok is True:
            with tx(db):
                start_session(pending["uid"])
            return redirect(safe_next(pending.get("next"), url_for("dashboard.home")))
        error = ("Too many failed attempts. Please wait 15 minutes, or reset your password." if ok == "locked"
                 else "That code is not valid. Enter the current code from your app, or one of your recovery codes.")
    return render_template("auth/two_step.html", error=error), (400 if error else 200)


@bp.route("/logout", methods=["POST"])
def logout():
    raw = session.get("sid")
    if raw:
        db = get_db()
        with tx(db):
            accounts.revoke_session(db, raw)
    session.clear()
    flash("You have signed out.", "ok")
    return redirect(url_for("public.home"))


@bp.route("/verify/<token>")
def verify(token):
    db = get_db()
    with tx(db):
        ok = accounts.verify_email(db, token)
    if ok:
        flash("Your email address is verified. You can now submit contributions for review.", "ok")
    else:
        flash("That verification link is invalid, already used, or expired. You can request a new one from your dashboard.", "error")
    return redirect(url_for("dashboard.home") if g.user else url_for("auth.login"))


@bp.route("/resend-verification", methods=["POST"])
@login_required
def resend_verification():
    db = get_db()
    from ..services import ratelimit
    with tx(db):
        if g.user.email_verified:
            flash("Your email address is already verified.", "ok")
        elif ratelimit.allow(db, f"verify:{g.user.id}", 3, 3600):
            accounts.send_verification(db, g.user.id, g.user.email, current_app.config["BASE_URL"])
            flash("A new verification link has been sent.", "ok")
        else:
            flash("Please wait before requesting another link.", "error")
    return redirect(url_for("dashboard.home"))


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        db = get_db()
        with tx(db):
            accounts.request_reset(db, request.form.get("email", ""), _ip(), current_app.config["BASE_URL"])
        # Identical response whether or not the address exists (no account enumeration).
        flash("If an account uses that address, a password-reset link has been sent to it.", "ok")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html")


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    db = get_db()
    errors = {}
    if request.method == "POST":
        if request.form.get("password") != request.form.get("password2"):
            errors["password2"] = "The passwords do not match."
        else:
            try:
                with tx(db):
                    accounts.reset_password(db, token, request.form.get("password", ""))
                session.clear()
                flash("Your password has been changed and all other sessions were signed out. Please sign in.", "ok")
                return redirect(url_for("auth.login"))
            except accounts.AccountError as e:
                errors = e.errors
    elif not accounts.reset_token_valid(db, token):
        errors["form"] = "This reset link is invalid or has expired."
    return render_template("auth/reset.html", errors=errors, token=token), (400 if errors else 200)


# ───────────── development helper: read queued email without an SMTP provider ─────────────
@dev_bp.route("/outbox")
def outbox():
    rows = get_db().execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 50").fetchall()
    return render_template("auth/dev_outbox.html", rows=rows)
