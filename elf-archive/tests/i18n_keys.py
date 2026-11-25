"""Collects every interface string that must have a translation (used by test_i18n and by
`python -m tests.i18n_keys` to list what a catalogue is missing)."""
import re
import sys
from pathlib import Path

from elf_archive import vocab
from elf_archive.services import dates, records

ROOT = Path(__file__).resolve().parent.parent / "elf_archive"
TEMPLATE_STR = re.compile(r"""\b_\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")
# Messages shown to contributors and visitors from Python code: flash(...), raised errors, field errors.
PY_STR = re.compile(r"""(?:\bflash|\bWorkflowError|\bPermissionDenied|\bAccountError|\bForumError|(?<![\w])_)\(\s*"([^"{}]+)"|errors\[[^\]]+\]\s*=\s*"([^"{}]+)"|"(?:photo|caption|taken|rights_status|rights_declared)":\s*"([^"]+)\"""")
PY_FILES = ("web/dashboard.py", "web/auth.py", "web/public.py", "web/community.py", "services/photos.py", "services/records.py", "services/forum.py",
            "services/accounts.py", "services/workflow.py", "__init__.py")
# English-only (staff) templates are not translated yet.
SKIP_TEMPLATES = ("editor/", "admin/", "auth/dev_outbox", "community/moderation", "pages/privacy", "pages/terms",
                  "pages/copyright", "pages/data-policy", "pages/_policy_draft")   # legal drafts: English until adopted


def template_keys():
    out = set()
    for f in (ROOT / "templates").rglob("*.html"):
        rel = f.relative_to(ROOT / "templates").as_posix()
        if rel.startswith(SKIP_TEMPLATES):
            continue
        for m in TEMPLATE_STR.finditer(f.read_text(encoding="utf-8")):
            out.add((m.group(1) if m.group(1) is not None else m.group(2)).replace("\\'", "'").replace('\\"', '"'))
    return out


def python_keys():
    out = set()
    for rel in PY_FILES:
        for m in PY_STR.finditer((ROOT / rel).read_text(encoding="utf-8")):
            s = next(g for g in m.groups() if g)
            if s.strip() and not s.startswith(("SELECT", "UPDATE", "INSERT", "DELETE")):
                out.add(s)
    return out


def data_keys(db=None):
    out = set(dates.MONTHS) | {"c.", "Unknown"}
    out |= {dates.precision_note(p) for p in vocab.PRECISIONS}
    out |= set(vocab.KIND_LABELS.values()) | {v[0] for v in vocab.STATUS_LABELS.values()}
    out |= {x for pair in vocab.EVIDENCE.values() for x in pair}
    out |= {x for pair in vocab.RELATIONSHIP_TYPES.values() for x in pair}
    out |= set(vocab.RIGHTS_LABELS.values())
    from elf_archive.services import forum, graph
    out |= set(graph.CATEGORIES.values()) | set(records.CONSENT_LABELS.values()) | set(vocab.ITEM_TYPE_LABELS.values())
    out |= set(forum.REPORT_CATEGORIES.values())
    from elf_archive import atlas
    out |= set(atlas.CATEGORY_LABELS.values()) | set(atlas.EVENT_CATEGORY_LABELS.values()) | {"Born here", "Died here", "Born and died here", "Took part in an event here"}
    from elf_archive.services import workflow
    out |= set(workflow._NOTICE.values())                     # notification messages are stored in English, shown translated
    out |= {"Someone replied to your forum topic.", "Please sign in again.", "Two-step sign-in is on.", "Two-step sign-in is off.",
            "That code is not valid. Enter the current code from your app, or one of your recovery codes.",
            "That password is not correct.", "Your role requires two-step sign-in. Please turn it on to continue.",
            "Privacy policy", "Terms of use", "Copyright and permissions", "Data and licensing policy",
            "About the archive", "Historical and editorial standards", "How to contribute", "How to submit corrections",
            "Accessibility statement"}
    out |= {s.capitalize() for s in vocab.RELATIONSHIP_STATUSES}
    out |= {c.replace("_", " ").capitalize() for c in vocab.COORD_PRECISIONS}
    out |= {s.replace("_", " ").capitalize() for s in vocab.SOURCE_TYPES}
    out |= {n.replace("_", " ") for n in vocab.NAME_TYPES}
    out |= {"People", "Families", "Places", "Events", "Sources", "Digital Archive", "Oral Histories", "Community",
            "same name or spelling", "similar spelling", "same name or spelling; same birth year",
            "similar spelling; same birth year", "Contributed to the archive and reviewed by an editor.",
            "ELF Digital Historical Archive",
            # error pages (titles and texts registered in elf_archive/__init__.py)
            "Request could not be processed", "Please go back and try again.", "Not permitted",
            "You do not have permission to do this.", "Not found", "This page does not exist or is not publicly available.",
            "Method not allowed", "That action is not available here.", "Too large", "The submitted content is too large.",
            "Too many requests", "Please wait a little and try again.", "Something went wrong",
            "The error has been logged. Please try again later.",
            "Your session expired or the form was invalid. Please go back, reload, and try again."}
    for kind in records.SPECS:
        for f in records.spec_for(kind):
            out.add(f.label)
            if f.help:
                out.add(f.help)
            if f.kind == "choice":
                out |= {label for _, label in f.choices}
    if db is not None:
        for table in ("place_types", "event_types"):
            out |= {r[0] for r in db.execute(f"SELECT label FROM {table}")}
        for r in db.execute("SELECT title, description FROM forum_categories"):
            out |= {r[0], r[1]}
    return out


def required(db=None):
    return {k for k in template_keys() | python_keys() | data_keys(db) if k and k.strip() and k != "—"}


if __name__ == "__main__":       # python -m tests.i18n_keys ti   → prints missing msgids as JSON
    import json
    from elf_archive import i18n
    from tests.helpers import make_db
    lang = sys.argv[1] if len(sys.argv) > 1 else "ti"
    have = i18n.catalog(lang)
    missing = sorted(required(make_db()) - set(have))
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({k: "" for k in missing}, ensure_ascii=False, indent=1))
    print(f"{len(missing)} missing", file=sys.stderr)
