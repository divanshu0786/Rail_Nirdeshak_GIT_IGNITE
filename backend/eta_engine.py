from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from models import Train, RouteStop, Station, LiveTrainState, FieldObservation, ETAPrediction

def parse_hhmm(time_str: str, base_date: Optional[datetime] = None) -> datetime:
    if not base_date:
        base_date = datetime.utcnow()
    parts = time_str.split(":")
    hours, minutes = int(parts[0]), int(parts[1])
    return base_date.replace(hour=hours, minute=minutes, second=0, microsecond=0)

def format_hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")

def calculate_dynamic_eta(
    db: Session,
    train: Train,
    live_state: LiveTrainState,
    max_upcoming_stations: int = 5
) -> List[ETAPrediction]:
    """
    Dynamic ETA & Delay Prediction Engine:
    ETA = Current Time + Base Travel Time + Signal Delay + Congestion Delay + Weather Delay - Recovery Margin
    Incorporates physical field observations and shared-track propagation risk.
    """
    # 1. Get all route stops ordered by sequence
    stops = db.query(RouteStop).filter(RouteStop.train_id == train.id).order_by(RouteStop.stop_sequence).all()
    if not stops:
        return []

    # 2. Find upcoming stops
    # If next_station is specified, find stops starting from next_station
    upcoming_stops: List[RouteStop] = []
    found_next = False
    
    for stop in stops:
        if live_state.next_station_id and stop.station_id == live_state.next_station_id:
            found_next = True
        if found_next:
            upcoming_stops.append(stop)
    
    # Fallback if next_station_id wasn't set or reached end
    if not upcoming_stops:
        upcoming_stops = stops[1:max_upcoming_stations + 1]
    else:
        upcoming_stops = upcoming_stops[:max_upcoming_stations]

    # 3. Check for active field observations along track section
    active_obs = db.query(FieldObservation).filter(
        (FieldObservation.track_section == live_state.track_section) |
        (FieldObservation.station_id.in_([s.station_id for s in upcoming_stops]))
    ).all()
    
    field_obs_delay = sum(obs.impact_delay_min for obs in active_obs)

    # 4. Check shared-track propagation risk with preceding/following trains
    other_trains_on_section = db.query(LiveTrainState).filter(
        LiveTrainState.track_section == live_state.track_section,
        LiveTrainState.train_id != train.id
    ).all()

    shared_track_delayed = any(t.current_delay_min >= 10 for t in other_trains_on_section)
    propagation_risk = "HIGH" if (shared_track_delayed or live_state.current_delay_min >= 15) else (
        "MODERATE" if (live_state.current_delay_min >= 8 or len(active_obs) > 0) else "LOW"
    )

    # 5. Clear old predictions for this train
    db.query(ETAPrediction).filter(ETAPrediction.train_id == train.id).delete()

    predictions = []
    cumulative_delay = live_state.current_delay_min
    now = datetime.utcnow()

    for idx, stop in enumerate(upcoming_stops):
        station = db.query(Station).filter(Station.id == stop.station_id).first()
        if not station or not stop.scheduled_arrival:
            continue

        # Distance factor to this upcoming stop from current position
        dist_factor = max(1.0, (stop.distance_from_source_km - (live_state.remaining_distance_km if live_state.remaining_distance_km > 0 else 0)) / 40.0)
        
        # Explainable Delay Contributors
        # Signal Delay
        signal_delay = max(0, int(3 + (field_obs_delay * 0.4) if "SIGNAL" in str(active_obs) else 2))
        
        # Congestion Delay based on speed and track density
        speed_deficit = max(0.0, 90.0 - live_state.speed_kmh)
        congestion_delay = int(round(min(12, (speed_deficit / 10.0) + (4 if shared_track_delayed else 1))))
        
        # Weather impact
        weather_delay = 4 if live_state.weather_condition == "FOG" else (2 if live_state.weather_condition == "RAIN" else 0)
        
        # Recovery Buffer (Express trains have scheduled padding to recover delay over distance)
        recovery_margin = min(cumulative_delay, int(round(1.5 * (idx + 1))))

        # Recalculate evolving delay
        step_delay = cumulative_delay + signal_delay + congestion_delay + weather_delay - recovery_margin
        predicted_delay = max(0, step_delay)
        cumulative_delay = predicted_delay # Carries over to next station

        # Calculate Predicted Time
        scheduled_dt = parse_hhmm(stop.scheduled_arrival, now)
        predicted_dt = scheduled_dt + timedelta(minutes=predicted_delay)
        predicted_arrival_str = format_hhmm(predicted_dt)

        # Generate explainable delay summary
        reasons = []
        if signal_delay > 0:
            reasons.append(f"Signal ({signal_delay}m)")
        if congestion_delay > 0:
            reasons.append(f"Congestion ({congestion_delay}m)")
        if weather_delay > 0:
            reasons.append(f"Weather ({weather_delay}m)")
        if recovery_margin > 0:
            reasons.append(f"Recovery buffer (-{recovery_margin}m)")
        
        reason_summary = " + ".join(reasons) if reasons else "On-time corridor clearance"

        pred = ETAPrediction(
            train_id=train.id,
            station_id=stop.station_id,
            scheduled_arrival=stop.scheduled_arrival,
            predicted_arrival=predicted_arrival_str,
            predicted_delay_min=predicted_delay,
            signal_delay_min=signal_delay,
            congestion_delay_min=congestion_delay,
            weather_delay_min=weather_delay,
            recovery_min=recovery_margin,
            propagation_risk=propagation_risk,
            reason_summary=reason_summary,
            calculated_at=now
        )
        db.add(pred)
        predictions.append(pred)

    db.commit()
    return predictions
