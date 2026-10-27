"""TLS diagnostics never need Neon credentials. Real libpq handshakes use a test CA."""
import os
import shutil
import socket
import ssl
import struct
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import certifi
import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from quantmesh import postgres as pg
from quantmesh import postgres_tls as tls
from quantmesh.backend import PersistenceError


@pytest.mark.parametrize("setting", [None, "", "   "])
def test_default_ca_is_valid_certifi_and_tls_cannot_be_weakened(monkeypatch, setting):
    if setting is None:
        monkeypatch.delenv("QUANTMESH_SSLROOTCERT", raising=False)
    else:
        monkeypatch.setenv("QUANTMESH_SSLROOTCERT", setting)
    monkeypatch.setenv("PGSSLMODE", "disable")
    monkeypatch.setenv("PGSSLSNI", "0")
    monkeypatch.setenv("PGGSSENCMODE", "require")
    monkeypatch.setenv("PGSSLROOTCERT", "/unavailable/secret/legacy.pem")
    monkeypatch.setenv("QUANTMESH_DATABASE_URL", "postgresql://test:private@db.example/db?sslmode=disable&sslsni=0&sslrootcert=/bad&gssencmode=require")
    settings = pg.connection_settings()
    assert settings["sslmode"] == "verify-full" and settings["sslsni"] == "1"
    assert settings["gssencmode"] == "disable"
    assert settings["sslrootcert"] == certifi.where()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=settings["sslrootcert"])
    assert context.get_ca_certs()


def test_system_is_explicit_native_libpq_trust_not_silently_certifi(monkeypatch):
    monkeypatch.setenv("QUANTMESH_SSLROOTCERT", "system")
    assert tls.ca_bundle() == "system"


@pytest.mark.parametrize("kind", ["missing", "directory", "relative", "windows", "empty", "invalid"])
def test_invalid_ca_configuration_is_rejected_before_any_connection(monkeypatch, tmp_path, kind):
    path = tmp_path / "private-path.pem"
    if kind == "directory":
        path.mkdir()
    elif kind in {"empty", "invalid"}:
        path.write_text("" if kind == "empty" else "not a certificate PRIVATE-SECRET")
    value = "relative-private.pem" if kind == "relative" else r"C:\private\bundle.pem" if kind == "windows" else str(path)
    monkeypatch.setenv("QUANTMESH_SSLROOTCERT", value)
    monkeypatch.setenv("QUANTMESH_DATABASE_URL", "postgresql://private:PRIVATE-SECRET@db.example/db")
    monkeypatch.setattr(psycopg, "connect", lambda **_: pytest.fail("Invalid CA reached the driver"))
    with pytest.raises(PersistenceError) as caught:
        with pg.transaction():
            pass
    assert caught.value.code in {"TLS_CA_PATH_INVALID", "TLS_CA_BUNDLE_INVALID"}
    assert "PRIVATE-SECRET" not in str(caught.value) and value not in str(caught.value)


@pytest.mark.parametrize("detail,code", [
    ('server certificate for "PRIVATE-HOST" does not match host name "SECRET"', "TLS_HOSTNAME_MISMATCH"),
    ("SSL error: certificate verify failed: unable to get local issuer certificate", "TLS_ISSUER_MISSING"),
    ("SSL error: certificate verify failed: self-signed certificate in certificate chain", "TLS_SELF_SIGNED_CHAIN"),
    ("SSL error: certificate verify failed: certificate has expired", "TLS_CERTIFICATE_EXPIRED"),
    ("certificate is not yet valid", "TLS_CERTIFICATE_NOT_YET_VALID"),
    ("certificate revoked", "TLS_CERTIFICATE_REVOKED"),
    ('root certificate file "/PRIVATE-PATH" does not exist', "TLS_CA_PATH_INVALID"),
    ('could not load private key file "/PRIVATE-KEY"', "TLS_CLIENT_CERTIFICATE"),
    ("SSL connection has been closed unexpectedly", "CONNECTION_CLOSED"),
    ("SSL SYSCALL error: EOF detected", "CONNECTION_CLOSED"),
    ("channel binding required, but SSL not in use", "AUTH_CHANNEL_BINDING"),
    ("server does not support SSL, but SSL was required", "TLS_NOT_SUPPORTED"),
    ("connection timeout expired", "NETWORK_TIMEOUT"),
    ('could not translate host name "PRIVATE-HOST" to address', "HOSTNAME_RESOLUTION"),
    ("password authentication failed for user SECRET", "DATABASE_AUTHENTICATION"),
    ("SSL error: handshake failure", "TLS_PROTOCOL"),
    ("SSL error: certificate verify failed", "TLS_VERIFY_FAILED"),
    ("SECRET ssl-in-a-hostname connection refused", "CONNECTIVITY"),
])
def test_driver_failure_classification_never_displays_raw_details(detail, code):
    assert tls.classify(psycopg.OperationalError(detail)) == code
    error = tls.failure(code)
    assert error.code == code and "SECRET" not in str(error) and "PRIVATE" not in str(error)


