# ⚡ LeadForge — AI Outreach Platform

Upload a raw lead export (Apollo / ZoomInfo / LinkedIn Sales Navigator / any source) and
LeadForge automatically, for each lead:

1. **Validates & normalizes** the data (missing website/company, invalid email, duplicates).
2. **Researches the company** by scraping its website.
3. **Analyzes the role** to infer priorities & pain points.
4. **Maps an opportunity** against *our* services (the outreach angle).
5. **Personalizes** a master context brief.
6. **Generates a unique email** (no templates, no mail merge).
7. **Generates a WhatsApp** message (shorter, conversational).
8. **QA-reviews** its own output with a *second* model and scores it /10.

Everything lands in a dashboard with search, filters, upload history, and a human review
flow (**Approve / Edit / Regenerate**). Reviewed drafts can then be **sent**:

9.  **Sends the email** through a configurable provider (`console` mock / `smtp` / `resend`),
    with a CAN-SPAM/GDPR unsubscribe footer and a do-not-contact suppression check.
10. **Sends the WhatsApp** message via Meta's WhatsApp Business Cloud API (opt-in gated).

Until real credentials exist, both channels default to a **`console`** provider that logs the
message and records it as sent — so the entire flow is exercisable today. Flip a provider in
`.env` to go live.

## Architecture

```
Excel upload → Validation → per-lead pipeline (concurrent, in-process worker):
  Company Research → Role Analysis → Opportunity Mapping → Personalization
  → Email Gen → WhatsApp Gen → QA Review → persist
→ Dashboard (stats, search/filter, history) → Human Review → Send (email + WhatsApp)

ALL sends ──────────► Channels ──────────► {console | smtp | resend} · {console | meta}
(one send_* interface)   (guard → deliver → record; suppression + opt-in enforced)

ALL agents ─────────► LLM Gateway ─────────► {OpenRouter | NVIDIA NIM}
(never call a provider directly)   (routes task→model, retries, fallback)
```

**Non-negotiable rule:** no agent instantiates a provider client. Every model call goes
through `app/llm/gateway.py`, which maps a *task* to a *(provider, model)* via
`MODEL_ROUTES` in `app/config.py`. Swap models or providers there without touching agents.
OpenRouter and NVIDIA NIM are both OpenAI-compatible, so they share one client
(`app/llm/providers/openai_compatible.py`); adding Ollama later is a few lines.

## Stack

FastAPI · Jinja2 + HTMX · SQLAlchemy (async) + SQLite · httpx · selectolax · pandas.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

copy .env.example .env          # then add your keys
```

Set in `.env`:

- `OPENROUTER_API_KEY` — https://openrouter.ai/keys
- `NVIDIA_NIM_API_KEY` — https://build.nvidia.com

## Run

```bash
uvicorn app.main:app --reload
# open http://localhost:8000
```

Generate a sample export and upload it:

```bash
python scripts/make_sample.py    # writes sample_leads.xlsx
```

## Test

```bash
pytest
```

Covers header mapping, validation/dedupe, the JSON parser, and gateway routing + fallback
(providers mocked — no network or keys required).

## Configuration knobs (`app/config.py` / `.env`)

| Setting | Purpose |
|---|---|
| `MODEL_ROUTES` | task → (provider, model). QA uses a different model on purpose. |
| `COMPANY_PROFILE` | your services — the Opportunity agent reasons against this. |
| `PIPELINE_CONCURRENCY` | leads processed in parallel per job. |
| `QUALITY_THRESHOLD` | score at/above which a lead counts as "high quality". |
| `LLM_FALLBACK_ORDER` | provider order tried when a route's primary fails. |
| `EMAIL_PROVIDER` | `console` (mock) · `smtp` · `resend`. SMTP/Resend keys in `.env`. |
| `WHATSAPP_PROVIDER` | `console` (mock) · `meta`. Token + phone-number-id in `.env`. |
| `REQUIRE_OPT_IN_FOR_WHATSAPP` | block WhatsApp sends to non-opted-in leads (default on). |
| `PUBLIC_BASE_URL` / `COMPANY_POSTAL_ADDRESS` | used to build the email unsubscribe footer. |

## Project layout

```
app/
  config.py            settings, MODEL_ROUTES, COMPANY_PROFILE
  llm/                 gateway + providers (the only place models are chosen)
  ingest/              excel parse, column mapping, validation
  scraping/            website fetch + HTML→text
  agents/              7 task agents (each calls only the gateway)
  pipeline/            orchestrator (per lead) + in-process worker (per job)
  channels/            email + whatsapp senders, suppression (one send_* interface)
  web/                 routes + Jinja2/HTMX templates
  models.py db.py schemas.py job_service.py send_service.py
tests/                 unit tests
scripts/               make_sample.py · run_demo.py · e2e_one.py (one-lead live run)
```

## Going live (when credentials arrive)

- **Email:** set `EMAIL_PROVIDER=smtp` + `SMTP_*` (or `EMAIL_PROVIDER=resend` + `RESEND_API_KEY`),
  and a real `EMAIL_FROM`. Set up SPF + DKIM + DMARC on the sending domain first.
- **WhatsApp:** set `WHATSAPP_PROVIDER=meta`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, and a
  pre-approved `WHATSAPP_TEMPLATE_NAME` for cold first-contact.

## Not yet built

Multi-user auth, Redis/Celery durable queue, follow-up sequences, rate limiting/observability,
and the sending-domain infra (SPF/DKIM/DMARC, warm-up) above.
