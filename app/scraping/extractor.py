"""Turn raw HTML into clean, LLM-friendly text and discover useful internal links."""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

_DROP_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "form", "svg")

# Internal pages worth following for company research.
_INTERESTING = ("about", "company", "service", "product", "solution", "what-we-do",
                "platform", "industries")


def html_to_text(html: str, *, max_chars: int = 6000) -> str:
    tree = HTMLParser(html)
    for tag in _DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    body = tree.body or tree.root
    if body is None:
        return ""
    text = body.text(separator=" ", strip=True)
    text = " ".join(text.split())
    return text[:max_chars]


def page_title(html: str) -> str:
    tree = HTMLParser(html)
    node = tree.css_first("title")
    return node.text(strip=True) if node else ""


def find_internal_links(html: str, base_url: str, *, limit: int = 4) -> list[str]:
    """Return absolute URLs of interesting same-domain pages (about/services/...)."""
    tree = HTMLParser(html)
    base_host = urlparse(base_url).netloc.lower()
    found: list[str] = []
    seen: set[str] = set()
    for a in tree.css("a"):
        href = a.attributes.get("href")
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != base_host:
            continue
        path = parsed.path.lower()
        if not any(k in path for k in _INTERESTING):
            continue
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if clean in seen or clean.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(clean)
        found.append(clean)
        if len(found) >= limit:
            break
    return found
