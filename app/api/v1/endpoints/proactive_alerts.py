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

# Test endpoint
@router.get("/proactive_alerts/test")
async def test_proactive_alerts(_=Depends(verify_token)):
    return {"status": "OK"}

# For sending push notifications via Pushover
def send_push_notification(title: str, message: str):
    try:
        response = httpx.post(
            f"https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user": PUSHOVER_API_KEY,
                "title": title,
                "message": message,
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Failed to send push notification: {exc}")

# For sending email notifications via SuprSend
def send_email_notification(subject: str, message: str):
    try:
        # Suprsend API endpoint and auth
        supr_send_url = "https://api.suprsend.com/notifications"
        auth = (SUPRSEND_API_KEY, SUPRSEND_API_SECRET)

        # Prepare notification
        notification = {
            "notification": {
                "title": subject,
                "message": message,
            },
            "recipients": ["matthew"],  # Assuming Matthew's email or identifier
        }

        response = httpx.post(supr_send_url, auth=auth, json=notification)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Failed to send email notification: {exc}")

# Endpoint to trigger a notification (example)
class NotificationRequest(BaseModel):
    subject: str
    message: str

@router.post("/proactive_alerts/send-notification")
async def send_notification(notification: NotificationRequest, _=Depends(verify_token)):
    send_push_notification(notification.subject, notification.message)
    send_email_notification(notification.subject, notification.message)
    return {"status": "Notification sent"}

# Monitoring endpoint - example for checking new emails
@router.get("/proactive_alerts/monitor-emails")
async def monitor_emails(_=Depends(verify_token)):
    try:
        # Establish a database connection (as per your requirement)
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        
        # Your logic to monitor emails and trigger notifications goes here
        # For demonstration, assume we're checking a specific condition
        cur.execute("SELECT * FROM emails WHERE status = 'new'")
        new_emails = cur.fetchall()
        
        for email in new_emails:
            # Trigger a notification
            send_push_notification("New Email", f"You have a new email: {email[1]}")
            send_email_notification("New Email", f"You have a new email: {email[1]}")
        
        conn.close()
        return {"status": "Emails monitored and notifications sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))