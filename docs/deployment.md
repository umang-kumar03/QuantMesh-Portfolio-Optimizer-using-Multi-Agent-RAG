# Deployment and operations

## Local development (no credentials needed)

Use Python 3.11 or 3.12; Python 3.12 is recommended for container builds.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints.txt -e '.[dev]'
pytest -q
ruff check .
python -m pip check
streamlit run app.py --server.address=127.0.0.1
```

Default `QUANTMESH_AUTH_MODE=single-user` is for a private loopback workspace.
Never expose this mode to untrusted users. The application does not automatically
load `.env`; export variables through secure environment settings/process manager.
Compose itself reads a local `.env` for interpolation; never commit that file.

## Optional services and exact configuration

| Variable | Purpose / requirements |
|---|---|
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage key with **TIME_SERIES_DAILY_ADJUSTED** and full-history entitlement (normally premium). Free key availability does not establish access to this endpoint. |
| `QUANTMESH_LLM_PROVIDER` | `openai` or `groq` |
| `QUANTMESH_LLM_MODEL` | Optional accessible chat model; defaults to `gpt-4o-mini` for OpenAI or `llama-3.3-70b-versatile` for Groq. Must support JSON object output. |
| `QUANTMESH_LLM_API_KEY` | Key for the selected provider with access/billing for that model. Never use a key for a different provider. |
| `QUANTMESH_AUTH_MODE` | `single-user` (local only) or `multi-user` (private shared service) |
| `QUANTMESH_USERS_FILE` | Absolute protected account file in multi-user mode |
| `QUANTMESH_SESSION_SECRET` | Raw cryptographically random secret, at least 32 characters, for local HMAC. Proxy placeholder secrets cannot sign sessions. |
| `QUANTMESH_DB` | Owner-scoped SQLite research journal; default `.quantmesh/research.sqlite3` |
| `QUANTMESH_CACHE_DB` | Shared provider cache and persistent request/login budgets; default `.quantmesh/market.sqlite3` |
| `QUANTMESH_USERS_FILE_HOST` | Compose host path to the private account file |

Allow HTTPS to `www.alphavantage.co`, and to `api.openai.com` or `api.groq.com`
as selected. GitHub PR creation additionally needs `api.github.com`. Normal
sample/CSV research requires none of these service keys or destinations.

Authoritative API contracts:
[Alpha Vantage adjusted daily](https://www.alphavantage.co/documentation/#dailyadj),
[OpenAI chat completions](https://platform.openai.com/docs/api-reference/chat),
[Groq OpenAI compatibility](https://console.groq.com/docs/openai).
Provider documentation and entitlement may change; validate on your account.
The cloud network blocked live provider/API checks during implementation.

## Provision private multi-user access

Accounts are provisioned by the operator; there is no public registration.
Run from an activated environment. The CLI prompts securely for passwords and
confirmation, writes salted scrypt hashes atomically, and refuses a credential
file inside the checkout. `local` is reserved for pre-authentication legacy data.

```sh
python -m quantmesh.manage_users alice --file /absolute/private/quantmesh/users.json
python -m quantmesh.manage_users bob --file /absolute/private/quantmesh/users.json
```

Protect the directory as well as the file (CLI uses mode 0600). For Docker, the
file must be readable by container UID 10001: set its ownership or an appropriate
host ACL to that UID without making it world-readable. Mount it read-only;
Compose refuses to create a missing path. Provision changes on the host, then
restart the container to refresh a bind mount after the CLI's atomic replacement.

Generate a high-entropy session secret using a password manager or a secure local
secret-generation command, place it directly in your secret manager, and export
it as `QUANTMESH_SESSION_SECRET`. Do not use an example string from documentation.
Set `QUANTMESH_AUTH_MODE=multi-user` and `QUANTMESH_USERS_FILE` for non-container
multi-user operation. Missing/malformed configuration blocks all research access.
Sessions expire after one hour. Replacing a user's password hash, removing the
user, or rotating the session secret revokes access on the next application run.
Sign-out clears all current session research/upload state.

## Container deployment preparation

Set the required authentication variables securely, then:

```sh
docker compose config --quiet
docker compose up --build -d
docker compose logs quantmesh
```

Compose binds only loopback, requires multi-user authentication configuration,
mounts the account file read-only, and retains journal/cache in a named volume.
Never dump `docker compose config` or container environment: they can contain
real secrets. TLS and authenticated access policies must be configured on your
reverse proxy before remote use. Forward WebSockets and preserve Streamlit's
CSRF/CORS protections. No public deployment has been performed or authorized.

Both images run as UID 10001 with explicit readable app/config permissions.
Health probes `/_stcore/health`; an HTTP health response alone does not prove
login or dashboard functionality. Small private groups on one instance are the
supported topology. No multi-replica SQLite deployment, SSO, MFA or reset-by-email.

### Isolated Docker package networking

On Linux/Python 3.12, if the host can reach PyPI but the Docker builder cannot:

```sh
./scripts/build-image.sh quantmesh:local
docker compose up -d --no-build
```

The helper supplies TLS-verified host-downloaded wheels as a BuildKit context to
`Dockerfile.offline`. The Python base image must be cached or registry-accessible.
Use a writable `DOCKER_CONFIG` directory if the home directory is read-only.
Never disable certificate verification or embed proxy credentials in an image.

## Backup and migration

Back up existing journals before enabling this version. Migration adds `owner`
and an owner/id index atomically. All pre-existing records remain owned by
`local`; they are not silently transferred to named users. Named-user reads and
writes always pass the authenticated identity to parameterized SQL queries.

Stop the app before copying the SQLite files, or use SQLite's online backup API.
Back up account hashes and the session key separately in protected secret storage.
Treat journal backups as private research data. Keep ownership intact on restore.
Market cache can be discarded to refresh history, but deleting its database also
resets request and login budgets; do not do so while serving users. Cache rows
are bounded to 64 symbols, with six-hour freshness and at most seven-day stale
fallback. Full price adjustment history is refreshed after TTL to incorporate
splits/dividends. Check provider licensing before sharing or redistributing data.
