"""SQLite policy for a single instance backed by a local persistent disk."""
import sqlite3
import os
from pathlib import Path


def open_database(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if not Path(path).exists():
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
    if os.name != "nt":
        os.chmod(path, 0o600)
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn
    except Exception:
        conn.close()
        raise
