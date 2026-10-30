import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import engine, Base, SessionLocal, get_db, upgrade_database_schema
import models
import schemas
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_current_user,
    require_controller_user,
    require_admin_user,
    verify_ws_token,
    record_failed_attempt,
    is_rate_limited,
    clear_failed_attempts,
    set_session_cookie,
    clear_session_cookie,
    validate_railway_id,
    SECRET_KEY,
    ALGORITHM
)
from firebase_service import (
    is_phone_request_rate_limited,
    record_phone_request_attempt,
    create_phone_verification_session,
    consume_phone_verification_session,
    verify_firebase_id_token,
    normalize_phone_number,
    mask_phone_number
)
from eta_engine import calculate_dynamic_eta
from websocket_manager import manager
import weather_service

# Auto-upgrade database schema and create tables if not existing
upgrade_database_schema(engine)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Rail Nirdeshak API",
    description="Dynamic ETA Prediction & Delay Propagation Platform for Indian Railways",
    version="1.0.0"
)

@app.on_event("startup")
def startup_event():
    """Ensure database schema is up-to-date and auto-seed on startup."""
    upgrade_database_schema(engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        import seed_data
        seed_data.seed_controller_if_missing(db)
        train_count = db.query(models.Train).count()
        if train_count == 0:
            print("[Rail Nirdeshak] Database is empty. Running auto-seeder...")
            try:
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
        "has_weather_api": bool(os.getenv("OPENWEATHERMAP_API_KEY")),
        "firebase": {
            "apiKey": os.getenv("FIREBASE_API_KEY", "AIzaSyCf0ljc0-ppBcwhh8gXEeHAWP-wSQGLjmg"),
            "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", "rail-nirdeshak.firebaseapp.com"),
            "projectId": os.getenv("FIREBASE_PROJECT_ID", "rail-nirdeshak"),
            "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET", "rail-nirdeshak.firebasestorage.app"),
            "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", "724629020533"),
            "appId": os.getenv("FIREBASE_APP_ID", "1:724629020533:web:e1f98f8e9bb42e37d9bd3c")
        }
    }

# ----------------- AUTHENTICATION -----------------
@app.post("/auth/register", response_model=schemas.TokenOut)
@app.post("/api/auth/register", response_model=schemas.TokenOut)
def register(user_in: schemas.UserRegister, db: Session = Depends(get_db)):
    # Check existing email
    existing_email = db.query(models.User).filter(models.User.email == user_in.email.strip().lower()).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email is already registered.")
    
    # Check existing username or railway_id if provided
    username_clean = (user_in.username or user_in.email.split("@")[0]).strip().lower()
    existing_user = db.query(models.User).filter(models.User.username == username_clean).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username is already taken.")

    # Public registration is strictly restricted to 'passenger' role
    assigned_role = "passenger"

    user = models.User(
        username=username_clean,
        email=user_in.email.strip().lower(),
        full_name=user_in.full_name.strip(),
        hashed_password=hash_password(user_in.password),
        role=assigned_role,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "email": user.email,
        "role": user.role
    })
    return {"access_token": token, "token_type": "bearer", "user": user}

@app.post("/auth/login", response_model=schemas.TokenOut)
@app.post("/api/auth/login", response_model=schemas.TokenOut)
def login(creds: schemas.UserLogin, db: Session = Depends(get_db)):
    identifier = (creds.username or creds.email or "").strip().lower()
    if not identifier or not creds.password:
        raise HTTPException(status_code=400, detail="Username/Email and password are required.")

    # Rate limiting check against brute-force attacks
    rate_limited, wait_sec = is_rate_limited(identifier)
    if rate_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Temporarily locked for {wait_sec} seconds."
        )

    # Query user by username, railway_id, or email
    user = db.query(models.User).filter(
        (models.User.username == identifier) |
        (models.User.railway_id == identifier) |
        (models.User.email == identifier)
    ).first()

    if not user or not verify_password(creds.password, user.hashed_password):
        record_failed_attempt(identifier)
        raise HTTPException(status_code=401, detail="Invalid username or password. Please try again.")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="User account is deactivated. Please contact an administrator.")

    # Reset failed attempts upon successful login
    clear_failed_attempts(identifier)

    # Update last login timestamp
    user.last_login = datetime.utcnow()
    # Seamlessly upgrade legacy SHA-256 hash to bcrypt if needed
    if not user.hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
        user.hashed_password = hash_password(creds.password)
    db.commit()
    db.refresh(user)

    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "email": user.email,
        "role": user.role
    })
    return {"access_token": token, "token_type": "bearer", "user": user}

# ----------------- FIREBASE PHONE OTP AUTHENTICATION -----------------

