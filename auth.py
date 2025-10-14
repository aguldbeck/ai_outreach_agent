# auth.py — Supabase JWT verification (RS256 via JWKS) with HS256 fallback
# Compatible with: Render + Supabase + Lovable frontends

import os
import json
import requests
from jose import jwt
from jose.exceptions import JWTError, ExpiredSignatureError
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta

# ---------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------
SUPABASE_PROJECT_REF = os.getenv("SUPABASE_PROJECT_REF", "fegmlnvmmuauohitkngx")
SUPABASE_URL = os.getenv("SUPABASE_URL", f"https://{SUPABASE_PROJECT_REF}.supabase.co").rstrip("/")
SUPABASE_JWKS_URL = os.getenv("SUPABASE_JWKS_URL", f"{SUPABASE_URL}/auth/v1/jwks")
SUPABASE_AUDIENCE = os.getenv("SUPABASE_AUDIENCE", "authenticated")

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-secret")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")

# ---------------------------------------------------------------------
# Auth security setup
# ---------------------------------------------------------------------
http_bearer = HTTPBearer(auto_error=False)

# Cache the JWKS to reduce Supabase requests
_JWKS_CACHE = None
_JWKS_LAST_FETCH = None
_JWKS_CACHE_TTL = 60 * 60  # 1 hour


def get_jwks():
    """Fetch and cache JWKS keys from Supabase."""
    global _JWKS_CACHE, _JWKS_LAST_FETCH
    now = datetime.utcnow()
    if _JWKS_CACHE and _JWKS_LAST_FETCH and (now - _JWKS_LAST_FETCH).seconds < _JWKS_CACHE_TTL:
        return _JWKS_CACHE
    try:
        print(f"Fetching JWKS from: {SUPABASE_JWKS_URL}")
        res = requests.get(SUPABASE_JWKS_URL, timeout=10)
        res.raise_for_status()
        _JWKS_CACHE = res.json()
        _JWKS_LAST_FETCH = now
        return _JWKS_CACHE
    except Exception as e:
        print(f"[auth.py] Failed to fetch JWKS: {e}")
        return None


def verify_supabase_token(token: str):
    """Try verifying a Supabase JWT using RS256 + JWKS."""
    jwks = get_jwks()
    if not jwks or "keys" not in jwks:
        raise HTTPException(status_code=401, detail="Failed to load JWKS")

    try:
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == header.get("kid")), None)
        if not key:
            raise HTTPException(status_code=401, detail="Public key not found in JWKS")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=SUPABASE_AUDIENCE,
            issuer=f"{SUPABASE_URL}/auth/v1",
        )
        return payload
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Supabase token: {e}")


def verify_local_token(token: str):
    """Fallback local HS256 JWT validation."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid local token")


def verify_token(token: str):
    """Main token verification pipeline."""
    try:
        # Try Supabase first
        return verify_supabase_token(token)
    except HTTPException as e:
        print(f"[auth.py] Supabase verification failed: {e.detail}")
        # Fallback to local
        return verify_local_token(token)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(http_bearer)):
    """FastAPI dependency to inject current user from Authorization header."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = credentials.credentials
    user_data = verify_token(token)
    return user_data


# ---------------------------------------------------------------------
# Token generator (for internal/local service use only)
# ---------------------------------------------------------------------
def create_local_token(data: dict, expires_minutes: int = 120):
    """Generate a simple HS256 token (used for internal service calls)."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)
    return encoded_jwt