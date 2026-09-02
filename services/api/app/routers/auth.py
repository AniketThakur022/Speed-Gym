"""Auth router — /api/v1/auth per memory `api-contract-v1`.

register/login/refresh/me (email+password, rotating refresh with replay
detection that revokes the device session — pre-loss demo parity), QR
scanner-login pairing (300-s one-time HMAC-signed nonce in Redis), and the
Firebase adapter routes (kept for the frozen APK contract, 501 until an IdP
config exists).
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Optional

import psycopg.errors
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .. import db
from ..security import (
    get_current_user,
    hash_password,
    issue_tokens,
    mint_access_token,
    qr_signature,
    refresh_token_hash,
    user_public,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

QR_TTL_SECONDS = 300


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refreshToken: str


class IdTokenRequest(BaseModel):
    idToken: str


class QrVerifyRequest(BaseModel):
    code: str
    sig: str


def _fingerprint(request: Request) -> Optional[str]:
    return request.headers.get("X-Device-Fingerprint")


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, request: Request) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        try:
            row = await (
                await conn.execute(
                    """INSERT INTO users (email, password_hash, display_name)
                       VALUES (%s, %s, %s)
                       RETURNING id, email, display_name, tier""",
                    (body.email.lower(), hash_password(body.password), body.display_name),
                )
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(status_code=409, detail="email already registered")
        return await issue_tokens(conn, row, _fingerprint(request))


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT id, email, display_name, tier, password_hash FROM users WHERE email = %s",
                (body.email.lower(),),
            )
        ).fetchone()
        if row is None or not verify_password(body.password, row[4]):
            raise HTTPException(status_code=401, detail="invalid credentials")
        return await issue_tokens(conn, row[:4], _fingerprint(request))


@router.post("/refresh")
async def refresh(body: RefreshRequest, request: Request) -> dict:
    token_hash = refresh_token_hash(body.refreshToken)
    now = datetime.now(timezone.utc)
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT jti, user_id, expires_at, rotated_to, revoked_at, device_fingerprint
                   FROM refresh_tokens WHERE token_hash = %s""",
                (token_hash,),
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="invalid refresh token")
        jti, user_id, expires_at, rotated_to, revoked_at, device_fp = row

        if revoked_at is not None:
            raise HTTPException(status_code=401, detail="refresh token revoked")

        if rotated_to is not None:
            # Replay of an already-rotated token — kill the whole device session.
            await conn.execute(
                """UPDATE refresh_tokens
                   SET revoked_at = NOW(), revoke_reason = 'rotation_replay'
                   WHERE user_id = %s
                     AND device_fingerprint IS NOT DISTINCT FROM %s
                     AND revoked_at IS NULL""",
                (user_id, device_fp),
            )
            # Commit before raising: the connection context manager rolls back
            # on exception, which would silently discard the revocation.
            await conn.commit()
            raise HTTPException(
                status_code=401,
                detail="refresh token replay detected; device session revoked",
            )

        if expires_at <= now:
            raise HTTPException(status_code=401, detail="refresh token expired")

        user_row = await (
            await conn.execute(
                "SELECT id, email, display_name, tier FROM users WHERE id = %s", (user_id,)
            )
        ).fetchone()
        if user_row is None:
            raise HTTPException(status_code=401, detail="unknown user")

        tokens = await issue_tokens(conn, user_row, device_fp)
        new_jti = await (
            await conn.execute(
                "SELECT jti FROM refresh_tokens WHERE token_hash = %s",
                (refresh_token_hash(tokens["refreshToken"]),),
            )
        ).fetchone()
        await conn.execute(
            "UPDATE refresh_tokens SET rotated_to = %s WHERE jti = %s", (new_jti[0], jti)
        )
        return tokens


@router.post("/logout")
async def logout(body: RefreshRequest) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        await conn.execute(
            """UPDATE refresh_tokens
               SET revoked_at = NOW(), revoke_reason = 'logout'
               WHERE token_hash = %s AND revoked_at IS NULL""",
            (refresh_token_hash(body.refreshToken),),
        )
    return {"status": "logged_out"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    return {"user": user}


# ── QR scanner-login (300-s one-time HMAC-signed nonce; QR-01..06) ──────────


@router.post("/scanner-login/generate")
async def scanner_login_generate() -> dict:
    code = secrets.token_urlsafe(16)
    poll_token = secrets.token_urlsafe(16)
    redis = db.get_redis()
    await redis.set(
        f"qr:pair:{code}",
        json.dumps({"status": "pending", "poll": poll_token}),
        ex=QR_TTL_SECONDS,
    )
    return {
        "code": code,
        "sig": qr_signature(code),
        "pollToken": poll_token,
        "expiresIn": QR_TTL_SECONDS,
    }


@router.post("/scanner-login/verify")
async def scanner_login_verify(
    body: QrVerifyRequest, user: dict = Depends(get_current_user)
) -> dict:
    if body.sig != qr_signature(body.code):
        raise HTTPException(status_code=400, detail="bad QR signature")
    redis = db.get_redis()
    key = f"qr:pair:{body.code}"
    state_raw = await redis.get(key)
    if state_raw is None:
        raise HTTPException(status_code=410, detail="pairing code expired or used")
    state = json.loads(state_raw)
    if state["status"] != "pending":
        raise HTTPException(status_code=409, detail="pairing code already approved")
    state.update(status="approved", user_id=user["id"])
    await redis.set(key, json.dumps(state), keepttl=True)
    return {"status": "approved"}


@router.get("/scanner-login/poll")
async def scanner_login_poll(code: str, pollToken: str, request: Request) -> dict:
    redis = db.get_redis()
    key = f"qr:pair:{code}"
    state_raw = await redis.get(key)
    if state_raw is None:
        raise HTTPException(status_code=410, detail="pairing code expired or used")
    state = json.loads(state_raw)
    if not secrets.compare_digest(state.get("poll", ""), pollToken):
        raise HTTPException(status_code=403, detail="bad poll token")
    if state["status"] == "pending":
        return {"status": "pending"}

    pool = await db.get_pg()
    async with pool.connection() as conn:
        user_row = await (
            await conn.execute(
                "SELECT id, email, display_name, tier FROM users WHERE id = %s",
                (state["user_id"],),
            )
        ).fetchone()
        if user_row is None:
            raise HTTPException(status_code=410, detail="pairing user no longer exists")
        tokens = await issue_tokens(conn, user_row, _fingerprint(request))
    await redis.delete(key)  # one-time nonce burns on collection
    return {"status": "approved", **tokens}


# ── Firebase adapter routes (frozen APK contract; pluggable IdP, 501 until
#    FIREBASE_* config exists — see api-contract-v1) ─────────────────────────


@router.post("/google", status_code=501)
async def auth_google(body: IdTokenRequest) -> dict:
    raise HTTPException(
        status_code=501,
        detail="Google idToken exchange not configured (owner decision: email/password + QR ship first)",
    )


@router.post("/phone", status_code=501)
async def auth_phone(body: IdTokenRequest) -> dict:
    raise HTTPException(
        status_code=501,
        detail="Phone idToken exchange not configured (owner decision: email/password + QR ship first)",
    )
