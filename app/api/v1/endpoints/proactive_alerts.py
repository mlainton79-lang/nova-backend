from fastapi import APIRouter, Depends, HTTPException
from app.core.security import verify_token
import psycopg2
import os
import httpx
from pydantic import BaseModel

router = APIRouter()

# Assuming Email API and PushOver API credentials are set as environment variables
PUSHOVER_API_KEY = os.environ.get("PUSHOVER_API_KEY", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")
EMAIL_API_KEY = os.environ.get("EMAIL_API_KEY", "")
EMAIL_API_SECRET = os.environ.get("EMAIL_API_SECRET", "")

# Connect to DB
def get_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
    return conn

# Define a model for proactive alerts
class ProactiveAlert(BaseModel):
    message: str

# Test endpoint
@router.get("/proactive_alerts/test")
async def test_proactive_alerts(_=Depends(verify_token)):
    return {"status": "OK"}

# Endpoint to send proactive alerts
@router.post("/proactive_alerts")
async def send_proactive_alert(alert: ProactiveAlert, _=Depends(verify_token)):
    try:
        # Assuming a function to send push notifications via PushOver API
        async def send_push_notification(title: str, message: str):
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.pushover.net/1/messages.json",
                    data={
                        "token": PUSHOVER_API_TOKEN,
                        "user": PUSHOVER_API_KEY,
                        "title": title,
                        "message": message,
                    },
                )
                if response.status_code != 200:
                    raise HTTPException(status_code=500, detail="Failed to send push notification")

        # Assuming a function to monitor emails and trigger alerts
        async def monitor_emails():
            # Implement email monitoring logic here, e.g., using EmailEngine API
            # For demonstration purposes, assume an email is monitored and an alert is triggered
            alert_message = "New email received!"
            await send_push_notification("Proactive Alert", alert_message)

        await monitor_emails()
        return {"message": "Proactive alert sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))