@pytest.mark.parametrize("state,code", [("42501", "DATABASE_PERMISSIONS"), ("42P01", "DATABASE_SCHEMA"),
                                        ("28P01", "DATABASE_AUTHENTICATION"), ("3D000", "DATABASE_NAME")])
def test_sqlstate_takes_precedence_over_arbitrary_message_words(state, code):
    class DriverError(psycopg.OperationalError):
        @property
        def sqlstate(self):
            return state
    assert tls.classify(DriverError("certificate verify failed password-secret")) == code


def test_probe_is_rate_limited_and_cannot_receive_credentials(monkeypatch):
    monkeypatch.setattr(tls, "_probe_cache", {})
    seen = []
    monkeypatch.setattr(tls, "probe", lambda settings: seen.append(settings) or "TLS_CHAIN_UNTRUSTED")
    settings = {"host": "test.example", "hostaddr": "127.0.0.1", "port": "5432", "sslrootcert": certifi.where(),
                "user": "private-user", "password": "secret-password", "dbname": "private-db"}
    assert tls.diagnose(settings) == "TLS_CHAIN_UNTRUSTED"
    assert tls.diagnose(dict(settings, password="new-secret")) == "TLS_CHAIN_UNTRUSTED"
    assert len(seen) == 1
    assert set(seen[0]) == {"host", "hostaddr", "port", "sslrootcert", "sslnegotiation"}
    assert "secret-password" not in repr(tls._probe_cache)


def test_probe_success_does_not_bypass_libpq_failure_or_allow_dashboard(monkeypatch):
    monkeypatch.setenv("QUANTMESH_BACKEND", "postgres")
    monkeypatch.setenv("QUANTMESH_DEPLOYMENT", "production")
    monkeypatch.setenv("QUANTMESH_AUTH_MODE", "multi-user")
    monkeypatch.setenv("QUANTMESH_SESSION_SECRET", "test-only-not-a-real-secret" * 2)
    monkeypatch.setenv("QUANTMESH_DATABASE_URL", "postgresql://private-user:private-password@private-host.example/private-db")
    monkeypatch.delenv("QUANTMESH_SSLROOTCERT", raising=False)
    def fail(**_):
        raise psycopg.OperationalError("SSL error: certificate verify failed PRIVATE-CONTENT")
    monkeypatch.setattr(psycopg, "connect", fail)
    monkeypatch.setattr(pg, "diagnose", lambda *_: "TLS_PYTHON_VERIFIED_LIBPQ_FAILED")
    with pytest.raises(PersistenceError, match="TLS_PYTHON_VERIFIED_LIBPQ_FAILED"):
        pg.users()
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "cloud_app.py").run()
    assert not app.exception and not app.metric
    assert any("TLS_PYTHON_VERIFIED_LIBPQ_FAILED" in item.value for item in app.error)
    assert any("libpq" in item.value for item in app.caption)
    rendered = " ".join(item.value for item in list(app.error) + list(app.caption))
    for secret in ("private-user", "private-password", "private-host", "private-db", "PRIVATE-CONTENT"):
        assert secret not in rendered


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("openssl CLI is required for real libpq TLS handshake tests")
    root = tmp_path_factory.mktemp("tls-certificates")
    def run(*args):
        subprocess.run(["openssl", *args], check=True, capture_output=True)
    run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(root / "ca.key"),
        "-out", str(root / "ca.pem"), "-subj", "/CN=QuantMesh test CA", "-days", "2",
        "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(root / "server.key"),
        "-out", str(root / "server.csr"), "-subj", "/CN=neon.test")
    (root / "server.ext").write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:neon.test,DNS:*.neon.test\n")
    run("x509", "-req", "-in", str(root / "server.csr"), "-CA", str(root / "ca.pem"),
        "-CAkey", str(root / "ca.key"), "-set_serial", "2", "-days", "2",
        "-extfile", str(root / "server.ext"), "-out", str(root / "server.pem"))
    os.chmod(root / "ca.key", 0o600)
    os.chmod(root / "server.key", 0o600)
    return root


