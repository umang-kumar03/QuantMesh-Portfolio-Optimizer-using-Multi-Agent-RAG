# Authentication and persistence audit

## Reused

Admin-provisioned accounts outside Git, random per-password salts, scrypt
(N=16384,r=8,p=1), constant-time digest comparison, generic login failures, signed
one-hour server-side sessions, password-record fingerprint binding, per-username
and global persistent login budgets, pre-dashboard authentication, and parameterized
owner-scoped journal reads/writes. No public signup was added. Password work factor
is unchanged; reassess it against contemporary policy and host capacity before a
higher-risk deployment. This is not a formal cryptographic or penetration audit.

## Findings fixed

- **Unsafe direct image startup:** an image could bind 0.0.0.0 while defaulting to
  single-user mode. Both Dockerfiles now use a production launcher, multi-user
  defaults, and fail before listening if credentials/durable configuration are missing.
  The UI also rejects production+single-user even when the launcher is bypassed.
- **Private download media capability URLs:** native Streamlit downloads are not
  owner-authorized endpoints. Multi-user exports now remain in the authenticated
  WebSocket-rendered iframe as base64 browser-local downloads, with no /media link.
  Labels are escaped, filenames/types restricted, and no external scripts are loaded.
- **Concurrent account updates:** read/modify/replace could lose another operator's
  update. Provisioning now locks the complete update and fsyncs atomic replacement.
- **Persistent account bootstrapping:** a host secret/mount could accidentally become
  the only account copy. A first-start seed is copied privately to the persistent
  disk once; redeploys never replace live membership. Explicit revoke/disable commands
  avoid manual JSON edits. Never recycle an old username for a different person.
- **Durability and rollback ambiguity:** SQLite now uses WAL, full synchronous commits,
  bounded lock waits and a versioned journal migration that rejects future schemas.
  Online backup and non-overwriting, checksum/integrity-verified restore are provided.
- **Unnecessary provider-body persistence:** Alpha cache now stores only validated
  prices and required symbol identity, not arbitrary response metadata.
- **Over-detailed storage errors:** UI no longer echoes raw journal exceptions/paths.

## Verification and deployment boundaries

Tests cover login success/failure, salted hashes, session expiry/revocation, account
removal, throttling, bootstrap persistence, concurrent provisioning/writes, legacy
and future schemas, owner isolation, unauthenticated sessions, private exports and
backup/restore. Existing Yahoo, Groq and analytics tests remain in the full suite.
See validation.md and the PR for actual results. HTTPS and hosting/disk persistence
must be verified only after the owner approves a deployment. No paid resources or
public service were created. Review the operational limits in production-deployment.md.
