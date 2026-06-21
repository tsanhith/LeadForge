# LeadForge Roadmap

Current state: upload → validate → per-lead agent pipeline (research, role, opportunity,
personalization, email + WhatsApp generation, QA review) → dashboard with search/filter/history
→ human review (approve / edit / regenerate) → **send** (email + WhatsApp) with compliance.

**What it does NOT do yet:** follow-up sequences, authenticate users, or scale beyond a single
process. This roadmap covers closing those gaps.

---

## Phase 1 — Email sending  ✅ (done)
Turn an approved draft into a sent email.

- **DB** — `Outreach.send_status` (`draft|queued|sent|failed|suppressed|bounced|replied`),
  `sent_at`, `provider_message_id`, `send_error`. *(SQLite auto-migrates on startup.)*
- **`app/channels/email.py`** — sender behind a small interface (same spirit as the LLM
  gateway): `async def send_email(to, subject, body) -> SendResult`. Providers: `console`
  (mock, default), `smtp` (Google Workspace / M365 / SES SMTP), `resend`. Selected in `.env`.
- **`app/send_service.py`** — guard (reviewed? deliverable? suppressed?) → send → record.
- **Endpoint** — `POST /leads/{id}/send`, enabled only once reviewed (approved/edited).
- **UI** — **Send email** button + status badge on the review panel; send column in the table.
- **Compliance** — unsubscribe footer (link + postal address) auto-appended to every email; a
  `suppressions` table + `GET /unsubscribe` checked before every send (CAN-SPAM / GDPR).
  Apollo `Email Status` flows through as an `unverified_email` flag that blocks bad sends.
- **Infra (not code, still TODO)** — dedicated sending domain with **SPF + DKIM + DMARC**,
  domain warm-up, send throttling. *(Pending the official mailbox.)*

## Phase 2 — WhatsApp sending  ✅ (done)
More restricted than email (Meta policy).

- **`app/channels/whatsapp.py`** — Meta WhatsApp Business Cloud API sender (`console` mock +
  `meta`). Sends a pre-approved template when `WHATSAPP_TEMPLATE_NAME` is set, else plain text.
- **DB** — `Outreach.wa_send_status`, `wa_sent_at`, `wa_provider_message_id`, `wa_send_error`;
  `Lead.opt_in`.
- **Consent** — `require_opt_in_for_whatsapp` (default on) blocks sends to non-opted-in
  contacts; an opt-in toggle lives on the review panel.
- **UI** — Send WhatsApp button + status, mirroring email.
- **Pending creds** — drop `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` in `.env` and set
  `WHATSAPP_PROVIDER=meta` to go live.

## Phase 3 — Campaigns & follow-ups
- **`Sequence` + `SequenceStep` models** — multi-step ("no reply in 3 days → follow-up 2").
- **Scheduler** in the worker — timezone-aware send windows, per-account rate limiting.
- **Reply detection** (inbound webhook) → auto-pause the sequence for that lead.

## Phase 4 — Production hardening  ◑ (auth + queue done)
- ✅ **Auth + users/roles** — session-cookie login (PBKDF2 hashing), admin/member roles, a
  gate middleware over the whole app, first-admin seeding, and a `WEBHOOK_SECRET` for the
  public webhook endpoints. User management at `/users`.
- ✅ **Durable queue** — pluggable backend: `inprocess` (default; resumes interrupted jobs
  on restart via DB recovery) or `arq` (Redis-backed, scales horizontally — run
  `arq app.pipeline.arq_worker.WorkerSettings`).
- **CRM / enrichment** (todo) — push to HubSpot/Salesforce; pull from Apollo/Lusha/ZoomInfo
  when a website is thin or missing.
- **Reliability** (partial) — structured logging in place; still want a per-lead audit log,
  retries with backoff, and metrics.

## Phase 5 — Results & quality loop
- Track **open / reply / meeting-booked** per outreach angle.
- Feed outcomes back into prompt tuning; A/B test subject lines.
- Lift QA scores above the `QUALITY_THRESHOLD` (8.0) bar.

---

## Smaller improvements / backlog
- ~~Export approved outreach to CSV.~~ ✅ `GET /jobs/{id}/export.csv` (respects filters).
- Lower/adjust `QUALITY_THRESHOLD` or improve generation prompts so more leads auto-pass QA.
- Bulk actions in the lead table (approve all ≥ score, regenerate selected).
- Retry/refresh of failed leads from the job dashboard.
- Bump GitHub Actions to action majors that run on Node 24 (silence the deprecation notice).
- Add the Ollama provider to the gateway (a few lines — local/free models).
