# Security review

## Authentication and data isolation

Default single-user mode is restricted by operational policy to private loopback
use. The prepared Compose deployment enforces multi-user mode, account-file and
session-secret requirements. Authentication is checked **before** data uploads,
provider calls, analytics, journal reads or exports. Unknown modes and missing or
malformed required configuration fail closed. No public registration is available.

Provisioned passwords use scrypt (N=16384, r=8, p=1), a random 16-byte salt and
constant-time digest comparison. Password length is bounded and failed-login errors
do not reveal account existence. Persistent SQLite budgets cap each username at
5 attempts/minute, 100/day and the instance at 30/minute, 1000/day (successful
attempts count too). This limits brute force; it can still be abused for denial
of service. Add network access controls and proxy rate limits for remote operation.

Signed session tokens stay in server-side Streamlit session state, expire after
one hour and are bound to the current password-record fingerprint. Account removal,
password replacement and signing-key rotation revoke sessions at the next rerun.
Sign-out clears all session state. A raw secret with at least 32 random characters
is required; never use a network-secret placeholder for HMAC. Sessions are not
persisted or placed in custom browser cookies.

Each journal operation uses the server-authenticated owner in parameterized SQL.
Legacy rows migrate to the reserved `local` owner and cannot be claimed by named
accounts. Raw CSV uploads remain in the user's Streamlit session. Saved summaries
remain private to their owner. Provider history cache is intentionally shared
within the instance and must contain only licensed provider data, never uploads.
Operators with filesystem access can read all databases; no encryption-at-rest or
protection from a compromised server process is claimed.

## Provider and model boundary

- Only fixed HTTPS Alpha Vantage, OpenAI and Groq API URLs are allowed by code;
  arbitrary endpoint configuration is rejected. Redirects are disabled to prevent
  forwarding credentials to a different host. TLS verification stays enabled.
- Requests have connect/read timeouts and a 5 MB decompressed-response cap. Error
  messages omit raw provider bodies, URLs, API keys and request exception text.
  Error-body inspection is capped at 64 KiB and retains only allowlisted constant
  codes; arbitrary provider messages, failed generations and unknown codes are
  discarded. HTTP status remains available for troubleshooting.
- Atomic persistent budgets cap Alpha Vantage at 5/minute and 25/day, LLM at
  3/minute and 50/day across the instance. Budgets are deliberately conservative;
  actual account restrictions may be stricter. Provider 429/entitlement errors are
  handled without general automatic retries. One explicitly disclosed, budgeted Groq
  recovery is allowed only for known HTTP 400 JSON-generation codes; recovered
  output must pass the same citation validation. Authentication, access, model,
  rate-limit, timeout and server failures are not automatically retried.
- Provider history must contain matching symbol metadata and positive finite
  adjusted prices. History is aligned on the intersection of dates without fills.
  Cache freshness, stale fallback, synthetic substitution and provenance are visible.
- LLM use requires an explicit button and consent to sending the question, computed
  summary metrics and selected local methodology. No tickers, raw prices or saved
  journal records are sent automatically; a user can still disclose them in a question.
- Generated output cannot edit calculations, allocations or records. Citation IDs
  must exist in the supplied source set and quoted excerpts must match exactly;
  malformed schema, invented IDs/quotes and external URLs are discarded. Only
  server-owned source labels are displayed. Generated explanations are rendered as
  plain text, explicitly unverified, and must not be treated as financial facts.
  Quote/identity validation is **not semantic entailment verification**. Prompt
  injection and hallucination remain model risks despite strict instructions.

## Other controls and limits

Uploads are bounded to 10 MB, 10,000 daily rows and 30 assets, with strict numeric,
date and missing-value validation. No arbitrary code, pickle or URL ingestion.
Spreadsheet-formula prefixes in CSV labels are neutralized. SQLite connections
close reliably. Untrusted content never enters unsafe HTML. Streamlit's default
CSRF/CORS protections remain enabled. Container images run non-root; credential
files are mounted read-only and excluded from build contexts and version control.

