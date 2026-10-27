"""Real PostgreSQL tests require an explicitly disposable *_test database. No provider keys."""
import json
import certifi
import os
import secrets
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from quantmesh import postgres as pg
from quantmesh.account_store import update_account
from quantmesh.auth import load_users, login, password_record, verify_session
from quantmesh.backend import PersistenceError, backend
from quantmesh.cloud import configure
from quantmesh.http import ServiceError
from quantmesh.market import MarketClient, cache_get, cache_put, reserve_request
from quantmesh.pg_admin import export_state, read_export, restore_state
from quantmesh.storage import list_runs, save_run


@pytest.fixture
def pgdb(monkeypatch, tmp_path):
    url = os.environ.get("QUANTMESH_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set QUANTMESH_TEST_DATABASE_URL to a disposable PostgreSQL *_test database")
    settings = psycopg.conninfo.conninfo_to_dict(url)
    if not settings.get("dbname", "").endswith("_test"):
        pytest.fail("Refusing destructive integration fixture: database name must end in _test")
    monkeypatch.setenv("QUANTMESH_BACKEND", "postgres")
    monkeypatch.setenv("QUANTMESH_DATABASE_URL", url)
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "multi-user")
    monkeypatch.setenv("QUANTMESH_DEPLOYMENT", "production")
    monkeypatch.setenv("QUANTMESH_SESSION_SECRET", secrets.token_hex(32))
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "never-research.sqlite3"))
    monkeypatch.setenv("QUANTMESH_CACHE_DB", str(tmp_path / "never-market.sqlite3"))
    monkeypatch.setenv("QUANTMESH_USERS_FILE", str(tmp_path / "never-users.json"))
    with pg.transaction(check_schema=False) as conn:
        conn.execute("DROP SCHEMA IF EXISTS quantmesh CASCADE")
    pg.migrate()
    for user in ("alice", "bob"):
        update_account(Path("unused"), user, record=password_record(f"test-{user}-long-password"))
    return tmp_path


def credentials():
    return os.environ["QUANTMESH_SESSION_SECRET"].encode()


def test_two_users_auth_journal_exports_and_logout(pgdb):
    alice = login("alice", "test-alice-long-password", {}, credentials(), "unused")
    assert verify_session(alice, load_users("unused"), credentials()) == "alice"
    for user in ("alice", "bob"):
        save_run("unused", f"{user} private", {"owner": user}, owner=user)
    assert [r["name"] for r in list_runs("unused", owner="alice")] == ["alice private"]
    assert [r["name"] for r in list_runs("unused", owner="bob")] == ["bob private"]
    assert not list_runs("unused", owner="carol")
    with pytest.raises(ValueError):
        list_runs("unused", owner="alice' OR 1=1")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception and not app.metric
    app.text_input[0].set_value("bob")
    app.text_input[1].set_value("test-bob-long-password")
    app.button[0].click().run()
    assert not app.exception and len(app.metric) == 4
    assert any("bob private" in item.label for item in app.expander)
    assert not any("alice private" in item.label for item in app.expander)
    assert not app.get("download_button")
    frames = app.get("iframe")
    assert len(frames) == 3
    assert all(not item.proto.src and "data:" in item.proto.srcdoc
               and "/media/" not in item.proto.srcdoc for item in frames)
    next(b for b in app.sidebar.button if b.label == "Sign out").click().run()
    assert not app.exception and not app.metric
    assert not any(pgdb.glob("*.sqlite3")) and not (pgdb / "never-users.json").exists()


