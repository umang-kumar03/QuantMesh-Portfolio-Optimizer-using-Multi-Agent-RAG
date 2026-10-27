# Streamlit Community Cloud + Neon Free

This is a **prepared and locally tested architecture**, not a live deployment.
It preserves the SQLite/JSON, Docker and paid Render modes. No account, hosted
resource, public URL or paid plan has been created. A small multi-user demo can fit
these free tiers, but there is no guaranteed 24/7 uptime or guaranteed future pricing.

## Architecture and security boundaries

Set `QUANTMESH_BACKEND=postgres` explicitly. The default remains `sqlite`.
PostgreSQL stores **all** durable application state in schema `quantmesh`:
accounts with salted scrypt hashes and revocation metadata, owner-scoped research,
login and provider request budgets, validated Alpha Vantage and Yahoo caches, and
schema version. API keys and the session-signing secret remain platform secrets,
never database rows. No JSON account file or SQLite journal/limiter is used in
PostgreSQL mode. yfinance's disposable local cookie/timezone cache is not account,
research or rate-limit storage and can safely disappear.

The existing one-hour signed sessions and record-fingerprint revocation are reused.
Account records are read afresh on authenticated reruns. Tokens stay in Streamlit
session state; a new browser/server session requires login. Expiry/revocation acts
on the next rerun, not by erasing a previously displayed static browser page.
Ownership is enforced by parameterized server queries and the authenticated UI;
this is application authorization, not database row-level security. The app server
and its database credential remain trusted. Do not share the database with
untrusted applications or expose the runtime credential to browser code.

Connections are short-lived, with no process-global pool or credential-bearing
cached connection. Non-loopback connections enforce certificate **and hostname**
verification (`sslmode=verify-full`, system CA roots). Keep Neon channel binding in
the copied URL. Connect timeout is 30s; transaction statement/lock/idle timeouts are
10s/5s/15s. A failure rolls back and returns a fixed sanitized error. There is no
automatic write retry, anonymous mode, SQLite fallback or sample substitution for
a database outage. Retry a failed operation after recovery. If a commit response
is lost, verify whether the save succeeded before retrying: automatic deduplication
of uncertain saves is not implemented.

## 1. Prepare your local operator environment

