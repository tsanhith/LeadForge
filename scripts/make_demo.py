"""Generate a realistic demo lead export (demo_leads.xlsx).

Uses REAL company websites so the Company Research agent has genuine content to scrape,
across varied industries/roles. Includes two deliberately messy rows (missing website +
invalid email, and a duplicate) to demonstrate the validation layer. Names/emails are
fictional. Headers use an Apollo-style layout to exercise column mapping.

Usage: python scripts/make_demo.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROWS = [
    {"First Name": "John", "Last Name": "Carter", "Title": "Chief Technology Officer",
     "Company Name": "Twilio", "Website": "https://www.twilio.com",
     "Industry": "Communications API", "Email": "john.carter@twilio.com",
     "Mobile": "+1 415 555 0110"},
    {"First Name": "Sarah", "Last Name": "Lee", "Title": "VP of Engineering",
     "Company Name": "Shopify", "Website": "shopify.com",
     "Industry": "E-commerce", "Email": "sarah.lee@shopify.com",
     "Mobile": "+1 415 555 0111"},
    {"First Name": "David", "Last Name": "Kim", "Title": "Head of Operations",
     "Company Name": "Flexport", "Website": "https://www.flexport.com",
     "Industry": "Logistics", "Email": "david.kim@flexport.com",
     "Mobile": "+1 415 555 0112"},
    {"First Name": "Emma", "Last Name": "Wilson", "Title": "Chief Marketing Officer",
     "Company Name": "HubSpot", "Website": "https://www.hubspot.com",
     "Industry": "Marketing Software", "Email": "emma.wilson@hubspot.com",
     "Mobile": "+1 617 555 0113"},
    {"First Name": "Raj", "Last Name": "Patel", "Title": "Director of IT",
     "Company Name": "Snowflake", "Website": "https://www.snowflake.com",
     "Industry": "Data Cloud", "Email": "raj.patel@snowflake.com",
     "Mobile": "+1 408 555 0114"},
    {"First Name": "Lisa", "Last Name": "Chen", "Title": "Product Manager",
     "Company Name": "Notion", "Website": "https://www.notion.so",
     "Industry": "Productivity Software", "Email": "lisa.chen@notion.so",
     "Mobile": "+1 415 555 0115"},
    # Messy row: missing website + invalid email (kept but flagged).
    {"First Name": "Tom", "Last Name": "Baker", "Title": "COO",
     "Company Name": "Acme Freight", "Website": "",
     "Industry": "Logistics", "Email": "tom[at]acmefreight", "Mobile": ""},
    # Duplicate of the first lead by email (should be dropped at validation).
    {"First Name": "John", "Last Name": "Carter", "Title": "Chief Technology Officer",
     "Company Name": "Twilio", "Website": "https://www.twilio.com",
     "Industry": "Communications API", "Email": "john.carter@twilio.com",
     "Mobile": "+1 415 555 0110"},
]


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "demo_leads.xlsx"
    df = pd.DataFrame(ROWS)
    # Combine first/last into a single "Full Name" column too, to show alias mapping.
    df.insert(0, "Full Name", df["First Name"] + " " + df["Last Name"])
    df = df.drop(columns=["First Name", "Last Name"])
    df.to_excel(out, index=False)
    print(f"wrote {out} ({len(df)} rows)")


if __name__ == "__main__":
    main()
