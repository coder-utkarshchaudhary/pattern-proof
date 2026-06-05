"""
Discovery Service.
Discovers pages for an audit: robots/sitemap, BFS link crawl, SPA route discovery (Playwright).
Outputs: pages records in MongoDB + discovery.completed event.
"""
import asyncio
import uuid
from datetime import datetime
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from api.dependencies import validate_audit_url
from config import settings
from db.nosql import pages_col
from models.taxonomy import PageType
from services.bus import EventBus, EventEnvelope
from tools.scrapper import (
    classify_page_type,
    extract_links_from_html,
    fetch_robots_txt,
    fetch_sitemap,
    normalize_url,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class DiscoveryService:
    def __init__(self, bus: EventBus):
        self.bus = bus

    async def run(self, audit_id: str, root_url: str, config: dict) -> dict:
        """
        Run discovery for an audit.
        config keys: max_pages, max_depth, include_dynamic
        Returns summary: {page_count, pages}
        """
        max_pages = config.get("max_pages", 25)
        max_depth = config.get("max_depth", 3)
        parsed = urlparse(root_url)
        domain = parsed.netloc
        domain_root = f"{parsed.scheme}://{domain}"

        logger.info("Discovery started", extra={"audit_id": audit_id, "url": root_url})

        discovered: list[dict] = []
        visited: set[str] = set()
        queue: list[tuple[str, int, str | None]] = [(root_url, 0, None)]  # (url, depth, parent)

        # --- robots.txt ---
        robots_text = await fetch_robots_txt(domain_root) or ""
        disallowed: set[str] = set()
        for line in robots_text.splitlines():
            if line.lower().startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    disallowed.add(path)

        # --- sitemap ---
        sitemap_urls = await fetch_sitemap(domain_root)
        for su in sitemap_urls:
            norm = normalize_url(su, domain_root)
            if norm and norm not in visited and len(queue) + len(visited) < max_pages * 2:
                queue.append((norm, 1, root_url))

        async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                     headers={"User-Agent": "PatternProof-Audit/0.1"}) as client:
            while queue and len(discovered) < max_pages:
                url, depth, parent = queue.pop(0)
                if url in visited:
                    continue
                # Check robots disallow
                parsed_url = urlparse(url)
                if any(parsed_url.path.startswith(d) for d in disallowed):
                    logger.debug("robots.txt disallowed", extra={"url": url, "audit_id": audit_id})
                    visited.add(url)
                    continue
                # Only follow same domain
                if urlparse(url).netloc != domain:
                    continue
                visited.add(url)

                # SSRF protection: re-validate URL before fetching
                try:
                    validate_audit_url(url)
                except HTTPException as exc:
                    logger.debug(
                        "URL blocked by SSRF check",
                        extra={"url": url, "audit_id": audit_id, "reason": exc.detail},
                    )
                    continue

                try:
                    resp = await client.get(url)
                    html = resp.text
                except Exception as exc:
                    logger.warning("Fetch failed", extra={"url": url, "error": str(exc), "audit_id": audit_id})
                    continue

                page_type = classify_page_type(url, html_snippet=html[:2000])
                page_id = str(uuid.uuid4())
                page_doc = {
                    "_id": page_id,
                    "audit_id": audit_id,
                    "url": url,
                    "normalized_url": url,
                    "page_type": page_type,
                    "depth": depth,
                    "discovered_from": parent,
                    "artifact_uris": [],
                    "created_at": datetime.utcnow().isoformat(),
                }
                await pages_col().insert_one(page_doc)
                discovered.append({"page_id": page_id, "url": url, "page_type": page_type, "depth": depth})
                logger.info("Page discovered", extra={"audit_id": audit_id, "url": url, "page_type": page_type})

                if depth < max_depth:
                    links = extract_links_from_html(html, url)
                    for link in links:
                        norm = normalize_url(link, url)
                        if norm and norm not in visited and urlparse(norm).netloc == domain:
                            queue.append((norm, depth + 1, url))

        # Optionally: SPA discovery via Playwright if include_dynamic and few pages found
        if config.get("include_dynamic", True) and len(discovered) < 3:
            spa_pages = await self._spa_discover(audit_id, root_url, domain, domain_root, max_pages, visited, discovered)
            discovered.extend(spa_pages)

        logger.info("Discovery complete", extra={"audit_id": audit_id, "page_count": len(discovered)})
        return {"page_count": len(discovered), "pages": discovered}

    async def _spa_discover(self, audit_id, root_url, domain, domain_root, max_pages, visited, already_found):
        """Try Playwright for SPA route discovery."""
        found = []
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                hrefs: set[str] = set()
                page.on("response", lambda r: None)  # no-op
                await page.goto(root_url, wait_until="networkidle", timeout=20000)
                # Extract links from rendered DOM
                links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                for link in links:
                    from tools.scrapper import normalize_url as nu
                    from urllib.parse import urlparse as up
                    norm = nu(link, root_url)
                    if norm and norm not in visited and up(norm).netloc == domain:
                        hrefs.add(norm)
                await browser.close()
                import uuid as _uuid
                from datetime import datetime as _dt
                for href in list(hrefs)[:max_pages - len(already_found)]:
                    if href not in visited:
                        # SSRF protection: re-validate before storing
                        try:
                            validate_audit_url(href)
                        except HTTPException as exc:
                            logger.debug(
                                "SPA URL blocked by SSRF check",
                                extra={"url": href, "audit_id": audit_id, "reason": exc.detail},
                            )
                            continue
                        visited.add(href)
                        from tools.scrapper import classify_page_type as cpt
                        page_id = str(_uuid.uuid4())
                        doc = {
                            "_id": page_id, "audit_id": audit_id, "url": href,
                            "normalized_url": href, "page_type": cpt(href),
                            "depth": 1, "discovered_from": root_url,
                            "artifact_uris": [], "created_at": _dt.utcnow().isoformat(),
                        }
                        from db.nosql import pages_col as pc
                        await pc().insert_one(doc)
                        found.append({"page_id": page_id, "url": href, "page_type": cpt(href), "depth": 1})
        except Exception as exc:
            logger.warning("SPA discovery failed", extra={"audit_id": audit_id, "error": str(exc)})
        return found


async def run_discovery(audit_id: str, root_url: str, config: dict, bus: EventBus) -> None:
    """
    Entry point called by orchestrator on discovery.started event.
    Publishes discovery.completed when done, or audit.failed on error.
    """
    import uuid as _uuid
    svc = DiscoveryService(bus)
    try:
        result = await svc.run(audit_id, root_url, config)
        envelope = EventEnvelope(
            event_type="discovery.completed",
            audit_id=_uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={**result, "config": config, "url": root_url},
        )
        await bus.publish("discovery.completed", envelope)
    except Exception as exc:
        logger.error("Discovery failed", extra={"audit_id": audit_id, "error": str(exc)}, exc_info=exc)
        fail_env = EventEnvelope(
            event_type="audit.failed",
            audit_id=_uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={"error": str(exc)},
        )
        await bus.publish("audit.failed", fail_env)
