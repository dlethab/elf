"""Name handling. Originals are stored untouched; `normalize` produces a separate search form.

Normalization (search form only): Unicode NFKD, drop combining marks (Latin and Arabic
diacritics), case-fold, delete apostrophe-like marks so "Ghebre'ab" and "Ghebreab" meet,
turn other punctuation into spaces. Ge'ez (Ethiopic) letters are letters and survive intact.
Normalization never decides that two names are the same person; editors do.
"""
import re
import unicodedata

_APOS = dict.fromkeys(map(ord, "'’‘ʼʻʿʾ`´"), None)
_TATWEEL = "ـ"


def normalize(text):
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text).translate(_APOS).replace(_TATWEEL, "")
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    t = "".join(c if c.isalnum() else " " for c in t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(text):
    return normalize(text).split()


def slugify(text, fallback):
    """ASCII slug when possible; otherwise the permanent id (so non-Latin names never produce '')."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).replace("'", "").replace("’", "")
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t[:60].strip("-") or fallback
