"""
Rail Nirdeshak - Firebase Phone Number Authentication (SMS OTP) Test Suite
Verifies:
1. Phone Number Normalization & Masking
2. /api/auth/request-phone-verification (Railway ID clearance, role check, rate limiting)
3. Passenger Railway ID Denial (HTTP 403)
4. Anti-replay and Challenge Consumption
5. /api/auth/verify-firebase-session (Token verification, phone matching, UID binding)
6. HttpOnly Application Session Cookie & Token Generation
7. WebSocket protection with Token & Cookie
8. Logout & Cookie Invalidation
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import Headers
from database import SessionLocal, engine, Base, upgrade_database_schema
import models
import schemas
import firebase_service
from auth import (
    get_current_user,
    require_controller_user,
    verify_ws_token,
    create_access_token,
    set_session_cookie,
    clear_session_cookie
)
from main import (
    request_phone_verification,
    verify_firebase_session,
    logout,
    get_app_config,
    get_control_room_overview
)

def create_mock_request(client_ip="127.0.0.1", cookies=None, auth_header=None):
    scope = {
        "type": "http",
        "client": (client_ip, 50000),
        "headers": []
    }
    raw_headers = []
    if auth_header:
        raw_headers.append((b"authorization", auth_header.encode("latin-1")))
    if cookies:
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        raw_headers.append((b"cookie", cookie_str.encode("latin-1")))
    scope["headers"] = raw_headers
    return Request(scope)

def run_firebase_auth_tests():
    print("=" * 75)
    print("  RAIL NIRDESHAK - FIREBASE PHONE OTP INTEGRATION TEST SUITE")
    print("=" * 75)

    upgrade_database_schema(engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # -------------------------------------------------------------
        # Test 1: Phone Normalization and Masking Utilities
        # -------------------------------------------------------------
        print("\n[Test 1] Phone Normalization & Privacy Masking...")
        assert firebase_service.normalize_phone_number("9876543210") == "+919876543210"
        assert firebase_service.normalize_phone_number("+919876543210") == "+919876543210"
        assert firebase_service.normalize_phone_number("09876543210") == "+919876543210"
        
        masked = firebase_service.mask_phone_number("+919876543210")
        assert masked.endswith("3210"), f"Expected mask to end with 3210, got {masked}"
        assert "•••••" in masked or "•" in masked, f"Expected masked digits, got {masked}"
        assert masked.startswith("+91"), f"Expected country code +91, got {masked}"
        print(f"  ✓ PASS: Normalization ('9876543210' -> '+919876543210') and Masking ('{masked}') valid.")

        # -------------------------------------------------------------
        # Test 2: Request Phone Verification for Authorized Controller
        # -------------------------------------------------------------
        print("\n[Test 2] Request Phone Verification for 12-Digit Controller Railway ID...")
        req = create_mock_request("192.168.1.101")
        payload = schemas.PhoneVerificationRequest(railway_id="123456789012")
        res = request_phone_verification(payload, req, db)
        assert res.session_id is not None
        assert res.railway_id == "123456789012"
        assert res.phone_number == "+917357722601"
        assert res.role == "controller"
        assert res.masked_phone.endswith("2601")
        controller_session_id = res.session_id
        print(f"  ✓ PASS: Controller clearance verified. Session challenge generated: {controller_session_id[:8]}...")

        # -------------------------------------------------------------
        # Test 3: Request Phone Verification for Authorized DRM Admin
        # -------------------------------------------------------------
        print("\n[Test 3] Request Phone Verification for DRM Admin...")
        payload_admin = schemas.PhoneVerificationRequest(railway_id="987654321098")
        res_admin = request_phone_verification(payload_admin, req, db)
        assert res_admin.role == "admin"
        assert res_admin.phone_number == "+919876543211"
        print(f"  ✓ PASS: DRM Admin clearance verified. Role: {res_admin.role}, Phone: {res_admin.masked_phone}")

        # -------------------------------------------------------------
        # Test 4: Passenger Railway ID Rejection (HTTP 403 Forbidden)
        # -------------------------------------------------------------
        print("\n[Test 4] Passenger Railway ID Access Denied (Strict Role Enforcement)...")
        payload_psg = schemas.PhoneVerificationRequest(railway_id="111122223333")
        try:
            request_phone_verification(payload_psg, req, db)
            assert False, "Should have rejected passenger role"
        except HTTPException as e:
            assert e.status_code == 403, f"Expected 403 Forbidden, got {e.status_code}"
            assert "Passenger" in e.detail or "restricted" in e.detail
            print(f"  ✓ PASS: HTTP 403 Forbidden returned: '{e.detail}'")

        # -------------------------------------------------------------
        # Test 5: Unknown Railway ID Rejection (HTTP 404 Not Found)
        # -------------------------------------------------------------
        print("\n[Test 5] Non-Existent Railway ID Rejection...")
        payload_unknown = schemas.PhoneVerificationRequest(railway_id="000000000000")
        try:
            request_phone_verification(payload_unknown, req, db)
            assert False, "Should have rejected unknown ID"
        except HTTPException as e:
            assert e.status_code == 404
            assert "not found" in e.detail.lower()
            print(f"  ✓ PASS: HTTP 404 Not Found returned: '{e.detail}'")

        # -------------------------------------------------------------
        # Test 6: Rate Limiting on SMS Requests (HTTP 429)
        # -------------------------------------------------------------
        print("\n[Test 6] SMS Request Rate Limiting Protection...")
        test_client_ip = "192.168.1.99"
        for _ in range(5):
            firebase_service.record_phone_request_attempt(test_client_ip)
        limited, wait = firebase_service.is_phone_request_rate_limited(test_client_ip)
        assert limited is True
        print(f"  ✓ PASS: Rate limit triggered. Lockout period active: {wait}s remaining.")

        # -------------------------------------------------------------
        # Test 7: Challenge Anti-Replay Protection
        # -------------------------------------------------------------
        print("\n[Test 7] Single-Use Challenge Verification & Anti-Replay...")
        challenge_data = firebase_service.consume_phone_verification_session(controller_session_id, "123456789012")
        assert challenge_data is not None
        assert challenge_data["railway_id"] == "123456789012"
        
        # Second consumption must return None (single-use guarantee)
        replay_attempt = firebase_service.consume_phone_verification_session(controller_session_id, "123456789012")
        assert replay_attempt is None, "Session challenge must NOT be reusable!"
        print("  ✓ PASS: Challenge consumed once; replay attempt blocked.")

        # -------------------------------------------------------------
        # Test 8: Verify Firebase Session with Valid Token & Phone Match
        # -------------------------------------------------------------
        print("\n[Test 8] Verify Firebase Session with Valid Token & Phone Match...")
        # Create fresh challenge for verification
        fresh_challenge = request_phone_verification(payload, req, db)
        mock_fb_claims = {
            "uid": "fb_uid_test_controller_123",
            "phone_number": "+917357722601",
            "firebase": {"sign_in_provider": "phone"}
        }

        with patch("main.verify_firebase_id_token", return_value=mock_fb_claims):
            verify_payload = schemas.FirebaseSessionVerifyRequest(
                id_token="mock_valid_firebase_id_token_xyz",
                session_id=fresh_challenge.session_id,
                railway_id="123456789012"
            )
            mock_http_res = MagicMock()
            session_out = verify_firebase_session(verify_payload, mock_http_res, db)
            
            token_val = session_out["access_token"] if isinstance(session_out, dict) else session_out.access_token
            user_obj = session_out["user"] if isinstance(session_out, dict) else session_out.user
            assert token_val is not None
            assert user_obj.role == "controller"
            assert user_obj.phone_number == "+917357722601"
            assert mock_http_res.set_cookie.called, "HttpOnly session cookie must be set on response"
            print(f"  ✓ PASS: Firebase session verified. JWT token created, HttpOnly cookie dispatched.")

        # -------------------------------------------------------------
        # Test 9: Reject Firebase Session with Phone Number Mismatch
        # -------------------------------------------------------------
        print("\n[Test 9] Reject Firebase Session with Phone Mismatch (Spoof Protection)...")
        spoof_challenge = request_phone_verification(payload, req, db)
        mock_spoofed_claims = {
            "uid": "attacker_firebase_uid",
            "phone_number": "+919999999999",  # Attacker's phone, not officer's registered +919876543210
            "firebase": {"sign_in_provider": "phone"}
        }

        with patch("main.verify_firebase_id_token", return_value=mock_spoofed_claims):
            spoof_payload = schemas.FirebaseSessionVerifyRequest(
                id_token="spoofed_token_abc",
                session_id=spoof_challenge.session_id,
                railway_id="123456789012"
            )
            try:
                verify_firebase_session(spoof_payload, MagicMock(), db)
                assert False, "Should reject phone mismatch"
            except HTTPException as e:
                assert e.status_code == 403
                assert "not match" in e.detail.lower() or "mismatch" in e.detail.lower()
                print(f"  ✓ PASS: HTTP 403 returned on phone mismatch: '{e.detail}'")

        # -------------------------------------------------------------
        # Test 10: Reject Invalid / Expired Firebase Token
        # -------------------------------------------------------------
        print("\n[Test 10] Reject Invalid / Expired Firebase Token...")
        expired_challenge = request_phone_verification(payload, req, db)
        with patch("main.verify_firebase_id_token", side_effect=HTTPException(status_code=401, detail="Firebase ID token has expired")):
            bad_token_payload = schemas.FirebaseSessionVerifyRequest(
                id_token="expired_token",
                session_id=expired_challenge.session_id,
                railway_id="123456789012"
            )
            try:
                verify_firebase_session(bad_token_payload, MagicMock(), db)
                assert False, "Should reject expired token"
            except HTTPException as e:
                assert e.status_code == 401
                print(f"  ✓ PASS: HTTP 401 returned on invalid token: '{e.detail}'")

        # -------------------------------------------------------------
        # Test 11: HttpOnly Cookie Authentication on Protected Endpoints
        # -------------------------------------------------------------
        print("\n[Test 11] Cookie-Based Authentication for Control Room Resources...")
        # Get controller user record from DB
        ctrl_user = db.query(models.User).filter(models.User.username == "controller").first()
        valid_jwt = create_access_token({"sub": str(ctrl_user.id), "username": ctrl_user.username, "role": ctrl_user.role})

        # Request with rn_session cookie but NO Authorization header
        cookie_req = create_mock_request("127.0.0.1", cookies={"rn_session": valid_jwt})
        user_from_cookie = get_current_user(request=cookie_req, db=db)
        assert user_from_cookie.id == ctrl_user.id
        assert user_from_cookie.role == "controller"
        print(f"  ✓ PASS: Authenticated via rn_session cookie alone (User: {user_from_cookie.username}).")

        # Protected Overview API with cookie-authenticated controller
        overview = get_control_room_overview(user=user_from_cookie, db=db)
        assert "active_trains_count" in overview
        print(f"  ✓ PASS: Control room overview successfully fetched via cookie session.")

        # -------------------------------------------------------------
        # Test 12: WebSocket Authentication via Cookie
        # -------------------------------------------------------------
        print("\n[Test 12] WebSocket Authentication via Session Token / Cookie...")
        ws_user = verify_ws_token(valid_jwt, db, required_roles=["controller", "admin"])
        assert ws_user is not None
        assert ws_user.role == "controller"
        print(f"  ✓ PASS: WebSocket connection authorized for controller role.")

        # -------------------------------------------------------------
        # Test 13: Public Configuration Endpoint
        # -------------------------------------------------------------
        print("\n[Test 13] Public Configuration Endpoint (/api/config)...")
        cfg = get_app_config()
        assert "firebase" in cfg
        assert "projectId" in cfg["firebase"]
        assert cfg["firebase"]["projectId"] == "rail-nirdeshak"
        assert "apiKey" in cfg["firebase"]
        print(f"  ✓ PASS: /api/config correctly returns public Firebase client configuration.")

        # -------------------------------------------------------------
        # Test 14: Logout & Cookie Invalidation
        # -------------------------------------------------------------
        print("\n[Test 14] Session Logout & Cookie Clearing...")
        mock_logout_res = MagicMock()
        logout_data = logout(mock_logout_res, user=ctrl_user)
        assert logout_data["status"] == "success"
        assert mock_logout_res.delete_cookie.called or mock_logout_res.set_cookie.called
        print(f"  ✓ PASS: Logout successfully executed and cookie invalidation dispatched.")

        print("\n" + "=" * 75)
        print("  ALL 14 FIREBASE PHONE OTP AUTHENTICATION TESTS PASSED SUCCESSFULLY!")
        print("=" * 75)

    finally:
        db.close()

if __name__ == "__main__":
    run_firebase_auth_tests()
