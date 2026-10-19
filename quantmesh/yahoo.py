"""Unofficial Yahoo adjusted EOD history; no API key or unadjusted-price fallback."""
import hashlib
import json
import logging
import threading
import sqlite3
import re
import time
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pandas as pd

from quantmesh.data import sample_prices, validate_prices
from quantmesh.http import ServiceError
from quantmesh.market import MarketResult, database, reserve_request


def extract_adjusted(raw: pd.DataFrame, symbols: list[str], start: date,
                     end: date) -> tuple[pd.DataFrame, dict]:
    """Accept Adj Close explicitly; auto_adjust=False makes Close an unsafe substitute."""
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        raise ServiceError("Yahoo Finance returned no price history. Check symbols and dates.")
    if isinstance(raw.columns, pd.MultiIndex):
        levels = [level for level in range(raw.columns.nlevels)
                  if "Adj Close" in raw.columns.get_level_values(level)]
        if len(levels) != 1 or raw.columns.nlevels != 2:
            raise ServiceError("Yahoo Finance did not return an unambiguous adjusted-price field.")
        prices = raw.xs("Adj Close", axis=1, level=levels[0]).copy()
        prices.columns = prices.columns.map(lambda item: str(item).strip().upper())
    else:
        if len(symbols) != 1 or "Adj Close" not in raw.columns:
            raise ServiceError("Yahoo Finance adjusted prices are unavailable; unadjusted Close is not used.")
        prices = raw[["Adj Close"]].rename(columns={"Adj Close": symbols[0]}).copy()
    if prices.columns.duplicated().any() or any(s not in prices.columns for s in symbols):
        raise ServiceError("Yahoo Finance returned missing or ambiguous ticker history.")
    prices = prices.loc[:, symbols]
    if pd.api.types.is_numeric_dtype(prices.index.dtype):
        raise ServiceError("Yahoo Finance returned invalid trading dates.")
    try:
        dates = pd.DatetimeIndex(pd.to_datetime(prices.index, errors="coerce", format="mixed"))
        if dates.tz is not None:
            dates = dates.tz_localize(None)  # preserve the exchange's daily session date
        prices.index = dates.normalize()
    except (TypeError, ValueError):
        raise ServiceError("Yahoo Finance returned incompatible trading dates.") from None
    invalid = int(prices.index.isna().sum())
    prices = prices.loc[~prices.index.isna()].sort_index(kind="stable")
    duplicate_count = int(prices.index.duplicated().sum())
    duplicate_rows = prices.loc[prices.index.duplicated(keep=False)]
    if not duplicate_rows.empty and (duplicate_rows.groupby(level=0).nunique(dropna=False) > 1).any().any():
        raise ServiceError("Yahoo Finance returned conflicting prices for duplicate trading dates.")
    prices = prices.loc[~prices.index.duplicated(keep="last")]
    outside = int(((prices.index < pd.Timestamp(start)) | (prices.index > pd.Timestamp(end))).sum())
    prices = prices.loc[str(start):str(end)].apply(pd.to_numeric, errors="coerce")
    prices.index.name = "Date"
    if prices.empty or prices.isna().any().any():
        raise ServiceError("Yahoo Finance has missing observations or ticker history in this range; "
                           "no prices were filled or incomplete assets substituted.")
    return prices, {"invalid_date_rows_removed": invalid,
                    "identical_duplicate_rows_removed": duplicate_count,
                    "outside_requested_range_rows_removed": outside}


class _DownloadLogFilter(logging.Filter):
    """Suppress this call's library diagnostics (which may contain cookies or URLs)."""
    def __init__(self):
        super().__init__()
        self.thread = threading.get_ident()
        self.rate_limited = False

    def filter(self, record):
        if record.thread != self.thread:
            return True
        message = record.getMessage()
        if "YFRateLimitError" in message or "Too Many Requests" in message:
            self.rate_limited = True
        return False


def download_history(**kwargs):
    # yfinance owns cookie/crumb negotiation. Never reuse personal sessions.
    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError
    guard = _DownloadLogFilter()
    logger = logging.getLogger("yfinance")
    logger.addFilter(guard)
    try:
        raw = yf.download(**kwargs)
        # download() may swallow ticker exceptions and log them instead of raising.
        if guard.rate_limited:
            raise ServiceError("Yahoo Finance rate limit reached. Wait before retrying.")
        return raw
    except YFRateLimitError:
        raise ServiceError("Yahoo Finance rate limit reached. Wait before retrying.") from None
    except ServiceError:
        raise
    except Exception:
        raise ServiceError("Yahoo Finance download failed. Check network access and retry later.") from None
    finally:
        logger.removeFilter(guard)


