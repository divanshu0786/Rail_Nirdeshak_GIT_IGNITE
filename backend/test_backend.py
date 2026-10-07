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

    print("\n===========================================")
    print("ALL 13 BACKEND & DATASET TESTS PASSED!")
    print("===========================================")

if __name__ == "__main__":
    run_tests()
