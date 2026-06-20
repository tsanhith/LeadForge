"""Parse an uploaded .xlsx/.csv into canonical row dicts using the header mapping."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.ingest.column_map import map_headers


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

    rows: list[dict] = []
    for _, series in df.iterrows():
        row: dict = {}
        for source_header, canonical in mapping.items():
            val = series.get(source_header)
            if val is not None and str(val).strip():
                row[canonical] = str(val).strip()
        if row:  # skip empty rows
            rows.append(row)
    return rows
