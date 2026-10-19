"""Operator-only online SQLite backup and verified, non-overwriting offline restore."""
import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from quantmesh.account_store import account_lock, replace_users
from quantmesh.auth import load_users

FILES = ("research.sqlite3", "market.sqlite3", "users.json")


def copy_sqlite(source: Path, target: Path):
    source_conn = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn, pages=256, sleep=0.01)
        if target_conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed.")
    finally:
        source_conn.close()
        target_conn.close()
    os.chmod(target, 0o600)


def digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def backup(data_dir: Path, destination: Path):
    from quantmesh.serve import preflight
    paths = preflight()
    if data_dir.resolve() != Path(os.environ["QUANTMESH_DATA_DIR"]).resolve():
        raise ValueError("Backup data directory does not match the configured production storage.")
    if destination.resolve().is_relative_to(data_dir.resolve()):
        raise ValueError("Backup destination must be outside the live data directory.")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    complete = False
    try:
        with account_lock(paths["QUANTMESH_USERS_FILE"]):
            replace_users(destination / "users.json", load_users(str(paths["QUANTMESH_USERS_FILE"])))
            copy_sqlite(paths["QUANTMESH_DB"], destination / "research.sqlite3")
            copy_sqlite(paths["QUANTMESH_CACHE_DB"], destination / "market.sqlite3")
        manifest = {"version": 1, "sha256": {
            name: digest(destination / name)
            for name in FILES}}
        with (destination / "manifest.json").open("w") as manifest_file:
            json.dump(manifest, manifest_file, indent=2)
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
        os.chmod(destination / "manifest.json", 0o600)
        complete = True
    finally:
        if not complete:
            # Only remove files created in this new, private destination.
            for path in destination.iterdir():
                path.unlink()
            destination.rmdir()


def restore(source: Path, destination: Path, *, app_stopped: bool):
    if not app_stopped:
        raise ValueError("Stop the app and pass --app-stopped before restoring.")
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("version") != 1 or set(manifest.get("sha256", {})) != set(FILES):
        raise ValueError("Unsupported backup manifest.")
    for name in FILES:
        with (source / name).open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != manifest["sha256"][name]:
                raise ValueError("Backup checksum mismatch.")
    users = load_users(str(source / "users.json"))
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A deployment operator must stop all writers. Never overwrite a live file or WAL.
    if any((destination / name).exists() or (destination / (name + "-wal")).exists()
           or (destination / (name + "-shm")).exists() for name in FILES):
        raise ValueError("Restore target already contains database/account files. Use a new directory.")
    created = []
    try:
        for name in FILES[:2]:
            target = destination / name
            created.append(target)
            copy_sqlite(source / name, target)
        conn = sqlite3.connect(destination / FILES[0])
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise ValueError("Backup schema is newer than this application.")
        finally:
            conn.close()
        created.append(destination / "users.json")
        replace_users(destination / "users.json", users)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    create = actions.add_parser("create")
    create.add_argument("--destination", type=Path, required=True)
    recover = actions.add_parser("restore")
    recover.add_argument("--source", type=Path, required=True)
    recover.add_argument("--destination", type=Path, required=True)
    recover.add_argument("--app-stopped", action="store_true")
    args = parser.parse_args()
    if args.command == "create":
        backup(Path(os.environ["QUANTMESH_DATA_DIR"]), args.destination)
    else:
        restore(args.source, args.destination, app_stopped=args.app_stopped)
    print("Backup operation completed. Protect account hashes and research as private data.")


if __name__ == "__main__":
    main()
