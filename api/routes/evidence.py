"""Evidence retrieval endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from api.dependencies import get_current_user
from db.nosql import evidence_col
from db.sql import get_supabase, AuditRepo
from utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

async def _check_audit_access(audit_id: str, user: dict) -> dict:
    client = await get_supabase()
    audit = await AuditRepo(client).get(str(audit_id))
    if not audit:
        raise HTTPException(404, "Audit not found")
    if audit["user_id"] != user["sub"] and user.get("role") not in ("admin", "dev"):
        raise HTTPException(403, "Access denied")
    return audit

@router.get("/{audit_id}")
async def list_evidence(
    audit_id: str,
    user: Annotated[dict, Depends(get_current_user)] = None,
    limit: int = 50,
    skip: int = 0,
):
    """List evidence records for an audit."""
    await _check_audit_access(audit_id, user)
    cursor = evidence_col().find({"audit_id": audit_id}).skip(skip).limit(limit)
    results = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        results.append(doc)
    return {"audit_id": audit_id, "evidence": results, "count": len(results)}

@router.get("/{audit_id}/{evidence_id}")
async def get_evidence(
    audit_id: str,
    evidence_id: str,
    user: Annotated[dict, Depends(get_current_user)] = None,
):
    """Get a single evidence record."""
    await _check_audit_access(audit_id, user)
    doc = await evidence_col().find_one({"_id": evidence_id, "audit_id": audit_id})
    if not doc:
        raise HTTPException(404, "Evidence not found")
    doc["_id"] = str(doc["_id"])
    return doc

@router.get("/{audit_id}/screenshots/{screenshot_id}")
async def get_screenshot(
    audit_id: str,
    screenshot_id: str,
    user: Annotated[dict, Depends(get_current_user)] = None,
):
    """Return a signed URL or redirect to the screenshot artifact in Supabase Storage."""
    await _check_audit_access(audit_id, user)
    path = f"audits/{audit_id}/pages/{screenshot_id}/screenshot.png"
    try:
        from db.sql import get_supabase
        client = await get_supabase()
        # Create signed URL (60 minutes)
        signed = await client.storage.from_("pattern-proof").create_signed_url(path, 3600)
        return {"signed_url": signed.get("signedURL") or signed.get("signed_url", ""), "expires_in": 3600}
    except Exception as exc:
        logger.error("Signed URL error", extra={"audit_id": audit_id, "error": str(exc)})
        raise HTTPException(500, "Could not generate screenshot URL")
