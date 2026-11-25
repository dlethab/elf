"""Family-representative grants: scoped to one family, individually revocable, never a global role."""
from . import audit, entities
from .timeutil import now_iso


def active_grant(db, user_id, family_entity_id):
    return db.execute("SELECT * FROM family_representatives WHERE user_id=? AND family_id=? AND revoked_at IS NULL",
                      (user_id, family_entity_id)).fetchone()


def list_for_family(db, family_entity_id):
    return db.execute("SELECT fr.*, u.username, u.display_name FROM family_representatives fr JOIN users u ON u.id=fr.user_id "
                      "WHERE fr.family_id=? AND fr.revoked_at IS NULL ORDER BY fr.granted_at", (family_entity_id,)).fetchall()


def families_for_user(db, user_id):
    return db.execute(
        "SELECT e.id, e.public_id, e.slug, f.display_name, fr.can_propose_tree, fr.can_suggest_edits, fr.can_submit_media "
        "FROM family_representatives fr JOIN entities e ON e.id=fr.family_id JOIN families f ON f.entity_id=e.id "
        "WHERE fr.user_id=? AND fr.revoked_at IS NULL AND e.deleted_at IS NULL", (user_id,)).fetchall()


def grant(db, actor_id, username, family_entity_id, *, suggest_edits=True, propose_tree=True, submit_media=False):
    u = db.execute("SELECT id FROM users WHERE username=? AND is_active=1", ((username or "").strip(),)).fetchone()
    if not u:
        raise ValueError("No active user with that username.")
    fam = entities.get(db, family_entity_id)
    if not fam or fam["kind"] != "family":
        raise ValueError("Family not found.")
    if active_grant(db, u["id"], family_entity_id):
        raise ValueError("This user is already a representative of this family.")
    db.execute("INSERT INTO family_representatives(user_id, family_id, can_suggest_edits, can_propose_tree, can_submit_media, granted_by) "
               "VALUES (?,?,?,?,?,?)", (u["id"], family_entity_id, int(suggest_edits), int(propose_tree), int(submit_media), actor_id))
    audit.log(db, actor_id, "family_rep.granted", "family", fam["public_id"], {"user_id": u["id"]})
    return u["id"]


def revoke(db, actor_id, grant_id):
    g = db.execute("SELECT * FROM family_representatives WHERE id=? AND revoked_at IS NULL", (grant_id,)).fetchone()
    if not g:
        raise ValueError("Grant not found.")
    db.execute("UPDATE family_representatives SET revoked_at=?, revoked_by=? WHERE id=?", (now_iso(), actor_id, grant_id))
    audit.log(db, actor_id, "family_rep.revoked", "family", g["family_id"], {"user_id": g["user_id"]})
