"""
FastAPI dependencies: auth, DB clients, Redis, Supabase Storage, event bus,
and URL safety (SSRF protection).
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# URL safety (SSRF protection)
# ---------------------------------------------------------------------------

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("100.64.0.0/10"),   # shared address space
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("240.0.0.0/4"),
]

# Cloud metadata endpoints
_METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}


def _is_private_ip(host: str) -> bool:
    """Return True if the address is private, loopback, or a metadata IP."""
    try:
        addr = ipaddress.ip_address(host)
        if str(addr) in _METADATA_IPS:
            return True
        return any(addr in net for net in _PRIVATE_RANGES)
    except ValueError:
        return False


def validate_audit_url(url: str) -> str:
    """
    Validate that a URL is safe to audit.

    Blocks:
    - Non-http/https schemes
    - Missing hostnames
    - localhost and *.local hostnames
    - Bare private/reserved IP addresses
    - DNS names that resolve to private/reserved IPs (SSRF protection)
    - Unresolvable hostnames

    Raises HTTPException 422 on any violation.
    Returns the original URL string on success.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=422,
            detail="Only http/https URLs are allowed",
        )

    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=422, detail="URL must have a hostname")

    # Block localhost variants
    if (
        host in ("localhost", "localhost.localdomain")
        or host.endswith(".local")
    ):
        raise HTTPException(
            status_code=422,
            detail="localhost and .local hostnames are not allowed",
        )

    # If the host is a bare IP address, check it directly
    try:
        if _is_private_ip(host):
            raise HTTPException(
                status_code=422,
                detail="Private/reserved IP addresses are not allowed",
            )
    except ValueError:
        pass  # not a bare IP — fall through to DNS resolution

    # DNS resolve and re-check every resolved address
    try:
        resolved = socket.getaddrinfo(host, None)
        for _family, _type, _proto, _canonname, sockaddr in resolved:
            ip = sockaddr[0]
            if _is_private_ip(ip):
                raise HTTPException(
                    status_code=422,
                    detail=f"URL resolves to a private IP: {ip}",
                )
    except socket.gaierror:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot resolve hostname: {host}",
        )

    return url


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------


def _decode_token(token: str) -> dict:
    """Decode and verify a JWT. Raises HTTPException 401 on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
) -> dict:
    """Require a valid Bearer JWT; return the decoded payload."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return _decode_token(credentials.credentials)


async def require_admin(
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Require the caller to hold an admin or dev role."""
    if user.get("role") not in ("admin", "dev"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_dev(
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Require the caller to hold the dev role."""
    if user.get("role") != "dev":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev access required",
        )
    return user


# ---------------------------------------------------------------------------
# Database / cache dependencies
# ---------------------------------------------------------------------------


async def get_supabase_client():
    """Yield an async Supabase client (service-role key — server-only)."""
    from backend.db.sql import get_supabase

    return await get_supabase()


async def get_redis():
    """Yield a Redis connection and ensure it is closed after the request."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield r
    finally:
        await r.aclose()


# ---------------------------------------------------------------------------
# Storage dependency
# ---------------------------------------------------------------------------


async def get_storage():
    """Return the Supabase storage client for the pattern-proof bucket."""
    from backend.db.sql import get_supabase

    client = await get_supabase()
    return client.storage.from_("pattern-proof")


# ---------------------------------------------------------------------------
# Event bus dependency
# ---------------------------------------------------------------------------


def get_event_bus(request):  # noqa: F821
    """
    Retrieve the EventBus from application state.

    Usage in route handlers:
        from fastapi import Request
        @router.post("/...")
        async def my_route(request: Request):
            bus = request.app.state.event_bus
            ...
    """
    return request.app.state.event_bus
