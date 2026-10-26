"""Owner-scoped SQLite journal; legacy records remain assigned to local only."""
import json
from datetime import datetime, timezone
from contextlib import contextmanager
from quantmesh.sqlite_utils import open_database


@contextmanager
def connect(path: str):
    from quantmesh.backend import backend, PersistenceError
    if backend() != "sqlite":
        raise PersistenceError("SQLite access is disabled for the selected backend.")
    conn = open_database(path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("Journal schema is newer than this application. Restore a compatible release.")
            conn.execute("CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, "
                         "created TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
            if "owner" not in columns:
                conn.execute("ALTER TABLE runs ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'")
            conn.execute("CREATE INDEX IF NOT EXISTS runs_owner_id ON runs(owner,id)")
            conn.execute("PRAGMA user_version=1")
            yield conn
    finally:
        conn.close()


def save_run(path: str, name: str, payload: dict, *, owner: str = "local") -> int:
    validate_owner(owner)
    if not name.strip() or len(name) > 100:
        raise ValueError("Run name must contain 1 to 100 characters.")
    from quantmesh.backend import backend
    if backend() == "postgres":
        from quantmesh.postgres import save_run as save
        return save(name, payload, owner)
    with connect(path) as conn:
        cursor = conn.execute("INSERT INTO runs(created,name,payload,owner) VALUES (?,?,?,?)",
                              (datetime.now(timezone.utc).isoformat(), name.strip(),
                               json.dumps(payload, allow_nan=False), owner))
        return cursor.lastrowid


def list_runs(path: str, *, owner: str = "local") -> list[dict]:
    validate_owner(owner)
    from quantmesh.backend import backend
    if backend() == "postgres":
        from quantmesh.postgres import list_runs as read
        return read(owner)
    with connect(path) as conn:
        rows = conn.execute("SELECT id,created,name,payload FROM runs WHERE owner=? "
                            "ORDER BY id DESC LIMIT 50", (owner,))
        return [dict(id=r[0], created=r[1], name=r[2], payload=json.loads(r[3])) for r in rows]


def validate_owner(owner: str):
    from quantmesh.auth import USERNAME
    if not isinstance(owner, str) or not USERNAME.fullmatch(owner):
        raise ValueError("Invalid research owner.")