Use Python 3.12 on Linux/macOS/WSL and optionally PostgreSQL client tools for
advanced operator work. Follow your OS's official installation instructions.
From the checkout:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints.txt -e '.[dev]'
export QUANTMESH_BACKEND=postgres
```

This installs pinned psycopg and its binary driver. No paid APIs are needed.
Never place a real connection URL in a command argument, committed file or issue.
The Bash examples below prompt privately; they do not add the entered URL to shell
history. Do not enable shell tracing (`set -x`). On other shells, use their secure
process-environment or password-manager mechanism instead.

## 2. Manually create the free database

In the Neon console, explicitly select **Free**; do not upgrade, attach paid
resources or rely on time-limited trial credits. Review current terms and choose a
region near Community Cloud's available region. Use a dedicated project/database
for QuantMesh. Select PostgreSQL 17 if available (the tested server version).
Copy the **owner** direct connection URL from Connect into your private password
manager. Keep `sslmode=verify-full&channel_binding=require`; the code enforces
verify-full on remote hosts even if the URL says require or disable.

Enter the owner URL locally without printing it:

```sh
read -rsp 'Neon owner connection URL: ' QUANTMESH_DATABASE_URL
export QUANTMESH_DATABASE_URL
python -m quantmesh.pg_admin migrate
```

`migrate` creates version 1 in one transaction under an advisory lock. Repeating it
preserves data; newer/unknown versions fail. Runtime startup only checks schemas;
it never creates/migrates tables or provisions a default account. Keep the owner
URL only in the operator environment, **never in Community Cloud**.

## 3. Provision accounts (new demo) OR import existing state

For a **new database**, create individual accounts with prompted passwords:

```sh
python -m quantmesh.manage_users alice
python -m quantmesh.manage_users bob
```

Passwords must be 12–1,024 characters and are stored only as salted scrypt hashes.
There is no public registration. Do not pass `--file` in PostgreSQL mode.

For an **existing SQLite deployment**, do not provision new accounts first. Stop
all writers, retain the old configuration, and create a verified legacy backup
using the existing SQLite production environment:

```sh
python -m quantmesh.backup create --destination /absolute/private/sqlite-backup
```

The source environment must still select `QUANTMESH_BACKEND=sqlite`, multi-user
production auth, durable paths and `QUANTMESH_STORAGE_MODE=persistent-local`.
Keep the backup outside the checkout and live data directory. Then switch the
operator environment to PostgreSQL and its owner URL, run `pg_admin migrate`, and:

```sh
python -m quantmesh.pg_admin import-sqlite --source /absolute/private/sqlite-backup --app-stopped
```

Import checks backup hashes/integrity/schema, validates accounts, and atomically
copies **accounts, revocations, research ownership, request/login budgets and
caches**. It requires an entirely empty target, locks all destination data tables,
preserves research IDs and advances their sequence. Legacy unowned research stays
under reserved `local`, inaccessible to named users. Disabled owners' old research
is preserved without assigning it to someone else. Repeating an import refuses a
nonempty destination; it never merges or overwrites records. A failed import rolls
back all writes and can be retried against the same empty target.

Do not run both deployments with independent writes during cutover. Rotate the
session-signing secret at cutover and require new login. Verify row counts, account
membership, isolation and quotas before decommissioning the source. A checksum
protects against accidental corruption, not a maliciously rewritten backup.

## 4. Create a restricted web-app role

Use the owner environment from step 2 and a **new** database role name:

```sh
python -m quantmesh.pg_admin create-runtime quantmesh_app
```

The command privately prompts twice for a random **32+ character database password**
from your password manager. It creates a SQL role without administrator memberships
and grants only runtime operations in the same transaction. PostgreSQL stores the
connection password as SCRAM-SHA-256; no plaintext password row is created. It refuses an existing
role instead of silently resetting its password. Never use the owner or a role
with `neon_superuser`/other memberships as the runtime role. End-user passwords
continue to use scrypt; this separate database connection credential follows Neon’s
required password provisioning protocol over verified TLS.

**Do not substitute `psql \password`:** Neon's official SQL-role documentation says
client-hashed database passwords are unsupported. The operator helper sends the
connection password via safely quoted DDL over TLS, never command arguments,
files or application logs. PostgreSQL utility DDL cannot use ordinary bind parameters;
psycopg quotes the role/password using Identifier/Literal. Operator database-side
statement logging must remain restricted: review Neon's logging policy and do not
turn on verbose credential-bearing SQL tracing. Existing separately created safe
roles can instead receive grants without changing their password:

```sh
python -m quantmesh.pg_admin grant-runtime quantmesh_app
```

The helper refuses privileged roles, the current owner and roles with memberships.
The runtime role can read accounts/schema, read/insert journals, update bounded
caches and transact request budgets. It cannot provision/revoke accounts, edit
schema, update old research or run recovery. Schema migration, account management,
export and restore use the private owner connection instead. Re-run reviewed grants
after future schema upgrades. Use a dedicated fresh role; this command adds grants
and is not a scrubber for arbitrary pre-existing privileges.

The current deployment owner reports that the **direct Neon endpoint works** and
that the pooled endpoint timed out. Keep the functioning direct endpoint; this
release does not edit Secrets or switch endpoints. Select `quantmesh_app` in
Neon's Connect dialog if listed and use its **direct** URL for the current setup.
If the SQL-created role is absent, edit a private copy of the direct URL to use
that role's username/password while retaining the exact host, database and TLS
parameters. URL-encode special characters locally; never use an online credential
encoder. A long random alphanumeric password avoids URI-escaping ambiguity.
Never put the owner password in Cloud settings. Pooling remains supported, but
use it only after explicitly verifying network reachability from the chosen host.
No hostname is synthesized and no direct/pooler fallback happens automatically.
Connection establishment has a bounded **30-second** timeout for Cloud cold starts;
transaction statement/lock/idle timeouts remain 10s/5s/15s.

## 5. Configure Community Cloud without publishing yet

Review the PR/commit and select this GitHub repository, approved branch and
**`cloud_app.py`** as entrypoint, Python **3.12**. Root `requirements.txt` installs
the project using `constraints.txt`. `.streamlit/config.toml` retains CORS/XSRF
protection and 10 MB upload/20 MB message limits. Read the template
[secrets.toml.example](../.streamlit/secrets.toml.example).

In **App settings → Secrets**, enter these root-level TOML settings privately:

| Name | Value |
|---|---|
| `QUANTMESH_BACKEND` | `"postgres"` |
| `QUANTMESH_DEPLOYMENT` | `"production"` |
| `QUANTMESH_AUTH_MODE` | `"multi-user"` |
| `QUANTMESH_DATABASE_URL` | Working direct URL for `quantmesh_app`, not the owner; pooling optional after host-network verification |
| `QUANTMESH_SESSION_SECRET` | Stable cryptographically random 32+ character secret generated/stored in your password manager; rotate only intentionally |
| `QUANTMESH_LLM_PROVIDER` | `"groq"` (optional) |
| `QUANTMESH_LLM_MODEL` | `"openai/gpt-oss-20b"` (optional) |
| `QUANTMESH_LLM_API_KEY` | Groq key, optional until consented AI use |
| `ALPHAVANTAGE_API_KEY` | Optional; adjusted full-history entitlement may require a paid provider plan |

Do not set `QUANTMESH_STORAGE_MODE=persistent-local`, `QUANTMESH_USERS_FILE`,
`QUANTMESH_DB` or `QUANTMESH_CACHE_DB` to ephemeral paths for this mode. They are
not the PostgreSQL state store. There is no `DATABASE_URL` alias or automatic backend
inference. A missing/unknown backend or auth mode in the Cloud entrypoint denies
access. The app does not automatically load `.env`. For a local private smoke test,
use the same settings in environment variables and:

```sh
streamlit run cloud_app.py --server.address=127.0.0.1
```

Only manually launch a public service after the repository owner approves. This
PR does not supply a verified live URL. Community Cloud normally handles HTTPS;
verify its certificate, redirects and WebSockets after approved deployment.
`/_stcore/health` is Streamlit **liveness**, not database/auth readiness.

## 6. Acceptance, administration and recovery

Before sharing, use two browser sessions: unauthenticated viewers must see only
login; Alice must not see Bob's journal or exports, and vice versa. Test sample,
CSV, Yahoo history (availability/terms permitting), local RAG and both optimizers.
Groq needs explicit UI consent and remains separate from deterministic calculations.
Export downloads stay browser-local in multi-user mode, with no public media URL.

Save both users' research, reboot/hibernate the Streamlit app, and verify login and
research persistence. Test an expired/revoked session on rerun. Disable the database
connection temporarily: login/private data operations must deny access without
creating local databases; restore it and retry. Verify provider budgets and login
limits persist after a new process and, on an approved test branch, after a database
restart. Validate your actual host/network/TLS path; local tests do not establish it.

With the **owner** environment, revoke/disable access:

```sh
python -m quantmesh.manage_users alice --revoke
python -m quantmesh.manage_users alice --disable
```

The last account cannot be disabled. Never recycle usernames for different people:
old research remains owned by that name. Password changes also revoke old sessions.

Create off-platform private exports regularly (schedule according to your recovery
needs; no scheduler or storage account is provisioned):

```sh
python -m quantmesh.pg_admin export --destination /absolute/private/quantmesh-backup.json
```

Export uses one repeatable-read MVCC snapshot across all durable tables, with a
checksum and mode 0600, refuses existing destinations and exports outside the
checkout. It contains password hashes and private research: encrypt it with your
organization's approved tool, transfer to protected off-platform storage, and test
restore. Keys/DSNs/session secrets are not exported. App report exports are **not**
database backups. The built-in operator snapshot is limited to 64 MiB; for larger
data, use reviewed `pg_dump --schema=quantmesh` / `pg_restore` procedures against a
fresh isolated database, with credentials passed via protected environment/service
files rather than arguments. Those larger-database procedures are not integration
tested by this PR.

To recover, stop writers, select a **new empty database**, migrate and then:

```sh
python -m quantmesh.pg_admin restore --source /absolute/private/quantmesh-backup.json --app-stopped
```

Restore is atomic and refuses any nonempty application table. Validate users,
revocation, isolation, budgets and IDs, recreate/grant the runtime role in the new
database, switch the Cloud runtime URL, rotate the signing secret, and require login.
No automatic destructive reset/downgrade or online merge is provided. Keep a tested
backup and prior reviewed commit/image for rollback. To return to SQLite, retain
and restore the original SQLite backup/configuration; newer PostgreSQL writes are
not automatically reverse-migrated and must be separately archived/reconciled.
Do not silently discard post-cutover research by restoring an old SQLite snapshot.

## Current free-tier limits and resource exhaustion

Official source checked **2026-10-26**. Neon docs (updated 2026-10-23) currently list:

- Free: $0/month, 100 projects, 10 branches/project, **100 CU-hours/project/month**,
  autoscaling up to 2 CU, **1 GB Postgres/project** with **20 GB account-wide** cap,
  **5 GB public transfer/project/month**. Do not rely on older 0.5 GB quota articles.
- Scale-to-zero after **5 idle minutes**, cannot be disabled on Free. Short-lived
  connections allow sleeping; keepalive bots would consume compute and are not added.
  Cold starts may require a retry from the user.
- Compute/transfer exhaustion suspends compute until the next billing period or a
  manual upgrade. Storage-limit writes fail. Limits do not delete existing data;
  Free does not bill overages. Never upgrade automatically to restore availability.
- History window: **6 hours**, capped change history; **one manual snapshot**.
  Neither replaces a tested encrypted off-platform backup. No Free uptime SLA.

Community Cloud docs publish approximate February 2024 resource ranges, explicitly
subject to change: 0.078–2 CPU cores, 690 MB–2.7 GB memory, up to 50 GB disk. Disk
capacity is not persistent storage. Apps sleep after **12 hours without traffic**.
Check current console limits before deployment. Both services can sleep independently;
no 24/7 availability, recovery time, concurrency level or free-plan permanence is promised.

PostgreSQL-mode safeguards: at most 1,000 accounts; 100 journal records/owner;
256 KiB/report and 32 MiB total journal payload (new saves reject when full, never
silently erase research); 64 cache rows and 16 MiB payload/table, 2 MiB/entry.
Imported archives may exceed new-save quotas; review/archive before further saves.
Provider/login budgets persist and expired entries are pruned transactionally.
These are application limits, not a precise physical database-size cap: indexes,
row overhead, WAL, MVCC dead tuples and retained history also consume resources.
Monitor Neon usage and resource errors, export/archive research with owner-aware
operator review, and follow Neon vacuum/maintenance guidance. Global login limits
also let abusive users temporarily deny login to others; a free demo has no managed
WAF/MFA/SSO or public password recovery. Treat it as an admin-provisioned small demo,
not a security-certified financial production service.

References:
[Neon plans](https://neon.com/docs/introduction/plans),
[Free quotas](https://neon.com/faq/free-plan-limits-and-quotas),
[TLS](https://neon.com/docs/connect/connect-securely),
[Pooling](https://neon.com/docs/connect/connection-pooling),
[SQL roles and password requirements](https://neon.com/docs/manage/roles#manage-roles-with-sql),
[Streamlit resources/hibernation](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).
Verified Neon source snapshot:
[plans](https://github.com/neondatabase/website/blob/36e4c506cb373d9928768d0b61ca54857cbc53f6/content/docs/introduction/plans.md),
[quotas](https://github.com/neondatabase/website/blob/36e4c506cb373d9928768d0b61ca54857cbc53f6/content/faqs/free-plan-limits-and-quotas.md).
Provider eligibility and future terms remain the owner's responsibility.

### Windows certificate trust

If system CA verification fails locally but a trusted CA PEM bundle succeeds,
set `QUANTMESH_SSLROOTCERT` to its absolute PEM path in your private local
PowerShell environment. For example, with certifi installed:

```powershell
$env:QUANTMESH_SSLROOTCERT = .\.venv\Scripts\python.exe -c "import certifi; print(certifi.where())"
```

Certificate and hostname verification remain required (`verify-full`). Do not
copy a Windows CA path into Streamlit Cloud secrets.

### Cloud TLS startup failures

Use the [verified TLS diagnostic guide](postgres-tls.md). Blank/unset CA settings
already use the pinned Certifi bundle. The fixed startup code distinguishes CA
files, issuer chains, hostname mismatch, certificate dates, channel binding and
network errors without showing credentials. No universal Secret edit or reboot
is prescribed. Explicit `system` now means native libpq roots.
