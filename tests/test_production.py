import json
import os
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from streamlit.testing.v1 import AppTest

from quantmesh.account_store import update_account
from quantmesh.auth import load_users, login, password_record, verify_session
from quantmesh.backup import backup, restore
from quantmesh.http import ServiceError
from quantmesh.serve import preflight
from quantmesh.storage import list_runs, save_run


@pytest.fixture
def production(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"alice": password_record("test-long-password-alice")}))
    monkeypatch.setenv("QUANTMESH_DATA_DIR", str(root))
    monkeypatch.setenv("QUANTMESH_DEPLOYMENT", "production")
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "multi-user")
    monkeypatch.setenv("QUANTMESH_SESSION_SECRET", secrets.token_hex(32))
    monkeypatch.setenv("QUANTMESH_USERS_FILE", str(root / "users.json"))
    monkeypatch.setenv("QUANTMESH_BOOTSTRAP_USERS_FILE", str(seed))
    monkeypatch.setenv("QUANTMESH_DB", str(root / "research.sqlite3"))
    monkeypatch.setenv("QUANTMESH_CACHE_DB", str(root / "market.sqlite3"))
    return root, seed


def test_production_bootstrap_does_not_overwrite_durable_accounts(production):
    root, seed = production
    preflight()
    update_account(root / "users.json", "bob", record=password_record("test-long-password-bob"))
    seed.write_text("invalid new seed")
    preflight()
    assert set(load_users(str(root / "users.json"))) == {"alice", "bob"}
    if os.name != "nt":
        assert (root / "users.json").stat().st_mode & 0o077 == 0


def test_production_rejects_single_user_before_dashboard(production, monkeypatch):
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "single-user")
    with pytest.raises(ServiceError, match="multi-user"):
        preflight()
    app = AppTest.from_file("app.py").run()
    assert not app.exception and not app.metric
    assert any("Access denied" in e.value for e in app.error)


@pytest.mark.parametrize("setting", ["QUANTMESH_DB", "QUANTMESH_CACHE_DB", "QUANTMESH_USERS_FILE"])
def test_production_paths_cannot_escape_persistent_directory(production, monkeypatch, setting, tmp_path):
    monkeypatch.setenv(setting, str(tmp_path / "ephemeral"))
    with pytest.raises(ServiceError, match="below QUANTMESH_DATA_DIR"):
        preflight()


def test_missing_production_accounts_do_not_create_anonymous_access(production, monkeypatch):
    monkeypatch.delenv("QUANTMESH_BOOTSTRAP_USERS_FILE")
    with pytest.raises(ServiceError, match="Provision accounts"):
        preflight()


def test_password_hashes_are_salted_and_not_plaintext():
    password = "test-another-long-password"
    first, second = password_record(password), password_record(password)
    assert first["salt"] != second["salt"] and first["hash"] != second["hash"]
    assert password not in json.dumps(first)


def test_account_update_revokes_without_changing_password(production):
    root, _ = production
    preflight()
    file = root / "users.json"
    users = load_users(str(file))
    key = os.environ["QUANTMESH_SESSION_SECRET"].encode()
    token = login("alice", "test-long-password-alice", users, key, str(root / "market.sqlite3"))
    update_account(file, "alice", action="revoke")
    assert verify_session(token, load_users(str(file)), key) is None
    assert load_users(str(file))["alice"]["hash"] == users["alice"]["hash"]


def test_account_removal_revokes_access_and_preserves_journal(production):
    root, _ = production
    preflight()
    file = root / "users.json"
    update_account(file, "bob", record=password_record("test-long-password-bob"))
    users = load_users(str(file))
    key = os.environ["QUANTMESH_SESSION_SECRET"].encode()
    token = login("alice", "test-long-password-alice", users, key, str(root / "market.sqlite3"))
    save_run(str(root / "research.sqlite3"), "private", {}, owner="alice")
    update_account(file, "alice", action="disable")
    assert verify_session(token, load_users(str(file)), key) is None
    assert len(list_runs(str(root / "research.sqlite3"), owner="alice")) == 1
    assert not list_runs(str(root / "research.sqlite3"), owner="bob")


def test_concurrent_provisioning_preserves_all_accounts(production):
    root, _ = production
    preflight()
    def add(index):
        update_account(root / "users.json", f"person{index}", record=password_record("test-long-password"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add, range(4)))
    assert len(load_users(str(root / "users.json"))) == 5


