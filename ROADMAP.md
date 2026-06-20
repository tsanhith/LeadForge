# LeadForge Roadmap

Current state (MVP): upload → validate → per-lead agent pipeline (research, role,
opportunity, personalization, email + WhatsApp generation, QA review) → dashboard with
search/filter/history and a human review flow (approve / edit / regenerate).

**What the MVP does NOT do yet:** actually *send* anything, follow up, authenticate users,
or scale beyond a single process. This roadmap covers closing those gaps.

---

## Phase 1 — Email sending  ⭐ (next)
Turn an approved draft into a sent email.

- **DB** — add to `Outreach`: `send_status` (`draft|queued|sent|bounced|replied`), `sent_at`,
  `provider_message_id`, `send_error`.
- **`app/channels/email.py`** — sender behind a small interface (same spirit as the LLM
  gateway): `async def send_email(to, subject, body) -> SendResult`. Provider configurable
  (Resend / Amazon SES / SMTP); keys in `.env`.
- **Endpoint** — `POST /leads/{id}/send`, enabled only when `review_status == "approved"`.
- **UI** — a **Send** button on the review panel (disabled until approved) + status badge.
- **Compliance** — auto-append an unsubscribe line; a `suppression` table checked before
  every send (CAN-SPAM / GDPR).
- **Infra (not code)** — dedicated sending domain with **SPF + DKIM + DMARC**, domain
  warm-up, and send throttling, or cold email lands in spam.

## Phase 2 — WhatsApp sending
More restricted than email (Meta policy).

- **`app/channels/whatsapp.py`** — Meta WhatsApp Business Cloud API (or Twilio) sender.
- **DB** — `wa_send_status`, `wa_sent_at`; `opt_in` flag on `Lead`.
- **Templates** — pre-approved message templates (Meta requires them for first contact;
  free-form only inside the 24-hour reply window).
- **Consent** — only message opted-in contacts (cold blasting gets numbers banned).
- **UI** — Send button + status, mirroring email.

## Phase 3 — Campaigns & follow-ups
- **`Sequence` + `SequenceStep` models** — multi-step ("no reply in 3 days → follow-up 2").
- **Scheduler** in the worker — timezone-aware send windows, per-account rate limiting.
- **Reply detection** (inbound webhook) → auto-pause the sequence for that lead.

## Phase 4 — Production hardening
- **Auth + users/roles** — the app is currently open to anyone with the URL.
- **Durable queue** — replace the in-process asyncio worker with Redis + Celery/RQ
  (survives restarts, scales horizontally).
- **CRM / enrichment** — push to HubSpot/Salesforce; pull from Apollo/Lusha/ZoomInfo when a
  website is thin or missing.
- **Reliability** — per-lead audit log, retries with backoff, structured logging/metrics.

## Phase 5 — Results & quality loop
- Track **open / reply / meeting-booked** per outreach angle.
- Feed outcomes back into prompt tuning; A/B test subject lines.
- Lift QA scores above the `QUALITY_THRESHOLD` (8.0) bar.

---

## Smaller improvements / backlog
- Export approved outreach to CSV.
- Lower/adjust `QUALITY_THRESHOLD` or improve generation prompts so more leads auto-pass QA.
- Bulk actions in the lead table (approve all ≥ score, regenerate selected).
- Retry/refresh of failed leads from the job dashboard.
- Bump GitHub Actions to action majors that run on Node 24 (silence the deprecation notice).
- Add the Ollama provider to the gateway (a few lines — local/free models).
