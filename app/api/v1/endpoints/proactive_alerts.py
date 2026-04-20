from fastapi import APIRouter, Depends, HTTPException
from app.core.security import verify_token
import psycopg2
import os
import httpx
from pydantic import BaseModel

router = APIRouter()

# Assuming Email API and PushOver API are used for sending notifications
class ProactiveAlertsConfig(BaseModel):
    email_api_key: str = os.environ.get("EMAIL_API_KEY", "")
    pushover_api_key: str = os.environ.get("PUSHOVER_API_KEY", "")
    pushover_api_token: str = os.environ.get("PUSHOVER_API_TOKEN", "")

config = ProactiveAlertsConfig()

@router.get("/proactive_alerts/test")
async def test_proactive_alerts(_=Depends(verify_token)):
    return {"status": "OK"}

@router.post("/proactive_alerts/trigger")
async def trigger_proactive_alerts(_=Depends(verify_token)):
    try:
        # Connect to DB
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        
        # Fetch new emails or events (example: fetch emails)
        cur.execute("SELECT * FROM emails WHERE status='new'")
        emails = cur.fetchall()
        
        # Send push notifications
        for email in emails:
            message = f"New email from {email[1]}: {email[2]}"
            response = httpx.post(
                f"https://api.pushover.net/1/messages.json",
                data={
                    "token": config.pushover_api_token,
                    "user": config.pushover_api_key,
                    "message": message,
                },
            )
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to send push notification")
        
        # Update email status to 'notified'
        for email in emails:
            cur.execute("UPDATE emails SET status='notified' WHERE id=%s", (email[0],))
        conn.commit()
        conn.close()
        
        return {"message": "Proactive alerts triggered successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Monitor emails and events in the background (example: every minute)
# This part can be implemented using a scheduler like APScheduler or Celery
# For simplicity, let's assume it's done outside of this file