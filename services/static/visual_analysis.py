"""Visual analysis via Gemma 4 31B."""
import json
import uuid
from datetime import datetime

from agents.base import make_analyzer
from db.nosql import evidence_col
from utils.logger import get_logger

logger = get_logger(__name__)

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = make_analyzer("visual_analyzer")
    return _agent


async def analyze_visual(
    audit_id: str,
    page_id: str,
    url: str,
    screenshot_uri: str,
    taxonomy_scope: list,
) -> list:
    """
    Run visual analyzer (Gemma) on page screenshot.
    Returns list of evidence records stored in MongoDB.
    """
    agent = _get_agent()
    user_msg = json.dumps(
        {
            "audit_id": audit_id,
            "page_id": page_id,
            "url": url,
            "screenshot_uri": screenshot_uri,
            "taxonomy_scope": taxonomy_scope,
            "instructions": (
                "Analyze the screenshot. Return the evidence JSON array."
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

    stored = []
    for ev in evidence_list:
        # Build artifact_uris; filter empty strings; fall back to screenshot_uri.
        raw_uris = ev.get("artifact_uris") or []
        artifact_uris = (
            [u for u in raw_uris if u] or ([screenshot_uri] if screenshot_uri else [])
        )

        ev_doc = {
            "_id": str(uuid.uuid4()),
            "audit_id": audit_id,
            "page_id": page_id,
            "source": "visual",
            "taxonomy_scope": taxonomy_scope,
            "evidence_type": ev.get("evidence_type", "visual_observation"),
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
        "Visual analysis done",
        extra={
            "audit_id": audit_id,
            "page_id": page_id,
            "evidence_count": len(stored),
        },
    )
    return stored
