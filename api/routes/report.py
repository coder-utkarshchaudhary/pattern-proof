"""Report retrieval endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Annotated
from fastapi.responses import Response
from backend.api.dependencies import get_current_user
from backend.tools.report_builder import build_json_report, build_markdown_report, store_report
from backend.tools.pdf_generator import generate_pdf_report
from backend.db.sql import get_supabase, AuditRepo
from backend.utils.logger import get_logger

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
async def get_report(
    audit_id: str,
    format: str = Query(default="json", pattern="^(json|markdown|pdf)$"),
    user: Annotated[dict, Depends(get_current_user)] = None,
):
    """Get audit report in json, markdown, or pdf format."""
    await _check_audit_access(audit_id, user)

    if format == "json":
        report_data = await build_json_report(audit_id)
        return report_data

    elif format == "markdown":
        md = await build_markdown_report(audit_id)
        return Response(content=md, media_type="text/markdown")

    elif format == "pdf":
        pdf = await generate_pdf_report(audit_id)
        if not pdf:
            raise HTTPException(500, "PDF generation failed")
        # Store and return
        await store_report(audit_id, "pdf", pdf, "application/pdf")
        return Response(content=pdf, media_type="application/pdf",
                       headers={"Content-Disposition": f'attachment; filename="report-{audit_id}.pdf"'})

@router.get("/{audit_id}/pdf")
async def get_report_pdf(
    audit_id: str,
    user: Annotated[dict, Depends(get_current_user)] = None,
):
    """Direct PDF download endpoint."""
    await _check_audit_access(audit_id, user)
    pdf = await generate_pdf_report(audit_id)
    if not pdf:
        raise HTTPException(500, "PDF generation failed")
    await store_report(audit_id, "pdf", pdf, "application/pdf")
    return Response(content=pdf, media_type="application/pdf",
                   headers={"Content-Disposition": f'attachment; filename="report-{audit_id}.pdf"'})
