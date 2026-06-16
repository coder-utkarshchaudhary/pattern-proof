"""
Async MongoDB (Motor) adapter.

Collections:
    pages               — crawled page records
    states              — UI state snapshots
    state_transitions   — recorded action sequences
    network_events      — captured network requests/responses
    evidence            — raw evidence documents
    analyzer_outputs    — per-analyzer LLM output documents
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_client: AsyncIOMotorClient | None = None


# ---------------------------------------------------------------------------
# Client + database accessors
# ---------------------------------------------------------------------------


def get_motor_client() -> AsyncIOMotorClient:
    """Return the singleton Motor client, creating it on first call."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri)
        logger.info("Motor client created")
    return _client


def get_db() -> AsyncIOMotorDatabase:
    """Return the configured Motor database."""
    return get_motor_client()[settings.mongo_db_name]


def get_collection(name: str) -> AsyncIOMotorCollection:
    """Return a named collection from the default database."""
    return get_db()[name]


# ---------------------------------------------------------------------------
# Named collection accessors
# ---------------------------------------------------------------------------


def pages_col() -> AsyncIOMotorCollection:
    """Collection: pages."""
    return get_collection("pages")


def states_col() -> AsyncIOMotorCollection:
    """Collection: states."""
    return get_collection("states")


def transitions_col() -> AsyncIOMotorCollection:
    """Collection: state_transitions."""
    return get_collection("state_transitions")


def network_col() -> AsyncIOMotorCollection:
    """Collection: network_events."""
    return get_collection("network_events")


def evidence_col() -> AsyncIOMotorCollection:
    """Collection: evidence."""
    return get_collection("evidence")


def analyzer_col() -> AsyncIOMotorCollection:
    """Collection: analyzer_outputs."""
    return get_collection("analyzer_outputs")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def close_motor() -> None:
    """Close the Motor client and clear the singleton."""
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("Motor client closed")
