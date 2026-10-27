"""Operator-only PostgreSQL schema, consistent private exports and empty-target recovery."""
import argparse
import hashlib
import getpass
import re
import warnings
import json
import os
import sqlite3
from pathlib import Path

from psycopg import sql

from quantmesh.auth import load_file_users, validate_users
from quantmesh.backup import FILES, digest
from quantmesh.http import ServiceError
from quantmesh.postgres import TABLES, migrate, transaction
from quantmesh.storage import validate_owner

COLUMNS = {
    "accounts": ("username", "record"),
    "runs": ("id", "created", "name", "payload", "owner"),
    "request_budget": ("service", "requested"),
    "market_cache": ("symbol", "fetched", "payload"),
    "yahoo_history": ("cache_key", "fetched", "payload"),
}
MAX_EXPORT = 64 * 1024 * 1024


def checksum(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def export_state(destination):
    """One MVCC snapshot of all durable state; never includes connection/session secrets."""
    destination = Path(destination).resolve()
    checkout = Path(__file__).resolve().parents[1]
    if destination.is_relative_to(checkout) or destination.is_relative_to(Path.cwd()):
        raise ValueError("Write the private export outside the checkout/working directory.")
    with transaction(snapshot=True) as conn:
        data = {table: [list(row) for row in conn.execute(sql.SQL("SELECT {} FROM quantmesh.{}").format(
            sql.SQL(",").join(map(sql.Identifier, COLUMNS[table])), sql.Identifier(table))).fetchall()]
                for table in TABLES}
    raw = json.dumps({"version": 1, "sha256": checksum(data), "tables": data}, allow_nan=False).encode()
    if len(raw) > MAX_EXPORT:
        raise ValueError("Export exceeds 64 MiB. Use operator pg_dump/pg_restore instead.")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def validate_snapshot(data):
    if not isinstance(data, dict) or set(data) != set(TABLES):
        raise ValueError("Unsupported snapshot tables.")
    if any(not isinstance(rows, list) or any(not isinstance(row, (list, tuple)) or len(row) != len(COLUMNS[table])
           for row in rows) for table, rows in data.items()):
        raise ValueError("Invalid snapshot rows.")
    accounts = dict(data["accounts"])
    validate_users(accounts)
    if len(accounts) != len(data["accounts"]):
        raise ValueError("Duplicate snapshot account.")
    ids = set()
    for identifier, created, name, payload, owner in data["runs"]:
        validate_owner(owner)
        # Disabled owners retain historical research; never reassign it on import.
        if not isinstance(identifier, int) or identifier <= 0 or identifier in ids:
            raise ValueError("Invalid research identifier.")
        ids.add(identifier)
        if not isinstance(created, str) or not isinstance(name, str) or not 1 <= len(name) <= 100:
            raise ValueError("Invalid research metadata.")
        if not isinstance(json.loads(payload), dict):
            raise ValueError("Invalid research payload.")
    checksum(data)  # Reject nonfinite floats before any writes.


def restore_state(data, *, app_stopped):
    if not app_stopped:
        raise ValueError("Stop all application writers and pass --app-stopped before import/restore.")
    validate_snapshot(data)
    with transaction() as conn:
        # Lock all tables so even an accidental writer cannot interleave with emptiness checks.
        conn.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
            sql.SQL(",").join(sql.Identifier("quantmesh", table) for table in TABLES)))
        if any(conn.execute(sql.SQL("SELECT EXISTS(SELECT 1 FROM quantmesh.{})").format(
                sql.Identifier(table))).fetchone()[0] for table in TABLES):
            raise ValueError("Recovery target is not empty. Use a new migrated database; no records were overwritten.")
        for table in TABLES:
            query = sql.SQL("INSERT INTO quantmesh.{} ({}) VALUES ({})").format(
                sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, COLUMNS[table])),
                sql.SQL(",").join(sql.Placeholder() for _ in COLUMNS[table]))
            with conn.cursor() as cursor:
                rows = data[table]
                if table == "accounts":
                    from psycopg.types.json import Jsonb
                    rows = [(name, Jsonb(record)) for name, record in rows]
                cursor.executemany(query, rows)
        # Preserve imported IDs; set sequence so the next save cannot collide.
        conn.execute("SELECT setval(pg_get_serial_sequence('quantmesh.runs','id'), "
                     "GREATEST(COALESCE((SELECT MAX(id) FROM quantmesh.runs),1),1), "
                     "EXISTS(SELECT 1 FROM quantmesh.runs))")


def read_export(source):
    with Path(source).open("rb") as file:
        raw = file.read(MAX_EXPORT + 1)
    if len(raw) > MAX_EXPORT:
        raise ValueError("Export exceeds supported size.")
    envelope = json.loads(raw)
    data = envelope.get("tables")
    if envelope.get("version") != 1 or envelope.get("sha256") != checksum(data):
        raise ValueError("Export version/checksum mismatch.")
    return data


