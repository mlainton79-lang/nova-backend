from fastapi import APIRouter, Depends, HTTPException
from app.core.security import verify_token
import httpx
import psycopg2
import os
from pydantic import BaseModel

router = APIRouter()

# Assuming EmailEngine API details
EMAILENGINE_API_KEY = os.environ.get("EMAILENGINE_API_KEY", "")
EMAILENGINE_API_SECRET = os.environ.get("EMAILENGINE_API_SECRET", "")

# Assuming Pushover API details
PUSHOVER_API_KEY = os.environ.get("PUSHOVER_API_KEY", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")

# Database connection
def get_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
    return conn

class ProactiveAlertsConfig(BaseModel):
    emailengine_api_key: str
    emailengine_api_secret: str
    pushover_api_key: str
    pushover_api_token: str

@router.get("/proactive_alerts/test")
async def test_proactive_alerts(_=Depends(verify_token)):
    return {"status": "OK"}

@router.post("/proactive_alerts/config")
async def set_proactive_alerts_config(config: ProactiveAlertsConfig, _=Depends(verify_token)):
    # Save config to DB
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO proactive_alerts_config (emailengine_api_key, emailengine_api_secret, pushover_api_key, pushover_api_token) VALUES (%s, %s, %s, %s)", 
                 (config.emailengine_api_key, config.emailengine_api_secret, config.pushover_api_key, config.pushover_api_token))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Config saved"}

@router.get("/proactive_alerts/events")
async def get_events(_=Depends(verify_token)):
    # Fetch events from EmailEngine
    headers = {
        "Authorization": f"Bearer {EMAILENGINE_API_KEY}",
        "Content-Type": "application/json"
    }
    response = httpx.get(f"https://api.emailengine.com/events?api_key={EMAILENGINE_API_KEY}", headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch events")
    events = response.json()
    return events

@router.post("/proactive_alerts/send-notification")
async def send_notification(event: dict, _=Depends(verify_token)):
    # Send push notification via Pushover
    data = {
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_API_KEY,
        "message": event.get("subject", ""),
        "title": event.get("subject", ""),
    }
    response = httpx.post("https://api.pushover.net/1/messages.json", data=data)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to send notification")
    return {"message": "Notification sent"}

# Monitor emails and events, send push notifications
@router.get("/proactive_alerts/monitor")
async def monitor_emails(_=Depends(verify_token)):
    # Fetch new emails from EmailEngine
    headers = {
        "Authorization": f"Bearer {EMAILENGINE_API_KEY}",
        "Content-Type": "application/json"
    }
    response = httpx.get(f"https://api.emailengine.com/inbox?api_key={EMAILENGINE_API_KEY}", headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch emails")
    emails = response.json()
    for email in emails:
        # Send push notification for new email
        data = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_API_KEY,
            "message": email.get("subject", ""),
            "title": email.get("subject", ""),
        }
        response = httpx.post("https://api.pushover.net/1/messages.json", data=data)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to send notification")
    return {"message": "Emails monitored and notifications sent"}