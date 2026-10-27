# QuantMesh end-to-end audit — 2026-10-27

Scope: the current main implementation plus this review branch. The owner reports
that the live direct Neon endpoint, testuser1 login, dashboard, metrics and charts
work, while the pooled endpoint timed out. This audit preserves that direct
endpoint and the intended 30-second connection timeout. No production credentials,
accounts, passwords, research, or Secrets were read or modified. No migration,
merge, public deployment, paid service or external account was performed.

## Results and evidence boundaries

| Feature | Test result | Fix applied | Live verified |
|---|---|---|---|
| Minimum variance / maximum Sharpe | Independent diagonal solutions, binding/exact-feasible caps and solver postconditions pass | Reject invalid returns, overflowed estimates and nonfinite/out-of-bounds solver results | No; deterministic fixtures |
| Return / CAGR / volatility / Sharpe / drawdown / VaR | Independent cashflow/statistical calculation passes, including initial loss | Reject unrepresentable wealth/annualization; validate risk-free rate consistently | No; deterministic fixtures |
| Chronological holdout / costs / benchmark | Both objectives and 50/70/85% splits tested with mutated future prices; no weight leakage. Buy-and-hold and equal-weight cost checks pass | Existing methodology preserved | No; deterministic fixtures |
| Training, cap, risk-free, costs, initial capital controls | All five tabs/four chart specs render in AppTest; exported weights/metrics and chart wealth match independently recomputed results after control changes | Existing calculations preserved | No real browser/viewport test |
| Sample and CSV ingestion | Real parser/UI paths, empty/malformed input, date/price boundaries, deterministic samples and upload validation pass | Explicit sample provenance; CSV provenance remains unverified instead of implying real data | No; uploader object supplied by fixture |
| Alpha Vantage / Yahoo / cache / fallback | Mocked provider, malformed data, bad symbols/dates, durable cache, budgets, missing key and synthetic fallback tests pass | No provider changes; fallback remains explicit and portfolio-wide | Live Yahoo attempt returned no history; Alpha key absent |
| Research agents / retrieval / citations | Allocation/risk/validation/synthesis and unmatched-query abstention pass | Existing fixed methodology corpus preserved | No live financial-research claim |
| Groq / OpenAI | Mocked endpoints, provider failures, malformed/truncated output, rejected fabricated IDs/quotes and consent UI pass | Cloud bootstrap no longer inserts empty optional configuration that masks the provider default | No provider keys available |
| Price/weight CSV and JSON reports | Numeric round trips, metadata/parameters, strict JSON and export-to-journal equality pass | Complete date bounds/counts; protect text cells, string/multilevel indices and index names from formula injection | No native browser download verification |
| Private export transport | Authenticated UI sends three base64 download documents in iframe srcdoc, without public media routes | Replace deprecated components HTML API with supported st.iframe; keep escaping/type/filename guards | Local actual UI fixtures only |
| testuser1 / two-user isolation / journal / logout | Fresh testuser1 password in disposable PostgreSQL; save, new login/reopen and logout pass. Other users cannot see its journal | Blank-name validation and useful sanitized service/quota errors | Owner reports production login; not independently tested here |
| Sessions / revocation / account concurrency / restricted role | Existing expiry, revocation, disable, salted hashing, concurrent updates and real restricted-role tests pass | No security controls weakened | Disposable PostgreSQL only |
| Persistence / outage / recovery | Real local PostgreSQL stop/start retains accounts, journals, revoked sessions and request budgets. Outage denies access and reconnect succeeds using restricted quantmesh_app | Existing storage design preserved | No production DB restart or writes |
| TLS / deployment / startup | verify-full/SNI/fail-closed tests pass; actual local Streamlit HTTP health and authenticated Cloud entrypoint pass | Stale timeout test updated from 10 to 30; guide/template preserve direct endpoint | Public app request blocked by workspace egress proxy |

All automated provider responses are mocked; no paid API request was made.
The separate key-free live Yahoo attempt used fallback=False and returned no
history, including after an escalated retry. It is not recorded as a successful
provider test. Production database, Groq and Alpha credentials were absent.
The public Streamlit request failed at the workspace proxy with HTTP 403, including
an escalated retry. This is **not** evidence that the owner's working app is down.

## Discovered bugs and exact fixes

1. **Stale timeout expectation:** main intentionally uses connect_timeout=30 while
   its regression expected 10. Update the test, preserve runtime behavior and the
   separate existing transaction/lock/TLS-probe timeouts.