def test_invalid_login_hash_expiry_and_revocation_on_reconnect(pgdb):
    users = load_users("unused")
    assert "test-alice-long-password" not in json.dumps(users)
    with pytest.raises(ServiceError, match="Invalid username"):
        login("alice", "wrong", users, credentials(), "unused", now=100)
    token = login("alice", "test-alice-long-password", users, credentials(), "unused", now=101)
    assert verify_session(token, users, credentials(), now=3702) is None
    update_account(Path("unused"), "alice", action="revoke")
    assert verify_session(token, load_users("unused"), credentials(), now=102) is None
    # Fresh process, fresh connection: revocation must persist independently of Python objects.
    result = subprocess.run([sys.executable, "-c", '''
import json,os,sys
from quantmesh.auth import load_users, verify_session
assert verify_session(json.loads(sys.stdin.read()), load_users("unused"),
 os.environ["QUANTMESH_SESSION_SECRET"].encode(), now=102) is None
'''], input=json.dumps(token), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    update_account(Path("unused"), "alice", action="disable")
    assert "alice" not in load_users("unused")
    with pytest.raises(ValueError, match="last account"):
        update_account(Path("unused"), "bob", action="disable")


def test_concurrent_accounts_have_no_lost_updates(pgdb):
    def create(i):
        update_account(Path("unused"), f"person{i}", record=password_record("test-only-long-password"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(create, range(8)))
    assert set(load_users("unused")) == {"alice", "bob"} | {f"person{i}" for i in range(8)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: update_account(Path("unused"), "alice", action="revoke"), range(4)))
    assert len(load_users("unused")["alice"]["session_version"]) == 32


def test_concurrent_budgets_and_login_limits_survive_connections(pgdb):
    def reserve(_):
        try:
            reserve_request("unused", "provider-test", 5, 20, now=1000)
            return True
        except ServiceError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(12))) == 5
    with pytest.raises(ServiceError, match="budget reached"):
        reserve_request("unused", "provider-test", 5, 20, now=1001)
    for _ in range(5):
        with pytest.raises(ServiceError, match="Invalid username"):
            login("alice", "wrong", {}, credentials(), "unused", now=1001)
    with pytest.raises(ServiceError, match="budget reached"):
        login("alice", "test-alice-long-password", {}, credentials(), "unused", now=1002)
    reserve_request("unused", "provider-test", 5, 20, now=1061)
    with pg.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quantmesh.request_budget WHERE service='provider-test'").fetchone()[0] == 6


def test_cache_yahoo_alpha_groq_use_postgres(pgdb):
    from test_groq import completion
    from test_services import Session, Response, history
    from test_yahoo import frame, START, END
    from quantmesh.yahoo import YahooClient
    from quantmesh.llm import LLMConfig, explain
    from quantmesh.analytics import research
    from quantmesh.data import sample_prices
    alpha = MarketClient("unused", "test-only-key", session=Session([Response(history("SPY"))]))
    assert alpha.history("SPY")[2] == "provider"
    assert MarketClient("unused").history("SPY")[2] == "cache"
    yahoo = YahooClient("unused", downloader=lambda **_: frame(), clock=lambda: 1000)
    assert yahoo.load(["SPY", "QQQ", "GLD"], START, END, fallback=False).provenance["retrieval_status"] == "provider"
    assert yahoo.load(["SPY", "QQQ", "GLD"], START, END, fallback=False).provenance["retrieval_status"] == "cache"
    assert explain(research(sample_prices()), "risk volatility", LLMConfig("groq", "openai/gpt-oss-20b", "test-key"),
                   "unused", session=Session([completion()]))["status"] == "generated"
    with pg.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quantmesh.request_budget WHERE service='llm'").fetchone()[0] == 1
    for i in range(70):
        cache_put("unused", "market_cache", str(i), float(i), "{}")
    with pg.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quantmesh.market_cache").fetchone()[0] == 64
    assert not (pgdb / "never-market.sqlite3").exists()


def test_migrate_repeatable_newer_schema_refused(pgdb):
    save_run("unused", "preserved", {}, owner="alice")
    pg.migrate()
    assert len(list_runs("unused", owner="alice")) == 1
    with pg.transaction() as conn:
        conn.execute("UPDATE quantmesh.schema_version SET version=999")
    with pytest.raises(PersistenceError, match="incompatible"):
        pg.migrate()
    with pytest.raises(PersistenceError):
        load_users("unused")


