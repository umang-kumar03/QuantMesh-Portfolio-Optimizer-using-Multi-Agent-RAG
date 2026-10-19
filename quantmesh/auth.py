"""Provisioned accounts with scrypt passwords and expiring, revocable signed sessions."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from quantmesh.http import ServiceError
from quantmesh.market import reserve_request

USERNAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


def password_record(password: str) -> dict:
    if not 12 <= len(password) <= 1024:
        raise ValueError("Passwords must contain 12–1,024 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return {"salt": salt.hex(), "hash": digest.hex()}


def load_users(path: str) -> dict:
    try:
        with Path(path).open("rb") as account_file:
            raw = account_file.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError
        users = json.loads(raw)
        if not isinstance(users, dict) or not 1 <= len(users) <= 1000:
            raise ValueError
        for name, record in users.items():
            if not USERNAME.fullmatch(name) or name == "local":
                raise ValueError
            if not isinstance(record, dict) or set(record) - {"salt", "hash", "session_version"}:
                raise ValueError
            if "session_version" in record and not re.fullmatch(r"[a-f0-9]{32}", record["session_version"]):
                raise ValueError
            if len(bytes.fromhex(record["salt"])) != 16 or len(bytes.fromhex(record["hash"])) != 64:
                raise ValueError
        return users
    except (OSError, ValueError, TypeError, KeyError):
        raise ServiceError("Authentication configuration is unavailable or invalid. "
                           "Provision users using python -m quantmesh.manage_users.") from None


def session_key() -> bytes:
    value = os.environ.get("QUANTMESH_SESSION_SECRET", "")
    if len(value) < 32:
        raise ServiceError("Multi-user mode requires QUANTMESH_SESSION_SECRET with at least 32 characters.")
    return value.encode()


def login(username: str, password: str, users: dict, key: bytes, budget_path: str,
          now: float | None = None) -> str:
    now = time.time() if now is None else now
    if len(username) > 64 or len(password) > 1024:
        raise ServiceError("Invalid username or password.")
    # Fail closed if the shared limiter cannot be read or updated.
    try:
        reserve_request(budget_path, "login-global", 30, 1000, now)
        reserve_request(budget_path, "login:" + hashlib.sha256(username.encode()).hexdigest(),
                        5, 100, now)
    except (OSError, sqlite3.Error):
        raise ServiceError("Authentication is temporarily unavailable.") from None
    # Equivalent hashing work for an unknown user avoids an obvious account-existence timing leak.
    record = users.get(username, {"salt": "00" * 16, "hash": "00" * 64})
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record["salt"]),
                            n=16384, r=8, p=1).hex()
    if not hmac.compare_digest(digest, record["hash"]) or username not in users:
        raise ServiceError("Invalid username or password.")
    payload = json.dumps({"user": username, "expires": now + 3600,
                          "revision": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()},
                         sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(payload).decode()
    signature = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def verify_session(token: str, users: dict, key: bytes, now: float | None = None) -> str | None:
    now = time.time() if now is None else now
    try:
        if len(token) > 2048:
            return None
        encoded, signature = token.split(".")
        if not hmac.compare_digest(signature, hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()):
            return None
        data = json.loads(base64.urlsafe_b64decode(encoded))
        user = data["user"]
        revision = hashlib.sha256(json.dumps(users[user], sort_keys=True).encode()).hexdigest()
        if data["expires"] <= now or not hmac.compare_digest(revision, data["revision"]):
            return None
        return user
    except (ValueError, TypeError, KeyError):
        return None


def require_user(st) -> str:
    """Run before any upload, provider, report or storage UI is created."""
    mode = os.environ.get("QUANTMESH_AUTH_MODE", "single-user")
    deployment = os.environ.get("QUANTMESH_DEPLOYMENT", "local")
    if deployment not in {"local", "production"} or (deployment == "production" and mode != "multi-user"):
        st.error("Production deployment requires multi-user authentication. Access denied.")
        st.stop()
    if mode == "single-user":
        st.sidebar.caption("Private single-user mode · Do not expose this mode publicly.")
        return "local"
    if mode != "multi-user":
        st.error("QUANTMESH_AUTH_MODE must be single-user or multi-user.")
        st.stop()
    try:
        key = session_key()
        users = load_users(os.environ.get("QUANTMESH_USERS_FILE", ""))
        owner = verify_session(st.session_state.get("auth_token", ""), users, key)
        if owner:
            st.sidebar.caption(f"Signed in as {owner}")
            if st.sidebar.button("Sign out"):
                st.session_state.clear()
                st.rerun()
            return owner
        if "auth_token" in st.session_state:
            st.session_state.clear()
        st.subheader("Sign in to your private research workspace")
        with st.form("login"):
            username = st.text_input("Username", max_chars=64)
            password = st.text_input("Password", type="password", max_chars=1024)
            submitted = st.form_submit_button("Sign in")
        if submitted:
            path = os.environ.get("QUANTMESH_CACHE_DB", ".quantmesh/market.sqlite3")
            st.session_state["auth_token"] = login(username, password, users, key, path)
            st.rerun()
    except ServiceError as exc:
        st.error(str(exc))
    st.stop()
