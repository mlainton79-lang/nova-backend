import psycopg2
import os
from datetime import datetime

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")

def init_log_table():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS request_logs (
                id SERIAL PRIMARY KEY,
                provider TEXT,
                message TEXT,
                reply TEXT,
                latency_ms INTEGER,
                ok BOOLEAN,
                error TEXT,
                deciding_brain TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LOGGER] init failed: {e}")

def log_request(provider, message, reply="", latency_ms=None, ok=True, error=None, deciding_brain=None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO request_logs (provider, message, reply, latency_ms, ok, error, deciding_brain) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (provider, message[:500], reply[:500], latency_ms, ok, error, deciding_brain)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LOGGER] log failed: {e}")
