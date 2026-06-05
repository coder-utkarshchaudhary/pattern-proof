"""
Pattern Detection Engine.
Pipeline: Evidence → Normalizer → Mathur Detector → Privacy Taxonomy Classifier → Findings
Risk scoring per System Design Document weights.
"""
from __future__ import annotations
import json
import uuid
from typing import Any

from db.nosql import evidence_col
from db.sql import get_supabase, FindingRepo
from agents.base import make_manager
from models.taxonomy import (
    MathurCategory, MathurPattern, DPDPDimension, CCPADimension,
    FindingSeverity, JurisdictionScope,
    SEVERITY_WEIGHTS, EVIDENCE_DIVERSITY_MULTIPLIERS,
    EVIDENCE_DIVERSITY_MAX_MULTIPLIER, TRAJECTORY_MULTIPLIER, PRIVACY_MULTIPLIER,
)
from services.bus import EventBus, EventEnvelope
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Evidence Normalizer
# ---------------------------------------------------------------------------


async def normalize_evidence(audit_id: str) -> list[dict]:
    """
    Fetch all evidence for an audit from MongoDB.
    Deduplicate: merge evidence records with same (claim, url, selector) across sources.
    """
    all_ev = []
    async for ev in evidence_col().find({"audit_id": audit_id}):
        all_ev.append(ev)

    # Dedup by (url, claim fingerprint): keep highest-confidence, merge artifact_uris and sources
    seen: dict[str, dict] = {}
    for ev in all_ev:
        key = f"{ev.get('url', '')}|{ev.get('claim', '')[:80]}"
        if key not in seen:
            seen[key] = dict(ev)
            seen[key]["_sources"] = {ev.get("source", "unknown")}
            seen[key]["_all_uris"] = set(ev.get("artifact_uris", []))
        else:
            existing = seen[key]
            # Keep higher confidence
            if ev.get("confidence", 0) > existing.get("confidence", 0):
                existing["confidence"] = ev["confidence"]
                existing["raw_observation"] = ev["raw_observation"]
            existing["_sources"].add(ev.get("source", "unknown"))
            existing["_all_uris"].update(ev.get("artifact_uris", []))

    normalized = []
    for key, ev in seen.items():
        ev["sources"] = list(ev.pop("_sources", set()))
        ev["artifact_uris"] = list(ev.pop("_all_uris", set()))
        if not ev["artifact_uris"]:
            ev["artifact_uris"] = ["no-artifact"]  # should never be empty
        normalized.append(ev)

    logger.info("Evidence normalized", extra={"audit_id": audit_id, "count": len(normalized)})
    return normalized


# ---------------------------------------------------------------------------
# Mathur Dark Pattern Detector
# ---------------------------------------------------------------------------

