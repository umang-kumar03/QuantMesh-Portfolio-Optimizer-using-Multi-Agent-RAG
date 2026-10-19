import numpy as np
import pandas as pd
import pytest

from quantmesh.agents import analyze, retrieve
from quantmesh.analytics import optimize, performance, research
from quantmesh.data import read_csv, sample_prices, validate_prices
from quantmesh.storage import list_runs, save_run


def test_sample_and_csv_round_trip():
    prices = sample_prices()
    pd.testing.assert_frame_equal(prices, sample_prices())
    np.testing.assert_allclose(read_csv(prices.to_csv().encode()), prices)


@pytest.mark.parametrize("mutation", ["nan", "negative", "duplicate", "order", "infinity"])
def test_invalid_prices_rejected(mutation):
    p = sample_prices()
    if mutation == "nan":
        p.iloc[5, 0] = np.nan
    elif mutation == "negative":
        p.iloc[5, 0] = -1
    elif mutation == "duplicate":
        p.index = [p.index[0]] * len(p)
    elif mutation == "order":
        p = p.iloc[::-1]
    else:
        p.iloc[5, 0] = np.inf
    with pytest.raises(ValueError):
        validate_prices(p)


def test_duplicate_csv_headers_rejected():
    with pytest.raises(ValueError, match="unique"):
        read_csv(b"Date,A,A\n2024-01-01,1,1")


@pytest.mark.parametrize("objective", ["Minimum variance", "Maximum Sharpe"])
def test_optimizer_constraints(objective):
    r = sample_prices().pct_change().iloc[1:]
    w = optimize(r, objective=objective, max_weight=0.4)
    assert w.sum() == pytest.approx(1)
    assert w.min() >= -1e-8
    assert w.max() <= 0.4 + 1e-8


def test_infeasible_cap_rejected():
    with pytest.raises(ValueError, match="infeasible"):
        optimize(sample_prices().pct_change().iloc[1:], max_weight=0.1)


def test_holdout_does_not_change_weights():
    p = sample_prices()
    first = research(p)
    split = int((len(p) - 1) * 0.7) + 1
    p.iloc[split:] *= np.linspace(1, 3, len(p) - split)[:, None]
    second = research(p)
    np.testing.assert_allclose(first.weights, second.weights)
    assert first.metrics.loc["Total return", "Optimized"] != second.metrics.loc[
        "Total return", "Optimized"]


def test_buy_hold_costs_and_initial_equity():
    p = sample_prices()
    free = research(p, cost_bps=0)
    paid = research(p, cost_bps=50)
    np.testing.assert_allclose(paid.equity.iloc[1:], free.equity.iloc[1:] * 0.995)
    np.testing.assert_allclose(paid.equity.iloc[0], [1, 1])
    test = p.pct_change().iloc[1:]
    test = test.iloc[int(len(test) * 0.7):]
    expected = (1 + test).cumprod() @ free.weights
    np.testing.assert_allclose(free.equity["Optimized"].iloc[1:], expected)
    np.testing.assert_allclose((1 + paid.returns).prod(), paid.equity.iloc[-1])


def test_drawdown_includes_initial_loss():
    metrics = performance(pd.Series([-0.1, 0.0]))
    assert metrics["Max drawdown"] == pytest.approx(-0.1)
    assert metrics["Total return"] == pytest.approx(-0.1)


def test_constant_prices_remain_finite_except_undefined_sharpe():
    p = sample_prices() * 0 + 100
    result = research(p, cost_bps=0)
    assert result.metrics.loc["Total return", "Optimized"] == 0
    assert np.isnan(result.metrics.loc["Sharpe", "Optimized"])


def test_sqlite_roundtrip_and_parameterization(tmp_path):
    path = str(tmp_path / "runs.db")
    name = "Robert'); DROP TABLE runs;--"
    save_run(path, name, {"weights": {"A": 0.5}})
    rows = list_runs(path)
    assert rows[0]["name"] == name
    assert rows[0]["payload"]["weights"]["A"] == 0.5
    with pytest.raises(ValueError):
        save_run(path, "", {})


def test_agents_cite_evidence_and_retrieve_relevant_text():
    assert retrieve("holdout evaluation")[0].id == "M3"
    assert retrieve("xyznonmatching") == []
    review = analyze(research(sample_prices()), "risk")
    assert "[M5]" in review["Risk agent"]
    assert "[M3, M4]" in review["Validation agent"]
    assert "[M5]" in review["Evidence synthesis agent"]
    unknown = analyze(research(sample_prices()), "xyznonmatching")
    assert "Insufficient evidence" in unknown["Evidence synthesis agent"]


def test_report_serializes_undefined_metrics_and_csv_formula_labels():
    import json
    from quantmesh.reports import build_report, safe_csv
    p = sample_prices() * 0 + 100
    report = build_report(p, research(p, cost_bps=0), "sample", {})
    assert report["metrics"]["Optimized"]["Sharpe"] is None
    assert len(report["data_sha256"]) == 64
    json.dumps(report, allow_nan=False)
    csv = safe_csv(pd.DataFrame({"=SUM(A1)": [1]}, index=["@evil"]))
    assert b"'=SUM(A1)" in csv
    assert b"'@evil" in csv


def test_minimum_variance_matches_independent_diagonal_solution():
    # Orthogonal centered return series have variances in the ratio 1:4.
    # With no covariance, the analytical fully invested solution is 80%/20%.
    returns = pd.DataFrame({
        "Low risk": np.tile([-0.01, 0.01, -0.01, 0.01], 20),
        "High risk": np.tile([-0.02, -0.02, 0.02, 0.02], 20),
    })
    weights = optimize(returns)
    np.testing.assert_allclose(weights, [0.8, 0.2], atol=1e-5)
