from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr

# Auth Schemas
class UserRegister(BaseModel):
    email: str
    full_name: str
    password: str
    role: Optional[str] = "passenger"

class UserLogin(BaseModel):
    email: str
    password: str

class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

# Station & Route Schemas
class StationOut(BaseModel):
    id: int
    code: str
    name: str
    latitude: float
    longitude: float
    zone: str
    division: str

    class Config:
        from_attributes = True

class RouteStopOut(BaseModel):
    id: int
    station_id: int
    stop_sequence: int
    scheduled_arrival: Optional[str]
    scheduled_departure: Optional[str]
    distance_from_source_km: float
    halt_minutes: int
    platform: str
    station: StationOut

    class Config:
        from_attributes = True

# Live State & Telemetry Schemas
class LiveStateOut(BaseModel):
    id: int
    train_id: int
    current_station_id: Optional[int]
    next_station_id: Optional[int]
    latitude: float
    longitude: float
    speed_kmh: float
    current_delay_min: int
    remaining_distance_km: float
    status: str
    track_section: str
    reference_pole: Optional[str]
    weather_condition: str
    last_updated: datetime
    current_station: Optional[StationOut] = None
    next_station: Optional[StationOut] = None

    class Config:
        from_attributes = True

class TelemetryInput(BaseModel):
    train_number: str
    latitude: float
    longitude: float
    speed_kmh: float
    current_delay_min: int
    remaining_distance_km: float
    status: Optional[str] = "RUNNING"
    track_section: Optional[str] = "NDLS-PNP-LINE1"
    reference_pole: Optional[str] = "KM 42/18"
    weather_condition: Optional[str] = "CLEAR"

# Prediction Schemas
class ETAPredictionOut(BaseModel):
    id: int
    station_id: int
    station_name: str
    station_code: str
    scheduled_arrival: str
    predicted_arrival: str
    predicted_delay_min: int
    signal_delay_min: int
    congestion_delay_min: int
    weather_delay_min: int
    recovery_min: int
    propagation_risk: str
    reason_summary: str

    class Config:
        from_attributes = True

# Train Schemas
class TrainOut(BaseModel):
    id: int
    train_number: str
    train_name: str
    train_type: str
    source: str
    destination: str
    total_distance_km: float
    is_active: bool

    class Config:
        from_attributes = True

class TrainDetailOut(TrainOut):
    route_stops: List[RouteStopOut] = []
    live_state: Optional[LiveStateOut] = None
    predictions: List[ETAPredictionOut] = []

# Field Observation Schemas
class FieldObservationCreate(BaseModel):
    station_id: Optional[int] = None
    track_section: str
    pole_reference: Optional[str] = None
    observation_type: str
    description: str
    impact_delay_min: int = 5
    severity: Optional[str] = "MEDIUM"

class FieldObservationOut(BaseModel):
    id: int
    station_id: Optional[int]
    track_section: str
    pole_reference: Optional[str]
    observation_type: str
    description: str
    impact_delay_min: int
    severity: str
    reported_at: datetime
    station: Optional[StationOut] = None

    class Config:
        from_attributes = True
