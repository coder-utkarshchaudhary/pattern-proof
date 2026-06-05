"""
Pydantic API schemas for Pattern Proof.

These are the authoritative request/response models used by all API routes,
WebSocket events, and internal services. Never bypass these schemas in
application code — always validate input/output through them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr, Field, AnyHttpUrl, SecretStr

from models.taxonomy import (
    AuditStatus,
    FindingSeverity,
    EvidenceSource,
    JurisdictionScope,
    UserRole,
    PrivacyTaxonomyResult,
)


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: SecretStr
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str | None
    role: UserRole
    created_at: datetime


# ---------------------------------------------------------------------------
# Audit schemas
# ---------------------------------------------------------------------------

class AuditRequest(BaseModel):
    url: AnyHttpUrl
    max_pages: int = Field(default=25, ge=1, le=500)
    max_depth: int = Field(default=3, ge=0, le=10)
    include_dynamic: bool = True
    include_static: bool = True
    include_privacy_taxonomy: bool = True
    jurisdiction_scopes: list[JurisdictionScope] = [
        JurisdictionScope.MATHUR,
        JurisdictionScope.DPDP,
        JurisdictionScope.CCPA,
    ]
    viewport_width: int = Field(default=1366, ge=320, le=3840)
    viewport_height: int = Field(default=768, ge=320, le=2160)
    credentials_profile_id: UUID | None = None  # accepted, deferred feature


class AuditCreateResponse(BaseModel):
    audit_id: UUID
    job_key: str
    status: AuditStatus
    stream_url: str


class AuditStatusResponse(BaseModel):
    audit_id: UUID
    status: AuditStatus
    progress_percent: float
    current_phase: str
    counts: dict[str, int]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    error: str | None = None


class AuditListItem(BaseModel):
    audit_id: UUID
    url: AnyHttpUrl
    status: AuditStatus
    progress_percent: float
    created_at: datetime


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceRecord(BaseModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    audit_id: UUID
    page_id: UUID | None = None
    state_id: UUID | None = None
    finding_id: UUID | None = None
    taxonomy_scope: list[JurisdictionScope]
    evidence_type: str
    source: EvidenceSource
    url: AnyHttpUrl | None = None
    selector: str | None = None
    region: dict[str, float] | None = None
    claim: str
    raw_observation: str
    confidence: float = Field(ge=0.0, le=1.0)
    artifact_uris: list[str]  # required, never empty for a valid finding
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------

class Finding(BaseModel):
    finding_id: UUID = Field(default_factory=uuid4)
    audit_id: UUID
    pattern: str  # MathurPattern or taxonomy dimension value
    taxonomy_scope: list[JurisdictionScope]
    category: str  # MathurCategory value
    severity: FindingSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    summary: str
    affected_urls: list[AnyHttpUrl]
    evidence_ids: list[UUID]
    reproduction_steps: list[str]
    remediation: list[str]
    requires_human_review: bool


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class AuditReport(BaseModel):
    audit_id: UUID
    url: AnyHttpUrl
    status: Literal["completed"]
    risk_score: float = Field(ge=0.0, le=100.0)
    generated_at: datetime
    executive_summary: str
    findings: list[Finding]
    evidence_count: int
    page_count: int
    state_count: int
    privacy_taxonomy_summary: list[PrivacyTaxonomyResult]
    artifact_uris: list[str]
    limitations: list[str]


# ---------------------------------------------------------------------------
# WebSocket events
# ---------------------------------------------------------------------------

class AuditStreamEvent(BaseModel):
    audit_id: UUID
    event_type: Literal[
        "audit.created",
        "task.started",
        "task.completed",
        "finding.created",
        "report.generated",
        "audit.completed",
        "audit.failed",
    ]
    phase: str
    message: str
    progress_percent: float
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

class JobStatus(BaseModel):
    job_key: str
    audit_id: UUID
    status: AuditStatus
    progress_percent: float
    phase: str
    updated_at: datetime


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = "0.1.0"


class ReadyResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, bool]
