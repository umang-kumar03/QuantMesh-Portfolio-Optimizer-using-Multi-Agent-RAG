"""Fail-closed production launcher; validates durable paths before binding a socket."""
import os
import secrets
import sqlite3
import sys
from pathlib import Path

from quantmesh.auth import load_users, session_key
from quantmesh.account_store import account_lock, replace_users
from quantmesh.http import ServiceError
from quantmesh.market import database
from quantmesh.storage import connect


def preflight() -> dict[str, Path]:
    if os.environ.get("QUANTMESH_AUTH_MODE") != "multi-user":
        raise ServiceError("Production startup requires QUANTMESH_AUTH_MODE=multi-user.")
    session_key()
    root = Path(os.environ.get("QUANTMESH_DATA_DIR", "")).resolve()
    if not os.environ.get("QUANTMESH_DATA_DIR") or not root.is_dir():
        raise ServiceError("QUANTMESH_DATA_DIR must be an existing mounted persistent directory.")
    paths = {}
    for name in ("QUANTMESH_DB", "QUANTMESH_CACHE_DB", "QUANTMESH_USERS_FILE"):
        value = os.environ.get(name, "")
        path = Path(value).resolve()
        if not value or not Path(value).is_absolute() or not path.is_relative_to(root) or path == root:
            raise ServiceError("All production database/account paths must be absolute and below QUANTMESH_DATA_DIR.")
        paths[name] = path
    if len(set(paths.values())) != 3:
        raise ServiceError("Research, cache and account storage must use distinct files.")
    probe = root / (".quantmesh-write-check-" + secrets.token_hex(8))
    try:
        with probe.open("xb"):
            pass
    finally:
        probe.unlink(missing_ok=True)
    target = paths["QUANTMESH_USERS_FILE"]
    # Seed exactly once from a host-managed secret file. Redeploys never overwrite accounts.
    with account_lock(target):
        if not target.exists():
            bootstrap = os.environ.get("QUANTMESH_BOOTSTRAP_USERS_FILE", "")
            if not bootstrap:
                raise ServiceError("Provision accounts or set QUANTMESH_BOOTSTRAP_USERS_FILE for first startup.")
            replace_users(target, load_users(bootstrap))
    load_users(str(target))
    if os.name != "nt" and target.stat().st_mode & 0o077:
        raise ServiceError("Account file must be private (chmod 600).")
    with connect(str(paths["QUANTMESH_DB"])):
        pass
    with database(str(paths["QUANTMESH_CACHE_DB"])):
        pass
    return paths


def main():
    os.umask(0o077)
    os.environ["QUANTMESH_DEPLOYMENT"] = "production"
    try:
        preflight()
        port = int(os.environ.get("PORT", "8501"))
        if not 1 <= port <= 65535:
            raise ValueError
    except (ServiceError, OSError, sqlite3.Error, ValueError) as exc:
        print(str(exc) if isinstance(exc, ServiceError) else
              "Production preflight failed. Check storage, schema and port configuration.", file=sys.stderr)
        raise SystemExit(1) from None
    os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", "app.py",
                             "--server.address=0.0.0.0", f"--server.port={port}",
                             "--server.enableCORS=true", "--server.enableXsrfProtection=true",
                             "--server.maxUploadSize=10", "--server.maxMessageSize=20"])


if __name__ == "__main__":
    main()