def test_snapshot_recovery_preserves_security_state_and_ids(pgdb, tmp_path):
    save_run("unused", "private", {}, owner="alice")
    reserve_request("unused", "llm", 1, 2, now=1000)
    update_account(Path("unused"), "alice", action="revoke")
    before = load_users("unused")
    file = tmp_path / "private-export.json"
    export_state(file)
    assert file.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        export_state(file)
    data = read_export(file)
    with pytest.raises(ValueError, match="Stop all"):
        restore_state(data, app_stopped=False)
    with pytest.raises(ValueError, match="not empty"):
        restore_state(data, app_stopped=True)
    with pg.transaction() as conn:
        for table in pg.TABLES:
            conn.execute(psycopg.sql.SQL("TRUNCATE quantmesh.{}").format(psycopg.sql.Identifier(table)))
    restore_state(data, app_stopped=True)
    assert load_users("unused") == before
    assert len(list_runs("unused", owner="alice")) == 1
    assert not list_runs("unused", owner="bob")
    assert save_run("unused", "second", {}, owner="bob") == 2
    with pytest.raises(ServiceError, match="budget reached"):
        reserve_request("unused", "llm", 1, 2, now=1001)
    file.write_text(file.read_text().replace('"sha256": "', '"sha256": "bad'))
    with pytest.raises(ValueError, match="checksum"):
        read_export(file)


def test_transaction_rollback_and_reconnection(pgdb):
    with pytest.raises(RuntimeError):
        with pg.transaction() as conn:
            conn.execute("DELETE FROM quantmesh.accounts")
            raise RuntimeError("test rollback")
    assert set(load_users("unused")) == {"alice", "bob"}
    with pytest.raises(PersistenceError):
        with pg.transaction() as conn:
            conn.execute("SELECT nonexistent_column FROM quantmesh.accounts")
    assert set(load_users("unused")) == {"alice", "bob"}


def test_runtime_role_can_use_state_but_cannot_migrate(pgdb, monkeypatch):
    with pg.transaction() as conn:
        conn.execute("DO $$ BEGIN CREATE ROLE quantmesh_runtime NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
        conn.execute("GRANT USAGE ON SCHEMA quantmesh TO quantmesh_runtime")
        conn.execute("GRANT SELECT ON quantmesh.schema_version TO quantmesh_runtime")
        conn.execute("GRANT SELECT,INSERT,DELETE ON quantmesh.runs,quantmesh.request_budget,quantmesh.market_cache,quantmesh.yahoo_history TO quantmesh_runtime")
        conn.execute("GRANT UPDATE ON quantmesh.market_cache,quantmesh.yahoo_history TO quantmesh_runtime")
        conn.execute("GRANT SELECT ON quantmesh.accounts TO quantmesh_runtime")
        conn.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA quantmesh TO quantmesh_runtime")
    original = pg.connection_settings
    monkeypatch.setattr(pg, "connection_settings", lambda: dict(original(), options="-c role=quantmesh_runtime"))
    assert set(load_users("unused")) == {"alice", "bob"}
    save_run("unused", "runtime", {}, owner="alice")
    cache_put("unused", "market_cache", "SPY", 1000, "{}")
    reserve_request("unused", "runtime-budget", 1, 2, now=1000)
    with pytest.raises(PersistenceError):
        pg.migrate()
    with pytest.raises(PersistenceError):
        update_account(Path("unused"), "alice", action="revoke")


def test_cloud_preflight_accepts_only_provisioned_postgres(pgdb):
    configure({})  # Existing explicit environment configuration is accepted.
    assert backend() == "postgres"


def test_failure_never_falls_back_or_displays_driver_details(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTMESH_BACKEND", "postgres")
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "multi-user")
    monkeypatch.setenv("QUANTMESH_SESSION_SECRET", "test-not-real-secret" * 3)
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "fallback.sqlite3"))
    def failed(**_):
        raise psycopg.OperationalError("sensitive-password sensitive-hostname sensitive-SQL")
    monkeypatch.setattr(pg, "connection_settings", lambda: {})
    monkeypatch.setattr(psycopg, "connect", failed)
    for operation in (lambda: load_users("ignored"), lambda: save_run("ignored", "x", {}, owner="alice"),
                      lambda: reserve_request("ignored", "llm", 1, 2),
                      lambda: cache_get("ignored", "market_cache", "SPY")):
        with pytest.raises(PersistenceError) as caught:
            operation()
        assert "sensitive" not in str(caught.value)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception and not app.metric and not app.text_input
    assert app.error and "sensitive" not in str(app.error)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mode", ["sqlite", "", "other"])
