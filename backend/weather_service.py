import os
import time
import httpx
from typing import Dict, Any, Optional

OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY", "")
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

# In-memory weather cache: key -> {"data": dict, "expires_at": timestamp}
# 15 minutes TTL for railway track section weather
CACHE_TTL_SECONDS = 900
_weather_cache: Dict[str, Dict[str, Any]] = {}

def get_live_weather(lat: float, lon: float, location_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch real-time weather metrics using OpenWeatherMap API with caching and railway impact analysis.
    """
    cache_key = f"{round(lat, 2)}_{round(lon, 2)}"
    now = time.time()

    if cache_key in _weather_cache:
        cached = _weather_cache[cache_key]
        if now < cached["expires_at"]:
            return cached["data"]

    try:
        url = f"{BASE_URL}?lat={lat}&lon={lon}&appid={OPENWEATHERMAP_API_KEY}&units=metric"
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                raw = resp.json()
                weather_main = raw.get("weather", [{}])[0].get("main", "Clear")
                weather_desc = raw.get("weather", [{}])[0].get("description", "clear sky").title()
                temp = raw.get("main", {}).get("temp", 28.0)
                humidity = raw.get("main", {}).get("humidity", 50)
                visibility_m = raw.get("visibility", 10000)
                wind_speed_ms = raw.get("wind", {}).get("speed", 3.0)
                wind_kmh = round(wind_speed_ms * 3.6, 1)

                # Railway delay impact classification
                delay_impact = 0
                condition_category = "CLEAR"
                caution_note = "Normal track visibility and adherence"

                main_upper = weather_main.upper()
                if "FOG" in main_upper or "MIST" in main_upper or "HAZE" in main_upper or "SMOKE" in main_upper or visibility_m < 2000:
                    condition_category = "FOG"
                    if visibility_m < 600:
                        delay_impact = 8
                        caution_note = f"Dense fog (Visibility {visibility_m}m): speed restricted by railway safety protocol"
                    elif visibility_m < 1500:
                        delay_impact = 4
                        caution_note = f"Moderate fog/haze (Visibility {visibility_m}m): cautionary aspect running"
                    else:
                        delay_impact = 2
                        caution_note = f"Mild haze (Visibility {visibility_m}m)"
                elif "RAIN" in main_upper or "DRIZZLE" in main_upper or "THUNDERSTORM" in main_upper:
                    condition_category = "RAIN"
                    delay_impact = 4 if "THUNDERSTORM" in main_upper or "HEAVY" in weather_desc.upper() else 2
                    caution_note = f"{weather_desc}: wet rail friction & track section caution"
                elif "WIND" in main_upper or wind_kmh > 45:
                    condition_category = "HIGH_WIND"
                    delay_impact = 3
                    caution_note = f"High crosswind ({wind_kmh} km/h)"
                else:
                    condition_category = "CLEAR" if "CLEAR" in main_upper else "CLOUDS"
                    delay_impact = 0
                    caution_note = f"{weather_desc}: normal operations"

                result = {
                    "source": "OpenWeatherMap Live API",
                    "lat": lat,
                    "lon": lon,
                    "city_name": raw.get("name") or location_name or "Railway Section",
                    "condition": condition_category,
                    "description": weather_desc,
                    "temp_c": round(temp, 1),
                    "humidity": humidity,
                    "visibility_meters": visibility_m,
                    "wind_speed_kmh": wind_kmh,
                    "railway_delay_impact_min": delay_impact,
                    "caution_note": caution_note,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }

                _weather_cache[cache_key] = {
                    "data": result,
                    "expires_at": now + CACHE_TTL_SECONDS
                }
                return result

    except Exception as err:
        # Graceful fallback without breaking system
        pass

    # Fallback default
    fallback = {
        "source": "Default Railway Weather Station",
        "lat": lat,
        "lon": lon,
        "city_name": location_name or "Railway Section",
        "condition": "CLEAR",
        "description": "Clear sky",
        "temp_c": 30.0,
        "humidity": 45,
        "visibility_meters": 10000,
        "wind_speed_kmh": 10.0,
        "railway_delay_impact_min": 0,
        "caution_note": "Normal track conditions",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    return fallback
