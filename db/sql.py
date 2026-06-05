"""
Async Supabase (Postgres) repository.

Uses the async supabase-py v2 client with the service-role key.
RLS is bypassed server-side; all authorisation is enforced in application code.

SECURITY:
- Never log the service-role key, JWTs, or raw passwords.
- The service-role key must never be returned to clients.
"""
from __future__ import annotations

from datetime import datetime

from supabase import acreate_client, AClient as AsyncClient

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


async def get_supabase() -> AsyncClient:
    """Create an async Supabase client. Call once per request via dependency."""
    client = await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    return client


# ---------------------------------------------------------------------------
# User repository
# ---------------------------------------------------------------------------


class UserRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._c = client

    async def create(
        self,
        email: str,
        password_hash: str,
        display_name: str | None,
        role: str,
    ) -> dict:
        res = await self._c.table("users").insert(
            {
                "email": email,
                "password_hash": password_hash,
                "display_name": display_name,
                "role": role,
                "is_active": True,
            }
        ).execute()
        return res.data[0]

    async def get_by_email(self, email: str) -> dict | None:
        res = (
            await self._c.table("users")
            .select("*")
            .eq("email", email)
            .maybe_single()
            .execute()
        )
        return res.data

    async def get_by_id(self, user_id: str) -> dict | None:
        res = (
            await self._c.table("users")
            .select("*")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        return res.data


# ---------------------------------------------------------------------------
# RefreshToken repository
# ---------------------------------------------------------------------------


class RefreshTokenRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._c = client

    async def create(
        self, user_id: str, token_hash: str, expires_at: str
    ) -> dict:
        res = await self._c.table("refresh_tokens").insert(
            {
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": expires_at,
            }
        ).execute()
        return res.data[0]

    async def get_active(self, token_hash: str) -> dict | None:
        res = await (
            self._c.table("refresh_tokens")
            .select("*")
            .eq("token_hash", token_hash)
            .is_("revoked_at", "null")
            .maybe_single()
            .execute()
        )
        return res.data

    async def revoke(self, token_hash: str) -> None:
        await self._c.table("refresh_tokens").update(
            {"revoked_at": datetime.utcnow().isoformat()}
        ).eq("token_hash", token_hash).execute()


# ---------------------------------------------------------------------------
# Audit repository
# ---------------------------------------------------------------------------


class AuditRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._c = client

    async def create(
        self,
        user_id: str,
        url: str,
        normalized_domain: str,
        config_json: dict,
    ) -> dict:
        import json

        res = await self._c.table("audits").insert(
            {
                "user_id": user_id,
                "url": url,
                "normalized_domain": normalized_domain,
                "status": "created",
                "config_json": json.dumps(config_json),
                "progress_percent": 0.0,
            }
        ).execute()
        return res.data[0]

    async def get(self, audit_id: str) -> dict | None:
        res = (
            await self._c.table("audits")
            .select("*")
            .eq("id", audit_id)
            .maybe_single()
            .execute()
        )
        return res.data

    async def list_for_user(self, user_id: str) -> list[dict]:
        res = (
            await self._c.table("audits")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data

    async def update_status(
        self,
        audit_id: str,
        status: str,
        progress: float,
        phase: str,
        error: str | None = None,
    ) -> None:
        update: dict = {
            "status": status,
            "progress_percent": progress,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if error:
            update["error_message"] = error
        if status == "completed":
            update["completed_at"] = datetime.utcnow().isoformat()
        await self._c.table("audits").update(update).eq("id", audit_id).execute()


# ---------------------------------------------------------------------------
# Finding repository
# ---------------------------------------------------------------------------


class FindingRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._c = client

    async def create(self, finding: dict) -> dict:
        res = await self._c.table("findings").insert(finding).execute()
        return res.data[0]

    async def list_for_audit(self, audit_id: str) -> list[dict]:
        res = (
            await self._c.table("findings")
            .select("*")
            .eq("audit_id", audit_id)
            .execute()
        )
        return res.data


# ---------------------------------------------------------------------------
# Report repository
# ---------------------------------------------------------------------------


class ReportRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._c = client

    async def create(self, audit_id: str, fmt: str, report_uri: str) -> dict:
        res = await self._c.table("reports").insert(
            {
                "audit_id": audit_id,
                "format": fmt,
                "report_uri": report_uri,
                "generated_at": datetime.utcnow().isoformat(),
            }
        ).execute()
        return res.data[0]

    async def get(self, audit_id: str, fmt: str) -> dict | None:
        res = await (
            self._c.table("reports")
            .select("*")
            .eq("audit_id", audit_id)
            .eq("format", fmt)
            .maybe_single()
            .execute()
        )
        return res.data
