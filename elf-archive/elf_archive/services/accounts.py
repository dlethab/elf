"""Accounts, sessions, email verification, password reset, roles.

Password hashing is delegated to Werkzeug's maintained scrypt implementation. Session and
reset/verification tokens are random, and only their SHA-256 hashes are stored."""
import hashlib
import re
import secrets
from dataclasses import dataclass

from werkzeug.security import check_password_hash, generate_password_hash

from . import audit, ratelimit
from .timeutil import future_iso, now_iso
from ..permissions import permissions_for
from ..vocab import ROLES

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
COMMON_PASSWORDS = {"password", "password1", "1234567890", "qwertyuiop", "letmein123", "iloveyou12",
                    "administrator", "welcome123", "passw0rd123"}
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing-equalisation")


class AccountError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    username: str
    display_name: str
    roles: frozenset
    email_verified: bool
    mfa_enabled: bool = False

    @property
    def permissions(self):
        return permissions_for(self.roles)

    def can(self, perm):
        return perm in self.permissions


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def validate_password(pw, *, email="", username=""):
    if len(pw) < 10:
        return "Use at least 10 characters."
    if len(pw) > 128:
        return "Use at most 128 characters."
    if pw.isdigit() or pw.lower() in COMMON_PASSWORDS:
        return "That password is too easy to guess."
    low = pw.lower()
    if username and username.lower() in low and len(username) >= 4:
        return "The password should not contain your username."
    if email and email.split("@")[0].lower() in low and len(email.split("@")[0]) >= 4:
        return "The password should not contain your email name."
    return None


def queue_email(db, to_email, subject, body):
    db.execute("INSERT INTO outbox(to_email, subject, body) VALUES (?,?,?)", (to_email, subject, body))


def _new_token(db, user_id, purpose, lifetime):
    raw = secrets.token_urlsafe(32)
    db.execute("INSERT INTO auth_tokens(user_id, purpose, token_hash, expires_at) VALUES (?,?,?,?)",
               (user_id, purpose, _h(raw), future_iso(lifetime)))
    return raw


def register(db, *, email, username, display_name, password, ip, base_url):
    email, username, display_name = (email or "").strip(), (username or "").strip(), (display_name or "").strip()
    errors = {}
    if not EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email address."
    if not USERNAME_RE.match(username):
        errors["username"] = "3–30 characters: letters, numbers, underscore."
    if not 1 <= len(display_name) <= 80:
        errors["display_name"] = "Enter a display name (up to 80 characters)."
    perr = validate_password(password or "", email=email, username=username)
    if perr:
        errors["password"] = perr
    if errors:
        raise AccountError(errors)
    if not ratelimit.allow(db, f"register:{ip}", 10, 3600):
        raise AccountError({"form": "Too many registrations from this network. Try again later."})
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        errors["email"] = "An account with this email already exists."
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        errors["username"] = "That username is taken."
    if errors:
        raise AccountError(errors)
    cur = db.execute("INSERT INTO users(email, username, display_name, password_hash) VALUES (?,?,?,?)",
                     (email, username, display_name, generate_password_hash(password)))
    uid = cur.lastrowid
    send_verification(db, uid, email, base_url)
    audit.log(db, uid, "account.registered", "user", uid, ip=ip)
    return uid


def send_verification(db, user_id, email, base_url):
    raw = _new_token(db, user_id, "verify_email", 86400)
    queue_email(db, email, "Verify your email address",
                f"Open this link to verify your email address (valid 24 hours):\n{base_url}/auth/verify/{raw}\n\n"
                "If you did not register, ignore this message.")


def verify_email(db, raw):
    row = db.execute("SELECT * FROM auth_tokens WHERE token_hash=? AND purpose='verify_email' "
                     "AND used_at IS NULL AND expires_at>?", (_h(raw), now_iso())).fetchone()
    if not row:
        return False
    db.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (now_iso(), row["id"]))
    db.execute("UPDATE users SET email_verified_at=?, updated_at=? WHERE id=? AND email_verified_at IS NULL",
               (now_iso(), now_iso(), row["user_id"]))
    audit.log(db, row["user_id"], "account.email_verified", "user", row["user_id"])
    return True


LOGIN_FAIL_LIMIT, LOGIN_WINDOW = 5, 900


def locked_out(db, identifier, ip):
    return (ratelimit.count(db, f"loginfail:id:{identifier.lower()}", LOGIN_WINDOW) >= LOGIN_FAIL_LIMIT
            or ratelimit.count(db, f"loginfail:ip:{ip}", LOGIN_WINDOW) >= LOGIN_FAIL_LIMIT * 6)


