"""
Report Synthesizer (Claude).
Uses the report_synthesizer prompt to generate an evidence-backed executive summary
and enhanced findings with remediation recommendations.

This runs AFTER pattern detection has created findings.
It takes the JSON report skeleton and augments the executive summary + finding summaries.
"""
import json
import uuid
from datetime import datetime

from agents.base import make_manager
from db.nosql import evidence_col
from services.bus import EventBus, EventEnvelope
from utils.logger import get_logger

logger = get_logger(__name__)
_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        _agent = make_manager("report_synthesizer")
    return _agent


async def synthesize_report(audit_id: str, report_skeleton: dict) -> dict:
    """
    Given a report skeleton dict (from report_builder.build_json_report),
    run the Report Synthesizer (Claude) to enhance:
    - executive_summary
    - findings[*].summary (richer, evidence-backed)
    - findings[*].remediation (more specific)

    Returns the enhanced report dict.
    Always preserves requires_human_review=True on privacy findings.
    """
    # Summarize evidence for context (limit tokens)
    evidence_sample = []
    async for ev in evidence_col().find({"audit_id": audit_id}).limit(30):
        evidence_sample.append({
            "source": ev.get("source"),
            "claim": ev.get("claim", "")[:200],
            "url": ev.get("url"),
            "confidence": ev.get("confidence"),
        })

    user_msg = json.dumps({
        "audit_id": audit_id,
        "target_url": report_skeleton.get("url"),
        "risk_score": report_skeleton.get("risk_score"),
        "finding_count": len(report_skeleton.get("findings", [])),
        "findings": [
            {
                "finding_id": f.get("finding_id"),
                "pattern": f.get("pattern"),
                "severity": f.get("severity"),
                "title": f.get("title"),
                "summary": f.get("summary"),
                "affected_urls": f.get("affected_urls", [])[:3],
                "evidence_ids": f.get("evidence_ids", [])[:5],
            }
            for f in report_skeleton.get("findings", [])[:20]
        ],
        "evidence_sample": evidence_sample,
        "instructions": (
            "Synthesize an enhanced report. For each finding, write a clear, evidence-backed summary. "
            "Write an executive summary suitable for a non-technical stakeholder. "
            "Suggest specific, actionable remediation. "
            "Mark any legal conclusions as requiring human review. "
            "Return strict JSON: {\"executive_summary\": str, \"enhanced_findings\": [{\"finding_id\": str, \"summary\": str, \"remediation\": [str]}]}"
        ),
    })

    agent = _get_agent()
    result = await agent.run(user_msg, expect_array=False, audit_id=audit_id)

    if not isinstance(result, dict):
        logger.warning("Report synthesizer returned non-dict", extra={"audit_id": audit_id})
        return report_skeleton

    # Apply enhancements
    enhanced_findings_map = {
        ef["finding_id"]: ef
        for ef in result.get("enhanced_findings", [])
        if "finding_id" in ef
    }

    enhanced_report = dict(report_skeleton)
    if result.get("executive_summary"):
        enhanced_report["executive_summary"] = result["executive_summary"]

    enhanced_findings = []
    for f in report_skeleton.get("findings", []):
        fid = str(f.get("finding_id", ""))
        if fid in enhanced_findings_map:
            enhanced_f = dict(f)
            ef = enhanced_findings_map[fid]
            if ef.get("summary"):
                enhanced_f["summary"] = ef["summary"]
            if ef.get("remediation"):
                enhanced_f["remediation"] = ef["remediation"]
        else:
            enhanced_f = f
        enhanced_findings.append(enhanced_f)

    enhanced_report["findings"] = enhanced_findings
    logger.info("Report synthesized", extra={"audit_id": audit_id,
                                               "findings_enhanced": len(enhanced_findings_map)})
    return enhanced_report


async def run_report_synthesis(audit_id: str, config: dict, bus: EventBus) -> None:
    """
    Full report synthesis pipeline.
    Builds JSON report skeleton → synthesizes with Claude → stores → publishes report.generated.
    """
    import uuid as _uuid
    try:
        from tools.report_builder import build_json_report, store_report
        skeleton = await build_json_report(audit_id)

        # Enhance with Claude synthesis
        enhanced = await synthesize_report(audit_id, skeleton)

        # Store JSON report
        import json as _json
        await store_report(audit_id, "json", _json.dumps(enhanced, indent=2, default=str), "application/json")

        # Publish report.generated
        envelope = EventEnvelope(
            event_type="report.generated",
            audit_id=_uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={"risk_score": enhanced.get("risk_score", 0.0), "finding_count": len(enhanced.get("findings", []))},
        )
        await bus.publish("report.generated", envelope)
        logger.info("Report synthesis complete", extra={"audit_id": audit_id})
    except Exception as exc:
        logger.error("Report synthesis failed", extra={"audit_id": audit_id, "error": str(exc)}, exc_info=exc)
        fail_env = EventEnvelope(
            event_type="audit.failed",
            audit_id=_uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={"error": str(exc)},
        )
        await bus.publish("audit.failed", fail_env)
