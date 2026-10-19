# Private multi-user deployment on Render

This is deployment preparation, not a verified live deployment. No resources, paid
services, domains or public URLs have been created. Do not launch the old local
single-user command publicly. The production launcher fails before binding a socket
unless multi-user accounts, session signing and durable paths are configured.

## Recommendation and limits

Use **one Render Python web-service instance with a persistent disk**, Standard
(or an appropriately sized paid plan with at least 2 GB memory). Review current
plan/disk pricing before creating it. Free/ephemeral services and Streamlit Community
Cloud do not provide the reliable application-owned persistent filesystem required
by this design. `render.yaml` prepares a one-instance service and 1 GB disk mounted
at `/var/data`; automatic deployment is off. Apply only after explicit owner approval.

SQLite is appropriate here because there is one process/instance on a local durable
disk with short transactions, WAL, full synchronous commits and a 10-second lock wait.
Do not use a network share, multiple replicas, or a serverless ephemeral filesystem.
For higher scale or a platform without persistent local disks, migrate the journal,
accounts and login budgets to a supported PostgreSQL/identity design first; do not
reuse this SQLite configuration there. Native Render runtime avoids Docker mount
ownership surprises. Docker Compose remains available for private self-hosting.

Render manages HTTPS termination and the public onrender.com URL/custom domain.
Before launch, verify its current HTTPS redirect, certificate, WebSocket support and
inbound access policy. They have **not been tested here**. Official references:
[web services](https://render.com/docs/web-services), [disks](https://render.com/docs/disks),
[Blueprint specification](https://render.com/docs/blueprint-spec).
Direct documentation access was restricted in this cloud environment, so confirm
current platform options and validate the Blueprint in Render before applying it.

## 1. Prepare accounts locally

Use your existing environment; the CLI keeps passwords out of arguments/history.
Use a directory outside the checkout and protect it. New account files contain only
salted scrypt hashes and optional session-revocation metadata, never passwords/keys.

```sh
python -m quantmesh.manage_users alice --file /absolute/private/quantmesh-users.json
python -m quantmesh.manage_users bob --file /absolute/private/quantmesh-users.json
```

Review the file's permissions privately (0600 on Unix). Do not print or commit it.
Copy its contents through Render's secure **secret file** editor as a file named
`quantmesh-users.json`, available at `/etc/secrets/quantmesh-users.json`. This is
operator-provisioned membership; there is no public registration or admin web UI.
Never reuse a disabled username for a different person: ownership uses usernames.

## 2. Configure, review, then deploy manually

Connect the intended repository and approved branch/release. Review `render.yaml`
without applying it automatically. Set the secret file before first startup. Some
Blueprint flows create the service before secret-file entry; startup will safely
fail until you add the file and manually redeploy. No anonymous bootstrap page exists.

| Setting | Production value / requirement |
|---|---|
| Runtime | Python 3.12; Blueprint pins 3.12.14; verify Render supports the patch |
| Build | `python -m pip install -c constraints.txt .` |
| Start | `python -m quantmesh.serve` |
| Health | `/_stcore/health` (200 `ok`; liveness, not a full authentication test) |
| Instance count | Exactly 1 |
| Persistent mount | `/var/data`, writable by app runtime |
| `QUANTMESH_DEPLOYMENT` | `production` |
| `QUANTMESH_AUTH_MODE` | `multi-user` |
| `QUANTMESH_DATA_DIR` | `/var/data` |
| `QUANTMESH_DB` | `/var/data/research.sqlite3` |
| `QUANTMESH_CACHE_DB` | `/var/data/market.sqlite3` |
| `QUANTMESH_USERS_FILE` | `/var/data/users.json` |
| `QUANTMESH_BOOTSTRAP_USERS_FILE` | `/etc/secrets/quantmesh-users.json`, first start only |
| `QUANTMESH_SESSION_SECRET` | Raw high-entropy secret, 32+ chars; Blueprint generates a value. Keep it stable across restarts; rotate to revoke sessions. Never use a network-proxy placeholder |
| `QUANTMESH_LLM_PROVIDER` | `groq` |
| `QUANTMESH_LLM_MODEL` | `openai/gpt-oss-20b` (user-verified Groq model; not an OpenAI endpoint) |
| `QUANTMESH_LLM_API_KEY` | Your Groq key via secure environment settings, optional until AI use |
| `ALPHAVANTAGE_API_KEY` | Optional; adjusted full-history plan entitlement still required |
| `PORT` | Supplied by Render; launcher honors it |

The launcher validates paths, writable storage, private account-file permissions,
valid accounts, schemas and signing configuration before starting Streamlit. It
cannot prove that an arbitrary directory is backed by durable infrastructure; the
mount definition and restart test below are essential. The first valid secret file
is copied atomically into persistent storage. Subsequent restarts/deploys **never
overwrite** disk accounts from that seed. Remove the seed after successful bootstrap
if desired. Keep a protected offline account backup before doing so.

No key is needed for sample/CSV workflows or Yahoo. Allow documented outbound hosts
for Yahoo/Groq/Alpha as needed; see data-sources.md. Provider availability/billing
must be tested in your hosting account. AI still requires explicit consent before
sending a question and computed summary evidence; raw prices are not automatically sent.

## 3. Required acceptance checks after an approved launch

1. Confirm HTTPS/certificate/redirect and `/_stcore/health`; check startup logs for
   safe failures without dumping environment variables or secrets.
2. In a private browser window, confirm dashboards, uploads, journal and exports
   are unavailable before login. Login as Alice and save uniquely named research.
3. In a separate browser profile, login as Bob; Alice's record must be absent.
4. Sign out and refresh. The dashboard must remain gated. Downloads use browser-local
   data links in multi-user mode, not unauthenticated server media URLs. Test CSV/JSON
   download behavior in your supported browsers (iframe downloads may be restricted).
5. Revoke an account's sessions using the CLI below, rerun its dashboard and confirm
   a sign-in screen. Rate-limit repeated wrong passwords; avoid locking out real users.
6. Restart the service. Browser sessions should require re-login, but accounts,
   research ownership and request/login budget history must remain on disk.
7. Perform a backup/restore drill to a separate private location before trusting backups.
8. With fallback disabled, test real Yahoo history and check actual dates/adjustment;
   test Groq separately with consent. No live provider success is implied by mocks.

## 4. Account operations

Run operator commands in Render's supported private service shell/SSH environment.
Use your actual durable path, not the bootstrap secret file.

```sh
python -m quantmesh.manage_users carol --file /var/data/users.json
python -m quantmesh.manage_users alice --file /var/data/users.json --revoke
python -m quantmesh.manage_users bob --file /var/data/users.json --disable
```

The first command also resets an existing user's password, revoking its sessions.
Changes are locked across operator processes and atomically written/fsynced.
Revocation changes a nonce without replacing the password. Disable removes access
but preserves that username's research. The CLI refuses to disable the last account.
All users are research users; administrative file access belongs only to operators.

## 5. Backups, restore and rollback

Before upgrades, create a new protected snapshot outside the data directory:

```sh
python -m quantmesh.backup create --destination /tmp/quantmesh-backup-YYYYMMDD-HHMM
```

The command uses SQLite's online backup API (including committed WAL state), checks
integrity, copies protected account hashes, and writes a checksum manifest. It copies
both databases, so login quotas survive restore. It does **not** copy API/session
secrets; retain those in a separate secret manager. Per-database snapshots are
consistent, but not one transaction across both DBs/accounts; pause writes for a
strict cross-file recovery point. Checksums detect corruption, not a maliciously
replaced backup/manifest. The snapshot is private but not encrypted by this tool.

`/tmp` on the host is ephemeral: immediately encrypt and transfer the snapshot to
an operator-controlled off-platform store using trusted tooling. Define a daily
schedule/retention and run restore drills; neither automated offsite transfer nor
an RPO/RTO guarantee is configured by this PR. Provider disk snapshots alone are
not proof of an application-consistent SQLite backup. Do not print backup contents,
put them in Git or leave the only copy on the production disk.

To restore, stop all writers/service access first. Use a new directory on the disk;
the tool will not overwrite existing DB/account/WAL files.

```sh
python -m quantmesh.backup restore --source /private/verified-snapshot --destination /var/data/restored --app-stopped
```

Point all three file variables at `/var/data/restored/research.sqlite3`,
`/var/data/restored/market.sqlite3`, `/var/data/restored/users.json`, then restart and
repeat the owner-isolation acceptance test. They remain within QUANTMESH_DATA_DIR.
Rotate the signing key to revoke sessions after recovery. Preserved login budgets
may briefly continue a prior lockout; do not delete budgets while serving users.

For code rollback, select the previous known-good release in Render and verify its
schema compatibility. Journal schema version 1 is explicitly checked; a newer version
fails closed instead of being reset. Never run an older binary that bypasses schema
checks or restore over live SQLite/WAL files. If migration rollback needs old data,
restore the pre-upgrade snapshot to a new directory before switching paths/release.
Do not roll back to a single-user public launch command.

## Remaining risks

One SQLite-backed instance; limited concurrency; no enterprise SSO/MFA, self-service
recovery, tamper-proof audit log or formal penetration test. Sessions live in the
Streamlit process/WebSocket, not durable browser authentication cookies. Reloads,
connection loss and restarts can require re-login. Expiry/revocation is checked on
reruns, not by remotely erasing already displayed browser data at an exact deadline.
Users can retain downloads/screenshots. Public Streamlit health/static routes remain
public; no assertion is made that every platform route is protected by account auth.
Use network access policies for a small private group and independent security review
before broader/public use. No live Render deployment, HTTPS or backup offsite transport
has been verified in this workspace.

Monitor disk utilization and alert well before exhaustion. Journals are not silently
pruned; set an operator retention/export policy with users. A full disk will block
writes or logins safely but can affect availability. Restore exercises and capacity
planning are operational responsibilities, not guarantees supplied by this code.
