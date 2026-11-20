"""NFR-10 — token and OTP primitives; RBAC matrix (FRD §3)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from clinicdesk.core.rbac import Permission, Role, has_permission
from clinicdesk.core.security import (
    AccessClaims,
    decode_access_token,
    encode_access_token,
    hash_otp,
    new_otp_code,
    otp_matches,
)
from clinicdesk.modules.tenancy.schemas import normalize_phone

SECRET = "x" * 40
NOW = datetime(2026, 11, 23, 5, 0, tzinfo=UTC)
CLAIMS = AccessClaims(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "receptionist", False)


def test_access_token_roundtrip_and_expiry():
    tok = encode_access_token(CLAIMS, secret=SECRET, kid="k1", now=NOW, ttl=timedelta(minutes=15))
    assert decode_access_token(tok, secret=SECRET, now=NOW + timedelta(minutes=14)) == CLAIMS
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(tok, secret=SECRET, now=NOW + timedelta(minutes=15))


def test_access_token_tampering_rejected():
    tok = encode_access_token(CLAIMS, secret=SECRET, kid="k1", now=NOW, ttl=timedelta(minutes=15))
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tok, secret="y" * 40, now=NOW)
    forged = jwt.encode({"sub": "x", "typ": "access", "iat": 0, "exp": 9e9}, "z" * 40, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged, secret=SECRET, now=NOW)
    unsigned = jwt.encode({"sub": "x", "typ": "access", "iat": 0, "exp": 9e9}, None, algorithm="none")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(unsigned, secret=SECRET, now=NOW)


def test_otp_hash_binds_phone_and_code():
    code = new_otp_code()
    assert len(code) == 6 and code.isdigit()
    h = hash_otp("+919800000001", code, SECRET)
    assert otp_matches("+919800000001", code, SECRET, h)
    assert not otp_matches("+919800000002", code, SECRET, h)


@pytest.mark.parametrize(
    ("role", "perm", "allowed"),
    [
        (Role.RECEPTIONIST, Permission.APPOINTMENT_BOOK, True),
        (Role.RECEPTIONIST, Permission.RECALL_RULES_MANAGE, False),
        (Role.RECEPTIONIST, Permission.BILLING_MANAGE, False),
        (Role.DOCTOR, Permission.APPOINTMENT_STATUS, True),
        (Role.DOCTOR, Permission.STAFF_MANAGE, False),
        (Role.DOCTOR, Permission.BILLING_MANAGE, False),
        (Role.OWNER, Permission.BILLING_MANAGE, True),
        (None, Permission.CLINIC_READ, False),
        ("hacker", Permission.CLINIC_READ, False),
    ],
)
def test_rbac_matrix(role, perm, allowed):
    assert has_permission(role, perm) is allowed


@pytest.mark.parametrize(
    ("raw", "out"),
    [("98765 43210", "+919876543210"), ("919876543210", "+919876543210"), ("+14155550100", "+14155550100")],
)
def test_phone_normalisation(raw, out):
    assert normalize_phone(raw) == out


@pytest.mark.parametrize("raw", ["12345", "abc", "+0123456789", "5876543210"])
def test_phone_rejects_invalid(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)
