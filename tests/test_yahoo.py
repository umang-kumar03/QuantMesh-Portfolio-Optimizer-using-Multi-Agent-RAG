"""No network or API credentials: every Yahoo download is controlled."""
from pathlib import Path
from datetime import date
import logging

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from quantmesh.agents import analyze
from quantmesh.analytics import research
from quantmesh.http import ServiceError
from quantmesh.yahoo import YahooClient, download_history, extract_adjusted

START, END = date(2023, 1, 1), date(2024, 1, 1)


def frame(symbols=("SPY", "QQQ", "GLD"), *, layout="price"):
    dates = pd.bdate_range("2023-01-02", periods=180)
    rng = np.random.default_rng(4)
    prices = 100 * np.exp(np.cumsum(rng.normal(.0003, .01, (180, len(symbols))), axis=0))
    values = {}
    for i, symbol in enumerate(symbols):
        values[("Close", symbol)] = prices[:, i] * 2
        values[("Adj Close", symbol)] = prices[:, i]
    result = pd.DataFrame(values, index=dates)
    if layout == "ticker":
        result.columns = result.columns.swaplevel()
    if layout == "flat":
        result.columns = result.columns.droplevel(1)
    return result


@pytest.mark.parametrize("layout", ["flat", "price", "ticker"])
def test_single_ticker_adjusted_extraction(layout):
    raw = frame(("SPY",), layout=layout)
    prices, _ = extract_adjusted(raw, ["SPY"], START, END)
    assert list(prices.columns) == ["SPY"]
    expected = raw["Adj Close"] if layout == "flat" else (
        raw[("Adj Close", "SPY")] if layout == "price" else raw[("SPY", "Adj Close")])
    np.testing.assert_allclose(prices["SPY"], np.asarray(expected))


@pytest.mark.parametrize("layout", ["price", "ticker"])
def test_multi_ticker_layout(layout):
    prices, _ = extract_adjusted(frame(layout=layout), ["QQQ", "SPY", "GLD"], START, END)
    assert list(prices.columns) == ["QQQ", "SPY", "GLD"]
    assert len(prices) == 180


def test_download_flags_cache_and_inclusive_end(tmp_path):
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        return frame()
    path = str(tmp_path / "market.db")
    first = YahooClient(path, downloader=download, clock=lambda: 1000).load(
        ["spy", "qqq", "gld"], START, END, fallback=False)
    second = YahooClient(path, downloader=download, clock=lambda: 1001).load(
        ["SPY", "QQQ", "GLD"], START, END, fallback=False)
    assert len(calls) == 1
    assert calls[0]["auto_adjust"] is False and calls[0]["back_adjust"] is False
    assert calls[0]["end"] == "2024-01-02"
    assert not calls[0]["threads"] and calls[0]["keepna"]
    assert first.provenance["retrieval_status"] == "provider"
    assert second.provenance["retrieval_status"] == "cache"
    assert not first.provenance["synthetic"]
    assert "Adj Close" in first.provenance["adjustment"]
    pd.testing.assert_frame_equal(first.prices, second.prices, check_freq=False)


@pytest.mark.parametrize("problem", ["missing-ticker", "missing-observation", "empty", "unadjusted", "negative", "short"])
def test_bad_downloads_rejected(tmp_path, problem):
    raw = frame()
    if problem == "missing-ticker":
        raw = raw.drop(columns="QQQ", level=1)
    elif problem == "missing-observation":
        raw.loc[raw.index[4], ("Adj Close", "QQQ")] = np.nan
    elif problem == "empty":
        raw = pd.DataFrame()
    elif problem == "unadjusted":
        raw = raw.drop(columns="Adj Close", level=0)
    elif problem == "negative":
        raw.loc[raw.index[4], ("Adj Close", "QQQ")] = -1
    else:
        raw = raw.iloc[:30]
    client = YahooClient(str(tmp_path / "market.db"), downloader=lambda **_: raw)
    with pytest.raises(ServiceError):
        client.load(["SPY", "QQQ", "GLD"], START, END, fallback=False)


def test_invalid_and_identical_duplicate_dates_reported():
    raw = frame()
    raw = pd.concat([raw, raw.iloc[[3]], raw.iloc[[5]]])
    raw.index = [*raw.index[:-1], "invalid-date"]
    prices, cleaned = extract_adjusted(raw.iloc[::-1], ["SPY", "QQQ", "GLD"], START, END)
    assert len(prices) == 180 and prices.index.is_monotonic_increasing
    assert cleaned["invalid_date_rows_removed"] == 1
    assert cleaned["identical_duplicate_rows_removed"] == 1


def test_conflicting_duplicate_dates_rejected():
    raw = frame()
    duplicate = raw.iloc[[2]].copy() * 2
    with pytest.raises(ServiceError, match="conflicting"):
        extract_adjusted(pd.concat([raw, duplicate]), ["SPY", "QQQ", "GLD"], START, END)


@pytest.mark.parametrize(("symbols", "start", "end"), [
    (["SPY"], START, END), (["SPY", "SPY"], START, END),
    (["SPY", "https://evil.example"], START, END),
    (["SPY", "QQQ"], END, START), (["SPY", "QQQ"], START, date(2099, 1, 1)),
])
def test_invalid_request_never_downloads(tmp_path, symbols, start, end):
    def forbidden(**_):
        pytest.fail("invalid request must not download")
    with pytest.raises(ValueError):
        YahooClient(str(tmp_path / "db"), downloader=forbidden).load(symbols, start, end)


