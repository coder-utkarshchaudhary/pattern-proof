"""
WebSocket connection for client-manager connection.
Tasks:
    1. WS /audits/{audit_id}/stream — Subscribe to Redis pub/sub channel and
       forward progress events to the connected client.
"""
from __future__ import annotations

from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from backend.config import settings
from backend.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# WS /audits/{audit_id}/stream
# ---------------------------------------------------------------------------


@router.websocket("/audits/{audit_id}/stream")
async def audit_stream(
    websocket: WebSocket,
    audit_id: UUID,
) -> None:
    """
    Stream real-time audit progress events to the client.

    Authentication is performed via a ``?token=<JWT>`` query parameter
    because WebSocket handshakes cannot carry HTTP Authorization headers
    reliably across all clients.

    The orchestrator publishes progress messages to the Redis channel
    ``audit:stream:{audit_id}``.  This handler subscribes to that channel
    and forwards each message as a WebSocket text frame until the client
    disconnects.
    """
    # --- 1. Authenticate via query-param token ---
    token: str | None = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)  # Policy Violation
        logger.warning(
            "WS rejected: missing token",
            extra={"audit_id": str(audit_id)},
        )
        return

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str = payload.get("sub", "")
    except JWTError:
        await websocket.close(code=1008)
        logger.warning(
            "WS rejected: invalid token",
            extra={"audit_id": str(audit_id)},
        )
        return

    await websocket.accept()
    logger.info(
        "WS connected",
        extra={"audit_id": str(audit_id), "user_id": user_id},
    )

    channel = f"audit:stream:{audit_id}"
    # decode_responses=True ensures message["data"] is str, not bytes.
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()

    try:
        await pubsub.subscribe(channel)

        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])

    except WebSocketDisconnect:
        logger.info(
            "WS disconnected",
            extra={"audit_id": str(audit_id), "user_id": user_id},
        )
    except Exception as exc:
        logger.error(
            "WS error",
            extra={"audit_id": str(audit_id), "error": str(exc)},
            exc_info=exc,
        )
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        try:
            await r.aclose()
        except Exception:
            pass
        logger.debug(
            "WS cleanup complete",
            extra={"audit_id": str(audit_id), "user_id": user_id},
        )
