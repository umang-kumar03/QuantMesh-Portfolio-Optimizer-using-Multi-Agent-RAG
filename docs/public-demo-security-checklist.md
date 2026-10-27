# Public demo security and operations checklist

**Scope:** Documentation-only review of repository code, templates and previously observed demo behavior; **not** a penetration test or direct inspection of Streamlit Cloud Secrets, Neon control-plane settings, browser history or private account records.

## Verified in the repository

- [x] The public Streamlit entrypoint is `cloud_app.py` and requires `postgres`, `production` and `multi-user` before rendering the research UI.
- [x] Authentication is required before UI exports/journal access; no self-service registration or known public account password is committed.
- [x] `.gitignore` excludes `.env`, `.streamlit/secrets.toml`, `.venv/`, local databases, backups and account-record files.
- [x] The tracked `.streamlit/secrets.toml.example` uses placeholders and leaves the signing secret empty.
- [x] PostgreSQL remote connections retain `sslmode=verify-full`, SNI/hostname checks, limited role permissions and fail-closed storage behavior.
- [x] Optional LLM calls need explicit UI consent; citations are schema/exact-quote checked and AI explanations marked unverified.
- [x] Provider fallback is labeled synthetic; Alpha Vantage unadjusted closes are not silently misrepresented as adjusted.
- [x] The GitHub Actions test matrix covers Python 3.11/3.12 with disposable PostgreSQL, and a pinned Python dependency scan.

## Operator-only checks — not verified by this repository review

- [ ] **Streamlit Cloud Secrets:** Only a dedicated runtime `quantmesh_app` role connects to the production database; the privileged Neon owner URL, personal passwords and long-lived service credentials are absent from the Cloud configuration, logs, issues and committed files. Do not paste values in review discussions.
- [ ] **Role grants:** Confirm `quantmesh_app` cannot migrate or modify account records. Use an approved database administrator/permission review; don't rerun destructive migration or account commands on production.
- [ ] **Provider keys:** Review Groq and Alpha Vantage usage limits, revocation controls, billing and any public-sharing restrictions. Do not expose a free/shared API key through a public screenshot.
- [ ] **Demo accounts:** Decide whether `testuser1` is only a temporary testing account. If removing it, first preserve or export any owner-scoped research and use the project's reviewed account management workflow. **No accounts were changed by this work.**
- [ ] **Public access:** Decide whether evaluators should receive individually provisioned accounts; never place a shared demonstration password into README, Streamlit page text or social media.
- [ ] **Backups:** Arrange private periodic Neon exports and a tested restore procedure outside the public repository. Verify plan-specific retention limits.
- [ ] **Platform health:** Review Streamlit/Neon quotas, free-tier hibernation, regional connectivity and uptime limits. The currently successful **direct Neon** endpoint is intentional; no automatic switch to pooling should occur.
- [ ] **Screenshots:** Use synthetic inputs and manually redact usernames, saved journal records, browser profile information, tokens and private endpoint details before publishing pictures.
- [ ] **Data rights:** Review Yahoo Finance's unofficial-history access and Alpha Vantage's paid adjusted-history entitlement before distributing datasets or publishing a live public API workflow.
- [ ] **Browser/device checks:** Verify download handling and responsive layout in supported browsers and a mobile viewport; automated AppTest is not an actual mobile-browser test.
- [ ] **Security boundaries:** No MFA/SSO, enterprise tenancy, formal penetration test or guaranteed 24/7 uptime is claimed. Database row-level security is not configured; application-level owner filtering is enforced.

## Incident checklist

If a credential might have appeared in a public repo, screenshot, log or chat, use the **provider's secure console** to revoke/rotate it and update the corresponding Cloud Secret. Avoid copying credentials into GitHub issues, pull requests, chat or terminals with command history. A session-signing secret rotation invalidates existing sessions; coordinate changes with the operator. Do not delete users, records, API keys or databases simply to tidy a demo.

**Current outcome:** The public repository can be documented without changing the live backend or exposing account-scoped assets. Secret existence, values, expiry and account hygiene require authorized operator review.
