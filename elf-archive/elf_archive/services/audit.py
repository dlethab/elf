import json

from .timeutil import now_iso


def log(db, actor_id, action, target_type=None, target_id=None, detail=None, ip=None):
    """Append to the audit trail. Never pass secrets in `detail`."""
    db.execute(
        "INSERT INTO audit_logs(actor_id, action, target_type, target_id, detail_json, ip, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (actor_id, action, target_type, None if target_id is None else str(target_id),
         json.dumps(detail, ensure_ascii=False, sort_keys=True) if detail is not None else None, ip, now_iso()),
    )
