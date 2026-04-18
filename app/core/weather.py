"""
Tony's Weather Awareness.
Uses Open-Meteo API - completely free, no API key needed.
Tony knows the weather and uses it proactively.
"""
import httpx
from datetime import datetime

# Matthew's location - Rotherham
LAT = 53.4326
LON = -1.3635
LOCATION = "Rotherham"

async def get_weather() -> dict:
    """Get current weather and today's forecast for Rotherham."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": LAT,
                    "longitude": LON,
                    "current": "temperature_2m,weathercode,windspeed_10m,precipitation",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                    "timezone": "Europe/London",
                    "forecast_days": 3
                }
            )
            r.raise_for_status()
            data = r.json()

            current = data.get("current", {})
            daily = data.get("daily", {})

            def weather_desc(code):
                codes = {
                    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
                    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle",
                    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
                    71: "light snow", 73: "snow", 75: "heavy snow", 80: "showers",
                    81: "heavy showers", 82: "violent showers", 95: "thunderstorm",
                }
                return codes.get(code, "unknown")

            temp = current.get("temperature_2m", "?")
            code = current.get("weathercode", 0)
            wind = current.get("windspeed_10m", 0)
            rain = current.get("precipitation", 0)

            today_max = daily.get("temperature_2m_max", [None])[0]
            today_min = daily.get("temperature_2m_min", [None])[0]
            today_rain = daily.get("precipitation_sum", [None])[0]

            return {
                "location": LOCATION,
                "current_temp": temp,
                "condition": weather_desc(code),
                "wind_kmh": wind,
                "precipitation_mm": rain,
                "today_max": today_max,
                "today_min": today_min,
                "today_rain_total": today_rain,
                "summary": f"{LOCATION}: {temp}°C, {weather_desc(code)}. High {today_max}°C, Low {today_min}°C. Rain: {today_rain}mm today.",
                "advice": _get_advice(temp, code, wind, today_rain)
            }
    except Exception as e:
        return {"error": str(e), "summary": "Weather unavailable"}


def _get_advice(temp, code, wind, rain):
    """Tony's practical weather advice."""
    tips = []
    if rain and float(rain) > 2:
        tips.append("Take a coat — it's going to rain")
    if temp and float(temp) < 5:
        tips.append("It's cold today — wrap up")
    if wind and float(wind) > 40:
        tips.append("Strong winds — be careful driving")
    if code in [61, 63, 65, 80, 81, 82]:
        tips.append("Wet weather — allow extra travel time")
    return ". ".join(tips) if tips else "No weather warnings today"


async def get_weather_summary() -> str:
    """Brief weather summary for system prompt injection."""
    w = await get_weather()
    if "error" in w:
        return ""
    return f"[WEATHER — {w['summary']} {w['advice']}]"
