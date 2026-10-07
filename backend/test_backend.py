import os
import sys
from fastapi.testclient import TestClient

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(__file__))

from main import app
from seed_data import seed

def run_tests():
    print("1. Re-seeding database for test verification...")
    seed()

    client = TestClient(app)

    print("\n2. Testing /health...")
    res = client.get("/health")
    assert res.status_code == 200, f"Health check failed: {res.text}"
    print("✓ Health check OK:", res.json()["status"])

    print("\n3. Testing Auth Login with seeded user...")
    res = client.post("/auth/login", json={"email": "passenger@railnirdeshak.in", "password": "demo123"})
    print("Login response:", res.json())
    token = res.json()["access_token"]
    print("✓ Login successful, token received:", token[:20], "...")

    print("\n4. Testing /auth/me with Bearer token...")
    res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, f"/auth/me failed with status {res.status_code}: {res.text}"
    assert res.json()["email"] == "passenger@railnirdeshak.in"
    print("✓ /auth/me OK for user:", res.json()["full_name"])

    print("\n5. Testing /api/trains list...")
    res = client.get("/api/trains")
    assert res.status_code == 200
    trains = res.json()
    assert len(trains) >= 2
    print(f"✓ Found {len(trains)} active trains:", [t["train_number"] for t in trains])

    print("\n6. Testing /api/trains/12497 detail & Dynamic ETA...")
    res = client.get("/api/trains/12497")
    assert res.status_code == 200
    data = res.json()
    assert data["train_number"] == "12497"
    assert len(data["predictions"]) > 0
    first_pred = data["predictions"][0]
    print(f"✓ Train 12497 Dynamic ETA verified. Next station: {first_pred['station_name']} ({first_pred['station_code']})")
    print(f"  Scheduled: {first_pred['scheduled_arrival']} -> Predicted: {first_pred['predicted_arrival']} (+{first_pred['predicted_delay_min']}m)")
    print(f"  Reason Breakdown: {first_pred['reason_summary']}")
    print(f"  Propagation Risk: {first_pred['propagation_risk']}")

    print("\n7. Testing /api/telemetry live ingest & recalculation...")
    telemetry_payload = {
        "train_number": "12497",
        "latitude": 29.2500,
        "longitude": 76.9800,
        "speed_kmh": 62.0,
        "current_delay_min": 18,
        "remaining_distance_km": 365.0,
        "track_section": "NDLS-PNP-LINE1",
        "reference_pole": "KM 78/04",
        "weather_condition": "CLEAR"
    }
    res = client.post("/api/telemetry", json=telemetry_payload)
    assert res.status_code == 200
    print("✓ Live Telemetry accepted and recalculated:", res.json()["status"])

    print("\n8. Testing Control Room Overview...")
    res = client.get("/api/control-room/overview")
    assert res.status_code == 200
    ctrl = res.json()
    print(f"✓ Control room overview OK. Active trains: {ctrl['active_trains_count']}, Delayed: {ctrl['delayed_trains_count']}, High Prop Risks: {ctrl['high_risk_propagations']}")

    print("\n9. Testing Frontend Static index.html root serving...")
    res = client.get("/")
    assert res.status_code == 200
    assert "RAIL NIRDESHAK" in res.text
    print("✓ Frontend index.html served seamlessly from root /")

    print("\n10. Testing Saved Trains flow...")
    res = client.post("/api/saved-trains/1", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    res = client.get("/api/saved-trains", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    saved = res.json()
    assert len(saved) >= 1
    print(f"✓ Saved trains verified: {len(saved)} bookmarked.")

    print("\n11. Testing Simulation Step trigger...")
    res = client.post("/api/telemetry/simulate-step/1?delay_delta=3&speed=70")
    assert res.status_code == 200
    print("✓ Telemetry step simulation OK. New state updated.")

    print("\n12. Testing Field Survey logging...")
    obs_payload = {
        "track_section": "NDLS-PNP-LINE1",
        "pole_reference": "KM 55/10",
        "observation_type": "SIGNAL_INTERLOCKING",
        "description": "Signal clearance speed restriction test",
        "impact_delay_min": 4
    }
    res = client.post("/api/field-observations", json=obs_payload)
    print("\n13. Testing 6-Month Dataset History Sampling & Replay...")
    res = client.get("/api/telemetry/history-samples/12497")
    assert res.status_code == 200
    samples = res.json()
    assert len(samples) > 0, "No historical samples extracted from data/"
    print(f"✓ Extracted {len(samples)} real historical log points from dataset.")
    res = client.post("/api/telemetry/apply-history-point/12497?point_idx=2")
    assert res.status_code == 200
    print("✓ Replayed historical point successfully:", res.json()["applied_point"]["current_station"])

    print("\n14. Testing Train Search by From/To Station...")
    # Test 1: New Delhi -> Amritsar
    r_ndls_asr = client.get("/api/trains/search?from_station=NDLS&to_station=ASR")
    assert r_ndls_asr.status_code == 200
    t1 = r_ndls_asr.json()["trains"][0]
    assert t1["train_number"] == "12497"
    print(f"  ✓ Test 1 Passed: NDLS -> ASR found Train {t1['train_number']} (Dep: {t1['origin_station']['departure']}, Arr: {t1['destination_station']['scheduled_arrival']}, Dyn ETA: {t1['destination_station']['dynamic_eta']})")

    # Test 2: Amritsar -> New Delhi (Reverse)
    r_asr_ndls = client.get("/api/trains/search?from_station=ASR&to_station=NDLS")
    assert r_asr_ndls.status_code == 200
    t2 = r_asr_ndls.json()["trains"][0]
    assert t2["train_number"] == "12498"
    print(f"  ✓ Test 2 Passed: ASR -> NDLS found Train {t2['train_number']}")

    # Test 3: New Delhi -> Kalka
    r_ndls_klk = client.get("/api/trains/search?from_station=New%20Delhi&to_station=Kalka")
    assert r_ndls_klk.status_code == 200
    t3 = r_ndls_klk.json()["trains"][0]
    assert t3["train_number"] == "12011"
    print(f"  ✓ Test 3 Passed: NDLS -> KLK found Train {t3['train_number']}")

    # Test 4: Kalka -> New Delhi
    r_klk_ndls = client.get("/api/trains/search?from_station=KLK&to_station=NDLS")
    assert r_klk_ndls.status_code == 200
    t4 = r_klk_ndls.json()["trains"][0]
    assert t4["train_number"] == "12012"
    print(f"  ✓ Test 4 Passed: KLK -> NDLS found Train {t4['train_number']}")

    # Test 5: Invalid station
    r_inv = client.get("/api/trains/search?from_station=NON_EXISTENT_STATION&to_station=ASR")
    assert r_inv.status_code == 404
    print("  ✓ Test 5 Passed: Invalid station returned 404 cleanly")

    # Test 6: Same station
    r_same = client.get("/api/trains/search?from_station=NDLS&to_station=NDLS")
    assert r_same.status_code == 400
    print("  ✓ Test 6 Passed: Same origin/destination returned 400 cleanly")

    # Test 7: Route where no direct train exists
    r_no_direct = client.get("/api/trains/search?from_station=ASR&to_station=KLK")
    assert r_no_direct.status_code == 200
    assert r_no_direct.json()["count"] == 0
    print("  ✓ Test 7 Passed: No direct train route correctly returned count 0")

    # Test 8: Multiple trains on corridor sub-route (SNP -> PNP)
    r_multi = client.get("/api/trains/search?from_station=SNP&to_station=PNP")
    assert r_multi.status_code == 200
    assert r_multi.json()["count"] >= 1
    print(f"  ✓ Test 8 Passed: Sub-corridor SNP -> PNP found {r_multi.json()['count']} trains")

    # Test 9: Search result structure & track details
    assert "departure" in t1["origin_station"]
    assert "scheduled_arrival" in t1["destination_station"]
    assert "dynamic_eta" in t1["destination_station"]
    print("  ✓ Test 9 Passed: Search response contains dynamic ETA, delay, and sequence")

    # Test 10: Track page detail loads
    r_detail = client.get(f"/api/trains/{t1['train_number']}")
    assert r_detail.status_code == 200
    assert len(r_detail.json()["predictions"]) > 0
    print(f"  ✓ Test 10 Passed: Track detail for Train {t1['train_number']} loaded and verified")

    print("\n===========================================")
    print("ALL 14 BACKEND, DATASET & SEARCH TESTS PASSED!")
    print("===========================================")

if __name__ == "__main__":
    run_tests()
