"""
State Explorer: computes state signatures and manages the state graph.
State hash = sha256(normalized_url + dom_signature + visible_text_hash + cookie_hash)
"""
import hashlib
import json
import uuid
from datetime import datetime
from db.nosql import states_col, transitions_col
from utils.logger import get_logger

logger = get_logger(__name__)

def compute_state_hash(url: str, dom_sig: str, visible_text: str, cookies: list[dict], storage: dict) -> str:
    """Compute a deterministic state hash."""
    components = "|".join([
        url.split("?")[0],  # normalized URL (strip query)
        hashlib.sha256(dom_sig.encode()).hexdigest()[:16],
        hashlib.sha256(visible_text.encode()).hexdigest()[:16],
        hashlib.sha256(json.dumps(sorted(c.get("name","") for c in cookies)).encode()).hexdigest()[:8],
    ])
    return hashlib.sha256(components.encode()).hexdigest()

async def record_state(audit_id: str, page_id: str | None, url: str,
                       dom_sig: str, visible_text: str, cookies: list[dict],
                       storage: dict, screenshot_uri: str, dom_uri: str, a11y_uri: str) -> dict:
    """Record a state in MongoDB. Returns the state document."""
    state_hash = compute_state_hash(url, dom_sig, visible_text, cookies, storage)
    state_id = str(uuid.uuid4())
    doc = {
        "_id": state_id,
        "audit_id": audit_id,
        "page_id": page_id,
        "state_hash": state_hash,
        "url": url,
        "visible_text_hash": hashlib.sha256(visible_text.encode()).hexdigest(),
        "cookie_hash": hashlib.sha256(json.dumps(sorted(c.get("name","") for c in cookies)).encode()).hexdigest(),
        "screenshot_uri": screenshot_uri,
        "dom_uri": dom_uri,
        "a11y_tree_uri": a11y_uri,
        "created_at": datetime.utcnow().isoformat(),
    }
    await states_col().insert_one(doc)
    return doc

async def record_transition(audit_id: str, from_state_id: str, to_state_id: str,
                             action_type: str, action_label: str, cost: float = 1.0,
                             artifact_uris: list[str] | None = None) -> dict:
    """Record a state transition in MongoDB."""
    doc = {
        "_id": str(uuid.uuid4()),
        "audit_id": audit_id,
        "from_state_id": from_state_id,
        "to_state_id": to_state_id,
        "action_type": action_type,
        "action_label": action_label,
        "cost": cost,
        "artifact_uris": artifact_uris or [],
        "created_at": datetime.utcnow().isoformat(),
    }
    await transitions_col().insert_one(doc)
    return doc
