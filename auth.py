# auth.py — fixed for Supabase JWT verification via RS256 (JWKS)
# Also keeps fallback local auth for testing

import os
import json
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import requests
from fastapi import APIRouter, Form, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from jose import jwt, jwk
from jose.utils import base64url_decode
from passlib.hash import pbkdf2_sha256
from dotenv import load_dotenv

# -----------------------------
# Setup / env
# -----------------------------
load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-secret")  # fallback HS256 for local mode
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")
JWT_EXPIRES_MIN = int(os.getenv("JWT_EXPIRES_MIN", "120"))

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_PROJECT_REF = (
    SUPABASE_URL.split("//")[1].split(".")[0]
    if SUPABASE_URL.startswith("https://")
    else os.getenv("SUPABASE_PROJECT_REF", "").strip()
)

SUPABASE_ISSUER = f"https://{SUPABASE_PROJECT_REF}.supabase.co/auth/v1" if SUPABASE_PROJECT_REF else ""
SUPABASE_JWKS_URL = f"{SUPABASE_ISSUER}/keys" if SUPABASE_PROJECT_REF else ""
SUPABASE_AUDIENCE = os.getenv("SUPABASE_AUDIENCE", "authenticated")

USERS_FILE = os.path.join(os.getcwd(), "users.json")

# -----------------------------
# File helpers
# -----------------------------
def _read_json(path: str, fallback):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return fallback

def _write_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# -----------------------------
# Models
# -----------------------------
class Token(BaseModel):
    access_token: str
    token_type: str

class User(BaseModel):
    id: str
    email: EmailStr

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)
router = APIRouter(prefix="/auth", tags=["auth"])

# -----------------------------
# Local JWT utilities
# -----------------------------
def create_local_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=JWT_EXPIRES_MIN))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)

def decode_local_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])

# -----------------------------
# Supabase JWT verification (RS256)
# -----------------------------
_JWKS_CACHE: Dict[str, Any] = {}
_JWKS_FETCHED_AT = 0
_JWKS_TTL = 3600  # seconds

def _load_jwks() -> Dict[str, Any]:
    """Fetch JWKS from Supabase (cached)."""
    global _JWKS_CACHE, _JWKS_FETCHED_AT
    if not SUPABASE_JWKS_URL:
        raise HTTPException(401, "Supabase project not configured on backend")

    now = time.time()
    if not _JWKS_CACHE or (now - _JWKS_FETCHED_AT) > _JWKS_TTL:
        print(f"DEBUG: Fetching JWKS from {SUPABASE_JWKS_URL}")
        try:
            resp = requests.get(SUPABASE_JWKS_URL, timeout=10)
            resp.raise_for_status()
            _JWKS_CACHE = resp.json()
            _JWKS_FETCHED_AT = now
        except Exception as e:
            print("DEBUG: Failed to fetch JWKS:", e)
            raise HTTPException(401, f"JWKS fetch failed: {e}")
    return _JWKS_CACHE

def _verify_supabase_token(token: str) -> Dict[str, Any]:
    """Verify RS256 JWT issued by Supabase."""
    try:
        jwks = _load_jwks()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        rsa_key = next(
            (
                {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key.get("use"),
                    "n": key["n"],
                    "e": key["e"],
                }
                for key in jwks.get("keys", [])
                if key.get("kid") == kid
            ),
            None,
        )

        if not rsa_key:
            print("DEBUG: No matching key in JWKS for kid:", kid)
            raise HTTPException(401, "Unknown signing key")

        public_key = jwk.construct(rsa_key)
        message, encoded_sig = token.rsplit(".", 1)
        decoded_sig = base64url_decode(encoded_sig.encode("utf-8"))
        if not public_key.verify(message.encode("utf-8"), decoded_sig):
            print("DEBUG: Signature verification failed.")
            raise HTTPException(401, "Invalid token signature")

        claims = jwt.get_unverified_claims(token)

        # Expiry
        if "exp" in claims and time.time() > float(claims["exp"]):
            print("DEBUG: Token expired.")
            raise HTTPException(401, "Token expired")

        # Issuer
        if SUPABASE_ISSUER and claims.get("iss") != SUPABASE_ISSUER:
            print("DEBUG: Invalid issuer:", claims.get("iss"))
            raise HTTPException(401, "Invalid issuer")

        # Audience
        aud = claims.get("aud")
        if isinstance(aud, list):
            if SUPABASE_AUDIENCE not in aud:
                print("DEBUG: Invalid audience list:", aud)
                raise HTTPException(401, "Invalid audience")
        elif aud != SUPABASE_AUDIENCE:
            print("DEBUG: Invalid audience string:", aud)
            raise HTTPException(401, "Invalid audience")

        print("DEBUG: Supabase token verified OK for sub:", claims.get("sub"))
        return claims

    except Exception as e:
        print("DEBUG: Exception verifying Supabase token:", e)
        raise

# -----------------------------
# Authentication dependencies
# -----------------------------
def _cred_exc():
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

def _try_local(token: str) -> Optional[User]:
    try:
        payload = decode_local_token(token)
        uid = payload.get("sub")
        email = payload.get("email")
        if uid and email:
            users = _read_json(USERS_FILE, [])
            for u in users:
                if u.get("id") == uid and u.get("email") == email:
                    return User(id=uid, email=email)
    except Exception:
        return None
    return None

def _try_supabase(token: str) -> Optional[User]:
    try:
        claims = _verify_supabase_token(token)
        uid = claims.get("sub")
        email = claims.get("email") or claims.get("user_metadata", {}).get("email")
        if uid and email:
            return User(id=uid, email=email)
    except Exception as e:
        print("DEBUG: _try_supabase error:", e)
        return None
    return None

def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> User:
    print("DEBUG: Incoming token:", token[:40] if token else None)
    if not token:
        raise _cred_exc()
    user = None
    try:
        user = _try_supabase(token)
    except Exception as e:
        print("DEBUG: Supabase check failed, falling back to local:", e)
    if not user:
        user = _try_local(token)
    if not user:
        print("DEBUG: Token failed validation in both paths.")
        raise _cred_exc()
    print("DEBUG: Authenticated user:", user.email)
    return user

def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[User]:
    if not token:
        return None
    return _try_supabase(token) or _try_local(token)

# -----------------------------
# Local testing routes
# -----------------------------
@router.post("/register")
def register(email: EmailStr = Form(...), password: str = Form(...)):
    users = _read_json(USERS_FILE, [])
    if any(u.get("email") == email for u in users):
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = pbkdf2_sha256.hash(password)
    user_id = str(uuid.uuid4())
    users.append({"id": user_id, "email": email, "hashed_password": hashed})
    _write_json(USERS_FILE, users)
    return {"msg": "User registered successfully"}

@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends()):
    users = _read_json(USERS_FILE, [])
    for u in users:
        if u.get("email") == form.username and pbkdf2_sha256.verify(form.password, u.get("hashed_password", "")):
            token = create_local_access_token({"sub": u["id"], "email": u["email"]})
            return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@router.get("/me", response_model=User)
def me(current: User = Depends(get_current_user)):
    return current