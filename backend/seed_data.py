import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, engine, Base
from models import User, Station, Train, RouteStop, LiveTrainState, FieldObservation, ETAPrediction
import hashlib

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 1. Users
        demo_user = User(
            email="passenger@railnirdeshak.in",
            full_name="Rajesh Sharma",
            hashed_password=hash_pw("demo123"),
            role="passenger"
        )
        controller_user = User(
            email="control@railnirdeshak.in",
            full_name="Northern Zone Controller",
            hashed_password=hash_pw("admin123"),
            role="controller"
        )
        db.add_all([demo_user, controller_user])
        db.commit()

        # 2. Stations
        stations_data = [
            {"code": "NDLS", "name": "New Delhi", "latitude": 28.6427, "longitude": 77.2195, "zone": "NR", "division": "DLI"},
            {"code": "SNP", "name": "Sonipat Junction", "latitude": 28.9944, "longitude": 77.0194, "zone": "NR", "division": "DLI"},
            {"code": "PNP", "name": "Panipat Junction", "latitude": 29.3909, "longitude": 76.9635, "zone": "NR", "division": "DLI"},
            {"code": "KUN", "name": "Karnal", "latitude": 29.6857, "longitude": 76.9905, "zone": "NR", "division": "DLI"},
            {"code": "KKDE", "name": "Kurukshetra Junction", "latitude": 29.9695, "longitude": 76.8783, "zone": "NR", "division": "DLI"},
            {"code": "UMB", "name": "Ambala Cantt Junction", "latitude": 30.3340, "longitude": 76.8329, "zone": "NR", "division": "UMB"},
            {"code": "CDG", "name": "Chandigarh Junction", "latitude": 30.7046, "longitude": 76.8206, "zone": "NR", "division": "UMB"},
            {"code": "KLK", "name": "Kalka", "latitude": 30.8359, "longitude": 76.9360, "zone": "NR", "division": "UMB"},
            {"code": "LDH", "name": "Ludhiana Junction", "latitude": 30.9010, "longitude": 75.8573, "zone": "NR", "division": "FZR"},
            {"code": "JUC", "name": "Jalandhar City", "latitude": 31.3260, "longitude": 75.5762, "zone": "NR", "division": "FZR"},
            {"code": "ASR", "name": "Amritsar Junction", "latitude": 31.6340, "longitude": 74.8723, "zone": "NR", "division": "FZR"},
        ]

        station_objs = {}
        for s in stations_data:
            st = Station(**s)
            db.add(st)
            db.flush()
            station_objs[s["code"]] = st

        db.commit()

        # 3. Trains
        shane_punjab = Train(
            train_number="12497",
            train_name="Shane Punjab Express",
            train_type="Superfast Express",
            source="New Delhi (NDLS)",
            destination="Amritsar Junction (ASR)",
            total_distance_km=448.0,
            is_active=True
        )
        kalka_shatabdi = Train(
            train_number="12011",
            train_name="Kalka Shatabdi Express",
            train_type="Shatabdi Express",
            source="New Delhi (NDLS)",
            destination="Kalka (KLK)",
            total_distance_km=303.0,
            is_active=True
        )
        db.add_all([shane_punjab, kalka_shatabdi])
        db.commit()

        # 4. Route Stops for 12497 Shane Punjab
        shane_stops = [
            {"code": "NDLS", "seq": 1, "arr": "06:40", "dep": "06:40", "dist": 0.0, "halt": 0, "plat": "1"},
            {"code": "SNP", "seq": 2, "arr": "07:20", "dep": "07:22", "dist": 44.0, "halt": 2, "plat": "2"},
            {"code": "PNP", "seq": 3, "arr": "07:50", "dep": "07:52", "dist": 89.0, "halt": 2, "plat": "3"},
            {"code": "KUN", "seq": 4, "arr": "08:16", "dep": "08:18", "dist": 123.0, "halt": 2, "plat": "2"},
            {"code": "KKDE", "seq": 5, "arr": "08:41", "dep": "08:43", "dist": 156.0, "halt": 2, "plat": "1"},
            {"code": "UMB", "seq": 6, "arr": "09:55", "dep": "10:02", "dist": 198.0, "halt": 7, "plat": "7"},
            {"code": "LDH", "seq": 7, "arr": "11:34", "dep": "11:44", "dist": 312.0, "halt": 10, "plat": "1"},
            {"code": "JUC", "seq": 8, "arr": "12:45", "dep": "12:50", "dist": 369.0, "halt": 5, "plat": "2"},
            {"code": "ASR", "seq": 9, "arr": "14:15", "dep": "14:15", "dist": 448.0, "halt": 0, "plat": "4"},
        ]

        for stop in shane_stops:
            db.add(RouteStop(
                train_id=shane_punjab.id,
                station_id=station_objs[stop["code"]].id,
                stop_sequence=stop["seq"],
                scheduled_arrival=stop["arr"],
                scheduled_departure=stop["dep"],
                distance_from_source_km=stop["dist"],
                halt_minutes=stop["halt"],
                platform=stop["plat"]
            ))

        # 4b. Route Stops for 12011 Kalka Shatabdi
        kalka_stops = [
            {"code": "NDLS", "seq": 1, "arr": "07:40", "dep": "07:40", "dist": 0.0, "halt": 0, "plat": "2"},
            {"code": "PNP", "seq": 2, "arr": "08:48", "dep": "08:50", "dist": 89.0, "halt": 2, "plat": "3"},
            {"code": "KKDE", "seq": 3, "arr": "09:30", "dep": "09:32", "dist": 156.0, "halt": 2, "plat": "1"},
            {"code": "UMB", "seq": 4, "arr": "10:15", "dep": "10:23", "dist": 198.0, "halt": 8, "plat": "6"},
            {"code": "CDG", "seq": 5, "arr": "11:05", "dep": "11:13", "dist": 266.0, "halt": 8, "plat": "1"},
            {"code": "KLK", "seq": 6, "arr": "11:45", "dep": "11:45", "dist": 303.0, "halt": 0, "plat": "3"},
        ]

        for stop in kalka_stops:
            db.add(RouteStop(
                train_id=kalka_shatabdi.id,
                station_id=station_objs[stop["code"]].id,
                stop_sequence=stop["seq"],
                scheduled_arrival=stop["arr"],
                scheduled_departure=stop["dep"],
                distance_from_source_km=stop["dist"],
                halt_minutes=stop["halt"],
                platform=stop["plat"]
            ))

        db.commit()

        # 5. Live State
        live_12497 = LiveTrainState(
            train_id=shane_punjab.id,
            current_station_id=station_objs["SNP"].id,
            next_station_id=station_objs["PNP"].id,
            latitude=29.1850,
            longitude=76.9920,
            speed_kmh=78.5,
            current_delay_min=14,
            remaining_distance_km=379.0,
            status="RUNNING",
            track_section="NDLS-PNP-LINE1",
            reference_pole="KM 68/14",
            weather_condition="CLEAR"
        )

        live_12011 = LiveTrainState(
            train_id=kalka_shatabdi.id,
            current_station_id=station_objs["NDLS"].id,
            next_station_id=station_objs["PNP"].id,
            latitude=28.8200,
            longitude=77.1200,
            speed_kmh=88.0,
            current_delay_min=6,
            remaining_distance_km=271.0,
            status="RUNNING",
            track_section="NDLS-PNP-LINE1",
            reference_pole="KM 28/06",
            weather_condition="CLEAR"
        )
        db.add_all([live_12497, live_12011])
        db.commit()

        # 6. Field Observations
        obs1 = FieldObservation(
            station_id=station_objs["PNP"].id,
            track_section="NDLS-PNP-LINE1",
            pole_reference="KM 74/22",
            observation_type="SIGNAL_INTERLOCKING",
            description="Automatic Block Signal testing in progress near Ganaur - speed restricted to 50 km/h.",
            impact_delay_min=8,
            severity="MEDIUM"
        )
        obs2 = FieldObservation(
            station_id=station_objs["UMB"].id,
            track_section="PNP-UMB-LINE2",
            pole_reference="KM 182/04",
            observation_type="CONGESTION_HEADWAY",
            description="High freight traffic density at Ambala Cantt approach causing queue delays.",
            impact_delay_min=6,
            severity="HIGH"
        )
        db.add_all([obs1, obs2])
        db.commit()

        # 7. Seed Initial Predictions for 12497
        pred1 = ETAPrediction(
            train_id=shane_punjab.id,
            station_id=station_objs["PNP"].id,
            scheduled_arrival="07:50",
            predicted_arrival="08:04",
            predicted_delay_min=14,
            signal_delay_min=8,
            congestion_delay_min=6,
            weather_delay_min=3,
            recovery_min=3,
            propagation_risk="LOW",
            reason_summary="Signal Halt (+8m) + Section Congestion (+6m) + Weather (+3m) - Section Recovery Buffer (-3m)"
        )
        pred2 = ETAPrediction(
            train_id=shane_punjab.id,
            station_id=station_objs["KUN"].id,
            scheduled_arrival="08:16",
            predicted_arrival="08:28",
            predicted_delay_min=12,
            signal_delay_min=6,
            congestion_delay_min=5,
            weather_delay_min=3,
            recovery_min=2,
            propagation_risk="LOW",
            reason_summary="Speed restriction clearing (+6m) + Moderate Congestion (+5m) - Recovery (-2m)"
        )
        pred3 = ETAPrediction(
            train_id=shane_punjab.id,
            station_id=station_objs["KKDE"].id,
            scheduled_arrival="08:41",
            predicted_arrival="08:51",
            predicted_delay_min=10,
            signal_delay_min=4,
            congestion_delay_min=4,
            weather_delay_min=3,
            recovery_min=1,
            propagation_risk="MODERATE",
            reason_summary="Headway separation with 12011 Shatabdi behind (+4m) + Residual delay (+7m) - Buffer (-1m)"
        )
        pred4 = ETAPrediction(
            train_id=shane_punjab.id,
            station_id=station_objs["UMB"].id,
            scheduled_arrival="09:55",
            predicted_arrival="10:04",
            predicted_delay_min=9,
            signal_delay_min=3,
            congestion_delay_min=6,
            weather_delay_min=2,
            recovery_min=2,
            propagation_risk="HIGH",
            reason_summary="Yard approach congestion (+6m) + Signal (+3m) - Scheduled buffer (-2m)"
        )
        db.add_all([pred1, pred2, pred3, pred4])
        print("Database base seeded successfully with Trains 12497, 12011, stations, field surveys and predictions.")
    finally:
        db.close()

    try:
        from data_loader import load_all_data
        load_all_data()
    except Exception as e:
        print("Data loader note:", e)

if __name__ == "__main__":
    seed()
