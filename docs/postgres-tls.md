# PostgreSQL TLS startup diagnosis

TLS and hostname verification remain mandatory. There is no `sslmode=require`,
`verify-ca`, trust-all context, alternate-host retry, or SQLite/anonymous fallback.
An optional diagnostic handshake cannot authorize login or bypass a failed libpq
connection. Account data and schema are not changed by this fix.

## Findings in main

The previous error handler classified any OperationalError containing `ssl`, `tls`
or `certificate` as a certificate-verification failure. That also matched closed
SSL connections and some channel-binding failures. It obscured the actual cause.
The latest CA patch already selected Certifi by default; substituting Certifi again
was not evidence of a solution. It also treated explicit `system` as Certifi, so
trying `"system"` and `""` did not actually compare two trust stores. Its TLS test
still expected `system` and failed against that code.

The production exception/hostname/CA configuration is unavailable to this workspace.
The supplied public Streamlit URL could not be fetched: the workspace egress proxy
returned HTTP 403, including after an escalated retry. No production database URL
or credential binding was available. Therefore **the actual production certificate
failure and recovery have not been verified**. Do not infer them from the old label.
Local owner-role success does not validate Cloud's hostname/trust store: TLS runs
before PostgreSQL username/password authentication.

## Connection policy

- Blank/unset `QUANTMESH_SSLROOTCERT` uses the installed, directly pinned Certifi
  PEM path, resolved inside the running Python environment. No Windows/Linux path
  is hardcoded. CA files must be readable absolute files, at most 8 MiB, and load
  usable CA certificates before libpq is called.
- Explicit `QUANTMESH_SSLROOTCERT=system` now means libpq/OpenSSL native system
  roots. Bundled libpq's OpenSSL trust paths can differ from Python's or the OS's.
  It is no longer silently interpreted as Certifi. Explicit custom PEM paths are
  supported but must exist in that runtime. No arbitrary CA is downloaded/trusted.
- Non-loopback connections override URL/environment attempts to weaken TLS:
  `sslmode=verify-full`, `sslsni=1`, `gssencmode=disable`. SNI carries the configured
  hostname, not a guessed IP/name. GSS encryption cannot supersede required TLS.
  Hostname verification is never replaced by chain-only verification.
- No direct/pooler hostname is synthesized. Use the exact endpoint from Neon's
  Connect dialog. `-pooler` indicates the pooled endpoint; a direct endpoint is
  also valid TLS when its certificate matches. Connection credentials never move
  automatically between endpoints.

## Sanitized startup codes

The UI shows a fixed error code/message and, for TLS failures, Python/psycopg/libpq/
Certifi versions, binary implementation, CA-source enum and endpoint-kind enum.
It never shows the hostname, port, certificate names, CA path, username, database
name, password, URL, SQL or raw driver exception. Driver DEBUG/rollback logs are
suppressed for the transaction's thread; other threads' logs remain enabled.

