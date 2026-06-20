"""Map arbitrary source headers (Apollo / ZoomInfo / Sales Navigator / etc.) to our
canonical lead fields. Matching is case/space/punctuation-insensitive with alias lists.
"""
from __future__ import annotations

import re

CANONICAL_FIELDS = (
    "name",
    "position",
    "company",
    "website",
    "linkedin",
    "industry",
    "email",
    "phone",
    "description",
)

# Aliases per canonical field. Compared after normalization (lowercased, alnum only).
_ALIASES: dict[str, list[str]] = {
    "name": ["name", "fullname", "full name", "contact", "contactname", "person",
             "leadname", "prospect"],
    "position": ["position", "title", "jobtitle", "job title", "role", "designation"],
    "company": ["company", "companyname", "company name", "account", "accountname",
                "organization", "organisation", "employer", "businessname"],
    "website": ["website", "companywebsite", "web", "url", "companyurl", "domain",
                "companydomain", "site"],
    "linkedin": ["linkedin", "linkedinurl", "linkedinprofile", "linkedin url",
                 "linkedinlink", "personlinkedin"],
    "industry": ["industry", "sector", "vertical", "companyindustry"],
    "email": ["email", "emailaddress", "email address", "workemail", "work email",
              "businessemail", "primaryemail"],
    "phone": ["phone", "phonenumber", "phone number", "mobile", "telephone", "tel",
              "directphone", "workphone", "contactnumber"],
    "description": ["description", "notes", "about", "companydescription", "bio",
                    "summary", "keywords"],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Precompute normalized alias -> field lookup.
_LOOKUP: dict[str, str] = {}
for _field, _names in _ALIASES.items():
    for _n in _names:
        _LOOKUP[_norm(_n)] = _field


def map_headers(headers: list[str]) -> dict[str, str]:
    """Return {source_header: canonical_field} for headers we recognize.

    Exact (normalized) alias matches win; otherwise a substring heuristic is tried.
    First header to claim a canonical field keeps it.
    """
    mapping: dict[str, str] = {}
    claimed: set[str] = set()

    # Pass 1: exact normalized alias match.
    for h in headers:
        if h is None:
            continue
        key = _norm(str(h))
        field = _LOOKUP.get(key)
        if field and field not in claimed:
            mapping[h] = field
            claimed.add(field)

    # Pass 2: substring heuristic for anything still unclaimed.
    for h in headers:
        if h is None or h in mapping:
            continue
        key = _norm(str(h))
        if not key:
            continue
        for alias_key, field in _LOOKUP.items():
            if field in claimed:
                continue
            if alias_key in key or key in alias_key:
                mapping[h] = field
                claimed.add(field)
                break

    return mapping
