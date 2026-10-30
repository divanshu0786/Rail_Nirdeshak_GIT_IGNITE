"""
Rail Nirdeshak - Firebase Authentication & Token Verification Service
Handles:
1. Firebase Admin SDK initialization with service account credentials or project configuration.
2. Cryptographic Firebase ID Token verification.
3. Phone number normalization and privacy masking.
4. Cryptographic one-time session challenge generation & consumption for 2FA OTP flow.
"""

import os
import sys
import time
import re
import json
import secrets
from typing import Optional, Dict, Tuple, Any, List
from datetime import datetime, timedelta

import firebase_admin
from firebase_admin import credentials, auth, exceptions

# Global initialization state
_firebase_initialized = False
_firebase_init_error = None

def init_firebase_admin() -> bool:
    """
    Initialize Firebase Admin SDK using one of the following methods (in priority order):
    1. FIREBASE_SERVICE_ACCOUNT_KEY: Path to serviceAccountKey.json file
    2. FIREBASE_SERVICE_ACCOUNT_JSON: Raw JSON string of the service account
    3. GOOGLE_APPLICATION_CREDENTIALS: Standard Google Cloud environment variable
    4. Project ID default initialization
    """
    global _firebase_initialized, _firebase_init_error

    if _firebase_initialized and len(firebase_admin._apps) > 0:
        return True

    # Check if already initialized by another module
    if len(firebase_admin._apps) > 0:
        _firebase_initialized = True
        return True

    key_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY")
    key_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    project_id = os.getenv("FIREBASE_PROJECT_ID", "rail-nirdeshak")

    try:
        if key_path and os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred, {"projectId": project_id})
            _firebase_initialized = True
            print(f"[Firebase Admin] Initialized with service account file: {key_path}")
            return True

        elif key_json:
            try:
                cert_dict = json.loads(key_json)
                cred = credentials.Certificate(cert_dict)
                firebase_admin.initialize_app(cred, {"projectId": project_id})
                _firebase_initialized = True
                print("[Firebase Admin] Initialized with FIREBASE_SERVICE_ACCOUNT_JSON")
                return True
            except Exception as json_err:
                print(f"[Firebase Admin] Warning: Failed to parse FIREBASE_SERVICE_ACCOUNT_JSON: {json_err}", file=sys.stderr)

        elif google_creds and os.path.exists(google_creds):
            cred = credentials.Certificate(google_creds)
            firebase_admin.initialize_app(cred, {"projectId": project_id})
            _firebase_initialized = True
            print(f"[Firebase Admin] Initialized with GOOGLE_APPLICATION_CREDENTIALS: {google_creds}")
            return True

        else:
            # Initialize with project ID (can verify tokens if Google Cloud application default credentials exist)
            try:
                firebase_admin.initialize_app(options={"projectId": project_id})
                _firebase_initialized = True
                print(f"[Firebase Admin] Initialized with Project ID: {project_id}")
                return True
            except Exception as e:
                _firebase_init_error = str(e)
                print(f"[Firebase Admin] Initialized in development mode ({e})")
                return False

    except Exception as exc:
        _firebase_init_error = str(exc)
        print(f"[Firebase Admin] Initialization warning: {exc}", file=sys.stderr)
        return False

# Attempt initialization on module load
init_firebase_admin()


# ----------------- PHONE NUMBER HELPERS -----------------

def normalize_phone_number(phone: str, default_country_code: str = "+91") -> str:
    """
    Normalizes a phone number to standard E.164 format (+919876543210).
    """
    if not phone:
        return ""
    # Strip whitespace, dashes, parentheses
    cleaned = re.sub(r"[\s\-\(\)]", "", str(phone).strip())

    if cleaned.startswith("+"):
        return cleaned
    
    # If starts with 00, replace with +
    if cleaned.startswith("00"):
        return "+" + cleaned[2:]

    # If starts with 0 and 11 digits (e.g. 09876543210), strip 0 and add default country code
    if cleaned.startswith("0") and len(cleaned) == 11:
        return default_country_code + cleaned[1:]

    # 10 digits standard Indian mobile
    if len(cleaned) == 10:
        return default_country_code + cleaned

    return default_country_code + cleaned


def mask_phone_number(phone: str) -> str:
    """
    Returns a privacy-masked phone number, e.g. '+919876543210' -> '+91 ••••• •3210'.
    """
    if not phone:
        return ""
    norm = normalize_phone_number(phone)
    if len(norm) >= 10:
        country = norm[:-10] if len(norm) > 10 else "+91"
        national = norm[-10:]
        masked_national = f"••••• •{national[-4:]}"
        return f"{country} {masked_national}".strip()
    return norm[:3] + "••••" + norm[-2:] if len(norm) > 5 else "••••••"


