import os

DEV_SECRET = "dev-only-insecure-secret-change-me"


def _bool(name, default):
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _origins(value, env):
    """Validated origins ('https://host' or 'https://host:port', nothing else). http:// only outside production."""
    import re
    items = value if isinstance(value, (list, tuple)) else re.split(r"[\s,]+", value or "")
    out = []
    for o in (i.strip().rstrip("/") for i in items):
        if not o:
            continue
        if not re.fullmatch(r"https://[a-z0-9.-]+(:\d{1,5})?" if env == "production" else r"https?://[a-z0-9.-]+(:\d{1,5})?", o.lower()):
            raise RuntimeError(f"ELF_EMBED_ORIGINS: '{o}' is not a site address like https://elfveterans.org")
        out.append(o.lower())
    return out


def load_config(overrides=None):
    env = (overrides or {}).get("ENV") or os.environ.get("ELF_ENV", "development")
    cfg = {
        "ENV": env,
        "SECRET_KEY": os.environ.get("ELF_SECRET_KEY", DEV_SECRET),
        "DATABASE_PATH": os.environ.get("ELF_DATABASE_PATH", "instance/archive.db"),
        "BASE_URL": os.environ.get("ELF_BASE_URL", "http://localhost:5000").rstrip("/"),
        "SITE_NAME": os.environ.get("ELF_SITE_NAME", "ELF Digital Historical Archive"),
        "CONTACT_EMAIL": os.environ.get("ELF_CONTACT_EMAIL", ""),
        "REQUIRE_EMAIL_VERIFICATION": _bool("ELF_REQUIRE_EMAIL_VERIFICATION", True),
        "ALLOW_SELF_REVIEW": _bool("ELF_ALLOW_SELF_REVIEW", False),
        # Staff (editors, moderators, researchers, administrators) must turn on two-step sign-in.
        "REQUIRE_STAFF_MFA": _bool("ELF_REQUIRE_STAFF_MFA", False),
        "SESSION_LIFETIME_SECONDS": int(os.environ.get("ELF_SESSION_LIFETIME_SECONDS", 7 * 24 * 3600)),
        "SMTP_HOST": os.environ.get("ELF_SMTP_HOST", ""),
        "SMTP_PORT": int(os.environ.get("ELF_SMTP_PORT", 587)),
        "SMTP_USER": os.environ.get("ELF_SMTP_USER", ""),
        "SMTP_PASSWORD": os.environ.get("ELF_SMTP_PASSWORD", ""),
        "SMTP_FROM": os.environ.get("ELF_SMTP_FROM", ""),
        # On a development machine pending migrations are applied at start-up, so new code never meets an old
        # database. In production they are applied deliberately (`flask --app elf_archive migrate`, after a backup).
        "AUTO_MIGRATE": _bool("ELF_AUTO_MIGRATE", env == "development"),
        # Number of reverse proxies in front of the app (1 for nginx or Caddy on the same server). 0 = none.
        "TRUSTED_PROXIES": int(os.environ.get("ELF_TRUSTED_PROXIES", 0)),
        # Uploaded files live OUTSIDE the web-served static folder and are only served through the
        # access-checking /media route. Local disk for now; S3-compatible storage is a later option.
        "MEDIA_ROOT": os.environ.get("ELF_MEDIA_ROOT", "instance/media"),
        # Optional street-level map layer (e.g. OpenStreetMap). Empty = the archive's own base map only,
        # with no third party involved. Example: https://tile.openstreetmap.org/{z}/{x}/{y}.png
        "MAP_TILE_URL": os.environ.get("ELF_MAP_TILE_URL", ""),
        "MAP_TILE_ATTRIBUTION": os.environ.get("ELF_MAP_TILE_ATTRIBUTION", ""),
        "MAX_PHOTO_BYTES": int(os.environ.get("ELF_MAX_PHOTO_MB", 15)) * 1024 * 1024,
        "MAX_PHOTOS_PER_SUBMISSION": int(os.environ.get("ELF_MAX_PHOTOS_PER_SUBMISSION", 10)),
        "MAX_DOCUMENT_BYTES": int(os.environ.get("ELF_MAX_DOCUMENT_MB", 30)) * 1024 * 1024,
        "MAX_AV_BYTES": int(os.environ.get("ELF_MAX_AV_MB", 250)) * 1024 * 1024,
        # The largest accepted upload plus room for the form fields.
        "MAX_CONTENT_LENGTH": (max(int(os.environ.get("ELF_MAX_PHOTO_MB", 15)), int(os.environ.get("ELF_MAX_DOCUMENT_MB", 30)),
                                   int(os.environ.get("ELF_MAX_AV_MB", 250))) + 2) * 1024 * 1024,
    }
    # Sites allowed to show the map and timeline in a frame (space- or comma-separated origins), e.g.
    # ELF_EMBED_ORIGINS="https://elfveterans.org https://www.elfveterans.org". Empty = no site may (the default).
    cfg["EMBED_ORIGINS"] = os.environ.get("ELF_EMBED_ORIGINS", "")
    cfg.update(overrides or {})
    cfg["EMBED_ORIGINS"] = _origins(cfg["EMBED_ORIGINS"], cfg["ENV"])
    if cfg["ENV"] == "production":
        if cfg["SECRET_KEY"] == DEV_SECRET or len(cfg["SECRET_KEY"]) < 32:
            raise RuntimeError("ELF_SECRET_KEY must be set to a random value of at least 32 characters in production.")
        if not cfg["BASE_URL"].startswith("https://"):
            raise RuntimeError("ELF_BASE_URL must be an https:// URL in production.")
    return cfg