| Code | Evidence and appropriate next action |
|---|---|
| `TLS_CA_PATH_INVALID` | Configured CA file is missing, unreadable, relative, or not a file. Only if this appears, correct `QUANTMESH_SSLROOTCERT` to a trusted PEM present **inside Cloud**, or remove that override to use the default Certifi bundle. Never copy a local Windows path into Cloud. |
| `TLS_CA_BUNDLE_INVALID` | The CA file is empty, oversized, malformed, has no usable CAs, or native roots cannot be loaded. Verify the installed/configured trust material; do not weaken verification. |
| `TLS_HOSTNAME_MISMATCH` | The certificate does not match the configured hostname. Compare the private URL's host with the exact Neon Connect endpoint; do not manually invent a pooler suffix or substitute an IP. No hostname needs to be posted publicly. |
| `TLS_ISSUER_MISSING` | OpenSSL could not find the issuer in the presented chain or selected trust store. A valid CA-file path alone does not establish trust in the presented chain. Investigate the server's intermediate chain or an authorized interception CA. |
| `TLS_SELF_SIGNED_CERTIFICATE`, `TLS_SELF_SIGNED_CHAIN` | A self-signed certificate is untrusted. Use only a legitimate provider/organization CA obtained through an authenticated channel; never trust an arbitrary certificate fetched from the failing server. |
| `TLS_CHAIN_INCOMPLETE`, `TLS_CA_CONSTRAINTS` | The certificate chain cannot be completed or its CA constraints are invalid. Correct the chain/provider configuration. |
| `TLS_CERTIFICATE_EXPIRED`, `TLS_CERTIFICATE_NOT_YET_VALID`, `TLS_CERTIFICATE_REVOKED` | Certificate validity/revocation failed. Check provider certificates and runtime clock based on this evidence. |
| `TLS_PYTHON_VERIFIED_LIBPQ_FAILED` | Python verified the same numeric peer/hostname/CA policy, but the primary libpq connection failed. This is not permission to proceed. Compare the safe package versions and libpq-specific client-certificate/revocation/trust configuration; it does not alone prove a library bug. |
| `TLS_CLIENT_CERTIFICATE`, `TLS_PROTOCOL`, `TLS_NOT_SUPPORTED` | Client certificate/key configuration, TLS negotiation, or endpoint TLS support failed; these are not all CA-chain failures. |
| `TLS_VERIFY_FAILED` | libpq reported verification failure but a more specific verified reason is unavailable. Do not guess or expose raw connection logs. |
| `AUTH_CHANNEL_BINDING`, `DATABASE_AUTHENTICATION`, `DATABASE_PERMISSIONS`, `DATABASE_SCHEMA`, `DATABASE_NAME` | Authentication, required channel binding, role permissions, schema, or database configuration failed. These are separate from server certificate trust. |
| `CONNECTION_CLOSED`, `NETWORK_TIMEOUT`, `HOSTNAME_RESOLUTION`, `CONNECTIVITY` | Transport, timeout, DNS or connection failure. SSL appearing in a closed-connection message does not prove a certificate error. |

No Secret change is universally required. In particular, do not repeatedly toggle
`QUANTMESH_SSLROOTCERT`, replace keys, or reboot without the new code providing
specific evidence. Existing blank/unset CA configuration already selects Certifi.
Share only the new fixed code and safe version caption if further diagnosis is
needed, never Secrets contents or raw libpq messages.

## How the verification-only probe works

For the otherwise generic libpq `certificate verify failed` reason only, the code
may perform one additional TLS handshake per minute/config/process. It uses the
**numeric peer and port of the failed libpq connection**, retains the original
hostname for SNI/verification, and never does a fresh DNS lookup or selects another
endpoint. If the peer is unavailable, it retains the original sanitized failure.
Its CA validation and certificate/hostname checks remain enabled. PostgreSQL
SSLRequest negotiation and explicit direct TLS/ALPN are supported.

It sends no PostgreSQL StartupMessage, database name, username, password, SQL, or
client certificate. OpenSSL's structured verification number maps to fixed codes.
Python success still raises a failure for the primary connection. TCP/TLS timeouts
are 3 seconds; a bounded, synchronized 60-second cache prevents probe storms.
Probe failures do not turn database access into sample/anonymous access.

## Verification and release

Automated checks use the pinned psycopg 3.3.6 binary driver (libpq 18 in the local
Python 3.12 environment), generated ephemeral test CAs, and a loopback TLS protocol
fixture. They test trusted wildcard/SNI connections, untrusted issuers, hostname
rejection before authentication, direct TLS/ALPN, credential-free probes, invalid
CA paths/content, raw-log suppression, fail-closed UI and the existing full-state
PostgreSQL/SQLite regressions. No production credential is required or committed.

The Cloud deployment tracks **main**, so a pushed feature branch alone does not
change the running app. After review/applying this change to main, verify the real
multi-user login page; HTTP 200 or Streamlit health alone is not enough. If it still
fails, the new code supplies the specific safe diagnostic above. Live verification
must remain marked outstanding until that login page is actually observed. No
public deployment or successful production recovery is claimed by these tests.