def test_cloud_refuses_unsafe_backend(monkeypatch, mode):
    monkeypatch.setenv("QUANTMESH_BACKEND", mode)
    with pytest.raises(ServiceError, match="requires postgres"):
        configure({"QUANTMESH_BACKEND": mode})


def test_remote_database_tls_enforced(monkeypatch):
    monkeypatch.setenv("QUANTMESH_DATABASE_URL", "postgresql://user:test-only@db.example.org/db?sslmode=disable")
    settings = pg.connection_settings()
    assert settings["sslmode"] == "verify-full" and settings["sslrootcert"] == certifi.where()
    assert settings["connect_timeout"] == "30"


@pytest.mark.parametrize("value", ["", "invalid database url", "postgresql:///missing-host"])
def test_invalid_connection_configuration_is_sanitized(monkeypatch, value):
    monkeypatch.setenv("QUANTMESH_DATABASE_URL", value)
    with pytest.raises(PersistenceError, match="configuration"):
        pg.connection_settings()


def test_sqlite_backup_import_is_atomic_and_preserves_all_state(pgdb, tmp_path):
    import sqlite3
    from quantmesh.backup import FILES, digest
    from quantmesh.pg_admin import read_sqlite_backup
    source = tmp_path / "legacy-backup"
    source.mkdir()
    before = load_users("unused")
    (source / "users.json").write_text(json.dumps(before))
    with sqlite3.connect(source / "research.sqlite3") as conn:
        conn.execute("CREATE TABLE runs(id INTEGER PRIMARY KEY,created TEXT,name TEXT,payload TEXT,owner TEXT)")
        for i, owner in enumerate(("alice", "bob", "local"), start=10):
            conn.execute("INSERT INTO runs VALUES (?,?,?,?,?)", (i, "2026-10-26", owner, "{}", owner))
        conn.execute("PRAGMA user_version=1")
    with sqlite3.connect(source / "market.sqlite3") as conn:
        conn.execute("CREATE TABLE request_budget(service TEXT,requested REAL)")
        conn.execute("INSERT INTO request_budget VALUES ('llm',1000)")
        conn.execute("CREATE TABLE market_cache(symbol TEXT,fetched REAL,payload TEXT)")
        conn.execute("INSERT INTO market_cache VALUES ('SPY',1000,'{}')")
    (source / "manifest.json").write_text(json.dumps({"version": 1, "sha256": {name: digest(source / name) for name in FILES}}))
    data = read_sqlite_backup(source)
    with pg.transaction() as conn:
        for table in pg.TABLES:
            conn.execute(psycopg.sql.SQL("TRUNCATE quantmesh.{}").format(psycopg.sql.Identifier(table)))
    broken = dict(data, request_budget=[["bad", "not-a-number"]])
    with pytest.raises(PersistenceError):
        restore_state(broken, app_stopped=True)
    with pg.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quantmesh.accounts").fetchone()[0] == 0
    restore_state(data, app_stopped=True)
    assert load_users("unused") == before
    for owner in ("alice", "bob", "local"):
        assert [r["name"] for r in list_runs("unused", owner=owner)] == [owner]
    assert save_run("unused", "next", {}, owner="alice") == 13
    assert cache_get("unused", "market_cache", "SPY") == (1000, "{}")
    with pytest.raises(ServiceError, match="budget reached"):
        reserve_request("unused", "llm", 1, 2, now=1001)
    with pytest.raises(ValueError, match="not empty"):
        restore_state(data, app_stopped=True)