# Pattern keyword signals (claim text matching)
_MATHUR_SIGNALS: list[tuple[str, MathurCategory, MathurPattern, FindingSeverity]] = [
    # (keyword, category, pattern, severity)
    ("hidden fee", MathurCategory.SNEAKING, MathurPattern.HIDDEN_FEES, FindingSeverity.HIGH),
    ("drip pric", MathurCategory.SNEAKING, MathurPattern.DRIP_PRICING, FindingSeverity.HIGH),
    ("preselect", MathurCategory.SNEAKING, MathurPattern.PRESELECTED_ADDONS, FindingSeverity.MEDIUM),
    ("auto-renew", MathurCategory.SNEAKING, MathurPattern.HIDDEN_SUBSCRIPTION, FindingSeverity.HIGH),
    ("automatically renew", MathurCategory.SNEAKING, MathurPattern.HIDDEN_SUBSCRIPTION, FindingSeverity.HIGH),
    ("hard to cancel", MathurCategory.OBSTRUCTION, MathurPattern.HARD_CANCELLATION, FindingSeverity.HIGH),
    ("cancellation step", MathurCategory.OBSTRUCTION, MathurPattern.HARD_CANCELLATION, FindingSeverity.MEDIUM),
    ("forced registration", MathurCategory.FORCED_ACTION, MathurPattern.FORCED_REGISTRATION, FindingSeverity.MEDIUM),
    ("must create account", MathurCategory.FORCED_ACTION, MathurPattern.FORCED_REGISTRATION, FindingSeverity.MEDIUM),
    ("forced consent", MathurCategory.FORCED_ACTION, MathurPattern.FORCED_CONSENT, FindingSeverity.HIGH),
    ("hidden control", MathurCategory.INTERFACE_INTERFERENCE, MathurPattern.HIDDEN_LOW_CONTRAST_CHOICE, FindingSeverity.HIGH),
    ("low contrast", MathurCategory.INTERFACE_INTERFERENCE, MathurPattern.HIDDEN_LOW_CONTRAST_CHOICE, FindingSeverity.MEDIUM),
    ("misleading label", MathurCategory.INTERFACE_INTERFERENCE, MathurPattern.MISLEADING_BUTTON_LABEL, FindingSeverity.HIGH),
    ("trick question", MathurCategory.INTERFACE_INTERFERENCE, MathurPattern.TRICK_QUESTION, FindingSeverity.HIGH),
    ("countdown timer", MathurCategory.URGENCY, MathurPattern.COUNTDOWN_TIMER, FindingSeverity.MEDIUM),
    ("limited time", MathurCategory.URGENCY, MathurPattern.EXPIRING_OFFER, FindingSeverity.LOW),
    ("only X left", MathurCategory.SCARCITY, MathurPattern.LOW_STOCK_CLAIM, FindingSeverity.LOW),
    ("limited stock", MathurCategory.SCARCITY, MathurPattern.LOW_STOCK_CLAIM, FindingSeverity.LOW),
    ("popup after rejection", MathurCategory.NAGGING, MathurPattern.REPEATED_POPUP, FindingSeverity.MEDIUM),
    ("repeated popup", MathurCategory.NAGGING, MathurPattern.REPEATED_POPUP, FindingSeverity.MEDIUM),
    ("shame", MathurCategory.CONFIRMSHAMING, MathurPattern.GUILT_REJECTION_LABEL, FindingSeverity.MEDIUM),
    ("no thanks", MathurCategory.CONFIRMSHAMING, MathurPattern.GUILT_REJECTION_LABEL, FindingSeverity.LOW),
    ("easy to subscribe", MathurCategory.ROACH_MOTEL, MathurPattern.HARD_CANCELLATION, FindingSeverity.HIGH),
    ("roach motel", MathurCategory.ROACH_MOTEL, MathurPattern.HARD_CANCELLATION, FindingSeverity.CRITICAL),
    ("free trial", MathurCategory.FORCED_CONTINUITY, MathurPattern.HIDDEN_SUBSCRIPTION, FindingSeverity.MEDIUM),
    ("forced continuity", MathurCategory.FORCED_CONTINUITY, MathurPattern.HIDDEN_SUBSCRIPTION, FindingSeverity.HIGH),
]


def detect_mathur_patterns(evidence_list: list[dict]) -> list[dict]:
    """
    Rule-based Mathur dark-pattern detection over normalized evidence.
    Groups evidence by matched pattern → findings.
    Returns list of candidate finding dicts (not yet persisted).
    """
    # Group evidence by pattern
    pattern_groups: dict[str, dict] = {}

    for ev in evidence_list:
        claim_lower = (ev.get("claim", "") + " " + ev.get("raw_observation", "")).lower()
        for keyword, category, pattern, severity in _MATHUR_SIGNALS:
            if keyword.lower() in claim_lower:
                key = pattern.value
                if key not in pattern_groups:
                    pattern_groups[key] = {
                        "pattern": pattern.value,
                        "category": category.value,
                        "severity": severity.value,
                        "evidence": [],
                        "urls": set(),
                        "taxonomy_scope": [JurisdictionScope.MATHUR.value],
                    }
                pattern_groups[key]["evidence"].append(ev)
                if ev.get("url"):
                    pattern_groups[key]["urls"].add(ev["url"])

    findings = []
    for key, group in pattern_groups.items():
        evs = group["evidence"]
        all_sources = {e.get("source", "unknown") for e in evs}
        source_count = len(all_sources)

        # Aggregate confidence
        avg_confidence = sum(e.get("confidence", 0.5) for e in evs) / max(len(evs), 1)

        # Evidence diversity multiplier
        if source_count >= 3:
            ev_mult = EVIDENCE_DIVERSITY_MAX_MULTIPLIER
        else:
            ev_mult = EVIDENCE_DIVERSITY_MULTIPLIERS.get(source_count, 1.0)

        # Trajectory multiplier for sequence-level patterns
        is_sequence_pattern = group["category"] in (
            MathurCategory.ROACH_MOTEL.value,
            MathurCategory.FORCED_CONTINUITY.value,
            MathurCategory.OBSTRUCTION.value,
        )
        traj_mult = TRAJECTORY_MULTIPLIER if is_sequence_pattern else 1.0

        findings.append({
            "pattern": group["pattern"],
            "category": group["category"],
            "severity": group["severity"],
            "taxonomy_scope": group["taxonomy_scope"],
            "confidence": round(min(avg_confidence * ev_mult * traj_mult, 1.0), 3),
            "evidence_ids": [str(e.get("_id", "")) for e in evs],
            "affected_urls": list(group["urls"]),
            "reproduction_steps": [ev.get("claim", "") for ev in evs[:3]],
            "remediation": _remediation_for(group["pattern"]),
            "requires_human_review": avg_confidence < 0.8 or is_sequence_pattern,
            "_evidence_sources": list(all_sources),  # temp field for risk scoring
            "_ev_mult": ev_mult,
        })

    return findings


