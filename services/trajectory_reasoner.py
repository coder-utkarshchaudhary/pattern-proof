"""
Trajectory Reasoner (Claude).
Analyzes the state graph and action sequences to detect sequence-level dark patterns:
- Roach Motel (easy in, hard out)
- Forced Continuity (free trial → paid without visible disclosure)
- Obstruction (loops, dead ends, excessive steps)
- Rights-exercise friction (CCPA opt-out, DPDP consent withdrawal)

Uses the trajectory_reasoner prompt loaded from prompts/.
Inputs: state graph summary, transition sequences, evidence list.
Outputs: trajectory findings added to evidence and MongoDB.
"""
import json
import uuid
from datetime import datetime

from agents.base import make_manager
from db.nosql import evidence_col, states_col, transitions_col
from db.sql import get_supabase, FindingRepo
from services.bus import EventBus, EventEnvelope
from models.taxonomy import MathurCategory, MathurPattern, FindingSeverity, JurisdictionScope, TRAJECTORY_MULTIPLIER
from utils.logger import get_logger

logger = get_logger(__name__)
_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        _agent = make_manager("trajectory_reasoner")
    return _agent


async def analyze_trajectories(audit_id: str, config: dict) -> list[dict]:
    """
    Analyze state transitions and trajectories for sequence-level dark patterns.
    Returns list of trajectory evidence records stored in MongoDB.
    """
    # Gather state graph data
    states = []
    async for s in states_col().find({"audit_id": audit_id}).limit(50):
        states.append({
            "state_id": s["_id"],
            "url": s.get("url"),
            "state_hash": s.get("state_hash"),
        })

    transitions = []
    async for t in transitions_col().find({"audit_id": audit_id}).limit(100):
        transitions.append({
            "from_state_id": t.get("from_state_id"),
            "to_state_id": t.get("to_state_id"),
            "action_type": t.get("action_type"),
            "action_label": t.get("action_label"),
            "cost": t.get("cost", 1.0),
        })

    # Get KG path analysis
    kg_summary = {}
    try:
        from services.knowledge_graph import get_knowledge_graph_service
        kg = get_knowledge_graph_service()
        cancellation = await kg.get_cancellation_path(audit_id)
        consent_asym = await kg.get_consent_asymmetry(audit_id)
        kg_summary = {
            "cancellation_path": cancellation,
            "consent_asymmetry": consent_asym,
        }
    except Exception as exc:
        logger.warning("KG summary failed", extra={"audit_id": audit_id, "error": str(exc)})

    # Prepare agent input
    user_msg = json.dumps({
        "audit_id": audit_id,
        "states": states,
        "transitions": transitions,
        "knowledge_graph_summary": kg_summary,
        "jurisdiction_scopes": config.get("jurisdiction_scopes", ["mathur", "dpdp", "ccpa"]),
        "instructions": (
            "Analyze the state graph and transitions for sequence-level dark patterns. "
            "Focus on: Roach Motel (is unsubscription/cancellation harder than subscription?), "
            "Forced Continuity (is free trial → billing disclosed at trial start?), "
            "Obstruction (excessive steps, loops, dead ends to exercise a right or cancel), "
            "Rights-exercise friction (steps needed to opt-out, delete, withdraw consent). "
            "Return strict JSON with a 'trajectory_findings' array as defined in your schema."
        ),
    })

    agent = _get_agent()
    result = await agent.run(user_msg, expect_array=False, audit_id=audit_id)

    # Prompt schema uses "trajectory_findings"; fall back to "evidence_bundle" for resilience
    if isinstance(result, dict):
        findings_raw = (
            result.get("trajectory_findings")
            or result.get("evidence_bundle")
            or []
        )
    else:
        findings_raw = []

    stored = []
    for ev in findings_raw:
        # Map trajectory_findings schema → evidence document
        claim = ev.get("summary") or ev.get("claim") or ""
        ev_doc = {
            "_id": str(uuid.uuid4()),
            "audit_id": audit_id,
            "source": "trajectory",
            "taxonomy_scope": ev.get("taxonomy_scope", ["mathur"]),
            "evidence_type": f"trajectory_{ev.get('pattern', 'observation')}",
            "url": None,
            "claim": claim,
            "raw_observation": claim,
            "confidence": float(ev.get("confidence", 0.6)) * TRAJECTORY_MULTIPLIER,
            "artifact_uris": ev.get("artifact_uris") or ["trajectory://state-graph"],
            "metadata": {
                "pattern": ev.get("pattern", ""),
                "severity": ev.get("severity", "medium"),
                "states": ev.get("states", []),
                "limitations": ev.get("limitations", []),
            },
            "created_at": datetime.utcnow().isoformat(),
        }
        if not ev_doc["artifact_uris"]:
            ev_doc["artifact_uris"] = ["trajectory://state-graph"]
        await evidence_col().insert_one(ev_doc)
        stored.append(ev_doc)

    logger.info("Trajectory analysis done", extra={"audit_id": audit_id, "evidence_count": len(stored)})
    return stored


async def run_trajectory_analysis(audit_id: str, config: dict, bus: EventBus) -> list[dict]:
    """
    Run trajectory analysis. Called after dynamic exploration.
    Returns trajectory evidence list.
    """
    try:
        return await analyze_trajectories(audit_id, config)
    except Exception as exc:
        logger.error("Trajectory analysis failed", extra={"audit_id": audit_id, "error": str(exc)}, exc_info=exc)
        return []
