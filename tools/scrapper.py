"""
Web scraping utilities: URL normalization, robots.txt, sitemap parsing, link extraction.
"""
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin, urlunparse

import httpx
from bs4 import BeautifulSoup

from models.taxonomy import PageType
from utils.logger import get_logger

logger = get_logger(__name__)

_HTTP_HEADERS = {
    "User-Agent": "PatternProof-Audit/0.1 (+https://patternproof.io/bot)",
}

_CLIENT_DEFAULTS = dict(timeout=10, follow_redirects=True, headers=_HTTP_HEADERS)


def normalize_url(url: str, base_url: str | None = None) -> str | None:
    """
    Normalize a URL: resolve relative URLs, remove fragments, lowercase scheme+host.
    Returns None if URL is not http/https or is invalid.
    """
    if not url or not isinstance(url, str):
        return None

    try:
        if base_url:
            url = urljoin(base_url, url)

        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return None

        if not parsed.netloc:
            return None

        # Lowercase scheme and host; preserve path, query, params as-is
        normalized = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",  # drop fragment
        ))
        return normalized
    except Exception as exc:
        logger.debug("URL normalization failed", extra={"error": str(exc)})
        return None


async def fetch_robots_txt(domain_root: str) -> str | None:
    """Fetch robots.txt. Returns text content or None."""
    robots_url = domain_root.rstrip("/") + "/robots.txt"
    try:
        async with httpx.AsyncClient(**_CLIENT_DEFAULTS) as client:
            resp = await client.get(robots_url)
            if resp.status_code == 200:
                return resp.text
            logger.debug(
                "robots.txt not found",
                extra={"url": robots_url, "status": resp.status_code},
            )
    except Exception as exc:
        logger.debug("robots.txt fetch failed", extra={"url": robots_url, "error": str(exc)})
    return None


def parse_sitemap_urls(sitemap_text: str, base_url: str) -> list[str]:
    """Extract URLs from sitemap XML (handles sitemap index too)."""
    urls: list[str] = []

    # Try stdlib XML first — handles both <urlset> and <sitemapindex>
    try:
        root = ET.fromstring(sitemap_text)
        # Strip namespace to simplify tag matching
        for elem in root.iter():
            # Tag may look like "{http://www.sitemaps.org/schemas/sitemap/0.9}loc" or just "loc"
            local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local == "loc" and elem.text:
                loc = elem.text.strip()
                norm = normalize_url(loc, base_url)
                if norm:
                    urls.append(norm)
        return urls
    except ET.ParseError:
        pass

    # Fallback: html.parser (works because BeautifulSoup treats <loc> as a tag)
    try:
        soup = BeautifulSoup(sitemap_text, "html.parser")
        for tag in soup.find_all("loc"):
            loc = tag.get_text(strip=True)
            if loc:
                norm = normalize_url(loc, base_url)
                if norm:
                    urls.append(norm)
        return urls
    except Exception as exc:
        logger.debug("Sitemap parsing failed", extra={"error": str(exc)})

    return urls


async def fetch_sitemap(domain_root: str) -> list[str]:
    """Fetch /sitemap.xml and extract URLs. Returns [] on failure."""
    sitemap_url = domain_root.rstrip("/") + "/sitemap.xml"
    try:
        async with httpx.AsyncClient(**_CLIENT_DEFAULTS) as client:
            resp = await client.get(sitemap_url)
            if resp.status_code == 200:
                urls = parse_sitemap_urls(resp.text, domain_root)
                logger.debug(
                    "Sitemap fetched",
                    extra={"url": sitemap_url, "count": len(urls)},
                )
                return urls
            logger.debug(
                "Sitemap not found",
                extra={"url": sitemap_url, "status": resp.status_code},
            )
    except Exception as exc:
        logger.debug("Sitemap fetch failed", extra={"url": sitemap_url, "error": str(exc)})
    return []


def extract_links_from_html(html: str, base_url: str) -> list[str]:
    """Extract all <a href> and form action links from HTML. Return normalized absolute URLs."""
    links: list[str] = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # <a href="...">
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            norm = normalize_url(href, base_url)
            if norm:
                links.append(norm)

        # <form action="...">
        for tag in soup.find_all("form", action=True):
            action = tag["action"].strip()
            norm = normalize_url(action, base_url)
            if norm:
                links.append(norm)

    except Exception as exc:
        logger.debug("Link extraction failed", extra={"error": str(exc)})

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique.append(link)
    return unique


# ---------------------------------------------------------------------------
# Page classification signals
# ---------------------------------------------------------------------------

