"""Fetch a company's website: homepage + a few interesting internal pages.

Returns combined clean text (and metadata). Fails gracefully — a missing or broken site
yields ``available=False`` rather than raising, so the pipeline can degrade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.scraping.extractor import find_internal_links, html_to_text, page_title

logger = logging.getLogger("leadforge.scraping")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 LeadForge/1.0"
)


@dataclass
class SiteContent:
    url: str
    available: bool = False
    title: str = ""
    text: str = ""
    pages_fetched: list[str] = field(default_factory=list)
    error: str = ""


async def fetch_site(
    website: str | None,
    *,
    timeout: float = 15.0,
    max_pages: int = 3,
    per_page_chars: int = 4000,
) -> SiteContent:
    if not website:
        return SiteContent(url="", error="no website")

    headers = {"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=headers
    ) as client:
        try:
            resp = await client.get(website)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("scrape failed for %s: %s", website, exc)
            return SiteContent(url=website, error=str(exc))

        home_html = resp.text
        final_url = str(resp.url)
        result = SiteContent(
            url=final_url,
            available=True,
            title=page_title(home_html),
            pages_fetched=[final_url],
        )
        parts = [html_to_text(home_html, max_chars=per_page_chars)]

        # Follow a couple of interesting internal pages.
        links = find_internal_links(home_html, final_url, limit=max_pages - 1)
        for link in links:
            try:
                r = await client.get(link)
                r.raise_for_status()
            except httpx.HTTPError:
                continue
            parts.append(html_to_text(r.text, max_chars=per_page_chars))
            result.pages_fetched.append(link)

        result.text = "\n\n".join(p for p in parts if p).strip()
        if not result.text:
            result.available = False
            result.error = "no extractable text"
        return result
