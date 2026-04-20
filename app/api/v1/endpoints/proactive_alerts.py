from fastapi import APIRouter, Depends, HTTPException
from app.core.security import verify_token
import psycopg2
import os
import httpx
from pydantic import BaseModel

router = APIRouter()

# Assuming Email API and PushOver API are used for sending notifications
class Notification(BaseModel):
    subject: str
    message: str

@router.get("/proactive_alerts/test")
async def test_proactive_alerts(_=Depends(verify_token)):
    return {"status": "OK"}

@router.post("/proactive_alerts/trigger")
async def trigger_proactive_alerts(notification: Notification, _=Depends(verify_token)):
    try:
        # Connect to DB to potentially fetch more data or log the notification
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        # Example: cur.execute("INSERT INTO notifications (subject, message) VALUES (%s, %s)", (notification.subject, notification.message))
        # For simplicity, this example skips actual DB operations
        conn.close()
        
        # Send push notification using Pushover API
        pushover_api_key = os.environ.get("PUSHOVER_API_KEY", "")
        pushover_api_token = os.environ.get("PUSHOVER_API_TOKEN", "")
        if pushover_api_key and pushover_api_token:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.pushover.net/1/messages.json",
                    data={
                        "token": pushover_api_token,
                        "user": pushover_api_key,
                        "message": notification.message,
                    },
                )
                if response.status_code != 200:
                    raise HTTPException(status_code=500, detail="Failed to send push notification")
        else:
            raise HTTPException(status_code=500, detail="PUSHOVER_API_KEY or PUSHOVER_API_TOKEN is missing")
        
        # Send email notification using Email API (for simplicity, let's assume a basic email API)
        email_api_key = os.environ.get("EMAIL_API_KEY", "")
        if email_api_key:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://example.com/email-api/send",
                    headers={"Authorization": f"Bearer {email_api_key}"},
                    json={"subject": notification.subject, "message": notification.message},
                )
                if response.status_code != 200:
                    raise HTTPException(status_code=500, detail="Failed to send email notification")
        else:
            raise HTTPException(status_code=500, detail="EMAIL_API_KEY is missing")
        
        return {"message": "Notification sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))