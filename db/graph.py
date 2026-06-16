"""
Neo4j async graph database adapter.

Node types:
    Page, State, Action, Form, Modal, Product, Cart, Checkout,
    Account, ConsentSurface, PrivacyRightsSurface, Finding, Evidence

Edge types:
    LINKS_TO, REDIRECTS_TO, CLICKS_TO, SUBMITS_TO, ADDS_TO_CART,
    CHECKOUTS_TO, OPENS_MODAL, DISMISSES_MODAL, CHANGES_PRICE,
    SETS_CONSENT, EXERCISES_RIGHT, SUPPORTS_FINDING
"""
from neo4j import AsyncGraphDatabase, AsyncDriver

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_driver: AsyncDriver | None = None


# ---------------------------------------------------------------------------
# Driver lifecycle
# ---------------------------------------------------------------------------


async def get_driver() -> AsyncDriver:
    """Return the singleton Neo4j async driver, creating it on first call."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        logger.info("Neo4j async driver created")
    return _driver


async def close_driver() -> None:
    """Close the Neo4j driver and clear the singleton."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


async def upsert_page_node(
    audit_id: str, page_id: str, url: str, page_type: str
) -> None:
    """Create or update a Page node in the graph."""
    driver = await get_driver()
    async with driver.session() as s:
        await s.run(
            "MERGE (p:Page {page_id: $page_id}) "
            "SET p.audit_id=$audit_id, p.url=$url, p.page_type=$page_type",
            page_id=page_id,
            audit_id=audit_id,
            url=url,
            page_type=page_type,
        )


async def upsert_state_node(
    audit_id: str, state_id: str, state_hash: str, url: str
) -> None:
    """Create or update a State node in the graph."""
    driver = await get_driver()
    async with driver.session() as s:
        await s.run(
            "MERGE (s:State {state_id: $state_id}) "
            "SET s.audit_id=$audit_id, s.state_hash=$state_hash, s.url=$url",
            state_id=state_id,
            audit_id=audit_id,
            state_hash=state_hash,
            url=url,
        )


async def create_edge(
    from_id: str,
    from_label: str,
    to_id: str,
    to_label: str,
    edge_type: str,
    props: dict | None = None,
) -> None:
    """
    Create or merge a directed edge between two nodes.

    The id property used for MATCH depends on the label:
        Page  -> page_id
        State -> state_id
    """
    driver = await get_driver()
    props = props or {}
    from_key = "page_id" if from_label == "Page" else "state_id"
    to_key = "page_id" if to_label == "Page" else "state_id"
    async with driver.session() as s:
        await s.run(
            f"MATCH (a:{from_label} {{{from_key}: $from_id}}) "
            f"MATCH (b:{to_label} {{{to_key}: $to_id}}) "
            f"MERGE (a)-[r:{edge_type}]->(b) SET r += $props",
            from_id=from_id,
            to_id=to_id,
            props=props,
        )
