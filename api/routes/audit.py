"""
API Endpoints for audit related tasks.
Tasks:
    1. POST /audits -> Create audit job.
    2. GET /audits -> Fetch all audits.
    3. GET /audits/{audit_id} -> Fetch all details for the audit.
    4. GET /audits/{audit_id}/status -> Fetch audit status.
    5. GET /audits/{audit_id}/findings -> Fetch findings for the audit.
    6. GET /audits/{audit_id}/graph -> Stub for knowledge graph.
    7. POST /audits/{audit_id}/cancel -> Cancel an audit.
"""
from __future__ import annotations

from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.dependencies import (
    get_current_user,
    get_redis,
    get_supabase_client,
    validate_audit_url,
)
from db.sql import AuditRepo, FindingRepo
from models.schema import (
    AuditCreateResponse,
    AuditListItem,
    AuditRequest,
    AuditStatusResponse,
)
from models.taxonomy import AuditStatus
from services.bus import EventEnvelope
from utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_ownership(audit: dict, user: dict) -> None:
    """Raise 403 if the user does not own the audit and is not admin/dev."""
    if audit["user_id"] != user["sub"] and user.get("role") not in ("admin", "dev"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this audit",
        )


async def _get_audit_owned(
    audit_id: UUID,
    user: dict,
    client,
) -> dict:
    """Fetch an audit row; raise 404 if absent, 403 if not owned."""
    audit_repo = AuditRepo(client)
    audit = await audit_repo.get(str(audit_id))
    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit {audit_id} not found",
        )
    _require_ownership(audit, user)
    return audit


# ---------------------------------------------------------------------------
# POST /audits
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=AuditCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new audit job",
)
async def create_audit(
    body: AuditRequest,
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
    client=Depends(get_supabase_client),
    redis=Depends(get_redis),
) -> AuditCreateResponse:
    url_str = str(body.url)

    # SSRF validation
    validate_audit_url(url_str)

    normalized_domain = urlparse(url_str).netloc

    # Serialize config; mode="json" converts enums and UUID to JSON-safe types.
    config_json: dict = body.model_dump(mode="json", exclude={"url"})

    # Persist to Supabase
    audit_repo = AuditRepo(client)
    audit = await audit_repo.create(
        user_id=user["sub"],
        url=url_str,
        normalized_domain=normalized_domain,
        config_json=config_json,
    )

    audit_id: UUID = UUID(audit["id"])
    job_key = f"audit:{audit_id}"

    # Cache job key → audit_id in Redis (TTL 24 h)
    await redis.set(f"job:{job_key}", str(audit_id), ex=86400)

    # Publish audit.created event
    envelope = EventEnvelope(
        event_type="audit.created",
        audit_id=audit_id,
        correlation_id=str(audit_id),
        payload={"url": url_str, "normalized_domain": normalized_domain},
    )
    await request.app.state.event_bus.publish("audit.created", envelope)

    logger.info(
        "Audit created",
        extra={"audit_id": str(audit_id), "user_id": user["sub"]},
    )

    return AuditCreateResponse(
        audit_id=audit_id,
        job_key=job_key,
        status=AuditStatus.CREATED,
        stream_url=f"/audits/{audit_id}/stream",
    )


# ---------------------------------------------------------------------------
# GET /audits
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[AuditListItem],
    summary="List all audits for the current user",
)
async def list_audits(
    user: Annotated[dict, Depends(get_current_user)],
    client=Depends(get_supabase_client),
) -> list[AuditListItem]:
    audit_repo = AuditRepo(client)
    rows = await audit_repo.list_for_user(user["sub"])

    return [
        AuditListItem(
            audit_id=UUID(row["id"]),
            url=row["url"],
            status=AuditStatus(row["status"]),
            progress_percent=row.get("progress_percent", 0.0),
            created_at=row["created_at"],
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# GET /audits/{audit_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{audit_id}",
    summary="Get full audit details",
)
async def get_audit(
    audit_id: UUID,
    user: Annotated[dict, Depends(get_current_user)],
    client=Depends(get_supabase_client),
) -> dict:
    audit = await _get_audit_owned(audit_id, user, client)
    return audit


# ---------------------------------------------------------------------------
# GET /audits/{audit_id}/status
# ---------------------------------------------------------------------------


@router.get(
    "/{audit_id}/status",
    response_model=AuditStatusResponse,
    summary="Get audit status and progress",
)
async def get_audit_status(
    audit_id: UUID,
    user: Annotated[dict, Depends(get_current_user)],
    client=Depends(get_supabase_client),
) -> AuditStatusResponse:
    audit = await _get_audit_owned(audit_id, user, client)

    return AuditStatusResponse(
        audit_id=UUID(audit["id"]),
        status=AuditStatus(audit["status"]),
        progress_percent=audit.get("progress_percent", 0.0),
        current_phase=audit.get("current_phase", ""),
        counts=audit.get("counts", {}),
        created_at=audit["created_at"],
        updated_at=audit.get("updated_at") or audit["created_at"],
        completed_at=audit.get("completed_at"),
        error=audit.get("error_message"),
    )


# ---------------------------------------------------------------------------
# GET /audits/{audit_id}/findings
# ---------------------------------------------------------------------------


@router.get(
    "/{audit_id}/findings",
    summary="List findings for an audit",
)
async def get_audit_findings(
    audit_id: UUID,
    user: Annotated[dict, Depends(get_current_user)],
    client=Depends(get_supabase_client),
) -> list[dict]:
    # Ownership check
    await _get_audit_owned(audit_id, user, client)

    finding_repo = FindingRepo(client)
    findings = await finding_repo.list_for_audit(str(audit_id))
    return findings


# ---------------------------------------------------------------------------
# GET /audits/{audit_id}/graph
# ---------------------------------------------------------------------------


@router.get(
    "/{audit_id}/graph",
    summary="Knowledge graph for an audit (stub)",
)
async def get_audit_graph(
    audit_id: UUID,
    user: Annotated[dict, Depends(get_current_user)],
    client=Depends(get_supabase_client),
) -> dict:
    # Ownership check
    await _get_audit_owned(audit_id, user, client)

    return {
        "message": "Knowledge graph not yet available",
        "audit_id": str(audit_id),
    }


# ---------------------------------------------------------------------------
# POST /audits/{audit_id}/cancel
# ---------------------------------------------------------------------------


@router.post(
    "/{audit_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel a running audit",
)
async def cancel_audit(
    audit_id: UUID,
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
    client=Depends(get_supabase_client),
) -> dict:
    audit = await _get_audit_owned(audit_id, user, client)

    # Guard: cannot cancel an already-terminal audit
    terminal_statuses = {
        AuditStatus.COMPLETED,
        AuditStatus.FAILED,
        AuditStatus.CANCELLED,
    }
    if AuditStatus(audit["status"]) in terminal_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Audit is already in terminal state: {audit['status']}",
        )

    audit_repo = AuditRepo(client)
    await audit_repo.update_status(
        audit_id=str(audit_id),
        status="cancelled",
        progress=audit.get("progress_percent", 0.0),
        phase="cancelled",
    )

    # Publish audit.cancelled event
    envelope = EventEnvelope(
        event_type="audit.cancelled",
        audit_id=audit_id,
        correlation_id=str(audit_id),
        payload={"cancelled_by": user["sub"]},
    )
    await request.app.state.event_bus.publish("audit.cancelled", envelope)

    logger.info(
        "Audit cancelled",
        extra={"audit_id": str(audit_id), "user_id": user["sub"]},
    )

    return {"audit_id": str(audit_id), "status": "cancelled"}