def test_cloud_db_failure_denies_access_and_provider_sample_fallback(monkeypatch):
    from quantmesh.yahoo import YahooClient
    from test_yahoo import START, END
    monkeypatch.setenv("QUANTMESH_BACKEND", "postgres")
    monkeypatch.setattr(pg, "connection_settings", lambda: {})
    def fail(**_):
        raise psycopg.OperationalError("test-sensitive")
    monkeypatch.setattr(psycopg, "connect", fail)
    with pytest.raises(PersistenceError):
        YahooClient("unused").load(["SPY", "QQQ"], START, END, fallback=True)
    with pytest.raises(PersistenceError):
        MarketClient("unused").load(["SPY", "QQQ"], START, END, fallback=True)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "cloud_app.py").run()
    assert not app.exception and not app.metric and app.error


def test_runtime_grants_reject_privileged_roles(pgdb):
    from quantmesh.pg_admin import grant_runtime
    with pytest.raises(ValueError, match="separate"):
        grant_runtime("postgres")
    with pg.transaction() as conn:
        conn.execute("DO $$ BEGIN CREATE ROLE quantmesh_demo NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    grant_runtime("quantmesh_demo")
    with pg.transaction() as conn:
        assert conn.execute("SELECT has_table_privilege('quantmesh_demo','quantmesh.runs','INSERT')").fetchone()[0]
        assert not conn.execute("SELECT has_table_privilege('quantmesh_demo','quantmesh.accounts','UPDATE')").fetchone()[0]


def test_demo_journal_quota_rejects_without_deleting(pgdb, monkeypatch):
    monkeypatch.setattr(pg, "MAX_JOURNAL_BYTES", 5)
    save_run("unused", "keep", {}, owner="alice")
    with pytest.raises(ServiceError, match="storage demo limit"):
        save_run("unused", "too much", {"value": "test"}, owner="alice")
    assert len(list_runs("unused", owner="alice")) == 1


def test_killed_connection_can_reconnect_without_losing_state(pgdb):
    save_run("unused", "before disconnect", {}, owner="alice")
    with pytest.raises(PersistenceError):
        with pg.transaction() as conn:
            conn.execute("SELECT pg_terminate_backend(pg_backend_pid())")
    assert len(list_runs("unused", owner="alice")) == 1
    assert set(load_users("unused")) == {"alice", "bob"}


def test_no_sqlite_helpers_or_single_user_bypass(monkeypatch, tmp_path):
    from quantmesh.market import database
    from quantmesh.storage import connect
    monkeypatch.setenv("QUANTMESH_BACKEND", "postgres")
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "single-user")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception and not app.metric and app.error
    for helper in (database, connect):
        with pytest.raises(PersistenceError):
            with helper(str(tmp_path / "forbidden.sqlite3")):
                pass
    assert not list(tmp_path.iterdir())


def test_unknown_backend_denies_dashboard(monkeypatch):
    monkeypatch.setenv("QUANTMESH_BACKEND", "unsupported")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception and not app.metric and app.error


def test_cloud_entrypoint_with_explicit_environment_reaches_login(pgdb):
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "cloud_app.py").run()
    assert not app.exception and not app.metric
    assert len(app.text_input) == 2 and not app.error
    app.text_input[0].set_value("alice")
    app.text_input[1].set_value("test-alice-long-password")
    app.button[0].click().run()
    assert not app.exception and len(app.metric) == 4
    app.button(key="save-research").click().run()
    assert not app.exception and list_runs("unused", owner="alice")