def authenticate(db, identifier, password, ip):
    """Return user id, 'locked', or None. Failures are rate-limited; timing is equalised for unknown users."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    if locked_out(db, identifier, ip):
        return "locked"
    row = db.execute("SELECT id, password_hash, is_active FROM users WHERE email=? OR username=?",
                     (identifier, identifier)).fetchone()
    ok = check_password_hash(row["password_hash"] if row else _DUMMY_HASH, password or "")
    if row and ok and row["is_active"]:
        audit.log(db, row["id"], "auth.login", "user", row["id"], ip=ip)
        return row["id"]
    ratelimit.hit(db, f"loginfail:id:{identifier.lower()}")
    ratelimit.hit(db, f"loginfail:ip:{ip}")
    audit.log(db, None, "auth.login_failed", "user", None, {"identifier_hash": _h(identifier.lower())[:16]}, ip)
    return None


# ───────────── Sessions ─────────────
def create_session(db, user_id, ip, user_agent, lifetime_seconds):
    raw = secrets.token_urlsafe(32)
    db.execute("INSERT INTO user_sessions(token_hash, user_id, created_at, expires_at, ip, user_agent) VALUES (?,?,?,?,?,?)",
               (_h(raw), user_id, now_iso(), future_iso(lifetime_seconds), ip, (user_agent or "")[:200]))
    return raw


def load_session(db, raw):
    """CurrentUser for a live session, else None (expired, revoked, deactivated)."""
    if not raw:
        return None
    r = db.execute(
        "SELECT u.* FROM user_sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.is_active=1",
        (_h(raw), now_iso())).fetchone()
    if not r:
        return None
    return CurrentUser(r["id"], r["email"], r["username"], r["display_name"],
                       frozenset(get_roles(db, r["id"])), r["email_verified_at"] is not None, r["totp_enabled_at"] is not None)


def revoke_session(db, raw):
    db.execute("UPDATE user_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (now_iso(), _h(raw)))


def revoke_all_sessions(db, user_id, except_raw=None):
    keep = _h(except_raw) if except_raw else ""
    db.execute("UPDATE user_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND token_hash<>?",
               (now_iso(), user_id, keep))


# ───────────── Password reset / change ─────────────
def request_reset(db, email, ip, base_url):
    """Always behaves identically to the caller (no account enumeration)."""
    email = (email or "").strip()
    if not ratelimit.allow(db, f"reset:{ip}", 10, 3600):
        return
    u = db.execute("SELECT id, email FROM users WHERE email=? AND is_active=1", (email,)).fetchone()
    if u:
        raw = _new_token(db, u["id"], "reset_password", 3600)
        queue_email(db, u["email"], "Reset your password",
                    f"Open this link to choose a new password (valid 1 hour):\n{base_url}/auth/reset/{raw}\n\n"
                    "If you did not request this, ignore this message.")
        audit.log(db, u["id"], "account.reset_requested", "user", u["id"], ip=ip)


def reset_token_valid(db, raw):
    return db.execute("SELECT 1 FROM auth_tokens WHERE token_hash=? AND purpose='reset_password' AND used_at IS NULL "
                      "AND expires_at>?", (_h(raw), now_iso())).fetchone() is not None


def reset_password(db, raw, new_password):
    row = db.execute("SELECT t.*, u.email, u.username FROM auth_tokens t JOIN users u ON u.id=t.user_id "
                     "WHERE t.token_hash=? AND t.purpose='reset_password' AND t.used_at IS NULL AND t.expires_at>?",
                     (_h(raw), now_iso())).fetchone()
    if not row:
        raise AccountError({"form": "This reset link is invalid or has expired."})
    err = validate_password(new_password or "", email=row["email"], username=row["username"])
    if err:
        raise AccountError({"password": err})
    db.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (now_iso(), row["id"]))
    db.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
               (generate_password_hash(new_password), now_iso(), row["user_id"]))
    revoke_all_sessions(db, row["user_id"])
    audit.log(db, row["user_id"], "account.password_reset", "user", row["user_id"])
    return row["user_id"]


def change_password(db, user_id, current, new, keep_session_raw=None):
    u = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not check_password_hash(u["password_hash"], current or ""):
        raise AccountError({"current_password": "Current password is incorrect."})
    err = validate_password(new or "", email=u["email"], username=u["username"])
    if err:
        raise AccountError({"new_password": err})
    db.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?", (generate_password_hash(new), now_iso(), user_id))
    revoke_all_sessions(db, user_id, except_raw=keep_session_raw)
    audit.log(db, user_id, "account.password_changed", "user", user_id)


# ───────────── Profile ─────────────
def update_profile(db, user_id, form):
    dn = (form.get("display_name") or "").strip()
    if not 1 <= len(dn) <= 80:
        raise AccountError({"display_name": "Enter a display name (up to 80 characters)."})
    pref = form.get("attribution_pref", "display_name")
    if pref not in ("display_name", "username", "anonymous"):
        raise AccountError({"attribution_pref": "Choose one of the listed options."})
    db.execute("UPDATE users SET display_name=?, bio=?, languages=?, research_interests=?, attribution_pref=?, "
               "notify_submission_updates=?, notify_forum_replies=?, updated_at=? WHERE id=?",
               (dn, (form.get("bio") or "")[:1000], (form.get("languages") or "")[:200],
                (form.get("research_interests") or "")[:500], pref,
                1 if form.get("notify_submission_updates") else 0, 1 if form.get("notify_forum_replies") else 0, now_iso(), user_id))


# ───────────── Roles ─────────────
def get_roles(db, user_id):
    return [r["role"] for r in db.execute("SELECT role FROM user_roles WHERE user_id=? AND revoked_at IS NULL", (user_id,))]


def active_admin_count(db):
    return db.execute("SELECT COUNT(*) FROM user_roles r JOIN users u ON u.id=r.user_id "
                      "WHERE r.role='administrator' AND r.revoked_at IS NULL AND u.is_active=1").fetchone()[0]


def grant_role(db, actor_id, user_id, role, ip=None):
    if role not in ROLES:
        raise AccountError({"role": "Unknown role."})
    if not db.execute("SELECT 1 FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone():
        raise AccountError({"user": "User not found or inactive."})
    db.execute("INSERT INTO user_roles(user_id, role, granted_by, granted_at) VALUES (?,?,?,?) "
               "ON CONFLICT(user_id, role) DO UPDATE SET revoked_at=NULL, revoked_by=NULL, granted_by=excluded.granted_by, "
               "granted_at=excluded.granted_at", (user_id, role, actor_id, now_iso()))
    audit.log(db, actor_id, "role.granted", "user", user_id, {"role": role}, ip)


def revoke_role(db, actor_id, user_id, role, ip=None):
    if role == "administrator" and active_admin_count(db) <= 1 and \
            db.execute("SELECT 1 FROM user_roles WHERE user_id=? AND role='administrator' AND revoked_at IS NULL", (user_id,)).fetchone():
        raise AccountError({"role": "Cannot remove the last administrator."})
    db.execute("UPDATE user_roles SET revoked_at=?, revoked_by=? WHERE user_id=? AND role=? AND revoked_at IS NULL",
               (now_iso(), actor_id, user_id, role))
    audit.log(db, actor_id, "role.revoked", "user", user_id, {"role": role}, ip)


# ───────────── Deactivation / anonymisation ─────────────
def deactivate(db, actor_id, user_id, ip=None):
    if "administrator" in get_roles(db, user_id) and active_admin_count(db) <= 1:
        raise AccountError({"user": "Cannot deactivate the last administrator."})
    db.execute("UPDATE users SET is_active=0, deactivated_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), user_id))
    revoke_all_sessions(db, user_id)
    audit.log(db, actor_id, "account.deactivated", "user", user_id, ip=ip)


def reactivate(db, actor_id, user_id, ip=None):
    db.execute("UPDATE users SET is_active=1, deactivated_at=NULL, updated_at=? WHERE id=? AND anonymized_at IS NULL",
               (now_iso(), user_id))
    audit.log(db, actor_id, "account.reactivated", "user", user_id, ip=ip)


def anonymize(db, actor_id, user_id, ip=None):
    """Scrub personal data but keep the row, so attribution links and audit history stay intact."""
    u = db.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()
    if not u or u["is_active"]:
        raise AccountError({"user": "Deactivate the account before anonymising it."})
    db.execute("UPDATE users SET email=?, username=?, display_name='Former contributor', bio=NULL, languages=NULL, "
               "research_interests=NULL, password_hash=?, attribution_pref='anonymous', anonymized_at=?, updated_at=? WHERE id=?",
               (f"anon-{user_id}@anonymized.invalid", f"former_{user_id}", "!" + secrets.token_hex(16),
                now_iso(), now_iso(), user_id))
    db.execute("DELETE FROM auth_tokens WHERE user_id=?", (user_id,))
    audit.log(db, actor_id, "account.anonymized", "user", user_id, ip=ip)


MAX_EMAIL_ATTEMPTS = 5      # with send-email every 2 minutes, a short mail-server outage is ridden out


def deliver_outbox(db, smtp_factory, sender, limit=50):
    """Send queued email through an SMTP client (injected, so it is testable and optional).
    A failed message is retried on later runs, up to MAX_EMAIL_ATTEMPTS; `error` keeps the latest failure."""
    from email.message import EmailMessage
    sent = 0
    for r in db.execute("SELECT * FROM outbox WHERE sent_at IS NULL AND attempts < ? ORDER BY id LIMIT ?",
                        (MAX_EMAIL_ATTEMPTS, limit)).fetchall():
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, r["to_email"], r["subject"]
        msg.set_content(r["body"])
        try:
            with smtp_factory() as s:
                s.send_message(msg)
            db.execute("UPDATE outbox SET sent_at=?, attempts=attempts+1 WHERE id=?", (now_iso(), r["id"]))
            sent += 1
        except Exception as exc:  # recorded, never logged with message body
            db.execute("UPDATE outbox SET error=?, attempts=attempts+1 WHERE id=?", (type(exc).__name__, r["id"]))
    return sent
