from fastapi import APIRouter, Depends, HTTPException
from app.core.security import verify_token
import psycopg2
import os
import httpx
from pydantic import BaseModel

router = APIRouter()

# Assuming these are set in your environment variables
SUPRSEND_API_KEY = os.environ.get("SUPRSEND_API_KEY", "")
SUPRSEND_API_SECRET = os.environ.get("SUPRSEND_API_SECRET", "")
PUSHOVER_API_KEY = os.environ.get("PUSHOVER_API_KEY", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")
EMAILENGINE_API_KEY = os.environ.get("EMAILENGINE_API_KEY", "")
EMAILENGINE_API_SECRET = os.environ.get("EMAILENGINE_API_SECRET", "")

# Connect to DB
def get_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
    return conn

# Suprsend and Pushover notification models
class Notification(BaseModel):
    title: str
    message: str

# Test endpoint
@router.get("/proactive_alerts/test")
async def test_proactive_alerts(_=Depends(verify_token)):
    return {"status": "OK"}

# Endpoint to trigger a notification (example)
@router.post("/proactive_alerts/notify")
async def send_notification(notification: Notification, _=Depends(verify_token)):
    try:
        # Using Suprsend for email notifications
        suprsend_url = "https://api.suprsend.com/notifications"
        headers = {
            "Authorization": f"Bearer {SUPRSEND_API_KEY}",
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(suprsend_url, headers=headers, json=notification.dict())
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to send notification via Suprsend")

        # Using Pushover for push notifications
        pushover_url = "https://api.pushover.net/1/messages.json"
        pushover_headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        pushover_data = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_API_KEY,
            "title": notification.title,
            "message": notification.message
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(pushover_url, headers=pushover_headers, data=pushover_data)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to send notification via Pushover")

        return {"message": "Notification sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Monitor emails and events (example with EmailEngine)
@router.get("/proactive_alerts/monitor-emails")
async def monitor_emails(_=Depends(verify_token)):
    try:
        emailengine_url = "https://api.emailengine.com/v1/events"
        headers = {
            "Authorization": f"Bearer {EMAILENGINE_API_KEY}",
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(emailengine_url, headers=headers)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to fetch emails via EmailEngine")
            events = response.json()
            # Process events and trigger notifications as needed
            for event in events:
                # Example: Send notification for new email
                notification = Notification(title="New Email", message="You have a new email")
                # Call send_notification endpoint or similar logic here
        return {"message": "Emails monitored"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))