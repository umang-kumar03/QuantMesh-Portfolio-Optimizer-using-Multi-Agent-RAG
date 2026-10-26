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

## Private production deployment follow-up

- Full suite: **122 tests passed** including production guard, bootstrap persistence,
  private browser-local exports, salted hashing, explicit account revocation/removal,
  concurrent provisioning/journal writes, WAL/schema versioning, restart login gating,
  owner isolation, online backup and corruption/non-overwrite restore checks.
- Ruff passed; pip check passed; 54 pinned dependencies audited with no known advisories.
- Production image rebuilt successfully. Direct image startup without signing credentials
  refused to serve. A non-root UID 10001 integration check validated actual launcher/
  health, authenticated UI, isolated records, private exports and server restarts.
  The check passed again in a newly created container attached to the same local
  Docker volume, preserving accounts and research; the temporary volume was removed.
- Render YAML parsed and local single-instance/disk/startup assertions passed. Compose
  configuration syntax passed with temporary fixture settings. Neither is a Render
  control-plane validation or a live HTTPS deployment test.
- Render docs HTTPS access was blocked in this environment; current provider controls,
  pricing/availability, Blueprint acceptance, live TLS/disk tests, browser download
  compatibility and offsite backup transfer remain manual deployment prerequisites.
- No hosting service, paid disk, public URL or public deployment was created.


## Free-hosting compatibility follow-up

- Full suite: **128 passed** on Python 3.12.14; all existing Yahoo, Groq, RAG,
  optimization/backtesting and authentication tests retained. New cases reject
  missing/empty/ephemeral/unsupported storage declarations before file creation,
  and verify login limits, revoked tokens, accounts and journal isolation in a
  fresh interpreter. External API responses remain mocked; no real keys required.
- Ruff, pip check and git diff --check passed. All 54 pinned dependencies audited:
  no known vulnerabilities reported by pip-audit (not a security certification).
- Actual production launcher returned HTTP 200 `ok` before and after a local restart
  with fixture accounts; removal of the bootstrap file did not lose accounts.
  Explicit ephemeral mode exited with status 1 before serving. Temporary local
  test storage does not establish any hosting provider's disk durability.
- Render local YAML structure and resolved Docker Compose checks passed: paid disk
  retained, one instance, multi-user mode, explicit persistent-local declaration,
  named data volume and localhost-only binding. No provider control-plane or TLS
  validation, ARM build, real VM reboot or live free hosting was performed.
- Official GitHub documentation provided Streamlit/Hugging Face hosting evidence;
  direct provider documentation URLs returned proxy 403. Unretrieved current plan
  quotas are explicitly unverified in free-hosting.md. No hosted resources/accounts
  were created and no public deployment was performed.


## Complete PostgreSQL / Community Cloud follow-up (2026-10-26)

- **154 tests passed**, zero skipped, on Python 3.12.14 with a real disposable
  PostgreSQL 17 server. CI now supplies PostgreSQL 17 for both Python 3.11/3.12
  matrix jobs. Local runs without QUANTMESH_TEST_DATABASE_URL intentionally skip
  real-DB cases; fixtures refuse databases not explicitly named *_test.
- Coverage includes concurrent account updates/revocations, two-user isolation and
  logout, password hashing, session expiry, persisted login/provider limits under
  concurrency, schema repeatability/newer-version refusal, real restricted-role
  grants, all-or-nothing SQLite full-state import, snapshot recovery/ID sequences,
  transaction rollback, terminated-connection recovery, and fail-closed UI/storage
  errors. Yahoo, Alpha and Groq network responses are mocked; all previous analytics,
  CSV/export, RAG, optimization/backtesting and SQLite production tests remain.
- Actual restricted **login-role** connection (separate from the owner), guarded
  Cloud entrypoint/login gate and local HTTP health passed. Restarting the local
  PostgreSQL container preserved accounts and isolated research and reconnected
  successfully. Runtime DDL was denied. No real Neon credential was used.
- Ruff, pip check and git diff --check passed. The initial security audit found
  newly reported advisories in existing Certifi/Pillow pins. Updated Certifi to
  2026.10.19 and Pillow to 13.0.0; Streamlit 1.66.1 is required for Pillow 13
  compatibility. New transitive server dependencies are pinned. Final pip-audit:
  **62 pinned packages, no known vulnerabilities**; dependency-audit.json refreshed.
  Existing AppTest checks now use absolute paths for Streamlit's changed path
  resolution; no assertions were removed.
- Free-tier facts were checked in Neon's official public source (plans updated
  2026-10-23). No live Neon/Community Cloud deployment, hosted TLS/network acceptance,
  actual cloud quotas/eligibility or public URL was verified. The guide names those
  remaining gates and no Free uptime guarantee is claimed.

- Rebuilt the Python 3.12 Linux **offline production image** with current pinned
  wheels. Missing signing configuration failed before serving. Non-root UID 10001
  SQLite/JSON auth, private exports, journal isolation and server restarts passed
  twice in recreated containers on the same local Docker volume. Temporary files
  used tmpfs after the workspace VFS layer exhausted disk; this was an environment
  capacity issue. No host ports were exposed. ARM/native provider builds remain
  unverified. Streamlit secrets, .env variants and custom SQLite files are excluded
  from Docker build contexts.
