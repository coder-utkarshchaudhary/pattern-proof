"""
Auth routes for Pattern Proof.

Provides email/password signup, login, JWT refresh, logout, and a
/me endpoint to retrieve the current user. A restricted /dev-token
endpoint is available only in the development environment.

Security notes:
- Passwords, tokens, and hashes are NEVER logged.
- Argon2id (via argon2-cffi) is used for password hashing.
- Refresh tokens are opaque URL-safe random bytes; only their SHA-256
  hash is persisted (stored hash in refresh_tokens table).
- JWT access tokens are short-lived (settings.access_token_ttl_minutes).
- Refresh tokens are long-lived (settings.refresh_token_ttl_days) and
  rotated on every use.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from pydantic import BaseModel, EmailStr

from api.dependencies import get_current_user
from config import settings
from db.sql import RefreshTokenRepo, UserRepo, get_supabase
from models.schema import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from models.taxonomy import UserRole
from utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

_ph = PasswordHasher()


# ---------------------------------------------------------------------------
# Local schema for /dev-token (not in shared schema.py)
# ---------------------------------------------------------------------------


class DevTokenRequest(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.DEV


# ---------------------------------------------------------------------------
# Internal token helpers
# ---------------------------------------------------------------------------


def _issue_access_token(user_id: str, role: str) -> str:
    """Mint a short-lived JWT access token."""
    now = datetime.utcnow()
    exp = now + timedelta(minutes=settings.access_token_ttl_minutes)
    return jwt.encode(
        {
            "sub": str(user_id),
            "role": role,
            "iat": now,
            "exp": exp,
            "token_type": "access",
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _issue_refresh_token(user_id: str) -> tuple[str, str]:
    """
    Generate a refresh token pair.

    Returns:
        (raw_token, token_hash) — store only the hash; send the raw value
        to the client.
    """
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, token_hash


def _refresh_token_expires_at() -> str:
    """Return the ISO-formatted expiry datetime for a new refresh token."""
    return (
        datetime.utcnow() + timedelta(days=settings.refresh_token_ttl_days)
    ).isoformat()


def _parse_expires_at(value: str | datetime) -> datetime:
    """
    Parse a refresh token expires_at value into a naive UTC datetime.

    Supabase may return a timezone-aware ISO string; normalise to naive
    UTC so comparisons against datetime.utcnow() (also naive) don't raise.
    """
    if isinstance(value, str):
        # Replace trailing Z with +00:00 — Python 3.10's fromisoformat
        # does not accept the Z suffix (fixed in 3.11+).
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = value
    # Strip timezone info to get a naive UTC datetime
    if dt.tzinfo is not None:
        dt = dt.utctimetuple()
        dt = datetime(*dt[:6])
    return dt


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(req: SignupRequest) -> TokenResponse:
    """
    Register a new user account.

    - 409 if the e-mail is already registered.
    - Returns an access token + refresh token on success.
    """
    client = await get_supabase()
    user_repo = UserRepo(client)
    rt_repo = RefreshTokenRepo(client)

    # Check for existing account
    existing = await user_repo.get_by_email(req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Hash password — must use .get_secret_value() to unwrap SecretStr
    password_hash = _ph.hash(req.password.get_secret_value())

    # Persist the user
    user = await user_repo.create(
        email=req.email,
        password_hash=password_hash,
        display_name=req.display_name,
        role=UserRole.USER.value,
    )

    user_id = str(user["id"])
    role = user.get("role", UserRole.USER.value)

    logger.info("User registered", extra={"user_id": user_id})

    # Issue tokens
    access_token = _issue_access_token(user_id, role)
    raw_refresh, refresh_hash = _issue_refresh_token(user_id)
    expires_at = _refresh_token_expires_at()

    await rt_repo.create(
        user_id=user_id,
        token_hash=refresh_hash,
        expires_at=expires_at,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    """
    Authenticate with email and password.

    - 401 if the email is not found or the password is incorrect.
    - Returns an access token + refresh token on success.
    """
    client = await get_supabase()
    user_repo = UserRepo(client)
    rt_repo = RefreshTokenRepo(client)

    user = await user_repo.get_by_email(req.email)
    if not user:
        # Use a generic error to avoid leaking whether the email exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password — must use .get_secret_value() to unwrap SecretStr
    try:
        _ph.verify(user["password_hash"], req.password.get_secret_value())
    except VerifyMismatchError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = str(user["id"])
    role = user.get("role", UserRole.USER.value)

    logger.info("User logged in", extra={"user_id": user_id})

    # Issue tokens
    access_token = _issue_access_token(user_id, role)
    raw_refresh, refresh_hash = _issue_refresh_token(user_id)
    expires_at = _refresh_token_expires_at()

    await rt_repo.create(
        user_id=user_id,
        token_hash=refresh_hash,
        expires_at=expires_at,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest) -> TokenResponse:
    """
    Exchange a valid refresh token for a new access + refresh token pair.

    - 401 if the refresh token is unknown, revoked, or expired.
    - Rotates the refresh token on every use (revoke old, issue new).
    """
    raw = req.refresh_token
    token_hash = hashlib.sha256(raw.encode()).hexdigest()

    client = await get_supabase()
    rt_repo = RefreshTokenRepo(client)

    stored = await rt_repo.get_active(token_hash)
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce expiry (the repo only filters on revoked_at, not expires_at)
    expires_at = _parse_expires_at(stored["expires_at"])
    if datetime.utcnow() > expires_at:
        # Revoke silently so the record is cleaned up
        await rt_repo.revoke(token_hash)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = str(stored["user_id"])

    # Fetch user to get current role
    user_repo = UserRepo(client)
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role = user.get("role", UserRole.USER.value)

    # Rotate: revoke old token, issue new pair
    await rt_repo.revoke(token_hash)

    access_token = _issue_access_token(user_id, role)
    raw_new, hash_new = _issue_refresh_token(user_id)
    new_expires_at = _refresh_token_expires_at()

    await rt_repo.create(
        user_id=user_id,
        token_hash=hash_new,
        expires_at=new_expires_at,
    )

    logger.info("Tokens refreshed", extra={"user_id": user_id})

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_new,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(req: RefreshRequest) -> None:
    """
    Revoke a refresh token (logout).

    Silently succeeds even if the token was already revoked or unknown
    (prevents information leakage about token state).
    """
    token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()

    client = await get_supabase()
    rt_repo = RefreshTokenRepo(client)

    # Revoke regardless — if not present or already revoked this is a no-op
    await rt_repo.revoke(token_hash)
    logger.info("Refresh token revoked")


@router.get("/me", response_model=UserResponse)
async def me(
    payload: Annotated[dict, Depends(get_current_user)],
) -> UserResponse:
    """
    Return the currently authenticated user's profile.

    Requires a valid Bearer access token.
    """
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    client = await get_supabase()
    user_repo = UserRepo(client)
    user = await user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(**user)


@router.post("/dev-token", response_model=TokenResponse)
async def dev_token(req: DevTokenRequest) -> TokenResponse:
    """
    Issue a JWT access token without a password (development use only).

    DISABLED unless BE_APP_ENV=development. Returns 403 in all other
    environments. Creates the user account if it does not already exist.
    """
    if settings.app_env != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev token endpoint is only available in development",
        )

    client = await get_supabase()
    user_repo = UserRepo(client)

    user = await user_repo.get_by_email(req.email)
    if not user:
        # Create a placeholder account with a random, unhashable password
        placeholder_hash = _ph.hash(secrets.token_urlsafe(32))
        user = await user_repo.create(
            email=req.email,
            password_hash=placeholder_hash,
            display_name=None,
            role=req.role.value,
        )
        logger.info(
            "Dev user created",
            extra={"user_id": str(user["id"]), "role": req.role.value},
        )

    user_id = str(user["id"])
    role = user.get("role", req.role.value)

    access_token = _issue_access_token(user_id, role)

    logger.info(
        "Dev token issued",
        extra={"user_id": user_id, "role": role},
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=None,
        expires_in=settings.access_token_ttl_minutes * 60,
    )
