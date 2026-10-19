# ◈ QuantMesh

**Portfolio research with transparent analytics, optional market history and grounded AI explanations.**

The existing portfolio dashboard now supports cached Alpha Vantage and Yahoo Finance adjusted daily
history, optional OpenAI/Groq research explanations, and private multi-user accounts.
It still runs immediately with deterministic synthetic data and no service keys.

## Run locally

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints.txt -e '.[dev]'
streamlit run app.py --server.address=127.0.0.1
```

Default mode is private single-user. Do not expose that mode publicly. Prepared
Docker Compose configuration requires provisioned multi-user authentication.
See [production deployment](docs/production-deployment.md) and the
[auth audit](docs/auth-audit.md) before sharing an instance. Render configuration
is provided for one paid instance with a persistent disk; no resources are created.
Production startup is `python -m quantmesh.serve`, never public single-user mode.
The prepared Groq deployment model is `openai/gpt-oss-20b`.

## Features

- Four separate sources: Sample market, Upload CSV, Alpha Vantage and Yahoo Finance.
- Yahoo Finance via pinned yfinance needs no API key; explicitly adjusted prices,
  strict missing-data validation, cached histories and clearly labeled fallback.
- Persistent historical cache, request budgets, freshness/provenance, bounded stale
  reuse, and clearly labeled sample fallback on service failure.
- Minimum-variance / maximum-Sharpe optimization with weight caps and training-only estimates.
- Chronological buy-and-hold holdout versus equal weight, explicit costs, risk and return charts.
- Deterministic specialist agents and cited local methodology retrieval.
- Optional AI explanation: explicit consent, supplied-fact citations, exact-quote
  validation, and clear separation from authoritative numerical analytics.
- CSV/JSON export and an owner-scoped SQLite research journal.
- Provisioned scrypt accounts, expiring/revocable sessions and persistent login throttling.

CSV: `Date,Asset A,Asset B,...`, ascending unique daily dates, 2–30 assets,
61–10,000 observations, positive finite adjusted prices, no missing values.
Use consistent currencies and verify corporate-action adjustments.

## Optional credentials

| Capability | Configuration |
|---|---|
| Adjusted daily historical prices | `ALPHAVANTAGE_API_KEY` with `TIME_SERIES_DAILY_ADJUSTED`/full-history plan entitlement (normally premium) |
| Generated explanation | `QUANTMESH_LLM_API_KEY`, `QUANTMESH_LLM_PROVIDER=openai` or `groq`, optional `QUANTMESH_LLM_MODEL` |
| Private multi-user access | `QUANTMESH_AUTH_MODE=multi-user`, protected `QUANTMESH_USERS_FILE`, raw random `QUANTMESH_SESSION_SECRET` (32+ characters) |

Provision accounts using `python -m quantmesh.manage_users USER --file /absolute/private/users.json`.
Passwords are securely prompted, never supplied as command arguments. Never commit
credentials; `.env.example` documents names only. The app does not load `.env`
automatically. Provider requests need allowed outbound HTTPS destinations and
account/model permissions. No API key is required for sample/CSV deterministic research.

Groq troubleshooting and local verification: [deployment guide](docs/deployment.md#verify-groq-explanations-locally).

## Checks

```sh
pytest -q
ruff check .
python -m pip check
```

CI tests Python 3.11/3.12 and audits pinned dependencies. See
[actual validation results](docs/validation.md); live paid API success is not
claimed when credentials or network access are unavailable.

## Documentation

[Architecture](docs/architecture.md) · [Requirements](docs/requirements.md) ·
[Historical data sources](docs/data-sources.md) · [Research and attribution](docs/research.md) · [Roadmap](docs/roadmap.md) ·
[Deployment](docs/deployment.md) · [Security](docs/security.md)

No trade execution or public deployment. Historical results do not predict future
returns. AI explanations may be wrong even when their quoted evidence matches;
local methodology sources are not live financial news or investment recommendations.
