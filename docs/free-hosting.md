# Free multi-user hosting compatibility

**Decision:** there is no verified, reliable, entirely free managed-host configuration
for the current QuantMesh storage architecture. Do not select a free web-service
plan and place the SQLite databases or accounts on its temporary filesystem.
The supported paid Render configuration and private Docker Compose remain intact.
Nothing in this change deploys a service, provisions an account, or starts billing.

## What must survive

| State | Location | Why persistence matters |
|---|---|---|
| Account membership, scrypt hashes, revocation nonce | `users.json` | Membership and revocation must not revert on redeploy |
| Owner-scoped research and schema version | `research.sqlite3` | Private saved research must survive a new process/container |
| Login/provider request budgets and market cache | `market.sqlite3` | Restart must not reset brute-force protection or provider quotas |
| Session signing secret | Host secret manager/private runtime environment | Keep stable; deliberate rotation invalidates tokens |

All three files must share an operator-managed durable **local** filesystem under
`QUANTMESH_DATA_DIR`. SQLite WAL/full-sync and account-file locks require local
filesystem locking semantics. Object buckets, Git commits, mounted dataset repos,
network file shares and periodic copies of a live DB are not equivalent storage.
A cache miss is recoverable; losing login budgets or revocation state is a security
regression. A browser's Streamlit session is not an account or database backup.

Production startup now additionally requires
`QUANTMESH_STORAGE_MODE=persistent-local`. Compose and Render set it alongside their
volume/disk configuration. Existing manually configured production services must
add it before upgrading. Missing, ephemeral or unknown modes fail **before** seeding
accounts or opening databases. This is an explicit operator confirmation, **not**
a physical disk durability detector: setting the variable cannot make a temporary
directory persistent. Review the mount and perform the restart/redeploy acceptance
checks below. Dockerfile alone does not supply this confirmation or a durable mount.
Local private `streamlit run app.py` does not require this setting.

## Host comparison and evidence

Research date: 2026-10-20. Quotas and eligibility can change. Do not rely on an old
"free tier" blog post; verify the linked official terms in your own account before
any manual resource creation. Live host provisioning, TLS and billing were not tested.

| Option | Free-tier limits / storage constraint | QuantMesh decision |
|---|---|---|
| Streamlit Community Cloud | Official docs publish approximate February 2024 limits: 0.078–2 CPU cores, 690 MB–2.7 GB RAM, up to 50 GB storage; explicitly subject to change. Idle apps hibernate after 12 hours. These capacity figures are not a durable local-volume contract. | No supported persistent SQLite deployment. Requires a complete external-state backend first. |
| Render free web service | No persistent disk in the free web-service design. Commonly documented limits are 750 instance-hours/workspace/month and sleep after 15 idle minutes; current numbers could not be independently retrieved here. | Do not convert `render.yaml` to free or remove its disk. Its Standard plan is paid. Verify current limits at the linked official page. |
| Hugging Face Spaces | Official source currently says default CPU Basic has 2 cores, 16 GB RAM and 50 GB **nonpersistent** disk, with no hourly hardware charge, but creating Docker/Gradio Spaces requires a paid plan (free ZeroGPU Gradio exception does not host this Streamlit Docker app). Storage documentation now recommends attached Storage Buckets. | Not a zero-cost Docker hosting recommendation. Bucket mounts do not establish SQLite WAL/local-lock compatibility and are unsupported here. |
| Free managed PostgreSQL (e.g. Neon or Supabase) + free web host | A database tier is not a web host or a drop-in SQLite filesystem. Compute/storage/connection quotas, inactivity suspension and backup retention depend on the current plan; no live quota verification was possible here. | Potential future architecture, not supported by setting `DATABASE_URL`. No external database backend is implemented or implied. |
| Oracle Always Free VM | Candidate for durable local boot/block storage, subject to region capacity, eligibility, allocation quotas and idle-resource reclamation policies. Historical A1 allowances often quoted online must be rechecked; this workspace could not retrieve current official terms. | Conditional self-managed candidate only, not a verified free/reliable recommendation. Requires Linux administration, backups, TLS and capacity/architecture validation. Do not select paid shapes or rely on temporary trial credits. |
| Existing owner-operated Linux machine | Can retain a local Docker volume across container recreation. Hardware, power, connectivity and domain availability are the owner's responsibility. | Existing Compose is compatible for a private demo with no new hosting subscription. This is not a guaranteed no-cost, always-online managed service. |

Official references:

