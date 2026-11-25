"""Duplicate-person candidates. A REVIEW AID ONLY: similarity never merges anything and is not
evidence of identity. Editors decide."""
from difflib import SequenceMatcher

from .names import normalize


def find_person_candidates(db, names, birth_year=None, limit=5, exclude_entity_id=None):
    wanted = {normalize(n) for n in names if n}
    wanted.discard("")
    if not wanted:
        return []
    found = {}
    rows = db.execute("SELECT n.entity_id, n.normalized, n.name, p.preferred_name, p.birth_start, p.birth_precision, "
                      "e.public_id, e.slug, e.visibility FROM entity_names n JOIN entities e ON e.id=n.entity_id "
                      "JOIN people p ON p.entity_id=e.id "
                      "WHERE e.kind='person' AND e.merged_into IS NULL AND e.deleted_at IS NULL").fetchall()
    for r in rows:
        if r["entity_id"] == exclude_entity_id:
            continue
        for w in wanted:
            if w == r["normalized"]:
                score, why = 1.0, "same name or spelling"
            else:
                sm = SequenceMatcher(None, w, r["normalized"])
                if sm.real_quick_ratio() < 0.8 or sm.quick_ratio() < 0.8:
                    continue
                score = sm.ratio()
                if score < 0.85:
                    continue
                why = "similar spelling"
            by = r["birth_start"][:4] if (r["birth_start"] and r["birth_precision"] != "unknown") else None
            if birth_year and by and str(birth_year) == by:
                score, why = min(1.0, score + 0.05), why + "; same birth year"
            cur = found.get(r["entity_id"])
            if not cur or score > cur["score"]:
                found[r["entity_id"]] = {"entity_id": r["entity_id"], "public_id": r["public_id"], "slug": r["slug"],
                                         "name": r["preferred_name"], "matched": r["name"], "score": round(score, 2),
                                         "why": why, "visibility": r["visibility"]}
    return sorted(found.values(), key=lambda x: -x["score"])[:limit]
