"""Operator commands:  flask --app elf_archive <command>

  migrate            apply pending database migrations
  create-admin       create the first administrator (prompts for the password; never pass it as an argument)
  send-email         deliver queued email through SMTP (requires ELF_SMTP_* settings)
  reindex            rebuild the public search index from the database
  backup DEST [--media DIR]   online copy of the database (+ incremental copy of media files)
  export-public DEST.zip      public data export (JSON + CSV, public fields only)
  seed-test-data     DEVELOPMENT ONLY: add clearly labelled fictional records for trying the interface
"""
import getpass
import os
import smtplib

import click
from flask import current_app
from werkzeug.security import generate_password_hash

from . import db as dbm
from .db import tx
from .services import accounts, audit, search
from .services.timeutil import now_iso


def _conn():
    return dbm.connect(current_app.config["DATABASE_PATH"])


def register(app):
    @app.cli.command("migrate")
    def migrate_cmd():
        conn = _conn()
        applied = dbm.migrate(conn)
        click.echo("Applied: " + (", ".join(applied) if applied else "nothing (already up to date)"))

    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--username", required=True)
    @click.option("--display-name", default=None)
    def create_admin(email, username, display_name):
        conn = _conn()
        pw = getpass.getpass("Password (min 10 characters): ")
        if pw != getpass.getpass("Repeat password: "):
            raise click.ClickException("Passwords do not match.")
        err = accounts.validate_password(pw, email=email, username=username)
        if err:
            raise click.ClickException(err)
        with tx(conn):
            if conn.execute("SELECT 1 FROM users WHERE email=? OR username=?", (email, username)).fetchone():
                raise click.ClickException("A user with that email or username already exists.")
            cur = conn.execute("INSERT INTO users(email, username, display_name, password_hash, email_verified_at) VALUES (?,?,?,?,?)",
                               (email, username, display_name or username, generate_password_hash(pw), now_iso()))
            uid = cur.lastrowid
            for role in ("administrator", "editor"):
                conn.execute("INSERT INTO user_roles(user_id, role) VALUES (?,?)", (uid, role))
            audit.log(conn, None, "account.admin_created_cli", "user", uid)
        click.echo(f"Administrator '{username}' created.")

    @app.cli.command("send-email")
    def send_email():
        cfg = current_app.config
        if not cfg["SMTP_HOST"] or not cfg["SMTP_FROM"]:
            raise click.ClickException("Set ELF_SMTP_HOST and ELF_SMTP_FROM first. Queued mail stays in the outbox table.")

        def factory():
            s = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20)
            s.starttls()
            if cfg["SMTP_USER"]:
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            return s
        conn = _conn()
        click.echo(f"Sent {accounts.deliver_outbox(conn, factory, cfg['SMTP_FROM'])} message(s).")

    @app.cli.command("reindex")
    def reindex():
        conn = _conn()
        with tx(conn):
            search.rebuild_all(conn)
        click.echo("Search index rebuilt.")

    @app.cli.command("backup")
    @click.argument("destination")
    @click.option("--media", "media_dest", default=None,
                  help="Also copy media files into this folder (incremental: files already copied are skipped).")
    def backup(destination, media_dest):
        """Consistent online copy of the database (safe while the site is running), then an integrity check."""
        import os
        import shutil
        import sqlite3
        if os.path.exists(destination):
            raise click.ClickException("Destination exists; choose a new file name (e.g. include the date).")
        src = _conn()
        dst = sqlite3.connect(destination)
        with dst:
            src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {k: dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for k, t in (("entities", "entities"), ("revisions", "revisions"), ("users", "users"), ("audit", "audit_logs"))}
        dst.close()
        if result != "ok":
            raise click.ClickException(f"Backup written but integrity check failed: {result}")
        copied = 0
        if media_dest:
            # stored files are never modified after upload (new versions get new keys), so name + size identifies a copy
            root = current_app.config["MEDIA_ROOT"]
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    s = os.path.join(dirpath, f)
                    d = os.path.join(media_dest, os.path.relpath(s, root))
                    if not (os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s)):
                        os.makedirs(os.path.dirname(d), exist_ok=True)
                        shutil.copy2(s, d)
                        copied += 1
        with tx(src):
            audit.log(src, None, "system.backup", "system", None,
                      {"destination": os.path.basename(destination), "media_copied": copied if media_dest else None, **counts})
        click.echo(f"Backup written to {destination} (integrity ok; {counts})"
                   + (f"; {copied} new media file(s) copied to {media_dest}" if media_dest else ""))

    @app.cli.command("export-public")
    @click.argument("destination")
    @click.option("--include-fictional", is_flag=True, help="Development only: include fictional test records.")
    def export_public(destination, include_fictional):
        """Write the public data export (JSON + CSV, public fields only) to a ZIP file."""
        import os
        from .services import export as ex
        if os.path.exists(destination):
            raise click.ClickException("Destination exists; choose a new file name.")
        if include_fictional and current_app.config["ENV"] == "production":
            raise click.ClickException("Fictional test records cannot be exported from production.")
        conn = _conn()
        with tx(conn):
            data, manifest = ex.export_zip(conn, None, current_app.config["BASE_URL"], include_fictional, via="cli")
        with open(destination, "wb") as f:
            f.write(data)
        click.echo(f"Public export written to {destination}: {manifest['counts']}")

    @app.cli.command("sample-db")
    @click.option("--path", default="instance/sample.db", show_default=True, help="Where to create the sample database.")
    @click.option("--media", default="instance/sample-media", show_default=True, help="Where to keep its files.")
    def sample_db(path, media):
        """Build a SEPARATE, fully fictional sample archive (replaces any earlier sample; never the real database)."""
        if current_app.config["ENV"] == "production":
            raise click.ClickException("Refusing to build sample data on a production server.")
        from .sampledata import USERS, build
        click.echo("Building the sample archive (about a minute)…")
        password, report = build(path, media, current_app.config["DATABASE_PATH"])
        lines = [f"Sample archive created: {path}", *report, "", f"Every account uses the password: {password}"]
        lines += [f"  {name:<18} {why}" for name, _roles, _verified, why in USERS]
        lines += ["", "To open it:  .\\run-sample.ps1   then visit http://127.0.0.1:5001",
                  "Everything in it is fictional. Run this command again to start over."]
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(os.path.join(os.path.dirname(path) or ".", "sample-accounts.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        click.echo("\n".join(lines))

    @app.cli.command("seed-test-data")
    def seed_test_data():
        if current_app.config["ENV"] == "production":
            raise click.ClickException("Refusing to add fictional data to a production database.")
        from .devseed import seed
        click.echo(seed(_conn()))