def _remediation_for(pattern: str) -> list[str]:
    """Return standard remediation steps for a pattern type."""
    remediations = {
        "hidden_fees": ["Display all fees upfront before checkout", "Use clear itemized pricing"],
        "drip_pricing": ["Show total price at first point of sale", "Avoid staged fee revelation"],
        "hard_cancellation": ["Provide single-click cancellation", "Offer cancellation in account settings without calling support"],
        "forced_consent": ["Allow access without consent", "Separate consent from functionality"],
        "misleading_button_label": ["Use clear, accurate labels", "Ensure button text matches its action"],
        "countdown_timer": ["Remove false urgency timers", "Use accurate inventory/availability data"],
        "repeated_popup": ["Respect user rejection of popups", "Show a prompt at most once per session"],
        "guilt_rejection_label": ["Use neutral opt-out labels", "Remove emotionally manipulative copy"],
    }
    return remediations.get(pattern, ["Review and remediate this pattern per UX best practices"])


# ---------------------------------------------------------------------------
# Privacy Taxonomy Classifier
# ---------------------------------------------------------------------------

_privacy_agent = None


def _get_privacy_agent():
    global _privacy_agent
    if _privacy_agent is None:
        _privacy_agent = make_manager("privacy_taxonomy_classifier")
    return _privacy_agent


async def classify_privacy_taxonomy(audit_id: str, evidence_list: list[dict], config: dict) -> list[dict]:
    """
    Run the Privacy Taxonomy Classifier (Claude) over evidence.
    Returns list of PrivacyTaxonomyResult dicts.
    Always marks legal conclusions as requires_human_review=True.
    """
    if not config.get("include_privacy_taxonomy", True):
        return []

    jurisdiction_scopes = config.get("jurisdiction_scopes", ["mathur", "dpdp", "ccpa"])
    privacy_scopes = [s for s in jurisdiction_scopes if s in ("dpdp", "ccpa")]
    if not privacy_scopes:
        return []

    # Summarize evidence for the classifier (token-efficient)
    evidence_summary = [
        {
            "evidence_id": str(ev.get("_id", "")),
            "source": ev.get("source"),
            "claim": ev.get("claim", "")[:300],
            "url": ev.get("url"),
            "taxonomy_scope": ev.get("taxonomy_scope", []),
        }
        for ev in evidence_list[:100]  # limit context
    ]

    agent = _get_privacy_agent()
    user_msg = json.dumps({
        "audit_id": audit_id,
        "jurisdiction_scopes": privacy_scopes,
        "evidence_summary": evidence_summary,
        "instructions": "Classify the evidence against the DPDP and CCPA/CPRA dimensions. Return the privacy_classifications JSON array. Mark all legal conclusions as requires_human_review=true.",
    })

    result = await agent.run(user_msg, expect_array=False, audit_id=audit_id)
    classifications = result.get("privacy_classifications", []) if isinstance(result, dict) else []

    # Enforce requires_human_review=True on all legal conclusions
    for c in classifications:
        c["requires_human_review"] = True  # always

    logger.info("Privacy taxonomy classified",
                extra={"audit_id": audit_id, "count": len(classifications)})
    return classifications


# ---------------------------------------------------------------------------
# Risk Scoring
# ---------------------------------------------------------------------------


