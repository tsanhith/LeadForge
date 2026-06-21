"""Application configuration.

All tunables live here so the rest of the app stays provider-agnostic. In particular,
``MODEL_ROUTES`` is the *only* place that maps a pipeline task to a concrete provider+model;
agents reference tasks by name and never know which model runs.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Providers (both OpenAI-compatible /chat/completions endpoints).
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    nvidia_nim_api_key: str = ""
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"

    # Order providers are tried for fallback when a route's primary fails.
    llm_fallback_order: str = "openrouter,nvidia_nim"

    pipeline_concurrency: int = 4
    quality_threshold: float = 8.0

    database_url: str = "sqlite+aiosqlite:///./leadforge.db"
    upload_dir: str = "./uploads"

    request_timeout: float = 60.0
    max_retries: int = 2

    # ---- Outreach: email channel ----
    # Provider stays "console" (logs the email, marks it sent) until real credentials land,
    # so the whole pipeline is exercisable end-to-end today. Switch to smtp/resend in .env.
    email_provider: str = "console"  # console|smtp|resend
    email_from: str = "outreach@leadforge.ai"
    email_from_name: str = "LeadForge AI"
    email_reply_to: str = ""

    # SMTP — for the "official mail" (Google Workspace / Microsoft 365 / any SMTP relay).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    # Resend (https://resend.com) transactional API — alternative to SMTP.
    resend_api_key: str = ""

    # ---- Outreach: WhatsApp channel (Meta WhatsApp Business Cloud API) ----
    whatsapp_provider: str = "console"  # console|meta
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    # Meta requires a pre-approved template for the FIRST message to a contact. If set, the
    # generated copy is passed as body parameter {{1}}; otherwise a plain text message is sent
    # (only valid inside the 24h customer-service window).
    whatsapp_template_name: str = ""
    whatsapp_template_lang: str = "en_US"

    # ---- Compliance / public surface ----
    public_base_url: str = "http://localhost:8000"  # used to build the unsubscribe link
    company_postal_address: str = "LeadForge AI"     # CAN-SPAM requires a physical address
    require_opt_in_for_whatsapp: bool = True

    @property
    def fallback_order(self) -> list[str]:
        return [p.strip() for p in self.llm_fallback_order.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------------------
# Model routing: task -> (provider, model). Change models here without touching agents.
# Free-tier-friendly defaults. The QA task deliberately uses a *different* model from the
# generation tasks so the review is a genuine second opinion.
# --------------------------------------------------------------------------------------
MODEL_ROUTES: dict[str, tuple[str, str]] = {
    # Fast/cheap model for the extraction-style stages.
    "research": ("nvidia_nim", "meta/llama-3.1-8b-instruct"),
    "role": ("nvidia_nim", "meta/llama-3.1-8b-instruct"),
    # Strong model for the reasoning + writing stages.
    "opportunity": ("nvidia_nim", "meta/llama-3.3-70b-instruct"),
    "personalize": ("nvidia_nim", "meta/llama-3.3-70b-instruct"),
    "email": ("nvidia_nim", "meta/llama-3.3-70b-instruct"),
    "whatsapp": ("nvidia_nim", "meta/llama-3.3-70b-instruct"),
    # QA reviews everyone else's work -> route to a DIFFERENT model family (Qwen).
    "qa": ("nvidia_nim", "qwen/qwen3-next-80b-a3b-instruct"),
}

# Default route used if a task name is missing from MODEL_ROUTES.
DEFAULT_ROUTE: tuple[str, str] = ("nvidia_nim", "meta/llama-3.3-70b-instruct")


# --------------------------------------------------------------------------------------
# Our company / service catalog. The Opportunity Mapping agent reasons against this to
# find a relevant outreach angle for each lead. Edit to match your real offering.
# --------------------------------------------------------------------------------------
COMPANY_PROFILE: dict[str, object] = {
    "name": "LeadForge AI",
    "one_liner": "We build custom AI agents and automation that remove repetitive work.",
    "services": [
        "Agentic AI systems",
        "Workflow & process automation",
        "Custom AI product development",
        "AI integration into existing tools",
    ],
    "value_props": [
        "Cut manual, repetitive internal work",
        "Faster operations through automation",
        "Bespoke AI — not off-the-shelf templates",
    ],
}
