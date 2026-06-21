"""Generate a small sample lead export for testing the pipeline end-to-end.

Includes deliberately messy rows (missing website, invalid email, a duplicate) to exercise
the validation layer. Usage: python scripts/make_sample.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROWS = [
    {"Full Name": "John Smith", "Title": "CTO", "Company Name": "ABC Logistics",
     "Website": "https://www.fedex.com", "Industry": "Logistics",
     "Email": "john@abclogistics.com", "Mobile": "+1 555 0100"},
    {"Full Name": "Maria Garcia", "Title": "HR Manager", "Company Name": "Stripe",
     "Website": "stripe.com", "Industry": "Fintech",
     "Email": "maria@stripe.com", "Mobile": "+1 555 0101"},
    {"Full Name": "Wei Chen", "Title": "VP Engineering", "Company Name": "Vercel",
     "Website": "https://vercel.com", "Industry": "Software",
     "Email": "wei@vercel.com", "Mobile": "+1 555 0102"},
    # missing website + invalid email (kept, but flagged):
    {"Full Name": "Priya Patel", "Title": "Operations Director", "Company Name": "NoSite Co",
     "Website": "", "Industry": "Manufacturing",
     "Email": "not-an-email", "Mobile": ""},
    # duplicate of John Smith by email (should be dropped):
    {"Full Name": "John Smith", "Title": "CTO", "Company Name": "ABC Logistics",
     "Website": "https://www.fedex.com", "Industry": "Logistics",
     "Email": "john@abclogistics.com", "Mobile": "+1 555 0100"},
]


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "sample_leads.xlsx"
    pd.DataFrame(ROWS).to_excel(out, index=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
