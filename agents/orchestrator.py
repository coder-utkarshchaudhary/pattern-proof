"""
Audit Orchestrator for Pattern Proof.

Stateless pipeline driver that listens on EventBus topics, drives the audit
lifecycle state machine, publishes next-phase events, updates audit status in
Supabase, and fans WebSocket progress events via Redis pub/sub.

Lifecycle:
    created → queued → discovering → static_analysis → dynamic_analysis
            → detecting_patterns → reporting → completed
    (any state) → failed | cancelled

Usage:
    orchestrator = create_orchestrator(bus)
    await orchestrator.setup()   # called once at application startup
"""

import json
import uuid
from datetime import datetime

import redis.asyncio as aioredis

from backend.config import settings
from backend.db.sql import get_supabase, AuditRepo
from backend.models.schema import AuditStreamEvent
from backend.models.taxonomy import AuditStatus
from backend.agents.bus import EventBus, EventEnvelope
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Phase → progress_percent mapping
# ---------------------------------------------------------------------------

PHASE_PROGRESS: dict[str, float] = {
    "created": 0.0,
    "queued": 2.0,
    "discovering": 10.0,
    "static_analysis": 30.0,
    "dynamic_analysis": 55.0,
    "detecting_patterns": 75.0,
    "reporting": 90.0,
    "completed": 100.0,
    "failed": 100.0,
    "cancelled": 100.0,
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class AuditOrchestrator:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def setup(self):
        """Register all event handlers. Call once at startup."""
        await self.bus.subscribe("audit.created", self._on_audit_created)
        await self.bus.subscribe("discovery.completed", self._on_discovery_completed)
        await self.bus.subscribe("static.completed", self._on_static_completed)
        await self.bus.subscribe("dynamic.completed", self._on_dynamic_completed)
        await self.bus.subscribe("finding.created", self._on_finding_created)
        await self.bus.subscribe("report.generated", self._on_report_generated)
        await self.bus.subscribe("audit.failed", self._on_audit_failed)
        await self.bus.subscribe("audit.cancelled", self._on_audit_cancelled)
        logger.info("AuditOrchestrator handlers registered")

    async def _update_status(self, audit_id: str, status: str, phase: str) -> None:
        """Update audit in Supabase and fan WS event via Redis."""
        progress = PHASE_PROGRESS.get(status, 0.0)
        client = await get_supabase()
        repo = AuditRepo(client)
        await repo.update_status(audit_id, status, progress, phase)
        # Fan to WebSocket channel
        r = await self._get_redis()
        event = AuditStreamEvent(
            audit_id=uuid.UUID(audit_id),
            event_type="audit.created" if status == "queued" else
                       "audit.completed" if status == "completed" else
                       "audit.failed" if status == "failed" else "task.started",
            phase=phase,
            message=f"Audit phase: {phase}",
            progress_percent=progress,
        )
        await r.publish(f"audit:stream:{audit_id}", event.model_dump_json())
        logger.info("Audit status updated", extra={"audit_id": audit_id, "status": status, "phase": phase})

    async def _publish_next(self, topic: str, audit_id: str, payload: dict | None = None) -> None:
        envelope = EventEnvelope(
            event_type=topic,
            audit_id=uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload=payload or {},
        )
        await self.bus.publish(topic, envelope)

    async def _on_audit_created(self, envelope: EventEnvelope) -> None:
        audit_id = str(envelope.audit_id)
        logger.info("audit.created", extra={"audit_id": audit_id})
        await self._update_status(audit_id, "queued", "queued")
        # Transition to discovering
        await self._update_status(audit_id, "discovering", "discovering")
        await self._publish_next("discovery.started", audit_id, envelope.payload)

    async def _on_discovery_completed(self, envelope: EventEnvelope) -> None:
        audit_id = str(envelope.audit_id)
        logger.info("discovery.completed", extra={"audit_id": audit_id})
        audit_config = envelope.payload.get("config", {})
        if audit_config.get("include_static", True):
            await self._update_status(audit_id, "static_analysis", "static_analysis")
            await self._publish_next("static.started", audit_id, envelope.payload)
        elif audit_config.get("include_dynamic", True):
            await self._update_status(audit_id, "dynamic_analysis", "dynamic_analysis")
            await self._publish_next("dynamic.started", audit_id, envelope.payload)
        else:
            await self._publish_next("report.requested", audit_id, envelope.payload)

    async def _on_static_completed(self, envelope: EventEnvelope) -> None:
        audit_id = str(envelope.audit_id)
        logger.info("static.completed", extra={"audit_id": audit_id})
        audit_config = envelope.payload.get("config", {})
        if audit_config.get("include_dynamic", True):
            await self._update_status(audit_id, "dynamic_analysis", "dynamic_analysis")
            await self._publish_next("dynamic.started", audit_id, envelope.payload)
        else:
            await self._update_status(audit_id, "detecting_patterns", "detecting_patterns")
            await self._publish_next("report.requested", audit_id, envelope.payload)

    async def _on_dynamic_completed(self, envelope: EventEnvelope) -> None:
        audit_id = str(envelope.audit_id)
        logger.info("dynamic.completed", extra={"audit_id": audit_id})
        await self._update_status(audit_id, "detecting_patterns", "detecting_patterns")
        await self._publish_next("report.requested", audit_id, envelope.payload)

    async def _on_finding_created(self, envelope: EventEnvelope) -> None:
        audit_id = str(envelope.audit_id)
        r = await self._get_redis()
        event = AuditStreamEvent(
            audit_id=envelope.audit_id,
            event_type="finding.created",
            phase="detecting_patterns",
            message=f"Finding created: {envelope.payload.get('title', '')}",
            progress_percent=PHASE_PROGRESS["detecting_patterns"],
            payload=envelope.payload,
        )
        await r.publish(f"audit:stream:{audit_id}", event.model_dump_json())

    async def _on_report_generated(self, envelope: EventEnvelope) -> None:
        audit_id = str(envelope.audit_id)
        logger.info("report.generated", extra={"audit_id": audit_id})
        await self._update_status(audit_id, "completed", "completed")

    async def _on_audit_failed(self, envelope: EventEnvelope) -> None:
        audit_id = str(envelope.audit_id)
        error = envelope.payload.get("error", "Unknown error")
        logger.error("audit.failed", extra={"audit_id": audit_id, "error": error})
        client = await get_supabase()
        repo = AuditRepo(client)
        await repo.update_status(audit_id, "failed", 100.0, "failed", error=error)
        r = await self._get_redis()
        event = AuditStreamEvent(
            audit_id=envelope.audit_id,
            event_type="audit.failed",
            phase="failed",
            message=f"Audit failed: {error}",
            progress_percent=100.0,
        )
        await r.publish(f"audit:stream:{audit_id}", event.model_dump_json())

    async def _on_audit_cancelled(self, envelope: EventEnvelope) -> None:
        audit_id = str(envelope.audit_id)
        logger.info("audit.cancelled", extra={"audit_id": audit_id})
        await self._update_status(audit_id, "cancelled", "cancelled")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_orchestrator(bus: EventBus) -> AuditOrchestrator:
    """Create and return an AuditOrchestrator bound to the given EventBus."""
    return AuditOrchestrator(bus)