def test_failure_fallback_is_whole_portfolio_and_labeled(tmp_path):
    def fail(**_):
        raise ServiceError("Yahoo Finance download failed.")
    result = YahooClient(str(tmp_path / "db"), downloader=fail).load(["SPY", "QQQ"], START, END)
    assert result.provenance["synthetic"]
    assert "SYNTHETIC" in result.warning
    assert "SPY" not in result.prices.columns


def test_library_network_error_sanitized(monkeypatch):
    import yfinance
    def fail(**_):
        raise OSError("private cookie and URL")
    monkeypatch.setattr(yfinance, "download", fail)
    with pytest.raises(ServiceError, match="network") as caught:
        download_history(tickers=["SPY"])
    assert "private cookie" not in str(caught.value)


def test_library_raised_or_swallowed_rate_limit(monkeypatch, caplog):
    import yfinance
    from yfinance.exceptions import YFRateLimitError
    def fail(**_):
        raise YFRateLimitError()
    monkeypatch.setattr(yfinance, "download", fail)
    with pytest.raises(ServiceError, match="rate limit"):
        download_history(tickers=["SPY"])
    def swallowed(**_):
        logging.getLogger("yfinance").error("YFRateLimitError Too Many Requests private-cookie")
        return pd.DataFrame()
    monkeypatch.setattr(yfinance, "download", swallowed)
    with pytest.raises(ServiceError, match="rate limit"):
        download_history(tickers=["SPY"])
    assert "private-cookie" not in caplog.text


@pytest.mark.parametrize("objective", ["Minimum variance", "Maximum Sharpe"])
def test_existing_analytics_and_agents_accept_yahoo_prices(tmp_path, objective):
    data = YahooClient(str(tmp_path / "db"), downloader=lambda **_: frame()).load(
        ["SPY", "QQQ", "GLD"], START, END, fallback=False)
    result = research(data.prices, objective=objective, max_weight=.6, cost_bps=10)
    assert result.weights.sum() == pytest.approx(1)
    assert len(result.returns) > 10
    assert result.test_start > result.training_end
    assert len(analyze(result, "risk volatility")["Retrieved evidence"]) > 0


def test_yahoo_ui_and_source_results_do_not_cross_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "journal"))
    monkeypatch.setenv("QUANTMESH_CACHE_DB", str(tmp_path / "cache"))
    monkeypatch.setattr("quantmesh.yahoo.download_history", lambda **_: frame())
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert app.sidebar.radio[0].options == ["Sample market", "Upload CSV", "Alpha Vantage", "Yahoo Finance"]
    app.sidebar.radio[0].set_value("Yahoo Finance").run()
    next(b for b in app.button if b.label == "Load market history").click().run()
    assert not app.exception and len(app.metric) == 4
    assert any("Yahoo Finance" in message.value for message in app.success)
    app.sidebar.radio[0].set_value("Alpha Vantage").run()
    assert not app.exception and not app.metric
    app.sidebar.radio[0].set_value("Yahoo Finance").run()
    assert len(app.metric) == 4


def test_yahoo_prices_work_with_configured_groq_pipeline(tmp_path):
    import json
    from quantmesh.llm import explain, LLMConfig
    from test_services import Session, Response
    loaded = YahooClient(str(tmp_path / "cache"), downloader=lambda **_: frame()).load(
        ["SPY", "QQQ", "GLD"], START, END, fallback=False)
    session = Session([Response({"choices": [{"message": {"content": json.dumps({"claims": [
        {"source_id": "M5", "quote": "Volatility measures return dispersion.",
         "explanation": "Volatility describes the dispersion of observed returns."}]})}}]})])
    generated = explain(research(loaded.prices), "risk volatility",
                        LLMConfig("groq", "llama-3.3-70b-versatile", "test-only-key"),
                        str(tmp_path / "budget"), session=session)
    assert generated["status"] == "generated"
    assert session.calls[0][2]["json"]["model"] == "llama-3.3-70b-versatile"
    assert "SPY" not in json.dumps(session.calls[0][2]["json"])


def test_yahoo_ui_fallback_report_is_never_labeled_real(tmp_path, monkeypatch):
    from quantmesh.storage import list_runs
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "journal"))
    monkeypatch.setenv("QUANTMESH_CACHE_DB", str(tmp_path / "cache"))
    monkeypatch.setattr("quantmesh.yahoo.download_history", lambda **_: pd.DataFrame())
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    app.sidebar.radio[0].set_value("Yahoo Finance").run()
    next(b for b in app.button if b.label == "Load market history").click().run()
    assert not app.exception and len(app.metric) == 4
    assert any("SYNTHETIC" in e.value for e in app.warning)
    app.button(key="save-research").click().run()
    saved = list_runs(str(tmp_path / "journal"))[0]["payload"]
    assert saved["data_source"] == "Synthetic sample fallback"
    assert saved["market_provenance"]["synthetic"]
    assert saved["market_provenance"]["requested_provider"] == "Yahoo Finance"


def test_expired_yahoo_cache_refetches(tmp_path):
    calls = []
    def download(**_):
        calls.append(True)
        return frame()
    path = str(tmp_path / "cache")
    YahooClient(path, downloader=download, clock=lambda: 100).load(["SPY", "QQQ"], START, END)
    result = YahooClient(path, downloader=download, clock=lambda: 22000).load(["SPY", "QQQ"], START, END)
    assert len(calls) == 2 and result.provenance["retrieval_status"] == "provider"


def test_library_log_filter_restored_after_failure(monkeypatch):
    import yfinance
    logger = logging.getLogger("yfinance")
    original = list(logger.filters)
    def failure(**_):
        raise OSError("test")
    monkeypatch.setattr(yfinance, "download", failure)
    with pytest.raises(ServiceError):
        download_history(tickers=["SPY"])
    assert logger.filters == original
