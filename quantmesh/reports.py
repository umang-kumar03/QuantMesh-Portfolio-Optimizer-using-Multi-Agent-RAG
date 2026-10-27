"""Portable, strict reports and spreadsheet-safe CSV exports."""
import hashlib
import json

import pandas as pd

from quantmesh.analytics import ResearchResult


def safe_csv(frame: pd.DataFrame) -> bytes:
    frame = frame.copy()

    def safe(value):
        if not isinstance(value, str):
            return value
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    frame = frame.map(safe)
    frame.columns = [safe(str(c)) for c in frame.columns]
    if isinstance(frame.index, pd.MultiIndex):
        frame.index = pd.MultiIndex.from_tuples(
            [tuple(safe(part) for part in key) for key in frame.index], names=frame.index.names)
    else:
        frame.index = frame.index.map(safe)
    frame.index.names = [safe(name) for name in frame.index.names]
    return frame.to_csv().encode()


def build_report(prices: pd.DataFrame, result: ResearchResult, source: str,
                 parameters: dict) -> dict:
    return {
        "schema_version": 1,
        "data_source": source,
        "data_start": prices.index[0].isoformat(),
        "data_end": prices.index[-1].isoformat(),
        "observations": len(prices),
        "asset_count": len(prices.columns),
        "data_sha256": hashlib.sha256(prices.to_csv().encode()).hexdigest(),
        "parameters": parameters,
        "training_end": result.training_end,
        "test_start": result.test_start,
        "weights": result.weights.to_dict(),
        "metrics": json.loads(result.metrics.to_json()),
        "assumptions": "Daily adjusted prices; 252 days/year; buy and hold; initial costs only",
    }
