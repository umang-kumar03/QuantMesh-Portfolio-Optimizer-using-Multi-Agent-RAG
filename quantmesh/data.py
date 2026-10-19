"""Strict price ingestion. No forward filling or silent data repair."""
from io import BytesIO

import numpy as np
import pandas as pd

MAX_BYTES = 10 * 1024 * 1024


def validate_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if not 2 <= len(frame.columns) <= 30:
        raise ValueError("Provide between 2 and 30 asset columns.")
    if not 61 <= len(frame) <= 10000:
        raise ValueError("Provide between 61 and 10,000 daily observations.")
    if frame.columns.duplicated().any() or any(not str(c).strip() for c in frame.columns):
        raise ValueError("Asset names must be unique and nonempty.")
    frame = frame.copy()
    try:
        frame.index = pd.to_datetime(frame.index, errors="raise", utc=True).tz_convert(None)
        frame = frame.astype(float)
    except (ValueError, TypeError) as exc:
        raise ValueError("Dates must be valid and all prices must be numeric.") from exc
    if frame.index.hasnans or frame.index.duplicated().any():
        raise ValueError("Dates must be present and unique.")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("Dates must be in ascending order.")
    if not np.isfinite(frame.to_numpy()).all() or (frame <= 0).any().any():
        raise ValueError("Prices must be positive and finite, with no missing values.")
    if (frame.index.normalize().duplicated()).any():
        raise ValueError("Only one observation per calendar day is supported.")
    if ((frame.index[-1] - frame.index[0]).days / (len(frame) - 1)) > 4:
        raise ValueError("Use daily price data; weekly or monthly data is not supported.")
    return frame


def read_csv(raw: bytes) -> pd.DataFrame:
    if len(raw) > MAX_BYTES:
        raise ValueError("CSV exceeds the 10 MB limit.")
    try:
        import csv
        headers = next(csv.reader(BytesIO(raw).read().decode("utf-8-sig").splitlines()))
        if len(headers) != len(set(headers)):
            raise ValueError("CSV column names must be unique.")
        frame = pd.read_csv(BytesIO(raw))
        if frame.columns[0] != "Date":
            raise ValueError("First CSV column must be Date.")
        return validate_prices(frame.set_index("Date"))
    except (IndexError, StopIteration, UnicodeError, pd.errors.ParserError,
            pd.errors.EmptyDataError) as exc:
        raise ValueError("Unable to read CSV. Use Date followed by numeric asset columns.") from exc


def sample_prices(seed: int = 42, periods: int = 1008) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    market = rng.normal(0.00025, 0.009, (periods, 1))
    beta = np.array([1.1, 0.85, 0.2, 0.45, 1.25])
    noise = rng.normal(0, [0.007, 0.006, 0.003, 0.008, 0.012], (periods, 5))
    returns = market * beta + noise + [0.0001, 0.00008, 0.00004, 0.00005, 0.00015]
    frame = pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)),
                         index=pd.bdate_range("2021-01-04", periods=periods),
                         columns=["US Equity", "Global Equity", "Bonds", "Gold", "Technology"])
    frame.index.name = "Date"
    return validate_prices(frame)