@app.post("/api/auth/request-phone-verification", response_model=schemas.PhoneVerificationResponse)
def request_phone_verification(req: schemas.PhoneVerificationRequest, request: Request, db: Session = Depends(get_db)):
    """
    Initiate Firebase Phone Authentication workflow:
    1. Officer enters 12-digit Railway ID.
    2. FastAPI validates Railway ID format and verifies against officer registry.
    3. Verifies account is active and holds Controller or Admin clearance.
    4. Retrieves registered trusted phone number from DB.
    5. Returns single-use session challenge and masked phone for client Firebase auth.
    """
    import re
    railway_id = (req.railway_id or "").strip()
    if not re.fullmatch(r"^\d{12}$", railway_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please enter a valid 12-digit Railway ID (numeric only)."
        )

    # Rate limiting protection against SMS abuse
    client_ip = request.client.host if request.client else "unknown"
    rate_limited, wait_sec = is_phone_request_rate_limited(f"{client_ip}:{railway_id}")
    if rate_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many verification requests. Please wait {wait_sec} seconds before trying again."
        )
    record_phone_request_attempt(f"{client_ip}:{railway_id}")

    # Query officer by 12-digit Railway ID
    officer = db.query(models.User).filter(models.User.railway_id == railway_id).first()
    if not officer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Official Railway ID not found in authorized personnel registry."
        )

    if not officer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Officer account is currently deactivated. Please contact Division IT."
        )

    officer_role = (officer.role or "").strip().lower()
    if officer_role not in ["controller", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Railway ID belongs to an unauthorized role (Passenger). Control Room access is restricted to Controllers and DRM Admins."
        )

    # Check registered phone number
    raw_phone = officer.phone_number
    if not raw_phone:
        # Default fallback to configured official number
        default_phone = os.getenv("CONTROLLER_PHONE_NUMBER", "+919876543210")
        officer.phone_number = default_phone
        db.commit()
        db.refresh(officer)
        raw_phone = officer.phone_number

    phone = normalize_phone_number(raw_phone)
    masked = mask_phone_number(phone)

    # Create secure single-use session challenge (10-minute TTL)
    session_id = create_phone_verification_session(railway_id, phone, officer.id)

    return schemas.PhoneVerificationResponse(
        session_id=session_id,
        railway_id=officer.railway_id or railway_id,
        masked_phone=masked,
        phone_number=phone,
        officer_name=officer.full_name,
        role=officer.role,
        expires_in=600
    )


@app.post("/api/auth/verify-firebase-session", response_model=schemas.TokenOut)
def verify_firebase_session(req: schemas.FirebaseSessionVerifyRequest, response: Response, db: Session = Depends(get_db)):
    """
    Validate Firebase ID Token and finalize authenticated Control Room session:
    1. Consumes single-use session challenge (anti-replay).
    2. Verifies ID token with Firebase Admin SDK.
    3. Matches verified Firebase phone number strictly against officer DB record.
    4. Validates officer clearance (Controller or Admin).
    5. Sets secure HttpOnly application session cookie and issues JWT access token.
    """
    railway_id = (req.railway_id or "").strip()
    session_id = (req.session_id or "").strip()
    id_token = (req.id_token or "").strip()

    if not railway_id or not session_id or not id_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="id_token, session_id, and railway_id are required."
        )

    # 1. Consume session challenge (prevents replay attacks)
    session_data = consume_phone_verification_session(session_id, railway_id)
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification challenge expired or invalid. Please request a new verification code."
        )

    # 2. Verify Firebase ID Token via Firebase Admin SDK
    try:
        decoded_token = verify_firebase_id_token(id_token)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Firebase verification failed: {ve}"
        )

    firebase_phone = normalize_phone_number(decoded_token.get("phone_number", ""))
    firebase_uid = decoded_token.get("uid")

    if not firebase_phone:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token does not contain a verified phone number."
        )

    # 3. Lookup officer record in trusted database
    officer = db.query(models.User).filter(models.User.railway_id == railway_id).first()
    if not officer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authorized officer record not found."
        )

    # 4. Strict phone number matching
    expected_phone = normalize_phone_number(officer.phone_number or "")
    if firebase_phone != expected_phone:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Security violation: Verified phone number ({firebase_phone}) does not match the registered official mobile number on file."
        )

    # 5. Verify role clearance
    officer_role = (officer.role or "").strip().lower()
    if officer_role not in ["controller", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Officer account does not have Controller clearance."
        )

    # 6. Update officer record with Firebase UID and last login
    officer.firebase_uid = firebase_uid
    officer.last_login = datetime.utcnow()
    db.commit()
    db.refresh(officer)

    # 7. Generate application JWT access token
    token = create_access_token({
        "sub": str(officer.id),
        "username": officer.username,
        "railway_id": officer.railway_id,
        "email": officer.email,
        "role": officer.role,
        "phone_number": officer.phone_number
    })

    # 8. Set secure HttpOnly application session cookie
    set_session_cookie(response, token)

    return {"access_token": token, "token_type": "bearer", "user": officer}


@app.post("/auth/logout")
@app.post("/api/auth/logout")
def logout(response: Response, user: Optional[models.User] = Depends(get_current_user)):
    if response:
        clear_session_cookie(response)
    return {"status": "success", "message": "Logged out successfully."}