@contextmanager
def postgres_tls_server(certificates, *, direct=False):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificates / "server.pem"), str(certificates / "server.key"))
    context.set_alpn_protocols(["postgresql"])
    observed = {"sni": [], "startup": 0, "alpn": []}
    context.set_servername_callback(lambda _, name, __: observed["sni"].append(name))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(.1)
    stop = threading.Event()
    def recv_exact(conn, count):
        data = b""
        while len(data) < count:
            part = conn.recv(count-len(data))
            if not part:
                return b""
            data += part
        return data
    def message(tag, data):
        return tag + struct.pack("!I", len(data)+4) + data
    def serve():
        while not stop.is_set():
            try:
                raw, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                with raw:
                    raw.settimeout(2)
                    if not direct:
                        if recv_exact(raw, 8) != struct.pack("!II", 8, 80877103):
                            continue
                        raw.sendall(b"S")
                    with context.wrap_socket(raw, server_side=True) as secure:
                        observed["alpn"].append(secure.selected_alpn_protocol())
                        length = recv_exact(secure, 4)
                        if not length:
                            continue  # Diagnostic probes close before any PostgreSQL startup/auth.
                        recv_exact(secure, struct.unpack("!I", length)[0]-4)
                        observed["startup"] += 1
                        secure.sendall(message(b"R", struct.pack("!I", 0))
                                       + message(b"S", b"server_version\x0017.0\x00")
                                       + message(b"S", b"client_encoding\x00UTF8\x00")
                                       + message(b"S", b"standard_conforming_strings\x00on\x00")
                                       + message(b"Z", b"I"))
                        secure.recv(1024)
            except OSError:
                pass
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], observed
    finally:
        stop.set()
        listener.close()
        thread.join(timeout=3)


def test_real_libpq_accepts_valid_wildcard_chain_and_sends_hostname_sni(certificates, monkeypatch):
    with postgres_tls_server(certificates) as (port, observed):
        monkeypatch.setenv("QUANTMESH_SSLROOTCERT", str(certificates / "ca.pem"))
        monkeypatch.setenv("QUANTMESH_DATABASE_URL", f"postgresql://test@ep-test-pooler.neon.test:{port}/test?hostaddr=127.0.0.1&sslmode=disable&sslsni=0&gssencmode=require")
        with psycopg.connect(**pg.connection_settings()) as conn:
            assert conn.pgconn.ssl_in_use
        assert observed["sni"] == ["ep-test-pooler.neon.test"]
        assert observed["startup"] == 1


def test_real_libpq_hostname_rejected_before_authentication(certificates, monkeypatch):
    with postgres_tls_server(certificates) as (port, observed):
        monkeypatch.setenv("QUANTMESH_SSLROOTCERT", str(certificates / "ca.pem"))
        monkeypatch.setenv("QUANTMESH_DATABASE_URL", f"postgresql://test@wrong.example:{port}/test?hostaddr=127.0.0.1")
        with pytest.raises(psycopg.OperationalError) as caught:
            psycopg.connect(**pg.connection_settings())
        assert tls.classify(caught.value) == "TLS_HOSTNAME_MISMATCH"
        assert observed["startup"] == 0


def test_real_probe_recovers_chain_reason_without_sending_authentication(certificates, monkeypatch):
    with postgres_tls_server(certificates) as (port, observed):
        monkeypatch.delenv("QUANTMESH_SSLROOTCERT", raising=False)
        monkeypatch.setenv("QUANTMESH_DATABASE_URL", f"postgresql://test@neon.test:{port}/test?hostaddr=127.0.0.1")
        settings = pg.connection_settings()
        with pytest.raises(psycopg.OperationalError) as caught:
            psycopg.connect(**settings)
        assert tls.peer_address(caught.value) == "127.0.0.1"
        assert tls.probe(settings) == "TLS_ISSUER_MISSING"
        assert observed["startup"] == 0


