"""Central permission matrix. Every server-side check goes through `can()`.

Roles are additive. 'contributor' is implicit for any active account. Family-representative
power is NOT a role: it is a scoped, revocable grant (see services/families.py).
Moderators deliberately receive no archival-review permissions (least privilege)."""
from .vocab import BASE_ROLE

CONTRIBUTOR = frozenset({
    "submission.create", "submission.view_own", "submission.edit_own",
    "submission.withdraw_own", "profile.edit_own",
})
EDITOR = frozenset({
    "queue.view", "submission.review", "submission.request_revision", "submission.decide",
    "submission.publish", "record.view_any", "record.restrict", "duplicates.view",
    "confidential.view", "messages.view", "family_rep.manage", "record.edit", "citation.manage",
    "record.merge", "import.run", "restricted.view",
})
# Researchers are vetted by administrators. They can VIEW material marked for research access
# (restricted records and media), and every such view is logged. They cannot edit or publish.
RESEARCHER = frozenset({"restricted.view"})
MODERATOR = frozenset({"reports.view", "forum.moderate"})
ADMINISTRATOR = EDITOR | MODERATOR | frozenset({
    "users.manage", "roles.assign", "audit.view", "admin.overview", "settings.manage",
})

ROLE_PERMISSIONS = {
    BASE_ROLE: CONTRIBUTOR,
    "editor": EDITOR,
    "moderator": MODERATOR,
    "administrator": ADMINISTRATOR,
    "researcher": RESEARCHER,
}


def permissions_for(roles):
    perms = set(CONTRIBUTOR)
    for r in roles:
        perms |= ROLE_PERMISSIONS.get(r, frozenset())
    return frozenset(perms)


def can(roles, permission):
    return permission in permissions_for(roles)
