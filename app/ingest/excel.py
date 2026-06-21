"""Parse an uploaded .xlsx/.csv into canonical row dicts using the header mapping.

Beyond the generic header mapping, this layer handles two real-world quirks of exports like
Apollo / ZoomInfo / Sales Navigator:

* a contact's name often arrives split across ``First Name`` / ``Last Name`` columns — we
  compose a single ``name`` from them;
* there are several phone columns (mobile / direct / corporate) and many are blank — we pick
  the first non-empty, preferring the mobile number (the one WhatsApp can reach), and strip
  the leading ``'`` that spreadsheets add to keep ``+`` numbers as text.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.ingest.column_map import _norm, map_headers


def _find_header(headers: list[str], *normalized_names: str) -> str | None:
    """Return the first source header whose normalized form matches one given."""
    wanted = set(normalized_names)
    for h in headers:
        if _norm(str(h)) in wanted:
            return h
    return None


def _clean_phone(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lstrip("'").strip()
    return v or None


def parse_file(path: str | Path) -> list[dict]:
    """Read a spreadsheet and return rows keyed by canonical field names.

    Unrecognized columns are dropped. Fully empty rows are skipped.
    """
    path = Path(path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(path, dtype=str)

    df = df.where(pd.notnull(df), None)
    headers = [str(c) for c in df.columns]
    mapping = map_headers(headers)  # {source_header: canonical_field}

    # Source columns that carry a name or a phone, handled specially below.
    first_col = _find_header(headers, "firstname")
    last_col = _find_header(headers, "lastname")
    # Deliverability hint from the export (Apollo: valid/invalid/catch-all/unavailable).
    email_status_col = _find_header(headers, "emailstatus", "emailverificationstatus")
    # Phone columns in preference order: mobile first (WhatsApp-reachable), then the rest.
    phone_cols = [
        h for key in ("mobilephone", "workdirectphone", "directphone", "phone",
                      "corporatephone", "homephone", "otherphone", "companyphone")
        for h in headers if _norm(str(h)) == key
    ]

    rows: list[dict] = []
    for _, series in df.iterrows():
        row: dict = {}
        for source_header, canonical in mapping.items():
            val = series.get(source_header)
            if val is not None and str(val).strip():
                row[canonical] = str(val).strip()

        # Compose a full name from split First/Last columns when present.
        if first_col or last_col:
            parts = [series.get(first_col), series.get(last_col)]
            composed = " ".join(p.strip() for p in parts if p and p.strip())
            if composed:
                row["name"] = composed

        # Prefer the first non-empty phone (mobile leads), stripping spreadsheet quoting.
        # This wins over the generic mapping so WhatsApp gets a mobile when one exists.
        for col in phone_cols:
            cleaned = _clean_phone(series.get(col))
            if cleaned:
                row["phone"] = cleaned
                break
        if row.get("phone"):
            row["phone"] = _clean_phone(row["phone"])

        if email_status_col is not None:
            status = series.get(email_status_col)
            if status and str(status).strip():
                row["email_status"] = str(status).strip().lower()

        if row:  # skip empty rows
            rows.append(row)
    return rows
