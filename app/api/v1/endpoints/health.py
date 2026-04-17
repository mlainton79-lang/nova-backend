from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0", "service": "Nova Backend"}

@router.get("/health/db")
def health_db():
    try:
        from app.core.gmail_service import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT name, default_version FROM pg_available_extensions WHERE name = 'vector'")
        pgvector_available = cur.fetchone()
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        pgvector_installed = cur.fetchone()
        cur.execute("SELECT version()")
        pg_version = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {
            "db": "ok",
            "pg_version": pg_version,
            "pgvector_available": pgvector_available is not None,
            "pgvector_installed": pgvector_installed is not None
        }
    except Exception as e:
        return {"db": "error", "error": str(e)}
