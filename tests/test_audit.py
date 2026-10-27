"""Independent finance calculations, report boundaries and UI control regressions."""
import csv
import base64
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from quantmesh.analytics import optimize, performance, research
from quantmesh.data import sample_prices
from quantmesh.http import ServiceError
from quantmesh.reports import build_report, safe_csv

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_performance_matches_independent_cashflow_calculation():
    values = [.10, -.05, .02, -.01]
    result = performance(pd.Series(values), risk_free=.03)
    wealth, peak, drawdown = 1., 1., 0.
    for value in values:
        wealth *= 1+value
        peak = max(peak, wealth)
        drawdown = min(drawdown, wealth/peak-1)
    mean = sum(values)/len(values)
    vol = math.sqrt(sum((v-mean)**2 for v in values)/(len(values)-1)*252)
    assert result["Total return"] == pytest.approx(wealth-1)
    assert result["CAGR"] == pytest.approx(wealth**(252/len(values))-1)
    assert result["Volatility"] == pytest.approx(vol)
    assert result["Sharpe"] == pytest.approx((mean*252-.03)/vol)
    assert result["Max drawdown"] == pytest.approx(drawdown)
    assert result["Daily VaR 95%"] == pytest.approx(-.05*.85-.01*.15)


@pytest.mark.parametrize("values", [[1e200, 1e200], [100., 100.], [-.9999]*1000])
def test_performance_rejects_unrepresentable_wealth_or_annualization(values):
    with pytest.raises(ValueError, match="numerical range"):
        performance(pd.Series(values))


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), -.01, .26])
def test_performance_validates_risk_free_rate(rate):
    with pytest.raises(ValueError, match="risk-free"):
        performance(pd.Series([.01, -.01]), risk_free=rate)


@pytest.mark.parametrize("values", [[-.1, 1.1], [float("nan"), 1.], [.9, .1]])
def test_optimizer_checks_solver_postconditions(monkeypatch, values):
    monkeypatch.setattr("quantmesh.analytics.minimize", lambda *_a, **_kw:
                        SimpleNamespace(success=True, x=np.array(values), message="test solver output"))
    with pytest.raises(ValueError, match="feasible allocation"):
        optimize(sample_prices().pct_change().iloc[1:, :2], max_weight=.8)


def test_optimizer_rejects_economically_invalid_and_overflowing_returns():
    invalid = pd.DataFrame({"A": [-1.01]*40, "B": [.01]*40})
    with pytest.raises(ValueError, match="greater than -100%"):
        optimize(invalid)
    extreme = pd.DataFrame({"A": [1e200, 0.]*20, "B": [.01]*40})
    with pytest.raises(ValueError, match="numerical range"):
        optimize(extreme)


def diagonal_returns():
    return pd.DataFrame({"A": .001+np.tile([-.01, .01, -.01, .01], 20),
                         "B": .002+np.tile([-.02, -.02, .02, .02], 20)})


def test_maximum_sharpe_matches_analytic_diagonal_solution_and_binding_cap():
    frame = diagonal_returns()
    weights = optimize(frame, "Maximum Sharpe", risk_free=0)
    np.testing.assert_allclose(weights, [2/3, 1/3], atol=1e-5)
    np.testing.assert_allclose(optimize(frame, "Maximum Sharpe", max_weight=.6, risk_free=0),
                               [.6, .4], atol=1e-5)
    higher_rf = optimize(frame, "Maximum Sharpe", risk_free=.25)
    assert higher_rf["A"] < weights["A"]


@pytest.mark.parametrize("objective", ["Minimum variance", "Maximum Sharpe"])
@pytest.mark.parametrize("fraction", [.5, .7, .85])
def test_each_split_and_objective_excludes_future_prices(objective, fraction):
    prices = sample_prices(periods=252)
    before = research(prices, objective, train_fraction=fraction, max_weight=.6)
    split = int((len(prices)-1)*fraction)
    changed = prices.copy()
    changed.iloc[split+1:] *= np.linspace(1, 2, len(prices)-split-1)[:, None]
    after = research(changed, objective, train_fraction=fraction, max_weight=.6)
    np.testing.assert_allclose(before.weights, after.weights)
    assert before.training_end == prices.index[split].date().isoformat()
    assert before.test_start == prices.index[split+1].date().isoformat()
    assert before.metrics.loc["Total return", "Optimized"] != after.metrics.loc["Total return", "Optimized"]


def test_csv_escapes_text_cells_string_index_and_index_name_without_changing_numbers():
    frame = pd.DataFrame({"=header": ["\t=cmd"], "price": [123.45], "return": [-.02]},
                         index=pd.Index(["@index"], dtype="string", name="+name"))
    rows = list(csv.reader(io.StringIO(safe_csv(frame).decode())))
    assert rows == [["'+name", "'=header", "price", "return"], ["'@index", "'\t=cmd", "123.45", "-0.02"]]
    assert frame.iloc[0, 0] == "\t=cmd"  # Caller data is not modified.


def test_csv_multiindex_formula_levels_are_escaped():
    frame = pd.DataFrame({"value": [1]}, index=pd.MultiIndex.from_tuples([("=formula", "@formula")], names=["-level", "safe"]))
    rows = list(csv.reader(io.StringIO(safe_csv(frame).decode())))
    assert rows[0][0] == "'-level" and rows[1][:2] == ["'=formula", "'@formula"]


