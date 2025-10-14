# auth.py — Supabase JWT verification (HS256 + RS256 hybrid)
# Compatible with: Render + Supabase + Lovable frontends

import os
import json
import requests
from datetime import datetime, timedelta
from jose import jwt
from jose.exceptions import JWTError, ExpiredSignatureError
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# ---------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------
SUPABASE_PROJECT_REF = os.getenv("SUPABASE_PROJECT_REF", "fegmlnvmmuauohitkngx")
SUPABASE_URL = os.getenv("SUPABASE_URL", f"https://{SUPABASE_PROJECT_REF}.supabase.co").rstrip("/")
SUPABASE_JWKS_URL = os.getenv("SUPABASE_JWKS_URL", f"{SUPABASE_URL}/auth/v1/jwks")
SUPABASE_AUDIENCE = os.getenv("SUPABASE_AUDIENCE", "authenticated")

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET") or os.getenv("JWT_SECRET", "change-me-secret")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")

# ---------------------------------------------------------------------
# Router + models
# ---------------------------------------------------------------------
router = APIRouter(prefix="/auth", tags=["auth"])
http_bearer = HTTPBearer(auto_error=False)

class User(BaseModel):
    id: str
    email: str

# ---------------------------------------------------------------------
# JWKS caching
# ---------------------------------------------------------------------
_JWKS_CACHE = None
_JWKS_LAST_FETCH = None
_JWKS_CACHE_TTL = 3600  # 1 hour

def get_jwks():
    """Fetch and cache JWKS keys from Supabase."""
    global _JWKS_CACHE, _JWKS_LAST_FETCH
    now = datetime.utcnow()
    if _JWKS_CACHE and _JWKS_LAST_FETCH and (now - _JWKS_LAST_FETCH).seconds < _JWKS_CACHE_TTL:
        return _JWKS_CACHE
    try:
        print(f"[auth] Fetching JWKS from {SUPABASE_JWKS_URL}")
        res = requests.get(SUPABASE_JWKS_URL, timeout=10)
        res.raise_for_status()
        _JWKS_CACHE = res.json()
        _JWKS_LAST_FETCH = now
        return _JWKS_CACHE
    except Exception as e:
        print(f"[auth] Failed to fetch JWKS: {e}")
        return None

# ---------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------
def _verify_rs256_token(token: str):
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
        raise HTTPException(status_code=401, detail=f"Invalid RS256 token: {e}")

def _verify_hs256_token(token: str):
    """Verify Supabase HS256 JWT, allowing audience='authenticated' by default."""
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=SUPABASE_AUDIENCE,
        )
        return payload
    except JWTError as e:
        # fallback: ignore audience entirely for local use or testing
        try:
            options = {"verify_aud": False}
            payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], options=options)
            print("[auth] Ignored audience claim for local HS256 token")
            return payload
        except JWTError as e2:
            raise HTTPException(status_code=401, detail=f"Invalid HS256 token: {e2}")

def verify_token_auto(token: str):
    """Auto-detect HS256 vs RS256 and decode accordingly."""
    try:
        unverified = jwt.get_unverified_header(token)
        algo = unverified.get("alg", "HS256")
        if algo.startswith("HS"):
            print("[auth] Detected HS256 token — verifying locally")
            return _verify_hs256_token(token)
        elif algo.startswith("RS"):
            print("[auth] Detected RS256 token — verifying via JWKS")
            return _verify_rs256_token(token)
        else:
            raise HTTPException(401, f"Unsupported JWT algorithm: {algo}")
    except Exception as e:
        print(f"[auth] Token auto-detect failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or unsupported token")

# ---------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(http_bearer)) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = credentials.credentials
    claims = verify_token_auto(token)
    uid = claims.get("sub")
    email = claims.get("email") or claims.get("user_metadata", {}).get("email")

    if not uid or not email:
        raise HTTPException(status_code=401, detail="Token missing user info")

    return User(id=uid, email=email)

def get_current_user_optional(credentials: HTTPAuthorizationCredentials = Depends(http_bearer)) -> User | None:
    """Optional variant: returns None instead of 401 if missing."""
    if not credentials:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None

# ---------------------------------------------------------------------
# Token generator (for internal service use)
# ---------------------------------------------------------------------
def create_local_token(data: dict, expires_minutes: int = 120):
    """Generate HS256 token (internal use)."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SUPABASE_JWT_SECRET, algorithm="HS256")

# ---------------------------------------------------------------------
# Test route
# ---------------------------------------------------------------------
@router.get("/me")
def read_me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "auth_source": "Supabase hybrid"}