import json
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from quantmesh.auth import load_users, login, password_record, verify_session
from quantmesh.http import ServiceError
from quantmesh.storage import list_runs, save_run


@pytest.fixture
def users():
    return {"alice": password_record("correct-horse-battery"),
            "bob": password_record("another-long-password")}


def test_sessions_tampering_expiry_password_revocation(tmp_path, users):
    key = b"a" * 32
    token = login("alice", "correct-horse-battery", users, key, str(tmp_path / "auth.db"), now=100)
    assert verify_session(token, users, key, now=101) == "alice"
    assert verify_session(token + "x", users, key, now=101) is None
    assert verify_session(token, users, key, now=3701) is None
    assert verify_session(token, users, b"b" * 32, now=101) is None
    users["alice"] = password_record("replacement-password")
    assert verify_session(token, users, key, now=101) is None


def test_failed_login_generic_errors_and_persistent_throttle(tmp_path, users):
    path = str(tmp_path / "auth.db")
    for _ in range(5):
        with pytest.raises(ServiceError, match="Invalid username or password"):
            login("alice", "wrong", users, b"a" * 32, path, now=100)
    with pytest.raises(ServiceError, match="budget"):
        login("alice", "correct-horse-battery", users, b"a" * 32, path, now=101)


def test_owner_scoping_and_legacy_migration(tmp_path):
    path = str(tmp_path / "research.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY,created TEXT,name TEXT,payload TEXT)")
        conn.execute("INSERT INTO runs VALUES (1,'old','legacy','{}')")
    save_run(path, "Alice private", {}, owner="alice")
    save_run(path, "Bob private", {}, owner="bob")
    assert [r["name"] for r in list_runs(path, owner="alice")] == ["Alice private"]
    assert [r["name"] for r in list_runs(path, owner="bob")] == ["Bob private"]
    assert [r["name"] for r in list_runs(path)] == ["legacy"]
    with pytest.raises(ValueError):
        list_runs(path, owner="alice' OR 1=1")


def test_bad_auth_configuration_fails_closed(tmp_path):
    path = tmp_path / "users.json"
    path.write_text('{"local": {"salt":"00", "hash":"00"}}')
    with pytest.raises(ServiceError):
        load_users(str(path))


def test_multi_user_login_logout_and_record_isolation(tmp_path, monkeypatch, users):
    path = tmp_path / "users.json"
    path.write_text(json.dumps(users))
    db = str(tmp_path / "research.db")
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "multi-user")
    monkeypatch.setenv("QUANTMESH_USERS_FILE", str(path))
    monkeypatch.setenv("QUANTMESH_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("QUANTMESH_DB", db)
    monkeypatch.setenv("QUANTMESH_CACHE_DB", str(tmp_path / "cache.db"))
    save_run(db, "Bob confidential", {}, owner="bob")
    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception
    assert not app.metric
    app.text_input[0].set_value("alice")
    app.text_input[1].set_value("correct-horse-battery")
    app.button[0].click().run()
    assert not app.exception
    assert len(app.metric) == 4
    assert not any("Bob confidential" in e.label for e in app.expander)
    app.button(key="save-research").click().run()
    assert len(list_runs(db, owner="alice")) == 1
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert not app.metric


def test_missing_multi_user_secret_blocks_dashboard(monkeypatch):
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "multi-user")
    monkeypatch.delenv("QUANTMESH_SESSION_SECRET", raising=False)
    app = AppTest.from_file("app.py").run()
    assert not app.exception
    assert not app.metric
    assert any("SESSION_SECRET" in e.value for e in app.error)
