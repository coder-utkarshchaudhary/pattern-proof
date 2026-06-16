"""
Snapshot capture: DOM, CSS, accessibility tree, screenshot, OCR text.
Uploads artifacts to Supabase Storage under audits/{audit_id}/pages/{page_id}/.
"""
import json

from backend.utils.logger import get_logger
from backend.config import settings  # noqa: F401 — imported for consistency with foundation

logger = get_logger(__name__)


async def capture_snapshot(page_id: str, audit_id: str, url: str, viewport: dict) -> dict:
    """
    Capture DOM, CSS computed styles, accessibility tree, screenshot.
    Upload to Supabase Storage. Return artifact_uris dict.

    Returns:
        {
            "dom_uri": "str",
            "css_uri": "str",
            "a11y_tree_uri": "str",
            "screenshot_uri": "str",
            "ocr_text_uri": "str",  # raw screenshot-based text placeholder
        }
    """
    from playwright.async_api import async_playwright

    artifacts: dict = {}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={
                    "width": viewport.get("width", 1366),
                    "height": viewport.get("height", 768),
                }
            )
            pg = await context.new_page()
            await pg.goto(url, wait_until="networkidle", timeout=30000)

            # DOM snapshot
            dom_content = await pg.content()
            artifacts["dom_uri"] = await _upload_text(
                dom_content, audit_id, page_id, "dom.html"
            )

            # Computed CSS (sample key elements)
            css_data = await pg.evaluate("""
                () => {
                    const els = document.querySelectorAll(
                        'button,input,a,form,[role="dialog"]'
                    );
                    return Array.from(els).slice(0, 100).map(el => ({
                        tag: el.tagName, id: el.id, classes: el.className,
                        computed: Object.fromEntries(
                            [
                                'display', 'visibility', 'opacity', 'color',
                                'background-color', 'font-size', 'position',
                                'z-index', 'pointer-events'
                            ].map(p => [p, getComputedStyle(el).getPropertyValue(p)])
                        )
                    }));
                }
            """)
            artifacts["css_uri"] = await _upload_text(
                json.dumps(css_data, indent=2), audit_id, page_id, "css.json"
            )

            # Accessibility tree
            a11y = await pg.accessibility.snapshot(interesting_only=False)
            artifacts["a11y_tree_uri"] = await _upload_text(
                json.dumps(a11y or {}, indent=2), audit_id, page_id, "a11y.json"
            )

            # Screenshot (PNG)
            screenshot_bytes = await pg.screenshot(full_page=True, type="png")
            artifacts["screenshot_uri"] = await _upload_bytes(
                screenshot_bytes, audit_id, page_id, "screenshot.png", "image/png"
            )

            # OCR text placeholder (visible text for LLM-assisted OCR)
            visible_text = await pg.evaluate("() => document.body.innerText")
            artifacts["ocr_text_uri"] = await _upload_text(
                visible_text, audit_id, page_id, "ocr_text.txt"
            )

            await browser.close()
            logger.info(
                "Snapshot captured",
                extra={"audit_id": audit_id, "page_id": page_id},
            )
    except Exception as exc:
        logger.error(
            "Snapshot capture failed",
            extra={"audit_id": audit_id, "page_id": page_id, "error": str(exc)},
            exc_info=exc,
        )

    return artifacts


async def _upload_text(
    content: str, audit_id: str, page_id: str, filename: str
) -> str:
    """Upload text content to Supabase Storage. Return storage path."""
    path = f"audits/{audit_id}/pages/{page_id}/{filename}"
    try:
        from backend.db.sql import get_supabase

        client = await get_supabase()
        await client.storage.from_("pattern-proof").upload(
            path,
            content.encode("utf-8"),
            file_options={
                "content-type": "text/plain; charset=utf-8",
                "upsert": "true",
            },
        )
    except Exception as exc:
        logger.warning(
            "Storage upload failed",
            extra={"path": path, "error": str(exc)},
        )
    return f"supabase://pattern-proof/{path}"


async def _upload_bytes(
    data: bytes, audit_id: str, page_id: str, filename: str, content_type: str
) -> str:
    """Upload raw bytes to Supabase Storage. Return storage path."""
    path = f"audits/{audit_id}/pages/{page_id}/{filename}"
    try:
        from backend.db.sql import get_supabase

        client = await get_supabase()
        await client.storage.from_("pattern-proof").upload(
            path,
            data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
    except Exception as exc:
        logger.warning(
            "Storage upload failed",
            extra={"path": path, "error": str(exc)},
        )
    return f"supabase://pattern-proof/{path}"
