"""Alpha Vantage adjusted daily history with durable cache and atomic request budgets."""
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from quantmesh.sqlite_utils import open_database
from quantmesh.backend import backend, PersistenceError, CACHE_TABLES

import numpy as np
import pandas as pd

from quantmesh.data import sample_prices, validate_prices
from quantmesh.http import ServiceError, request_json

URL = "https://www.alphavantage.co/query"
DOCUMENTATION = "https://www.alphavantage.co/documentation/#dailyadj"


@contextmanager
def database(path):
    if backend() != "sqlite":
        raise PersistenceError("SQLite access is disabled for the selected backend.")
    conn = open_database(path)
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS market_cache "
                         "(symbol TEXT PRIMARY KEY, fetched REAL NOT NULL, payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS request_budget "
                         "(service TEXT NOT NULL, requested REAL NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS yahoo_history "
                         "(cache_key TEXT PRIMARY KEY, fetched REAL NOT NULL, payload TEXT NOT NULL)")
            yield conn
    finally:
        conn.close()


def reserve_request(path: str, service: str, per_minute: int, per_day: int,
                    now: float | None = None):
    now = time.time() if now is None else now
    if backend() == "postgres":
        from quantmesh.postgres import reserve
        return reserve(service, per_minute, per_day, now)
    with database(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM request_budget WHERE requested < ?", (now - 86400,))
        minute, day = conn.execute(
            "SELECT COALESCE(SUM(requested > ?),0),COUNT(*) FROM request_budget WHERE service=?",
            (now - 60, service)).fetchone()
        if minute >= per_minute or day >= per_day:
            raise ServiceError("Local request budget reached. Wait before retrying or use cached/sample data.")
        conn.execute("INSERT INTO request_budget VALUES (?,?)", (service, now))


def parse_history(payload: dict, symbol: str) -> pd.Series:
    if not isinstance(payload, dict):
        raise ServiceError("Provider returned an unexpected history format.")
    # Alpha Vantage returns a structured notice rather than price rows when an
    # API key lacks premium access. Never render the raw provider body or token.
    notice = " ".join(str(payload.get(key, ""))[:2000].lower()
                      for key in ("Information", "Note", "Error Message"))
    if "premium" in notice or "subscribe" in notice or "subscription" in notice:
        raise ServiceError("Alpha Vantage daily adjusted prices require premium API access. "
                           "For a free real-data alternative, select Yahoo Finance.")
    if "rate limit" in notice or "api call frequency" in notice or "calls per minute" in notice:
        raise ServiceError("Alpha Vantage request limit reached. Retry later or select Yahoo Finance.")
    rows = payload.get("Time Series (Daily)")
    if not isinstance(rows, dict) or not rows:
        raise ServiceError("No Alpha Vantage adjusted history returned. Check symbol, API access "
                           "and plan entitlement; Yahoo Finance is a free-data alternative.")
    metadata = payload.get("Meta Data", {})
    if (not isinstance(metadata, dict) or not isinstance(metadata.get("2. Symbol"), str)
            or metadata["2. Symbol"].upper() != symbol):
        raise ServiceError("Provider symbol metadata did not match the requested asset.")
    try:
        if not 61 <= len(rows) <= 10000:
            raise ValueError
        series = pd.Series({day: float(row["5. adjusted close"]) for day, row in rows.items()},
                           name=symbol)
        series.index = pd.to_datetime(series.index, format="%Y-%m-%d", errors="raise")
        series = series.sort_index()
        values = series.to_numpy()
        if not np.isfinite(values).all() or (values <= 0).any() or series.index.duplicated().any():
            raise ValueError
        return series
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ServiceError("Provider returned invalid adjusted-price observations.") from None


@dataclass
class MarketResult:
    prices: pd.DataFrame
    provenance: dict
    warning: str = ""


class MarketClient:
    def __init__(self, cache_path: str, api_key: str = "", *, session=None,
                 clock=time.time, ttl: int = 21600, stale_limit: int = 604800):
        self.path, self.key, self.session = cache_path, api_key, session
        self.clock, self.ttl, self.stale_limit = clock, ttl, stale_limit

    def history(self, symbol: str) -> tuple[pd.Series, float, str]:
        now = self.clock()
        cached = cache_get(self.path, "market_cache", symbol)
        previous = None
        if cached:
            try:
                previous = parse_history(json.loads(cached[1]), symbol)
            except (ServiceError, ValueError, TypeError):
                cached = None
        if cached and 0 <= now - cached[0] < self.ttl:
            return previous, cached[0], "cache"
        try:
            if not self.key:
                raise ServiceError("ALPHAVANTAGE_API_KEY is not configured.")
            reserve_request(self.path, "alphavantage", 5, 25, now)
            payload = request_json("GET", URL, session=self.session, params={
                "function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": symbol,
                "outputsize": "full", "apikey": self.key})
            series = parse_history(payload, symbol)
            # Persist only validated prices and required identity, never arbitrary response metadata.
            safe_payload = {"Meta Data": {"2. Symbol": symbol}, "Time Series (Daily)": {
                str(day.date()): {"5. adjusted close": float(value)} for day, value in series.items()}}
            cache_put(self.path, "market_cache", symbol, now, json.dumps(safe_payload, allow_nan=False))
            return series, now, "provider"
        except PersistenceError:
            raise
        except ServiceError:
            if cached and 0 <= now - cached[0] <= self.stale_limit:
                return previous, cached[0], "stale cache"
            raise

    def load(self, symbols: list[str], start: date, end: date, *, fallback=True) -> MarketResult:
        symbols = [s.strip().upper() for s in symbols]
        if not 2 <= len(symbols) <= 5 or len(set(symbols)) != len(symbols):
            raise ValueError("Choose 2–5 unique symbols.")
        if any(not re.fullmatch(r"[A-Z0-9][A-Z0-9.:-]{0,19}", s) for s in symbols):
            raise ValueError("Symbols may contain letters, numbers, periods, colons and hyphens.")
        if start >= end or end > date.today():
            raise ValueError("Choose a historical start date before the end date, no later than today.")
        try:
            histories, details = [], {}
            for symbol in symbols:
                series, fetched, status = self.history(symbol)
                histories.append(series)
                details[symbol] = {"fetched_at_unix": fetched, "status": status,
                                   "latest_observation": series.index[-1].date().isoformat()}
            aligned = pd.concat(histories, axis=1, join="inner").loc[str(start):str(end)]
            aligned.index.name = "Date"
            try:
                prices = validate_prices(aligned)
            except ValueError:
                raise ServiceError("Aligned provider history failed daily-price validation. "
                                   "Choose a longer overlapping date range.") from None
            warning = "Stale cached history used; check timestamps." if any(
                d["status"] == "stale cache" for d in details.values()) else ""
            return MarketResult(prices, {"provider": "Alpha Vantage", "synthetic": False,
                                "endpoint": "TIME_SERIES_DAILY_ADJUSTED",
                                "documentation": DOCUMENTATION, "symbols": details,
                                "alignment": "intersection of dates; no imputation",
                                "requested_start": str(start), "requested_end": str(end)}, warning)
        except PersistenceError:
            raise
        except (ServiceError, sqlite3.Error, OSError) as exc:
            if not fallback:
                raise ServiceError(str(exc) if isinstance(exc, ServiceError)
                                   else "Market cache unavailable. Check storage permissions.") from None
            reason = str(exc) if isinstance(exc, ServiceError) else "Market cache unavailable."
            return MarketResult(sample_prices(), {"provider": "synthetic", "synthetic": True,
                                "requested_symbols": symbols},
                                reason + " SYNTHETIC SAMPLE substituted for the entire portfolio; "
                                "requested tickers and dates do not describe this dataset.")


def cache_get(path, table, key):
    column = CACHE_TABLES[table]
    if backend() == "postgres":
        from quantmesh.postgres import cache_get as read
        return read(table, key)
    with database(path) as conn:
        return conn.execute(f"SELECT fetched,payload FROM {table} WHERE {column}=?", (key,)).fetchone()


def cache_put(path, table, key, fetched, payload):
    column = CACHE_TABLES[table]
    if backend() == "postgres":
        from quantmesh.postgres import cache_put as write
        return write(table, key, fetched, payload)
    with database(path) as conn:
        conn.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?,?)", (key, fetched, payload))
        conn.execute(f"DELETE FROM {table} WHERE {column} NOT IN "
                     f"(SELECT {column} FROM {table} ORDER BY fetched DESC LIMIT 64)")
