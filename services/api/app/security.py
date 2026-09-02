"""Auth primitives — password hashing (stdlib scrypt), 15-min access JWTs,
opaque rotating refresh tokens (SHA-256 at rest), bearer dependency.

Contract: memory `api-contract-v1`. JWT_SECRET is shared with the Node game
server as deploy-time config; refresh tokens never leave this service except
as opaque strings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, Request
from jose import JWTError, jwt

from .config import get_settings
from . import db

SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 16384, 8, 1, 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=SCRYPT_DKLEN,
        )
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def mint_access_token(user_id: str, tier: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tier": tier,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="invalid or expired access token")


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the client, sha256 hex for the ledger)."""
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def refresh_token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def qr_signature(code: str) -> str:
    settings = get_settings()
    return hmac.new(settings.jwt_secret.encode(), b"qr:" + code.encode(), hashlib.sha256).hexdigest()


def user_public(row: Any) -> dict:
    """APK contract user shape: {id, name, email, role} (+tier, additive)."""
    user_id, email, display_name, tier = row
    return {
        "id": str(user_id),
        "name": display_name,
        "email": email,
        "role": "user",
        "tier": tier,
    }


async def issue_tokens(conn, user_row: Any, device_fingerprint: Optional[str]) -> dict:
    settings = get_settings()
    user = user_public(user_row)
    raw_refresh, token_hash = new_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)
    await conn.execute(
        """INSERT INTO refresh_tokens (user_id, token_hash, device_fingerprint, expires_at)
           VALUES (%s, %s, %s, %s)""",
        (user["id"], token_hash, device_fingerprint, expires_at),
    )
    return {
        "user": user,
        "token": mint_access_token(user["id"], user["tier"]),
        "refreshToken": raw_refresh,
    }


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    payload = decode_access_token(auth.removeprefix("Bearer ").strip())
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT id, email, display_name, tier FROM users WHERE id = %s",
                (payload["sub"],),
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="unknown user")
    return user_public(row)
