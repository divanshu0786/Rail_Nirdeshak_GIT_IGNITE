import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="passenger") # "passenger" or "controller"
    created_at = Column(DateTime, default=datetime.utcnow)

    saved_trains = relationship("SavedTrain", back_populates="user", cascade="all, delete-orphan")


class Station(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    zone = Column(String, default="NR")
    division = Column(String, default="DLI")

    route_stops = relationship("RouteStop", back_populates="station")


class Train(Base):
    __tablename__ = "trains"

    id = Column(Integer, primary_key=True, index=True)
    train_number = Column(String, unique=True, index=True, nullable=False)
    train_name = Column(String, nullable=False)
    train_type = Column(String, default="Express") # Superfast, Shatabdi, Express
    source = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    total_distance_km = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)

    route_stops = relationship("RouteStop", back_populates="train", order_by="RouteStop.stop_sequence")
    live_state = relationship("LiveTrainState", back_populates="train", uselist=False)
    predictions = relationship("ETAPrediction", back_populates="train")


class RouteStop(Base):
    __tablename__ = "route_stops"

    id = Column(Integer, primary_key=True, index=True)
    train_id = Column(Integer, ForeignKey("trains.id"), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    stop_sequence = Column(Integer, nullable=False)
    scheduled_arrival = Column(String, nullable=True) # "HH:MM"
    scheduled_departure = Column(String, nullable=True) # "HH:MM"
    distance_from_source_km = Column(Float, default=0.0)
    halt_minutes = Column(Integer, default=2)
    platform = Column(String, default="1")

    train = relationship("Train", back_populates="route_stops")
    station = relationship("Station", back_populates="route_stops")


class LiveTrainState(Base):
    __tablename__ = "live_train_states"

    id = Column(Integer, primary_key=True, index=True)
    train_id = Column(Integer, ForeignKey("trains.id"), unique=True, nullable=False)
    current_station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)
    next_station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    speed_kmh = Column(Float, default=0.0)
    current_delay_min = Column(Integer, default=0)
    remaining_distance_km = Column(Float, default=0.0)
    status = Column(String, default="RUNNING") # RUNNING, HALTED, ARRIVED
    track_section = Column(String, default="NDLS-PNP-LINE1")
    reference_pole = Column(String, default="KM 42/18")
    weather_condition = Column(String, default="CLEAR") # CLEAR, FOG, RAIN
    last_updated = Column(DateTime, default=datetime.utcnow)

    train = relationship("Train", back_populates="live_state")
    current_station = relationship("Station", foreign_keys=[current_station_id])
    next_station = relationship("Station", foreign_keys=[next_station_id])


class FieldObservation(Base):
    __tablename__ = "field_observations"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)
    track_section = Column(String, nullable=False)
    pole_reference = Column(String, nullable=True)
    observation_type = Column(String, nullable=False) # SIGNAL_MAINTENANCE, SPEED_RESTRICTION, CONGESTION, WEATHER
    description = Column(Text, nullable=False)
    impact_delay_min = Column(Integer, default=5)
    severity = Column(String, default="MEDIUM") # LOW, MEDIUM, HIGH
    reported_at = Column(DateTime, default=datetime.utcnow)

    station = relationship("Station")


class ETAPrediction(Base):
    __tablename__ = "eta_predictions"

    id = Column(Integer, primary_key=True, index=True)
    train_id = Column(Integer, ForeignKey("trains.id"), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    predicted_arrival = Column(String, nullable=False) # "HH:MM"
    scheduled_arrival = Column(String, nullable=False)
    predicted_delay_min = Column(Integer, default=0)
    signal_delay_min = Column(Integer, default=0)
    congestion_delay_min = Column(Integer, default=0)
    weather_delay_min = Column(Integer, default=0)
    recovery_min = Column(Integer, default=0)
    propagation_risk = Column(String, default="LOW") # LOW, MODERATE, HIGH
    reason_summary = Column(String, nullable=False)
    calculated_at = Column(DateTime, default=datetime.utcnow)

    train = relationship("Train", back_populates="predictions")
    station = relationship("Station")


class SavedTrain(Base):
    __tablename__ = "saved_trains"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    train_id = Column(Integer, ForeignKey("trains.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="saved_trains")
    train = relationship("Train")
