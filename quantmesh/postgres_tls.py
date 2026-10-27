"""Verified PostgreSQL TLS configuration and credential-free failure diagnostics."""
import os
import ipaddress
import logging
from contextlib import contextmanager
import socket
import ssl
import struct
import threading
import time
from pathlib import Path

import certifi
import psycopg

from quantmesh.backend import PersistenceError

# Only these fixed messages may cross the driver boundary. Never format exception text.
MESSAGES = {
    "TLS_CA_PATH_INVALID": "The CA bundle is not a readable absolute file in this runtime.",
    "TLS_CA_BUNDLE_INVALID": "The configured CA bundle contains no usable PEM CA certificates.",
    "TLS_HOSTNAME_MISMATCH": "The server certificate does not match the configured connection hostname.",
    "TLS_CERTIFICATE_EXPIRED": "A server-chain certificate has expired.",
    "TLS_CERTIFICATE_NOT_YET_VALID": "A server-chain certificate is not yet valid.",
    "TLS_ISSUER_MISSING": "The TLS issuer certificate could not be found in the presented chain or selected trust store.",
    "TLS_SELF_SIGNED_CERTIFICATE": "The server presented an untrusted self-signed certificate.",
    "TLS_SELF_SIGNED_CHAIN": "The server chain contains an untrusted self-signed certificate.",
    "TLS_CHAIN_INCOMPLETE": "The TLS issuer chain could not be completed.",
    "TLS_CA_CONSTRAINTS": "The server chain failed CA certificate constraints validation.",
    "TLS_CHAIN_UNTRUSTED": "The server certificate chain cannot be verified by the selected CA bundle.",
    "TLS_CERTIFICATE_REVOKED": "A server-chain certificate has been revoked.",
    "TLS_VERIFY_FAILED": "Certificate verification failed without a more specific verified reason.",
    "TLS_PYTHON_VERIFIED_LIBPQ_FAILED": "A separate Python TLS check passed; the libpq connection still failed. Verification was not bypassed.",
    "TLS_CLIENT_CERTIFICATE": "libpq could not load its configured client certificate or private key.",
    "TLS_PROTOCOL": "The server TLS negotiation failed.",
    "TLS_NOT_SUPPORTED": "The configured server did not accept PostgreSQL TLS negotiation.",
    "AUTH_CHANNEL_BINDING": "The server did not complete the required channel-binding authentication.",
    "DATABASE_AUTHENTICATION": "Database authentication failed.",
    "DATABASE_PERMISSIONS": "The configured role lacks required database permissions.",
    "DATABASE_SCHEMA": "The required database schema is unavailable.",
    "DATABASE_NAME": "The configured database is unavailable.",
    "NETWORK_TIMEOUT": "The database connection timed out.",
    "HOSTNAME_RESOLUTION": "The database hostname could not be resolved.",
    "CONNECTION_CLOSED": "The server closed the connection; this is not evidence of a certificate error.",
    "CONNECTIVITY": "The database connection could not be established.",
    "DATABASE_OPERATION": "The database operation failed.",
}


def failure(code):
    return PersistenceError(f"PostgreSQL check failed [{code}]. {MESSAGES[code]} Contact the operator.", code=code)


def ca_bundle():
    """Blank uses the pinned portable bundle; explicit 'system' means libpq system roots."""
    selected = os.environ.get("QUANTMESH_SSLROOTCERT", "").strip()
    if selected == "system":
        return "system"
    path = Path(selected or certifi.where())
    try:
        if not path.is_absolute() or not path.is_file():
            raise failure("TLS_CA_PATH_INVALID")
        if path.stat().st_size > 8 * 1024 * 1024:
            raise failure("TLS_CA_BUNDLE_INVALID")
        # Opening catches permissions; do not echo a private path or OS exception.
        with path.open("rb") as file:
            if not file.read(1):
                raise failure("TLS_CA_BUNDLE_INVALID")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=str(path))
        if not context.get_ca_certs():
            raise failure("TLS_CA_BUNDLE_INVALID")
    except (OSError, ValueError) as exc:
        if isinstance(exc, PersistenceError):
            raise
        if isinstance(exc, ssl.SSLError):
            raise failure("TLS_CA_BUNDLE_INVALID") from None
        raise failure("TLS_CA_PATH_INVALID") from None
    return str(path)