Small private single-instance groups are supported. No MFA, SSO, self-service
password recovery, per-user provider billing, immutable audit log, managed backup,
formal penetration test or multi-replica database support is claimed. Use a TLS
reverse proxy, access policy, resource quotas and protected backups before hosting.
No public deployment occurs without owner approval.

The dependency audit covers pinned Python packages, not base-image OS packages.
See `docs/validation.md` for actual checks and `dependency-audit.json` for the scan.
Repeat audits and container scanning before release. Never paste credentials into
chat, issues, commits or pull-request comments.

## Yahoo Finance boundary

No Yahoo API keys, personal login sessions, arbitrary URLs or new authentication
paths are introduced. Safe ticker/date inputs are passed only to yfinance's fixed
daily-download API. Explicit adjusted-price extraction rejects Close-only data,
missing assets, incomplete observations and conflicting duplicate dates. Cached
frames are revalidated and bounded in a separate table. Raw uploads are never cached.

The yfinance/curl transport is distinct from the direct requests-based API helper:
its cookie negotiation and HTTP behavior are owned by the pinned library. TLS
verification is not disabled. Per-call yfinance logs are suppressed only for the
calling thread, with rate-limit classification retained; no raw exceptions, cookie
values or responses are returned to the UI. Library-generated Yahoo cookie/timezone
files live beside the configured cache, outside Git and container build contexts.
The five-per-minute/25-per-day budget counts logical downloads, not each internal
HTTP request. Yahoo availability, personal-use/redistribution terms and revision
bias require operator review. Existing user isolation and LLM disclosure rules
remain in effect, and no public deployment is authorized.

## Production deployment hardening

Read auth-audit.md for findings and production-deployment.md for operational gates.
Direct images and the hosted service now start through a fail-closed launcher that
requires multi-user auth, private provisioned accounts, raw session signing and
validated disk paths before binding a port. The UI separately rejects production
single-user mode. No plaintext credentials are put in DBs. Alpha caching retains
only validated prices and required identity, not arbitrary provider metadata.

Multi-user downloads use escaped, base64 browser-local links inside the authenticated
WebSocket UI instead of Streamlit media capability URLs. No download data enters a
public server media route. This preserves exports but cannot prevent authorized
users retaining files; browser compatibility must be checked before hosting.
WAL/full-sync, lock waits, version checks, atomic account updates and verified
backup/restore improve persistence; they do not establish actual hosting durability
or automatic offsite backups. Streamlit expiry/revocation applies on reruns, not
instant erasure of a static browser view. A fresh server session requires re-login.
Render HTTPS, Blueprint control-plane acceptance and live storage must still be
verified after approval; no claim of a tested public deployment or complete
production security certification is made.

## Explicit PostgreSQL backend

`QUANTMESH_BACKEND=sqlite` (default) preserves existing JSON accounts, SQLite data,
Docker/Render durable-disk startup and backup procedures. SQLite production still
requires `QUANTMESH_STORAGE_MODE=persistent-local`. `QUANTMESH_BACKEND=postgres`
requires multi-user mode and a private `QUANTMESH_DATABASE_URL`; it stores accounts,
revocation, owner-scoped research, all login/provider budgets and validated market
caches in PostgreSQL. It never falls back to JSON, SQLite or single-user access.
`cloud_app.py` separately requires explicit postgres/production/multi-user settings
before loading the dashboard. Database failures stop access; provider sample fallback
cannot mask a storage outage. Schema/account provisioning is operator-only, not a
runtime migration or public registration flow.

See [Community Cloud + Neon](neon-community-cloud.md) for exact secrets, TLS,
restricted role grants, free-tier quotas, import/export/restore and residual risks.
Connections use certificate/hostname verification remotely, bounded timeouts and
transaction-scoped locks. Application owner predicates remain mandatory; DB row-level
security is not implemented. Secrets belong in platform settings, never Git or DB
rows. No hosted TLS/disk/network/uptime assurance is claimed from local tests.

Docker build contexts exclude `.streamlit/secrets.toml`, `.env` variants and custom
SQLite files. The Cloud template deliberately leaves the signing secret empty so
a copied template cannot start with a publicly known placeholder signing key.