# ----------------- SESSION CHALLENGE MANAGEMENT -----------------

CHALLENGE_TTL_SECONDS = 600  # 10 minutes

_active_challenges: Dict[str, Dict[str, Any]] = {}
_phone_request_rate_limits: Dict[str, List[float]] = {}
MAX_PHONE_REQUESTS_PER_WINDOW = 5
PHONE_WINDOW_SECONDS = 300  # 5 minutes


def is_phone_request_rate_limited(identifier: str) -> Tuple[bool, int]:
    """Rate limit SMS request attempts per Railway ID or IP."""
    now = time.time()
    key = str(identifier).strip()
    if key not in _phone_request_rate_limits:
        _phone_request_rate_limits[key] = []
    recent = [t for t in _phone_request_rate_limits[key] if now - t < PHONE_WINDOW_SECONDS]
    _phone_request_rate_limits[key] = recent
    if len(recent) >= MAX_PHONE_REQUESTS_PER_WINDOW:
        oldest = recent[0]
        remaining = int(PHONE_WINDOW_SECONDS - (now - oldest))
        return True, max(1, remaining)
    return False, 0


def record_phone_request_attempt(identifier: str) -> None:
    now = time.time()
    key = str(identifier).strip()
    if key not in _phone_request_rate_limits:
        _phone_request_rate_limits[key] = []
    _phone_request_rate_limits[key] = [t for t in _phone_request_rate_limits[key] if now - t < PHONE_WINDOW_SECONDS]
    _phone_request_rate_limits[key].append(now)


def create_phone_verification_session(railway_id: str, phone_number: str, officer_id: int) -> str:
    """
    Creates a secure, high-entropy single-use session challenge for phone verification.
    """
    now = time.time()
    # Clean up expired challenges
    expired_keys = [k for k, v in _active_challenges.items() if now > v.get("expires_at", 0)]
    for k in expired_keys:
        _active_challenges.pop(k, None)

    session_id = secrets.token_urlsafe(32)
    _active_challenges[session_id] = {
        "session_id": session_id,
        "railway_id": railway_id,
        "phone_number": normalize_phone_number(phone_number),
        "officer_id": officer_id,
        "created_at": now,
        "expires_at": now + CHALLENGE_TTL_SECONDS,
        "used": False
    }
    return session_id


def consume_phone_verification_session(session_id: str, railway_id: str) -> Optional[Dict[str, Any]]:
    """
    Validates and consumes a session challenge. Once consumed, it cannot be reused (anti-replay).
    """
    now = time.time()
    session = _active_challenges.get(session_id)
    if not session:
        return None

    if session.get("used"):
        return None  # Already consumed

    if now > session.get("expires_at", 0):
        _active_challenges.pop(session_id, None)
        return None  # Expired

    if session.get("railway_id") != railway_id:
        return None  # Railway ID mismatch

    # Mark as consumed immediately to prevent replay
    session["used"] = True
    _active_challenges.pop(session_id, None)
    return session


# ----------------- FIREBASE TOKEN VERIFICATION -----------------

def verify_firebase_id_token(id_token: str) -> Dict[str, Any]:
    """
    Verifies a Firebase ID token using the Firebase Admin SDK.
    Returns the decoded token claims dictionary containing:
      - uid: Firebase UID
      - phone_number: Verified phone number (E.164)
      - auth_time: Authentication timestamp
      - exp: Expiration timestamp
    Raises ValueError or auth.InvalidIdTokenError on verification failure.
    """
    if not id_token or not isinstance(id_token, str):
        raise ValueError("Invalid Firebase ID token provided.")

    init_firebase_admin()

    try:
        # Standard production verification via Firebase Admin SDK
        decoded_token = auth.verify_id_token(id_token.strip(), check_revoked=True)
        return decoded_token
    except auth.RevokedIdTokenError:
        raise ValueError("Firebase ID token has been revoked. Please request a new verification code.")
    except auth.ExpiredIdTokenError:
        raise ValueError("Firebase ID token has expired. Please verify again.")
    except auth.InvalidIdTokenError as e:
        # Check if in local development mode without service account credentials
        # Allow testing with valid decoded structure or test tokens
        dev_mode = os.getenv("FIREBASE_DEV_MODE", "false").lower() in ("true", "1", "yes")
        if dev_mode:
            import jwt
            try:
                # Unverified decode for development inspection only if explicitly enabled
                unverified = jwt.decode(id_token.strip(), options={"verify_signature": False})
                if unverified.get("phone_number"):
                    print("[Firebase Admin Dev Mode] Accepted token in development mode.")
                    return unverified
            except Exception:
                pass
        raise ValueError(f"Invalid Firebase ID token: {e}")
    except Exception as exc:
        raise ValueError(f"Firebase token verification failed: {exc}")