@app.get("/auth/me", response_model=schemas.UserOut)
@app.get("/api/auth/me", response_model=schemas.UserOut)
def get_me(user: models.User = Depends(require_current_user)):
    return user

# ----------------- STATIONS & TRAINS (PUBLIC) -----------------
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

    # Resolve Station Entities
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

    # Find matching trains in correct sequence order
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

# ----------------- TELEMETRY INGESTION (PUBLIC/IOT) -----------------
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

    # Dynamic Recalculation
    preds = calculate_dynamic_eta(db, train, state)

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
            if idx % 15 == 0:
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

# ----------------- PROTECTED CONTROLLER SIMULATION TOOLS -----------------
@app.post("/api/telemetry/simulate-step/{train_id}")
async def simulate_step(
    train_id: int,
    delay_delta: int = 2,
    speed: float = 75.0,
    user: models.User = Depends(require_controller_user),
    db: Session = Depends(get_db)
):
    train = db.query(models.Train).filter(models.Train.id == train_id).first()
    if not train or not train.live_state:
        raise HTTPException(status_code=404, detail="Train or live state not found")

    train.live_state.latitude += 0.04
    train.live_state.longitude -= 0.02
    train.live_state.current_delay_min = max(0, train.live_state.current_delay_min + delay_delta)
    train.live_state.speed_kmh = speed
    train.live_state.remaining_distance_km = max(10.0, train.live_state.remaining_distance_km - 8.0)
    train.live_state.last_updated = datetime.utcnow()

    db.commit()

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

@app.post("/api/telemetry/apply-history-point/{train_number}")
async def apply_history_point(
    train_number: str,
    point_idx: int = 0,
    user: models.User = Depends(require_controller_user),
    db: Session = Depends(get_db)
):
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

# ----------------- SAVED TRAINS (MY TRAINS - REQUIRES AUTH) -----------------
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

# ----------------- FIELD OBSERVATIONS (PROTECTED CONTROLLER API) -----------------
@app.get("/api/field-observations", response_model=List[schemas.FieldObservationOut])
def get_field_observations(limit: int = 10, db: Session = Depends(get_db)):
    """Public read-only field observation highlights for track visualization."""
    return db.query(models.FieldObservation).order_by(models.FieldObservation.reported_at.desc()).limit(limit).all()

@app.post("/api/field-observations", response_model=schemas.FieldObservationOut)
def create_field_observation(
    obs_in: schemas.FieldObservationCreate,
    user: models.User = Depends(require_controller_user),
    db: Session = Depends(get_db)
):
    """Restricted to Controller or Admin accounts."""
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

# ----------------- LIVE WEATHER API (PUBLIC) -----------------
@app.get("/api/weather")
def get_weather_data(lat: float = 28.6427, lon: float = 77.2195, location: Optional[str] = None):
    return weather_service.get_live_weather(lat, lon, location)

# ----------------- CONTROL ROOM OVERVIEW (PROTECTED CONTROLLER API) -----------------
@app.get("/api/control-room/overview")
def get_control_room_overview(
    user: models.User = Depends(require_controller_user),
    db: Session = Depends(get_db)
):
    """Restricted to authorized Controller or Admin personnel."""
    trains = db.query(models.Train).filter(models.Train.is_active == True).all()
    observations = db.query(models.FieldObservation).all()
    
    active_trains_summary = []
    total_delayed = 0
    high_propagation_risks = 0

    for t in trains:
        delay = t.live_state.current_delay_min if t.live_state else 0
        if delay > 5:
            total_delayed += 1
        
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
        "controller": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role
        },
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
    """Public passenger live train updates."""
    await manager.connect_train(websocket, train_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect_train(websocket, train_id)

@app.websocket("/ws/control-room")
async def websocket_control_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Protected Control Room real-time WebSocket. Rejects unauthorized connections."""
    cookie_token = websocket.cookies.get("rn_session")
    auth_token = token or cookie_token
    user = verify_ws_token(auth_token, db, required_roles=["controller", "admin"])
    if not user:
        # Reject unauthenticated or non-controller connection
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized or Forbidden")
        return

    await manager.connect_control(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect_control(websocket)

# ----------------- FRONTEND STATIC MOUNT -----------------
import os
from starlette.staticfiles import StaticFiles

frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    import socket

    def is_port_available(h, p):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((h, p))
                return True
            except OSError:
                return False

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    if not is_port_available(host, port):
        print(f"[Rail Nirdeshak] Port {port} is busy or restricted on this machine.")
        for fallback_port in [8001, 8080, 5000, 8888]:
            if is_port_available(host, fallback_port):
                print(f"[Rail Nirdeshak] Automatically switching to available port {fallback_port}!")
                port = fallback_port
                break

    print(f"[Rail Nirdeshak] Launching on http://localhost:{port} (bound to {host}:{port})")
    uvicorn.run(app, host=host, port=port)