def test_real_probe_confirms_hostname_and_valid_chain_without_login(certificates):
    with postgres_tls_server(certificates) as (port, observed):
        settings = {"host": "neon.test", "hostaddr": "127.0.0.1", "port": str(port),
                    "sslrootcert": str(certificates / "ca.pem")}
        assert tls.probe(settings) == "TLS_PYTHON_VERIFIED_LIBPQ_FAILED"
        assert observed["startup"] == 0
        assert tls.probe(dict(settings, host="wrong.example")) == "TLS_HOSTNAME_MISMATCH"


def test_transaction_reports_real_chain_failure_and_never_authenticates(certificates, monkeypatch):
    with postgres_tls_server(certificates) as (port, observed):
        monkeypatch.delenv("QUANTMESH_SSLROOTCERT", raising=False)
        monkeypatch.setenv("QUANTMESH_DATABASE_URL", f"postgresql://test@neon.test:{port}/test?hostaddr=127.0.0.1")
        with pytest.raises(PersistenceError) as caught:
            with pg.transaction():
                pytest.fail("Untrusted TLS reached a database transaction")
        assert caught.value.code == "TLS_ISSUER_MISSING"
        assert observed["startup"] == 0


def test_diagnostic_does_not_resolve_or_guess_an_alternate_endpoint(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_kw: pytest.fail("Unexpected network access"))
    settings = {"host": "private.example", "sslrootcert": certifi.where()}
    assert tls.probe(settings) == "TLS_VERIFY_FAILED"
    assert tls.diagnose(settings, psycopg.OperationalError("certificate verify failed")) == "TLS_VERIFY_FAILED"


def test_multiple_attempt_network_error_cannot_hide_observed_tls_verification():
    error = psycopg.OperationalError("connection timed out\nMultiple connection attempts failed.\nSSL error: certificate verify failed")
    assert tls.classify(error) == "TLS_VERIFY_FAILED"


def test_raw_driver_debug_logs_are_private_without_muting_other_threads(monkeypatch, caplog):
    import logging
    logger = logging.getLogger("psycopg")
    caplog.set_level(logging.DEBUG, logger="psycopg")
    monkeypatch.setattr(pg, "connection_settings", lambda: {})
    def failed(**_):
        logger.debug("postgresql://private-user:PRIVATE-PASSWORD@private-host/db")
        thread = threading.Thread(target=lambda: logger.warning("unrelated worker event"))
        thread.start()
        thread.join()
        raise psycopg.OperationalError("PRIVATE-PASSWORD connection refused")
    monkeypatch.setattr(psycopg, "connect", failed)
    with pytest.raises(PersistenceError):
        with pg.transaction():
            pass
    logger.warning("logging restored after transaction")
    assert "unrelated worker event" in caplog.text
    assert "logging restored" in caplog.text
    assert "PRIVATE-PASSWORD" not in caplog.text and "postgresql://" not in caplog.text


def test_real_direct_tls_preserves_libpq_alpn_and_credential_free_probe(certificates, monkeypatch):
    with postgres_tls_server(certificates, direct=True) as (port, observed):
        monkeypatch.setenv("QUANTMESH_SSLROOTCERT", str(certificates / "ca.pem"))
        monkeypatch.setenv("QUANTMESH_DATABASE_URL", f"postgresql://test@neon.test:{port}/test?hostaddr=127.0.0.1&sslnegotiation=direct")
        settings = pg.connection_settings()
        with psycopg.connect(**settings) as conn:
            assert conn.pgconn.ssl_in_use
        assert tls.probe(settings) == "TLS_PYTHON_VERIFIED_LIBPQ_FAILED"
    assert observed["startup"] == 1
    assert observed["alpn"] == ["postgresql", "postgresql"]


def test_loopback_label_cannot_disable_tls_for_remote_hostaddr(monkeypatch):
    monkeypatch.delenv("QUANTMESH_SSLROOTCERT", raising=False)
    monkeypatch.setenv("QUANTMESH_DATABASE_URL", "postgresql://test@localhost/test?hostaddr=203.0.113.1&sslmode=disable")
    settings = pg.connection_settings()
    assert settings["sslmode"] == "verify-full" and settings["sslsni"] == "1"
    assert settings["sslrootcert"] == certifi.where()
