# Free hosting: current architecture options

The earlier SQLite-only hosting audit correctly ruled out persistent accounts on
ephemeral local disks. QuantMesh now supports a complete PostgreSQL backend for
those hosts: [Community Cloud + Neon beginner guide](neon-community-cloud.md).
Accounts, password hashes, revocations, private journals, market caches and every
login/provider budget are remote; this is not a journal-only migration.

| Path | Supported persistence | Main limitation |
|---|---|---|
| Community Cloud + Neon Free | Explicit PostgreSQL mode, guarded `cloud_app.py` | Both services sleep; compute/storage/transfer quotas; no Free uptime SLA |
| Existing private Docker Compose | JSON + SQLite on durable named local volume | Host administration, storage and TLS are owner responsibilities |
| Paid Render Blueprint | One SQLite/JSON instance with a paid persistent disk | Not zero-cost; review billing before manually applying |
| Free host + ephemeral SQLite/JSON | Unsupported | Loses research and can reset security state |
| Bucket/network mounts for SQLite | Unsupported | No verified WAL/locking/local-disk durability contract |

Default `QUANTMESH_BACKEND=sqlite` preserves existing configurations. PostgreSQL
requires explicit backend/auth configuration and an initialized remote database;
connection failure never chooses a local fallback. API keys and session secrets
remain platform secrets. No service, free account, paid resource or public URL has
been provisioned by this work. Only local PostgreSQL behavior is verified.

Current Neon quotas and official source snapshots, Streamlit hibernation/resource
limits, beginner setup, safe migration, off-platform backups, rollback and remaining
security limitations are documented in [the deployment guide](neon-community-cloud.md).
Zero-cost compatibility means a small admin-provisioned demo can fit Free tiers;
it does not establish guaranteed availability, unlimited traffic or permanent free
pricing. Review current eligibility and plan settings manually before deployment.