def classify(exc):
    state = exc.sqlstate
    if state in {"28P01", "28000"}:
        return "DATABASE_AUTHENTICATION"
    if state == "42501":
        return "DATABASE_PERMISSIONS"
    if state in {"42P01", "3F000"}:
        return "DATABASE_SCHEMA"
    if state == "3D000":
        return "DATABASE_NAME"
    if not isinstance(exc, psycopg.OperationalError):
        return "DATABASE_OPERATION"
    detail = str(exc).lower()  # Inspected only; never returned or logged.
    if "channel binding" in detail:
        return "AUTH_CHANNEL_BINDING"
    if any(s in detail for s in ("password authentication failed", "authentication failed")):
        return "DATABASE_AUTHENTICATION"
    if any(s in detail for s in ("does not match host name", "hostname mismatch", "ip address mismatch")):
        return "TLS_HOSTNAME_MISMATCH"
    if "certificate has expired" in detail:
        return "TLS_CERTIFICATE_EXPIRED"
    if "certificate is not yet valid" in detail:
        return "TLS_CERTIFICATE_NOT_YET_VALID"
    if "certificate revoked" in detail:
        return "TLS_CERTIFICATE_REVOKED"
    if "could not load system root" in detail:
        return "TLS_CA_BUNDLE_INVALID"
    if "root certificate file" in detail and any(s in detail for s in ("does not exist", "could not read", "permission denied")):
        return "TLS_CA_PATH_INVALID"
    if any(s in detail for s in ("could not load private key", "could not load ssl certificate", "private key file")):
        return "TLS_CLIENT_CERTIFICATE"
    if "unable to get local issuer" in detail:
        return "TLS_ISSUER_MISSING"
    if "self-signed certificate in certificate chain" in detail:
        return "TLS_SELF_SIGNED_CHAIN"
    if "self-signed certificate" in detail:
        return "TLS_SELF_SIGNED_CERTIFICATE"
    if "unable to verify the first certificate" in detail:
        return "TLS_CHAIN_INCOMPLETE"
    if "unknown ca" in detail:
        return "TLS_CHAIN_UNTRUSTED"
    if "certificate verify failed" in detail or "certificate verification failed" in detail:
        return "TLS_VERIFY_FAILED"
    if "server does not support ssl" in detail:
        return "TLS_NOT_SUPPORTED"
    if any(s in detail for s in ("could not translate host", "name or service not known", "nodename nor servname")):
        return "HOSTNAME_RESOLUTION"
    if any(s in detail for s in ("timed out", "timeout expired", "connection timeout")):
        return "NETWORK_TIMEOUT"
    if any(s in detail for s in ("closed unexpectedly", "connection reset by peer", "eof detected")):
        return "CONNECTION_CLOSED"
    if any(s in detail for s in ("ssl error:", "tls alert", "ssl handshake")):
        return "TLS_PROTOCOL"
    return "CONNECTIVITY"


VERIFY_CODES = {
    9: "TLS_CERTIFICATE_NOT_YET_VALID", 10: "TLS_CERTIFICATE_EXPIRED",
    18: "TLS_SELF_SIGNED_CERTIFICATE", 19: "TLS_SELF_SIGNED_CHAIN", 20: "TLS_ISSUER_MISSING",
    21: "TLS_CHAIN_INCOMPLETE", 23: "TLS_CERTIFICATE_REVOKED", 24: "TLS_CA_CONSTRAINTS",
    62: "TLS_HOSTNAME_MISMATCH", 64: "TLS_HOSTNAME_MISMATCH",
}


