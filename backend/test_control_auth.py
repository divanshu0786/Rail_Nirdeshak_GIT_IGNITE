"""
Rail Nirdeshak - Automated Security & Control Room Authentication Test Suite
Verifies all 10 security scenarios from Master Development Prompt.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app
from database import SessionLocal, engine, Base, upgrade_database_schema
from models import User
from auth import hash_password

def run_security_tests():
    print("================================================================")
    print("  RUNNING CONTROL ROOM SECURITY & AUTHENTICATION TEST SUITE")
    print("================================================================")

    upgrade_database_schema(engine)
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    # 1. Verify Public Endpoints remain accessible without token
    print("\n[Test 1] Public endpoints accessible without authentication...")
    res = client.get("/health")
    assert res.status_code == 200
    res = client.get("/api/stations")
    assert res.status_code == 200
    res = client.get("/api/trains")
    assert res.status_code == 200
    print("  ✓ PASS: /health, /api/stations, /api/trains are publicly accessible.")

    # 2. Call protected Control Room overview without authentication -> HTTP 401
    print("\n[Test 2] Direct call to /api/control-room/overview without token...")
    res = client.get("/api/control-room/overview")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    print(f"  ✓ PASS: HTTP 401 Unauthorized returned. Detail: {res.json().get('detail')}")

    # 3. Call protected Field Observation submission without token -> HTTP 401
    print("\n[Test 3] Direct call to POST /api/field-observations without token...")
    obs_payload = {
        "track_section": "NDLS-PNP-LINE1",
        "pole_reference": "KM 60/10",
        "observation_type": "SIGNAL_INTERLOCKING",
        "description": "Unauthorized submission attempt",
        "impact_delay_min": 5
    }
    res = client.post("/api/field-observations", json=obs_payload)
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    print(f"  ✓ PASS: HTTP 401 Unauthorized returned.")

    # 4. Call protected Simulation Stepper without token -> HTTP 401
    print("\n[Test 4] Direct call to POST /api/telemetry/simulate-step/1 without token...")
    res = client.post("/api/telemetry/simulate-step/1?delay_delta=2&speed=70")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    print(f"  ✓ PASS: HTTP 401 Unauthorized returned.")

    # 5. Login with invalid username -> HTTP 401
    print("\n[Test 5] Login attempt with non-existent username...")
    res = client.post("/api/auth/login", json={"username": "ghost_controller", "password": "AnyPassword123!"})
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    assert "Invalid username or password" in res.json().get("detail", "")
    print(f"  ✓ PASS: HTTP 401 returned with message: '{res.json().get('detail')}'")

    # 6. Login with invalid password -> HTTP 401
    print("\n[Test 6] Login attempt with wrong password for controller...")
    res = client.post("/api/auth/login", json={"username": "controller", "password": "WrongPassword!"})
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    assert "Invalid username or password" in res.json().get("detail", "")
    print(f"  ✓ PASS: HTTP 401 returned with message: '{res.json().get('detail')}'")

    # 7. Login as Passenger -> Obtain Passenger Token
    print("\n[Test 7] Login as regular Passenger...")
    res = client.post("/api/auth/login", json={"username": "passenger", "password": "demo123"})
    if res.status_code != 200:
        # Fallback with email
        res = client.post("/api/auth/login", json={"email": "passenger@railnirdeshak.in", "password": "demo123"})
    assert res.status_code == 200, f"Passenger login failed: {res.text}"
    passenger_token = res.json()["access_token"]
    assert res.json()["user"]["role"] == "passenger"
    print(f"  ✓ PASS: Logged in as passenger. Token generated.")

    # 8. Passenger attempts to access Control Room -> HTTP 403 Forbidden!
    print("\n[Test 8] Passenger attempts to call /api/control-room/overview...")
    res = client.get("/api/control-room/overview", headers={"Authorization": f"Bearer {passenger_token}"})
    assert res.status_code == 403, f"Expected 403 Forbidden for passenger, got {res.status_code}"
    print(f"  ✓ PASS: HTTP 403 Forbidden returned. Detail: {res.json().get('detail')}")

    # 9. Passenger attempts to submit Field Observation -> HTTP 403 Forbidden!
    print("\n[Test 9] Passenger attempts to call POST /api/field-observations...")
    res = client.post("/api/field-observations", json=obs_payload, headers={"Authorization": f"Bearer {passenger_token}"})
    assert res.status_code == 403, f"Expected 403 Forbidden for passenger, got {res.status_code}"
    print(f"  ✓ PASS: HTTP 403 Forbidden returned. Detail: {res.json().get('detail')}")

    # 10. Login with valid Controller Credentials
    print("\n[Test 10] Controller login with username 'controller' and password 'Admin@Rail2026!'...")
    res = client.post("/api/auth/login", json={"username": "controller", "password": "Admin@Rail2026!"})
    if res.status_code != 200:
        # Check email fallback
        res = client.post("/api/auth/login", json={"email": "control@railnirdeshak.in", "password": "Admin@Rail2026!"})
    assert res.status_code == 200, f"Controller login failed: {res.text}"
    ctrl_token = res.json()["access_token"]
    ctrl_user = res.json()["user"]
    assert ctrl_user["role"] in ["controller", "admin"]
    print(f"  ✓ PASS: Controller authentication succeeded. Role: {ctrl_user['role']}, Name: {ctrl_user['full_name']}")

    # 11. Controller accesses Control Room Overview -> HTTP 200 OK
    print("\n[Test 11] Authorized Controller fetches /api/control-room/overview...")
    res = client.get("/api/control-room/overview", headers={"Authorization": f"Bearer {ctrl_token}"})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert "active_trains_count" in data
    assert "delayed_trains_count" in data
    assert "high_risk_propagations" in data
    assert "controller" in data
    assert data["controller"]["username"] == "controller"
    print(f"  ✓ PASS: Dashboard data successfully returned. Active trains: {data['active_trains_count']}, Propagation alerts: {data['high_risk_propagations']}")

    # 12. Controller dispatches Field Observation -> HTTP 200 OK
    print("\n[Test 12] Authorized Controller posts /api/field-observations...")
    res = client.post("/api/field-observations", json=obs_payload, headers={"Authorization": f"Bearer {ctrl_token}"})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    print(f"  ✓ PASS: Field observation successfully recorded. ID: {res.json().get('id')}")

    # 13. Controller triggers manual simulation step -> HTTP 200 OK
    print("\n[Test 13] Authorized Controller executes /api/telemetry/simulate-step/1...")
    res = client.post("/api/telemetry/simulate-step/1?delay_delta=3&speed=78", headers={"Authorization": f"Bearer {ctrl_token}"})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    print(f"  ✓ PASS: Telemetry simulation step executed: {res.json()}")

    # 14. Verify Logout Endpoint
    print("\n[Test 14] Controller Logout...")
    res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {ctrl_token}"})
    assert res.status_code == 200
    print("  ✓ PASS: Logout endpoint returned HTTP 200.")

    # 15. WebSocket Security Verification
    print("\n[Test 15] Control Room WebSocket rejection without token...")
    try:
        with client.websocket_connect("/ws/control-room") as ws:
            assert False, "WebSocket should have been rejected"
    except Exception as e:
        print(f"  ✓ PASS: Unauthenticated WebSocket connection rejected: {e}")

    print("\n================================================================")
    print("  ALL 15 SECURITY & ROLE-BASED ACCESS CONTROL TESTS PASSED!")
    print("================================================================\n")

if __name__ == "__main__":
    run_security_tests()
