"""Ingest quirks specific to Apollo-style exports: split name, multiple phones, email status."""
from __future__ import annotations

from app.ingest.excel import parse_file
from app.ingest.validator import validate_rows

_APOLLO_HEADER = (
    "First Name,Last Name,Title,Company Name,Email,Email Status,Website,"
    "Work Direct Phone,Mobile Phone\n"
)


def _write(tmp_path, *rows: str):
    p = tmp_path / "apollo.csv"
    p.write_text(_APOLLO_HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return p


def test_composes_full_name_and_prefers_mobile(tmp_path):
    path = _write(
        tmp_path,
        "Prasanth,Palukuri,Director,Aera,p@aera.com,valid,aera.com,,'+91 91776 22213",
    )
    rows = parse_file(path)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Prasanth Palukuri"          # First + Last composed
    assert row["phone"] == "+91 91776 22213"           # mobile preferred, leading ' stripped
    assert row["email_status"] == "valid"


def test_falls_back_to_direct_phone_when_no_mobile(tmp_path):
    path = _write(
        tmp_path,
        "Ann,Lee,VP,Acme,a@acme.com,valid,acme.com,'+1 646-338-6530,",
    )
    assert parse_file(path)[0]["phone"] == "+1 646-338-6530"


def test_invalid_email_status_becomes_flag(tmp_path):
    path = _write(
        tmp_path,
        "Bad,Addr,Dir,NoMail,bad@x.com,invalid,x.com,,'+1 555-0100",
    )
    rows = parse_file(path)
    validated = validate_rows(rows)
    assert "unverified_email" in validated[0].flags
    assert validated[0].valid  # flagged, not dropped