def test_concurrent_journal_writes_and_process_reopen(production):
    root, _ = production
    preflight()
    path = str(root / "research.sqlite3")
    def add(index):
        save_run(path, f"run {index}", {"index": index}, owner="alice" if index % 2 else "bob")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add, range(12)))
    assert len(list_runs(path, owner="alice")) == 6
    assert len(list_runs(path, owner="bob")) == 6
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_newer_schema_fails_without_resetting_version(production):
    root, _ = production
    preflight()
    path = str(root / "research.sqlite3")
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="newer"):
        list_runs(path, owner="alice")
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 999


def test_backup_restore_preserves_private_records_accounts_and_budget(production, tmp_path):
    root, _ = production
    preflight()
    db = str(root / "research.sqlite3")
    save_run(db, "Alice private", {}, owner="alice")
    users = load_users(str(root / "users.json"))
    login("alice", "test-long-password-alice", users, os.environ["QUANTMESH_SESSION_SECRET"].encode(),
          str(root / "market.sqlite3"))
    target = tmp_path / "backup"
    backup(root, target)
    recovered = tmp_path / "recovered"
    restore(target, recovered, app_stopped=True)
    assert load_users(str(recovered / "users.json")) == users
    assert len(list_runs(str(recovered / "research.sqlite3"), owner="alice")) == 1
    assert not list_runs(str(recovered / "research.sqlite3"), owner="bob")
    with sqlite3.connect(recovered / "market.sqlite3") as conn:
        assert conn.execute("SELECT COUNT(*) FROM request_budget").fetchone()[0] == 2
    with pytest.raises(ValueError, match="already contains"):
        restore(target, recovered, app_stopped=True)


def test_restore_checks_integrity_and_requires_stopped_app(production, tmp_path):
    root, _ = production
    preflight()
    target = tmp_path / "backup"
    backup(root, target)
    with pytest.raises(ValueError, match="Stop the app"):
        restore(target, tmp_path / "recovered", app_stopped=False)
    (target / "users.json").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        restore(target, tmp_path / "recovered", app_stopped=True)


def test_new_streamlit_session_requires_login_but_disk_data_survives(production):
    root, _ = production
    preflight()
    save_run(str(root / "research.sqlite3"), "Durable research", {}, owner="alice")
    app = AppTest.from_file("app.py").run()
    assert not app.exception and not app.metric
    app.text_input[0].set_value("alice")
    app.text_input[1].set_value("test-long-password-alice")
    app.button[0].click().run()
    assert not app.exception and len(app.metric) == 4
    assert any("Durable research" in e.label for e in app.expander)
    restarted = AppTest.from_file("app.py").run()
    assert not restarted.exception and not restarted.metric
    assert len(list_runs(str(root / "research.sqlite3"), owner="alice")) == 1


def test_private_exports_do_not_create_unauthenticated_media_routes(monkeypatch):
    import base64
    from contextlib import nullcontext
    from quantmesh.exports import download
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "multi-user")
    rendered = []
    monkeypatch.setattr("quantmesh.exports.components.html", lambda body, **_: rendered.append(body))
    download(nullcontext(), "Download <private>", b"private,test", "report.csv", "text/csv")
    assert len(rendered) == 1 and "/media/" not in rendered[0]
    assert "data:text/csv;base64," in rendered[0]
    assert base64.b64encode(b"private,test").decode() in rendered[0]
    assert "<private>" not in rendered[0]


def test_private_export_cannot_inject_html(monkeypatch):
    from contextlib import nullcontext
    from quantmesh.exports import download
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "multi-user")
    with pytest.raises(ValueError):
        download(nullcontext(), "label", "data", '\" onclick=\"evil', "text/html")


def test_alpha_cache_does_not_persist_extra_provider_metadata(tmp_path):
    from test_services import Session, Response, history
    from quantmesh.market import MarketClient, database
    payload = history("SPY")
    payload["api_key"] = "test-sensitive-echo"
    payload["Meta Data"]["unexpected"] = "test-sensitive-echo"
    path = str(tmp_path / "cache")
    MarketClient(path, "test-only-key", session=Session([Response(payload)])).history("SPY")
    with database(path) as conn:
        cached = conn.execute("SELECT payload FROM market_cache").fetchone()[0]
    assert "test-sensitive-echo" not in cached and "test-only-key" not in cached
    assert "5. adjusted close" in cached


def test_sqlite_files_are_private_on_unix(production):
    root, _ = production
    preflight()
    if os.name != "nt":
        assert (root / "research.sqlite3").stat().st_mode & 0o077 == 0
        assert (root / "market.sqlite3").stat().st_mode & 0o077 == 0
