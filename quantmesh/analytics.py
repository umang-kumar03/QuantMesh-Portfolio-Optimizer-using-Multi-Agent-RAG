"""Long-only optimization and chronological holdout evaluation."""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

TRADING_DAYS = 252


@dataclass
class ResearchResult:
    weights: pd.Series
    returns: pd.DataFrame
    equity: pd.DataFrame
    metrics: pd.DataFrame
    training_end: str
    test_start: str
    turnover: float


def _validate_risk_free(risk_free):
    if not np.isfinite(risk_free) or not 0 <= risk_free <= 0.25:
        raise ValueError("Annual risk-free rate must be between 0 and 25%.")


def optimize(returns: pd.DataFrame, objective: str = "Minimum variance",
             max_weight: float = 1.0, risk_free: float = 0.03) -> pd.Series:
    n = returns.shape[1]
    if n < 2 or len(returns) < 30 or (not np.isfinite(returns.to_numpy()).all() or (returns <= -1).any().any()):
        raise ValueError("Optimization needs at least 30 finite returns greater than -100% for two assets.")
    if returns.columns.duplicated().any():
        raise ValueError("Optimization asset names must be unique.")
    if objective not in {"Minimum variance", "Maximum Sharpe"}:
        raise ValueError("Unknown optimization objective.")
    if not np.isfinite(max_weight) or not 1 / n <= max_weight <= 1:
        raise ValueError("Weight cap is infeasible: cap × number of assets must be at least 1.")
    _validate_risk_free(risk_free)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            mu = returns.mean().to_numpy() * TRADING_DAYS
            cov = returns.cov().to_numpy() * TRADING_DAYS
            # Fixed diagonal shrinkage uses training data only.
            cov = 0.9 * cov + 0.1 * np.diag(np.diag(cov)) + np.eye(n) * 1e-10
    except FloatingPointError:
        raise ValueError("Return estimates exceed the supported numerical range.") from None
    if not np.isfinite(mu).all() or not np.isfinite(cov).all():
        raise ValueError("Return estimates exceed the supported numerical range.")

    def loss(w):
        variance = float(w @ cov @ w)
        if objective == "Minimum variance":
            return variance
        return -float((w @ mu - risk_free) / np.sqrt(max(variance, 1e-12)))

    result = minimize(loss, np.full(n, 1 / n), method="SLSQP",
                      bounds=[(0, max_weight)] * n,
                      constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                      options={"maxiter": 1000, "ftol": 1e-10})
    if (not result.success or result.x.shape != (n,) or not np.isfinite(result.x).all()
            or abs(result.x.sum() - 1) > 1e-6 or (result.x < -1e-6).any()
            or (result.x > max_weight + 1e-6).any()):
        raise ValueError("Optimizer failed to find a feasible allocation: " + result.message)
    return pd.Series(result.x, index=returns.columns, name="Weight")


def performance(returns: pd.Series, risk_free: float = 0.03) -> dict:
    values = returns.to_numpy()
    if len(values) < 2 or not np.isfinite(values).all() or (values <= -1).any():
        raise ValueError("Performance requires at least two finite returns greater than -100%.")
    _validate_risk_free(risk_free)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            equity = np.r_[1.0, np.cumprod(1 + values)]
            if (equity <= 0).any():
                raise FloatingPointError
            years = len(values) / TRADING_DAYS
            vol = float(np.std(values, ddof=1) * np.sqrt(TRADING_DAYS))
            excess = values.mean() * TRADING_DAYS - risk_free
            metrics = {"Total return": equity[-1] - 1,
                       "CAGR": equity[-1] ** (1 / years) - 1,
                       "Volatility": vol,
                       "Sharpe": float(excess / vol) if vol > 1e-12 else np.nan,
                       "Max drawdown": float((equity / np.maximum.accumulate(equity) - 1).min()),
                       "Daily VaR 95%": float(np.quantile(values, 0.05))}
    except FloatingPointError:
        raise ValueError("Performance exceeds the supported numerical range. Check price scales and returns.") from None
    if any(not np.isfinite(value) for key, value in metrics.items() if key != "Sharpe"):
        raise ValueError("Performance exceeds the supported numerical range. Check price scales and returns.")
    return metrics


def research(prices: pd.DataFrame, objective: str = "Minimum variance",
             train_fraction: float = 0.7, max_weight: float = 1.0,
             risk_free: float = 0.03, cost_bps: float = 10) -> ResearchResult:
    from quantmesh.data import validate_prices
    prices = validate_prices(prices)
    if not 0.5 <= train_fraction <= 0.85:
        raise ValueError("Training fraction must be between 50% and 85%.")
    if not np.isfinite(cost_bps) or not 0 <= cost_bps <= 100:
        raise ValueError("Transaction cost must be between 0 and 100 basis points.")
    returns = prices.pct_change(fill_method=None).iloc[1:]
    split = int(len(returns) * train_fraction)
    train, test = returns.iloc[:split], returns.iloc[split:]
    if len(train) < 30 or len(test) < 10:
        raise ValueError("Insufficient observations for a chronological holdout.")
    weights = optimize(train, objective, max_weight, risk_free)
    equal = np.full(len(weights), 1 / len(weights))
    # Buy-and-hold: asset weights drift; no hidden daily rebalancing.
    growth = (1 + test).cumprod()
    equity = pd.DataFrame({"Optimized": growth @ weights, "Equal weight": growth @ equal})
    equity *= 1 - cost_bps / 10000  # initial investment from cash, 100% traded notional
    evaluated = equity.pct_change(fill_method=None)
    evaluated.iloc[0] = equity.iloc[0] - 1
    metrics = pd.DataFrame({c: performance(evaluated[c], risk_free) for c in equity})
    baseline = pd.DataFrame([[1., 1.]], columns=equity.columns, index=[train.index[-1]])
    equity = pd.concat([baseline, equity])
    return ResearchResult(weights, evaluated, equity, metrics,
                          str(train.index[-1].date()), str(test.index[0].date()), 1.0)
