# QuantMesh requirements

## Project discovery

The original connected repository described a multi-agent RAG portfolio optimizer
and financial analysis application. Its remote `main` contained only README at
4788cf01166fdb03cbee0acd96101b3fb065c3af. The locally developed dashboard, engine,
SQLite journal, research agents, tests and Docker files are preserved and extended.

## Delivered acceptance criteria

- Offline synthetic sample mode and strict daily adjusted-price CSV ingestion.
- Optional documented Alpha Vantage adjusted full-history integration with symbol
  metadata validation, finite-price checks, persistent caching and request budgets.
- Six-hour freshness, bounded seven-day stale reuse, visible provenance and explicit
  whole-portfolio sample fallback; no mixed synthetic/live dataset.
- Existing long-only minimum variance / maximum Sharpe optimization, caps, chronological
  holdout, equal-weight comparison, initial costs, interactive financial charts and metrics.
- Deterministic specialist agents and methodology retrieval remain usable without keys.
- Optional OpenAI/Groq explanation, configurable accessible model, explicit consent,
  schema/known-ID/exact-quote validation and visibly unverified generated interpretation.
- No invented external publication labels or model-selected source URLs.
- Provisioned multi-user authentication before research execution, expiry/revocation,
  login budgets, sign-out cleanup and owner-scoped journal reads/writes.
- Local legacy journals migrate without assigning their records to named users.
- CSV/JSON reports preserve data fingerprint, parameters, split and provider provenance.
- Loading/error states, safe provider failures, secure secret configuration, tests,
  CI, non-root images and private deployment preparation.

## Boundaries and external prerequisites

Market integration fetches end-of-day adjusted history, not intraday/tick quotes.
Alpha Vantage's adjusted endpoint normally requires premium plan entitlement.
Live market and LLM provider behavior must be checked after keys and HTTPS egress
are configured. Controlled-response contract tests are not a claim of paid API success.

No trade execution, external financial-news ingestion, arbitrary document ingestion,
Excel parser, MFA/SSO, self-service account recovery, multi-replica persistence or
public deployment is included. CSV is the supported spreadsheet interchange format.
Model explanations may be wrong despite valid quotations; they cannot change metrics.
Deploy to a private single instance with TLS/access policies and protected backups.
