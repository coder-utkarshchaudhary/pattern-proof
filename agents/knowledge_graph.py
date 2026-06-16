"""
Knowledge Graph Service.
Reads pages, states, and transitions from MongoDB and materializes them in Neo4j.
Provides path query functions for trajectory analysis.
Deterministic — no LLM calls.
"""
import json
from datetime import datetime
from backend.db.graph import get_driver, upsert_page_node, upsert_state_node, create_edge
from backend.db.nosql import pages_col, states_col, transitions_col
from backend.utils.logger import get_logger

logger = get_logger(__name__)

class KnowledgeGraphService:

    async def build_for_audit(self, audit_id: str) -> dict:
        """
        Build the knowledge graph for a completed discovery + exploration phase.
        Reads pages, states, transitions from MongoDB.
        Writes nodes + edges to Neo4j.
        Returns summary counts.
        """
        # Pages → Page nodes
        page_cursor = pages_col().find({"audit_id": audit_id})
        page_count = 0
        async for page in page_cursor:
            await upsert_page_node(audit_id, page["_id"], page["url"], page.get("page_type", "other"))
            page_count += 1
            # Link discovery edges (discovered_from → LINKS_TO → page)
            if page.get("discovered_from"):
                await _link_pages(audit_id, page["discovered_from"], page["url"], page["_id"])

        # States → State nodes
        state_cursor = states_col().find({"audit_id": audit_id})
        state_count = 0
        async for state in state_cursor:
            await upsert_state_node(audit_id, state["_id"], state["state_hash"], state["url"])
            state_count += 1

        # Transitions → edges
        trans_cursor = transitions_col().find({"audit_id": audit_id})
        edge_count = 0
        async for trans in trans_cursor:
            action_type = trans.get("action_type", "click")
            edge_type = _action_to_edge_type(action_type, trans.get("action_label", ""))
            await create_edge(
                trans["from_state_id"], "State",
                trans["to_state_id"], "State",
                edge_type,
                props={
                    "action_type": action_type,
                    "action_label": trans.get("action_label", ""),
                    "cost": trans.get("cost", 1.0),
                    "audit_id": audit_id,
                    "timestamp": trans.get("created_at", ""),
                }
            )
            edge_count += 1

        logger.info("KG built", extra={"audit_id": audit_id, "pages": page_count,
                                        "states": state_count, "edges": edge_count})
        return {"pages": page_count, "states": state_count, "edges": edge_count}

    async def add_finding_node(self, audit_id: str, finding_id: str, pattern: str, severity: str, evidence_ids: list[str]) -> None:
        """Add a Finding node and connect it to supporting Evidence nodes."""
        driver = await get_driver()
        async with driver.session() as s:
            await s.run(
                "MERGE (f:Finding {finding_id: $fid}) SET f.audit_id=$aid, f.pattern=$pattern, f.severity=$severity",
                fid=finding_id, aid=audit_id, pattern=pattern, severity=severity,
            )
            for eid in evidence_ids:
                await s.run(
                    "MERGE (e:Evidence {evidence_id: $eid}) SET e.audit_id=$aid "
                    "WITH e MATCH (f:Finding {finding_id: $fid}) "
                    "MERGE (e)-[:SUPPORTS_FINDING]->(f)",
                    eid=eid, aid=audit_id, fid=finding_id,
                )
        logger.debug("Finding node added to KG", extra={"audit_id": audit_id, "finding_id": finding_id})

    async def get_cancellation_path(self, audit_id: str) -> dict:
        """
        Find shortest path from subscription state to cancellation state.
        Returns path steps and total cost.
        """
        driver = await get_driver()
        async with driver.session() as s:
            result = await s.run("""
                MATCH (start:State {audit_id: $aid}), (end:State {audit_id: $aid})
                WHERE (start.url CONTAINS 'subscription' OR start.url CONTAINS 'plan' OR start.url CONTAINS 'billing')
                  AND (end.url CONTAINS 'cancel' OR end.url CONTAINS 'unsubscribe')
                MATCH path = shortestPath((start)-[*..15]->(end))
                RETURN path, length(path) as steps
                LIMIT 1
            """, aid=audit_id)
            record = await result.single()
            if not record:
                return {"path_found": False, "steps": None}
            return {"path_found": True, "steps": record["steps"]}

    async def get_consent_asymmetry(self, audit_id: str) -> dict:
        """
        Compare steps to accept vs reject consent.
        Returns click counts for accept and reject paths.
        """
        driver = await get_driver()
        async with driver.session() as s:
            accept_res = await s.run("""
                MATCH (s:State {audit_id: $aid})-[r:SETS_CONSENT|CLICKS_TO*1..5]->()
                WHERE r.action_label CONTAINS 'accept' OR r.action_label CONTAINS 'agree'
                RETURN count(r) as steps
            """, aid=audit_id)
            reject_res = await s.run("""
                MATCH (s:State {audit_id: $aid})-[r:SETS_CONSENT|CLICKS_TO*1..5]->()
                WHERE r.action_label CONTAINS 'reject' OR r.action_label CONTAINS 'decline'
                RETURN count(r) as steps
            """, aid=audit_id)
            accept_rec = await accept_res.single()
            reject_rec = await reject_res.single()
            return {
                "accept_steps": accept_rec["steps"] if accept_rec else 0,
                "reject_steps": reject_rec["steps"] if reject_rec else 0,
            }

    async def get_audit_graph_summary(self, audit_id: str) -> dict:
        """Return a summary of graph nodes/edges for the audit API response."""
        driver = await get_driver()
        async with driver.session() as s:
            result = await s.run("""
                MATCH (n {audit_id: $aid})
                WITH labels(n)[0] as label, count(n) as cnt
                RETURN label, cnt
            """, aid=audit_id)
            counts = {}
            async for record in result:
                counts[record["label"]] = record["cnt"]
        return {"node_counts": counts, "audit_id": audit_id}


def _action_to_edge_type(action_type: str, label: str) -> str:
    """Map action type + label to a Neo4j edge type."""
    label_lower = label.lower()
    if "submit" in label_lower or action_type == "submit":
        return "SUBMITS_TO"
    if "cart" in label_lower or "add to" in label_lower:
        return "ADDS_TO_CART"
    if "checkout" in label_lower:
        return "CHECKOUTS_TO"
    if "modal" in label_lower or "dialog" in label_lower:
        return "OPENS_MODAL"
    if "consent" in label_lower or "accept" in label_lower or "reject" in label_lower:
        return "SETS_CONSENT"
    if "navigate" == action_type or "link" in label_lower:
        return "LINKS_TO"
    if "redirect" in action_type:
        return "REDIRECTS_TO"
    return "CLICKS_TO"


async def _link_pages(audit_id: str, from_url: str, to_url: str, to_page_id: str) -> None:
    """Create LINKS_TO edge between Page nodes identified by URL."""
    driver = await get_driver()
    async with driver.session() as s:
        await s.run(
            "MATCH (a:Page {audit_id: $aid, url: $from_url}) "
            "MATCH (b:Page {page_id: $to_pid}) "
            "MERGE (a)-[:LINKS_TO]->(b)",
            aid=audit_id, from_url=from_url, to_pid=to_page_id,
        )


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_kg_service: KnowledgeGraphService | None = None


def get_knowledge_graph_service() -> KnowledgeGraphService:
    global _kg_service
    if _kg_service is None:
        _kg_service = KnowledgeGraphService()
    return _kg_service