def compute_risk_score(findings: list[dict]) -> float:
    """
    Compute overall risk score 0-100 from findings.
    Per System Design Document weights.
    """
    total = 0.0
    for f in findings:
        weight = SEVERITY_WEIGHTS.get(f.get("severity", "low"), 5.0)
        confidence = f.get("confidence", 0.5)
        ev_mult = f.get("_ev_mult", 1.0)

        # Privacy multiplier for rights-friction patterns
        is_privacy_critical = any(
            d in f.get("pattern", "") for d in
            ["opt_out", "deletion", "consent_withdrawal", "sensitive"]
        )
        privacy_mult = PRIVACY_MULTIPLIER if is_privacy_critical else 1.0

        score = weight * confidence * ev_mult * privacy_mult
        total += score

    return round(min(total, 100.0), 2)


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------


async def run_pattern_detection(audit_id: str, config: dict, bus: EventBus) -> None:
    """
    Full pattern detection pipeline.
    Called by orchestrator on report.requested (after static/dynamic complete).
    Publishes finding.created for each finding, then report.requested for reporting.
    """
    try:
        # 1. Normalize evidence
        evidence_list = await normalize_evidence(audit_id)
        if not evidence_list:
            logger.warning("No evidence found", extra={"audit_id": audit_id})

        # 2. Mathur detection
        candidate_findings = detect_mathur_patterns(evidence_list)

        # 3. Privacy taxonomy classification
        privacy_results = await classify_privacy_taxonomy(audit_id, evidence_list, config)

        # 4. Persist findings
        client = await get_supabase()
        finding_repo = FindingRepo(client)

        persisted_findings = []
        for cf in candidate_findings:
            finding_id = str(uuid.uuid4())
            # Generate title from pattern
            title = cf["pattern"].replace("_", " ").title()
            summary = (
                f"Detected {title} pattern. Confidence: {cf['confidence']:.0%}. "
                f"Evidence from: {', '.join(cf.get('_evidence_sources', []))}"
            )

            finding_doc = {
                "id": finding_id,
                "audit_id": audit_id,
                "pattern": cf["pattern"],
                "taxonomy_scope": json.dumps(cf["taxonomy_scope"]),
                "category": cf["category"],
                "severity": cf["severity"],
                "confidence": cf["confidence"],
                "title": title,
                "summary": summary,
                "affected_urls": json.dumps(cf["affected_urls"]),
                "evidence_ids": json.dumps(cf["evidence_ids"]),
                "reproduction_steps": json.dumps(cf["reproduction_steps"]),
                "remediation": json.dumps(cf["remediation"]),
                "requires_human_review": cf["requires_human_review"],
            }
            await finding_repo.create(finding_doc)
            persisted_findings.append(finding_doc)

            # Publish finding.created event
            find_env = EventEnvelope(
                event_type="finding.created",
                audit_id=uuid.UUID(audit_id),
                correlation_id=audit_id,
                payload={"finding_id": finding_id, "title": title, "severity": cf["severity"]},
            )
            await bus.publish("finding.created", find_env)

        # 5. Add findings to Neo4j knowledge graph
        try:
            from services.knowledge_graph import get_knowledge_graph_service
            kg = get_knowledge_graph_service()
            for f in persisted_findings:
                await kg.add_finding_node(
                    audit_id, f["id"], f["pattern"], f["severity"],
                    json.loads(f["evidence_ids"])
                )
        except Exception as exc:
            logger.warning("KG finding node failed", extra={"audit_id": audit_id, "error": str(exc)})

        # 6. Compute risk score
        risk_score = compute_risk_score(candidate_findings)

        logger.info("Pattern detection complete",
                    extra={"audit_id": audit_id, "findings": len(persisted_findings),
                           "risk_score": risk_score})

        # 7. Return result — the caller (gateway lifespan handler) is responsible
        #    for invoking report synthesis next.  We do NOT re-publish
        #    "report.requested" here to avoid a subscriber self-loop.
        logger.info("Pattern detection returning result to caller",
                    extra={"audit_id": audit_id, "risk_score": risk_score})
        return {
            "risk_score": risk_score,
            "finding_count": len(persisted_findings),
            "evidence_count": len(evidence_list),
            "privacy_taxonomy": privacy_results,
        }

    except Exception as exc:
        logger.error("Pattern detection failed", extra={"audit_id": audit_id, "error": str(exc)}, exc_info=exc)
        fail_env = EventEnvelope(
            event_type="audit.failed",
            audit_id=uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={"error": str(exc)},
        )
        await bus.publish("audit.failed", fail_env)
        return None
