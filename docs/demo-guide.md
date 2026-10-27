# QuantMesh — guided public demo

**Live app:** https://quantmesh-portfolio-optimizer-using-multi-agent-rag-7ujd3x7e8m.streamlit.app/

> Access is sign-in gated. The operator creates demo accounts privately; there are no public/default passwords or signup links. Do not put credentials into screenshots, URLs, issue comments or the repository.

## Five-minute walkthrough

| Step | Screen | Action | What to look for |
|---|---|---|---|
| 1 | Sign in | Use your own operator-provisioned account | Authenticated `Portfolio lab` sidebar. Each account has its own saved research |
| 2 | Performance | Select **Sample market**, then switch between **Minimum variance** and **Maximum Sharpe** | Total return, CAGR, volatility, drawdown, optimized-vs-equal-weight chart, train/holdout dates |
| 3 | Risk & allocation | Explore weights, heatmap and drawdown | Weights total 100%, each within configured cap; correlations are descriptive and use the full observed period |
| 4 | Research agents | Read deterministic allocation/risk/validation/evidence results | Local methodology references; **optional** AI button only after explicit consent |
| 5 | Data & export | Download prices CSV, weights CSV and research JSON | Source provenance, split boundaries, reported parameters and metrics |
| 6 | Saved research | Save a small sample snapshot, refresh and sign back in | Only your own previously saved research appears |
| 7 | External data | Select Yahoo Finance, e.g. `SPY,QQQ,GLD`; disable sample fallback before testing real data | Green **adjusted historical prices loaded** banner plus provenance; Yahoo is unofficial, data may be unavailable |

**CSV test:** Upload a previously exported `prices.csv` (or a safe sample with Date + 2–30 adjusted-price columns and 61–10,000 ordered dates); verify new graph and metrics. Do not upload private holdings or account statements to a public demonstration.

**Alpha Vantage:** Its daily adjusted series requires a compatible premium plan. A free key may receive a clear entitlement error; this is not equivalent to a broken optimizer. For freely accessible adjusted history use Yahoo Finance where its access terms permit.

## Display and interpretation

- This is **research software**, not trading execution or investment advice.
- Backtest returns are historical and **not forecasts**. Maximum Sharpe can underperform out of sample.
- Synthetic samples are visibly labeled. Uploaded data are user supplied and adjustments are not independently verified.
- The research agents rely on a **local curated methodology corpus**. The Groq/OpenAI option sends the consented question and selected computed facts to the provider and labels generated interpretations as unverified.
- Cited excerpts are verified for identity and exact quotation, **not for semantic truth**.

## Screenshot preparation for a public README / portfolio

Do **not** commit screenshots of a logged-in private journal, personal workspace, browser profile, private user identifier, authentication form entries, URLs with tokens, Streamlit Secrets or provider credentials.

For optional visuals, use a clean **synthetic** data session; crop browser chrome and sidebar account details; exclude saved records and API/network debug panels. Manually review and redact all pixels and image metadata before adding screenshots to `docs/images/`. No screenshots were added by this documentation change because access-scoped screenshots cannot be safely published without operator review.

Recommended public screenshots, when sanitized and approved by the operator: **Sample performance chart**, **synthetic allocation and correlation heatmap**, **research agent citation panel**. This repository's README uses a text architecture diagram instead.

## Validation boundaries (as of October 27, 2026)

The operator's live browser walkthrough reported successful sign-in/out, saved-snapshot persistence, interactive optimizers, risk charts, optional consented Groq response, price/weights/report downloads, CSV import and real Yahoo adjusted-history success. Alpha Vantage premium entitlement remained unavailable; its friendly limitation message was shown. Separate CI tests cover code paths with fixtures, not all live providers, account isolation in production or device-specific browser behavior.

No public demo credentials are provided. Ask the project maintainer for an individual account when a private evaluator needs interactive access.
