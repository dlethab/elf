"""Photographs attached to contributions.

Lifecycle:
  1. A contributor uploads a photo to their own DRAFT (or returned) submission, with a caption,
     photographer, date and an honest statement of its rights. Nothing is public.
  2. While reviewing, an editor decides per photo: include or leave out, public or restricted, and
     the rights status they have established. A photo can only be public with rights that allow it.
  3. Publishing the submission turns each included photo into an archive item linked to the record.

File safety: the type is checked from the file's CONTENT (Pillow), never its name; size and pixel
count are limited; files are stored under random keys outside the web root. Visitors only ever get
re-encoded copies (display size and thumbnail) with all embedded metadata removed, including GPS
location. The untouched original is preserved for the archive and is visible to staff only.
"""
import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from . import audit, dates, entities, ratelimit, search, storage as storage_mod
from .entities import PUBLIC_WHERE
from .timeutil import now_iso
from .workflow import EDITABLE, PHOTO_KINDS, PermissionDenied, WorkflowError
from ..db import tx
from ..vocab import CONTRIBUTOR_RIGHTS, ITEM_TYPES, PUBLIC_RIGHTS, RIGHTS_STATUSES

FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
DISPLAY_SIDE, THUMB_SIDE = 1600, 480
Image.MAX_IMAGE_PIXELS = 60_000_000          # larger images are refused (decompression-bomb guard)
REVIEW_STATES = ("submitted", "under_review", "approved")


class PhotoError(Exception):
    """Validation problems, as {field: message}. Messages are English msgids (translated in templates)."""

    def __init__(self, errors):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


# ───────────── image handling ─────────────
def _identify(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                fmt = im.format
                im.verify()                   # structural check of the whole file
            im = Image.open(io.BytesIO(data))
            im.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            OSError, SyntaxError, ValueError):
        raise PhotoError({"photo": "This file is not a photo the archive can accept. Use a JPEG, PNG or WebP image."}) from None
    if fmt not in FORMATS:
        raise PhotoError({"photo": "This file is not a photo the archive can accept. Use a JPEG, PNG or WebP image."})
    return im, fmt


