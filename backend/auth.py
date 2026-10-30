import os
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import jwt
import hashlib
import bcrypt
from fastapi import Depends, HTTPException, status, Header, Query
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from database import get_db
from models import User

SECRET_KEY = os.getenv("SECRET_KEY", "rail-nirdeshak-super-secret-key-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720")) # 12 hours

security = HTTPBearer(auto_error=False)

# ----------------- LOGIN RATE LIMITING -----------------
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 300 # 5 minutes
_failed_attempts: Dict[str, List[float]] = {}

def record_failed_attempt(identifier: str) -> None:
    now = time.time()
    key = identifier.strip().lower()
    if key not in _failed_attempts:
        _failed_attempts[key] = []
    _failed_attempts[key] = [t for t in _failed_attempts[key] if now - t < LOCKOUT_WINDOW_SECONDS]
    _failed_attempts[key].append(now)

def is_rate_limited(identifier: str) -> Tuple[bool, int]:
    now = time.time()
    key = identifier.strip().lower()
    if key not in _failed_attempts:
        return False, 0
    recent = [t for t in _failed_attempts[key] if now - t < LOCKOUT_WINDOW_SECONDS]
    _failed_attempts[key] = recent
    if len(recent) >= MAX_FAILED_ATTEMPTS:
        oldest = recent[0]
        remaining = int(LOCKOUT_WINDOW_SECONDS - (now - oldest))
        return True, max(1, remaining)
    return False, 0

def clear_failed_attempts(identifier: str) -> None:
    key = identifier.strip().lower()
    _failed_attempts.pop(key, None)

# ----------------- PASSWORD HASHING (BCRYPT + LEGACY FALLBACK) -----------------
def hash_password(password: str) -> str:
    """Hash password securely using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash, with backward-compatible SHA-256 fallback."""
    if not hashed_password or not plain_password:
        return False
    
    # Check if bcrypt hash format ($2a$, $2b$, or $2y$)
    if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        except Exception:
            return False

    # Backward compatibility: legacy SHA-256 verification
    try:
        legacy_hash = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
        return legacy_hash == hashed_password
    except Exception:
        return False

# ----------------- JWT TOKEN UTILITIES -----------------
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None

# ----------------- AUTHENTICATION DEPENDENCIES -----------------
def get_current_user(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Extract user from Authorization Bearer header or ?token= query parameter."""
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "").strip()
    elif token:
        raw_token = token.strip()

    if not raw_token:
        return None

    payload = decode_access_token(raw_token)
    if not payload:
        return None

    sub = payload.get("sub")
    if not sub:
        return None

    try:
        user = db.query(User).filter(User.id == int(sub)).first()
        if user and not user.is_active:
            return None
        return user
    except Exception:
        return None

def require_current_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """Require an authenticated and active user (passenger, controller, or admin)."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated. Please contact an administrator.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def require_controller_user(user: User = Depends(require_current_user)) -> User:
    """Require an authenticated user with Controller or Admin role."""
    user_role = (user.role or "").strip().lower()
    if user_role not in ["controller", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Controller or Admin privileges required.",
        )
    return user

def verify_ws_token(token: Optional[str], db: Session, required_roles: Optional[List[str]] = None) -> Optional[User]:
    """Validate a WebSocket connection token and role."""
    if not token:
        return None
    payload = decode_access_token(token.strip())
    if not payload or not payload.get("sub"):
        return None
    try:
        user = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not user or not user.is_active:
            return None
        if required_roles:
            role = (user.role or "").strip().lower()
            if role not in [r.lower() for r in required_roles]:
                return None
        return user
    except Exception:
        return None
