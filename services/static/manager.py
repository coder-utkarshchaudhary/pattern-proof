"""
Static Analysis Manager (Claude).
Coordinates DOM, CSS, OCR, accessibility, visual analyzers.
Normalizes outputs into a unified evidence bundle.
"""
import asyncio
import uuid as _uuid

from backend.services.static.snapshot import capture_snapshot
from backend.services.static.dom_analysis import analyze_dom
from backend.services.static.css_analysis import analyze_css
from backend.services.static.visual_analysis import analyze_visual
from backend.services.static.ocr_analysis import analyze_ocr
from backend.services.static.accessibility_analysis import analyze_accessibility
from backend.agents.bus import EventBus, EventEnvelope
from backend.db.nosql import pages_col
from backend.utils.logger import get_logger

logger = get_logger(__name__)


async def run_static_analysis(
    audit_id: str, pages: list, config: dict, bus: EventBus
) -> None:
    """
    Run static analysis on all discovered pages.
    Publishes static.completed when done, audit.failed on error.
    """
    try:
        total_evidence: list = []
        taxonomy_scope = config.get(
            "jurisdiction_scopes", ["mathur", "dpdp", "ccpa"]
        )
        viewport = {
            "width": config.get("viewport_width", 1366),
            "height": config.get("viewport_height", 768),
        }

        for page in pages:
            page_id = page["page_id"]
            url = page["url"]
            logger.info(
                "Static analysis: capturing snapshot",
                extra={"audit_id": audit_id, "page_id": page_id},
            )

            # Capture all artifacts
            artifacts = await capture_snapshot(page_id, audit_id, url, viewport)

            # Update page record with artifact URIs
            await pages_col().update_one(
                {"_id": page_id},
                {"$set": {"artifact_uris": list(artifacts.values())}},
            )

            # Run all five analyzers concurrently
            results = await asyncio.gather(
                analyze_dom(
                    audit_id,
                    page_id,
                    url,
                    artifacts.get("dom_uri", ""),
                    artifacts.get("a11y_tree_uri", ""),
                    taxonomy_scope,
                ),
                analyze_css(
                    audit_id,
                    page_id,
                    url,
                    artifacts.get("css_uri", ""),
                    taxonomy_scope,
                ),
                analyze_visual(
                    audit_id,
                    page_id,
                    url,
                    artifacts.get("screenshot_uri", ""),
                    taxonomy_scope,
                ),
                analyze_ocr(
                    audit_id,
                    page_id,
                    url,
                    artifacts.get("ocr_text_uri", ""),
                    artifacts.get("screenshot_uri", ""),
                    taxonomy_scope,
                ),
                analyze_accessibility(
                    audit_id,
                    page_id,
                    url,
                    artifacts.get("a11y_tree_uri", ""),
                    taxonomy_scope,
                ),
                return_exceptions=True,
            )

            for r in results:
                if isinstance(r, list):
                    total_evidence.extend(r)
                elif isinstance(r, Exception):
                    logger.warning(
                        "Analyzer error",
                        extra={"audit_id": audit_id, "error": str(r)},
                    )

        envelope = EventEnvelope(
            event_type="static.completed",
            audit_id=_uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={
                "evidence_count": len(total_evidence),
                "config": config,
                "pages": pages,
            },
        )
        await bus.publish("static.completed", envelope)
        logger.info(
            "Static analysis complete",
            extra={"audit_id": audit_id, "evidence_count": len(total_evidence)},
        )

    except Exception as exc:
        logger.error(
            "Static analysis failed",
            extra={"audit_id": audit_id, "error": str(exc)},
            exc_info=exc,
        )
        fail_env = EventEnvelope(
            event_type="audit.failed",
            audit_id=_uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={"error": str(exc)},
        )
        await bus.publish("audit.failed", fail_env)