2. **Nonfinite performance from finite inputs:** cumulative wealth/CAGR could
   overflow and drawdown become NaN without rejecting input. Guard arithmetic,
   reject unrepresentable results and preserve the intentional undefined Sharpe
   for zero volatility. No metric is silently replaced by a plausible number.
3. **Standalone risk-free validation gap:** performance accepted invalid risk-free
   rates even though optimize rejected them. Reuse the same finite 0–25% boundary.
4. **Optimizer validation gaps:** economically invalid returns and overflowed
   estimates could reach the solver; solver success alone did not check every
   weight's finiteness/bounds. Validate inputs/estimates and all allocation
   postconditions. A mocked dishonest solver result is rejected rather than fixed
   by silently clipping weights.
5. **CSV formula protection gaps:** escaping covered only column labels and object
   indices. Protect all text cells, string/multilevel indices and index names,
   while preserving numeric values and caller data. JSON report content remains
   strict data, not spreadsheet formulas.
6. **Incomplete report provenance:** reports lacked complete data bounds/counts;
   primary sample/CSV provenance was empty. Add data_start/data_end/observations/
   asset_count and explicit sample seed/synthetic metadata. Uploaded CSV origin is
   explicitly unverified. Primary samples are not mislabeled as provider fallback.
   These additive schema-v1 fields do not rewrite old journal records.
7. **Unhelpful journal errors:** safe backend/quota messages were discarded as
   generic storage-permission failures. Display the sanitized ServiceError only;
   keep OS/SQLite/raw errors generic. Reject blank names at the UI and bound their
   length, with no write on validation failure.
8. **Missing optional AI bootstrap settings:** absent variables were inserted as
   empty strings, masking the documented default provider and producing a provider
   error instead of a missing-key error. Preserve absence, validate provided
   settings and retain all explicit provider/model/key configuration.
9. **Deprecated private-export API:** components.v1.html emitted a removal warning.
   Use st.iframe with trusted constant/escaped/base64 HTML srcdoc, preserving
   browser-local authenticated exports and avoiding media-file capability URLs.
10. **Deployment guide mismatch:** previous guidance/template preferred pooling.
    Document the owner's working direct endpoint and 30-second timeout; pooling
    is optional only after explicit reachability verification. No runtime endpoint
    is synthesized, changed or retried through an alternative hostname.

## Verification commands and scope

Run the full suite against a disposable PostgreSQL database named *_test using
QUANTMESH_TEST_DATABASE_URL. The fixture resets only that explicitly selected test
schema and refuses a database without the suffix. Never point this variable at
production. Tests need no real API credentials. Existing GitHub Actions supply
PostgreSQL 17 and test Python 3.11 and 3.12.

```sh
pytest -q
ruff check .
python -m pip check
pip-audit --disable-pip --no-deps -r constraints.txt --progress-spinner off
```

Local final result: **236 passed, 0 failed, 0 skipped**, Python 3.12.14 with real
PostgreSQL 17 and local TLS fixtures. Ruff, pip check and git diff --check passed.
Fresh security audit: 62 pinned packages, no known advisories. This is not a
formal penetration test, dependency-integrity certification or load test.

Separate smoke checks passed: actual PostgreSQL stop/start with revocation and
request-budget persistence; actual restricted quantmesh_app reconnection; actual
loopback Streamlit health plus authenticated Cloud UI and private export srcdoc.
Health alone is not authentication readiness. These are local isolated fixtures,
not a live Neon/Community Cloud verification. Real browser/mobile layout, browser
CSV-download interaction, long-running load, live external API success, actual host
TLS/network/billing policies, and off-platform backup operations remain unverified.

## Release and remaining setup

Review the PR and its CI results before applying it to main. No automatic merge or
public deployment is authorized by this audit. The current working production
Secrets and direct endpoint should remain as configured; no key/Secret change is
needed for these fixes. Optional provider use still requires the documented Groq/
OpenAI key and Alpha adjusted-data entitlement. No credentials should be posted
in issues, comments, logs or chat.

After an owner-approved merge, verify the live login page, five tabs, a small
owner-scoped saved snapshot and private exports using authorized accounts, plus
browser responsiveness. Do not restart/reset production data to repeat the local
fixture tests. Follow deployment/security documentation for backups, quotas,
Streamlit session limitations and free-tier hibernation; no 24/7 guarantee is added.
