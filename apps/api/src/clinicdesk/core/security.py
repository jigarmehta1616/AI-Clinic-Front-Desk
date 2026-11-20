"""Token and OTP primitives (ADR-0007). No I/O here."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    session_family: uuid.UUID
    clinic_id: uuid.UUID | None
    role: str | None
    is_platform_admin: bool
    doctor_id: uuid.UUID | None = None


def encode_access_token(claims: AccessClaims, *, secret: str, kid: str, now: datetime, ttl: timedelta) -> str:
    payload = {
        "sub": str(claims.user_id),
        "sid": str(claims.session_family),
        "cid": str(claims.clinic_id) if claims.clinic_id else None,
        "role": claims.role,
        "pa": claims.is_platform_admin,
        "did": str(claims.doctor_id) if claims.doctor_id else None,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM, headers={"kid": kid})


def decode_access_token(token: str, *, secret: str, now: datetime) -> AccessClaims:
    """Raises jwt.InvalidTokenError on any problem."""
    payload = jwt.decode(
        token,
        secret,
        algorithms=[ALGORITHM],
        # Time claims are checked below against the injected clock, not wall time.
        options={"require": ["exp", "iat", "sub", "typ"], "verify_exp": False, "verify_iat": False},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    ts = int(now.timestamp())
    if int(payload["exp"]) <= ts:
        raise jwt.ExpiredSignatureError("expired")
    if int(payload["iat"]) > ts + 60:
        raise jwt.ImmatureSignatureError("issued in the future")
    return AccessClaims(
        user_id=uuid.UUID(payload["sub"]),
        session_family=uuid.UUID(payload["sid"]),
        clinic_id=uuid.UUID(payload["cid"]) if payload.get("cid") else None,
        role=payload.get("role"),
        is_platform_admin=bool(payload.get("pa")),
        doctor_id=uuid.UUID(payload["did"]) if payload.get("did") else None,
    )


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(phone: str, code: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(phone: str, code: str, pepper: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(phone, code, pepper), expected_hash)
