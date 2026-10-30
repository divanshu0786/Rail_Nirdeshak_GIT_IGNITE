"""
Rail Nirdeshak - Control Room Security & Role-Based Access Control Verification Suite
Direct verification of all 10 security requirements from the Master Development Prompt.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from fastapi import HTTPException
from database import SessionLocal, engine, Base, upgrade_database_schema
import models
import schemas
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_controller_user,
    require_admin_user,
    verify_ws_token,
    record_failed_attempt,
    is_rate_limited,
    clear_failed_attempts,
    SECRET_KEY,
    ALGORITHM
)
from main import (
    login,
    get_control_room_overview,
    create_field_observation,
    logout
)

def run_tests():
    print("=" * 70)
    print("  RAIL NIRDESHAK - CONTROL ROOM AUTHENTICATION TEST SUITE")
    print("=" * 70)

    upgrade_database_schema(engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # -------------------------------------------------------------
        # Test 1: Verify Password Hashing with Bcrypt
        # -------------------------------------------------------------
        print("\n[Test 1] Secure Password Hashing & Verification...")
        plain = "Admin@Rail2026!"
        hashed = hash_password(plain)
        assert hashed.startswith(("$2a$", "$2b$", "$2y$")), "Hash must use Bcrypt prefix"
        assert verify_password(plain, hashed) is True, "Password verification must succeed"
        assert verify_password("WrongPassword!", hashed) is False, "Wrong password must be rejected"
        print("  ✓ PASS: Bcrypt hashing and verification working securely.")

        # -------------------------------------------------------------
        # Test 2: Unauthenticated Access to Controller Resources (HTTP 401)
        # -------------------------------------------------------------
        print("\n[Test 2] Unauthenticated access to require_controller_user()...")
        try:
            require_controller_user(None)
            assert False, "Should have raised 401"
        except HTTPException as e:
            assert e.status_code == 401, f"Expected 401, got {e.status_code}"
            print(f"  ✓ PASS: Correctly raised HTTP 401 Unauthorized: {e.detail}")

        # -------------------------------------------------------------
        # Test 3: Login Attempt with Non-Existent Username (HTTP 401)
        # -------------------------------------------------------------
        print("\n[Test 3] Login attempt with non-existent username...")
        try:
            login(schemas.UserLogin(username="ghost_user_999", password="Password123!"), db)
            assert False, "Should have raised 401"
        except HTTPException as e:
            assert e.status_code == 401
            assert "Invalid username or password" in e.detail
            print(f"  ✓ PASS: HTTP 401 returned: '{e.detail}'")

        # -------------------------------------------------------------
        # Test 4: Login Attempt with Incorrect Password (HTTP 401)
        # -------------------------------------------------------------
        print("\n[Test 4] Login attempt with incorrect password for controller...")
        try:
            login(schemas.UserLogin(username="controller", password="WrongPassword!"), db)
            assert False, "Should have raised 401"
        except HTTPException as e:
            assert e.status_code == 401
            assert "Invalid username or password" in e.detail
            print(f"  ✓ PASS: HTTP 401 returned: '{e.detail}'")

        # -------------------------------------------------------------
        # Test 5: Brute-Force Rate Limiting (HTTP 429)
        # -------------------------------------------------------------
        print("\n[Test 5] Brute-force rate limiting protection...")
        test_ip = "brute_attacker_user"
        clear_failed_attempts(test_ip)
        for i in range(5):
            record_failed_attempt(test_ip)
        
        limited, wait = is_rate_limited(test_ip)
        assert limited is True, "User should be rate limited after 5 failures"
        print(f"  ✓ PASS: Rate limit triggered. Temporary lockout active for {wait}s.")
        clear_failed_attempts(test_ip)

        # -------------------------------------------------------------
        # Test 6: Passenger Authentication
        # -------------------------------------------------------------
        print("\n[Test 6] Passenger Login with valid credentials...")
        passenger_res = login(schemas.UserLogin(username="passenger", password="demo123"), db)
        assert passenger_res["user"].role == "passenger"
        psg_token = passenger_res["access_token"]
        print(f"  ✓ PASS: Passenger authenticated. Role: {passenger_res['user'].role}")

        # -------------------------------------------------------------
        # Test 7: Passenger attempts Controller Access (HTTP 403 Forbidden)
        # -------------------------------------------------------------
        print("\n[Test 7] Passenger attempts to access Control Room...")
        try:
            require_controller_user(passenger_res["user"])
            assert False, "Passenger should be forbidden"
        except HTTPException as e:
            assert e.status_code == 403, f"Expected 403, got {e.status_code}"
            assert "Controller or Admin" in e.detail
            print(f"  ✓ PASS: HTTP 403 Forbidden returned: '{e.detail}'")

        # -------------------------------------------------------------
        # Test 8: Controller Authentication
        # -------------------------------------------------------------
        print("\n[Test 8] Controller Login with valid credentials...")
        ctrl_res = login(schemas.UserLogin(username="controller", password="Admin@Rail2026!"), db)
        assert ctrl_res["user"].role == "controller"
        ctrl_token = ctrl_res["access_token"]
        ctrl_user = ctrl_res["user"]
        print(f"  ✓ PASS: Controller authenticated. Name: {ctrl_user.full_name}, Role: {ctrl_user.role}")

        # -------------------------------------------------------------
        # Test 9: Controller access to require_controller_user()
        # -------------------------------------------------------------
        print("\n[Test 9] Controller authorization check...")
        authorized = require_controller_user(ctrl_user)
        assert authorized.id == ctrl_user.id
        print(f"  ✓ PASS: Controller successfully authorized.")

        # -------------------------------------------------------------
        # Test 10: Authorized Controller Access to Overview API
        # -------------------------------------------------------------
        print("\n[Test 10] Controller fetches Control Room Overview...")
        overview = get_control_room_overview(user=ctrl_user, db=db)
        assert "active_trains_count" in overview
        assert "delayed_trains_count" in overview
        assert "high_risk_propagations" in overview
        assert "trains" in overview
        print(f"  ✓ PASS: Overview returned {overview['active_trains_count']} active trains, {overview['high_risk_propagations']} propagation risks.")

        # -------------------------------------------------------------
        # Test 11: Authorized Controller Submits Field Observation
        # -------------------------------------------------------------
        print("\n[Test 11] Controller dispatches field observation...")
        obs_payload = schemas.FieldObservationCreate(
            track_section="NDLS-PNP-LINE1",
            pole_reference="KM 52/10",
            observation_type="SIGNAL_INTERLOCKING",
            impact_delay_min=8,
            description="Interlocking test and inspection by controller."
        )
        obs_result = create_field_observation(obs_in=obs_payload, user=ctrl_user, db=db)
        assert obs_result.track_section == "NDLS-PNP-LINE1"
        assert obs_result.impact_delay_min == 8
        print(f"  ✓ PASS: Observation successfully created with ID {obs_result.id}.")

        # -------------------------------------------------------------
        # Test 12: WebSocket Security - Unauthenticated Rejection
        # -------------------------------------------------------------
        print("\n[Test 12] WebSocket security: Unauthenticated connection...")
        ws_user_none = verify_ws_token(None, db, required_roles=["controller", "admin"])
        assert ws_user_none is None, "WebSocket should reject None token"
        print("  ✓ PASS: None token rejected with WS_1008 policy violation.")

        # -------------------------------------------------------------
        # Test 13: WebSocket Security - Passenger Token Rejection
        # -------------------------------------------------------------
        print("\n[Test 13] WebSocket security: Passenger token rejection...")
        ws_user_psg = verify_ws_token(psg_token, db, required_roles=["controller", "admin"])
        assert ws_user_psg is None, "WebSocket should reject passenger role"
        print("  ✓ PASS: Passenger token rejected from Control Room WebSocket.")

        # -------------------------------------------------------------
        # Test 14: WebSocket Security - Controller Token Acceptance
        # -------------------------------------------------------------
        print("\n[Test 14] WebSocket security: Controller token verification...")
        ws_user_ctrl = verify_ws_token(ctrl_token, db, required_roles=["controller", "admin"])
        assert ws_user_ctrl is not None, "WebSocket must accept valid controller token"
        assert ws_user_ctrl.role == "controller"
        print(f"  ✓ PASS: Controller WebSocket verified for user '{ws_user_ctrl.username}'.")

        # -------------------------------------------------------------
        # Test 15: Session Logout
        # -------------------------------------------------------------
        print("\n[Test 15] Controller Logout...")
        logout_res = logout(user=ctrl_user)
        assert logout_res["status"] == "success"
        print("  ✓ PASS: Logout successfully executed.")

        print("\n" + "=" * 70)
        print("  ALL 15 CONTROL ROOM SECURITY & RBAC TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)

    finally:
        db.close()

if __name__ == "__main__":
    run_tests()
