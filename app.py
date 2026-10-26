"""QuantMesh portfolio research workspace."""
import json
import os
import sqlite3
from datetime import date

import plotly.express as px
import streamlit as st

from quantmesh.agents import CORPUS, analyze
from quantmesh.analytics import research
from quantmesh.data import read_csv, sample_prices
from quantmesh.storage import list_runs, save_run
from quantmesh.reports import build_report, safe_csv
from quantmesh.exports import download
from quantmesh.auth import require_user
from quantmesh.market import MarketClient
from quantmesh.yahoo import YahooClient
from quantmesh.llm import LLMConfig, explain
from quantmesh.http import ServiceError

st.set_page_config(page_title="QuantMesh | Portfolio Lab", page_icon="◈", layout="wide")
st.markdown("""<style>
.block-container {padding-top:2rem;max-width:1500px}
[data-testid="stMetric"] {background:#151d32;padding:18px;border-radius:12px}
h1 {letter-spacing:-1.5px} footer {visibility:hidden}
</style>""", unsafe_allow_html=True)
st.caption("◈ QUANTMESH  /  RESEARCH WORKSPACE")
st.title("Clarity in every allocation.")
st.write("Build a portfolio, challenge its assumptions, and follow the evidence.")
owner = require_user(st)
cache_path = os.environ.get("QUANTMESH_CACHE_DB", ".quantmesh/market.sqlite3")
provenance = {}

with st.sidebar:
    st.header("Portfolio lab")
    source = st.radio("Data source", ["Sample market", "Upload CSV", "Alpha Vantage", "Yahoo Finance"])
    uploaded = st.file_uploader("Daily adjusted closing prices", type=["csv"]) if source == "Upload CSV" else None
    if source in {"Alpha Vantage", "Yahoo Finance"}:
        st.caption("Historical end-of-day adjusted prices, not real-time quotes.")
        st.caption("Alpha Vantage adjusted history needs plan entitlement." if source == "Alpha Vantage"
                   else "Yahoo Finance via yfinance · Unofficial access; no API key required.")
        with st.form("market-request-" + source):
            symbols_text = st.text_input("Symbols (2–5, comma-separated)", "SPY,QQQ,GLD")
            start = st.date_input("History start", date(2021, 1, 4))
            end = st.date_input("History end", date.today())
            allow_fallback = st.checkbox("Use labeled sample data on service failure", value=True)
            fetch_market = st.form_submit_button("Load market history")
        if fetch_market:
            try:
                with st.spinner("Loading validated market history…"):
                    client = (YahooClient(cache_path) if source == "Yahoo Finance" else
                              MarketClient(cache_path, os.environ.get("ALPHAVANTAGE_API_KEY", "")))
                    loaded = client.load(symbols_text.split(","), start, end, fallback=allow_fallback)
                    st.session_state["market_result_" + source] = loaded
            except (ValueError, OSError, sqlite3.Error) as exc:
                st.session_state.pop("market_result_" + source, None)
                st.error(str(exc) if isinstance(exc, ValueError) else "Market storage is unavailable.")
    st.caption("CSV: Date, then 2–30 assets. 61–10,000 rows; ascending, unique dates; no gaps in values.")
    objective = st.selectbox("Optimization", ["Minimum variance", "Maximum Sharpe"])
    training = st.slider("Training data (%)", 50, 85, 70, 5)
    cap = st.slider("Maximum asset weight (%)", 10, 100, 60, 5)
    rf = st.number_input("Annual risk-free rate (%)", 0.0, 25.0, 3.0, 0.25)
    costs = st.number_input("Initial transaction cost (bps)", 0, 100, 10)
    capital = st.number_input("Initial capital ($)", 100, 100000000, 100000, 1000)
    st.divider()
    st.caption("Research tool · No trade execution · Not investment advice")

try:
    if source in {"Alpha Vantage", "Yahoo Finance"}:
        loaded = st.session_state.get("market_result_" + source)
        if loaded is None:
            st.info("Submit Load market history to fetch prices or use the sample fallback.")
            st.stop()
        prices, provenance = loaded.prices, loaded.provenance
        if loaded.warning:
            st.warning(loaded.warning)
        if provenance["synthetic"]:
            st.info("SYNTHETIC SAMPLE DATA")
        else:
            st.success(source + " adjusted historical prices loaded. Check provenance and timestamps.")
        with st.expander("Market data provenance"):
            st.json(provenance)
    elif source == "Upload CSV":
        if uploaded is None:
            st.info("Upload daily adjusted prices to begin, or select Sample market.")
            st.stop()
        prices = read_csv(uploaded.getvalue())
        st.info("Imported prices: verify adjustment for dividends, splits, and currency consistency.")
    else:
        prices = sample_prices()
        st.info("SAMPLE DATA · Reproducible synthetic prices, not actual market history.")
    params = dict(objective=objective, train_fraction=training / 100, max_weight=cap / 100,
                  risk_free=rf / 100, cost_bps=costs)
    with st.spinner("Evaluating allocation and chronological holdout…"):
        result = research(prices, **params)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

m = result.metrics["Optimized"]
cols = st.columns(4)
for col, key in zip(cols, ["Total return", "CAGR", "Volatility", "Max drawdown"]):
    col.metric(key, f"{m[key]:.2%}")
st.caption(f"{len(prices):,} daily observations · {len(prices.columns)} assets · "
           f"Training through {result.training_end} · Holdout from {result.test_start}")

overview, risk, evidence, data, saved = st.tabs(
    ["Performance", "Risk & allocation", "Research agents", "Data & export", "Saved research"])
