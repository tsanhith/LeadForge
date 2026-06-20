"""Validation + normalization that runs BEFORE any AI touches the data.

Given canonical row dicts, normalize fields, flag problems, and detect duplicates. Rows
with no usable identity (no company AND no website AND no email) are treated as invalid and
excluded from processing; everything else is kept with flags for the reviewer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email


@dataclass
class ValidatedLead:
    data: dict
    flags: list[str] = field(default_factory=list)
    valid: bool = True  # False => excluded from the pipeline entirely


def normalize_website(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None
    if not re.match(r"^https?://", v, re.I):
        v = "https://" + v
    parsed = urlparse(v)
    netloc = parsed.netloc.lower()
    if not netloc:
        return None
    return f"{parsed.scheme.lower()}://{netloc}{parsed.path.rstrip('/')}"


def normalize_email(value: str | None) -> tuple[str | None, bool]:
    """Return (normalized_email_or_None, is_valid)."""
    if not value:
        return None, False
    v = str(value).strip()
    if not v:
        return None, False
    try:
        result = validate_email(v, check_deliverability=False)
        return result.normalized.lower(), True
    except EmailNotValidError:
        return v.lower(), False


def _clean(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def validate_rows(rows: list[dict]) -> list[ValidatedLead]:
    """Normalize, flag, and dedupe a list of canonical row dicts."""
    out: list[ValidatedLead] = []
    seen_emails: set[str] = set()
    seen_company_name: set[tuple[str, str]] = set()

    for raw in rows:
        data = {k: _clean(v) for k, v in raw.items()}
        flags: list[str] = []

        data["website"] = normalize_website(data.get("website"))
        email_norm, email_ok = normalize_email(data.get("email"))
        data["email"] = email_norm

        if not data.get("company"):
            flags.append("missing_company")
        if not data.get("website"):
            flags.append("missing_website")
        if data.get("email") and not email_ok:
            flags.append("invalid_email")
        if not data.get("email"):
            flags.append("missing_email")

        # No identity at all -> cannot research or reach out.
        valid = bool(data.get("company") or data.get("website") or email_ok)
        if not valid:
            flags.append("no_identity")

        # Duplicate detection (only among otherwise-valid rows).
        if valid:
            if email_ok and email_norm in seen_emails:
                flags.append("duplicate")
                valid = False
            else:
                name_key = (
                    (data.get("company") or "").lower(),
                    (data.get("name") or "").lower(),
                )
                if name_key != ("", "") and name_key in seen_company_name:
                    flags.append("duplicate")
                    valid = False
                else:
                    if email_ok:
                        seen_emails.add(email_norm)
                    if name_key != ("", ""):
                        seen_company_name.add(name_key)

        out.append(ValidatedLead(data=data, flags=flags, valid=valid))

    return out
