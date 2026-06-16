"""
Report Builder.
Assembles JSON and Markdown reports from Supabase + MongoDB data.
PDF generation is in pdf_generator.py.
"""
import json
from datetime import datetime
from uuid import UUID
from backend.db.sql import get_supabase, AuditRepo, FindingRepo, ReportRepo
from backend.db.nosql import evidence_col, pages_col, states_col
from backend.utils.logger import get_logger

logger = get_logger(__name__)

async def build_json_report(audit_id: str) -> dict:
    """
    Build a complete JSON report dict for an audit.
    Pulls findings from Supabase, evidence/pages/states counts from MongoDB.
    """
    client = await get_supabase()
    audit = await AuditRepo(client).get(audit_id)
    if not audit:
        raise ValueError(f"Audit {audit_id} not found")

    findings_raw = await FindingRepo(client).list_for_audit(audit_id)

    # Parse JSON fields stored as strings in Supabase
    findings = []
    for f in findings_raw:
        findings.append({
            "finding_id": f["id"],
            "audit_id": audit_id,
            "pattern": f["pattern"],
            "taxonomy_scope": _parse_json_field(f.get("taxonomy_scope"), []),
            "category": f["category"],
            "severity": f["severity"],
            "confidence": f["confidence"],
            "title": f["title"],
            "summary": f["summary"],
            "affected_urls": _parse_json_field(f.get("affected_urls"), []),
            "evidence_ids": _parse_json_field(f.get("evidence_ids"), []),
            "reproduction_steps": _parse_json_field(f.get("reproduction_steps"), []),
            "remediation": _parse_json_field(f.get("remediation"), []),
            "requires_human_review": f.get("requires_human_review", True),
        })

    # MongoDB counts
    evidence_count = await evidence_col().count_documents({"audit_id": audit_id})
    page_count = await pages_col().count_documents({"audit_id": audit_id})
    state_count = await states_col().count_documents({"audit_id": audit_id})

    # Compute risk score from findings
    from backend.models.taxonomy import SEVERITY_WEIGHTS, EVIDENCE_DIVERSITY_MULTIPLIERS, EVIDENCE_DIVERSITY_MAX_MULTIPLIER
    risk_score = 0.0
    for f in findings:
        weight = SEVERITY_WEIGHTS.get(f["severity"], 5.0)
        risk_score += weight * f["confidence"]
    risk_score = round(min(risk_score, 100.0), 2)

    # Artifact URIs (reports already stored)
    reports_res = await client.table("reports").select("report_uri").eq("audit_id", audit_id).execute()
    artifact_uris = [r["report_uri"] for r in (reports_res.data or [])]

    return {
        "audit_id": audit_id,
        "url": audit["url"],
        "status": "completed",
        "risk_score": risk_score,
        "generated_at": datetime.utcnow().isoformat(),
        "executive_summary": _generate_executive_summary(findings, risk_score, audit["url"]),
        "findings": findings,
        "evidence_count": evidence_count,
        "page_count": page_count,
        "state_count": state_count,
        "privacy_taxonomy_summary": [],  # populated by pattern detection phase
        "artifact_uris": artifact_uris,
        "limitations": [
            "This audit covers observable website behaviour only.",
            "DPDP and CCPA/CPRA classifications are audit signals, not legal advice.",
            "Dynamic exploration is bounded by time and action budgets.",
            "Findings marked requires_human_review require expert verification.",
        ],
    }


def _generate_executive_summary(findings: list[dict], risk_score: float, url: str) -> str:
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        severity_counts[f.get("severity", "low")] += 1

    summary_parts = [f"Pattern Proof audit of {url} completed."]
    if not findings:
        summary_parts.append("No dark patterns were detected in the audit scope.")
    else:
        parts = [f"{v} {k}" for k, v in severity_counts.items() if v > 0]
        summary_parts.append(f"Detected {len(findings)} findings: {', '.join(parts)}.")
    summary_parts.append(f"Overall risk score: {risk_score:.1f}/100.")
    if risk_score >= 70:
        summary_parts.append("HIGH RISK: Immediate remediation recommended.")
    elif risk_score >= 40:
        summary_parts.append("MEDIUM RISK: Review and address findings.")
    else:
        summary_parts.append("LOW RISK: Address findings at next review cycle.")
    return " ".join(summary_parts)


def _parse_json_field(value, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


async def build_markdown_report(audit_id: str) -> str:
    """Build a human-readable Markdown report."""
    report = await build_json_report(audit_id)
    lines = [
        f"# Pattern Proof Audit Report",
        f"",
        f"**URL**: {report['url']}",
        f"**Audit ID**: {audit_id}",
        f"**Generated**: {report['generated_at']}",
        f"**Risk Score**: {report['risk_score']}/100",
        f"",
        f"## Executive Summary",
        f"",
        report["executive_summary"],
        f"",
        f"## Findings ({len(report['findings'])})",
        f"",
    ]

    for i, f in enumerate(report["findings"], 1):
        lines += [
            f"### {i}. {f['title']} [{f['severity'].upper()}]",
            f"",
            f"**Pattern**: `{f['pattern']}`  ",
            f"**Category**: {f['category']}  ",
            f"**Confidence**: {f['confidence']:.0%}  ",
            f"**Requires Human Review**: {'Yes' if f['requires_human_review'] else 'No'}",
            f"",
            f"**Summary**: {f['summary']}",
            f"",
        ]
        if f["reproduction_steps"]:
            lines.append("**Reproduction Steps**:")
            for step in f["reproduction_steps"]:
                lines.append(f"- {step}")
            lines.append("")
        if f["remediation"]:
            lines.append("**Remediation**:")
            for rem in f["remediation"]:
                lines.append(f"- {rem}")
            lines.append("")
        if f["affected_urls"]:
            lines.append(f"**Affected URLs**: {', '.join(f['affected_urls'][:5])}")
            lines.append("")

    lines += [
        "## Limitations",
        "",
    ]
    for lim in report["limitations"]:
        lines.append(f"- {lim}")
    lines.append("")
    lines.append("---")
    lines.append("*This report was generated by Pattern Proof. It does not constitute legal advice.*")

    return "\n".join(lines)


async def store_report(audit_id: str, fmt: str, content: str | bytes, content_type: str) -> str:
    """Upload report to Supabase Storage and record in reports table. Returns storage URI."""
    path = f"audits/{audit_id}/reports/report.{fmt}"
    try:
        client = await get_supabase()
        data = content.encode("utf-8") if isinstance(content, str) else content
        await client.storage.from_("pattern-proof").upload(
            path, data,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        uri = f"supabase://pattern-proof/{path}"
        await ReportRepo(client).create(audit_id, fmt, uri)
        logger.info("Report stored", extra={"audit_id": audit_id, "format": fmt, "path": path})
        return uri
    except Exception as exc:
        logger.error("Report storage failed", extra={"audit_id": audit_id, "error": str(exc)})
        return ""