class YahooClient:
    def __init__(self, cache_path: str, *, downloader=None, clock=time.time):
        self.path, self.downloader, self.clock = cache_path, downloader or download_history, clock

    def load(self, symbols: list[str], start: date, end: date, *, fallback=True) -> MarketResult:
        symbols = [s.strip().upper() for s in symbols]
        if not 2 <= len(symbols) <= 5 or len(set(symbols)) != len(symbols):
            raise ValueError("Choose 2–5 unique symbols.")
        if any(not re.fullmatch(r"[A-Z0-9][A-Z0-9.:-]{0,19}", s) for s in symbols):
            raise ValueError("Invalid Yahoo Finance symbol. Use exchange ticker notation, not URLs.")
        if start >= end or end > date.today():
            raise ValueError("Choose a historical start date before the end date, no later than today.")
        now = self.clock()
        cache_key = hashlib.sha256(json.dumps([symbols, str(start), str(end), "adj-close-v1"]).encode()).hexdigest()
        try:
            with database(self.path) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS yahoo_history "
                             "(cache_key TEXT PRIMARY KEY, fetched REAL NOT NULL, payload TEXT NOT NULL)")
                cached = conn.execute("SELECT fetched,payload FROM yahoo_history WHERE cache_key=?",
                                      (cache_key,)).fetchone()
            if cached and 0 <= now - cached[0] < 21600:
                try:
                    payload = json.loads(cached[1])
                    prices = validate_prices(pd.read_json(StringIO(payload["prices"]), orient="table"))
                    if list(prices.columns) != symbols or not (
                            prices.index.min() >= pd.Timestamp(start) and prices.index.max() <= pd.Timestamp(end)):
                        raise ValueError
                    provenance = payload["provenance"]
                    if provenance.get("provider") != "Yahoo Finance" or provenance.get("synthetic") is not False:
                        raise ValueError
                    provenance["retrieval_status"] = "cache"
                    return MarketResult(prices, provenance)
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass  # invalid cache is never trusted; refresh within the normal budget
            reserve_request(self.path, "yahoo-download", 5, 25, now)
            if self.downloader is download_history:
                import yfinance as yf
                location = Path(self.path).parent / "yfinance"
                location.mkdir(parents=True, exist_ok=True)
                yf.set_tz_cache_location(str(location))
            raw = self.downloader(tickers=symbols, start=start.isoformat(),
                                  end=(end + timedelta(days=1)).isoformat(), interval="1d",
                                  auto_adjust=False, back_adjust=False, actions=False,
                                  repair=False, keepna=True, progress=False, threads=False, ignore_tz=True,
                                  group_by="column", multi_level_index=True, timeout=20)
            prices, cleaning = extract_adjusted(raw, symbols, start, end)
            try:
                prices = validate_prices(prices)
            except ValueError:
                raise ServiceError("Yahoo Finance history failed daily-price validation. "
                                   "Use at least 61 complete positive daily observations.") from None
            provenance = {"provider": "Yahoo Finance", "library": "yfinance", "synthetic": False,
                          "symbols": symbols, "requested_start": str(start), "requested_end": str(end),
                          "actual_start": str(prices.index.min().date()),
                          "actual_end": str(prices.index.max().date()),
                          "adjustment": "Explicit Adj Close; auto_adjust=False; no Close substitution",
                          "retrieved_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                          "retrieval_status": "provider", "cleaning": cleaning,
                          "frequency": "historical end-of-day; not real-time quotes"}
            payload = json.dumps({"prices": prices.to_json(orient="table", date_format="iso"),
                                  "provenance": provenance}, allow_nan=False)
            with database(self.path) as conn:
                conn.execute("INSERT OR REPLACE INTO yahoo_history VALUES (?,?,?)", (cache_key, now, payload))
                conn.execute("DELETE FROM yahoo_history WHERE cache_key NOT IN "
                             "(SELECT cache_key FROM yahoo_history ORDER BY fetched DESC LIMIT 64)")
            return MarketResult(prices, provenance)
        except (ServiceError, OSError, sqlite3.Error, ValueError, TypeError) as exc:
            # Never return raw yfinance/curl/cache exceptions to the UI, even with fallback disabled.
            message = str(exc) if isinstance(exc, ServiceError) else "Yahoo Finance service or cache is unavailable."
            if not fallback:
                raise ServiceError(message) from None
            return MarketResult(sample_prices(), {"provider": "synthetic", "synthetic": True,
                                "requested_provider": "Yahoo Finance", "requested_symbols": symbols,
                                "requested_start": str(start), "requested_end": str(end)},
                                message + " SYNTHETIC SAMPLE substituted for the entire portfolio; "
                                "requested tickers and dates do not describe this dataset.")
