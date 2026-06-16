"""
FastAPI application factory and gateway.

Startup wires:
  1. EventBus (Eager dev / Redpanda prod)
  2. AuditOrchestrator lifecycle state machine
  3. Service handlers for every bus topic
  4. All API routers

Event pipeline (loop-free):
  audit.created      → orchestrator → discovery.started
  discovery.started  → run_discovery → discovery.completed
  discovery.completed → orchestrator → static.started
  static.started     → run_static_analysis → static.completed
  static.completed   → orchestrator → dynamic.started
  dynamic.started    → run_dynamic_analysis → dynamic.completed
  dynamic.completed  → orchestrator → detecting_patterns status → report.requested
  report.requested   → run_pattern_detection → run_report_synthesis → report.generated
  report.generated   → orchestrator → completed
  audit.failed       → orchestrator → failed status
  audit.cancelled    → orchestrator → cancelled status
"""
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.models.schema import HealthResponse, ReadyResponse
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    from backend.agents.bus import create_event_bus
    from backend.agents.orchestrator import create_orchestrator

    bus = create_event_bus()
    await bus.start()
    app.state.event_bus = bus

    # Set up orchestrator (subscribes to: audit.created, discovery.completed,
    # static.completed, dynamic.completed, finding.created, report.generated,
    # audit.failed, audit.cancelled)
    orchestrator = create_orchestrator(bus)
    await orchestrator.setup()
    app.state.orchestrator = orchestrator

    # --- Wire service handlers to bus topics ---

    async def _handle_discovery_started(envelope) -> None:
        """discovery.started → run full discovery, emit discovery.completed."""
        from backend.agents.discovery import run_discovery
        config = envelope.payload.get("config", {})
        url = envelope.payload.get("url", "")
        if not url:
            logger.warning("discovery.started missing url", extra={"audit_id": str(envelope.audit_id)})
            return
        await run_discovery(str(envelope.audit_id), url, config, bus)

    await bus.subscribe("discovery.started", _handle_discovery_started)

    async def _handle_static_started(envelope) -> None:
        """static.started → run static analysis on all discovered pages."""
        from backend.services.static.manager import run_static_analysis
        config = envelope.payload.get("config", {})
        pages = envelope.payload.get("pages", [])
        await run_static_analysis(str(envelope.audit_id), pages, config, bus)

    await bus.subscribe("static.started", _handle_static_started)

    async def _handle_dynamic_started(envelope) -> None:
        """dynamic.started → run browser exploration."""
        from backend.services.dynamic.browser_exploration import run_dynamic_analysis
        config = envelope.payload.get("config", {})
        url = envelope.payload.get("url", "")
        pages = envelope.payload.get("pages", [])
        await run_dynamic_analysis(str(envelope.audit_id), url, pages, config, bus)

    await bus.subscribe("dynamic.started", _handle_dynamic_started)

    async def _handle_report_requested(envelope) -> None:
        """
        report.requested → pattern detection → report synthesis → report.generated.

        This handler is the ONLY subscriber to report.requested.
        run_pattern_detection does NOT re-publish report.requested (loop prevented).
        run_report_synthesis publishes report.generated when done.
        """
        audit_id = str(envelope.audit_id)
        config = envelope.payload.get("config", {})

        from backend.agents.pattern_detection import run_pattern_detection
        from backend.agents.report_synthesizer import run_report_synthesis

        logger.info("report.requested: running pattern detection", extra={"audit_id": audit_id})
        result = await run_pattern_detection(audit_id, config, bus)

        if result is None:
            # run_pattern_detection already published audit.failed
            logger.warning("Pattern detection returned None; skipping synthesis",
                           extra={"audit_id": audit_id})
            return

        logger.info("report.requested: running report synthesis", extra={"audit_id": audit_id})
        await run_report_synthesis(audit_id, config, bus)

    await bus.subscribe("report.requested", _handle_report_requested)

    logger.info("Application startup complete", extra={"env": settings.app_env,
                                                        "event_bus": settings.event_bus})
    yield

    # --- Shutdown ---
    await bus.stop()

    from backend.db.nosql import close_motor
    await close_motor()

    from backend.db.graph import close_driver
    await close_driver()

    logger.info("Application shutdown complete")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pattern Proof API",
        version="0.1.0",
        description="Automated dark-pattern and privacy-choice audit platform",
        lifespan=lifespan,
    )

    # CORS — tighten in production via allowed-origins env var
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Middleware: request ID + structured access log
    # ------------------------------------------------------------------

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.monotonic()
        response: Response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "HTTP request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    # ------------------------------------------------------------------
    # Global exception handler
    # ------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "Unhandled exception",
            extra={"request_id": request_id, "error": str(exc)},
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    # ------------------------------------------------------------------
    # Health endpoints
    # ------------------------------------------------------------------

    @app.get("/healthz", response_model=HealthResponse, tags=["Health"])
    async def healthz():
        """Liveness probe — always 200 if the process is alive."""
        return HealthResponse()

    @app.get("/readyz", response_model=ReadyResponse, tags=["Health"])
    async def readyz():
        """Readiness probe — checks Redis, MongoDB, and Neo4j."""
        checks: dict[str, bool] = {}

        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.redis_url)
            await r.ping()
            await r.aclose()
            checks["redis"] = True
        except Exception:
            checks["redis"] = False

        try:
            from backend.db.nosql import get_motor_client
            client = get_motor_client()
            await client.admin.command("ping")
            checks["mongodb"] = True
        except Exception:
            checks["mongodb"] = False

        try:
            from backend.db.graph import get_driver
            driver = await get_driver()
            async with driver.session() as s:
                await s.run("RETURN 1")
            checks["neo4j"] = True
        except Exception:
            checks["neo4j"] = False

        overall = "ready" if all(checks.values()) else "degraded"
        return ReadyResponse(status=overall, checks=checks)

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------

    from backend.api.routes.auth import router as auth_router
    app.include_router(auth_router, prefix="/auth", tags=["Auth"])

    from backend.api.routes.audit import router as audit_router
    app.include_router(audit_router, prefix="/audits", tags=["Audits"])

    from backend.api.routes.jobs import router as jobs_router
    app.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])

    from backend.api.routes.evidence import router as evidence_router
    app.include_router(evidence_router, prefix="/evidence", tags=["Evidence"])

    from backend.api.routes.report import router as report_router
    app.include_router(report_router, prefix="/reports", tags=["Reports"])

    from backend.api.routes.ws import router as ws_router
    app.include_router(ws_router, tags=["WebSocket"])

    return app


app = create_app()
