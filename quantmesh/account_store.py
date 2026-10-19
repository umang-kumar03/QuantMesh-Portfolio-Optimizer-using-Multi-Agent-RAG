"""Cross-process account-file updates; locks cover read/modify/atomic replacement."""
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from quantmesh.auth import load_users


@contextmanager
def account_lock(target: Path):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(str(target) + ".lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            lock.write(b"0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def replace_users(target: Path, users: dict):
    """Caller holds account_lock. Never put plaintext passwords in this mapping."""
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".quantmesh-users-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(users, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        if os.name != "nt":
            descriptor = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_account(target: Path, username: str, *, record=None, action="set"):
    import secrets
    with account_lock(target):
        users = load_users(str(target)) if target.exists() else {}
        if action == "disable":
            if username not in users or len(users) <= 1:
                raise ValueError("Cannot disable a missing or last account. Provision an alternative operator account first.")
            del users[username]
        elif action == "revoke":
            if username not in users:
                raise ValueError("Account does not exist.")
            users[username]["session_version"] = secrets.token_hex(16)
        else:
            users[username] = record
        replace_users(target, users)
