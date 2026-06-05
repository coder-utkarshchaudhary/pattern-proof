"""
Key-based job orchestration for the pipeline.
Tasks:
    1. POST /jobs   — Alias for creating a new audit job; delegates to audit creation logic.
    2. GET  /jobs/{job_key} — Poll job status by opaque job_key.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.dependencies import get_current_user, get_redis, get_supabase_client
from db.sql import AuditRepo
from models.schema import AuditRequest, AuditCreateResponse, JobStatus
from models.taxonomy import AuditStatus
from utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# POST /jobs  — alias: create audit
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Create a new audit job (alias — use POST /audits instead)",
)
async def create_job(
    body: AuditRequest,
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
    client=Depends(get_supabase_client),
    redis=Depends(get_redis),
) -> dict:
    """
    Thin alias that re-uses the audit creation logic.

    Prefer POST /audits for the canonical response shape.
    This endpoint delegates to the audit router's create_audit handler and
    returns the same AuditCreateResponse payload.
    """
    from api.routes.audit import create_audit

    result: AuditCreateResponse = await create_audit(
        body=body,
        request=request,
        user=user,
        client=client,
        redis=redis,
    )
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# GET /jobs/{job_key}  — poll status
# ---------------------------------------------------------------------------


@router.get(
    "/{job_key}",
    response_model=JobStatus,
    summary="Poll job status by job_key",
)
async def get_job_status(
    job_key: str,
    user: Annotated[dict, Depends(get_current_user)],
    redis=Depends(get_redis),
    client=Depends(get_supabase_client),
) -> JobStatus:
    # Redis key is stored as  job:{job_key}
    audit_id_str: str | None = await redis.get(f"job:{job_key}")
    if not audit_id_str:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_key}' not found or has expired",
        )

    audit_repo = AuditRepo(client)
    audit = await audit_repo.get(audit_id_str)
    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit {audit_id_str} not found for job '{job_key}'",
        )

    # Ownership check
    if audit["user_id"] != user["sub"] and user.get("role") not in ("admin", "dev"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this job",
        )

    updated_at_raw = audit.get("updated_at") or audit["created_at"]
    # updated_at may arrive as a string; coerce to datetime if needed.
    if isinstance(updated_at_raw, str):
        updated_at = datetime.fromisoformat(updated_at_raw)
    else:
        updated_at = updated_at_raw

    logger.debug(
        "Job status polled",
        extra={"job_key": job_key, "audit_id": audit_id_str, "user_id": user["sub"]},
    )

    return JobStatus(
        job_key=job_key,
        audit_id=UUID(audit["id"]),
        status=AuditStatus(audit["status"]),
        progress_percent=audit.get("progress_percent", 0.0),
        phase=audit.get("current_phase", ""),
        updated_at=updated_at,
    )
