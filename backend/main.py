import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import engine, Base, get_db
import models
import schemas
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_current_user
)
from eta_engine import calculate_dynamic_eta
from websocket_manager import manager
import weather_service

# Create tables on startup if not existing
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Rail Nirdeshak API",
    description="Dynamic ETA Prediction Platform for Indian Railways",
    version="1.0.0"
)

@app.on_event("startup")
def ensure_database_seeded():
    """Ensure database has stations and trains populated on startup."""
    db = SessionLocal()
    try:
        train_count = db.query(models.Train).count()
        if train_count == 0:
            print("[Rail Nirdeshak] Database is empty. Running auto-seeder...")
            try:
                import seed_data
                seed_data.seed()
                print("[Rail Nirdeshak] Database auto-seeding complete.")
            except Exception as e:
                print(f"[Rail Nirdeshak] Auto-seeding warning: {e}")
    except Exception as err:
        print(f"[Rail Nirdeshak] Startup DB check error: {err}")
    finally:
        db.close()

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Rail Nirdeshak Backend", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/config")
def get_app_config():
    return {
        "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY", ""),
        "maptiler_api_key": os.getenv("MAPTILER_API_KEY", os.getenv("MAP_API_KEY", "")),
        "map_api_key": os.getenv("MAP_API_KEY", os.getenv("MAPTILER_API_KEY", "")),
        "has_weather_api": bool(os.getenv("OPENWEATHERMAP_API_KEY"))
    }