_PATH_PATTERNS: list[tuple[re.Pattern, PageType]] = [
    # Checkout before cart (more specific)
    (re.compile(r"/(checkout|payment|pay|order-confirm|order-summary)", re.I), PageType.CHECKOUT),
    (re.compile(r"/(cart|basket|bag|shopping-bag)", re.I), PageType.CART),
    (re.compile(r"/(product|item|p/|detail|dp/|listing|sku)", re.I), PageType.PRODUCT),
    (re.compile(r"/(signup|register|create[-_]account|join)", re.I), PageType.SIGNUP),
    (re.compile(r"/(login|sign[-_]in|signin|log[-_]in)", re.I), PageType.LOGIN),
    (re.compile(r"/(account|profile|dashboard|my[-_]account|me/)", re.I), PageType.ACCOUNT),
    (re.compile(r"/(subscri|plan|billing|upgrade|pricing)", re.I), PageType.SUBSCRIPTION),
    (re.compile(r"/(cancel|cancellation|unsubscribe|downgrade)", re.I), PageType.CANCELLATION),
    (re.compile(r"/(privacy[-_]policy|privacy|data[-_]policy|gdpr|dpdp|ccpa)", re.I), PageType.PRIVACY_POLICY),
    (re.compile(r"/(consent|cookie[-_]policy|cookie|permissions)", re.I), PageType.CONSENT),
    (re.compile(r"/(settings|preferences|config)", re.I), PageType.SETTINGS),
]

_TITLE_PATTERNS: list[tuple[re.Pattern, PageType]] = [
    (re.compile(r"\b(checkout|payment|place order)\b", re.I), PageType.CHECKOUT),
    (re.compile(r"\b(cart|basket|shopping bag)\b", re.I), PageType.CART),
    (re.compile(r"\b(product|buy now|add to cart)\b", re.I), PageType.PRODUCT),
    (re.compile(r"\b(sign up|register|create account)\b", re.I), PageType.SIGNUP),
    (re.compile(r"\b(log in|login|sign in|signin)\b", re.I), PageType.LOGIN),
    (re.compile(r"\b(account|profile|dashboard)\b", re.I), PageType.ACCOUNT),
    (re.compile(r"\b(subscription|billing|upgrade|pricing|plans?)\b", re.I), PageType.SUBSCRIPTION),
    (re.compile(r"\b(cancel|cancellation|unsubscribe)\b", re.I), PageType.CANCELLATION),
    (re.compile(r"\b(privacy policy|privacy|data policy)\b", re.I), PageType.PRIVACY_POLICY),
    (re.compile(r"\b(cookie(s| settings| policy)?|consent|gdpr)\b", re.I), PageType.CONSENT),
    (re.compile(r"\b(settings|preferences)\b", re.I), PageType.SETTINGS),
]

_HTML_PATTERNS: list[tuple[re.Pattern, PageType]] = [
    (re.compile(r'id=["\']checkout|class=["\'][^"\']*checkout', re.I), PageType.CHECKOUT),
    (re.compile(r'id=["\']cart|class=["\'][^"\']*\bcart\b', re.I), PageType.CART),
    (re.compile(r'id=["\']signup|class=["\'][^"\']*signup', re.I), PageType.SIGNUP),
    (re.compile(r'type=["\']password', re.I), PageType.LOGIN),
    (re.compile(r'id=["\']login|class=["\'][^"\']*\blogin\b', re.I), PageType.LOGIN),
]


def classify_page_type(url: str, title: str = "", html_snippet: str = "") -> str:
    """
    Classify page into PageType. Use URL path and title/HTML signals.
    Return PageType string value.
    """
    parsed = urlparse(url)
    path = parsed.path or "/"

    # Root path is home
    if path in ("/", ""):
        return PageType.HOME.value

    # Check URL path against patterns (highest confidence)
    for pattern, page_type in _PATH_PATTERNS:
        if pattern.search(path):
            return page_type.value

    # Check title signals (medium confidence)
    if title:
        for pattern, page_type in _TITLE_PATTERNS:
            if pattern.search(title):
                return page_type.value

    # Check HTML snippet signals (lower confidence, limited to first ~2000 chars)
    if html_snippet:
        for pattern, page_type in _HTML_PATTERNS:
            if pattern.search(html_snippet):
                return page_type.value

        # Try to extract <title> from the snippet if title wasn't passed
        if not title:
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html_snippet, re.I | re.S)
            if title_match:
                extracted_title = title_match.group(1).strip()
                for pattern, page_type in _TITLE_PATTERNS:
                    if pattern.search(extracted_title):
                        return page_type.value

    return PageType.OTHER.value
