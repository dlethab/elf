"""Test helpers. ALL data created here is synthetic and obviously fictional; it is never a
historical claim. Names are prefixed 'Testperson' / 'Testville' etc."""
from werkzeug.security import generate_password_hash

from elf_archive import db as dbm
from elf_archive.services import accounts, entities, records, workflow

CONFIG = {"REQUIRE_EMAIL_VERIFICATION": True, "ALLOW_SELF_REVIEW": False}
PASSWORD = "correct-horse-battery-staple"
_FAST_HASH = None


def fast_hash():
    global _FAST_HASH
    if _FAST_HASH is None:
        _FAST_HASH = generate_password_hash(PASSWORD)
    return _FAST_HASH


def make_db():
    conn = dbm.connect(":memory:")
    dbm.migrate(conn)
    return conn


def make_user(db, username, roles=(), verified=True, active=True):
    cur = db.execute(
        "INSERT INTO users(email, username, display_name, password_hash, email_verified_at, is_active) VALUES (?,?,?,?,?,?)",
        (f"{username}@example.test", username, username.title(), fast_hash(),
         "2000-01-01T00:00:00Z" if verified else None, int(active)))
    for r in roles:
        db.execute("INSERT INTO user_roles(user_id, role) VALUES (?,?)", (cur.lastrowid, r))
    return cu(db, cur.lastrowid)


def cu(db, user_id):
    r = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return accounts.CurrentUser(r["id"], r["email"], r["username"], r["display_name"],
                                frozenset(accounts.get_roles(db, user_id)), r["email_verified_at"] is not None)


def submit_new(db, user, kind, raw, **kw):
    """Validate → create → submit. Returns submission id."""
    clean, errors = records.validate(db, kind, raw)
    assert not errors, errors
    workflow.authorize_new(db, user, kind, config=CONFIG, **kw.pop("auth", {}))
    sid = workflow.create(db, user, kind, clean, config=CONFIG, **kw)
    workflow.transition(db, user, sid, "submitted", config=CONFIG)
    return sid


def publish(db, editor, sid, consent=False):
    workflow.transition(db, editor, sid, "under_review", config=CONFIG)
    workflow.transition(db, editor, sid, "approved", message="Looks good", config=CONFIG)
    return workflow.transition(db, editor, sid, "published", consent_confirmed=consent, config=CONFIG)


def publish_new(db, contributor, editor, kind, raw, consent=False):
    sid = submit_new(db, contributor, kind, raw)
    return entities.get(db, publish(db, editor, sid, consent)["result_entity_id"])
