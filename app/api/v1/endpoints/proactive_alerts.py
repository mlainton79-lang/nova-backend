from fastapi import APIRouter, Depends, HTTPException
from app.core.security import verify_token
import os
import psycopg2
import httpx
from pydantic import BaseModel

# Assuming Email API and Push API keys are set as environment variables
PUSH_API_KEY = os.environ.get("KEY_PUSHPRO", "")
EMAIL_API_KEY = os.environ.get("KEY_EMAILAPI", "")

# Database connection
conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
cur = conn.cursor()

router = APIRouter()

class EmailNotification(BaseModel):
    subject: str
    body: str

class ProactiveAlertsStatus(BaseModel):
    status: str

@router.get("/proactive_alerts/test")
async def test_proactive_alerts(_=Depends(verify_token)):
    return {"status": "OK"}

@router.post("/proactive_alerts/email")
async def send_email_notification(email_notification: EmailNotification, _=Depends(verify_token)):
    try:
        # Assuming a simple email sending mechanism via httpx for demonstration
        # Replace with actual email API (e.g., EmailEngine) integration
        response = httpx.post(
            f"https://api.emailengine.com/v1/send",
            headers={"Authorization": f"Bearer {EMAIL_API_KEY}"},
            json={"subject": email_notification.subject, "body": email_notification.body},
        )
        response.raise_for_status()
        return {"message": "Email sent successfully"}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=500, detail="Failed to send email") from exc

@router.post("/proactive_alerts/push")
async def send_push_notification(notification: str, _=Depends(verify_token)):
    try:
        # Pushover API example
        response = httpx.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSH_API_KEY,
                "user": "Matthew's User Key",  # Replace with actual user key
                "message": notification,
            },
        )
        response.raise_for_status()
        return {"message": "Push notification sent successfully"}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=500, detail="Failed to send push notification") from exc

@router.get("/proactive_alerts/events")
async def monitor_events(_=Depends(verify_token)):
    try:
        # Fetch new events or emails from database or external API
        cur.execute("SELECT * FROM events WHERE processed = FALSE")
        events = cur.fetchall()
        for event in events:
            # Process event (e.g., send push notification or email)
            # For demonstration, assume sending a push notification
            yield send_push_notification("New event detected").json()
        return {"message": "Events processed"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to process events") from exc