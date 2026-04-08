from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0", "service": "Nova Backend"}
