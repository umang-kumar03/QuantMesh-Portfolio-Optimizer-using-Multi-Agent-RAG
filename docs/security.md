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
- Atomic persistent budgets cap Alpha Vantage at 5/minute and 25/day, LLM at
  3/minute and 50/day across the instance. Budgets are deliberately conservative;
  actual account restrictions may be stricter. Provider 429/entitlement errors are
  handled without automatic retry loops or silent extra paid calls.
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
