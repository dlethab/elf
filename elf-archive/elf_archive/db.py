"""SQLite access, explicit transactions, and the migration runner."""
import itertools
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

from .vocab import VOCAB

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_savepoints = itertools.count(1)

DATE_MACRO = (
    "{p}_start TEXT, {p}_end TEXT, "
    "{p}_precision TEXT NOT NULL DEFAULT 'unknown' CHECK ({p}_precision IN ({prec}) "
    "AND ({p}_precision <> 'unknown' OR {p}_start IS NULL)), "
    "{p}_note TEXT"
)


def connect(path):
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db():
    if "db" not in g:
        shared = current_app.config.get("_SHARED_CONNECTION")   # tests use one in-memory db
        g.db = shared if shared is not None else connect(current_app.config["DATABASE_PATH"])
        g.db_shared = shared is not None
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None and not g.pop("db_shared", False):
        db.close()


@contextmanager
def tx(db):
    """Atomic block. Nested use becomes a savepoint, so services can compose safely."""
    if db.in_transaction:
        name = f"sp_{next(_savepoints)}"
        db.execute(f"SAVEPOINT {name}")
        try:
            yield db
        except BaseException:
            db.execute(f"ROLLBACK TO {name}")
            db.execute(f"RELEASE {name}")
            raise
        else:
            db.execute(f"RELEASE {name}")
    else:
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except BaseException:
            db.execute("ROLLBACK")
            raise
        else:
            db.execute("COMMIT")


def _expand(sql):
    sql = re.sub(r"\{\{VOCAB:(\w+)\}\}",
                 lambda m: ",".join(f"'{v}'" for v in VOCAB[m.group(1)]), sql)
    prec = ",".join(f"'{v}'" for v in VOCAB["PRECISIONS"])
    return re.sub(r"\{\{DATE:(\w+)\}\}", lambda m: DATE_MACRO.format(p=m.group(1), prec=prec), sql)


FK_OFF_MARKER = "-- migrate: foreign_keys=off"


def pending_migrations(path):
    """Names of migrations not yet applied to the database file (read-only check)."""
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    except sqlite3.OperationalError:
        done = set()
    finally:
        conn.close()
    return [f.stem for f in sorted(MIGRATIONS_DIR.glob("*.sql")) if f.stem not in done]


def migrate(db):
    """Apply pending migrations in order. Each file runs atomically.

    A migration that rebuilds a table (SQLite cannot change a CHECK constraint in place) starts with
    the line `-- migrate: foreign_keys=off`. It then runs with foreign-key enforcement suspended, as
    SQLite's documented table-rebuild procedure requires, and is committed only if
    `PRAGMA foreign_key_check` finds no broken reference afterwards."""
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
               "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')))")
    done = {r[0] for r in db.execute("SELECT version FROM schema_migrations")}
    applied = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if f.stem in done:
            continue
        sql = _expand(f.read_text(encoding="utf-8"))
        record = "\nINSERT INTO schema_migrations(version) VALUES ('" + f.stem + "');"
        fk_off = sql.lstrip().startswith(FK_OFF_MARKER)
        try:
            if fk_off:
                db.execute("PRAGMA foreign_keys = OFF")
                db.executescript("BEGIN;\n" + sql + record)
                broken = db.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"Migration {f.stem} would break {len(broken)} references; rolled back.")
                db.execute("COMMIT")
            else:
                db.executescript("BEGIN;\n" + sql + record + "\nCOMMIT;")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            if fk_off:
                db.execute("PRAGMA foreign_keys = ON")
        applied.append(f.stem)
    return applied
