# Validation record

Validated in the connected Linux cloud workspace using Python 3.12.14.

| Check | Actual result |
|---|---|
| `pytest -q` | **52 passed** |
| `ruff check .` | Passed |
| `python -m pip check` | No broken requirements |
| Pinned dependency audit | 43 packages; no known advisories reported |
| Fresh Streamlit startup | Health HTTP 200 `ok`; application HTML HTTP 200 |
| Existing analytics/UI regression tests | Passed |
| Provider contracts, cache, stale/sample fallback and quota tests | Passed using controlled HTTP responses |
| Grounded model output / fabricated citation rejection | Passed using controlled HTTP responses |
| Authentication / session / owner isolation / legacy migration | Passed |
| Non-root rebuilt container | Built successfully via host-wheel route |
| Container integrated smoke check | UID 10001, real server health, gated login, rendered authenticated dashboard and isolated SQLite write passed |
| Compose with temporary test settings | Configuration syntax passed |
| Compose without required authentication settings | Rejected as intended |
| Python 3.11 CI matrix | Configured; not executed in this workspace |
| Standard Docker package-network build | Builder DNS/proxy unavailable; verified host-wheel fallback used |
| Live Alpha Vantage and paid LLM calls | Unrun: keys absent and provider HTTPS destinations denied by current network policy |
| GitHub API inspection | Denied by current proxy policy (HTTP 403); Git read access succeeded |
| Public deployment | Not performed; requires separate owner approval |

Tests include an independent analytical minimum-variance allocation, portfolio
feasibility, future-data isolation, buy-and-hold equity, benchmark costs, initial
drawdown, zero-volatility reporting, strict JSON, spreadsheet-formula neutralization,
parameterized persistence and safe account scoping. New UI tests exercise missing
provider keys, explicit sample provenance, AI consent/failure handling, real password
login, private journal access and sign-out. HTTP tests reject oversized responses,
redirects, invalid payloads and leaked credentials. Concurrent budget reservations
are checked for atomicity.

The Python audit is recorded in `dependency-audit.json`; it is time-dependent and
does not cover OS packages or prove absence of security defects. No paid API call,
remote CI run, successful push or PR creation is inferred from local test success.
GitHub publication outcomes are reported explicitly after the actual attempts.

## Groq integration fix

The generic HTTP error discarded the status and structured code, so it could not
diagnose the reported chat rejection. The endpoint and JSON-object mode were
confirmed against the official Groq SDK contract; deprecated max_tokens was
replaced with Groq's max_completion_tokens. Known JSON-generation failures have
a single budgeted recovery, with unchanged grounding validation. Live behavior
is unverified because this workspace has no Groq credential. No real key is used
by automated tests. Follow-up validation: **74 tests passed**, Ruff passed, pip check
reported no broken requirements, and git diff --check passed. Regression coverage
includes all requested HTTP statuses, sensitive-body redaction, Groq payloads,
bounded recovery, truncation, timeouts and Streamlit error/recovery presentation.

## Yahoo Finance follow-up

- Full suite: **103 passed** (29 new Yahoo adapter/integration/UI cases), without
  internet or credentials for automated tests.
- Ruff passed; pip check reported no broken requirements; constraints now include
  yfinance 1.7.0 and all its additional transitive runtime dependencies.
- Pinned dependency audit: 54 packages, no known advisories reported (see JSON artifact).
- Controlled downloads cover flat and both MultiIndex orders, explicit adjusted-price
  extraction, missing/empty/unadjusted/nonfinite data, invalid/duplicate dates,
  input errors, network/rate failures, fresh/expired cache, explicit sample fallback,
  provider session separation, both optimizers, existing agents and consented Groq output.
- Actual Yahoo fetch with fallback disabled returned no history. Connectivity probes
  to query1/query2.finance.yahoo.com, fc.yahoo.com and guce.yahoo.com were denied
  by proxy HTTP 403. **Live Yahoo prices remain unverified in this environment.**
- Existing authentication and journal-isolation code were not changed. No public deployment.