def test_runtime_creation_is_atomic_restricted_and_quotes_password(pgdb, monkeypatch):
    from quantmesh.pg_admin import create_runtime
    role = "quantmesh_created_runtime_test"
    with pg.transaction() as conn:
        conn.execute(psycopg.sql.SQL("DROP ROLE IF EXISTS {}").format(psycopg.sql.Identifier(role)))
    password = secrets.token_urlsafe(32) + "';DROP SCHEMA quantmesh;--"
    create_runtime(role, password)
    with pg.transaction() as conn:
        stored = conn.execute("SELECT rolpassword FROM pg_authid WHERE rolname=%s", (role,)).fetchone()[0]
        assert stored.startswith("SCRAM-SHA-256$") and password not in stored
    with pytest.raises(ValueError, match="already exists"):
        create_runtime(role, secrets.token_urlsafe(32))
    original = pg.connection_settings()
    monkeypatch.setenv("QUANTMESH_DATABASE_URL", psycopg.conninfo.make_conninfo(
        **dict(original, user=role, password=password)))
    assert set(load_users("unused")) == {"alice", "bob"}
    save_run("unused", "restricted role", {}, owner="alice")
    with pytest.raises(PersistenceError):
        update_account(Path("unused"), "alice", action="revoke")
    with pytest.raises(PersistenceError):
        pg.migrate()


def test_runtime_creation_rejects_unsafe_role_or_weak_password():
    from quantmesh.pg_admin import create_runtime
    for name, password in [("unsafe;DROP", "a" * 40), ("safe_name", "short")]:
        with pytest.raises(ValueError, match="safe database role"):
            create_runtime(name, password)


def test_runtime_cli_refuses_unprotected_password_input(monkeypatch, capsys):
    import getpass
    import warnings
    from quantmesh.pg_admin import main
    monkeypatch.setattr(sys, "argv", ["pg_admin", "create-runtime", "safe_role"])
    def unprotected_input(_):
        warnings.warn("Cannot protect terminal input", getpass.GetPassWarning)
        raise AssertionError("Unprotected password input must not continue")
    monkeypatch.setattr(getpass, "getpass", unprotected_input)
    with pytest.raises(SystemExit, match="No secrets were logged"):
        main()
    assert not capsys.readouterr().out


def test_testuser1_fixture_full_cloud_journal_lifecycle(pgdb):
    """The production username is exercised with a fresh test-only password/database."""
    update_account(Path("unused"), "testuser1", record=password_record("isolated-fixture-password"))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "cloud_app.py", default_timeout=30).run()
    assert not app.exception and not app.metric
    app.text_input[0].set_value("testuser1")
    app.text_input[1].set_value("isolated-fixture-password")
    app.button[0].click().run()
    assert not app.exception and len(app.tabs) == 5 and len(app.metric) == 4
    next(item for item in app.text_input if item.label == "Research name").set_value("Test user private snapshot")
    app.button(key="save-research").click().run()
    assert not app.exception
    assert len(list_runs("unused", owner="testuser1")) == 1
    assert not list_runs("unused", owner="bob")
    fresh = AppTest.from_file(Path(__file__).resolve().parents[1] / "cloud_app.py", default_timeout=30).run()
    assert not fresh.exception and not fresh.metric
    fresh.text_input[0].set_value("testuser1")
    fresh.text_input[1].set_value("isolated-fixture-password")
    fresh.button[0].click().run()
    assert any("Test user private snapshot" in item.label for item in fresh.expander)
    next(button for button in fresh.sidebar.button if button.label == "Sign out").click().run()
    assert not fresh.exception and not fresh.metric


def test_cloud_missing_optional_ai_settings_keep_defaults_and_report_missing_key(pgdb, monkeypatch):
    for key in ("QUANTMESH_LLM_PROVIDER", "QUANTMESH_LLM_MODEL", "QUANTMESH_LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "cloud_app.py", default_timeout=30).run()
    assert not app.exception
    app.text_input[0].set_value("alice")
    app.text_input[1].set_value("test-alice-long-password")
    app.button[0].click().run()
    next(item for item in app.checkbox if item.label.startswith("I agree")).check().run()
    next(item for item in app.button if item.label == "Generate AI explanation").click().run()
    assert not app.exception and len(app.metric) == 4
    assert any("QUANTMESH_LLM_API_KEY is not configured" in item.value for item in app.error)
    assert "QUANTMESH_LLM_PROVIDER" not in os.environ