def read_sqlite_backup(source):
    """Import a verified legacy backup; never read concurrently changing SQLite files."""
    source = Path(source)
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("version") != 1 or set(manifest.get("sha256", {})) != set(FILES):
        raise ValueError("Invalid SQLite backup manifest.")
    for name in FILES:
        if digest(source / name) != manifest["sha256"][name]:
            raise ValueError("SQLite backup checksum mismatch.")
    data = {table: [] for table in TABLES}
    data["accounts"] = list(load_file_users(str(source / "users.json")).items())
    for name, tables in [("research.sqlite3", ("runs",)),
                         ("market.sqlite3", ("request_budget", "market_cache", "yahoo_history"))]:
        with sqlite3.connect((source / name).resolve().as_uri() + "?mode=ro", uri=True) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite backup integrity failure.")
            if name == "research.sqlite3" and conn.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise ValueError("SQLite schema is newer than this application.")
            for table in tables:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    columns = ",".join(COLUMNS[table])  # Constants, not input SQL.
                    if table == "runs":
                        actual = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
                        if "owner" not in actual:
                            columns = "id,created,name,payload,'local'"
                    data[table] = [list(row) for row in conn.execute(f"SELECT {columns} FROM {table}")]
                elif table != "yahoo_history":
                    raise ValueError("SQLite backup is missing required durable state.")
    validate_snapshot(data)
    return data


def _grant_runtime(conn, role):
    row = conn.execute("SELECT oid,rolsuper,rolcreaterole,rolcreatedb,rolbypassrls FROM pg_roles WHERE rolname=%s",
                       (role,)).fetchone()
    if (not row or any(row[1:]) or conn.execute("SELECT current_user").fetchone()[0] == role
            or conn.execute("SELECT 1 FROM pg_auth_members WHERE member=%s", (row[0],)).fetchone()):
        raise ValueError("Runtime role must be separate, unprivileged and have no role memberships.")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA quantmesh TO {}").format(sql.Identifier(role)))
    conn.execute(sql.SQL("GRANT SELECT ON quantmesh.schema_version,quantmesh.accounts TO {}").format(sql.Identifier(role)))
    conn.execute(sql.SQL("GRANT SELECT,INSERT ON quantmesh.runs TO {}").format(sql.Identifier(role)))
    conn.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON quantmesh.request_budget,"
                        "quantmesh.market_cache,quantmesh.yahoo_history TO {}").format(sql.Identifier(role)))
    conn.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA quantmesh TO {}").format(sql.Identifier(role)))


def grant_runtime(role):
    """Grant only web-app operations to an already-created, unprivileged login role."""
    with transaction() as conn:
        _grant_runtime(conn, role)


def create_runtime(role, password):
    """Neon requires a plaintext DB-role password over TLS, not psql's client hash.

    Utility DDL cannot use server bind parameters; psycopg Identifier/Literal
    quote both values. No credential appears in CLI arguments, files or our logs.
    This is a database connection password, not an end-user password record.
    """
    if (not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", role)
            or not 32 <= len(password) <= 1024 or "\x00" in password):
        raise ValueError("Use a safe database role name and a random 32+ character password.")
    with transaction() as conn:
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
            raise ValueError("Database role already exists; refusing to reset its password or privileges.")
        conn.execute("SET LOCAL password_encryption = 'scram-sha-256'")
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                            "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}").format(
                                sql.Identifier(role), sql.Literal(password)))
        _grant_runtime(conn, role)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    grant = commands.add_parser("grant-runtime")
    grant.add_argument("role")
    create = commands.add_parser("create-runtime")
    create.add_argument("role")
    export = commands.add_parser("export")
    export.add_argument("--destination", type=Path, required=True)
    for name in ("restore", "import-sqlite"):
        action = commands.add_parser(name)
        action.add_argument("--source", type=Path, required=True)
        action.add_argument("--app-stopped", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            migrate()
        elif args.command == "create-runtime":
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("New runtime database password (random 32+ characters): ")
                if password != getpass.getpass("Confirm runtime database password: "):
                    raise ValueError("Passwords do not match.")
            create_runtime(args.role, password)
        elif args.command == "grant-runtime":
            grant_runtime(args.role)
        elif args.command == "export":
            export_state(args.destination)
        else:
            data = read_export(args.source) if args.command == "restore" else read_sqlite_backup(args.source)
            restore_state(data, app_stopped=args.app_stopped)
    except (ServiceError, OSError, ValueError, sqlite3.Error, TypeError, KeyError,
            getpass.GetPassWarning, EOFError):
        raise SystemExit("Database operation failed. Check configuration, schema, private backup and empty-target requirements. No secrets were logged.") from None
    print("Database operation completed. Protect exported hashes and private research.")


if __name__ == "__main__":
    main()
