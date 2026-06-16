"""OCR analysis via Gemma 4 31B (LLM-assisted OCR; swap point for pytesseract)."""
import json
import uuid
from datetime import datetime

from backend.agents.base import make_analyzer
from backend.db.nosql import evidence_col
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = make_analyzer("ocr_analyzer")
    return _agent


async def analyze_ocr(
    audit_id: str,
    page_id: str,
    url: str,
    ocr_text_uri: str,
    screenshot_uri: str,
    taxonomy_scope: list,
) -> list:
    """
    Run OCR analyzer (Gemma) on visible text and screenshot artifacts.
    Returns list of evidence records stored in MongoDB.
    """
    agent = _get_agent()
    user_msg = json.dumps(
        {
            "audit_id": audit_id,
            "page_id": page_id,
            "url": url,
            "ocr_text_uri": ocr_text_uri,
            "screenshot_uri": screenshot_uri,
            "taxonomy_scope": taxonomy_scope,
            "instructions": (
                "Analyze the OCR text and screenshot. Return the evidence JSON array."
            ),
        }
    )
    result = await agent.run(user_msg, expect_array=False, audit_id=audit_id)

    # Analyzers emit {"evidence": [...]}, manager emits {"evidence_bundle": [...]}.
    # A bare JSON array is also accepted for resilience.
    if isinstance(result, list):
        evidence_list = result
    elif isinstance(result, dict):
        evidence_list = result.get("evidence_bundle") or result.get("evidence") or []
    else:
        evidence_list = []

    # Build the fallback artifact list from both OCR artifacts (filter empties).
    fallback_uris = [u for u in [ocr_text_uri, screenshot_uri] if u]

    stored = []
    for ev in evidence_list:
        # Build artifact_uris; filter empty strings; fall back to both OCR artifacts.
        raw_uris = ev.get("artifact_uris") or []
        artifact_uris = [u for u in raw_uris if u] or fallback_uris

        ev_doc = {
            "_id": str(uuid.uuid4()),
            "audit_id": audit_id,
            "page_id": page_id,
            "source": "ocr",
            "taxonomy_scope": taxonomy_scope,
            "evidence_type": ev.get("evidence_type", "ocr_observation"),
            "url": url,
            "selector": ev.get("selector"),
            "region": ev.get("region"),
            "claim": ev.get("claim") or ev.get("risk_signal", ""),
            "raw_observation": ev.get("raw_observation", ""),
            "confidence": float(ev.get("confidence", 0.5)),
            "artifact_uris": artifact_uris,
            "metadata": ev.get("metadata", {}),
            "created_at": datetime.utcnow().isoformat(),
        }
        await evidence_col().insert_one(ev_doc)
        stored.append(ev_doc)

    logger.info(
        "OCR analysis done",
        extra={
            "audit_id": audit_id,
            "page_id": page_id,
            "evidence_count": len(stored),
        },
    )
    return stored