- [Streamlit resources and hibernation](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
- [Render free services](https://render.com/docs/free), [persistent disks](https://render.com/docs/disks)
- [Spaces overview](https://huggingface.co/docs/hub/spaces-overview), [storage](https://huggingface.co/docs/hub/spaces-storage)
- [Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Neon plans](https://neon.com/docs/introduction/pro-plans), [Supabase pricing](https://supabase.com/pricing)

Direct documentation websites were denied by the workspace proxy (HTTP 403).
Streamlit and Hugging Face evidence was instead read from their official GitHub
sources, pinned for reproducibility:
[Streamlit](https://github.com/streamlit/docs/blob/b5d4187308f222cb89161952f5eaa362954f749d/content/deploy/community-cloud/manage-your-app/_index.md),
[Spaces overview](https://github.com/huggingface/hub-docs/blob/c7ba19d3ad4b2d07f9b30d12c619b38b98220d94/docs/hub/spaces-overview.md),
[Spaces storage](https://github.com/huggingface/hub-docs/blob/c7ba19d3ad4b2d07f9b30d12c619b38b98220d94/docs/hub/spaces-storage.md).
Other current quotas/pricing remain unverified; no unverified quota is a deployment guarantee.

## Beginner path using the existing supported deployment

If you only have a free ephemeral web host, **stop here**: do not deploy persistent
accounts there. Choose a durable host you already own, or review the paid Render
path in [production-deployment.md](production-deployment.md). If considering a free
VM, manually confirm its current zero-cost eligibility, persistent disk, sufficient
resources and billing exclusions first. No signup or resource creation is automated.

On an approved Linux host with Docker Engine and Compose installed:

1. Clone this repository and select a reviewed commit. Allow at least 2 GB runtime
   RAM plus host/build overhead. ARM images have not been validated in this workspace.
2. Create a private directory **outside the repository** and provision two accounts:

   ```sh
   mkdir -p /absolute/private/quantmesh
   chmod 700 /absolute/private/quantmesh
   python -m quantmesh.manage_users alice --file /absolute/private/quantmesh/users.json
   python -m quantmesh.manage_users bob --file /absolute/private/quantmesh/users.json
   ```

   Run the CLI in the installed Python environment (README installation commands).
   Passwords are prompted. The container runs as UID 10001; the bootstrap file and
   its parent traversal permissions must allow that UID to read it while denying
   unrelated users. Use an appropriate protected ACL or ownership on this dedicated
   file; do not make it world-readable or change ownership of unrelated directories.
3. Use a protected deployment environment file outside Git with mode 0600. Set
   `QUANTMESH_USERS_FILE_HOST` to the absolute bootstrap file and
   `QUANTMESH_SESSION_SECRET` to a securely generated stable raw random value of at
   least 32 characters. Generate/store it privately; never paste it in chat/logs.
   Optional `QUANTMESH_LLM_API_KEY` is your Groq key;
   `QUANTMESH_LLM_PROVIDER=groq`, `QUANTMESH_LLM_MODEL=openai/gpt-oss-20b`.
   `ALPHAVANTAGE_API_KEY` is optional and adjusted-history entitlement may cost money.
   Yahoo, CSV, sample, optimization, backtesting and local RAG need no API key.
4. From the checkout, manually start the existing configuration:

   ```sh
   docker compose --env-file /absolute/private/quantmesh/runtime.env up --build -d
   ```

   Compose supplies production/multi-user mode, `persistent-local`, `/data` paths,
   a named `research` volume, memory/CPU/PID limits and a localhost-only port.
   Keep the same Compose project name and volume across updates; changing the
   project name can select a different empty volume. Never run `down -v` or prune
   the data volume. The underlying Docker data directory must itself be durable.
   The first launch copies the seed once; later launches retain live accounts.
5. Verify local health (`/_stcore/health` returns 200 `ok`), then Alice/Bob login,
   logout, owner-separated journal entries and private exports. A health response
   alone does not validate login, storage, or security.
6. Before any approved public exposure, configure a maintained HTTPS reverse proxy
   with WebSocket support on this same host. Keep port 8501 bound to loopback;
   expose only TLS through the proxy, restrict administrative access, and verify
   certificates/redirects. Domain/certificate/provider setup is manual and may
   introduce cost. No public URL or public deployment is provided by this PR.
7. Configure off-host encrypted backups and test restore **before** using real data.
   Use the existing `python -m quantmesh.backup` commands and account administration
   in [production-deployment.md](production-deployment.md). Back up the live volume,
   not just the bootstrap file. Keep API keys and signing secret outside backups
   of application data. Do not upload backup contents to GitHub.

## Persistence and security acceptance

Before sharing even a demo, create Alice/Bob research, revoke an existing Alice
session, recreate the container using the same volume and restart the host. Verify
accounts, separate journals, revocation and login budgets survive; a fresh browser
session must log in. Test backup/restore into a separate empty volume with the app
stopped for restore. Validate HTTPS/WebSockets and the disk's lifecycle on the chosen
provider. A process restart test cannot prove a provider's redeploy/VM deletion
retention policy. Keep an off-host copy and record the verified recovery procedure.

For rollback, retain the previous reviewed commit/image and a compatible backup.
Stop writes, roll back code with the same volume only when its schema is compatible;
otherwise restore a compatible backup into a new volume. Never downgrade publicly
to anonymous single-user access. Session expiry/revocation is checked on reruns;
a static browser view cannot be remotely erased. No MFA, SSO, public registration,
password recovery or uptime guarantee is added by free hosting.

## Why no partial external-database migration

The code currently uses SQLite transactions for provider/login budgets and journal
migrations, and atomic locked JSON account updates for membership/revocation.
Moving only the journal leaves account resets and brute-force budget resets on
restart. Moving only `users.json` into host secrets makes live revocation/provisioning
nonpersistent. Syncing DB/account files to Git or buckets can leak private data,
lose concurrent writes, roll back revocation, and break WAL consistency.

A future PostgreSQL backend must migrate **all** durable security state, preserve
legacy ownership and revocation fingerprints, implement transactional distributed
login budgets and account updates, use verified TLS and least-privilege credentials,
and provide versioned non-destructive migration/rollback plus actual database
integration tests. It must handle database suspension/outage by denying login and
private data access. Such a migration is feasible as a separate backend project,
but not safely implemented as an untested free-hosting switch. No dependency or
unsupported `DATABASE_URL` setting was added. The safe outcome here is an explicit
blocker and tested preservation of the existing architecture.