with overview:
    st.subheader("Out-of-sample portfolio value")
    st.plotly_chart(px.line(result.equity * capital, labels={"value": "Portfolio value ($)",
                    "index": "Date", "variable": "Portfolio"},
                    color_discrete_sequence=["#41dbc0", "#8f9ef5"]), width="stretch")
    st.dataframe(result.metrics.style.format("{:.3f}"), width="stretch")
    st.caption("Returns are decimal fractions; Sharpe is unitless. 252 trading days per year. "
               "Both portfolios buy and hold, with identical initial costs; no rebalancing.")
with risk:
    left, right = st.columns(2)
    with left:
        st.subheader("Target allocation")
        st.plotly_chart(px.pie(names=result.weights.index, values=result.weights.values,
                              hole=0.65), width="stretch")
        st.dataframe(result.weights.to_frame().style.format("{:.2%}"))
    with right:
        st.subheader("Asset return correlations")
        st.plotly_chart(px.imshow(prices.pct_change(fill_method=None).iloc[1:].corr(),
                                  zmin=-1, zmax=1, color_continuous_scale="Tealrose"),
                        width="stretch")
        st.caption("Correlation uses the complete dataset for descriptive analysis only; "
                   "the optimizer uses training observations only.")
    drawdowns = result.equity / result.equity.cummax() - 1
    st.plotly_chart(px.area(drawdowns, labels={"value": "Drawdown"}), width="stretch")
with evidence:
    st.subheader("Specialist research review")
    st.caption("Deterministic analytics + cited local methodology. Optional AI explanations are separate. "
               "Evidence is a curated methodology corpus, not external financial research.")
    query = st.text_input("Find methodology evidence", "portfolio risk diversification holdout")
    review = analyze(result, query)
    for name in ["Allocation agent", "Risk agent", "Validation agent",
                 "Evidence synthesis agent"]:
        with st.container(border=True):
            st.markdown(f"**{name}**")
            st.write(review[name])
    st.markdown("**Retrieved methodology**")
    if not review["Retrieved evidence"]:
        st.info("No matching evidence. Try risk, diversification, costs, or holdout.")
    for item in review["Retrieved evidence"]:
        st.write(f"[{item.id}] {item.title}: {item.text}")
    st.divider()
    st.markdown("**Optional AI explanation**")
    st.caption("Explicit opt-in: sends your question, computed summary metrics and retrieved "
               "methodology to the configured provider. Groq JSON-mode rejection may trigger one "
               "additional budgeted request. No raw prices, tickers or saved journal "
               "are sent automatically. Do not include confidential information in the question.")
    consent = st.checkbox("I agree to send this question and summary to the configured AI provider")
    if st.button("Generate AI explanation", disabled=not consent):
        try:
            config = LLMConfig(os.environ.get("QUANTMESH_LLM_PROVIDER", "openai"),
                               os.environ.get("QUANTMESH_LLM_MODEL", ""),
                               os.environ.get("QUANTMESH_LLM_API_KEY", ""))
            with st.spinner("Generating and validating cited explanation…"):
                generated = explain(result, query, config, cache_path)
            if generated["status"] == "abstained":
                st.info(generated["message"])
            else:
                st.warning(generated["warning"])
                if generated.get("json_mode_recovery"):
                    st.info("Groq JSON mode rejected its first generation. A single recovery "
                            "request succeeded and passed the same citation checks.")
                for claim in generated["claims"]:
                    ref = generated["sources"][claim["source_id"]]
                    st.text(f"[{claim['source_id']}] {ref['title']}")
                    st.text("Verified excerpt: " + claim["quote"])
                    st.text("AI interpretation (unverified): " + claim["explanation"])
        except (ServiceError, OSError, sqlite3.Error) as exc:
            st.error(str(exc) if isinstance(exc, ServiceError) else
                     "AI request budget storage unavailable. Deterministic research is unaffected.")
    with st.expander("All citation sources"):
        for item in CORPUS:
            st.write(f"[{item.id}] {item.title}: {item.text}")
with data:
    st.subheader("Price history")
    st.dataframe(prices, width="stretch")
    actual_source = "Synthetic sample fallback" if provenance.get("synthetic") else source
    report = build_report(prices, result, actual_source, {**params, "initial_capital": capital})
    report["market_provenance"] = provenance
    a, b, c = st.columns(3)
    download(a, "Download prices CSV", safe_csv(prices), "prices.csv", "text/csv")
    download(b, "Download weights CSV", safe_csv(result.weights.to_frame()),
                      "weights.csv", "text/csv")
    download(c, "Download research report", json.dumps(report, indent=2, allow_nan=False),
                      "quantmesh-report.json", "application/json")
    st.caption("Report includes parameters, data fingerprint, split dates, metrics, and weights. "
               "Export prices as well to reproduce an imported dataset.")
with saved:
    st.subheader("Private research journal")
    st.caption("Research is scoped to your signed-in account. Uploaded raw prices are not saved.")
    name = st.text_input("Research name", "Portfolio experiment")
    db = os.environ.get("QUANTMESH_DB", ".quantmesh/research.sqlite3")
    try:
        if st.button("Save research snapshot", type="primary", key="save-research"):
            save_run(db, name, report, owner=owner)
            st.success("Research snapshot saved.")
        for run in list_runs(db, owner=owner):
            with st.expander(f"#{run['id']} · {run['name']} · {run['created'][:19]} UTC"):
                st.json(run["payload"])
    except (ServiceError, OSError, ValueError, sqlite3.Error):
        st.error("Research journal is unavailable. Check storage permissions and retry; "
                 "contact the operator if the problem persists.")
st.divider()
st.caption("Limitations: historical estimation risk, selection bias, end-of-day prices, no taxes, "
           "no liquidity model. Repeated holdout tuning introduces selection bias. "
           "Maximum Sharpe optimization is a local numerical solution, not a guarantee.")