def probe(settings):
    """One verified SSLRequest handshake to the SAME endpoint; never send StartupMessage/auth.

    This obtains OpenSSL's structured verify_code when libpq says only 'verify failed'.
    No credentials are passed into this function and no alternate endpoint is tried.
    """
    try:
        context = (ssl.create_default_context() if settings["sslrootcert"] == "system"
                   else ssl.create_default_context(cafile=settings["sslrootcert"]))
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        if settings.get("sslnegotiation") == "direct":
            context.set_alpn_protocols(["postgresql"])
        # Probe the numeric peer actually attempted by libpq, never a fresh DNS
        # lookup (which could select a different server or exceed the deadline).
        address = str(ipaddress.ip_address(settings.get("hostaddr", "")))
        with socket.create_connection((address, int(settings.get("port", 5432))), timeout=3) as raw:
            raw.settimeout(3)
            if settings.get("sslnegotiation", "postgres") != "direct":
                raw.sendall(struct.pack("!II", 8, 80877103))
                if raw.recv(1) != b"S":
                    return "TLS_NOT_SUPPORTED"
            with context.wrap_socket(raw, server_hostname=settings["host"]):
                return "TLS_PYTHON_VERIFIED_LIBPQ_FAILED"
    except ssl.SSLCertVerificationError as exc:
        return VERIFY_CODES.get(exc.verify_code, "TLS_VERIFY_FAILED")
    except (OSError, ValueError):
        # Do not overwrite an observed libpq TLS error with a failed diagnostic probe.
        return "TLS_VERIFY_FAILED"


_probe_lock = threading.Lock()
_probe_cache = {}


def peer_address(exc):
    """Use libpq's numeric peer without parsing or retaining raw driver messages."""
    try:
        return str(ipaddress.ip_address(exc.pgconn.hostaddr.decode("ascii")))
    except (AttributeError, ValueError, UnicodeError, psycopg.Error):
        return ""


def diagnose(settings, exc=None):
    """At most one no-auth probe/minute/config/process; bounded cache and no secrets in keys."""
    safe = {key: settings[key] for key in ("host", "hostaddr", "port", "sslrootcert", "sslnegotiation") if key in settings}
    address = peer_address(exc) if exc is not None else ""
    try:
        safe["hostaddr"] = str(ipaddress.ip_address(address or safe.get("hostaddr", "")))
    except ValueError:
        return "TLS_VERIFY_FAILED"
    try:
        port = int(exc.pgconn.port) if exc is not None else int(safe.get("port", 5432))
        if not 1 <= port <= 65535:
            return "TLS_VERIFY_FAILED"
        safe["port"] = str(port)
    except (AttributeError, ValueError, TypeError, psycopg.Error):
        return "TLS_VERIFY_FAILED"
    safe.setdefault("sslnegotiation", os.environ.get("PGSSLNEGOTIATION", "postgres"))
    key = tuple(sorted(safe.items()))
    with _probe_lock:
        now = time.monotonic()
        previous = _probe_cache.get(key)
        if previous and now - previous[0] < 60:
            return previous[1]
        result = probe(safe)
        if len(_probe_cache) >= 8:
            _probe_cache.clear()
        _probe_cache[key] = (now, result)
        return result


def runtime_summary():
    """Public package versions and CA-source enum only; no paths/DSNs/environment dump."""
    import sys
    from importlib.metadata import version
    selected = os.environ.get("QUANTMESH_SSLROOTCERT", "").strip()
    source = "system" if selected == "system" else "custom PEM" if selected else "bundled Certifi"
    try:
        host = psycopg.conninfo.conninfo_to_dict(os.environ.get("QUANTMESH_DATABASE_URL", "")).get("host", "")
        endpoint = ("Neon pooled" if host.split(".", 1)[0].endswith("-pooler") else "Neon direct") if host.endswith(".neon.tech") else "custom PostgreSQL"
    except (ValueError, psycopg.Error):
        endpoint = "unavailable"
    return (f"Python {sys.version_info.major}.{sys.version_info.minor}; "
            f"psycopg {psycopg.__version__} ({psycopg.pq.__impl__}); "
            f"libpq {psycopg.pq.version()}; certifi {version('certifi')}; CA source: {source}; endpoint kind: {endpoint}.")


@contextmanager
def private_driver_logs():
    """Suppress this thread's libpq raw errors even when an operator enables DEBUG."""
    thread = threading.get_ident()
    logger = logging.getLogger("psycopg")
    class Guard(logging.Filter):
        def filter(self, record):
            return record.thread != thread
    guard = Guard()
    logger.addFilter(guard)
    try:
        yield
    finally:
        logger.removeFilter(guard)
