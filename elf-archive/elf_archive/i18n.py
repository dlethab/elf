"""Interface languages: English (source), Tigrinya and Arabic (right-to-left).

Only INTERFACE text is translated. Historical content (names, biographies, captions, sources) is
always shown exactly as it was recorded, in whatever language and script it was entered.

The Tigrinya and Arabic catalogues in translations/*.json are DRAFTS until reviewed by native
speakers; the site says so on every translated page. A missing translation falls back to English,
so an incomplete catalogue never breaks a page.

Strings are looked up by their English text: `_("Search the archive")`. Placeholders use
str.format names: `_("{n} published records", n=5)`.
"""
import json
from pathlib import Path

from flask import g, request

from .services import dates

LANGUAGES = {
    "en": {"name": "English", "dir": "ltr"},
    "ti": {"name": "ትግርኛ", "dir": "ltr"},
    "ar": {"name": "العربية", "dir": "rtl"},
}
DEFAULT = "en"
COOKIE = "elf_lang"
CATALOG_DIR = Path(__file__).parent / "translations"

# Pages that are still English-only. They are marked lang="en" so screen readers pronounce them
# correctly, and visitors using another language are told why.
ENGLISH_ONLY_PREFIXES = ("editor.", "admin.", "dev.", "community.mod")
ENGLISH_ONLY_ENDPOINTS = set()
# Legal drafts are translated only after a lawyer has approved the English text.
ENGLISH_ONLY_PAGES = {"privacy", "terms", "copyright", "data-policy"}

_catalogs = {}
_reviewed = {}


def catalog(lang):
    if lang not in _catalogs:
        path = CATALOG_DIR / f"{lang}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        meta = data.pop("_meta", None) or {}
        _reviewed[lang] = meta.get("status") == "reviewed"
        _catalogs[lang] = data
    return _catalogs[lang]


def is_draft(lang):
    """True until a native-speaker review is recorded by setting "_meta": {"status": "reviewed"} in the catalogue."""
    catalog(lang)
    return not _reviewed.get(lang, False)


def select_language():
    """before_request: the visitor's choice is a cookie; anything unknown means English."""
    lang = request.cookies.get(COOKIE)
    g.lang = lang if lang in LANGUAGES else DEFAULT


def current():
    return g.get("lang", DEFAULT)


def gettext(text, **kw):
    if not text:
        return text
    lang = current()
    out = (catalog(lang).get(text) if lang != DEFAULT else None) or text
    if kw:
        try:
            return out.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text.format(**kw)     # a broken translation never breaks the page
    return out


def fdate(start, end=None, precision="unknown"):
    return dates.format_date(start, end, precision, months=[gettext(m) for m in dates.MONTHS],
                             approx=gettext("c."), unknown=gettext("Unknown"))


def precision_note(precision):
    return gettext(dates.precision_note(precision))


def is_english_only(endpoint, view_args=None):
    if endpoint == "public.info":
        return (view_args or {}).get("page") in ENGLISH_ONLY_PAGES
    return bool(endpoint) and (endpoint.startswith(ENGLISH_ONLY_PREFIXES) or endpoint in ENGLISH_ONLY_ENDPOINTS)
