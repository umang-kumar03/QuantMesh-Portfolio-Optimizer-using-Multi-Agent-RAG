"""Explicit persistence selection. Never infer or fall back from connection failures."""
import os

from quantmesh.http import ServiceError


CACHE_TABLES = {"market_cache": "symbol", "yahoo_history": "cache_key"}


class PersistenceError(ServiceError):
    """Sanitized storage outage/configuration failure; must not trigger sample fallback."""


def backend():
    selected = os.environ.get("QUANTMESH_BACKEND", "sqlite")
    if selected not in {"sqlite", "postgres"}:
        raise PersistenceError("QUANTMESH_BACKEND must be sqlite or postgres. Access denied.")
    return selected