def _derive(im, side):
    """A re-encoded JPEG copy. Nothing embedded in the original (EXIF, GPS, comments) is carried over."""
    im = ImageOps.exif_transpose(im)             # keep the photo upright once orientation data is dropped
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.getchannel("A"))
        im = flat
    elif im.mode != "RGB":
        im = im.convert("RGB")
    im.thumbnail((side, side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    return buf.getvalue(), im.size


# ───────────── metadata ─────────────
def validate_meta(form):
    def text(name, limit):
        v = " ".join((form.get(name) or "").split())
        if len(v) > limit:
            errors[name] = "This is too long."
        return v or None

    errors = {}
    clean = {"caption": text("caption", 500), "creator_text": text("creator_text", 200),
             "place_note": text("place_note", 1000), "people_note": text("people_note", 1000),
             "rights_holder": text("rights_holder", 300)}
    if not clean["caption"]:
        errors["caption"] = "Describe what the photo shows."
    try:
        clean["taken"] = dates.parse(form.get("taken") or "")
    except dates.DateError:
        errors["taken"] = "Use a form like 1952, 1952-03, 1952-03-14, c. 1952, 1950s, or 1950 to 1955."
    rights = (form.get("rights_status") or "").strip()
    if rights not in CONTRIBUTOR_RIGHTS:
        errors["rights_status"] = "Choose one of the listed options."
    clean["rights_status"] = rights
    if form.get("rights_declared") != "1":
        errors["rights_declared"] = "Please confirm this statement to upload the photo."
    return clean, errors


# ───────────── contributor actions ─────────────
def _own_editable(db, user, sid):
    s = db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not s or s["submitter_id"] != user.id:
        raise PermissionDenied("Not your submission.")
    if s["status"] not in EDITABLE:
        raise WorkflowError("Photos can only be added or removed while the submission is a draft or has been returned to you.")
    if s["kind"] not in PHOTO_KINDS:
        raise WorkflowError("Photos cannot be attached to a relationship proposal.")
    return s


UNSUPPORTED = ("This file type is not accepted. Use a photo or scan (JPEG, PNG, WebP), a PDF document, "
               "or an audio or video recording (MP3, M4A, OGG, WAV, MP4, WebM).")
DEFAULT_ITEM_TYPE = {"image": "photograph", "document": "scanned_document", "audio": "audio_recording", "video": "video_recording"}
EXTENSIONS = {"application/pdf": ".pdf", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/ogg": ".ogg", "audio/wav": ".wav",
              "audio/flac": ".flac", "video/mp4": ".mp4", "video/webm": ".webm"}
# Active content a PDF must not contain: it is an archive document, not a program.
PDF_ACTIVE = (b"/JavaScript", b"/JS ", b"/JS(", b"/JS<", b"/Launch", b"/EmbeddedFile", b"/RichMedia", b"/XFA")


def sniff(head):
    """(media_kind, mime) from a file's first bytes, or (None, None). Never from the file name."""
    if head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n" or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image", None
    if head[:5] == b"%PDF-":
        return "document", "application/pdf"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio", "audio/mpeg"
    if head[:4] == b"OggS":
        return "audio", "audio/ogg"
    if head[:4] == b"fLaC":
        return "audio", "audio/flac"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if head[4:8] == b"ftyp":
        return ("audio", "audio/mp4") if head[8:11] in (b"M4A", b"M4B") else ("video", "video/mp4")
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video", "video/webm"
    return None, None


def _limit(kind, config):
    return {"image": config["MAX_PHOTO_BYTES"], "document": config.get("MAX_DOCUMENT_BYTES", 30 * 1024 * 1024)}.get(
        kind, config.get("MAX_AV_BYTES", 250 * 1024 * 1024))


def _hash_and_scan(stream, pdf):
    """SHA-256 of a stream, and for PDFs whether it contains active content. Reads in chunks."""
    h, tail, active = hashlib.sha256(), b"", False
    stream.seek(0)
    while chunk := stream.read(1024 * 1024):
        h.update(chunk)
        if pdf and not active:
            window = tail + chunk
            active = any(m in window for m in PDF_ACTIVE)
            tail = chunk[-32:]
    stream.seek(0)
    return h.hexdigest(), active


def _strip_av_metadata(store, key, mime):
    """With ffmpeg on the server, make a playback copy without embedded metadata (no re-encoding).
    Returns (key, size, sha256) or None. Without ffmpeg the original is used for playback."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not hasattr(store, "path"):
        return None
    out = tempfile.NamedTemporaryFile(suffix=EXTENSIONS.get(mime, ""), delete=False)
    out.close()
    try:
        r = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(store.path(key)), "-map", "0", "-map_metadata", "-1",
                            "-map_chapters", "-1", "-c", "copy", out.name], capture_output=True, timeout=600)
        if r.returncode != 0:
            return None
        new = storage_mod.new_key()
        with open(out.name, "rb") as f:
            store.put_stream(new, f)
        with open(out.name, "rb") as f:
            digest, _ = _hash_and_scan(f, False)
        return new, os.path.getsize(out.name), digest
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.unlink(out.name)
        except OSError:
            pass


def add(db, store, user, sid, upload, filename, form, *, config):
    """Validate and store one file (photo, document, audio or video) on the user's own editable
    submission. `upload` is a file-like object (or bytes). Returns the attachment id."""
    if config.get("REQUIRE_EMAIL_VERIFICATION", True) and not user.email_verified:
        raise PermissionDenied("Please verify your email address before uploading photos.")
    _own_editable(db, user, sid)
    stream = io.BytesIO(upload) if isinstance(upload, (bytes, bytearray)) else upload
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    head = stream.read(64)
    stream.seek(0)
    clean, errors = validate_meta(form)
    kind, mime = sniff(head) if size else (None, None)
    item_type = form.get("item_type") or DEFAULT_ITEM_TYPE.get(kind, "other")
    if item_type not in ITEM_TYPES:
        errors["item_type"] = "Choose one of the listed options."
    transcript = (form.get("transcript") or "").replace("\r\n", "\n").strip()[:100000] or None
    if not size:
        errors["photo"] = "Choose a photo to upload."
    elif kind is None:
        errors["photo"] = UNSUPPORTED
    elif size > _limit(kind, config):
        errors["photo"] = "This photo is too large. Reduce its size and try again."
    if errors:
        raise PhotoError(errors)
    if count(db, sid) >= config["MAX_PHOTOS_PER_SUBMISSION"]:
        raise PhotoError({"photo": "This submission already has the maximum number of photos."})
    if not ratelimit.allow(db, f"upload:{user.id}", 60, 3600):
        raise PhotoError({"photo": "You have uploaded many photos recently. Please wait a while before adding more."})

    if kind == "image":
        data = stream.read()
        im, fmt = _identify(data)
        digest = hashlib.sha256(data).hexdigest()
    else:
        digest, active = _hash_and_scan(stream, kind == "document")
        if active:
            raise PhotoError({"photo": "This PDF contains active content (scripts or embedded files), which the archive does not accept. Print it to a new PDF or scan it, and upload that instead."})
    if db.execute("SELECT 1 FROM media_files WHERE submission_id=? AND file_role='original' AND sha256=?", (sid, digest)).fetchone():
        raise PhotoError({"photo": "This photo is already attached to this submission."})

    written, files = [], []
    try:
        if kind == "image":
            display, dsize = _derive(im, DISPLAY_SIDE)
            thumb, tsize = _derive(im, THUMB_SIDE)
            for blob, m, (w, h), role in ((data, FORMATS[fmt], im.size, "original"), (display, "image/jpeg", dsize, "access_derivative"),
                                          (thumb, "image/jpeg", tsize, "thumbnail")):
                key = storage_mod.new_key()
                store.put(key, blob)
                written.append(key)
                files.append((key, m, len(blob), w, h, hashlib.sha256(blob).hexdigest(), role))
        else:
            key = storage_mod.new_key()
            store.put_stream(key, stream)
            written.append(key)
            files.append((key, mime, size, None, None, digest, "original"))
            if kind in ("audio", "video"):
                stripped = _strip_av_metadata(store, key, mime)
                if stripped:
                    written.append(stripped[0])
                    files.append((stripped[0], mime, stripped[1], None, None, stripped[2], "access_derivative"))
        with tx(db):
            orig_id = None
            for key, m, sz, w, h, sha, role in files:
                cur = db.execute(
                    "INSERT INTO media_files(submission_id, storage_key, original_filename, mime_type, size_bytes, width, height, "
                    "sha256, file_role, derived_from_id, access_level, processing_status, uploaded_by) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?, 'private', 'done', ?)",
                    (sid, key, (filename or "")[:200] or None, m, sz, w, h, sha, role, orig_id, user.id))
                orig_id = orig_id or cur.lastrowid
            taken = clean["taken"]
            cur = db.execute(
                "INSERT INTO submission_photos(submission_id, original_media_id, caption, creator_text, taken_start, taken_end, "
                "taken_precision, taken_note, place_note, people_note, rights_holder, rights_status, rights_declared, "
                "media_kind, item_type, transcript) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
                (sid, orig_id, clean["caption"], clean["creator_text"], taken.start, taken.end, taken.precision, taken.note,
                 clean["place_note"], clean["people_note"], clean["rights_holder"], clean["rights_status"], kind, item_type, transcript))
            db.execute("UPDATE submissions SET updated_at=? WHERE id=?", (now_iso(), sid))
            audit.log(db, user.id, "photo.uploaded", "submission", sid, {"photo": cur.lastrowid, "sha256": digest, "kind": kind})
            return cur.lastrowid
    except BaseException:
        for key in written:                  # never leave stored files without a database row
            store.delete(key)
        raise


def remove(db, store, user, sid, photo_id):
    """Contributors may remove their own photo before review. Not yet an archive record, so it is deleted."""
    with tx(db):
        _own_editable(db, user, sid)
        p = db.execute("SELECT * FROM submission_photos WHERE id=? AND submission_id=?", (photo_id, sid)).fetchone()
        if not p:
            raise WorkflowError("Photo not found.")
        keys = [r["storage_key"] for r in db.execute(
            "SELECT storage_key FROM media_files WHERE id=? OR derived_from_id=?", (p["original_media_id"],) * 2)]
        db.execute("DELETE FROM submission_photos WHERE id=?", (photo_id,))
        db.execute("DELETE FROM media_files WHERE derived_from_id=?", (p["original_media_id"],))
        db.execute("DELETE FROM media_files WHERE id=?", (p["original_media_id"],))
        audit.log(db, user.id, "photo.removed", "submission", sid, {"photo": photo_id})
    for k in keys:
        store.delete(k)


# ───────────── reading ─────────────
def count(db, sid):
    return db.execute("SELECT COUNT(*) FROM submission_photos WHERE submission_id=?", (sid,)).fetchone()[0]


def pending_count(db, sid):
    return db.execute("SELECT COUNT(*) FROM submission_photos WHERE submission_id=? AND editor_decision='pending'",
                      (sid,)).fetchone()[0]


def list_for_submission(db, sid):
    return db.execute(
        "SELECT p.*, o.storage_key AS original_key, o.original_filename, o.size_bytes, o.width, o.height, o.mime_type, o.sha256, "
        "(SELECT storage_key FROM media_files WHERE derived_from_id=o.id AND file_role='thumbnail') AS thumb_key, "
        "(SELECT storage_key FROM media_files WHERE derived_from_id=o.id AND file_role='access_derivative') AS display_key, "
        "e.public_id AS item_public_id, e.visibility AS item_visibility "
        "FROM submission_photos p JOIN media_files o ON o.id=p.original_media_id "
        "LEFT JOIN entities e ON e.id=p.result_item_id WHERE p.submission_id=? ORDER BY p.id", (sid,)).fetchall()


def research_access(db, user, entity_id):
    """Vetted researchers may see published material that is RESTRICTED (never private or embargoed):
    archive items, and oral histories whose interviewee consented to research access."""
    if not (user and user.can("restricted.view")):
        return False
    from flask import current_app, has_app_context
    if has_app_context() and current_app.config.get("REQUIRE_STAFF_MFA") and not user.mfa_enabled:
        return False                       # the staff two-step policy covers research access too
    e = entities.get(db, entity_id)
    if not e or e["publication_status"] != "published" or e["visibility"] != "restricted" or e["merged_into"] or e["deleted_at"]:
        return False
    if e["kind"] == "archive_item":
        a = db.execute("SELECT access_level, rights_status FROM archive_items WHERE entity_id=?", (entity_id,)).fetchone()
        if a["access_level"] in ("private", "embargoed") or a["rights_status"] in ("private_embargoed",):
            return False
        oh = db.execute("SELECT entity_id FROM oral_histories WHERE media_item_id=?", (entity_id,)).fetchone()
        return oh is None or consent_granted(db, oh["entity_id"], "research_access")
    if e["kind"] == "oral_history":
        return consent_granted(db, entity_id, "research_access")
    return False


def consent_granted(db, oral_history_id, consent_type):
    r = db.execute("SELECT granted FROM consent_records WHERE oral_history_id=? AND consent_type=? AND revoked_at IS NULL",
                   (oral_history_id, consent_type)).fetchone()
    return bool(r and r["granted"])


def can_view_media(db, user, m):
    """The single access rule for every stored file. Called on EVERY request for a file, so a copied
    or guessed URL is worth nothing without the right to see the file."""
    if user and user.can("record.view_any"):
        return True
    if m["owner_id"] is not None:
        if m["file_role"] == "original" and (m["mime_type"].startswith("image/") or db.execute(
                "SELECT 1 FROM media_files WHERE derived_from_id=? AND file_role='access_derivative'", (m["id"],)).fetchone()):
            return False      # when a cleaned copy exists, the original (with its embedded metadata) is staff-only
        ph = ",".join("?" * len(PUBLIC_RIGHTS))
        r = db.execute(f"SELECT 1 FROM entities e JOIN archive_items a ON a.entity_id=e.id WHERE e.id=? AND {PUBLIC_WHERE} "
                       f"AND a.access_level='public' AND a.rights_status IN ({ph})", (m["owner_id"], *PUBLIC_RIGHTS)).fetchone()
        if r is not None:
            return True
        return research_access(db, user, m["owner_id"])
    s = db.execute("SELECT submitter_id FROM submissions WHERE id=?", (m["submission_id"],)).fetchone()
    return bool(user and s and s["submitter_id"] == user.id)


# ───────────── editor actions ─────────────
def decide(db, user, sid, photo_id, form, *, config):
    if not user.can("submission.review"):
        raise PermissionDenied("You do not have permission for this action.")
    with tx(db):
        s = db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        p = db.execute("SELECT * FROM submission_photos WHERE id=? AND submission_id=?", (photo_id, sid)).fetchone()
        if not s or not p:
            raise WorkflowError("Photo not found.")
        if s["status"] not in REVIEW_STATES:
            raise WorkflowError("Photo decisions can only be made while the submission is being reviewed.")
        if s["submitter_id"] == user.id and not config.get("ALLOW_SELF_REVIEW", False):
            raise PermissionDenied("You cannot review your own submission. Another editor must do this.")
        decision = form.get("decision")
        access = form.get("access") or "restricted"
        rights = form.get("rights_status") or p["rights_status"]
        if decision not in ("accept", "decline") or access not in ("public", "restricted") or rights not in RIGHTS_STATUSES:
            raise WorkflowError("Choose one of the listed options.")
        if decision == "decline":
            access = "restricted"
        if access == "public" and rights not in PUBLIC_RIGHTS:
            raise WorkflowError("A photo can be public only when its rights allow it: public domain, permission granted, or licensed for use.")
        caption = " ".join((form.get("published_caption") or "").split())[:500] or p["caption"]
        note = (form.get("editor_note") or "").strip()[:2000] or None
        db.execute("UPDATE submission_photos SET editor_decision=?, editor_access=?, editor_rights_status=?, published_caption=?, "
                   "editor_note=?, decided_by=? WHERE id=?", (decision, access, rights, caption, note, user.id, photo_id))
        audit.log(db, user.id, "photo.decided", "submission", sid,
                  {"photo": photo_id, "decision": decision, "access": access, "rights": rights})


def _title(caption):
    if len(caption) <= 120:
        return caption
    cut = caption[:120].rsplit(" ", 1)[0]
    return cut + "…"


def publish_for_submission(db, s, record_id, actor_id):
    """Inside the publication transaction: turn included photos into archive items linked to the record."""
    photos = db.execute("SELECT * FROM submission_photos WHERE submission_id=? ORDER BY id", (s["id"],)).fetchall()
    if not photos:
        return 0
    if any(p["editor_decision"] == "pending" for p in photos):
        raise WorkflowError("Decide on every photo (include it or leave it out) before publishing.")
    record = db.execute(f"SELECT e.* FROM entities e WHERE e.id=? AND {PUBLIC_WHERE}", (record_id,)).fetchone()
    raw = entities.get(db, record_id)
    added = 0
    for p in photos:
        if p["editor_decision"] != "accept":
            continue
        rights = p["editor_rights_status"] or p["rights_status"]
        # A photo of a restricted record (e.g. a living person without consent) is never public.
        public = p["editor_access"] == "public" and rights in PUBLIC_RIGHTS and record is not None
        vis = "public" if public else "restricted"
        caption = p["published_caption"] or p["caption"]
        title = _title(caption)
        eid, pid, _ = entities.create_entity(db, "archive_item", title, created_by=actor_id, status="published",
                                             visibility=vis, fictional=bool(raw["is_fictional_test"]))
        db.execute(
            "INSERT INTO archive_items(entity_id, title, item_type, description, created_start, created_end, created_precision, "
            "created_note, creator, uploaded_by, provenance, rights_holder, rights_status, access_level, media_kind, transcript) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, title, p["item_type"], caption if caption != title else None, p["taken_start"], p["taken_end"], p["taken_precision"],
             p["taken_note"], p["creator_text"], s["submitter_id"], "Contributed to the archive and reviewed by an editor.",
             p["rights_holder"], rights, vis, p["media_kind"], p["transcript"]))
        entities.add_name(db, eid, title, "preferred")
        db.execute("INSERT INTO archive_item_subjects(item_id, subject_id) VALUES (?,?)", (eid, record_id))
        db.execute("UPDATE media_files SET owner_id=?, access_level=? WHERE id=? OR derived_from_id=?",
                   (eid, vis, p["original_media_id"], p["original_media_id"]))
        db.execute("UPDATE submission_photos SET result_item_id=? WHERE id=?", (eid, p["id"]))
        entities.add_revision(db, eid, actor_id, "Created from an approved contribution", submission_id=s["id"])
        audit.log(db, actor_id, "archive_item.published", "archive_item", pid, {"submission": s["id"], "visibility": vis})
        search.reindex(db, eid)
        added += 1
    if added:
        entities.add_revision(db, record_id, actor_id, f"{added} photograph{'s' if added != 1 else ''} added",
                              submission_id=s["id"])
    return added


def sync_item_access(db, item_id):
    """Keep an archive item's access level and its files in step with the item's publication state."""
    e = entities.get(db, item_id)
    public = e["publication_status"] == "published" and e["visibility"] == "public" and not e["deleted_at"]
    level = "public" if public else "restricted"
    db.execute("UPDATE archive_items SET access_level=? WHERE entity_id=?", (level, item_id))
    db.execute("UPDATE media_files SET access_level=? WHERE owner_id=?", (level, item_id))