def test_report_contains_exact_data_bounds_parameters_and_strict_metrics():
    prices = sample_prices(periods=252)
    params = dict(objective="Maximum Sharpe", train_fraction=.5, max_weight=.6,
                  risk_free=.02, cost_bps=50)
    result = research(prices, **params)
    report = build_report(prices, result, "Upload CSV", {**params, "initial_capital": 123456})
    report = json.loads(json.dumps(report, allow_nan=False))
    assert report["data_start"] == prices.index[0].isoformat()
    assert report["data_end"] == prices.index[-1].isoformat()
    assert report["observations"] == 252 and report["asset_count"] == 5
    assert report["parameters"]["initial_capital"] == 123456
    np.testing.assert_allclose(list(report["weights"].values()), result.weights)
    assert report["training_end"] < report["test_start"]


def test_all_tabs_charts_controls_and_exports_match_saved_results(tmp_path, monkeypatch):
    from quantmesh.storage import list_runs
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "research.db"))
    downloads = {}
    monkeypatch.setattr("quantmesh.exports.download", lambda _target, _label, payload, filename, _mime:
                        downloads.update({filename: payload}))
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Performance", "Risk & allocation", "Research agents", "Data & export", "Saved research"]
    assert len(app.get("plotly_chart")) == 4
    app.sidebar.selectbox[0].select("Maximum Sharpe")
    app.sidebar.slider[0].set_value(50)
    app.sidebar.slider[1].set_value(40)
    for item in app.sidebar.number_input:
        if item.label.startswith("Annual risk-free"):
            item.set_value(5.)
        elif item.label.startswith("Initial transaction"):
            item.set_value(50)
        elif item.label.startswith("Initial capital"):
            item.set_value(200000)
    app.run()
    assert not app.exception
    report = json.loads(downloads["quantmesh-report.json"])
    assert report["parameters"] == dict(objective="Maximum Sharpe", train_fraction=.5,
        max_weight=.4, risk_free=.05, cost_bps=50, initial_capital=200000)
    assert report["data_source"] == "Sample market"
    assert report["market_provenance"]["synthetic"] is True
    prices = pd.read_csv(io.BytesIO(downloads["prices.csv"]), index_col=0, parse_dates=True)
    weights = pd.read_csv(io.BytesIO(downloads["weights.csv"]), index_col=0)
    expected = research(prices, **{k: v for k,v in report["parameters"].items() if k != "initial_capital"})
    np.testing.assert_allclose(weights.iloc[:, 0], expected.weights, atol=1e-12)
    assert report["metrics"]["Optimized"]["Total return"] == pytest.approx(expected.metrics.loc["Total return", "Optimized"])
    spec = json.loads(app.get("plotly_chart")[0].proto.spec)
    trace = next(item for item in spec["data"] if item["name"] == "Optimized")
    encoded = trace["y"]
    values = (np.frombuffer(base64.b64decode(encoded["bdata"]), dtype=encoded["dtype"])
              if isinstance(encoded, dict) else np.asarray(encoded))
    np.testing.assert_allclose(values, expected.equity["Optimized"]*200000)
    app.button(key="save-research").click().run()
    assert not app.exception
    assert list_runs(str(tmp_path / "research.db"))[0]["payload"] == report


def test_journal_safe_service_error_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "research.db"))
    def unavailable(*_a, **_kw):
        raise ServiceError("Research storage demo limit reached. Ask the operator to archive records.")
    monkeypatch.setattr("quantmesh.storage.list_runs", unavailable)
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception and len(app.metric) == 4
    assert any("demo limit reached" in error.value for error in app.error)


def test_csv_upload_ui_validates_and_reports_unverified_provenance(tmp_path, monkeypatch):
    raw = sample_prices(periods=126).iloc[:, :2].to_csv().encode()
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "research.db"))
    monkeypatch.setattr("streamlit.file_uploader", lambda *_a, **_kw: SimpleNamespace(getvalue=lambda: raw))
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.sidebar.radio[0].set_value("Upload CSV").run()
    assert not app.exception and len(app.metric) == 4
    app.button(key="save-research").click().run()
    from quantmesh.storage import list_runs
    report = list_runs(str(tmp_path / "research.db"))[0]["payload"]
    assert report["data_source"] == "Upload CSV"
    assert report["market_provenance"]["synthetic"] is None
    assert report["observations"] == 126 and report["asset_count"] == 2


@pytest.mark.parametrize("raw", [b"", b"Date,A,B\n"+b"invalid-date,1,2\n"*61,
                                sample_prices(periods=126).to_csv().replace("Date,", "Wrong,").encode()])
def test_invalid_csv_upload_stops_dashboard_safely(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("QUANTMESH_DB", str(tmp_path / "research.db"))
    monkeypatch.setattr("streamlit.file_uploader", lambda *_a, **_kw: SimpleNamespace(getvalue=lambda: raw))
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.sidebar.radio[0].set_value("Upload CSV").run()
    assert not app.exception and not app.metric and app.error


@pytest.mark.parametrize("objective", ["Minimum variance", "Maximum Sharpe"])
@pytest.mark.parametrize("assets", [2, 5])
def test_exact_feasible_weight_cap(objective, assets):
    returns = sample_prices().iloc[:, :assets].pct_change().iloc[1:]
    np.testing.assert_allclose(optimize(returns, objective, max_weight=1/assets), np.full(assets, 1/assets), atol=1e-8)


def test_blank_research_name_has_validation_message_and_no_write(tmp_path, monkeypatch):
    from quantmesh.storage import list_runs
    path = str(tmp_path / "research.db")
    monkeypatch.setenv("QUANTMESH_DB", path)
    app = AppTest.from_file(APP, default_timeout=30).run()
    next(item for item in app.text_input if item.label == "Research name").set_value(" ")
    app.button(key="save-research").click().run()
    assert not app.exception
    assert any("Research name must contain" in item.value for item in app.error)
    assert not list_runs(path)
