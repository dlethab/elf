"""Two-step sign-in with an authenticator app (TOTP, RFC 6238: HMAC-SHA1, 6 digits, 30-second steps),
plus single-use recovery codes. The algorithm is the published standard, built from Python's hmac
module; nothing here invents cryptography. A code is accepted at most once (replay protection)."""
import base64
import hashlib
import hmac
import io
import json
import secrets
import struct
import time
from urllib.parse import quote

from . import audit, ratelimit
from .timeutil import now_iso

STEP, DIGITS, WINDOW = 30, 6, 1          # accept the previous/next step to allow for clock drift


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    return str((struct.unpack(">I", digest[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS).zfill(DIGITS)


def code_at(secret, t=None):
    return _code(secret, int((t if t is not None else time.time()) // STEP))


def matching_step(secret, code, t=None):
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = int((t if t is not None else time.time()) // STEP)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def otpauth_uri(secret, account, issuer="ELF Archive"):
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"


def qr_svg_data_uri(text):
    import qrcode
    import qrcode.image.svg
    buf = io.BytesIO()
    qrcode.make(text, image_factory=qrcode.image.svg.SvgPathFillImage, border=2).save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def _hash(code):
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def new_recovery_codes(n=10):
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(n)]
    return codes, json.dumps([_hash(c) for c in codes])


def enable(db, user_id, secret, code):
    """Confirm the first code from the app, then switch two-step sign-in on. Returns recovery codes."""
    step = matching_step(secret, code)
    if step is None:
        return None
    codes, stored = new_recovery_codes()
    db.execute("UPDATE users SET totp_secret=?, totp_enabled_at=?, totp_last_step=?, recovery_codes=?, updated_at=? WHERE id=?",
               (secret, now_iso(), step, stored, now_iso(), user_id))
    audit.log(db, user_id, "auth.mfa_enabled", "user", user_id)
    return codes


def disable(db, user_id, actor_id=None):
    db.execute("UPDATE users SET totp_secret=NULL, totp_enabled_at=NULL, totp_last_step=NULL, recovery_codes=NULL, updated_at=? WHERE id=?",
               (now_iso(), user_id))
    audit.log(db, actor_id or user_id, "auth.mfa_disabled", "user", user_id)


def regenerate_codes(db, user_id):
    codes, stored = new_recovery_codes()
    db.execute("UPDATE users SET recovery_codes=? WHERE id=?", (stored, user_id))
    audit.log(db, user_id, "auth.mfa_codes_regenerated", "user", user_id)
    return codes


def verify(db, user_id, code, ip=None):
    """True if `code` is a fresh authenticator code or an unused recovery code. Failures are rate-limited."""
    if not ratelimit.allow(db, f"mfa:{user_id}", 6, 900):
        return "locked"
    u = db.execute("SELECT totp_secret, totp_last_step, recovery_codes FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone()
    if not u or not u["totp_secret"]:
        return False
    step = matching_step(u["totp_secret"], code)
    if step is not None and step > (u["totp_last_step"] or -1):
        db.execute("UPDATE users SET totp_last_step=? WHERE id=?", (step, user_id))
        audit.log(db, user_id, "auth.mfa_ok", "user", user_id, ip=ip)
        return True
    hashes = json.loads(u["recovery_codes"] or "[]")
    h = _hash(code or "")
    if any(hmac.compare_digest(h, x) for x in hashes):
        hashes.remove(h)
        db.execute("UPDATE users SET recovery_codes=? WHERE id=?", (json.dumps(hashes), user_id))
        audit.log(db, user_id, "auth.mfa_recovery_code_used", "user", user_id, {"remaining": len(hashes)}, ip)
        return True
    audit.log(db, user_id, "auth.mfa_failed", "user", user_id, ip=ip)
    return False


def remaining_codes(db, user_id):
    r = db.execute("SELECT recovery_codes FROM users WHERE id=?", (user_id,)).fetchone()
    return len(json.loads(r["recovery_codes"] or "[]")) if r else 0