# ----------------- AUTHENTICATION -----------------
@app.post("/auth/register", response_model=schemas.TokenOut)
def register(user_in: schemas.UserRegister, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = models.User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=hash_password(user_in.password),
        role=user_in.role or "passenger"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    return {"access_token": token, "token_type": "bearer", "user": user}

@app.post("/auth/login", response_model=schemas.TokenOut)
def login(creds: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == creds.email).first()
    if not user or not verify_password(creds.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    return {"access_token": token, "token_type": "bearer", "user": user}

@app.get("/auth/me", response_model=schemas.UserOut)
def get_me(user: models.User = Depends(require_current_user)):
    return user

# ----------------- STATIONS & TRAINS -----------------
@app.get("/api/stations", response_model=List[schemas.StationOut])
def list_stations(query: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Station)
    if query:
        q = q.filter(
            (models.Station.code.ilike(f"%{query}%")) |
            (models.Station.name.ilike(f"%{query}%"))
        )
    return q.all()

@app.get("/api/trains", response_model=List[schemas.TrainOut])
def list_trains(query: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Train)
    if query:
        q = q.filter(
            (models.Train.train_number.ilike(f"%{query}%")) |
            (models.Train.train_name.ilike(f"%{query}%")) |
            (models.Train.source.ilike(f"%{query}%")) |
            (models.Train.destination.ilike(f"%{query}%"))
        )
    return q.all()

@app.get("/api/trains/search")
@app.get("/trains/search")
def search_trains_route(from_station: Optional[str] = None, to_station: Optional[str] = None, db: Session = Depends(get_db)):
    # Support both 'from' and 'from_station' parameter aliases
    from_q = from_station or ""
    to_q = to_station or ""

    if not from_q.strip() or not to_q.strip():
        raise HTTPException(status_code=400, detail="Please select both origin (from) and destination (to) stations.")

    def extract_code_or_name(st_str: str) -> str:
        st_str = st_str.strip()
        if "(" in st_str and ")" in st_str:
            code = st_str.split("(")[-1].split(")")[0].strip()
            if code:
                return code
        return st_str

    from_clean = extract_code_or_name(from_q)
    to_clean = extract_code_or_name(to_q)

    # 1. Resolve Station Entities
    from_st = db.query(models.Station).filter(
        (models.Station.code.ilike(from_clean)) | (models.Station.name.ilike(f"%{from_clean}%"))
    ).first()

    to_st = db.query(models.Station).filter(
        (models.Station.code.ilike(to_clean)) | (models.Station.name.ilike(f"%{to_clean}%"))
    ).first()

    if not from_st:
        raise HTTPException(status_code=404, detail=f"Origin station '{from_q}' not found.")
    if not to_st:
        raise HTTPException(status_code=404, detail=f"Destination station '{to_q}' not found.")

    if from_st.id == to_st.id:
        raise HTTPException(status_code=400, detail="Origin and destination cannot be the same station.")

    # 2. Find matching trains in correct sequence order
    all_trains = db.query(models.Train).filter(models.Train.is_active == True).all()
    results = []

    for t in all_trains:
        stops = t.route_stops
        from_stop = next((s for s in stops if s.station_id == from_st.id), None)
        to_stop = next((s for s in stops if s.station_id == to_st.id), None)

        if from_stop and to_stop and from_stop.stop_sequence < to_stop.stop_sequence:
            curr_delay = t.live_state.current_delay_min if t.live_state else 0
            live_status = t.live_state.status if t.live_state else "SCHEDULED"
            speed = t.live_state.speed_kmh if t.live_state else None
            
            dyn_eta = None
            if to_stop.scheduled_arrival:
                try:
                    parts = to_stop.scheduled_arrival.split(":")
                    h, m = int(parts[0]), int(parts[1])
                    total_m = (h * 60 + m + curr_delay) % (24 * 60)
                    dyn_eta = f"{total_m // 60:02d}:{total_m % 60:02d}"
                except Exception:
                    dyn_eta = to_stop.scheduled_arrival

            results.append({
                "train_id": t.id,
                "train_number": t.train_number,
                "train_name": t.train_name,
                "train_type": t.train_type,
                "source": t.source,
                "destination": t.destination,
                "origin_station": {
                    "code": from_st.code,
                    "name": from_st.name,
                    "departure": from_stop.scheduled_departure or from_stop.scheduled_arrival or "--",
                    "sequence": from_stop.stop_sequence,
                    "platform": from_stop.platform
                },
                "destination_station": {
                    "code": to_st.code,
                    "name": to_st.name,
                    "scheduled_arrival": to_stop.scheduled_arrival or to_stop.scheduled_departure or "--",
                    "dynamic_eta": dyn_eta or to_stop.scheduled_arrival or "--",
                    "sequence": to_stop.stop_sequence,
                    "platform": to_stop.platform
                },
                "distance_km": max(0.0, round(to_stop.distance_from_source_km - from_stop.distance_from_source_km, 1)),
                "current_delay_min": curr_delay,
                "live_speed_kmh": speed,
                "live_status": live_status,
                "is_live_available": t.live_state is not None
            })

    return {
        "from_station": {"code": from_st.code, "name": from_st.name},
        "to_station": {"code": to_st.code, "name": to_st.name},
        "count": len(results),
        "trains": results
    }

@app.get("/api/trains/{train_ident}")
def get_train_detail(train_ident: str, db: Session = Depends(get_db)):
    train = None
    if train_ident.isdigit():
        train = db.query(models.Train).filter(
            (models.Train.id == int(train_ident)) |
            (models.Train.train_number == train_ident)
        ).first()
    else:
        train = db.query(models.Train).filter(models.Train.train_number == train_ident).first()

    if not train:
        raise HTTPException(status_code=404, detail="Train not found")

    # If predictions are empty or outdated, recalculate
    if train.live_state and not train.predictions:
        calculate_dynamic_eta(db, train, train.live_state)
        db.refresh(train)

    # Format predictions with station details
    preds = []
    for p in train.predictions:
        station = db.query(models.Station).filter(models.Station.id == p.station_id).first()
        preds.append({
            "id": p.id,
            "station_id": p.station_id,
            "station_name": station.name if station else "Unknown",
            "station_code": station.code if station else "UNK",
            "scheduled_arrival": p.scheduled_arrival,
            "predicted_arrival": p.predicted_arrival,
            "predicted_delay_min": p.predicted_delay_min,
            "signal_delay_min": p.signal_delay_min,
            "congestion_delay_min": p.congestion_delay_min,
            "weather_delay_min": p.weather_delay_min,
            "recovery_min": p.recovery_min,
            "propagation_risk": p.propagation_risk,
            "reason_summary": p.reason_summary
        })

    # Build response
    stops_data = []
    for s in train.route_stops:
        station = db.query(models.Station).filter(models.Station.id == s.station_id).first()
        stops_data.append({
            "id": s.id,
            "station_id": s.station_id,
            "stop_sequence": s.stop_sequence,
            "scheduled_arrival": s.scheduled_arrival,
            "scheduled_departure": s.scheduled_departure,
            "distance_from_source_km": s.distance_from_source_km,
            "halt_minutes": s.halt_minutes,
            "platform": s.platform,
            "station": {
                "id": station.id,
                "code": station.code,
                "name": station.name,
                "latitude": station.latitude,
                "longitude": station.longitude,
                "zone": station.zone,
                "division": station.division
            }
        })

    live_data = None
    if train.live_state:
        curr_st = db.query(models.Station).filter(models.Station.id == train.live_state.current_station_id).first()
        next_st = db.query(models.Station).filter(models.Station.id == train.live_state.next_station_id).first()
        weather_info = weather_service.get_live_weather(
            train.live_state.latitude,
            train.live_state.longitude,
            location_name=curr_st.name if curr_st else train.source
        )
        live_data = {
            "id": train.live_state.id,
            "train_id": train.live_state.train_id,
            "latitude": train.live_state.latitude,
            "longitude": train.live_state.longitude,
            "speed_kmh": train.live_state.speed_kmh,
            "current_delay_min": train.live_state.current_delay_min,
            "remaining_distance_km": train.live_state.remaining_distance_km,
            "status": train.live_state.status,
            "track_section": train.live_state.track_section,
            "reference_pole": train.live_state.reference_pole,
            "weather_condition": train.live_state.weather_condition,
            "weather_info": weather_info,
            "last_updated": train.live_state.last_updated.isoformat(),
            "current_station": {"code": curr_st.code, "name": curr_st.name} if curr_st else None,
            "next_station": {"code": next_st.code, "name": next_st.name} if next_st else None,
        }

    return {
        "id": train.id,
        "train_number": train.train_number,
        "train_name": train.train_name,
        "train_type": train.train_type,
        "source": train.source,
        "destination": train.destination,
        "total_distance_km": train.total_distance_km,
        "is_active": train.is_active,
        "route_stops": stops_data,
        "live_state": live_data,
        "predictions": preds
    }

# ----------------- TELEMETRY & SIMULATION -----------------
@app.post("/api/telemetry")
async def receive_telemetry(telemetry: schemas.TelemetryInput, db: Session = Depends(get_db)):
    train = db.query(models.Train).filter(models.Train.train_number == telemetry.train_number).first()
    if not train:
        raise HTTPException(status_code=404, detail="Train not found for telemetry")

    state = train.live_state
    if not state:
        state = models.LiveTrainState(train_id=train.id, latitude=telemetry.latitude, longitude=telemetry.longitude)
        db.add(state)

    state.latitude = telemetry.latitude
    state.longitude = telemetry.longitude
    state.speed_kmh = telemetry.speed_kmh
    state.current_delay_min = telemetry.current_delay_min
    state.remaining_distance_km = telemetry.remaining_distance_km
    state.status = telemetry.status or state.status
    state.track_section = telemetry.track_section or state.track_section
    state.reference_pole = telemetry.reference_pole or state.reference_pole
    state.weather_condition = telemetry.weather_condition or state.weather_condition
    state.last_updated = datetime.utcnow()

    db.commit()
    db.refresh(state)

    # Trigger Dynamic Recalculation
    preds = calculate_dynamic_eta(db, train, state)

    # Broadcast real-time update to WebSocket subscribers
    payload = {
        "type": "TELEMETRY_UPDATE",
        "train_id": train.id,
        "train_number": train.train_number,
        "speed_kmh": state.speed_kmh,
        "latitude": state.latitude,
        "longitude": state.longitude,
        "current_delay_min": state.current_delay_min,
        "reference_pole": state.reference_pole,
        "predictions_count": len(preds),
        "timestamp": state.last_updated.isoformat()
    }
    await manager.broadcast_train_update(train.id, payload)
    await manager.broadcast_control_room(payload)

    return {"status": "success", "message": "Telemetry processed & Dynamic ETA recalculated", "live_state": payload}

@app.post("/api/telemetry/simulate-step/{train_id}")
async def simulate_step(train_id: int, delay_delta: int = 2, speed: float = 75.0, db: Session = Depends(get_db)):
    train = db.query(models.Train).filter(models.Train.id == train_id).first()
    if not train or not train.live_state:
        raise HTTPException(status_code=404, detail="Train or live state not found")

    # Step latitude slightly northwards towards Amritsar/Kalka
    train.live_state.latitude += 0.04
    train.live_state.longitude -= 0.02
    train.live_state.current_delay_min = max(0, train.live_state.current_delay_min + delay_delta)
    train.live_state.speed_kmh = speed
    train.live_state.remaining_distance_km = max(10.0, train.live_state.remaining_distance_km - 8.0)
    train.live_state.last_updated = datetime.utcnow()

    db.commit()

    # Recalculate Dynamic ETA
    preds = calculate_dynamic_eta(db, train, train.live_state)

    payload = {
        "type": "SIMULATION_STEP",
        "train_id": train.id,
        "train_number": train.train_number,
        "current_delay_min": train.live_state.current_delay_min,
        "speed_kmh": train.live_state.speed_kmh,
        "latitude": train.live_state.latitude,
        "longitude": train.live_state.longitude,
        "predictions_count": len(preds),
        "timestamp": train.live_state.last_updated.isoformat()
    }
    await manager.broadcast_train_update(train.id, payload)
    await manager.broadcast_control_room(payload)

    return {"status": "success", "train_number": train.train_number, "new_delay": train.live_state.current_delay_min}

@app.get("/api/telemetry/history-samples/{train_number}")
def get_history_samples(train_number: str):
    import csv
    csv_file = os.path.join(os.path.dirname(__file__), "..", "data", "ruhani_12497_shan_e_punjab_6months.csv")
    if not os.path.exists(csv_file):
        return []
    
    samples = []
    with open(csv_file, mode="r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            if idx % 15 == 0: # Sample every 15th row for smooth scrubbing
                samples.append({
                    "timestamp": row.get("Timestamp") or row.get("Date"),
                    "latitude": float(row.get("Latitude", 28.6434)),
                    "longitude": float(row.get("Longitude", 77.2196)),
                    "speed_kmh": float(row.get("Current_Speed", 80)),
                    "delay_min": int(float(row.get("Current_Delay", 0))),
                    "current_station": row.get("Current_Station", ""),
                    "next_station": row.get("Next_Station", "")
                })
            if len(samples) >= 50:
                break
    return samples

@app.post("/api/telemetry/apply-history-point/{train_number}")
async def apply_history_point(train_number: str, point_idx: int = 0, db: Session = Depends(get_db)):
    samples = get_history_samples(train_number)
    if not samples or point_idx >= len(samples):
        raise HTTPException(status_code=400, detail="Invalid sample point")
    
    pt = samples[point_idx]
    train = db.query(models.Train).filter(models.Train.train_number == train_number).first()
    if not train or not train.live_state:
        raise HTTPException(status_code=404, detail="Train not found")

    train.live_state.latitude = pt["latitude"]
    train.live_state.longitude = pt["longitude"]
    train.live_state.speed_kmh = pt["speed_kmh"]
    train.live_state.current_delay_min = pt["delay_min"]
    train.live_state.last_updated = datetime.utcnow()
    db.commit()

    preds = calculate_dynamic_eta(db, train, train.live_state)
    payload = {
        "type": "TELEMETRY_UPDATE",
        "train_id": train.id,
        "train_number": train.train_number,
        "speed_kmh": train.live_state.speed_kmh,
        "latitude": train.live_state.latitude,
        "longitude": train.live_state.longitude,
        "current_delay_min": train.live_state.current_delay_min,
        "reference_pole": train.live_state.reference_pole,
        "predictions_count": len(preds),
        "timestamp": train.live_state.last_updated.isoformat()
    }
    await manager.broadcast_train_update(train.id, payload)
    await manager.broadcast_control_room(payload)

    return {"status": "success", "applied_point": pt}

# ----------------- SAVED TRAINS (MY TRAINS) -----------------
@app.get("/api/saved-trains")
def get_saved_trains(user: models.User = Depends(require_current_user), db: Session = Depends(get_db)):
    saved = db.query(models.SavedTrain).filter(models.SavedTrain.user_id == user.id).all()
    results = []
    for s in saved:
        t = s.train
        results.append({
            "saved_id": s.id,
            "train_id": t.id,
            "train_number": t.train_number,
            "train_name": t.train_name,
            "source": t.source,
            "destination": t.destination,
            "current_delay_min": t.live_state.current_delay_min if t.live_state else 0,
            "status": t.live_state.status if t.live_state else "SCHEDULED",
            "saved_at": s.created_at.isoformat()
        })
    return results

@app.post("/api/saved-trains/{train_id}")
def add_saved_train(train_id: int, user: models.User = Depends(require_current_user), db: Session = Depends(get_db)):
    train = db.query(models.Train).filter(models.Train.id == train_id).first()
    if not train:
        raise HTTPException(status_code=404, detail="Train not found")
    
    existing = db.query(models.SavedTrain).filter(
        models.SavedTrain.user_id == user.id,
        models.SavedTrain.train_id == train_id
    ).first()
    if existing:
        return {"status": "already_saved", "saved_id": existing.id}

    saved = models.SavedTrain(user_id=user.id, train_id=train_id)
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return {"status": "saved", "saved_id": saved.id}

@app.delete("/api/saved-trains/{train_id}")
def remove_saved_train(train_id: int, user: models.User = Depends(require_current_user), db: Session = Depends(get_db)):
    saved = db.query(models.SavedTrain).filter(
        models.SavedTrain.user_id == user.id,
        models.SavedTrain.train_id == train_id
    ).first()
    if saved:
        db.delete(saved)
        db.commit()
    return {"status": "removed"}

# ----------------- FIELD OBSERVATIONS -----------------
@app.get("/api/field-observations", response_model=List[schemas.FieldObservationOut])
def get_field_observations(limit: int = 10, db: Session = Depends(get_db)):
    return db.query(models.FieldObservation).order_by(models.FieldObservation.reported_at.desc()).limit(limit).all()

@app.post("/api/field-observations", response_model=schemas.FieldObservationOut)
def create_field_observation(obs_in: schemas.FieldObservationCreate, db: Session = Depends(get_db)):
    obs = models.FieldObservation(
        station_id=obs_in.station_id,
        track_section=obs_in.track_section,
        pole_reference=obs_in.pole_reference,
        observation_type=obs_in.observation_type,
        description=obs_in.description,
        impact_delay_min=obs_in.impact_delay_min,
        severity=obs_in.severity or "MEDIUM"
    )
    db.add(obs)
    db.commit()
    db.refresh(obs)
    return obs

# ----------------- LIVE WEATHER API -----------------
@app.get("/api/weather")
def get_weather_data(lat: float = 28.6427, lon: float = 77.2195, location: Optional[str] = None):
    return weather_service.get_live_weather(lat, lon, location)

# ----------------- CONTROL ROOM OVERVIEW -----------------
@app.get("/api/control-room/overview")
def get_control_room_overview(db: Session = Depends(get_db)):
    trains = db.query(models.Train).filter(models.Train.is_active == True).all()
    observations = db.query(models.FieldObservation).all()
    
    active_trains_summary = []
    total_delayed = 0
    high_propagation_risks = 0

    for t in trains:
        delay = t.live_state.current_delay_min if t.live_state else 0
        if delay > 5:
            total_delayed += 1
        
        # Check propagation risk
        prop_risk = "LOW"
        if t.predictions:
            prop_risk = t.predictions[0].propagation_risk
            if prop_risk in ["HIGH", "MODERATE"]:
                high_propagation_risks += 1

        active_trains_summary.append({
            "id": t.id,
            "train_number": t.train_number,
            "train_name": t.train_name,
            "source": t.source,
            "destination": t.destination,
            "speed_kmh": t.live_state.speed_kmh if t.live_state else 0,
            "current_delay_min": delay,
            "status": t.live_state.status if t.live_state else "SCHEDULED",
            "track_section": t.live_state.track_section if t.live_state else "N/A",
            "propagation_risk": prop_risk,
            "upcoming_predictions": len(t.predictions)
        })

    return {
        "active_trains_count": len(trains),
        "delayed_trains_count": total_delayed,
        "high_risk_propagations": high_propagation_risks,
        "active_field_alerts": len(observations),
        "trains": active_trains_summary,
        "observations": [
            {
                "id": o.id,
                "section": o.track_section,
                "pole": o.pole_reference,
                "type": o.observation_type,
                "impact": o.impact_delay_min,
                "severity": o.severity,
                "description": o.description
            }
            for o in observations
        ]
    }

# ----------------- WEBSOCKET ENDPOINTS -----------------
@app.websocket("/ws/trains/{train_id}")
async def websocket_train_endpoint(websocket: WebSocket, train_id: int):
    await manager.connect_train(websocket, train_id)
    try:
        while True:
            # Keep socket alive and accept ping/pong or simulation trigger
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect_train(websocket, train_id)

@app.websocket("/ws/control-room")
async def websocket_control_endpoint(websocket: WebSocket):
    await manager.connect_control(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect_control(websocket)

import os
from starlette.staticfiles import StaticFiles

# Resolve frontend path
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"[Rail Nirdeshak] Launching on {host}:{port}")
    uvicorn.run(app, host=host, port=port)



