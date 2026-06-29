"""
Minimal JWT auth for SousChef admin routes.

One hardcoded admin user, credentials supplied via env vars
(ADMIN_USERNAME + ADMIN_PASSWORD_HASH). Tokens are HS256 JWTs carrying a
`role: "admin"` claim. Only role-gated routes depend on get_current_user.
"""
from __future__ import annotations

import datetime as dt
import os

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def _secret() -> str:
    return os.getenv("JWT_SECRET_KEY", "change-me-in-production")


def _algorithm() -> str:
    return os.getenv("JWT_ALGORITHM", "HS256")


def _expire_minutes() -> int:
    try:
        return int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
    except ValueError:
        return 30


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return a bcrypt hash (utf-8 string) for the given plaintext password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check of a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Credentials ───────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> bool:
    """True iff username + password match the configured admin credentials."""
    expected_user = os.getenv("ADMIN_USERNAME", "admin")
    expected_hash = os.getenv("ADMIN_PASSWORD_HASH", "")
    if not expected_hash:
        return False
    if username != expected_user:
        return False
    return verify_password(password, expected_hash)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    """Encode an HS256 JWT with an `exp` claim."""
    to_encode = dict(data)
    minutes = expires_minutes if expires_minutes is not None else _expire_minutes()
    expire = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, _secret(), algorithm=_algorithm())


_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Decode + validate the bearer token. Raises 401 on missing/invalid/expired
    token, 403 if the `role` claim is not "admin". Returns the payload dict.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_algorithm()])
    except jwt.ExpiredSignatureError:
        raise _CREDENTIALS_EXC
    except jwt.PyJWTError:
        raise _CREDENTIALS_EXC

    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return payload
